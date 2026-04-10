import json
import hashlib
import re
import base64
import io
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, AsyncGenerator, Optional
from loguru import logger
from PIL import Image


READ_ONLY_TOOLS = {"web_search", "advanced_web_search", "weather"}
WRITE_CAPABLE_TOOLS = {"bash", "str_replace_editor", "computer", "code_sandbox"}
LOCAL_SHELL_HINT_PATTERN = re.compile(
    r"(家目录|home目录|当前目录|工作区|workspace|目录下|文件夹|列出.*文件|看看.*文件|有哪些文件|ls\b|pwd\b|find\b|cat\b|grep\b|bash\b|shell\b|terminal\b|command\b|命令行)",
    re.IGNORECASE,
)
WEATHER_HINT_PATTERN = re.compile(r"(天气|温度|气温|weather|forecast)", re.IGNORECASE)
NEWS_HINT_PATTERN = re.compile(r"(新闻|热点|头条|快讯|news|headline|breaking)", re.IGNORECASE)
FINANCE_HINT_PATTERN = re.compile(r"(股价|股票|汇率|finance|stock|market|price|\$)", re.IGNORECASE)
CODE_HINT_PATTERN = re.compile(r"(代码|文件|测试|修复|修改|实现|重构|run|test|debug|fix|edit|code|repo|workspace)", re.IGNORECASE)
COMPUTER_HINT_PATTERN = re.compile(r"(浏览器|页面|截图|click|open|tab|网页|screen|ui)", re.IGNORECASE)
RUNTIME_CONTEXT_PATTERN = re.compile(
    r"(今天|今日|当天|目前|当前|现在|latest|today|current|recent|weather|forecast|新闻|热点|头条|price|stock|股价|汇率|news)",
    re.IGNORECASE,
)
SIMPLE_GREETING_PATTERN = re.compile(r"^\s*(hi|hello|hey|你好|嗨|在吗)\W*\s*$", re.IGNORECASE)
RAW_TOOL_CALL_MARKERS = ("<minimax:tool_call>", "<invoke ", "<parameter ")
RAW_TOOL_CALL_BLOCK_PATTERN = re.compile(
    r"<minimax:tool_call>\s*(.*?)\s*</minimax:tool_call>",
    re.IGNORECASE | re.DOTALL,
)
RAW_TOOL_INVOKE_PATTERN = re.compile(
    r"<invoke\s+name=\"([^\"]+)\"\s*>(.*?)</invoke>",
    re.IGNORECASE | re.DOTALL,
)
RAW_TOOL_PARAMETER_PATTERN = re.compile(
    r"<parameter\s+name=\"([^\"]+)\"\s*>(.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)
IMAGE_UNAVAILABLE_PATTERN = re.compile(
    r"(没有.*图片|没.*看到.*图片|未.*看到.*图片|看起来图片.*没有成功|don'?t\s+see\s+any\s+image|no\s+image\s+(was\s+)?provided|image.*not.*attached)",
    re.IGNORECASE,
)


class StreamingAgent:
    """
    Streaming agent plus mode-aware execution routing.

    - `agent` mode: native tool-calling loop
    - `plan` mode: create task graph only, no tool execution
    - `review` mode: route through execution engine for structured task transcript
    """

    def __init__(self, vllm_client, skill_manager, execution_engine=None, plan_agent=None):
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.execution_engine = execution_engine
        self.plan_agent = plan_agent
        self.session_context_cache: Dict[str, Dict[str, Any]] = {}

    def _contains_raw_tool_markup(self, raw_text: str) -> bool:
        text = raw_text or ""
        return any(marker in text for marker in RAW_TOOL_CALL_MARKERS)

    def _sanitize_visible_text(self, raw_text: str) -> str:
        text = raw_text or ""
        text = RAW_TOOL_CALL_BLOCK_PATTERN.sub("", text)
        marker_positions = [text.find(marker) for marker in RAW_TOOL_CALL_MARKERS if marker in text]
        if marker_positions:
            text = text[: min(marker_positions)]
        return text

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return "".join(parts)
        return ""

    def _compose_user_message_content(
        self,
        prompt_text: str,
        message_parts: Optional[List[Dict[str, Any]]],
    ) -> Any:
        if not message_parts:
            return prompt_text

        content: List[Dict[str, Any]] = []
        leading_text = prompt_text.strip()
        if leading_text:
            content.append({"type": "text", "text": leading_text})

        for part in message_parts:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "text":
                text_value = str(part.get("text") or "")
                if text_value:
                    content.append({"type": "text", "text": text_value})
            elif part_type == "image":
                data_url = part.get("data_url") or part.get("url")
                if data_url:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    })
        return content or prompt_text

    def _has_image_parts(self, message_parts: Optional[List[Dict[str, Any]]]) -> bool:
        for part in message_parts or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image" and (part.get("data_url") or part.get("url")):
                return True
        return False

    def _iter_inline_images(self, message_parts: Optional[List[Dict[str, Any]]]) -> List[str]:
        images: List[str] = []
        for part in message_parts or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image":
                data_url = part.get("data_url") or part.get("url")
                if isinstance(data_url, str) and data_url.startswith("data:image"):
                    images.append(data_url)
        return images

    def _text_only_message_parts(self, message_parts: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        text_parts: List[Dict[str, Any]] = []
        for part in message_parts or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text_value = str(part.get("text") or "")
                if text_value:
                    text_parts.append({"type": "text", "text": text_value})
        return text_parts

    def _color_name(self, rgb: tuple[int, int, int]) -> str:
        r, g, b = rgb
        if max(rgb) < 40:
            return "黑色"
        if min(rgb) > 220:
            return "白色"
        if abs(r - g) < 18 and abs(g - b) < 18:
            return "灰色"
        if r > 200 and g > 160 and b < 120:
            return "黄色"
        if r > 180 and g < 110 and b < 110:
            return "红色"
        if r > 180 and 100 < g < 180 and b < 120:
            return "橙色"
        if g > 150 and r < 140 and b < 140:
            return "绿色"
        if b > 150 and r < 150 and g < 170:
            return "蓝色"
        if r > 150 and b > 150 and g < 140:
            return "紫色"
        if r > 120 and g > 80 and b < 80:
            return "棕色"
        return "综合色"

    def _extract_ocr_text(self, image: Image.Image) -> str:
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
                image.save(tmp.name)
                result = subprocess.run(
                    ["tesseract", tmp.name, "stdout", "-l", "eng"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                text = (result.stdout or "").strip()
                text = re.sub(r"\s+", " ", text)
                return text[:160]
        except Exception as exc:
            logger.debug(f"OCR extraction skipped: {exc}")
            return ""

    def _analyze_inline_images_locally(self, message_parts: Optional[List[Dict[str, Any]]]) -> str:
        image_data_urls = self._iter_inline_images(message_parts)
        if not image_data_urls:
            return ""

        summaries: List[str] = []
        for index, data_url in enumerate(image_data_urls[:4], start=1):
            try:
                _, encoded = data_url.split(",", 1)
                image_bytes = base64.b64decode(encoded)
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                width, height = image.size

                palette = image.resize((24, 24)).getcolors(24 * 24) or []
                dominant = sorted(palette, key=lambda item: item[0], reverse=True)[:3]
                color_names: List[str] = []
                for _, color in dominant:
                    name = self._color_name(tuple(color))
                    if name not in color_names:
                        color_names.append(name)
                ocr_text = self._extract_ocr_text(image)

                fragments = [
                    f"第{index}张图片尺寸约为 {width}x{height} 像素",
                ]
                if color_names:
                    fragments.append(f"主色调偏{ '、'.join(color_names[:3]) }")
                if ocr_text:
                    fragments.append(f"可识别文字为“{ocr_text}”")
                summaries.append("，".join(fragments) + "。")
            except Exception as exc:
                logger.warning(f"Failed to analyze inline image locally: {exc}")

        if not summaries:
            return ""

        return (
            "我已经读取到你贴进来的图片。基于本地视觉兜底分析，我看到：\n\n- "
            + "\n- ".join(summaries)
            + "\n\n如果你希望，我还可以继续结合你的问题，围绕这些图片做更具体的说明。"
        )

    def _should_use_local_image_fallback(self, answer_text: str) -> bool:
        text = (answer_text or "").strip()
        if not text:
            return True
        return bool(IMAGE_UNAVAILABLE_PATTERN.search(text))

    def _canonical_tool_name(self, tool_name: str) -> str:
        raw_name = (tool_name or "").strip()
        lowered = raw_name.lower()
        if lowered in {"bash", "shell", "terminal", "run_command", "cli-mcp-server_run_command"}:
            return "bash"
        if lowered in {"read", "view", "view_file", "read_file", "open_file"}:
            return "str_replace_editor"
        return raw_name

    def _workspace_relative_path(self, raw_path: str, request_context: Optional[Dict[str, Any]]) -> str:
        path_text = (raw_path or "").strip()
        if not path_text:
            return path_text
        path = Path(path_text).expanduser()
        if not path.is_absolute():
            return path_text

        candidates = []
        if request_context:
            for key in ("workspace_display_path", "workspace_runtime_path"):
                value = request_context.get(key)
                if value:
                    candidates.append(value)
        if self.skill_manager:
            candidates.append(self.skill_manager.get_current_workspace())

        for candidate in candidates:
            try:
                relative = path.relative_to(Path(candidate).expanduser())
                return str(relative) or "."
            except Exception:
                continue
        return path_text

    def _rewrite_command_workspace_paths(self, command: str, request_context: Optional[Dict[str, Any]]) -> str:
        text = command or ""
        if not request_context:
            return text
        display_path = (request_context.get("workspace_display_path") or "").strip()
        runtime_path = (request_context.get("workspace_runtime_path") or "").strip()
        if display_path and runtime_path and display_path != runtime_path:
            text = text.replace(display_path, runtime_path)
        return text

    def _normalize_tool_invocation(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        request_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        canonical_name = self._canonical_tool_name(tool_name)
        normalized_args = dict(tool_args or {})

        if canonical_name == "bash":
            if "cmd" in normalized_args and "command" not in normalized_args:
                normalized_args["command"] = normalized_args.pop("cmd")
            if normalized_args.get("command"):
                normalized_args["command"] = self._rewrite_command_workspace_paths(
                    str(normalized_args["command"]),
                    request_context,
                )

        if canonical_name == "str_replace_editor":
            if "file_path" in normalized_args and "path" not in normalized_args:
                normalized_args["path"] = normalized_args.pop("file_path")
            if "filepath" in normalized_args and "path" not in normalized_args:
                normalized_args["path"] = normalized_args.pop("filepath")
            command_name = normalized_args.get("command") or normalized_args.get("action")
            if not command_name:
                normalized_args["command"] = "view"
            elif str(command_name).lower() in {"read", "view", "view_file", "read_file", "open_file"}:
                normalized_args["command"] = "view"
            if normalized_args.get("path"):
                normalized_args["path"] = self._workspace_relative_path(
                    str(normalized_args["path"]),
                    request_context,
                )

        return {
            "name": canonical_name,
            "arguments": normalized_args,
        }

    def _extract_tool_calls_from_xml_markup(self, raw_text: str) -> List[Dict[str, Any]]:
        text = raw_text or ""
        if not self._contains_raw_tool_markup(text):
            return []

        tool_calls: List[Dict[str, Any]] = []
        for index, match in enumerate(RAW_TOOL_INVOKE_PATTERN.finditer(text), start=1):
            raw_name = match.group(1).strip()
            argument_text = match.group(2) or ""
            params: Dict[str, Any] = {}
            for param_match in RAW_TOOL_PARAMETER_PATTERN.finditer(argument_text):
                param_name = param_match.group(1).strip()
                param_value = (param_match.group(2) or "").strip()
                params[param_name] = param_value
            tool_calls.append({
                "id": f"xml_tool_call_{index}",
                "type": "function",
                "function": {
                    "name": self._canonical_tool_name(raw_name),
                    "arguments": json.dumps(params, ensure_ascii=False),
                },
            })
        return tool_calls

    def _split_thinking_and_answer(self, raw_text: str) -> Dict[str, Any]:
        open_tag = "<think>"
        close_tag = "</think>"
        open_index = raw_text.find(open_tag)

        if open_index == -1:
            return {
                "has_thinking": False,
                "thinking_text": "",
                "answer_text": self._sanitize_visible_text(raw_text),
                "in_thinking": False,
            }

        before_open = raw_text[:open_index]
        after_open = raw_text[open_index + len(open_tag):]
        close_index = after_open.find(close_tag)

        if close_index == -1:
            return {
                "has_thinking": True,
                "thinking_text": self._sanitize_visible_text(after_open),
                "answer_text": self._sanitize_visible_text(before_open),
                "in_thinking": True,
            }

        thinking_text = after_open[:close_index]
        after_close = after_open[close_index + len(close_tag):]
        return {
            "has_thinking": True,
            "thinking_text": self._sanitize_visible_text(thinking_text),
            "answer_text": self._sanitize_visible_text(f"{before_open}{after_close}"),
            "in_thinking": False,
        }

    def _build_stream_deltas(
        self,
        raw_text: str,
        emitted_thinking_len: int,
        emitted_answer_len: int,
    ) -> Dict[str, Any]:
        parsed = self._split_thinking_and_answer(raw_text)
        thinking_text = parsed["thinking_text"]
        answer_text = parsed["answer_text"]

        thinking_delta = ""
        answer_delta = ""

        if len(thinking_text) > emitted_thinking_len:
            thinking_delta = thinking_text[emitted_thinking_len:]

        if len(answer_text) > emitted_answer_len:
            answer_delta = answer_text[emitted_answer_len:]

        return {
            "thinking_text": thinking_text,
            "answer_text": answer_text,
            "thinking_delta": thinking_delta,
            "answer_delta": answer_delta,
            "in_thinking": parsed["in_thinking"],
            "has_thinking": parsed["has_thinking"],
        }

    def _build_tool_fallback_answer(self, messages: List[Dict[str, Any]]) -> str:
        for entry in reversed(messages):
            if entry.get("role") != "tool":
                continue
            content = self._sanitize_visible_text((entry.get("content") or "")).strip()
            tool_name = entry.get("name") or "tool"
            if not content:
                continue
            if content.lower().startswith("error:"):
                return f"工具 `{tool_name}` 执行失败：{content[6:].strip()}"
            return content
        return "工具已经执行，但模型没有返回可显示的最终回答。"

    def _should_include_runtime_context(self, user_message: str) -> bool:
        text = (user_message or "").strip()
        if not text or SIMPLE_GREETING_PATTERN.match(text):
            return False
        return bool(RUNTIME_CONTEXT_PATTERN.search(text))

    def _estimate_context_percent(self, messages: List[Dict[str, Any]]) -> int:
        text_size = sum(len(self._message_content_to_text(item.get("content"))) for item in messages)
        return min(98, max(1, round(text_size / 140) + 4))

    def _emit_context_state(self, session_id: str, messages: List[Dict[str, Any]]) -> str:
        return self._sse({
            "type": "context_state",
            "session_id": session_id,
            "context_percent": self._estimate_context_percent(messages),
        })

    def _conversation_to_turns(self, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        turns: List[Dict[str, str]] = []
        pending_user: Optional[str] = None

        for item in messages:
            role = item.get("role")
            content = self._sanitize_visible_text(self._message_content_to_text(item.get("content"))).strip()
            if not content:
                continue

            if role == "user":
                if pending_user is not None:
                    turns.append({"user": pending_user, "assistant": ""})
                pending_user = content
            elif role == "assistant":
                if pending_user is None:
                    continue
                turns.append({"user": pending_user, "assistant": content})
                pending_user = None

        if pending_user is not None:
            turns.append({"user": pending_user, "assistant": ""})

        return turns

    def _serialize_turns(self, turns: List[Dict[str, str]]) -> str:
        lines: List[str] = []
        for index, turn in enumerate(turns, start=1):
            lines.append(f"Round {index}")
            lines.append(f"User: {turn.get('user', '').strip()}")
            assistant = (turn.get("assistant") or "").strip()
            if assistant:
                lines.append(f"Assistant: {assistant}")
            lines.append("")
        return "\n".join(lines).strip()

    def _signature_for_text(self, content: str) -> str:
        return hashlib.sha256((content or "").encode("utf-8")).hexdigest()

    async def _summarize_context_block(
        self,
        *,
        session_id: str,
        phase: str,
        instructions: str,
        content: str,
        max_tokens: int,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        request_messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": content},
        ]
        yield self._sse_log(session_id, phase, "request", {
            "messages": request_messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "model": model,
        })
        response = await self.vllm_client.chat_completion(
            messages=request_messages,
            temperature=0.2,
            max_tokens=max_tokens,
            stream=False,
            model=model,
        )
        message = {}
        if "choices" in response and response["choices"]:
            message = response["choices"][0].get("message", {}) or {}
        yield self._sse_log(session_id, phase, "response", {
            "message": message,
        })
        yield json.dumps({"content": message.get("content", "") or ""}, ensure_ascii=False)

    def _build_compacted_user_prompt(
        self,
        *,
        current_user_message: str,
        context: str,
        tool_context: str,
        request_context: Dict[str, Any],
        historical_summary: str,
        recent_summary: str,
        skill_index_prompt: Optional[str],
        relevant_skill_instructions: Optional[str],
        tool_guidance: Optional[str],
    ) -> str:
        sections = []
        historical_summary = self._sanitize_visible_text(historical_summary).strip()
        recent_summary = self._sanitize_visible_text(recent_summary).strip()

        if context:
            sections.append(f"[Workspace / tool context]\nTool context: {tool_context}\n{context}")

        runtime_lines = []
        if request_context:
            runtime_lines.extend([
                f"Current date: {request_context.get('current_date') or 'unknown'}",
                f"Current time: {request_context.get('current_time') or 'unknown'}",
                f"Current datetime: {request_context.get('current_datetime') or 'unknown'}",
                f"Timezone: {request_context.get('timezone') or 'unknown'}",
            ])
            if request_context.get("workspace_display_path"):
                runtime_lines.append(f"User-visible workspace path: {request_context.get('workspace_display_path')}")
            if request_context.get("workspace_runtime_path"):
                runtime_lines.append(f"Runtime workspace path: {request_context.get('workspace_runtime_path')}")
            if request_context.get("thread_runtime_dir"):
                runtime_lines.append(
                    "Internal thread runtime directory for intermediate artifacts: "
                    f"{request_context.get('thread_runtime_dir')}"
                )
            location = request_context.get("location") or {}
            loc_parts = [part for part in [location.get("city"), location.get("region"), location.get("country_name")] if part]
            if loc_parts:
                runtime_lines.append(f"Approximate user location: {', '.join(loc_parts)}")
        if runtime_lines:
            sections.append("[Runtime context]\n" + "\n".join(runtime_lines))

        if historical_summary:
            sections.append(f"[Historical context summary]\n{historical_summary}")

        if recent_summary:
            sections.append(f"[Recent {4} rounds summary]\n{recent_summary}")

        if skill_index_prompt:
            sections.append(skill_index_prompt)

        if relevant_skill_instructions:
            sections.append(relevant_skill_instructions)

        if tool_guidance:
            sections.append(f"[Tool selection guidance]\n{tool_guidance}")

        sections.append(
            "[Current user request]\n"
            f"{current_user_message}\n\n"
            "Use the summaries above as context. Do not treat missing older turns as absent; they are already compressed here."
        )

        return "\n\n".join(section for section in sections if section.strip())

    def _sse_log(self, session_id: str, phase: str, direction: str, payload: Dict[str, Any]) -> str:
        return self._sse({
            "type": "llm_log",
            "session_id": session_id,
            "phase": phase,
            "direction": direction,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "payload": payload,
        })

    def _build_readonly_summary_fallback(self, messages: List[Dict[str, Any]]) -> str:
        for entry in reversed(messages):
            if entry.get("role") != "tool":
                continue
            tool_name = entry.get("name") or "tool"
            content = self._sanitize_visible_text((entry.get("content") or "")).strip()
            if not content:
                continue
            if tool_name == "weather":
                return "天气工具已经拿到结果，但模型总结当前不可用。请稍后重试，我会继续通过模型整理后再返回给你。"
            if tool_name in {"advanced_web_search", "web_search"}:
                return "搜索工具已经拿到结果，但模型总结当前不可用。请稍后重试，我会继续通过模型整理后再返回给你。"
            return f"工具 `{tool_name}` 已经执行完成，但模型总结当前不可用。请稍后重试。"
        return self._build_tool_fallback_answer(messages)

    def _build_skill_index_prompt(self, tool_names: List[str]) -> Optional[str]:
        if not self.skill_manager or not tool_names:
            return None

        entries = self.skill_manager.build_skill_index(tool_names)
        if not entries:
            return None

        lines = ["Available skills index (compact metadata only; full instructions are loaded only for relevant skills):"]
        for item in entries:
            name = item.get("name") or item.get("tool_name") or "unknown"
            description = item.get("description") or "No description"
            location = item.get("location") or ""
            line = f"- {name}: {description}"
            if location:
                line += f" [SKILL.md: {location}]"
            lines.append(line)
        return "\n".join(lines)

    def _build_relevant_skill_instructions(self, tool_names: List[str]) -> Optional[str]:
        if not self.skill_manager or not tool_names:
            return None

        sections = []
        seen = set()
        for tool_name in tool_names:
            resolved_name = self.skill_manager.resolve_skill_name_for_tool(tool_name) or tool_name
            if resolved_name in seen:
                continue
            seen.add(resolved_name)
            instructions = self.skill_manager.get_skill_instructions(tool_name)
            if not instructions:
                continue
            compact = instructions.strip()
            if len(compact) > 2200:
                compact = compact[:2200].rstrip() + "\n..."
            sections.append(f"[Skill: {resolved_name}]\n{compact}")

        if not sections:
            return None

        return (
            "Relevant skill instructions loaded on demand for the tools currently eligible to solve this request:\n\n"
            + "\n\n".join(sections)
        )

    async def _stream_final_answer_without_tools(
        self,
        *,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        conversation_history: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
        instruction: str,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        final_messages = [
            *messages,
            {
                "role": "user",
                "content": instruction,
            },
        ]
        yield self._sse_log(session_id, "final_synthesis", "request", {
            "messages": final_messages,
            "temperature": 0.4,
            "max_tokens": 2000,
            "stream": False,
            "model": model,
        })
        raw_content = ""
        synthesis_attempts = 3
        for attempt in range(1, synthesis_attempts + 1):
            try:
                attempt_messages = list(final_messages)
                if attempt > 1:
                    attempt_messages.append({
                        "role": "user",
                        "content": (
                            "Return only the final natural-language answer. "
                            "Do not output any <minimax:tool_call>, <invoke>, <parameter>, XML, or tool invocation markup."
                        ),
                    })
                response = await self.vllm_client.chat_completion(
                    messages=attempt_messages,
                    temperature=0.4,
                    max_tokens=2000,
                    stream=False,
                    model=model,
                )
                if "choices" in response and response["choices"]:
                    raw_content = response["choices"][0].get("message", {}).get("content", "") or ""
                    yield self._sse_log(session_id, "final_synthesis", "response", {
                        "attempt": attempt,
                        "message": response["choices"][0].get("message", {}),
                    })
                if raw_content.strip() and not self._contains_raw_tool_markup(raw_content):
                    break
            except Exception:
                logger.exception(f"Final answer synthesis failed on attempt {attempt}")

        final_parts = self._split_thinking_and_answer(raw_content)
        if final_parts["thinking_text"].strip():
            yield self._sse({
                "type": "thinking_delta",
                "delta": final_parts["thinking_text"],
                "session_id": session_id,
            })

        final_answer = final_parts["answer_text"].strip() or self._build_readonly_summary_fallback(messages)
        if final_answer:
            yield self._sse({
                "type": "answer_delta",
                "delta": final_answer,
                "session_id": session_id,
            })

        conversation_history.append({
            "role": "assistant",
            "content": final_answer,
        })
        chat_sessions[session_id] = conversation_history
        yield self._emit_context_state(session_id, conversation_history)
        yield self._sse({"done": True, "session_id": session_id})

    def _build_direct_shell_command(self, user_message: str) -> Optional[str]:
        text = (user_message or "").strip().lower()
        if not text:
            return None

        if any(token in text for token in ["家目录", "home目录", "home directory", "home folder", "~"]):
            return "ls -la ~"
        if any(token in text for token in ["当前目录", "current directory", "workspace", "工作区", "项目目录", "repo", "repository"]):
            return "ls -la"
        if any(token in text for token in ["有什么文件", "有哪些文件", "列出文件", "看看文件", "目录下"]) and "bash" in WRITE_CAPABLE_TOOLS:
            return "ls -la"
        return None

    def _looks_like_local_shell_request(self, user_message: str, tool_context: str) -> bool:
        text = (user_message or "").strip()
        if not text:
            return False
        if LOCAL_SHELL_HINT_PATTERN.search(text):
            return True
        return tool_context == "workspace" and any(
            token in text.lower()
            for token in ["目录", "文件", "workspace", "repo", "repository", "project"]
        )

    def _select_eligible_tools(
        self,
        tools: List[Dict[str, Any]],
        user_message: str,
        tool_context: str,
    ) -> List[Dict[str, Any]]:
        if not tools:
            return []

        text = (user_message or "").strip()
        if SIMPLE_GREETING_PATTERN.match(text):
            return []

        desired_names: List[str]
        if self._looks_like_local_shell_request(text, tool_context):
            desired_names = ["bash", "str_replace_editor", "computer"]
        elif WEATHER_HINT_PATTERN.search(text):
            desired_names = ["weather", "advanced_web_search", "web_search"]
        elif NEWS_HINT_PATTERN.search(text) or FINANCE_HINT_PATTERN.search(text):
            desired_names = ["advanced_web_search", "web_search"]
        elif tool_context == "computer" or COMPUTER_HINT_PATTERN.search(text):
            desired_names = ["computer", "advanced_web_search"]
        elif CODE_HINT_PATTERN.search(text):
            desired_names = ["bash", "str_replace_editor", "code_sandbox", "advanced_web_search"]
        else:
            desired_names = ["advanced_web_search"]

        desired = set(desired_names)
        filtered = [tool for tool in tools if tool.get("name") in desired]
        return filtered or tools[: min(len(tools), 3)]

    def _prioritize_tools_for_request(
        self,
        tools: List[Dict[str, Any]],
        user_message: str,
        tool_context: str,
    ) -> List[Dict[str, Any]]:
        if not tools:
            return tools

        preferred_names: List[str] = []
        if self._looks_like_local_shell_request(user_message, tool_context):
            preferred_names.extend(["bash", "str_replace_editor", "computer"])
        elif WEATHER_HINT_PATTERN.search(user_message or ""):
            preferred_names.extend(["weather", "advanced_web_search", "web_search"])

        if not preferred_names:
            return tools

        priority = {name: index for index, name in enumerate(preferred_names)}
        return sorted(
            tools,
            key=lambda tool: (priority.get(tool.get("name"), len(priority)), tool.get("name", "")),
        )

    def _build_request_tool_guidance(
        self,
        user_message: str,
        tool_context: str,
        tools: List[Dict[str, Any]],
    ) -> Optional[str]:
        tool_names = {tool.get("name") for tool in tools}
        exact_tool_names = ", ".join(sorted(name for name in tool_names if name))
        exact_name_rule = (
            f"Use only the exact tool names from this list: {exact_tool_names}. "
            "Do not invent aliases such as shell, Read, View, cli-mcp-server_run_command, or XML invocation markup."
            if exact_tool_names
            else None
        )
        if self._looks_like_local_shell_request(user_message, tool_context) and "bash" in tool_names:
            guidance = (
                "This is a local machine or workspace request. You can directly inspect local files and directories "
                "with the bash tool. Prefer bash for listing files, reading directories, pwd, ls, find, cat, and grep. "
                "Do not use web search for local filesystem questions, and do not claim you lack file access when bash is available."
            )
            if exact_name_rule:
                guidance += " " + exact_name_rule
            return guidance
        if WEATHER_HINT_PATTERN.search(user_message or "") and "weather" in tool_names:
            guidance = (
                "This appears to be a weather or temperature question. Prefer the weather tool first. "
                "Only use search if the weather tool fails or the question requires broader web context."
            )
            if exact_name_rule:
                guidance += " " + exact_name_rule
            return guidance
        return exact_name_rule

    def _augment_tool_args(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        request_context: Dict[str, Any],
        user_message: str,
    ) -> Dict[str, Any]:
        augmented = dict(tool_args or {})
        location = request_context.get("location") or {}

        if tool_name in {"web_search", "advanced_web_search"}:
            augmented.setdefault("current_date", request_context.get("current_date"))
            augmented.setdefault("current_time", request_context.get("current_time"))
            augmented.setdefault("timezone", request_context.get("timezone"))
            augmented.setdefault("city", location.get("city"))
            augmented.setdefault("region", location.get("region"))
            augmented.setdefault("country_name", location.get("country_name"))

        if tool_name == "weather":
            if "city" not in augmented and location.get("city"):
                augmented["city"] = location.get("city")
            if ("lat" not in augmented or "lon" not in augmented) and location.get("lat") is not None and location.get("lon") is not None:
                augmented.setdefault("lat", location.get("lat"))
                augmented.setdefault("lon", location.get("lon"))

        return augmented

    async def _maybe_handle_direct_local_shell_request(
        self,
        *,
        session_id: str,
        conversation_history: List[Dict[str, Any]],
        user_message: str,
        tool_context: str,
        permission_mode: str,
        permission_confirmed: bool,
        tools: List[Dict[str, Any]],
    ) -> Optional[List[str]]:
        tool_names = {tool.get("name") for tool in tools}
        if "bash" not in tool_names:
            return None
        if not self._looks_like_local_shell_request(user_message, tool_context):
            return None

        command = self._build_direct_shell_command(user_message)
        if not command:
            return None

        bash_skill = self.skill_manager.skills.get("bash") if self.skill_manager else None
        if bash_skill is None:
            return None

        task_id = "task_1"
        events = [
            self._sse({
                "type": "task_start",
                "task_id": task_id,
                "description": "Execute bash",
                "skill": "bash",
                "action": "tool",
            })
        ]

        try:
            result = await bash_skill.execute(command=command, timeout=30)
            tool_result_str = str(result.content) if result.success else f"Error: {result.error}"
            success = result.success
        except Exception as e:
            tool_result_str = f"Error: {e}"
            success = False

        trunc_res = tool_result_str[:400] + "..." if len(tool_result_str) > 400 else tool_result_str
        events.append(self._sse({
            "type": "task_complete",
            "task_id": task_id,
            "success": success,
            "content": trunc_res,
            "description": "Execute bash",
        }))

        final_answer = (
            f"我直接查看了本地目录，结果如下：\n\n```bash\n{tool_result_str.strip()}\n```"
            if success
            else f"本地目录查询失败：{tool_result_str.replace('Error:', '').strip()}"
        )
        conversation_history.append({"role": "assistant", "content": final_answer})
        events.append(self._sse({"type": "answer_delta", "delta": final_answer, "session_id": session_id}))
        events.append(self._sse({"done": True, "session_id": session_id}))
        return events

    async def _maybe_compact_conversation(
        self,
        *,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        request_context: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        original = chat_sessions.get(session_id, [])
        if len(original) < 2:
            return
        selected_model = (request_context or {}).get("model") or None

        prior_messages = original[:-1]
        turns = self._conversation_to_turns(prior_messages)
        if not turns:
            return

        recent_turn_count = 4
        recent_turns = turns[-recent_turn_count:]
        historical_turns = turns[:-recent_turn_count]
        before_percent = self._estimate_context_percent(original)
        should_emit_notice = before_percent >= 80

        if should_emit_notice:
            yield self._sse({
                "type": "compression_start",
                "session_id": session_id,
                "before_percent": before_percent,
                "target_percent": 40,
                "content": "Compressing conversation context with model summaries...",
            })

        cache = self.session_context_cache.setdefault(session_id, {})
        historical_summary = cache.get("historical_summary", "")
        recent_summary = cache.get("recent_summary", "")

        historical_serialized = self._serialize_turns(historical_turns) if historical_turns else ""
        recent_serialized = self._serialize_turns(recent_turns) if recent_turns else ""

        historical_signature = self._signature_for_text(historical_serialized) if historical_serialized else ""
        recent_signature = self._signature_for_text(recent_serialized) if recent_serialized else ""

        if historical_serialized and cache.get("historical_signature") != historical_signature:
            try:
                summary_chunks: List[str] = []
                async for chunk in self._summarize_context_block(
                    session_id=session_id,
                    phase="compression_historical",
                    instructions=(
                        "Summarize the older conversation into compact working memory. "
                        "Preserve long-term user goals, constraints, decisions, preferences, unresolved issues, dates, locations, "
                        "and tool findings that still matter. Keep it concise and factual."
                    ),
                    content=historical_serialized,
                    max_tokens=900,
                    model=selected_model,
                ):
                    if chunk.startswith("data: "):
                        yield chunk
                    else:
                        summary_chunks.append(chunk)
                if summary_chunks:
                    historical_summary = json.loads(summary_chunks[-1]).get("content", "") or ""
                    historical_summary = self._split_thinking_and_answer(historical_summary)["answer_text"].strip()
                    cache["historical_summary"] = historical_summary.strip()
                    cache["historical_signature"] = historical_signature
            except Exception:
                logger.exception("Historical context compression failed")

        if recent_serialized and cache.get("recent_signature") != recent_signature:
            try:
                summary_chunks = []
                async for chunk in self._summarize_context_block(
                    session_id=session_id,
                    phase="compression_recent",
                    instructions=(
                        "Summarize the recent conversation rounds for immediate continuity. "
                        "Preserve the latest asks, current assumptions, recent tool outcomes, and what the assistant should continue doing next. "
                        "Keep it concise, accurate, and action-oriented."
                    ),
                    content=recent_serialized,
                    max_tokens=600,
                    model=selected_model,
                ):
                    if chunk.startswith("data: "):
                        yield chunk
                    else:
                        summary_chunks.append(chunk)
                if summary_chunks:
                    recent_summary = json.loads(summary_chunks[-1]).get("content", "") or ""
                    recent_summary = self._split_thinking_and_answer(recent_summary)["answer_text"].strip()
                    cache["recent_summary"] = recent_summary.strip()
                    cache["recent_signature"] = recent_signature
            except Exception:
                logger.exception("Recent context compression failed")

        cache["recent_turn_count"] = recent_turn_count
        after_basis = [
            {"role": "system", "content": "OBS Agent system prompt"},
            {
                "role": "user",
                "content": "\n\n".join(
                    part for part in [
                        historical_summary.strip(),
                        recent_summary.strip(),
                        (original[-1].get("content") or "").strip(),
                    ] if part
                ),
            },
        ]
        after_percent = self._estimate_context_percent(after_basis)

        if should_emit_notice:
            yield self._sse({
                "type": "compression_complete",
                "session_id": session_id,
                "before_percent": before_percent,
                "after_percent": after_percent,
                "content": "Conversation context compressed into historical and recent summaries.",
            })

    def _extract_tool_calls_from_response_message(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        tool_calls = []
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            tool_calls.append({
                "id": tool_call.get("id", ""),
                "type": tool_call.get("type", "function"),
                "function": {
                    "name": self._canonical_tool_name(function.get("name", "") or ""),
                    "arguments": function.get("arguments", "") or "",
                },
            })
        if not tool_calls:
            tool_calls = self._extract_tool_calls_from_xml_markup(message.get("content", "") or "")
        return tool_calls

    async def chat_stream(
        self,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        *,
        mode: str = "agent",
        permission_mode: str = "ask",
        permission_confirmed: bool = False,
        context: str = "",
        tool_context: str = "workspace",
        enabled_skills: Optional[List[str]] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        try:
            user_message = chat_sessions[session_id][-1]["content"] if chat_sessions.get(session_id) else ""
            enriched_user_message = self._apply_context_to_user_message(user_message, context, tool_context)
            effective_mode = mode

            if effective_mode == "plan":
                async for chunk in self._plan_only_stream(
                    user_message=enriched_user_message,
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                ):
                    yield chunk
                return

            if effective_mode == "review" and self.execution_engine is not None:
                async for chunk in self._execution_engine_stream(
                    user_message=enriched_user_message,
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                ):
                    yield chunk
                return

            async for chunk in self._native_tool_stream(
                session_id=session_id,
                chat_sessions=chat_sessions,
                permission_mode=permission_mode,
                permission_confirmed=permission_confirmed,
                context=context,
                tool_context=tool_context,
                enabled_skills=enabled_skills or [],
                request_context=request_context or {},
            ):
                yield chunk
        except Exception as e:
            logger.exception("StreamingAgent error")
            error_text = str(e)
            friendly_error = "请求暂时失败，请稍后重试。"
            if "529" in error_text:
                friendly_error = "模型服务当前较繁忙，请稍后再试。"
            elif "400" in error_text:
                friendly_error = "请求参数暂时不兼容，我已经记录下来了，请稍后重试。"
            yield self._sse({"error": friendly_error, "done": True})

    def _apply_context_to_user_message(self, user_message: str, context: str, tool_context: str) -> str:
        if SIMPLE_GREETING_PATTERN.match((user_message or "").strip()):
            return user_message
        context = (context or "").strip()
        tool_context = (tool_context or "workspace").strip()
        if not context:
            return user_message
        return (
            f"[Tool context: {tool_context}]\n"
            f"{context}\n\n"
            f"[User request]\n{user_message}"
        )

    def _rewrite_followup_location_query(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        rewritten = [dict(item) for item in messages]
        latest = rewritten[-1]
        if latest.get("role") != "user":
            return rewritten

        latest_text = (latest.get("content") or "").strip()
        if not latest_text or len(latest_text) > 20 or any(token in latest_text for token in ["天气", "温度", "气温", "weather", "forecast"]):
            return rewritten

        previous_assistant = None
        for item in reversed(rewritten[:-1]):
            if item.get("role") == "assistant":
                previous_assistant = (item.get("content") or "").strip()
                break

        if not previous_assistant:
            return rewritten

        weather_prompt_markers = [
            "哪个城市的天气",
            "请告诉我城市名称",
            "想查询哪个城市的天气",
            "告诉我城市名称",
            "哪个城市",
        ]
        if any(marker in previous_assistant for marker in weather_prompt_markers):
            latest["content"] = f"{latest_text}天气"
        return rewritten

    async def _plan_only_stream(
        self,
        *,
        user_message: str,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
    ) -> AsyncGenerator[str, None]:
        if self.plan_agent is None:
            yield self._sse({"error": "Plan agent not initialized", "done": True})
            return

        plan = await self.plan_agent.create_plan(user_message, chat_sessions.get(session_id, []))
        steps = [step.to_dict() for step in plan.steps]

        from .task_graph import analyze_task_dependencies

        task_graph = analyze_task_dependencies(steps)
        yield self._sse({
            "type": "plan",
            "plan": plan.to_dict(),
            "task_graph": task_graph.to_dict(),
        })

        summary_lines = ["Execution plan created:"]
        for task in task_graph.to_dict().get("tasks", []):
            description = task.get("description") or task.get("task_id")
            summary_lines.append(f"- {task.get('task_id')}: {description}")
            yield self._sse({
                "type": "task_start",
                "task_id": task.get("task_id"),
                "description": description,
                "action": task.get("action"),
                "skill": task.get("skill"),
                "virtual": True,
            })

        final_text = "\n".join(summary_lines)
        chat_sessions[session_id].append({"role": "assistant", "content": final_text})
        yield self._sse({"content": final_text, "done": True, "session_id": session_id})

    async def _execution_engine_stream(
        self,
        *,
        user_message: str,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
    ) -> AsyncGenerator[str, None]:
        async for event in self.execution_engine.execute_user_request(
            user_message=user_message,
            session_id=session_id,
            chat_history=chat_sessions.get(session_id, []),
        ):
            event_type = event.get("type")

            if event_type == "plan":
                yield self._sse({
                    "type": "plan",
                    "plan": event.get("content"),
                    "task_graph": event.get("task_graph"),
                })
                continue

            if event_type == "task_start":
                yield self._sse({
                    "type": "task_start",
                    "task_id": event.get("task_id"),
                    "description": event.get("description"),
                    "skill": event.get("skill"),
                    "action": event.get("action"),
                })
                continue

            if event_type == "task_complete":
                yield self._sse({
                    "type": "task_complete",
                    "task_id": event.get("task_id"),
                    "description": event.get("description"),
                    "success": event.get("success", False),
                    "content": event.get("content", ""),
                })
                continue

            if event_type == "final_response":
                final_text = event.get("content", "")
                chat_sessions[session_id].append({"role": "assistant", "content": final_text})
                yield self._sse({"content": final_text})
                continue

            if event_type == "error":
                yield self._sse({"error": event.get("content", "Unknown execution error"), "done": True})
                return

        yield self._sse({"done": True, "session_id": session_id})

    async def _native_tool_stream(
        self,
        *,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        permission_mode: str,
        permission_confirmed: bool,
        context: str,
        tool_context: str,
        enabled_skills: List[str],
        request_context: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        selected_model = (request_context or {}).get("model") or None
        async for chunk in self._maybe_compact_conversation(
            session_id=session_id,
            chat_sessions=chat_sessions,
            request_context=request_context,
        ):
            yield chunk

        conversation_history = chat_sessions[session_id].copy()
        rewritten_history = self._rewrite_followup_location_query(conversation_history)
        current_user_message = rewritten_history[-1]["content"] if rewritten_history else ""
        is_simple_greeting = bool(SIMPLE_GREETING_PATTERN.match((current_user_message or "").strip()))
        raw_message_parts = (request_context or {}).get("message_parts") or []
        has_inline_images = self._has_image_parts(raw_message_parts)
        inline_image_context = self._analyze_inline_images_locally(raw_message_parts) if has_inline_images else ""
        tools = self._get_allowed_tools(permission_mode, permission_confirmed, enabled_skills)
        if is_simple_greeting or has_inline_images:
            tools = []
        else:
            tools = self._select_eligible_tools(tools, current_user_message, tool_context)
        tools = self._prioritize_tools_for_request(tools, current_user_message, tool_context)
        direct_events = await self._maybe_handle_direct_local_shell_request(
            session_id=session_id,
            conversation_history=conversation_history,
            user_message=current_user_message,
            tool_context=tool_context,
            permission_mode=permission_mode,
            permission_confirmed=permission_confirmed,
            tools=tools,
        )
        if direct_events is not None:
            chat_sessions[session_id] = conversation_history
            for event in direct_events:
                yield event
            return
        system_prompts = []
        tool_guidance = self._build_request_tool_guidance(current_user_message, tool_context, tools)
        if tools:
            system_prompts.append(
                "You are OBS Agent. When tools are available, use them for requests that need real-time, "
                "external, or verifiable information. "
                "For weather, latest news, prices, search, or current status questions, call a suitable tool "
                "first and do not answer by claiming you cannot access live data unless a tool call has already failed."
            )
        elif has_inline_images:
            system_prompts.append(
                "The current user message includes inline images. Focus on directly understanding the attached "
                "images and answering from visual evidence. Do not emit tool-call markup, XML invocation tags, "
                "or claim the image is unavailable if it was provided in the prompt."
            )
        elif enabled_skills:
            system_prompts.append(
                "Only the currently selected skills are available in this session. "
                "If a needed tool is not enabled, do not fabricate tool calls, XML tags, or internal invocation markup. "
                "Instead, clearly explain that the required skill is not currently selected."
            )
        tool_names = [tool.get("name", "") for tool in tools if tool.get("name")]
        skill_index_prompt = self._build_skill_index_prompt(tool_names) if tools else None
        relevant_skill_instructions = self._build_relevant_skill_instructions(tool_names) if tools else None
        cache = self.session_context_cache.get(session_id, {})
        user_prompt = self._build_compacted_user_prompt(
            current_user_message=current_user_message,
            context=context if not is_simple_greeting else "",
            tool_context=tool_context,
            request_context=request_context if self._should_include_runtime_context(current_user_message) else {},
            historical_summary=(cache.get("historical_summary") or "").strip(),
            recent_summary=(cache.get("recent_summary") or "").strip(),
            skill_index_prompt=skill_index_prompt,
            relevant_skill_instructions=relevant_skill_instructions,
            tool_guidance=tool_guidance,
        )
        if inline_image_context:
            user_prompt = (
                f"{user_prompt}\n\n"
                "[Inline image analysis]\n"
                "The following image facts were extracted locally from the attached image(s). "
                "Use them as grounded visual context for your answer.\n"
                f"{inline_image_context}"
            )
        system_prompt = (
            "You are OBS Agent. Use the provided user prompt as the authoritative working context for this turn. "
            "The user prompt may already contain compressed historical context, recent context, runtime context, "
            "and on-demand skill instructions. Do not ask for the same background again unless necessary."
        )
        if system_prompts:
            system_prompt = f"{system_prompt}\n\n" + "\n".join(system_prompts)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": self._compose_user_message_content(
                    user_prompt,
                    self._text_only_message_parts(raw_message_parts) if has_inline_images else raw_message_parts,
                ),
            },
        ]
        yield self._emit_context_state(session_id, messages)

        max_iterations = 10
        tool_step_index = 0
        completed = False

        for iteration in range(max_iterations):
            logger.info(f"Streaming Agent Loop Iteration {iteration + 1}")
            assistant_message = {"role": "assistant", "content": ""}
            tool_calls = []
            emitted_thinking_len = 0
            emitted_answer_len = 0
            try:
                yield self._sse_log(session_id, "tool_planning", "request", {
                    "messages": messages,
                    "tools": tools if tools else None,
                    "temperature": 0.7,
                    "max_tokens": 4000,
                    "stream": True,
                    "model": selected_model,
                })
                stream_generator = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=tools if tools else None,
                    temperature=0.7,
                    max_tokens=4000,
                    stream=True,
                    model=selected_model,
                )

                async for chunk in stream_generator:
                    if "choices" not in chunk or not chunk["choices"]:
                        continue

                    delta = chunk["choices"][0].get("delta", {})

                    if "content" in delta and delta["content"]:
                        content_piece = delta["content"]
                        assistant_message["content"] += content_piece
                        parsed = self._build_stream_deltas(
                            assistant_message["content"],
                            emitted_thinking_len,
                            emitted_answer_len,
                        )

                        if parsed["thinking_delta"]:
                            emitted_thinking_len += len(parsed["thinking_delta"])
                            yield self._sse({
                                "type": "thinking_delta",
                                "delta": parsed["thinking_delta"],
                                "session_id": session_id,
                            })

                        if parsed["answer_delta"]:
                            emitted_answer_len += len(parsed["answer_delta"])
                            yield self._sse({
                                "type": "answer_delta",
                                "delta": parsed["answer_delta"],
                                "session_id": session_id,
                            })

                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc in delta["tool_calls"]:
                            index = tc.get("index", len(tool_calls))
                            while len(tool_calls) <= index:
                                tool_calls.append({
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""}
                                })

                            if "id" in tc and tc["id"]:
                                tool_calls[index]["id"] = tc["id"]
                            if "function" in tc:
                                if tc["function"].get("name"):
                                    tool_calls[index]["function"]["name"] += tc["function"]["name"]
                                if tc["function"].get("arguments"):
                                    tool_calls[index]["function"]["arguments"] += tc["function"]["arguments"]
            except Exception as exc:
                logger.warning(f"Streaming tool-planning failed, falling back to non-stream completion: {exc}")
                yield self._sse_log(session_id, "tool_planning", "response", {
                    "fallback": "stream_to_non_stream",
                    "error": str(exc),
                    "model": selected_model,
                })
                response = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=tools if tools else None,
                    temperature=0.7,
                    max_tokens=4000,
                    stream=False,
                    model=selected_model,
                )
                if "choices" not in response or not response["choices"]:
                    raise
                message = response["choices"][0].get("message", {}) or {}
                yield self._sse_log(session_id, "tool_planning", "response", {
                    "message": message,
                })
                assistant_message["content"] = message.get("content", "") or ""
                parsed = self._split_thinking_and_answer(assistant_message["content"])
                if parsed["thinking_text"]:
                    yield self._sse({
                        "type": "thinking_delta",
                        "delta": parsed["thinking_text"],
                        "session_id": session_id,
                    })
                if parsed["answer_text"]:
                    yield self._sse({
                        "type": "answer_delta",
                        "delta": parsed["answer_text"],
                        "session_id": session_id,
                    })
                tool_calls = self._extract_tool_calls_from_response_message(message)

            if not tool_calls:
                tool_calls = self._extract_tool_calls_from_response_message(assistant_message)

            if not tool_calls:
                yield self._sse_log(session_id, "tool_planning", "response", {
                    "message": assistant_message,
                })
                final_parts = self._split_thinking_and_answer(assistant_message["content"])
                final_answer = final_parts["answer_text"].strip()
                if has_inline_images and self._should_use_local_image_fallback(final_answer):
                    local_image_answer = self._analyze_inline_images_locally(
                        (request_context or {}).get("message_parts")
                    )
                    if local_image_answer:
                        final_answer = local_image_answer
                if not final_answer:
                    final_answer = self._build_tool_fallback_answer(messages)
                conversation_history.append({
                    "role": "assistant",
                    "content": final_answer,
                })
                chat_sessions[session_id] = conversation_history
                yield self._emit_context_state(session_id, conversation_history)
                yield self._sse({"done": True, "session_id": session_id})
                completed = True
                break

            normalized_parts = self._split_thinking_and_answer(assistant_message["content"])
            assistant_message["content"] = normalized_parts["answer_text"].strip()
            assistant_message["tool_calls"] = tool_calls
            yield self._sse_log(session_id, "tool_planning", "response", {
                "message": assistant_message,
            })
            messages.append(assistant_message)

            for tool_call in tool_calls:
                raw_tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]

                try:
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}
                except json.JSONDecodeError:
                    tool_args = {}

                normalized_invocation = self._normalize_tool_invocation(
                    raw_tool_name,
                    tool_args,
                    request_context,
                )
                tool_name = normalized_invocation["name"]
                tool_args = normalized_invocation["arguments"]

                tool_step_index += 1
                task_id = f"task_{tool_step_index}"
                yield self._sse({
                    "type": "task_start",
                    "task_id": task_id,
                    "description": f"Execute {tool_name}",
                    "skill": tool_name,
                    "action": "tool",
                })

                try:
                    if tool_name in self.skill_manager.skills:
                        skill = self.skill_manager.skills[tool_name]
                        tool_args = self._augment_tool_args(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            request_context=request_context,
                            user_message=current_user_message,
                        )
                        result = await skill.execute(**tool_args)
                        tool_result_str = str(result.content) if result.success else f"Error: {result.error}"
                        success = result.success
                    else:
                        tool_result_str = f"Tool {tool_name} not found"
                        success = False
                except Exception as e:
                    tool_result_str = str(e)
                    success = False

                trunc_res = tool_result_str[:400] + "..." if len(tool_result_str) > 400 else tool_result_str
                yield self._sse({
                    "type": "task_complete",
                    "task_id": task_id,
                    "success": success,
                    "content": trunc_res,
                    "description": f"Execute {tool_name}",
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", "unknown"),
                    "name": tool_name,
                    "content": tool_result_str,
                })

                if success and tool_name in READ_ONLY_TOOLS and tool_result_str.strip():
                    async for chunk in self._stream_final_answer_without_tools(
                        session_id=session_id,
                        chat_sessions=chat_sessions,
                        conversation_history=conversation_history,
                    messages=messages,
                    instruction=(
                        "请基于上面的工具结果直接给出最终回答。"
                        "要求：1. 先整合关键信息；2. 明确说明哪些信息最值得关注；"
                        "3. 不要继续调用任何工具；4. 不要输出 provider 名称、原始调试字段或内部执行说明；"
                        "5. 如果结果质量一般，就简短说明局限性，但仍然给出最有用的总结。"
                    ),
                    model=selected_model,
                ):
                        yield chunk
                    return

        if completed:
            return

        fallback_answer = self._build_tool_fallback_answer(messages)
        if "当前结果质量较低" in fallback_answer:
            fallback_answer = (
                "我尝试多次检索今日热点新闻，但当前搜索结果质量较低，没拿到足够可靠的正文内容。\n\n"
                f"{fallback_answer}\n\n"
                "建议你直接查看人民网、新华社、澎湃新闻或央视新闻获取最新头条。"
            )

        conversation_history.append({
            "role": "assistant",
            "content": fallback_answer,
        })
        chat_sessions[session_id] = conversation_history
        yield self._emit_context_state(session_id, conversation_history)
        yield self._sse({
            "type": "answer_delta",
            "delta": fallback_answer,
            "session_id": session_id,
        })
        yield self._sse({"done": True, "session_id": session_id})

    def _get_allowed_tools(self, permission_mode: str, permission_confirmed: bool, enabled_skills: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        tools = []
        if self.skill_manager:
            try:
                tools = self.skill_manager.get_anthropic_tools()
            except Exception as e:
                logger.warning(f"Could not get tools: {e}")
                tools = []

        if enabled_skills:
            enabled_set = set(enabled_skills)
            filtered = []
            for tool in tools:
                tool_name = tool.get("name")
                resolved_skill = self.skill_manager.resolve_skill_name_for_tool(tool_name) if self.skill_manager else None
                if tool_name in enabled_set or resolved_skill in enabled_set:
                    filtered.append(tool)
            tools = filtered

        if permission_mode == "plan":
            return []

        return tools

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
