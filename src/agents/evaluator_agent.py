from __future__ import annotations

import json
from utils.json_utils import safe_loads
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .harness_engine import HarnessEngine
from .base_agent import BaseAgent

_ALLOWED_VERDICTS = {"PASS", "FIXABLE", "REPLAN", "FAIL_HARD", "INFRA"}
_ALLOWED_NEXT_AGENTS = {"None", "Generator", "Planner", "Search"}




def _heuristic_verdict(payload: Mapping[str, Any], harness: HarnessEngine) -> Dict[str, Any]:
    plan_contract_raw = payload.get("plan_contract")
    run_report_raw = payload.get("run_report")
    plan_contract: Dict[str, Any] = dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    run_report: Dict[str, Any] = dict(run_report_raw) if isinstance(run_report_raw, Mapping) else {}
    acceptance = self._normalize_string_list(plan_contract.get("acceptance_criteria"))
    errors = run_report.get("errors") if isinstance(run_report.get("errors"), list) else []
    task_id = str(plan_contract.get("task_id") or "task_runtime_001")
    round_id = int(payload.get("round_id") or run_report.get("round_id") or 1)

    passed = run_report.get("status") == "PASSED" and not errors
    if passed:
        verdict = {
            "schema_version": "1.0",
            "task_id": task_id,
            "round_id": round_id,
            "verdict": "PASS",
            "score": 1.0,
            "passed_criteria": acceptance,
            "failed_criteria": [],
            "evidence": self._normalize_string_list(run_report.get("summary")) or ["Runner completed required checks successfully."],
            "root_cause": "",
            "repair_instruction": "",
            "needs_search": False,
            "search_questions": [],
            "next_agent": "None",
            "confidence": 0.85,
            "stop_reason": "",
        }
        verdict["display_summary"] = harness.display_summary_for_output("Evaluator", verdict)
        return verdict

    first_error = errors[0] if errors and isinstance(errors[0], Mapping) else {}
    error_type = str(first_error.get("type") or "")
    root_category = str(first_error.get("root_category") or "")
    message = str(first_error.get("message") or run_report.get("summary") or "Validation failed.")

    needs_search = harness.should_search(plan=plan_contract, run_report=run_report, eval_verdict={"needs_search": False})
    if needs_search:
        verdict_name = "INFRA"
        next_agent = "Search"
        repair_instruction = ""
    elif error_type == "PRODUCT_REQUIREMENT_MISS" or error_type in {"RUNNER_PORT_ERROR", "RUNNER_CONFIG_ERROR"}:
        verdict_name = "REPLAN"
        next_agent = "Planner"
        repair_instruction = f"Plan configuration error: {message}. Please adjust the dev_server port or smoke_test parameters."
    elif error_type.startswith("PRODUCT_"):
        verdict_name = "FIXABLE"
        next_agent = "Generator"
        repair_instruction = message
    elif error_type.startswith("RUNNER_") or error_type.startswith("INFRA_") or root_category in {"RUNNER", "INFRA"}:
        verdict_name = "INFRA"
        next_agent = "None"
        repair_instruction = ""
    else:
        verdict_name = "FIXABLE"
        next_agent = "Generator"
        repair_instruction = message

    verdict = {
        "schema_version": "1.0",
        "task_id": task_id,
        "round_id": round_id,
        "verdict": verdict_name,
        "score": 0.25 if verdict_name == "INFRA" else 0.4,
        "passed_criteria": [],
        "failed_criteria": acceptance or ["未达到验收标准"],
        "evidence": [message],
        "root_cause": message,
        "repair_instruction": repair_instruction,
        "needs_search": needs_search,
        "search_questions": [message] if needs_search else [],
        "next_agent": next_agent,
        "confidence": 0.7,
        "stop_reason": message if verdict_name in {"FAIL_HARD", "INFRA"} else "",
    }
    verdict["display_summary"] = harness.display_summary_for_output("Evaluator", verdict)
    return verdict


def _normalize_verdict(raw_obj: Optional[Dict[str, Any]], payload: Mapping[str, Any], harness: HarnessEngine) -> Dict[str, Any]:
    if not raw_obj:
        return _heuristic_verdict(payload, harness)
    base = _heuristic_verdict(payload, harness)
    if base.get("verdict") == "PASS":
        return base
    verdict_name = str(raw_obj.get("verdict") or base["verdict"]).upper()
    if verdict_name == "PASS":
        return base
    next_agent = str(raw_obj.get("next_agent") or base["next_agent"])
    verdict = {
        "schema_version": str(raw_obj.get("schema_version") or "1.0"),
        "task_id": str(raw_obj.get("task_id") or base["task_id"]),
        "round_id": int(raw_obj.get("round_id") or base["round_id"]),
        "verdict": verdict_name if verdict_name in _ALLOWED_VERDICTS else base["verdict"],
        "score": float(raw_obj["score"]) if raw_obj.get("score") is not None else float(base["score"]),
        "passed_criteria": self._normalize_string_list(raw_obj.get("passed_criteria")) or base["passed_criteria"],
        "failed_criteria": self._normalize_string_list(raw_obj.get("failed_criteria")) or base["failed_criteria"],
        "evidence": self._normalize_string_list(raw_obj.get("evidence")) or base["evidence"],
        "root_cause": str(raw_obj.get("root_cause") or base["root_cause"]),
        "repair_instruction": str(raw_obj.get("repair_instruction") or base["repair_instruction"]),
        "needs_search": bool(raw_obj.get("needs_search", base["needs_search"])),
        "search_questions": self._normalize_string_list(raw_obj.get("search_questions")) or base["search_questions"],
        "next_agent": next_agent if next_agent in _ALLOWED_NEXT_AGENTS else base["next_agent"],
        "confidence": float(raw_obj["confidence"]) if raw_obj.get("confidence") is not None else float(base["confidence"]),
        "stop_reason": str(raw_obj.get("stop_reason") or base["stop_reason"]),
    }
    verdict["display_summary"] = harness.display_summary_for_output("Evaluator", verdict)
    return verdict


class EvaluatorAgent(BaseAgent):
    def __init__(self, vllm_client: Any, skill_manager: Any = None) -> None:
        super().__init__("Evaluator", vllm_client, skill_manager)
        self.last_verdict: Dict[str, Any] = {}
    