import json
from typing import Any, Dict, List, Optional
from .harness_engine import HarnessEngine

class BaseAgent:
    def __init__(self, role_name: str, vllm_client: Any, skill_manager: Any = None) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt(role_name, "")

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _find_first_json_object(raw: str) -> Optional[Dict[str, Any]]:
        text = (raw or "").strip()
        if not text:
            return None
        start = text.find("{")
        if start == -1:
            return None
        text = text[start:]
        end = text.rfind("}")
        if end != -1:
            text = text[: end + 1]
        try:
            from utils.json_utils import safe_loads
            parsed = safe_loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return None

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value if v]
        return []

    @staticmethod
    def _normalize_object_list(value: Any, *, kind: str) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(dict(item))
            elif isinstance(item, str):
                if kind == "commands":
                    out.append({"command": item})
                elif kind == "smoke_tests":
                    out.append({
                        "id": "unknown",
                        "type": "browser",
                        "action": "goto",
                        "target": item,
                        "expect": {"type": "no_fatal_console_error"}
                    })
        return out
