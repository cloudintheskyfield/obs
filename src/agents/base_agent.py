from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from .harness_engine import HarnessEngine


class BaseAgent:
    """所有 Harness Agent 的公共基类。

    提供：
    - vllm_client / skill_manager / harness 的统一初始化
    - system_prompt 从 identity 文件加载
    - _sse: SSE 事件序列化
    - _status: 快捷状态 SSE
    - _find_first_json_object: 从 LLM 原始输出提取第一个 JSON 对象
    - _normalize_string_list: 统一将各种形式的字符串列表规范化
    - _normalize_object_list: 统一将各种形式的对象列表规范化
    - _strip_thinking: 去除 <think>…</think> 思维链标签
    - _append_assistant_message: 向 chat_sessions 追加 assistant 消息
    """

    def __init__(self, role_name: str, vllm_client: Any, skill_manager: Any = None) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt(role_name, "")

    # ─── SSE helpers ───────────────────────────────────────────────────────

    def _sse(self, payload: Dict[str, Any]) -> str:
        """将 payload 序列化为 SSE data 帧。"""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _status(
        self,
        status: str,
        *,
        role: Optional[str] = None,
        title: str = "",
        detail: str = "",
        session_id: str = "",
    ) -> str:
        """快捷返回 agent_step 类型的 SSE 帧。"""
        return self._sse(
            {
                "type": "agent_step",
                "role": role or self.__class__.__name__.replace("Agent", ""),
                "status": status,
                "title": title,
                "detail": detail,
                "session_id": session_id,
            }
        )

    # ─── JSON parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _find_first_json_object(raw: str) -> Optional[Dict[str, Any]]:
        """从字符串中提取第一个完整的 JSON 对象（支持 json_repair）。"""
        from utils.json_utils import safe_loads

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
                    candidate = text[start : idx + 1]
                    try:
                        parsed = safe_loads(candidate)
                    except Exception:
                        return None
                    return parsed if isinstance(parsed, dict) else None
        return None

    # ─── Normalization helpers ─────────────────────────────────────────────

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        """将 str / list[str] / None 统一为 List[str]。"""
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _normalize_object_list(value: Any, *, kind: str) -> List[Dict[str, Any]]:
        """将混合类型列表规范化为 List[Dict]，按 kind 决定字符串的展开方式。"""
        if not isinstance(value, list):
            return []
        out: List[Dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, Mapping):
                out.append(dict(item))
                continue
            text = str(item).strip()
            if not text:
                continue
            if kind == "commands":
                out.append({"command": text})
            elif kind == "smoke_tests":
                out.append(
                    {
                        "id": f"smoke_{index}",
                        "type": "browser",
                        "action": "goto",
                        "target": text,
                        "expect": {"type": "no_fatal_console_error"},
                    }
                )
            elif kind == "research_questions":
                out.append({"id": f"Q{index}", "question": text, "priority": "high"})
            elif kind == "key_findings":
                out.append(
                    {
                        "id": f"F{index}",
                        "question_id": f"Q{index}",
                        "finding": text,
                        "source_ids": [],
                        "confidence": 0.6,
                    }
                )
            elif kind == "implementation_guidance":
                out.append(
                    {"target": "Generator", "guidance": text, "applies_to": "Generator", "risk": "medium"}
                )
            elif kind == "raw_artifacts":
                out.append({"type": "note", "path": text})
            else:
                out.append({"value": text})
        return out

    # ─── Thinking strip ────────────────────────────────────────────────────

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """去除 LLM 输出中的 <think>…</think> 思维链标签及内容。"""
        return re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.IGNORECASE).strip()

    # ─── Chat session helpers ──────────────────────────────────────────────

    @staticmethod
    def _append_assistant_message(
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        session_id: str,
        content: str,
    ) -> None:
        """向 chat_sessions[session_id] 追加一条 assistant 消息。"""
        if not content:
            return
        chat_sessions.setdefault(session_id, []).append(
            {"role": "assistant", "content": content}
        )
