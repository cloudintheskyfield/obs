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
    - _extract_thinking_summary: 提取思维链的最后一句话作为动态状态详情
    """

    def __init__(self, role_name: str, vllm_client: Any, skill_manager: Any = None) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self._dynamic_status_task = None
        self._latest_dynamic_status = None
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

    def _trigger_dynamic_status(self, role: str, thinking_content: str, default_title: str) -> None:
        """非阻塞触发 UIStatusAgent 获取动态的前端展示状态。"""
        import asyncio
        if not thinking_content:
            return
            
        # 如果上一次请求还在 pending 中，说明我们不应该发起新的请求
        if self._dynamic_status_task and not self._dynamic_status_task.done():
            return
            
        async def _worker():
            try:
                from agents.ui_status_agent import UIStatusAgent
                agent = UIStatusAgent(self.vllm_client)
                result = await agent.generate_status(role, thinking_content, default_title)
                self._latest_dynamic_status = result
            except Exception:
                pass
                
        self._dynamic_status_task = asyncio.create_task(_worker())

    # ─── JSON parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _find_first_json_object(text: str) -> Optional[Dict[str, Any]]:
        """从字符串中提取第一个合法的 JSON 对象。"""
        from utils.json_utils import safe_loads
        if not text:
            return None
            
        # 1. 尝试去除 <think> 标签，避免解析里面的举例 JSON
        import re
        cleaned_text = re.sub(r"<(think|thinking)>[\s\S]*?</\1>", "", text, flags=re.IGNORECASE).strip()
        if not cleaned_text:
            cleaned_text = text # fallback

        # 2. 优先提取 markdown json 代码块
        json_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_text, re.IGNORECASE)
        for block in json_blocks:
            try:
                parsed = safe_loads(block.strip())
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        # 3. 如果都不行，尝试暴力匹配 `{}`。失败的话继续找下一个 `{`
        start = -1
        while True:
            start = cleaned_text.find("{", start + 1)
            if start < 0:
                break
            depth = 0
            in_string = False
            escape = False
            for idx in range(start, len(cleaned_text)):
                ch = cleaned_text[idx]
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
                        candidate = cleaned_text[start : idx + 1]
                        try:
                            parsed = safe_loads(candidate)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass # 遇到不合法的 json 或非 dict，退出当前 `{` 的匹配，继续找下一个
                        break
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

    @staticmethod
    def _extract_thinking_summary(thinking: str, *, default_detail: str = "处理中...") -> str:
        """Return a compact, user-facing progress line from streamed thinking text."""
        text = re.sub(r"<[^>]+>", " ", thinking or "")
        text = re.sub(r"```[\s\S]*?```", " ", text)
        fragments = [
            re.sub(r"\s+", " ", line).strip(" -\t\r\n")
            for line in re.split(r"[\r\n。.!?；;]+", text)
        ]
        summary = next((line for line in reversed(fragments) if line), "")
        if not summary:
            return default_detail
        return summary[:120]

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

    # ─── Markdown formatting ───────────────────────────────────────────────

    @classmethod
    def _format_as_markdown(cls, data: Any, depth: int = 0) -> str:
        """递归将字典或列表格式化为 Markdown 字符串以供模型阅读（替代 json.dumps）。"""
        indent = "  " * depth
        if data is None:
            return "null"
        if isinstance(data, bool):
            return "true" if data else "false"
        if isinstance(data, (int, float)):
            return str(data)
        if isinstance(data, str):
            if "\n" in data:
                # 给多行文本加上代码块以防止 Markdown 格式混乱
                return f"\n{indent}```\n{data}\n{indent}```"
            return data

        if isinstance(data, list):
            if not data:
                return "[]"
            lines = []
            for item in data:
                if isinstance(item, (dict, list)) and item:
                    lines.append(f"{indent}- \n{cls._format_as_markdown(item, depth + 1)}")
                else:
                    val = cls._format_as_markdown(item, depth + 1).strip()
                    lines.append(f"{indent}- {val}")
            return "\n".join(lines)
        
        if isinstance(data, dict):
            if not data:
                return "{}"
            lines = []
            for k, v in data.items():
                if isinstance(v, (dict, list)) and v:
                    lines.append(f"{indent}- **{k}**:\n{cls._format_as_markdown(v, depth + 1)}")
                else:
                    val = cls._format_as_markdown(v, depth + 1).lstrip()
                    lines.append(f"{indent}- **{k}**: {val}")
            return "\n".join(lines)
        
        return str(data)
