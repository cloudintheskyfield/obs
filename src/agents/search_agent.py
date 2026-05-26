from __future__ import annotations

import json
from utils.json_utils import safe_loads
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .base_agent import BaseAgent
from .harness_engine import HarnessEngine


def _find_first_json_object(raw: str) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = safe_loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:idx + 1]
                try:
                    parsed = safe_loads(candidate)
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_object_list(value: Any, *, kind: str) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: List[Dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, Mapping):
            items.append(dict(item))
            continue
        text = str(item).strip()
        if not text:
            continue
        if kind == "research_questions":
            items.append({"id": f"Q{index}", "question": text, "priority": "high"})
        elif kind == "key_findings":
            items.append({"id": f"F{index}", "question_id": f"Q{index}", "finding": text, "source_ids": [], "confidence": 0.6})
        elif kind == "implementation_guidance":
            items.append({"target": "Generator", "guidance": text, "applies_to": "Generator", "risk": "medium"})
        elif kind == "raw_artifacts":
            items.append({"type": "note", "path": text})
        else:
            items.append({"value": text})
    return items


def _normalize_search_report(raw_obj: Optional[Dict[str, Any]], search_input: Mapping[str, Any], harness: HarnessEngine) -> Dict[str, Any]:
    source: Dict[str, Any] = dict(raw_obj or {})
    task_id = str(source.get("task_id") or search_input.get("task_id") or "task_runtime_001")
    report = {
        "schema_version": str(source.get("schema_version") or "1.0"),
        "task_id": task_id,
        "round_id": int(source.get("round_id") or search_input.get("round_id") or 1),
        "search_id": str(source.get("search_id") or search_input.get("search_id") or "search_001"),
        "query_summary": str(source.get("query_summary") or ""),
        "status": str(source.get("status") or "SUCCESS"),
        "insufficient_evidence": bool(source.get("insufficient_evidence", False)),
        "sources": _normalize_object_list(source.get("sources"), kind="sources"),
        "key_findings": _normalize_object_list(source.get("key_findings"), kind="key_findings"),
        "implementation_guidance": _normalize_object_list(source.get("implementation_guidance"), kind="implementation_guidance"),
        "risks": _normalize_string_list(source.get("risks")),
        "recommended_next_agent": str(source.get("recommended_next_agent") or "Generator"),
        "raw_artifacts": _normalize_object_list(source.get("raw_artifacts"), kind="raw_artifacts"),
    }
    report["display_summary"] = harness.display_summary_for_output("Search", report)
    return report


class SearchAgent(BaseAgent):
    def __init__(self, vllm_client: Any, skill_manager: Any) -> None:
        super().__init__("Search", vllm_client, skill_manager)
        self.last_search_report: Dict[str, Any] = {}

    async def search(
        self,
        session_id: str,
        search_input: Mapping[str, Any],
        *,
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_iterations: int = 6,
    ) -> AsyncGenerator[str, None]:
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Search",
                "status": "running",
                "title": "执行外部资料检索",
                "detail": "按 Search Gate 收集有限的参考资料...",
                "session_id": session_id,
            }
        )

        search_tools = self.harness.filter_tools_for_role("Search", tools)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(dict(search_input), ensure_ascii=False, indent=2)},
        ]

        raw_content = ""
        tool_step = 0
        search_report: Dict[str, Any] = {}

        for iteration in range(max_iterations):
            assistant_message: Dict[str, Any] = {"role": "assistant", "content": ""}
            tool_calls: List[Dict[str, Any]] = []
            try:
                stream = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=search_tools if search_tools else None,
                    temperature=0.1,
                    max_tokens=1800,
                    stream=True,
                    model=model,
                )
                async for chunk in stream:
                    if isinstance(chunk, dict) and "__obs_phase" in chunk:
                        continue
                    if "choices" not in chunk or not chunk["choices"]:
                        continue
                    delta = chunk["choices"][0].get("delta", {})
                    piece = delta.get("content") or ""
                    if piece:
                        raw_content += piece
                        assistant_message["content"] += piece
                        yield self._sse(
                            {
                                "type": "agent_thinking",
                                "agent": "search",
                                "delta": piece,
                                "session_id": session_id,
                            }
                        )
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", len(tool_calls))
                            while len(tool_calls) <= idx:
                                tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            if tc.get("id"):
                                tool_calls[idx]["id"] = tc["id"]
                            if "function" in tc:
                                if tc["function"].get("name"):
                                    tool_calls[idx]["function"]["name"] += tc["function"]["name"]
                                if tc["function"].get("arguments"):
                                    tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]
            except Exception as exc:
                logger.warning(f"SearchAgent iteration {iteration} model error: {exc}")
                search_report = _normalize_search_report(
                    {
                        "status": "FAILED",
                        "insufficient_evidence": True,
                        "key_findings": [],
                        "implementation_guidance": [],
                        "risks": [str(exc)],
                        "recommended_next_agent": "Planner",
                    },
                    search_input,
                    self.harness,
                )
                break

            if not tool_calls:
                search_report = _normalize_search_report(_find_first_json_object(assistant_message["content"]), search_input, self.harness)
                break

            assistant_message["tool_calls"] = tool_calls
            messages.append(dict(assistant_message))

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    raw_args = tc["function"]["arguments"]
                    tool_args = safe_loads(raw_args) if raw_args else {}
                except Exception:
                    tool_args = {}

                tool_step += 1
                task_id = f"search_step_{tool_step}"
                yield self._sse(
                    {
                        "type": "task_start",
                        "task_id": task_id,
                        "description": f"[Search] {tool_name}",
                        "skill": tool_name,
                        "action": "tool",
                        "session_id": session_id,
                    }
                )

                tool_result = ""
                success = False
                try:
                    result = await self.skill_manager.execute_skill(
                        tool_name,
                        **tool_args,
                    )
                    tool_result = (
                        str(result.content)
                        if result.success
                        else f"Error: {result.error}"
                    )
                    success = result.success
                except Exception as exc:
                    tool_result = str(exc)

                yield self._sse(
                    {
                        "type": "task_complete",
                        "task_id": task_id,
                        "success": success,
                        "content": tool_result[:400] + "..." if len(tool_result) > 400 else tool_result,
                        "description": f"[Search] {tool_name}",
                        "session_id": session_id,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", "unknown"),
                        "name": tool_name,
                        "content": tool_result[:8000],
                    }
                )

        self.last_search_report = search_report
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Search",
                "status": "success" if search_report.get("status") != "FAILED" else "error",
                "title": "SearchReport 已生成",
                "detail": search_report.get("query_summary") or "",
                "session_id": session_id,
            }
        )
