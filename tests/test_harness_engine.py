import json
from pathlib import Path

from agents.harness_engine import HarnessEngine


def test_harness_signature_defines_three_roles_and_six_layers() -> None:
    signature = HarnessEngine().architecture_signature()

    assert signature["pattern"] == "agent + model + harness"
    assert [role["name"] for role in signature["roles"]] == [
        "Planner",
        "Search",
        "Generator",
        "Runner",
        "Evaluator",
    ]
    assert len(signature["layers"]) == 6
    assert "SEARCH" in signature["phase_order"]
    assert "RUN" in signature["phase_order"]


def test_harness_addendum_requires_environment_evaluation() -> None:
    addendum = HarnessEngine().system_addendum(
        active_mode="agent",
        user_message="生成一个网页游戏",
        tool_names=["str_replace_editor", "bash", "computer"],
    )

    assert "Planner" in addendum
    assert "Search" in addendum
    assert "Generator" in addendum
    assert "Runner" in addendum
    assert "Evaluator" in addendum
    assert "Search Gate" in addendum
    assert "Runner script errors" in addendum


def test_harness_maps_legacy_modes_to_strategies() -> None:
    harness = HarnessEngine()

    assert harness.strategy_for_mode("agent") == "default"
    assert harness.strategy_for_mode("create") == "create"
    assert harness.strategy_for_mode("plan") == "planner_only"
    assert harness.strategy_for_mode("review") == "evaluator_heavy"
    assert harness.strategy_for_mode("battle") == "comparison"
    assert harness.runtime_mode_for_strategy("planner_only") == "agent"
    assert harness.runtime_mode_for_strategy("create") == "create"


def test_search_gate_opens_only_for_current_or_external_uncertainty() -> None:
    harness = HarnessEngine()

    assert harness.should_search(user_request="请查最新 Playwright 文档")
    assert harness.should_search(plan={"external_research": {"required": True}})
    assert harness.should_search(
        run_report={
            "errors": [
                {
                    "type": "RUNNER_SCRIPT_ERROR",
                    "root_category": "UNKNOWN_API_USAGE",
                }
            ]
        }
    )
    assert not harness.should_search(
        run_report={
            "errors": [
                {
                    "type": "RUNNER_SCRIPT_ERROR",
                    "root_category": "INFRA",
                }
            ]
        }
    )


def test_default_policy_uses_only_spec_agent_tools() -> None:
    policy = HarnessEngine().default_policy("/tmp/workspace")
    permissions = policy["agent_permissions"]

    assert permissions["Planner"]["tools"] == []
    assert permissions["Evaluator"]["tools"] == []
    assert permissions["Generator"]["tools"] == ["filesystem", "file-manager"]
    assert "playwright-e2e" in permissions["Runner"]["tools"]
    assert "firecrawl-scraper" in permissions["Search"]["tools"]
    assert "weather" not in permissions["Search"]["tools"]
    assert "code-sandbox" not in permissions["Runner"]["tools"]


def test_persisted_harness_policy_matches_md_permission_matrix() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    policy = json.loads((repo_root / ".harness" / "policy.json").read_text(encoding="utf-8"))
    permissions = policy["agent_permissions"]

    assert permissions["Planner"]["tools"] == []
    assert permissions["Evaluator"]["tools"] == []
    assert permissions["Search"]["tools"] == [
        "web-search-free",
        "search",
        "web-scraper-pro",
        "firecrawl-scraper",
        "skill-lookup",
    ]
    assert permissions["Generator"]["tools"] == ["filesystem", "file-manager"]
    assert permissions["Runner"]["tools"] == [
        "desktop-commander",
        "playwright-e2e",
        "web-testing-playwright-e2e",
        "e2e",
        "computer-use",
    ]


def test_path_and_patch_policy_enforce_forbidden_files(tmp_path) -> None:
    harness = HarnessEngine()
    plan = {
        "allowed_files": ["src/**", "index.html"],
        "forbidden_files": [".env", ".git/**", ".harness/**", "package.json"],
    }

    assert harness.is_path_allowed("src/app.py", plan["allowed_files"], plan["forbidden_files"], tmp_path)
    assert not harness.is_path_allowed("../outside.py", plan["allowed_files"], plan["forbidden_files"], tmp_path)
    assert not harness.is_path_allowed("package.json", plan["allowed_files"], plan["forbidden_files"], tmp_path)

    harness.validate_patch_policy(
        {
            "changed_files": ["src/app.py"],
            "created_files": [],
            "deleted_files": [],
            "patch_envelope": {"operations": [{"path": "src/app.py"}]},
        },
        plan,
        workspace=tmp_path,
    )
    harness.validate_patch_envelope(
        {
            "operations": [{"path": "src/app.py"}],
            "changed_files": ["src/app.py"],
        },
        plan,
        workspace=tmp_path,
    )


def test_harness_forbids_root_workflow_test_artifacts(tmp_path) -> None:
    harness = HarnessEngine()
    plan = {
        "allowed_files": ["**"],
        "forbidden_files": ["workflow_*/**", "workflow_game_tests/**"],
    }

    assert not harness.is_path_allowed("workflow_e2e_tmp/index.html", plan["allowed_files"], plan["forbidden_files"], tmp_path)
    assert not harness.is_path_allowed("workflow_game_tests/current/package.json", plan["allowed_files"], plan["forbidden_files"], tmp_path)
    assert harness.is_path_allowed("tmp/workflow_e2e_tmp/index.html", plan["allowed_files"], plan["forbidden_files"], tmp_path)


def test_search_route_uses_report_recommendation() -> None:
    harness = HarnessEngine()

    assert harness.route_after_search({"status": "SUCCESS", "recommended_next_agent": "Runner"}) == "RUN"
    assert harness.route_after_search({"status": "SUCCESS", "recommended_next_agent": "Evaluator"}) == "EVALUATE"
    assert harness.route_after_search({"status": "SUCCESS", "recommended_next_agent": "Planner"}) == "REPLAN"


def test_same_error_repeated_forces_replan_before_more_repairs() -> None:
    harness = HarnessEngine()
    repeated = harness.same_error_repeated(
        [{"root_cause": "same bug"}],
        {"root_cause": "same bug"},
        max_same_error_repeats=2,
    )

    decision = harness.build_harness_decision(
        {
            "task_id": "task_1",
            "round_id": 2,
            "verdict": "FIXABLE",
            "repair_instruction": "small fix",
            "root_cause": "same bug",
        },
        repair_round=1,
        replan_round=0,
        same_error_repeated=repeated,
        budgets=harness.default_budgets(),
    )

    assert repeated is True
    assert decision["decision"] == "CALL_PLANNER"
    assert decision["next_state"] == "REPLAN"


def test_fail_hard_missing_generated_files_routes_back_to_generator() -> None:
    harness = HarnessEngine()

    decision = harness.build_harness_decision(
        {
            "task_id": "task_1",
            "round_id": 1,
            "verdict": "FAIL_HARD",
            "root_cause": "Generator did not create any implementation files - the index.html game file was never created",
            "repair_instruction": "",
            "next_agent": "Generator",
        },
        repair_round=0,
        replan_round=0,
        budgets=harness.default_budgets(),
    )

    assert decision["decision"] == "CALL_GENERATOR"
    assert decision["next_state"] == "GENERATE"
    assert decision["next_agent"] == "Generator"


def test_empty_patch_for_required_output_builds_generator_retry_verdict() -> None:
    harness = HarnessEngine()
    plan = {
        "task_id": "task_empty_patch",
        "goal": "生成 index.html 小游戏",
        "allowed_files": ["index.html"],
        "acceptance_criteria": ["index.html 被创建"],
    }
    patch_result = {
        "task_id": "task_empty_patch",
        "changed_files": [],
        "created_files": [],
        "deleted_files": [],
        "patch_envelope": {"operations": [], "changed_files": []},
    }

    verdict = harness.empty_patch_verdict(plan, patch_result, round_id=1)
    decision = harness.build_harness_decision(verdict, budgets=harness.default_budgets())

    assert harness.patch_result_is_empty(patch_result)
    assert harness.plan_requires_file_output(plan)
    assert verdict["next_agent"] == "Generator"
    assert "index.html" in verdict["repair_instruction"]
    assert decision["decision"] == "CALL_GENERATOR"


def test_evaluator_display_summary_humanizes_next_step() -> None:
    harness = HarnessEngine()

    summary = harness.display_summary_for_output(
        "Evaluator",
        {
            "verdict": "FIXABLE",
            "root_cause": "Missing implementation file",
            "next_agent": "Generator",
        },
    )

    assert summary["next_step"] == "交由 Generator 修复后重新验证"
