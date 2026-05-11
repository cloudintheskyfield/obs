from __future__ import annotations

import asyncio
from omni_agent.agents.harness_engine import HarnessEngine
from omni_agent.agents.runner_agent import RunnerAgent, _fallback_run_report, _normalize_run_report


def test_normalize_run_report_keeps_spec_shaped_artifacts_object() -> None:
    harness = HarnessEngine()
    report = _normalize_run_report(
        {
            "status": "TIMEOUT",
            "artifacts": {
                "run_dir": ".harness/runs/run_001",
                "screenshots": ["a.png"],
                "traces": ["trace.zip"],
                "logs": ["runner.log"],
                "browser_console": "console.log('ready')",
            },
        },
        {
            "task_id": "task_runtime_001",
            "round_id": 1,
            "run_dir": ".harness/runs/run_001",
            "plan_contract": {"task_id": "task_runtime_001"},
        },
        harness,
    )

    assert report["status"] == "TIMEOUT"
    assert report["artifacts"]["run_dir"] == ".harness/runs/run_001"
    assert report["artifacts"]["screenshots"] == ["a.png"]
    assert report["artifacts"]["traces"] == ["trace.zip"]
    assert report["artifacts"]["logs"] == ["runner.log"]
    assert report["artifacts"]["browser_console"] == "console.log('ready')"


def test_fallback_run_report_uses_infra_error_and_object_artifacts() -> None:
    harness = HarnessEngine()
    report = _fallback_run_report(
        {
            "task_id": "task_runtime_001",
            "round_id": 2,
            "run_dir": ".harness/runs/run_002",
            "plan_contract": {"task_id": "task_runtime_001"},
        },
        "runner crashed",
        harness,
    )

    assert report["status"] == "INFRA_ERROR"
    assert report["artifacts"]["run_dir"] == ".harness/runs/run_002"
    assert report["artifacts"]["screenshots"] == []
    assert report["artifacts"]["logs"] == []


def test_runner_executes_harness_provided_commands_and_writes_logs(tmp_path) -> None:
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_e2e",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_e2e"},
        "patch_result": {"changed_files": []},
        "test_commands": [
            {
                "name": "python_ok",
                "cmd": "python -c \"print('harness-e2e-ok')\"",
                "timeout_sec": 30,
                "required": True,
            }
        ],
        "dev_server": {},
        "smoke_tests": [],
        "runner_limits": {},
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["commands"][0]["status"] == "PASSED"
    assert "harness-e2e-ok" in report["commands"][0]["stdout_tail"]
    assert (tmp_path / report["commands"][0]["log"]).exists()
