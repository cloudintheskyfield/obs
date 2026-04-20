import json
import hashlib
import os
import re
import traceback
import base64
import io
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, AsyncGenerator, Optional
from loguru import logger
from PIL import Image

from ..services.request_lifecycle import RequestLifecycle

READ_ONLY_TOOLS = {"web_search", "advanced_web_search", "weather"}
WRITE_CAPABLE_TOOLS = {"bash", "str_replace_editor", "computer", "code_sandbox"}

MICROCOMPACT_THRESHOLD = 80   # start micro-compacting at 80 % of the model's context window
AUTOCOMPACT_THRESHOLD = 90    # full auto-compact (summarise turns) only above 90 %
TOOL_RESULT_KEEP_CHARS = 1_000
MICROCOMPACT_PROTECTED_TAIL = 20   # protect ~10 turns × 2 msgs from in-turn truncation
RECENT_TURNS_VERBATIM = 10         # target verbatim turns for compaction (see LLM_MAX_RECENT_DIALOG_TURNS)
# Hard caps on what we send to MiniMax in one request (avoid 400 / overload from giant prompts).
LLM_MAX_RECENT_DIALOG_TURNS = max(2, min(30, int(os.getenv("OBS_LLM_MAX_RECENT_TURNS", "10"))))
MAX_CHARS_PER_PROMPT_TURN = max(2_000, min(60_000, int(os.getenv("OBS_LLM_MAX_CHARS_PER_TURN", "10000"))))
HISTORICAL_SUMMARY_MAX_CHARS = max(8_000, min(120_000, int(os.getenv("OBS_LLM_MAX_HISTORICAL_CHARS", "24000"))))
TOOL_MESSAGE_SOFT_CHAR_LIMIT = max(4_000, min(200_000, int(os.getenv("OBS_LLM_TOOL_MESSAGE_SOFT_CHARS", "12000"))))
# Whole "[Recent conversation turns]" block ceiling (after per-turn truncation).
RECENT_TRANSCRIPT_BLOCK_MAX = max(20_000, min(200_000, int(os.getenv("OBS_LLM_MAX_RECENT_BLOCK_CHARS", "90000"))))
COMPACTABLE_TOOL_NAMES = frozenset({
    "bash", "str_replace_editor", "web_search", "advanced_web_search",
    "computer", "code_sandbox", "weather",
})
LOCAL_SHELL_HINT_PATTERN = re.compile(
    r"(家目录|home目录|当前目录|工作区|workspace|目录下|文件夹|列出.*文件|看看.*文件|有哪些文件|ls\b|pwd\b|find\b|cat\b|grep\b|bash\b|shell\b|terminal\b|command\b|命令行)",
    re.IGNORECASE,
)
WEATHER_HINT_PATTERN = re.compile(r"(天气|温度|气温|weather|forecast)", re.IGNORECASE)
NEWS_HINT_PATTERN = re.compile(r"(新闻|热点|头条|快讯|news|headline|breaking)", re.IGNORECASE)
FINANCE_HINT_PATTERN = re.compile(r"(股价|股票|汇率|finance|stock|market|price|\$)", re.IGNORECASE)
CODE_HINT_PATTERN = re.compile(r"(代码|文件|测试|修复|修改|实现|重构|run|test|debug|fix|edit|code|repo|workspace)", re.IGNORECASE)
COMPUTER_HINT_PATTERN = re.compile(r"(浏览器|页面|截图|click|open|tab|网页|screen|ui)", re.IGNORECASE)
WEB_REFERENCE_PATTERN = re.compile(r"(地址|链接|网址|url|网页|页面|网站|站点|里面|其中|上面|那个|这个)", re.IGNORECASE)
WEB_ACTION_PATTERN = re.compile(r"(打开|访问|进入|浏览|点开|操作|玩|play|open|visit|browse|navigate)", re.IGNORECASE)
URL_LIKE_PATTERN = re.compile(
    r"((?:https?://|://|www\.)[^\s]+|(?:\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?/[^\s]+)|(?:\blocalhost(?::\d+)?/[^\s]+))",
    re.IGNORECASE,
)
CODE_WRITE_PATTERN = re.compile(
    r"(写|创建|生成|帮我|开发|实现|编写|write|create|build|make|generate|game|贪吃蛇|游戏|程序|项目|app|应用)",
    re.IGNORECASE,
)
RUNTIME_CONTEXT_PATTERN = re.compile(
    r"(今天|今日|当天|目前|当前|现在|latest|today|current|recent|weather|forecast|新闻|热点|头条|price|stock|股价|汇率|news)",
    re.IGNORECASE,
)
SIMPLE_GREETING_PATTERN = re.compile(r"^\s*(hi|hello|hey|你好|嗨|在吗)\W*\s*$", re.IGNORECASE)
TOOL_INVENTORY_PATTERN = re.compile(
    r"(有什么工具|有哪些工具|你有什么技能|有哪些技能|你有什么skill|你有什么skills|可用工具|可用技能|可用skills?|当前.*工具|当前.*技能|当前.*skills?|what tools|what skills|available tools|available skills|which tools|which skills)",
    re.IGNORECASE,
)
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
DIRECTORY_LISTING_PATTERN = re.compile(
    r"(?m)^(total\s+\d+|[d\-lcbps][rwxStT\-]{9}\s+\d+\s+\S+\s+\S+)",
)
WEATHER_LOCATION_REQUIRED_PATTERN = re.compile(
    r"(provide either city|both lat and lon|city or both lat and lon|missing required.*city|缺少.*城市|需要.*经纬度)",
    re.IGNORECASE,
)
MODEL_CONTEXT_WINDOWS = {
    "minimax-m2": 200_000,
}


class StreamingAgent:
    """
    Streaming agent plus mode-aware execution routing.

    - `agent` mode: native tool-calling loop
    - `plan` mode: create task graph only, no tool execution
    - `review` mode: route through execution engine for structured task transcript
    - `battle` mode: run a direct model answer and a tool-assisted answer, then judge the winner
    """

    def __init__(self, vllm_client, skill_manager, execution_engine=None, plan_agent=None, request_lifecycle: Optional[RequestLifecycle] = None):
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.execution_engine = execution_engine
        self.plan_agent = plan_agent
        self.request_lifecycle = request_lifecycle or RequestLifecycle()
        self.session_context_cache: Dict[str, Dict[str, Any]] = {}

    def _phase(self, key: str, **overrides: Any) -> str:
        return self._sse(self.request_lifecycle.phase_payload(key, **overrides))

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

    def _collect_recent_image_turns(
        self,
        conversation_history: List[Dict[str, Any]],
        max_turns: int = 6,
    ) -> List[Dict[str, Any]]:
        turns: List[Dict[str, Any]] = []
        recent = conversation_history[:-1] if len(conversation_history) > 1 else []
        pairs: List[tuple] = []
        i = 0
        while i < len(recent):
            entry = recent[i]
            if entry.get("role") == "user":
                user_entry = entry
                assistant_entry = recent[i + 1] if i + 1 < len(recent) and recent[i + 1].get("role") == "assistant" else None
                pairs.append((user_entry, assistant_entry))
                i += 2 if assistant_entry else 1
            else:
                i += 1
        for user_entry, assistant_entry in pairs[-max_turns:]:
            parts = user_entry.get("message_parts") or []
            has_img = any(
                isinstance(p, dict) and p.get("type") == "image" and (p.get("data_url") or p.get("url"))
                for p in parts
            )
            if not has_img:
                continue
            content = self._compose_user_message_content(
                str(user_entry.get("content") or ""),
                parts,
            )
            turns.append({"role": "user", "content": content})
            if assistant_entry:
                ans = str(assistant_entry.get("content") or "")
                if ans:
                    turns.append({"role": "assistant", "content": ans})
        return turns

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
            if tool_name == "computer" and content in {
                "Screenshot taken successfully",
                "Current cursor position retrieved",
            }:
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

    def _get_context_window_tokens(self, model_name: Optional[str] = None) -> int:
        normalized = (model_name or getattr(getattr(self.vllm_client, "config", None), "model", "") or "").strip().lower()
        if normalized in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[normalized]
        if "minimax-m2" in normalized:
            return MODEL_CONTEXT_WINDOWS["minimax-m2"]
        return 128_000

    def _microcompact_messages(
        self,
        messages: List[Dict[str, Any]],
        protected_tail: int = MICROCOMPACT_PROTECTED_TAIL,
    ) -> List[Dict[str, Any]]:
        """Truncate large old tool results without an LLM call.

        Mirrors Claude Code's microcompactMessages pipeline: only compacts tool
        results for compactable tools in the un-protected head of the list, leaving
        the most recent `protected_tail` messages untouched so the model still has
        full context for the current iteration.
        """
        if len(messages) <= protected_tail:
            return messages

        split = len(messages) - protected_tail
        compactable_region = messages[:split]
        protected_region = messages[split:]

        freed_chars = 0
        compacted: List[Dict[str, Any]] = []
        for msg in compactable_region:
            if msg.get("role") == "tool" and msg.get("name") in COMPACTABLE_TOOL_NAMES:
                content = str(msg.get("content") or "")
                if len(content) > TOOL_RESULT_KEEP_CHARS:
                    freed_chars += len(content) - TOOL_RESULT_KEEP_CHARS
                    msg = {**msg, "content": content[:TOOL_RESULT_KEEP_CHARS] + "\n[...old tool result truncated by microcompact]"}
            compacted.append(msg)

        if freed_chars:
            logger.debug(f"microcompact freed ~{freed_chars} chars across {len(compacted)} messages")

        return compacted + protected_region

    def _estimate_text_tokens(self, text: str) -> int:
        if not text:
            return 0
        cjk_chars = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text)
        cjk_count = len(cjk_chars)
        remaining = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", " ", text)
        word_like = re.findall(r"[A-Za-z0-9_]+", remaining)
        punctuation_like = re.findall(r"[^\sA-Za-z0-9_]", remaining)
        word_tokens = sum(max(1, round(len(word) / 4)) for word in word_like)
        punctuation_tokens = round(len(punctuation_like) * 0.35)
        return max(0, cjk_count + word_tokens + punctuation_tokens)

    def _estimate_context_tokens(self, messages: List[Dict[str, Any]]) -> int:
        return sum(
            self._estimate_text_tokens(self._message_content_to_text(item.get("content")))
            for item in messages
        )

    def _estimate_context_percent(
        self,
        messages: List[Dict[str, Any]],
        model_name: Optional[str] = None,
    ) -> float:
        used_tokens = self._estimate_context_tokens(messages)
        max_tokens = self._get_context_window_tokens(model_name)
        if used_tokens <= 0 or max_tokens <= 0:
            return 0
        raw = (used_tokens / max_tokens) * 100
        # Round to 1 decimal; cap at 98 so we never show 100% before hard limit
        return min(98.0, round(raw, 1))

    def _emit_context_state(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        working_messages: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
    ) -> str:
        """Emit a context_state SSE event.

        ``messages`` is the conversation history (used for history display).
        ``working_messages`` is the full LLM context for this turn (system +
        history + tool calls/results).  When provided, the token count and
        percentage are computed from ``working_messages`` so they reflect real
        context-window usage.
        ``model_name`` is the currently selected model so the correct context
        window size is used in the percentage calculation.
        """
        token_source = working_messages if working_messages is not None else messages
        estimated_tokens = self._estimate_context_tokens(token_source)
        max_context_tokens = self._get_context_window_tokens(model_name)
        return self._sse({
            "type": "context_state",
            "session_id": session_id,
            "context_percent": self._estimate_context_percent(token_source, model_name),
            "estimated_context_tokens": estimated_tokens,
            "max_context_tokens": max_context_tokens,
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

    @staticmethod
    def _truncate_prompt_field(text: str, limit: int) -> str:
        t = (text or "").strip()
        if len(t) <= limit:
            return t
        return t[:limit] + "\n[...truncated for LLM prompt size limit — earlier text omitted]"

    def _serialize_turns(self, turns: List[Dict[str, str]]) -> str:
        lim = MAX_CHARS_PER_PROMPT_TURN
        lines: List[str] = []
        for index, turn in enumerate(turns, start=1):
            lines.append(f"Round {index}")
            lines.append(f"User: {self._truncate_prompt_field(turn.get('user', '') or '', lim)}")
            assistant = (turn.get("assistant") or "").strip()
            if assistant:
                lines.append(f"Assistant: {self._truncate_prompt_field(assistant, lim)}")
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

    async def _chunked_summarize(
        self,
        *,
        session_id: str,
        phase: str,
        instructions: str,
        content: str,
        max_tokens: int,
        model: Optional[str] = None,
        chunk_size: int = 7000,
        max_rounds: int = 4,
    ) -> AsyncGenerator[str, None]:
        """
        Summarize arbitrarily long content by splitting into chunks and iteratively
        compressing until the result fits in a single model call.

        Algorithm (map-reduce loop):
          Round 1: split content into chunk_size pieces → summarize each chunk
          Round N: join chunk summaries → if still > chunk_size, split again and repeat
          Stop when result fits in one chunk or max_rounds is reached.
        """
        current = content
        for round_idx in range(1, max_rounds + 1):
            if len(current) <= chunk_size:
                # Fits in a single call — final summarization
                chunks = [current]
            else:
                # Split into overlapping-free chunks
                chunks = [current[i:i + chunk_size] for i in range(0, len(current), chunk_size)]

            if len(chunks) == 1:
                # Single-chunk path — emit final result and stop
                async for item in self._summarize_context_block(
                    session_id=session_id,
                    phase=f"{phase}_r{round_idx}",
                    instructions=instructions,
                    content=chunks[0],
                    max_tokens=max_tokens,
                    model=model,
                ):
                    yield item
                return

            # Multi-chunk: summarize each chunk, collect results
            chunk_summaries: List[str] = []
            for chunk_idx, chunk in enumerate(chunks):
                chunk_phase = f"{phase}_r{round_idx}_c{chunk_idx + 1}of{len(chunks)}"
                summary_parts: List[str] = []
                async for item in self._summarize_context_block(
                    session_id=session_id,
                    phase=chunk_phase,
                    instructions=instructions + " (This is a partial segment; produce a compact intermediate summary.)",
                    content=chunk,
                    max_tokens=max(200, max_tokens // max(len(chunks), 1)),
                    model=model,
                ):
                    if item.startswith("data: "):
                        yield item  # forward SSE log events
                    else:
                        summary_parts.append(item)
                if summary_parts:
                    try:
                        chunk_text = json.loads(summary_parts[-1]).get("content", "") or ""
                        chunk_text = self._split_thinking_and_answer(chunk_text)["answer_text"].strip()
                        if chunk_text:
                            chunk_summaries.append(chunk_text)
                    except Exception:
                        pass

            if not chunk_summaries:
                # Nothing to combine — yield empty and exit
                yield json.dumps({"content": ""}, ensure_ascii=False)
                return

            # Combine all chunk summaries and loop
            current = "\n\n".join(chunk_summaries)

        # Fallback: emit whatever we have after max_rounds
        yield json.dumps({"content": current}, ensure_ascii=False)

    def _build_compacted_user_prompt(
        self,
        *,
        current_user_message: str,
        context: str,
        tool_context: str,
        request_context: Dict[str, Any],
        historical_summary: str,
        recent_summary: str,
        recent_turn_transcript: str,
        skill_index_prompt: Optional[str],
        relevant_skill_instructions: Optional[str],
        tool_guidance: Optional[str],
    ) -> str:
        sections = []
        historical_summary = self._sanitize_visible_text(historical_summary).strip()
        recent_summary = self._sanitize_visible_text(recent_summary).strip()
        recent_turn_transcript = self._sanitize_visible_text(recent_turn_transcript).strip()

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
            hs = self._truncate_prompt_field(historical_summary, HISTORICAL_SUMMARY_MAX_CHARS)
            sections.append(f"[Historical context summary]\n{hs}")

        if recent_turn_transcript:
            rt = self._truncate_prompt_field(recent_turn_transcript, RECENT_TRANSCRIPT_BLOCK_MAX)
            sections.append(f"[Recent conversation turns]\n{rt}")

        if recent_summary:
            sections.append(f"[Recent {RECENT_TURNS_VERBATIM} rounds summary]\n{recent_summary}")

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

    def _resolve_prompt_context(
        self,
        *,
        session_id: str,
        conversation_history: List[Dict[str, Any]],
        raw_recent_turn_count: int = RECENT_TURNS_VERBATIM,
    ) -> Dict[str, str]:
        cache = self.session_context_cache.setdefault(session_id, {})
        prior_messages = conversation_history[:-1]
        turns = self._conversation_to_turns(prior_messages)
        if not turns:
            return {
                "historical_summary": "",
                "recent_summary": "",
                "recent_turn_transcript": "",
            }

        # Keep exactly the latest N turns verbatim and compress anything older.
        # Older builds may have stored a larger recent_turn_count in cache; ignore it.
        recent_turn_count = min(LLM_MAX_RECENT_DIALOG_TURNS, RECENT_TURNS_VERBATIM, len(turns))
        recent_turns = turns[-recent_turn_count:]
        historical_turns = turns[:-recent_turn_count]

        historical_serialized = self._serialize_turns(historical_turns) if historical_turns else ""
        historical_signature = self._signature_for_text(historical_serialized) if historical_serialized else ""

        historical_summary = ""
        if historical_signature and cache.get("historical_signature") == historical_signature:
            historical_summary = (cache.get("historical_summary") or "").strip()
        elif historical_signature and cache.get("historical_signature") != historical_signature:
            cache.pop("historical_summary", None)
            cache.pop("historical_signature", None)

        # The last RECENT_TURNS_VERBATIM turns are always included verbatim — no summary.
        recent_turn_transcript = self._serialize_turns(recent_turns[-raw_recent_turn_count:]) if recent_turns else ""
        return {
            "historical_summary": historical_summary,
            "recent_summary": "",   # deliberately empty: verbatim transcript is used instead
            "recent_turn_transcript": recent_turn_transcript,
        }

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

    def _build_skill_index_prompt(
        self,
        tool_names: List[str],
        enabled_skills: Optional[List[str]] = None,
    ) -> Optional[str]:
        if not self.skill_manager:
            return None

        entries = self.skill_manager.build_skill_index(tool_names) if tool_names else []

        # Also include definition-only skills (enabled but no Python tool)
        skill_loader = getattr(self.skill_manager, "skill_loader", None)
        if skill_loader and enabled_skills:
            covered_skills: set = set()
            for t in tool_names:
                covered_skills.add(self.skill_manager.resolve_skill_name_for_tool(t) or t)
            for skill_name in enabled_skills:
                if skill_name in covered_skills:
                    continue
                skill_def = skill_loader.skills.get(skill_name)
                if skill_def and skill_def.skill_class is None:
                    meta = self.skill_manager.list_skill_metadata().get(skill_name, {})
                    entries.append({
                        "name": skill_name,
                        "description": meta.get("description", "Context skill — no tool call, interact via bash"),
                        "location": str(skill_def.skill_dir / "SKILL.md") if skill_def.skill_dir else "",
                    })

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

    def _build_definition_only_skill_instructions(
        self,
        enabled_skills: List[str],
        tool_names: List[str],
    ) -> Optional[str]:
        """Inject full SKILL.md for skills that have NO Python tool (definition-only).

        These skills never appear in ``tool_names`` so ``_build_relevant_skill_instructions``
        never injects them.  Without their content the model can't know they exist and
        will fall back to generic solutions.
        """
        if not self.skill_manager or not enabled_skills:
            return None

        # Resolve which skill-names are already covered by Python tools
        covered: set = set()
        for t in tool_names:
            resolved = self.skill_manager.resolve_skill_name_for_tool(t) or t
            covered.add(resolved)
            covered.add(t)

        sections = []
        skill_loader = getattr(self.skill_manager, "skill_loader", None)
        if skill_loader is None:
            return None

        for skill_name in enabled_skills:
            if skill_name in covered:
                continue  # already in relevant_skill_instructions
            skill_def = skill_loader.skills.get(skill_name)
            if skill_def is None or skill_def.skill_class is not None:
                continue  # not definition-only
            instructions = self.skill_manager.get_skill_instructions(skill_name)
            if not instructions:
                continue
            compact = instructions.strip()
            if len(compact) > 3500:
                compact = compact[:3500].rstrip() + "\n..."
            sections.append(f"[Context Skill: {skill_name}]\n{compact}")

        if not sections:
            return None
        return (
            "The following skills have been enabled. They have no direct tool call — "
            "interact with them via bash (curl/API) as described in each skill's instructions:\n\n"
            + "\n\n".join(sections)
        )

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

    def _looks_like_tool_inventory_request(self, user_message: str) -> bool:
        text = (user_message or "").strip()
        if not text:
            return False
        return bool(TOOL_INVENTORY_PATTERN.search(text))

    def _build_tool_inventory_answer(self, tools: List[Dict[str, Any]]) -> str:
        if not tools:
            return "当前没有启用任何工具。你可以先在 Skills 面板里勾选想让我使用的技能。"

        tool_names = [tool.get("name", "") for tool in tools if tool.get("name")]
        entries = self.skill_manager.build_skill_index(tool_names) if self.skill_manager else []

        if entries:
            lines = ["当前启用的工具只有这些："]
            for index, item in enumerate(entries, start=1):
                skill_name = item.get("name") or item.get("tool_name") or "unknown"
                tool_name = item.get("tool_name") or ""
                description = (item.get("description") or "").strip()
                label = f"{skill_name} ({tool_name})" if tool_name and tool_name != skill_name else skill_name
                lines.append(f"{index}. {label}：{description or '已启用'}")
            lines.append("如果你想让我使用别的工具，请先在 Skills 面板里勾选它。")
            return "\n".join(lines)

        lines = ["当前启用的工具只有这些："]
        for index, tool_name in enumerate(tool_names, start=1):
            lines.append(f"{index}. {tool_name}")
        lines.append("如果你想让我使用别的工具，请先在 Skills 面板里勾选它。")
        return "\n".join(lines)

    def _build_direct_answer_events(
        self,
        *,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        conversation_history: List[Dict[str, Any]],
        final_answer: str,
    ) -> List[str]:
        conversation_history.append({
            "role": "assistant",
            "content": final_answer,
        })
        chat_sessions[session_id] = conversation_history
        return [
            self._sse({
                "type": "answer_delta",
                "delta": final_answer,
                "session_id": session_id,
            }),
            self._emit_context_state(session_id, conversation_history),
            self._sse({"done": True, "session_id": session_id}),
        ]

    def _tool_names_to_skill_labels(self, tool_names: List[str]) -> List[str]:
        labels: List[str] = []
        seen = set()
        for tool_name in tool_names:
            normalized = (tool_name or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            skill_name = self.skill_manager.resolve_skill_name_for_tool(normalized) if self.skill_manager else None
            if skill_name and skill_name != normalized:
                labels.append(f"{skill_name} ({normalized})")
            else:
                labels.append(skill_name or normalized)
        return labels

    async def _generate_direct_battle_answer(
        self,
        *,
        session_id: str,
        conversation_history: List[Dict[str, Any]],
        current_user_message: str,
        context: str,
        tool_context: str,
        request_context: Dict[str, Any],
        raw_message_parts: List[Dict[str, Any]],
        inline_image_context: str,
        has_inline_images: bool,
        model: Optional[str],
    ) -> Dict[str, Any]:
        prompt_context = self._resolve_prompt_context(
            session_id=session_id,
            conversation_history=conversation_history,
        )
        user_prompt = self._build_compacted_user_prompt(
            current_user_message=current_user_message,
            context=context if not SIMPLE_GREETING_PATTERN.match((current_user_message or "").strip()) else "",
            tool_context=tool_context,
            request_context=request_context if self._should_include_runtime_context(current_user_message) else {},
            historical_summary=prompt_context["historical_summary"],
            recent_summary=prompt_context["recent_summary"],
            recent_turn_transcript=prompt_context["recent_turn_transcript"],
            skill_index_prompt=None,
            relevant_skill_instructions=None,
            tool_guidance=None,
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
            "You are OBS Agent. Answer the user's request directly in natural language. "
            "Do not call tools, do not emit XML or tool-call markup, and do not describe internal tool planning. "
            "Use the provided user prompt as the authoritative working context for this turn."
        )
        historical_image_turns = self._collect_recent_image_turns(
            conversation_history,
            max_turns=min(6, LLM_MAX_RECENT_DIALOG_TURNS),
        )
        messages = [
            {"role": "system", "content": system_prompt},
            *historical_image_turns,
            {
                "role": "user",
                "content": self._compose_user_message_content(
                    user_prompt,
                    self._text_only_message_parts(raw_message_parts) if has_inline_images else raw_message_parts,
                ),
            },
        ]
        response = await self.vllm_client.chat_completion(
            messages=messages,
            temperature=0.5,
            max_tokens=2200,
            stream=False,
            model=model,
        )
        raw_content = ""
        if "choices" in response and response["choices"]:
            raw_content = response["choices"][0].get("message", {}).get("content", "") or ""
        parsed = self._split_thinking_and_answer(raw_content)
        final_answer = parsed["answer_text"].strip() or self._sanitize_visible_text(raw_content).strip()
        if has_inline_images and self._should_use_local_image_fallback(final_answer):
            local_image_answer = self._analyze_inline_images_locally(raw_message_parts)
            if local_image_answer:
                final_answer = local_image_answer
        return {
            "answer": final_answer or "Direct model answer was empty.",
            "thinking": parsed["thinking_text"].strip(),
            "skills_used": [],
        }

    async def _collect_tool_battle_answer(
        self,
        *,
        session_id: str,
        conversation_history: List[Dict[str, Any]],
        permission_mode: str,
        permission_confirmed: bool,
        context: str,
        tool_context: str,
        enabled_skills: List[str],
        request_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        shadow_session_id = f"{session_id}__battle_tools"
        shadow_sessions = {shadow_session_id: [dict(item) for item in conversation_history]}
        answer_parts: List[str] = []
        skills_used: List[str] = []
        task_results: List[Dict[str, Any]] = []
        error_text = ""

        async for chunk in self._native_tool_stream(
            session_id=shadow_session_id,
            chat_sessions=shadow_sessions,
            permission_mode=permission_mode,
            permission_confirmed=permission_confirmed,
            context=context,
            tool_context=tool_context,
            enabled_skills=enabled_skills,
            request_context=request_context,
        ):
            if not chunk.startswith("data: "):
                continue
            try:
                payload = json.loads(chunk[6:].strip())
            except json.JSONDecodeError:
                continue

            if payload.get("type") == "task_start" and payload.get("skill"):
                skills_used.append(str(payload.get("skill")))
            elif payload.get("type") == "task_complete":
                task_results.append({
                    "skill": payload.get("description") or payload.get("task_id"),
                    "success": payload.get("success", False),
                })
            elif payload.get("type") == "answer_delta":
                answer_parts.append(payload.get("delta") or "")
            elif payload.get("error"):
                error_text = str(payload.get("error"))

        final_answer = "".join(answer_parts).strip()
        if not final_answer:
            tail = shadow_sessions.get(shadow_session_id, [])
            if tail and tail[-1].get("role") == "assistant":
                final_answer = str(tail[-1].get("content") or "").strip()
        if not final_answer and error_text:
            final_answer = f"Tool-assisted run failed: {error_text}"

        return {
            "answer": final_answer or "Tool-assisted answer was empty.",
            "skills_used": self._tool_names_to_skill_labels(skills_used),
            "raw_tools_used": skills_used,
            "task_results": task_results,
            "error": error_text,
        }

    async def _judge_battle_winner(
        self,
        *,
        user_message: str,
        direct_answer: str,
        tool_answer: str,
        tool_skills: List[str],
        model: Optional[str],
    ) -> Dict[str, Any]:
        judge_prompt = (
            "You are scoring a real head-to-head answer battle.\n\n"
            f"User request:\n{user_message}\n\n"
            "Candidate A - Direct model answer (no tools)\n"
            f"{direct_answer}\n\n"
            "Candidate B - Tool-assisted answer\n"
            f"Skills used: {', '.join(tool_skills) if tool_skills else 'none'}\n"
            f"{tool_answer}\n\n"
            "Judge factuality, completeness, usefulness, and whether tool use clearly improved the result.\n"
            "Return strict JSON only:\n"
            '{"winner":"A|B|Tie","reason":"short reason","confidence":0.0}'
        )
        try:
            response = await self.vllm_client.chat_completion(
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=0.1,
                max_tokens=220,
                stream=False,
                model=model,
            )
            raw_text = ""
            if "choices" in response and response["choices"]:
                raw_text = response["choices"][0].get("message", {}).get("content", "") or ""
            match = re.search(r"\{[\s\S]*\}", raw_text)
            if match:
                parsed = json.loads(match.group())
                winner = str(parsed.get("winner") or "Tie")
                if winner not in {"A", "B", "Tie"}:
                    winner = "Tie"
                return {
                    "winner": winner,
                    "reason": str(parsed.get("reason") or "").strip() or "Automatic judgement completed.",
                    "confidence": float(parsed.get("confidence") or 0),
                }
        except Exception:
            logger.exception("Battle judgement failed, falling back to heuristic winner")

        direct_len = len((direct_answer or "").strip())
        tool_len = len((tool_answer or "").strip())
        if tool_skills and tool_len >= max(80, int(direct_len * 0.65)):
            return {"winner": "B", "reason": "Tool-assisted answer used real skills and produced a comparably complete result.", "confidence": 0.55}
        if direct_len > tool_len * 1.2:
            return {"winner": "A", "reason": "Direct answer was materially clearer and more complete.", "confidence": 0.51}
        return {"winner": "Tie", "reason": "Both sides were similarly useful.", "confidence": 0.4}

    def _format_battle_report(
        self,
        *,
        direct_result: Dict[str, Any],
        tool_result: Dict[str, Any],
        judgement: Dict[str, Any],
    ) -> str:
        winner_map = {
            "A": "A · Direct Model",
            "B": "B · Tool-Assisted",
            "Tie": "Tie",
        }
        direct_skills = ", ".join(direct_result.get("skills_used") or []) or "None"
        tool_skills = ", ".join(tool_result.get("skills_used") or []) or "None"
        confidence = judgement.get("confidence")
        confidence_text = f"{round(float(confidence) * 100)}%" if isinstance(confidence, (int, float)) else "n/a"
        return (
            "## Battle Result\n"
            f"Winner: **{winner_map.get(judgement.get('winner'), 'Tie')}**\n"
            f"Reason: {judgement.get('reason') or 'No reason returned.'}\n"
            f"Confidence: {confidence_text}\n\n"
            "### A · Direct Model\n"
            f"Corresponding skills: {direct_skills}\n\n"
            f"{(direct_result.get('answer') or '').strip() or 'No answer returned.'}\n\n"
            "### B · Tool-Assisted\n"
            f"Corresponding skills: {tool_skills}\n\n"
            f"{(tool_result.get('answer') or '').strip() or 'No answer returned.'}"
        )

    async def _battle_stream(
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
        async for chunk in self._maybe_compact_conversation(
            session_id=session_id,
            chat_sessions=chat_sessions,
            request_context=request_context,
        ):
            yield chunk

        conversation_history = chat_sessions[session_id].copy()
        rewritten_history = self._rewrite_followup_reference_request(conversation_history)
        rewritten_history = self._rewrite_followup_location_query(rewritten_history)
        current_user_message = rewritten_history[-1]["content"] if rewritten_history else ""
        raw_message_parts = (request_context or {}).get("message_parts") or []
        has_inline_images = self._has_image_parts(raw_message_parts)
        inline_image_context = self._analyze_inline_images_locally(raw_message_parts) if has_inline_images else ""
        selected_model = (request_context or {}).get("model") or None

        yield self._phase("battle", content="Battle mode started: running direct and tool-assisted contenders.")

        direct_result = await self._generate_direct_battle_answer(
            session_id=session_id,
            conversation_history=conversation_history,
            current_user_message=current_user_message,
            context=context,
            tool_context=tool_context,
            request_context=request_context,
            raw_message_parts=raw_message_parts,
            inline_image_context=inline_image_context,
            has_inline_images=has_inline_images,
            model=selected_model,
        )
        yield self._phase("battle", content="Direct contender finished. Running tool-assisted contender.")

        tool_result = await self._collect_tool_battle_answer(
            session_id=session_id,
            conversation_history=conversation_history,
            permission_mode=permission_mode,
            permission_confirmed=permission_confirmed,
            context=context,
            tool_context=tool_context,
            enabled_skills=enabled_skills,
            request_context=request_context,
        )
        yield self._phase("battle", content="Tool-assisted contender finished. Judging winner.")

        judgement = await self._judge_battle_winner(
            user_message=current_user_message,
            direct_answer=direct_result.get("answer") or "",
            tool_answer=tool_result.get("answer") or "",
            tool_skills=tool_result.get("skills_used") or [],
            model=selected_model,
        )
        final_answer = self._format_battle_report(
            direct_result=direct_result,
            tool_result=tool_result,
            judgement=judgement,
        )
        yield self._sse({
            "type": "battle_result",
            "session_id": session_id,
            "winner": judgement.get("winner"),
            "reason": judgement.get("reason"),
            "confidence": judgement.get("confidence"),
            "direct": direct_result,
            "tool_assisted": tool_result,
        })
        for event in self._build_direct_answer_events(
            session_id=session_id,
            chat_sessions=chat_sessions,
            conversation_history=conversation_history,
            final_answer=final_answer,
        ):
            yield event

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
        yield self._emit_context_state(session_id, conversation_history, working_messages=final_messages)
        yield self._sse({"done": True, "session_id": session_id})

    def _build_direct_shell_command(self, user_message: str) -> Optional[str]:
        text = (user_message or "").strip().lower()
        if not text:
            return None

        if any(token in text for token in ["家目录", "home目录", "home directory", "home folder", "~"]):
            return "cd ~ && pwd && /bin/ls -la"
        if any(token in text for token in ["当前目录", "current directory", "workspace", "工作区", "项目目录", "repo", "repository"]):
            return "pwd && /bin/ls -la"
        if any(token in text for token in ["有什么文件", "有哪些文件", "列出文件", "看看文件", "目录下"]) and "bash" in WRITE_CAPABLE_TOOLS:
            return "pwd && /bin/ls -la"
        return None

    def _looks_like_directory_listing_output(self, output: str) -> bool:
        text = (output or "").strip()
        if not text:
            return False
        if "Command not allowed for security reasons" in text:
            return False
        if text.lower().startswith("error:"):
            return False
        return bool(DIRECTORY_LISTING_PATTERN.search(text))

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

    def _normalize_reference_url(self, raw_url: str) -> str:
        text = (raw_url or "").strip().rstrip("，。；;,)")
        if text.startswith("://"):
            return f"http{text}"
        if text.startswith("www."):
            return f"http://{text}"
        if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?/", text):
            return f"http://{text}"
        if re.match(r"^localhost(?::\d+)?/", text, re.IGNORECASE):
            return f"http://{text}"
        return text

    def _extract_reference_urls(self, text: str) -> List[str]:
        return [
            self._normalize_reference_url(match.group(1))
            for match in URL_LIKE_PATTERN.finditer(text or "")
        ]

    def _rewrite_inline_url_request(self, user_message: str) -> str:
        text = (user_message or "").strip()
        urls = self._extract_reference_urls(text)
        if not urls:
            return text

        normalized = text
        for url in urls:
            normalized = normalized.replace(url.replace("http://", "", 1) if url.startswith("http://") and url[7:] in normalized else url, url)

        remainder = normalized
        for raw in URL_LIKE_PATTERN.findall(normalized):
            remainder = remainder.replace(raw, " ")
        remainder = re.sub(r"\s+", " ", remainder).strip(" ，。；;")
        if not remainder:
            return normalized

        primary_url = urls[0]
        if WEB_ACTION_PATTERN.search(remainder) or len(remainder) <= 24:
            return f"打开这个地址 {primary_url}，然后{remainder}。"
        return f"围绕这个地址 {primary_url} 处理下面的请求：{remainder}"

    def _rewrite_followup_reference_request(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        rewritten = [dict(item) for item in messages]
        latest = rewritten[-1]
        if latest.get("role") != "user":
            return rewritten

        latest_text = self._rewrite_inline_url_request((latest.get("content") or "").strip())
        latest["content"] = latest_text
        if not latest_text:
            return rewritten

        if self._extract_reference_urls(latest_text):
            return rewritten
        if len(latest_text) > 80 or not WEB_ACTION_PATTERN.search(latest_text):
            return rewritten
        if not WEB_REFERENCE_PATTERN.search(latest_text):
            return rewritten

        for item in reversed(rewritten[:-1]):
            if item.get("role") != "user":
                continue
            previous_text = (item.get("content") or "").strip()
            urls = self._extract_reference_urls(previous_text)
            if not urls:
                continue
            previous_url = urls[0]
            latest["content"] = f"打开上条消息里的地址 {previous_url}，然后{latest_text}。"
            return rewritten

        return rewritten

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

        return tools

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
        elif self._extract_reference_urls(user_message) or (WEB_ACTION_PATTERN.search(user_message or "") and WEB_REFERENCE_PATTERN.search(user_message or "")):
            preferred_names.extend(["computer", "advanced_web_search", "web_search"])
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
        if (self._extract_reference_urls(user_message) or (WEB_ACTION_PATTERN.search(user_message or "") and WEB_REFERENCE_PATTERN.search(user_message or ""))) and "computer" in tool_names:
            guidance = (
                "This request references a web address, page, or in-page action. Prefer the computer tool to open the page, "
                "inspect it visually, and then interact with the page. Use search only if the page cannot be opened or you need outside context."
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

        if CODE_WRITE_PATTERN.search(user_message or ""):
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
            tool_result_str = str(result.content or "") if result.success else (result.error or result.content or "Unknown error")
            success = result.success
        except Exception as e:
            tool_result_str = f"Error: {e}"
            success = False

        if not success and self._looks_like_directory_listing_output(tool_result_str):
            success = True

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

    def _pick_direct_readonly_tool(self, tools: List[Dict[str, Any]], user_message: str) -> Optional[str]:
        tool_names = {tool.get("name") for tool in tools if tool.get("name")}
        text = (user_message or "").strip()
        if not text:
            return None
        if CODE_WRITE_PATTERN.search(text) or CODE_HINT_PATTERN.search(text) or COMPUTER_HINT_PATTERN.search(text):
            return None
        if WEATHER_HINT_PATTERN.search(text):
            if "weather" in tool_names:
                return "weather"
            if "advanced_web_search" in tool_names:
                return "advanced_web_search"
            if "web_search" in tool_names:
                return "web_search"
            return None
        if FINANCE_HINT_PATTERN.search(text) or NEWS_HINT_PATTERN.search(text) or RUNTIME_CONTEXT_PATTERN.search(text):
            if "advanced_web_search" in tool_names:
                return "advanced_web_search"
            if "web_search" in tool_names:
                return "web_search"
        return None

    def _build_direct_readonly_args(
        self,
        *,
        tool_name: str,
        user_message: str,
        request_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        location = request_context.get("location") or {}
        if tool_name == "weather":
            args: Dict[str, Any] = {}
            if location.get("city"):
                args["city"] = location.get("city")
            elif location.get("region"):
                args["city"] = location.get("region")
            if location.get("lat") is not None and location.get("lon") is not None:
                args.setdefault("lat", location.get("lat"))
                args.setdefault("lon", location.get("lon"))
            return args

        return self._augment_tool_args(
            tool_name=tool_name,
            tool_args={"query": user_message},
            request_context=request_context,
            user_message=user_message,
        )

    def _pick_readonly_search_fallback_tool(self, tools: List[Dict[str, Any]]) -> Optional[str]:
        tool_names = {tool.get("name") for tool in tools if tool.get("name")}
        if "advanced_web_search" in tool_names:
            return "advanced_web_search"
        if "web_search" in tool_names:
            return "web_search"
        return None

    def _looks_like_missing_weather_location_error(self, error_text: str) -> bool:
        return bool(WEATHER_LOCATION_REQUIRED_PATTERN.search((error_text or "").strip()))

    def _build_weather_search_fallback_query(self, user_message: str, request_context: Dict[str, Any]) -> str:
        location = request_context.get("location") or {}
        loc_parts = [part for part in [location.get("city"), location.get("region"), location.get("country_name")] if part]
        if loc_parts:
            return f"{' '.join(loc_parts)} {user_message}".strip()
        return user_message

    async def _maybe_handle_direct_readonly_request(
        self,
        *,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        conversation_history: List[Dict[str, Any]],
        user_message: str,
        tools: List[Dict[str, Any]],
        request_context: Dict[str, Any],
        model: Optional[str],
    ) -> AsyncGenerator[str, None]:
        tool_name = self._pick_direct_readonly_tool(tools, user_message)
        if not tool_name:
            return

        skill = self.skill_manager.skills.get(tool_name) if self.skill_manager else None
        if skill is None:
            return

        task_id = "task_1"
        yield self._phase("fast_path", content=f"Using direct {tool_name} path.")

        active_tool_name = tool_name
        active_skill = skill
        used_search_fallback = False
        tool_args = self._build_direct_readonly_args(
            tool_name=tool_name,
            user_message=user_message,
            request_context=request_context,
        )

        if tool_name == "weather" and not tool_args:
            fallback_tool_name = self._pick_readonly_search_fallback_tool(tools)
            fallback_skill = self.skill_manager.skills.get(fallback_tool_name) if fallback_tool_name and self.skill_manager else None
            if fallback_tool_name and fallback_skill is not None:
                active_tool_name = fallback_tool_name
                active_skill = fallback_skill
                used_search_fallback = True
                tool_args = self._augment_tool_args(
                    tool_name=fallback_tool_name,
                    tool_args={"query": self._build_weather_search_fallback_query(user_message, request_context)},
                    request_context=request_context,
                    user_message=user_message,
                )

        yield self._sse({
            "type": "task_start",
            "task_id": task_id,
            "description": f"Execute {active_tool_name}",
            "skill": active_tool_name,
            "action": "tool",
        })

        try:
            result = await active_skill.execute(**tool_args)
            tool_result_str = str(result.content) if result.success else f"Error: {result.error}"
            success = result.success
        except Exception as exc:
            tool_result_str = f"Error: {exc}"
            success = False

        if (
            not success
            and active_tool_name == "weather"
            and self._looks_like_missing_weather_location_error(tool_result_str)
        ):
            fallback_tool_name = self._pick_readonly_search_fallback_tool(tools)
            fallback_skill = self.skill_manager.skills.get(fallback_tool_name) if fallback_tool_name and self.skill_manager else None
            if fallback_tool_name and fallback_skill is not None:
                yield self._sse({
                    "type": "task_complete",
                    "task_id": task_id,
                    "success": False,
                    "content": tool_result_str[:400] + "..." if len(tool_result_str) > 400 else tool_result_str,
                    "description": "Execute weather",
                })
                task_id = "task_2"
                active_tool_name = fallback_tool_name
                active_skill = fallback_skill
                used_search_fallback = True
                tool_args = self._augment_tool_args(
                    tool_name=fallback_tool_name,
                    tool_args={"query": self._build_weather_search_fallback_query(user_message, request_context)},
                    request_context=request_context,
                    user_message=user_message,
                )
                yield self._sse({
                    "type": "task_start",
                    "task_id": task_id,
                    "description": f"Execute {active_tool_name}",
                    "skill": active_tool_name,
                    "action": "tool",
                })
                try:
                    result = await active_skill.execute(**tool_args)
                    tool_result_str = str(result.content) if result.success else f"Error: {result.error}"
                    success = result.success
                except Exception as exc:
                    tool_result_str = f"Error: {exc}"
                    success = False

        trunc_res = tool_result_str[:400] + "..." if len(tool_result_str) > 400 else tool_result_str
        yield self._sse({
            "type": "task_complete",
            "task_id": task_id,
            "success": success,
            "content": trunc_res,
            "description": f"Execute {active_tool_name}",
        })

        if not success:
            cleaned_error = tool_result_str.replace("Error:", "").strip()
            if active_tool_name == "weather" and self._looks_like_missing_weather_location_error(cleaned_error):
                final_answer = "我还没拿到可用的位置，所以暂时不能直接查你本地的天气。你告诉我城市名，比如“上海天气”或“北京今天天气”，我就能马上给你结果。"
            else:
                final_answer = (
                    f"我尝试直接调用 `{active_tool_name}` 获取实时结果，但这次失败了："
                    f"{cleaned_error}"
                )
            for event in self._build_direct_answer_events(
                session_id=session_id,
                chat_sessions=chat_sessions,
                conversation_history=conversation_history,
                final_answer=final_answer,
            ):
                yield event
            return

        if used_search_fallback:
            final_answer = tool_result_str.strip() or "我已经拿到实时搜索结果。"
            for event in self._build_direct_answer_events(
                session_id=session_id,
                chat_sessions=chat_sessions,
                conversation_history=conversation_history,
                final_answer=final_answer,
            ):
                yield event
            return

        messages = [
            {
                "role": "system",
                "content": (
                    "You are OBS Agent. A real tool result is already available below. "
                    "Answer directly from that result. Do not call any more tools. "
                    "Keep the answer fast, concise, and focused on what matters most."
                ),
            },
            {"role": "user", "content": user_message},
            {"role": "tool", "name": active_tool_name, "content": tool_result_str},
        ]
        async for chunk in self._stream_final_answer_without_tools(
            session_id=session_id,
            chat_sessions=chat_sessions,
            conversation_history=conversation_history,
            messages=messages,
            instruction=(
                "请直接根据上面的实时工具结果给出最终回答。"
                "要求：1. 先说结论；2. 如果是行情/新闻/天气，给出最关键的数字或变化；"
                "3. 不要继续调用工具；4. 不要输出内部执行说明。"
            ),
            model=model,
        ):
            yield chunk
        return

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

        recent_turn_count = min(LLM_MAX_RECENT_DIALOG_TURNS, RECENT_TURNS_VERBATIM, len(turns))
        recent_turns = turns[-recent_turn_count:]
        historical_turns = turns[:-recent_turn_count]
        before_percent = self._estimate_context_percent(original)
        should_emit_notice = before_percent >= AUTOCOMPACT_THRESHOLD

        if not should_emit_notice:
            return

        yield self._phase(
            "compression_start",
            session_id=session_id,
            before_percent=before_percent,
            target_percent=40,
            content="Compressing conversation context with model summaries...",
        )

        cache = self.session_context_cache.setdefault(session_id, {})
        historical_summary = cache.get("historical_summary", "")
        # recent_summary is intentionally skipped: the last RECENT_TURNS_VERBATIM turns
        # are always kept verbatim via recent_turn_transcript, so summarising them again
        # would just waste tokens and introduce information loss.

        historical_serialized = self._serialize_turns(historical_turns) if historical_turns else ""
        recent_serialized = self._serialize_turns(recent_turns) if recent_turns else ""  # kept for signature only

        historical_signature = self._signature_for_text(historical_serialized) if historical_serialized else ""
        recent_signature = self._signature_for_text(recent_serialized) if recent_serialized else ""

        if historical_serialized and cache.get("historical_signature") != historical_signature:
            try:
                summary_chunks: List[str] = []
                async for chunk in self._chunked_summarize(
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

        # Do NOT summarise recent turns — they are stored verbatim.
        # Update the recent_signature so _resolve_prompt_context can detect staleness.
        if recent_signature:
            cache["recent_signature"] = recent_signature
            cache.pop("recent_summary", None)   # clear any stale summary

        if False:  # dead branch kept for linter — old recent-summary block removed
            summary_chunks = []
            async for chunk in self._chunked_summarize(
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
                    pass  # dead branch

        cache["recent_turn_count"] = recent_turn_count
        # Estimate post-compression size: historical summary + verbatim recent turns + current user msg
        recent_verbatim = self._serialize_turns(recent_turns) if recent_turns else ""
        after_basis = [
            {"role": "system", "content": "OBS Agent system prompt"},
            {
                "role": "user",
                "content": "\n\n".join(
                    part for part in [
                        historical_summary.strip(),
                        recent_verbatim.strip(),
                        (original[-1].get("content") or "").strip(),
                    ] if part
                ),
            },
        ]
        after_percent = self._estimate_context_percent(after_basis)

        yield self._phase(
            "compression_complete",
            session_id=session_id,
            before_percent=before_percent,
            after_percent=after_percent,
            content="Conversation context compressed into historical and recent summaries.",
        )

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
                    enabled_skills=enabled_skills or [],
                ):
                    yield chunk
                return

            if effective_mode == "battle":
                async for chunk in self._battle_stream(
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
            error_text = str(e).strip() or repr(e)
            error_type = type(e).__name__
            tb = traceback.format_exc()
            last_line = tb.strip().rsplit("\n", 1)[-1].strip() if tb else error_text
            # Always surface the root exception to the client — do not replace with vague copy.
            detail_line = last_line if last_line and last_line not in error_text else ""
            combined = error_text if not detail_line else f"{error_text}\n↳ {detail_line}"
            yield self._sse({
                "error": combined,
                "error_type": error_type,
                "error_detail": last_line,
                "done": True,
                "session_id": session_id,
            })

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
        plan_id = str(uuid.uuid4())
        yield self._sse({
            "type": "plan",
            "plan_id": plan_id,
            "plan": plan.to_dict(),
            "task_graph": task_graph.to_dict(),
            "awaiting_approval": True,
        })

        summary_lines = ["Execution plan created:"]
        for task in task_graph.to_dict().get("tasks", []):
            description = task.get("description") or task.get("task_id")
            summary_lines.append(f"- {task.get('task_id')}: {description}")

        final_text = "\n".join(summary_lines)
        chat_sessions[session_id].append({"role": "assistant", "content": final_text})
        yield self._sse({"content": final_text, "done": True, "session_id": session_id})

    async def _execution_engine_stream(
        self,
        *,
        user_message: str,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        enabled_skills: Optional[List[str]] = None,
    ) -> AsyncGenerator[str, None]:
        async for event in self.execution_engine.execute_user_request(
            user_message=user_message,
            session_id=session_id,
            chat_history=chat_sessions.get(session_id, []),
            allowed_skill_names=enabled_skills or None,
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
        conversation_history = chat_sessions[session_id].copy()
        rewritten_history = self._rewrite_followup_reference_request(conversation_history)
        rewritten_history = self._rewrite_followup_location_query(rewritten_history)
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

        yield self._phase("prep_context")
        if self._looks_like_tool_inventory_request(current_user_message):
            direct_answer_events = self._build_direct_answer_events(
                session_id=session_id,
                chat_sessions=chat_sessions,
                conversation_history=conversation_history,
                final_answer=self._build_tool_inventory_answer(tools),
            )
            for event in direct_answer_events:
                yield event
            return
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
        handled_direct_readonly = False
        async for direct_chunk in self._maybe_handle_direct_readonly_request(
            session_id=session_id,
            chat_sessions=chat_sessions,
            conversation_history=conversation_history,
            user_message=current_user_message,
            tools=tools,
            request_context=request_context,
            model=selected_model,
        ):
            handled_direct_readonly = True
            yield direct_chunk
        if handled_direct_readonly:
            return

        async for chunk in self._maybe_compact_conversation(
            session_id=session_id,
            chat_sessions=chat_sessions,
            request_context=request_context,
        ):
            yield chunk

        conversation_history = chat_sessions[session_id].copy()
        rewritten_history = self._rewrite_followup_reference_request(conversation_history)
        rewritten_history = self._rewrite_followup_location_query(rewritten_history)
        current_user_message = rewritten_history[-1]["content"] if rewritten_history else ""
        yield self._phase("prep_route")
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
        skill_index_prompt = self._build_skill_index_prompt(tool_names, enabled_skills or []) if tools else None
        relevant_skill_instructions = self._build_relevant_skill_instructions(tool_names) if tools else None
        # Append instructions for definition-only skills (no Python tools) that are enabled
        definition_only_instructions = self._build_definition_only_skill_instructions(
            enabled_skills or [], tool_names
        )
        if definition_only_instructions:
            relevant_skill_instructions = (
                f"{relevant_skill_instructions}\n\n{definition_only_instructions}"
                if relevant_skill_instructions
                else definition_only_instructions
            )
        prompt_context = self._resolve_prompt_context(
            session_id=session_id,
            conversation_history=conversation_history,
        )
        user_prompt = self._build_compacted_user_prompt(
            current_user_message=current_user_message,
            context=context if not is_simple_greeting else "",
            tool_context=tool_context,
            request_context=request_context if self._should_include_runtime_context(current_user_message) else {},
            historical_summary=prompt_context["historical_summary"],
            recent_summary=prompt_context["recent_summary"],
            recent_turn_transcript=prompt_context["recent_turn_transcript"],
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
            "and on-demand skill instructions. Do not ask for the same background again unless necessary.\n\n"
            "TASK LIST FORMAT: For complex multi-step tasks (3+ distinct steps), output a concise task plan "
            "at the very beginning of your first response using this exact format on its own line:\n"
            "<obs:todo>Step one|Step two|Step three</obs:todo>\n"
            "As you complete each step, emit on its own line (no surrounding text on that line): "
            "<obs:done>N</obs:done>  (N is the 0-based index of the completed step).\n"
            "These tags are consumed by the UI and hidden from the user — do NOT explain or mention them."
        )
        if system_prompts:
            system_prompt = f"{system_prompt}\n\n" + "\n".join(system_prompts)
        historical_image_turns = self._collect_recent_image_turns(
            conversation_history,
            max_turns=min(6, LLM_MAX_RECENT_DIALOG_TURNS),
        )
        if historical_image_turns:
            system_prompt = (
                f"{system_prompt}\n\n"
                "Previous conversation turns containing images are included above the current user message. "
                "Refer to them when the user asks about past images."
            )
        messages = [
            {"role": "system", "content": system_prompt},
            *historical_image_turns,
            {
                "role": "user",
                "content": self._compose_user_message_content(
                    user_prompt,
                    self._text_only_message_parts(raw_message_parts) if has_inline_images else raw_message_parts,
                ),
            },
        ]
        yield self._phase("prep_prompt")
        yield self._emit_context_state(session_id, messages, model_name=selected_model)

        max_iterations = 30
        tool_step_index = 0
        completed = False
        todo_state: Dict[str, Any] = {}  # tracks emitted todo list / done indices

        for iteration in range(max_iterations):
            logger.info(f"Streaming Agent Loop Iteration {iteration + 1}")

            if iteration > 0 and self._estimate_context_percent(messages, selected_model) >= MICROCOMPACT_THRESHOLD:
                messages = self._microcompact_messages(messages)
                yield self._sse({
                    "type": "microcompact",
                    "session_id": session_id,
                    "iteration": iteration,
                    "context_percent": self._estimate_context_percent(messages, selected_model),
                })

            assistant_message = {"role": "assistant", "content": ""}
            tool_calls = []
            emitted_thinking_len = 0
            emitted_answer_len = 0
            _stream_exc: Optional[Exception] = None
            try:
                yield self._phase("prep_model")
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
                    if isinstance(chunk, dict) and "__obs_phase" in chunk:
                        ph = chunk.get("__obs_phase") or {}
                        if ph.get("kind") == "rate_limit_wait":
                            st = ph.get("http_status", "?")
                            msg = (
                                f"上游返回 {st}（繁忙/限流），"
                                f"第 {ph.get('attempt')}/{ph.get('max_attempts')} 次重试，"
                                f"约 {ph.get('delay_sec')}s 后再请求…"
                            )
                            yield self._sse({
                                "type": "phase",
                                "content": msg,
                                "transient": True,
                                "session_id": session_id,
                            })
                        continue
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
                            # Emit todo SSE events for any new obs: tags found
                            for todo_event in self._emit_todo_events(
                                assistant_message["content"], session_id, todo_state
                            ):
                                yield todo_event
                            # Strip obs: control tags before sending display text
                            clean_delta = self._strip_obs_tags(parsed["answer_delta"])
                            emitted_answer_len += len(parsed["answer_delta"])
                            if clean_delta:
                                yield self._sse({
                                    "type": "answer_delta",
                                    "delta": clean_delta,
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
                _stream_exc = exc   # preserve original error so we can surface it if model stays silent
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
                if not final_answer and any(item.get("role") == "tool" for item in messages):
                    yield self._sse({
                        "type": "phase",
                        "content": "Synthesizing final answer…",
                        "transient": True,
                        "session_id": session_id,
                    })
                    async for chunk in self._stream_final_answer_without_tools(
                        session_id=session_id,
                        chat_sessions=chat_sessions,
                        conversation_history=conversation_history,
                        messages=messages,
                        instruction=(
                            "请基于上面的工具执行结果给出最终自然语言回答。"
                            "要求：1. 说明已经完成了什么；2. 如果还有下一步，明确告诉用户；"
                            "3. 不要继续调用工具；4. 不要输出 XML、调试字段或内部规划说明；"
                            "5. 不要把诸如 'Screenshot taken successfully' 这类占位结果直接当成最终答复。"
                        ),
                        model=selected_model,
                    ):
                        yield chunk
                    completed = True
                    break
                if not final_answer:
                    # Try a meaningful tool-result fallback first
                    fallback = self._build_tool_fallback_answer(messages)
                    has_tool_results = any(item.get("role") == "tool" for item in messages)
                    if has_tool_results and fallback:
                        # Emit the tool-result summary so the user sees something
                        yield self._sse({"type": "answer_delta", "delta": fallback, "session_id": session_id})
                        final_answer = fallback
                    else:
                        # Model returned nothing at all — surface the original error verbatim
                        raw_cause = str(_stream_exc) if _stream_exc else "服务端未发送任何文字内容"
                        err_msg = f"模型返回了空响应\n{raw_cause}"
                        logger.error(f"Empty model response for session {session_id}: {raw_cause}")
                        yield self._sse({
                            "error": err_msg,
                            "error_type": type(_stream_exc).__name__ if _stream_exc else "EmptyModelResponse",
                            "done": True,
                            "session_id": session_id,
                        })
                        completed = True
                        break
                conversation_history.append({
                    "role": "assistant",
                    "content": final_answer,
                })
                chat_sessions[session_id] = conversation_history
                yield self._emit_context_state(session_id, conversation_history, working_messages=messages, model_name=selected_model)
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

                if len(tool_result_str) > TOOL_MESSAGE_SOFT_CHAR_LIMIT:
                    tool_result_str = (
                        tool_result_str[:TOOL_MESSAGE_SOFT_CHAR_LIMIT]
                        + "\n[... tool output truncated for API size — see server logs for full output]"
                    )

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
                    yield self._sse({
                        "type": "phase",
                        "content": "Synthesizing answer…",
                        "transient": True,
                        "session_id": session_id,
                    })
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
        yield self._emit_context_state(session_id, conversation_history, working_messages=messages, model_name=selected_model)
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

        return tools

    # ── todo-list tag helpers ──────────────────────────────────────────────
    _TODO_RE = re.compile(r"<obs:todo>(.*?)</obs:todo>", re.DOTALL)
    _DONE_RE = re.compile(r"<obs:done>(\d+)</obs:done>")
    _OBS_TAG_RE = re.compile(r"<obs:(?:todo|done)>.*?</obs:(?:todo|done)>", re.DOTALL)

    @staticmethod
    def _strip_obs_tags(text: str) -> str:
        """Remove <obs:todo> and <obs:done> control tags from display text."""
        cleaned = StreamingAgent._OBS_TAG_RE.sub("", text)
        # Collapse consecutive blank lines left by stripped tags
        return re.sub(r"\n{3,}", "\n\n", cleaned)

    def _emit_todo_events(
        self,
        full_text: str,
        session_id: str,
        todo_state: Dict[str, Any],
    ):
        """Scan accumulated text for new obs:todo / obs:done tags; yield SSE payloads."""
        events = []
        if not todo_state.get("list_emitted"):
            m = self._TODO_RE.search(full_text)
            if m:
                items = [s.strip() for s in m.group(1).split("|") if s.strip()]
                if items:
                    todo_state["list_emitted"] = True
                    todo_state["count"] = len(items)
                    events.append(self._sse({
                        "type": "todo_list",
                        "items": items,
                        "session_id": session_id,
                    }))
        # Check for done markers
        for m in self._DONE_RE.finditer(full_text):
            idx = int(m.group(1))
            if idx not in todo_state.get("done_set", set()):
                todo_state.setdefault("done_set", set()).add(idx)
                events.append(self._sse({
                    "type": "todo_done",
                    "index": idx,
                    "session_id": session_id,
                }))
        return events

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
