import json
import re
from datetime import datetime
from typing import Dict, List, Any, AsyncGenerator, Optional
from loguru import logger


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

    def _split_thinking_and_answer(self, raw_text: str) -> Dict[str, Any]:
        open_tag = "<think>"
        close_tag = "</think>"
        open_index = raw_text.find(open_tag)

        if open_index == -1:
            return {
                "has_thinking": False,
                "thinking_text": "",
                "answer_text": raw_text,
                "in_thinking": False,
            }

        before_open = raw_text[:open_index]
        after_open = raw_text[open_index + len(open_tag):]
        close_index = after_open.find(close_tag)

        if close_index == -1:
            return {
                "has_thinking": True,
                "thinking_text": after_open,
                "answer_text": before_open,
                "in_thinking": True,
            }

        thinking_text = after_open[:close_index]
        after_close = after_open[close_index + len(close_tag):]
        return {
            "has_thinking": True,
            "thinking_text": thinking_text,
            "answer_text": f"{before_open}{after_close}",
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
            content = (entry.get("content") or "").strip()
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
        text_size = sum(len((item.get("content") or "")) for item in messages if isinstance(item.get("content"), str))
        return min(98, max(1, round(text_size / 140) + 4))

    def _emit_context_state(self, session_id: str, messages: List[Dict[str, Any]]) -> str:
        return self._sse({
            "type": "context_state",
            "session_id": session_id,
            "context_percent": self._estimate_context_percent(messages),
        })

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
            content = (entry.get("content") or "").strip()
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
        })
        raw_content = ""
        synthesis_attempts = 3
        for attempt in range(1, synthesis_attempts + 1):
            try:
                response = await self.vllm_client.chat_completion(
                    messages=final_messages,
                    temperature=0.4,
                    max_tokens=2000,
                    stream=False,
                )
                if "choices" in response and response["choices"]:
                    raw_content = response["choices"][0].get("message", {}).get("content", "") or ""
                    yield self._sse_log(session_id, "final_synthesis", "response", {
                        "attempt": attempt,
                        "message": response["choices"][0].get("message", {}),
                    })
                if raw_content.strip():
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
        if self._looks_like_local_shell_request(user_message, tool_context) and "bash" in tool_names:
            return (
                "This is a local machine or workspace request. You can directly inspect local files and directories "
                "with the bash tool. Prefer bash for listing files, reading directories, pwd, ls, find, cat, and grep. "
                "Do not use web search for local filesystem questions, and do not claim you lack file access when bash is available."
            )
        if WEATHER_HINT_PATTERN.search(user_message or "") and "weather" in tool_names:
            return (
                "This appears to be a weather or temperature question. Prefer the weather tool first. "
                "Only use search if the weather tool fails or the question requires broader web context."
            )
        return None

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
        if permission_mode == "ask" and not permission_confirmed:
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
        if len(original) < 4:
            return

        before_percent = self._estimate_context_percent(original)
        if before_percent < 80:
            return

        yield self._sse({
            "type": "compression_start",
            "session_id": session_id,
            "before_percent": before_percent,
            "target_percent": 40,
            "content": "Compressing conversation context to keep the session responsive...",
        })

        keep_tail = 4
        prefix = original[:-keep_tail]
        suffix = original[-keep_tail:]
        if not prefix:
            return

        summary_request = [
            {
                "role": "system",
                "content": (
                    "Summarize the earlier conversation into a compact working memory. "
                    "Preserve user goals, constraints, decisions, open issues, dates, locations, and any tool results that still matter. "
                    "Keep it concise and factual."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(prefix, ensure_ascii=False),
            },
        ]
        yield self._sse_log(session_id, "compression", "request", {
            "messages": summary_request,
            "stream": False,
            "max_tokens": 900,
            "temperature": 0.2,
        })

        summary_text = ""
        try:
            response = await self.vllm_client.chat_completion(
                messages=summary_request,
                temperature=0.2,
                max_tokens=900,
                stream=False,
            )
            if "choices" in response and response["choices"]:
                summary_text = response["choices"][0].get("message", {}).get("content", "") or ""
                yield self._sse_log(session_id, "compression", "response", {
                    "message": response["choices"][0].get("message", {}),
                })
        except Exception:
            logger.exception("Conversation compression failed")

        if not summary_text.strip():
            yield self._sse({
                "type": "compression_complete",
                "session_id": session_id,
                "before_percent": before_percent,
                "after_percent": before_percent,
                "content": "Context compression skipped because a compact summary could not be generated.",
            })
            return

        compacted = [{
            "role": "system",
            "content": f"[Compressed conversation memory]\n{summary_text.strip()}",
        }, *suffix]
        chat_sessions[session_id] = compacted
        after_percent = self._estimate_context_percent(compacted)
        yield self._sse({
            "type": "compression_complete",
            "session_id": session_id,
            "before_percent": before_percent,
            "after_percent": after_percent,
            "content": "Conversation context compressed.",
        })

    def _extract_tool_calls_from_response_message(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        tool_calls = []
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            tool_calls.append({
                "id": tool_call.get("id", ""),
                "type": tool_call.get("type", "function"),
                "function": {
                    "name": function.get("name", "") or "",
                    "arguments": function.get("arguments", "") or "",
                },
            })
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
        async for chunk in self._maybe_compact_conversation(
            session_id=session_id,
            chat_sessions=chat_sessions,
            request_context=request_context,
        ):
            yield chunk

        conversation_history = chat_sessions[session_id].copy()
        messages = self._rewrite_followup_location_query(conversation_history)
        current_user_message = conversation_history[-1]["content"] if conversation_history else ""
        is_simple_greeting = bool(SIMPLE_GREETING_PATTERN.match((current_user_message or "").strip()))
        tools = self._get_allowed_tools(permission_mode, permission_confirmed, enabled_skills)
        if is_simple_greeting:
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
        if conversation_history:
            yield self._emit_context_state(session_id, conversation_history)
        system_prompts = []
        if context and not is_simple_greeting:
            system_prompts.append(
                "You are OBS Agent. Respect the current working context while answering. "
                f"Current tool context: {tool_context}. "
                f"Guidance: {context}"
            )
        tool_guidance = self._build_request_tool_guidance(current_user_message, tool_context, tools)
        if tool_guidance:
            system_prompts.append(tool_guidance)
        if tools:
            system_prompts.append(
                "You are OBS Agent. When tools are available, use them for requests that need real-time, "
                "external, or verifiable information. "
                "For weather, latest news, prices, search, or current status questions, call a suitable tool "
                "first and do not answer by claiming you cannot access live data unless a tool call has already failed."
            )
        elif enabled_skills:
            system_prompts.append(
                "Only the currently selected skills are available in this session. "
                "If a needed tool is not enabled, do not fabricate tool calls, XML tags, or internal invocation markup. "
                "Instead, clearly explain that the required skill is not currently selected."
            )
        if request_context and self._should_include_runtime_context(current_user_message):
            current_date = request_context.get("current_date")
            current_datetime = request_context.get("current_datetime")
            timezone = request_context.get("timezone")
            location = request_context.get("location") or {}
            loc_parts = [part for part in [location.get("city"), location.get("region"), location.get("country_name")] if part]
            location_text = ", ".join(loc_parts) if loc_parts else "unknown"
            system_prompts.append(
                "Use the provided runtime context as ground truth for relative time and location. "
                f"Current date: {current_date or 'unknown'}. "
                f"Current datetime: {current_datetime or 'unknown'}. "
                f"Timezone: {timezone or 'unknown'}. "
                f"Approximate user location: {location_text}. "
                "Interpret references like today / 今日 / 今天 using the exact current date above, "
                "and prefer location-aware results when relevant."
            )
        if tools:
            tool_names = [tool.get("name", "") for tool in tools if tool.get("name")]
            skill_index_prompt = self._build_skill_index_prompt(tool_names)
            if skill_index_prompt:
                system_prompts.append(skill_index_prompt)
            relevant_skill_instructions = self._build_relevant_skill_instructions(tool_names)
            if relevant_skill_instructions:
                system_prompts.append(relevant_skill_instructions)
        if system_prompts:
            # MiniMax rejects tool-enabled streaming requests when multiple system messages are present.
            messages = [{
                "role": "system",
                "content": "\n\n".join(system_prompts),
            }, *messages]

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
                })
                stream_generator = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=tools if tools else None,
                    temperature=0.7,
                    max_tokens=4000,
                    stream=True,
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
                })
                response = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=tools if tools else None,
                    temperature=0.7,
                    max_tokens=4000,
                    stream=False,
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
                yield self._sse_log(session_id, "tool_planning", "response", {
                    "message": assistant_message,
                })
                final_parts = self._split_thinking_and_answer(assistant_message["content"])
                final_answer = final_parts["answer_text"].strip()
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
                tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]

                try:
                    tool_args = json.loads(tool_args_str) if tool_args_str else {}
                except json.JSONDecodeError:
                    tool_args = {}

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

        if permission_mode == "ask" and not permission_confirmed:
            return [tool for tool in tools if tool.get("name") in READ_ONLY_TOOLS]

        return tools

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
