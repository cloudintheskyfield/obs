import json
import re
from typing import Dict, List, Any, AsyncGenerator, Optional
from loguru import logger


READ_ONLY_TOOLS = {"web_search"}
WRITE_CAPABLE_TOOLS = {"bash", "str_replace_editor", "computer", "code_sandbox"}


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

    async def chat_stream(
        self,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        *,
        mode: str = "agent",
        permission_mode: str = "ask",
        permission_confirmed: bool = False,
    ) -> AsyncGenerator[str, None]:
        try:
            user_message = chat_sessions[session_id][-1]["content"] if chat_sessions.get(session_id) else ""

            if mode == "plan":
                async for chunk in self._plan_only_stream(
                    user_message=user_message,
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                ):
                    yield chunk
                return

            if mode == "review" and self.execution_engine is not None:
                async for chunk in self._execution_engine_stream(
                    user_message=user_message,
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
            ):
                yield chunk
        except Exception as e:
            logger.error(f"StreamingAgent error: {e}")
            yield self._sse({"error": str(e), "done": True})

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
    ) -> AsyncGenerator[str, None]:
        messages = chat_sessions[session_id].copy()
        tools = self._get_allowed_tools(permission_mode, permission_confirmed)

        max_iterations = 10
        tool_step_index = 0

        for iteration in range(max_iterations):
            logger.info(f"Streaming Agent Loop Iteration {iteration + 1}")
            stream_generator = await self.vllm_client.chat_completion(
                messages=messages,
                tools=tools if tools else None,
                temperature=0.7,
                max_tokens=4000,
                stream=True,
            )

            assistant_message = {"role": "assistant", "content": ""}
            tool_calls = []
            emitted_thinking_len = 0
            emitted_answer_len = 0

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

            if not tool_calls:
                final_parts = self._split_thinking_and_answer(assistant_message["content"])
                messages.append({
                    "role": "assistant",
                    "content": final_parts["answer_text"].strip() or assistant_message["content"],
                })
                chat_sessions[session_id] = messages
                yield self._sse({"done": True, "session_id": session_id})
                break

            normalized_parts = self._split_thinking_and_answer(assistant_message["content"])
            assistant_message["content"] = normalized_parts["answer_text"].strip()
            assistant_message["tool_calls"] = tool_calls
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

    def _get_allowed_tools(self, permission_mode: str, permission_confirmed: bool) -> List[Dict[str, Any]]:
        tools = []
        if self.skill_manager:
            try:
                tools = self.skill_manager.get_anthropic_tools()
            except Exception as e:
                logger.warning(f"Could not get tools: {e}")
                tools = []

        if permission_mode == "plan":
            return []

        if permission_mode == "ask" and not permission_confirmed:
            return [tool for tool in tools if tool.get("name") in READ_ONLY_TOOLS]

        return tools

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
