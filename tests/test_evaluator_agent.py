from agents.evaluator_agent import _normalize_verdict
from agents.harness_engine import HarnessEngine


def test_evaluator_trusts_successful_run_report_over_model_speculation() -> None:
    payload = {
        "round_id": 1,
        "plan_contract": {
            "task_id": "game_smoke",
            "acceptance_criteria": ["page loads", "keyboard input works"],
        },
        "run_report": {
            "status": "PASSED",
            "errors": [],
            "summary": "completed 3/3 smoke test(s)",
        },
    }
    speculative_failure = {
        "verdict": "REPLAN",
        "failed_criteria": ["unproven mechanic"],
        "root_cause": "model guessed a missing behavior",
        "next_agent": "Planner",
    }

    verdict = _normalize_verdict(speculative_failure, payload, HarnessEngine())

    assert verdict["verdict"] == "PASS"
    assert verdict["failed_criteria"] == []
    assert verdict["next_agent"] == "None"


def test_evaluator_does_not_pass_failed_run_report() -> None:
    payload = {
        "round_id": 1,
        "plan_contract": {
            "task_id": "game_smoke",
            "acceptance_criteria": ["page loads"],
        },
        "run_report": {
            "status": "FAILED",
            "errors": [
                {
                    "type": "RUNNER_CONFIG_ERROR",
                    "root_category": "RUNNER",
                    "message": "bad smoke test",
                }
            ],
            "summary": "completed 0/1 smoke test(s)",
        },
    }
    speculative_pass = {
        "verdict": "PASS",
        "passed_criteria": ["page loads"],
        "next_agent": "None",
    }

    verdict = _normalize_verdict(speculative_pass, payload, HarnessEngine())

    assert verdict["verdict"] == "REPLAN"
    assert verdict["failed_criteria"] == ["page loads"]
    assert verdict["next_agent"] == "Planner"
