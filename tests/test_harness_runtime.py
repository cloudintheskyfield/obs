from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents.harness_runtime import HarnessRuntime


class _DummySkillManager:
    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def get_current_workspace(self) -> str:
        return str(self._workspace)

    def set_workspace(self, work_dir: str) -> str:
        self._workspace = Path(work_dir)
        self._workspace.mkdir(parents=True, exist_ok=True)
        return str(self._workspace)

    def get_anthropic_tools(self):
        return []

    def resolve_skill_name_for_tool(self, tool_name: str):
        return tool_name


class _FakeVllmClient:
    def __init__(self, *, require_search: bool = False) -> None:
        self.require_search = require_search

    async def chat_completion(self, *, messages, tools=None, temperature=0.1, max_tokens=1600, stream=True, model=None):
        system_prompt = str(messages[0].get("content") or "")
        if "Planner Agent" in system_prompt:
            payload = {
                "task_id": "task_runtime_e2e",
                "goal": "验证 Harness runtime 全链路",
                "assumptions": [],
                "implementation_strategy": "不改业务文件，只运行 Harness 指定命令。",
                "allowed_files": ["src/**"],
                "forbidden_files": [".env", ".env.*", ".git/**", "node_modules/**", "dist/**", "build/**", ".harness/**", "package.json"],
                "required_files_to_inspect": ["src/App.py"],
                "implementation_steps": [{"id": "step_1", "title": "保留现有文件", "details": "No-op generation for E2E.", "files": ["src/App.py"]}],
                "test_commands": [{"name": "runtime_ok", "cmd": "python -c \"print('harness-runtime-ok')\"", "timeout_sec": 30, "required": True}],
                "dev_server": {"enabled": False, "start_cmd": "", "url": "", "ready_patterns": [], "timeout_sec": 0},
                "smoke_tests": [],
                "acceptance_criteria": ["Runner 命令通过", "Evaluator 输出 PASS"],
                "repair_policy": {"max_rounds": 1, "prefer_minimal_patch": True},
                "rollback_policy": {"strategy": "none"},
                "external_research": {
                    "required": self.require_search,
                    "reason": "需要确认外部资料" if self.require_search else "",
                    "queries": ["Harness E2E smoke"] if self.require_search else [],
                    "allowed_domains": [],
                },
                "package_json_policy": {"allow_modify": False, "allow_add_scripts": False, "allow_add_dependencies": False, "requires_approval": True},
                "risks": [],
            }
        elif "Search Agent" in system_prompt:
            payload = {
                "schema_version": "1.0",
                "task_id": "task_runtime_e2e",
                "round_id": 1,
                "search_id": "search_001",
                "query_summary": "Search Gate E2E evidence collected.",
                "status": "SUCCESS",
                "insufficient_evidence": False,
                "sources": [{"id": "S1", "url": "https://www.findskills.org/zh/directory", "title": "FindSkills Directory", "trust": "high"}],
                "key_findings": [{"id": "F1", "question_id": "Q1", "finding": "Use bounded source-backed skills.", "source_ids": ["S1"], "confidence": 0.9}],
                "implementation_guidance": [{"target": "Generator", "guidance": "No source changes needed for this E2E.", "applies_to": "Generator", "risk": "low"}],
                "risks": [],
                "recommended_next_agent": "Generator",
                "raw_artifacts": [{"type": "search_report", "path": ".harness/search/search_001/search_report.json"}],
            }
        elif "Generator Agent" in system_prompt:
            payload = {
                "schema_version": "1.0",
                "task_id": "task_runtime_e2e",
                "round_id": 1,
                "mode": "initial",
                "changed_files": [],
                "created_files": [],
                "deleted_files": [],
                "summary": "No-op patch for Harness E2E.",
                "implementation_notes": ["No source changes were required."],
                "commands_to_run": [{"name": "runtime_ok", "cmd": "python -c \"print('harness-runtime-ok')\"", "reason": "E2E verification"}],
                "risk_points": [],
                "patch_envelope": {"schema_version": "1.0", "task_id": "task_runtime_e2e", "round_id": 1, "patch_type": "file_replacement", "operations": [], "changed_files": []},
                "needs_replan": False,
                "replan_reason": "",
            }
        elif "Evaluator Agent" in system_prompt:
            payload = {
                "schema_version": "1.0",
                "task_id": "task_runtime_e2e",
                "round_id": 1,
                "verdict": "PASS",
                "score": 1.0,
                "passed_criteria": ["Runner 命令通过", "Evaluator 输出 PASS"],
                "failed_criteria": [],
                "evidence": ["RunReport status PASSED"],
                "root_cause": "",
                "repair_instruction": "",
                "needs_search": False,
                "search_questions": [],
                "next_agent": "None",
                "confidence": 0.95,
                "stop_reason": "All checks passed.",
            }
        else:
            payload = {}

        async def stream_response():
            yield {"choices": [{"delta": {"content": json.dumps(payload, ensure_ascii=False)}}]}

        return stream_response()


class _FakeEmptyPatchThenCreateVllm:
    def __init__(self) -> None:
        self.generator_calls = 0

    async def chat_completion(self, *, messages, tools=None, temperature=0.1, max_tokens=1600, stream=True, model=None):
        system_prompt = str(messages[0].get("content") or "")
        if "Planner Agent" in system_prompt:
            payload = {
                "task_id": "task_index_html",
                "goal": "生成 index.html 小游戏",
                "assumptions": [],
                "implementation_strategy": "创建一个可直接打开的 HTML 文件。",
                "allowed_files": ["index.html"],
                "forbidden_files": [".env", ".env.*", ".git/**", "node_modules/**", "dist/**", "build/**", ".harness/**", "package.json"],
                "required_files_to_inspect": [],
                "implementation_steps": [{"id": "S1", "title": "创建 index.html", "description": "写入完整页面。"}],
                "test_commands": [{"name": "bad_browser_text", "cmd": "在浏览器中直接打开index.html文件", "timeout_sec": 30, "required": True}],
                "dev_server": {"enabled": False, "start_cmd": "", "url": "", "ready_patterns": [], "timeout_sec": 0},
                "smoke_tests": [],
                "acceptance_criteria": ["index.html 被创建"],
                "repair_policy": {"max_repair_rounds": 3, "repair_scope": "minimal_patch", "do_not_rewrite_whole_project": True, "if_same_error_repeats": "REPLAN"},
                "rollback_policy": {"snapshot_before_patch": True, "rollback_on_invalid_patch": True, "preserve_harness_artifacts": True},
                "external_research": {"required": False, "reason": "", "queries": [], "allowed_domains": []},
                "package_json_policy": {"allow_modify": False, "allow_add_scripts": False, "allow_add_dependencies": False, "requires_approval": True},
                "risks": [],
            }

            async def stream_response():
                yield {"choices": [{"delta": {"content": json.dumps(payload, ensure_ascii=False)}}]}

            return stream_response()

        if "Generator Agent" in system_prompt:
            self.generator_calls += 1
            if self.generator_calls == 1:
                payload = {
                    "schema_version": "1.0",
                    "task_id": "task_index_html",
                    "round_id": 1,
                    "mode": "initial",
                    "changed_files": [],
                    "created_files": [],
                    "deleted_files": [],
                    "summary": "No files changed.",
                    "implementation_notes": [],
                    "commands_to_run": [],
                    "risk_points": [],
                    "patch_envelope": {"operations": [], "changed_files": []},
                    "needs_replan": False,
                    "replan_reason": "",
                }

                async def empty_stream():
                    yield {"choices": [{"delta": {"content": json.dumps(payload, ensure_ascii=False)}}]}

                return empty_stream()

            if self.generator_calls == 2:
                args = json.dumps(
                    {
                        "command": "create",
                        "path": "index.html",
                        "file_text": "<!doctype html><html><body><canvas id=\"game\"></canvas><script>window.__gameReady=true</script></body></html>",
                    }
                )

                async def tool_stream():
                    yield {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call_create_index",
                                            "type": "function",
                                            "function": {"name": "file-manager", "arguments": args},
                                        }
                                    ]
                                }
                            }
                        ]
                    }

                return tool_stream()

            payload = {
                "schema_version": "1.0",
                "task_id": "task_index_html",
                "round_id": 2,
                "mode": "repair",
                "changed_files": ["index.html"],
                "created_files": ["index.html"],
                "deleted_files": [],
                "summary": "Created index.html.",
                "implementation_notes": [],
                "commands_to_run": [],
                "risk_points": [],
                "patch_envelope": {"operations": [{"path": "index.html"}], "changed_files": ["index.html"]},
                "needs_replan": False,
                "replan_reason": "",
            }

            async def patch_stream():
                yield {"choices": [{"delta": {"content": json.dumps(payload, ensure_ascii=False)}}]}

            return patch_stream()

        if "Evaluator Agent" in system_prompt:
            payload = {
                "schema_version": "1.0",
                "task_id": "task_index_html",
                "round_id": 2,
                "verdict": "PASS",
                "score": 1.0,
                "passed_criteria": ["index.html 被创建"],
                "failed_criteria": [],
                "evidence": ["RunReport status PASSED"],
                "root_cause": "",
                "repair_instruction": "",
                "needs_search": False,
                "search_questions": [],
                "next_agent": "None",
                "confidence": 0.95,
                "stop_reason": "All checks passed.",
            }

            async def eval_stream():
                yield {"choices": [{"delta": {"content": json.dumps(payload, ensure_ascii=False)}}]}

            return eval_stream()

        async def empty_stream():
            yield {"choices": [{"delta": {"content": "{}"}}]}

        return empty_stream()


def test_runtime_builds_spec_shaped_harness_inputs(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "App.tsx").write_text("export default function App() { return null; }\n", encoding="utf-8")

    runtime = HarnessRuntime(vllm_client=None, skill_manager=_DummySkillManager(tmp_path))
    plan_contract = {
        "task_id": "task_runtime_001",
        "goal": "实现一个最小页面",
        "allowed_files": ["src/**"],
        "forbidden_files": [".env", ".git/**", ".harness/**", "package.json"],
        "required_files_to_inspect": ["src/App.tsx"],
        "package_json_policy": {
            "allow_modify": False,
            "allow_add_scripts": False,
            "allow_add_dependencies": False,
            "requires_approval": True,
        },
        "test_commands": [{"name": "build", "cmd": "npm run build", "timeout_sec": 120, "required": True}],
        "dev_server": {
            "enabled": True,
            "start_cmd": "npm run dev -- --host 0.0.0.0",
            "url": "http://localhost:5173",
            "ready_patterns": ["ready in"],
            "timeout_sec": 60,
        },
        "smoke_tests": [{"id": "page_load", "type": "browser", "action": "goto", "target": "http://localhost:5173"}],
        "acceptance_criteria": ["页面可以打开"],
    }

    generator_input = runtime._build_generator_input(
        workspace=tmp_path,
        plan_contract=plan_contract,
        search_reports=[],
        last_run_report={},
        eval_verdict={},
        round_id=1,
    )
    assert generator_input["project_files_snapshot"]["src/App.tsx"].startswith("export default")
    assert generator_input["harness_constraints"]["allowed_write_paths"] == ["src/**"]
    assert generator_input["harness_constraints"]["forbidden_write_paths"][0] == ".env"

    runner_input = runtime._build_runner_input(
        workspace=tmp_path,
        plan_contract=plan_contract,
        patch_result={"changed_files": ["src/App.tsx"]},
        search_reports=[],
        artifact_info={"description": "Verify core functionality"},
        round_id=1,
    )
    assert runner_input["runner_limits"]["max_command_retries"] == 0
    assert runner_input["runner_limits"]["max_dev_server_retries"] == 2
    assert runner_input["permissions"]["can_write_project_files"] is False

    evaluator_input = runtime._build_evaluator_input(
        plan_contract=plan_contract,
        patch_result={"changed_files": ["src/App.tsx"], "created_files": [], "deleted_files": []},
        run_report={"artifacts": {"screenshots": [".harness/runs/run_001/screenshots/page.png"]}},
        search_reports=[],
        previous_verdicts=[],
        round_id=1,
        diff_path=".harness/runs/run_001/diff.patch",
    )
    assert evaluator_input["git_diff_summary"]["diff_path"] == ".harness/runs/run_001/diff.patch"
    assert evaluator_input["screenshots"] == [".harness/runs/run_001/screenshots/page.png"]


def test_runtime_runs_full_harness_chain_and_persists_evidence(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "App.py").write_text("print('app')\n", encoding="utf-8")
    runtime = HarnessRuntime(vllm_client=_FakeVllmClient(), skill_manager=_DummySkillManager(tmp_path))

    async def collect_events() -> list[dict]:
        events = []
        async for chunk in runtime.chat_stream(
            session_id="runtime-e2e",
            chat_sessions={"runtime-e2e": [{"role": "user", "content": "跑通 Harness 全链路"}]},
            mode="agent",
            request_context={"workspace_runtime_path": str(tmp_path)},
        ):
            if chunk.startswith("data: "):
                events.append(json.loads(chunk.removeprefix("data: ").strip()))
        return events

    events = asyncio.run(collect_events())
    decisions = [event["decision"] for event in events if event.get("type") == "harness_decision"]
    assert decisions[-1]["decision"] == "PASS"

    state = json.loads((tmp_path / ".harness" / "state.json").read_text(encoding="utf-8"))
    run_report = json.loads((tmp_path / ".harness" / "runs" / "run_001" / "output" / "run_report.json").read_text(encoding="utf-8"))
    eval_verdict = json.loads((tmp_path / ".harness" / "runs" / "run_001" / "output" / "eval_verdict.json").read_text(encoding="utf-8"))

    assert state["state"] == "PASS"
    assert run_report["status"] == "PASSED"
    assert "harness-runtime-ok" in run_report["commands"][0]["stdout_tail"]
    assert eval_verdict["verdict"] == "PASS"
    assert (tmp_path / run_report["commands"][0]["log"]).exists()


def test_runtime_runs_search_gate_chain_before_generator(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "App.py").write_text("print('app')\n", encoding="utf-8")
    runtime = HarnessRuntime(vllm_client=_FakeVllmClient(require_search=True), skill_manager=_DummySkillManager(tmp_path))

    async def collect_events() -> list[dict]:
        events = []
        async for chunk in runtime.chat_stream(
            session_id="runtime-search-e2e",
            chat_sessions={"runtime-search-e2e": [{"role": "user", "content": "先查资料再跑通 Harness 全链路"}]},
            mode="agent",
            request_context={"workspace_runtime_path": str(tmp_path)},
        ):
            if chunk.startswith("data: "):
                events.append(json.loads(chunk.removeprefix("data: ").strip()))
        return events

    events = asyncio.run(collect_events())
    summary_roles = [event.get("role") for event in events if event.get("type") == "agent_summary"]
    assert summary_roles[:5] == ["Planner", "Search", "Generator", "Runner", "Evaluator"]

    search_report = json.loads((tmp_path / ".harness" / "search" / "search_001" / "search_report.json").read_text(encoding="utf-8"))
    decision = json.loads((tmp_path / ".harness" / "runs" / "run_001" / "output" / "harness_decision.json").read_text(encoding="utf-8"))
    assert search_report["status"] == "SUCCESS"
    assert search_report["recommended_next_agent"] == "Generator"
    assert decision["decision"] == "PASS"


def test_runtime_retries_generator_when_patch_envelope_is_empty(tmp_path: Path) -> None:
    runtime = HarnessRuntime(vllm_client=_FakeEmptyPatchThenCreateVllm(), skill_manager=_DummySkillManager(tmp_path))

    async def collect_events() -> list[dict]:
        events = []
        async for chunk in runtime.chat_stream(
            session_id="runtime-empty-patch",
            chat_sessions={"runtime-empty-patch": [{"role": "user", "content": "生成 index.html 小游戏"}]},
            mode="agent",
            request_context={"workspace_runtime_path": str(tmp_path)},
        ):
            if chunk.startswith("data: "):
                events.append(json.loads(chunk.removeprefix("data: ").strip()))
        return events

    events = asyncio.run(collect_events())
    decisions = [event["decision"] for event in events if event.get("type") == "harness_decision"]
    first_run_verdict = json.loads((tmp_path / ".harness" / "runs" / "run_001" / "output" / "eval_verdict.json").read_text(encoding="utf-8"))
    second_run_report = json.loads((tmp_path / ".harness" / "runs" / "run_002" / "output" / "run_report.json").read_text(encoding="utf-8"))
    plan_contract = json.loads((tmp_path / ".harness" / "plan.json").read_text(encoding="utf-8"))

    assert decisions[0]["decision"] == "CALL_GENERATOR"
    assert decisions[-1]["decision"] == "PASS"
    assert "Generator did not create any implementation files" in first_run_verdict["root_cause"]
    assert (tmp_path / "index.html").exists()
    assert second_run_report["status"] == "PASSED"
    assert all("在浏览器" not in command["cmd"] for command in plan_contract["test_commands"])
