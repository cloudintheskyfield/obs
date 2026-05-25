from __future__ import annotations

import json
from utils.json_utils import safe_loads
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .harness_engine import HarnessEngine
from .base_agent import BaseAgent





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
        "sources": self._normalize_object_list(source.get("sources"), kind="sources"),
        "key_findings": self._normalize_object_list(source.get("key_findings"), kind="key_findings"),
        "implementation_guidance": self._normalize_object_list(source.get("implementation_guidance"), kind="implementation_guidance"),
        "risks": self._normalize_string_list(source.get("risks")),
        "recommended_next_agent": str(source.get("recommended_next_agent") or "Generator"),
        "raw_artifacts": self._normalize_object_list(source.get("raw_artifacts"), kind="raw_artifacts"),
    }
    report["display_summary"] = harness.display_summary_for_output("Search", report)
    return report


class SearchAgent(BaseAgent):
    def __init__(self, vllm_client: Any, skill_manager: Any) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt("Search", "")
        self.last_search_report: Dict[str, Any] = {}

    