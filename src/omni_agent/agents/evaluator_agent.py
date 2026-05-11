from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .harness_engine import HarnessEngine

EVALUATOR_SYSTEM_PROMPT = (
    "You are Evaluator Agent in a five-agent Harness workflow. "
    "Your only responsibility is judgement.\n\n"
    "Read the supplied PlanContract, optional PatchResult, RunReport, screenshots/log summaries, and previous verdicts.\n"
    "Do not execute commands. Do not use browser automation. Do not modify files. Do not call another agent.\n"
    "Return exactly one strict JSON EvalVerdict object with these fields:\n"
    "schema_version, task_id, round_id, verdict, score, passed_criteria, failed_criteria, evidence, root_cause, repair_instruction, needs_search, search_questions, next_agent, confidence, stop_reason.\n"
    "Use PASS for accepted results, FIXABLE for product issues that Generator can repair, REPLAN when the plan itself is wrong, FAIL_HARD for unrecoverable outcomes, and INFRA for runner or environment failures."
)

_ALLOWED_VERDICTS = {"PASS", "FIXABLE", "REPLAN", "FAIL_HARD", "INFRA"}
_ALLOWED_NEXT_AGENTS = {"None", "Generator", "Planner", "Search"}


def _find_first_json_object(raw: str) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
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
                    parsed = json.loads(candidate)
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


def _heuristic_verdict(payload: Mapping[str, Any], harness: HarnessEngine) -> Dict[str, Any]:
    plan_contract_raw = payload.get("plan_contract")
    run_report_raw = payload.get("run_report")
    plan_contract: Dict[str, Any] = dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    run_report: Dict[str, Any] = dict(run_report_raw) if isinstance(run_report_raw, Mapping) else {}
    acceptance = _normalize_string_list(plan_contract.get("acceptance_criteria"))
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
            "evidence": _normalize_string_list(run_report.get("summary")) or ["Runner completed required checks successfully."],
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
    elif error_type == "PRODUCT_REQUIREMENT_MISS":
        verdict_name = "REPLAN"
        next_agent = "Planner"
        repair_instruction = ""
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
    verdict_name = str(raw_obj.get("verdict") or base["verdict"]).upper()
    next_agent = str(raw_obj.get("next_agent") or base["next_agent"])
    verdict = {
        "schema_version": str(raw_obj.get("schema_version") or "1.0"),
        "task_id": str(raw_obj.get("task_id") or base["task_id"]),
        "round_id": int(raw_obj.get("round_id") or base["round_id"]),
        "verdict": verdict_name if verdict_name in _ALLOWED_VERDICTS else base["verdict"],
        "score": float(raw_obj["score"]) if raw_obj.get("score") is not None else float(base["score"]),
        "passed_criteria": _normalize_string_list(raw_obj.get("passed_criteria")) or base["passed_criteria"],
        "failed_criteria": _normalize_string_list(raw_obj.get("failed_criteria")) or base["failed_criteria"],
        "evidence": _normalize_string_list(raw_obj.get("evidence")) or base["evidence"],
        "root_cause": str(raw_obj.get("root_cause") or base["root_cause"]),
        "repair_instruction": str(raw_obj.get("repair_instruction") or base["repair_instruction"]),
        "needs_search": bool(raw_obj.get("needs_search", base["needs_search"])),
        "search_questions": _normalize_string_list(raw_obj.get("search_questions")) or base["search_questions"],
        "next_agent": next_agent if next_agent in _ALLOWED_NEXT_AGENTS else base["next_agent"],
        "confidence": float(raw_obj["confidence"]) if raw_obj.get("confidence") is not None else float(base["confidence"]),
        "stop_reason": str(raw_obj.get("stop_reason") or base["stop_reason"]),
    }
    verdict["display_summary"] = harness.display_summary_for_output("Evaluator", verdict)
    return verdict


class EvaluatorAgent:
    def __init__(self, vllm_client: Any, skill_manager: Any = None) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.last_verdict: Dict[str, Any] = {}

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def evaluate(
        self,
        session_id: str,
        evaluation_input: Mapping[str, Any],
        *,
        model: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Evaluator",
                "status": "running",
                "title": "生成 EvalVerdict",
                "detail": "基于 RunReport 和验收标准进行一次性判断...",
                "session_id": session_id,
            }
        )

        messages = [
            {"role": "system", "content": EVALUATOR_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(dict(evaluation_input), ensure_ascii=False, indent=2)},
        ]

        raw_content = ""
        try:
            stream = await self.vllm_client.chat_completion(
                messages=messages,
                tools=None,
                temperature=0.1,
                max_tokens=1600,
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
                    yield self._sse(
                        {
                            "type": "agent_thinking",
                            "agent": "evaluator",
                            "delta": piece,
                            "session_id": session_id,
                        }
                    )
        except Exception as exc:
            logger.warning(f"EvaluatorAgent model call failed: {exc}")
            self.last_verdict = _heuristic_verdict(evaluation_input, self.harness)
            yield self._sse(
                {
                    "type": "agent_step",
                    "role": "Evaluator",
                    "status": "error",
                    "title": "EvalVerdict 生成失败，已回退启发式判断",
                    "detail": str(exc),
                    "session_id": session_id,
                }
            )
            return

        self.last_verdict = _normalize_verdict(_find_first_json_object(raw_content), evaluation_input, self.harness)
        passed = self.last_verdict.get("verdict") == "PASS"
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Evaluator",
                "status": "success" if passed else "error",
                "title": "验收通过" if passed else "验收未通过",
                "detail": self.last_verdict.get("root_cause") or self.last_verdict.get("repair_instruction") or "",
                "session_id": session_id,
            }
        )
