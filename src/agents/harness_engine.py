from __future__ import annotations

import fnmatch
import json
from utils.json_utils import safe_loads
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from loguru import logger


def _deep_update(d: Dict[str, Any], u: Mapping[str, Any]) -> Dict[str, Any]:
    import collections.abc
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = _deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


class HarnessPolicyViolation(ValueError):
    """Raised when an agent output violates Harness policy."""


@dataclass(frozen=True)
class HarnessRole:
    name: str
    role: str
    goal: str
    success_criteria: List[str]
    tools: List[str]
    handoff: str
    permissions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "success_criteria": self.success_criteria,
            "tools": self.tools,
            "handoff": self.handoff,
            "permissions": self.permissions,
        }


@dataclass(frozen=True)
class HarnessLayer:
    name: str
    purpose: str
    rules: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "rules": self.rules,
        }


@dataclass(frozen=True)
class HarnessPolicy:
    tool_selection: List[str] = field(default_factory=list)
    context_selection: List[str] = field(default_factory=list)
    evidence_flow: List[str] = field(default_factory=list)
    recovery: List[str] = field(default_factory=list)
    user_experience: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_selection": self.tool_selection,
            "context_selection": self.context_selection,
            "evidence_flow": self.evidence_flow,
            "recovery": self.recovery,
            "user_experience": self.user_experience,
        }


class HarnessEngine:
    """Spec-backed Harness Orchestrator contract and policy helpers.

    This class is the single source for the five-role contract, search gate,
    state routing, path/command safety, artifact layout, and user-facing event
    normalization described in HARNESS_ORCHESTRATOR_SPEC.md.
    """

    STATES = [
        "INIT",
        "PLAN",
        "VALIDATE_PLAN",
        "SEARCH",
        "GENERATE",
        "APPLY_PATCH",
        "RUN",
        "EVALUATE",
        "REPAIR",
        "REPLAN",
        "PASS",
        "FAIL_HARD",
    ]

    ERROR_TAXONOMY = {
        "PRODUCT_BUILD_ERROR": "Generator",
        "PRODUCT_RUNTIME_ERROR": "Generator",
        "PRODUCT_UI_ERROR": "Generator",
        "PRODUCT_REQUIREMENT_MISS": "Planner or Generator",
        "RUNNER_SCRIPT_ERROR": "Harness or Runner",
        "RUNNER_TIMEOUT": "Runner or Harness",
        "RUNNER_BROWSER_ERROR": "Runner or Harness",
        "RUNNER_PORT_ERROR": "Planner",
        "RUNNER_CONFIG_ERROR": "Planner",
        "INFRA_DEPENDENCY_MISSING": "Harness",
        "INFRA_INSTALL_FORBIDDEN": "Harness",
        "INFRA_NETWORK_FORBIDDEN": "Harness",
        "INFRA_PERMISSION_DENIED": "Harness",
        "HARNESS_SCHEMA_ERROR": "Harness",
        "HARNESS_POLICY_VIOLATION": "Harness",
        "HARNESS_MAX_ITERATION": "Harness",
    }

    SCHEMA_REQUIRED_FIELDS = {
        "PlanContract": [
            "goal",
            "assumptions",
            "implementation_strategy",
            "allowed_files",
            "forbidden_files",
            "required_files_to_inspect",
            "implementation_steps",
            "test_commands",
            "dev_server",
            "smoke_tests",
            "acceptance_criteria",
            "repair_policy",
            "rollback_policy",
            "external_research",
            "package_json_policy",
            "risks",
        ],
        "SearchReport": [
            "schema_version",
            "task_id",
            "round_id",
            "search_id",
            "query_summary",
            "status",
            "insufficient_evidence",
            "sources",
            "key_findings",
            "implementation_guidance",
            "risks",
            "recommended_next_agent",
            "raw_artifacts",
        ],
        "PatchResult": [
            "schema_version",
            "task_id",
            "round_id",
            "mode",
            "changed_files",
            "created_files",
            "deleted_files",
            "summary",
            "implementation_notes",
            "commands_to_run",
            "risk_points",
            "patch_envelope",
            "needs_replan",
            "replan_reason",
        ],
        "RunReport": [
            "schema_version",
            "task_id",
            "round_id",
            "status",
            "started_at",
            "finished_at",
            "duration_sec",
            "commands",
            "dev_server",
            "browser_tests",
            "artifacts",
            "cleanup",
            "errors",
            "summary",
        ],
        "EvalVerdict": [
            "schema_version",
            "task_id",
            "round_id",
            "verdict",
            "score",
            "passed_criteria",
            "failed_criteria",
            "evidence",
            "root_cause",
            "repair_instruction",
            "needs_search",
            "search_questions",
            "next_agent",
            "confidence",
            "stop_reason",
        ],
    }

    DEFAULT_POLICY = {
        "schema_version": "1.0",
        "sandbox_mode": "workspace-write",
        "approval_policy": "ask",
        "protected_paths": [
            ".env",
            ".env.*",
            ".git/**",
            "node_modules/**",
            "dist/**",
            "build/**",
            ".harness/state.json",
            "workflow_*/**",
            "workflow_game_tests/**",
        ],
        "package_json_policy": {
            "allow_modify": False,
            "allow_add_scripts": False,
            "allow_add_dependencies": False,
            "requires_approval": True,
        },
        "agent_permissions": {
            "Planner": {
                "tools": [],
                "can_read_files": False,
                "can_write_files": False,
                "can_run_commands": False,
                "can_use_browser": False,
                "can_use_search": False,
            },
            "Search": {
                "tools": [
                    "web-search-free",
                    "search",
                    "web-scraper-pro",
                    "firecrawl-scraper",
                    "skill-lookup",
                ],
                "optional_tools": ["computer-use"],
                "can_read_files": False,
                "can_write_files": False,
                "can_run_commands": False,
                "can_use_browser": True,
                "can_use_search": True,
                "can_scrape_web": True,
                "allowed_write_paths": [".harness/search/**"],
                "forbidden_write_paths": [
                    "src/**",
                    "app/**",
                    "components/**",
                    "package.json",
                    ".env",
                    ".git/**",
                    "node_modules/**",
                ],
                "allow_login": False,
                "allow_download": False,
                "allow_execute_remote_code": False,
                "max_pages_to_scrape": 3,
            },
            "Generator": {
                "tools": [
                    "filesystem",
                    "file-manager",
                    "desktop-commander.file_read",
                    "desktop-commander.file_write",
                    "desktop-commander.str_replace",
                ],
                "can_read_files": True,
                "can_write_files": True,
                "can_run_commands": False,
                "can_use_browser": False,
                "can_use_search": False,
                "allowed_write_paths": [
                    "src/**",
                    "app/**",
                    "components/**",
                    "public/**",
                    "index.html",
                ],
                "forbidden_write_paths": [
                    ".env",
                    ".env.*",
                    ".git/**",
                    "node_modules/**",
                    "dist/**",
                    "build/**",
                    ".harness/**",
                    "package.json",
                    "workflow_*/**",
                    "workflow_game_tests/**",
                ],
            },
            "Runner": {
                "tools": [
                    "desktop-commander.terminal",
                    "Skill Management = python runtime",
                    "playwright-e2e",
                    "web-testing-playwright-e2e",
                    "e2e",
                    "computer-use",
                ],
                "can_read_files": True,
                "can_write_project_files": False,
                "can_write_artifacts": True,
                "can_run_commands": True,
                "can_use_browser": True,
                "can_use_search": False,
                "allowed_write_paths": [".harness/**", "logs/**", "screenshots/**", "tmp/**"],
                "forbidden_write_paths": [
                    "src/**",
                    "app/**",
                    "components/**",
                    "package.json",
                    ".env",
                    ".git/**",
                    "node_modules/**",
                ],
            },
            "Evaluator": {
                "tools": [],
                "can_read_files": True,
                "can_write_files": False,
                "can_run_commands": False,
                "can_use_browser": False,
                "can_use_search": False,
            },
        },
        "command_policy": {
            "allowed_commands": [
                "npm run build",
                "npm run lint",
                "npm test",
                "npm run test",
                "npm run dev",
                "pnpm build",
                "pnpm lint",
                "pnpm test",
                "pnpm dev",
                "yarn build",
                "yarn lint",
                "yarn test",
                "yarn dev",
                "python",
                "pytest",
                "node",
            ],
            "blocked_patterns": [
                r"rm\s+-rf\s+/",
                r"\bsudo\b",
                r"curl\s+.*\|\s*bash",
                r"wget\s+.*\|\s*bash",
                r"chmod\s+-R\s+777",
                r"chown\s+-R",
                r"kill\s+-9\s+-1",
                r"\bdd\s+if=",
                r"\bmkfs\b",
                r"diskutil\s+erase",
            ],
            "network_default": False,
            "install_default": False,
            "restrict_to_runner_input_commands": True,
            "require_timeout": True,
            "command_mode": "argv_or_escaped_shell",
        },
    }

    ROLES = [
        HarnessRole(
            name="Planner",
            role="planning_only",
            goal="Turn the user request and project summary into a strict PlanContract.",
            success_criteria=[
                "Outputs strict JSON only.",
                "Defines scope, allowed files, verification commands, smoke tests, and acceptance criteria.",
                "Marks external_research.required only when local context is insufficient or current external facts matter.",
            ],
            tools=[],
            handoff="PlanContract",
            permissions=DEFAULT_POLICY["agent_permissions"]["Planner"],
        ),
        HarnessRole(
            name="Search",
            role="external_research_only",
            goal="Search, scrape, and summarize external facts only when the Harness Search Gate allows it.",
            success_criteria=[
                "Prefers official docs and high-trust sources.",
                "Does not write code, run commands, judge final success, or route directly to another agent.",
                "Returns bounded SearchReport JSON with citations and implementation guidance.",
            ],
            tools=DEFAULT_POLICY["agent_permissions"]["Search"]["tools"],
            handoff="SearchReport",
            permissions=DEFAULT_POLICY["agent_permissions"]["Search"],
        ),
        HarnessRole(
            name="Generator",
            role="code_patch_only",
            goal="Modify only PlanContract.allowed_files and produce a PatchResult.",
            success_criteria=[
                "Keeps implementation scoped to the plan and repair instruction.",
                "Never runs build, browser, search, or unrelated shell commands.",
                "Returns changed files, patch envelope, risk notes, and commands for Runner.",
            ],
            tools=DEFAULT_POLICY["agent_permissions"]["Generator"]["tools"],
            handoff="PatchResult and PatchEnvelope",
            permissions=DEFAULT_POLICY["agent_permissions"]["Generator"],
        ),
        HarnessRole(
            name="Runner",
            role="execution_and_evidence_only",
            goal="Run Harness-provided commands and browser smoke tests, then collect evidence.",
            success_criteria=[
                "Writes logs, screenshots, traces, and JSON reports only under artifact paths.",
                "Never repairs product code or judges final acceptance.",
                "Classifies errors with the Harness taxonomy and always cleans up processes.",
            ],
            tools=DEFAULT_POLICY["agent_permissions"]["Runner"]["tools"],
            handoff="RunReport",
            permissions=DEFAULT_POLICY["agent_permissions"]["Runner"],
        ),
        HarnessRole(
            name="Evaluator",
            role="judgment_only",
            goal="Judge PlanContract, PatchResult, RunReport, and evidence once per round.",
            success_criteria=[
                "Outputs exactly one EvalVerdict JSON.",
                "Routes PRODUCT errors to Generator and Runner/Infra errors away from product code.",
                "Sets needs_search only for third-party API uncertainty.",
            ],
            tools=[],
            handoff="EvalVerdict",
            permissions=DEFAULT_POLICY["agent_permissions"]["Evaluator"],
        ),
    ]

    LAYERS = [
        HarnessLayer(
            name="1. State Machine",
            purpose="Own task state transitions instead of letting agents call each other.",
            rules=[
                "All agent inputs and outputs go through Harness.",
                "Each round calls Generator, Runner, and Evaluator at most once.",
                "PASS and FAIL_HARD are the only terminal states.",
            ],
        ),
        HarnessLayer(
            name="2. Policy and Permissions",
            purpose="Route tools by role and enforce read/write/command/search boundaries.",
            rules=[
                "Forbidden paths beat allowed paths.",
                "Runner cannot write business files.",
                "Search is disabled unless the Search Gate says yes.",
            ],
        ),
        HarnessLayer(
            name="3. Contracts and Schemas",
            purpose="Validate PlanContract, SearchReport, PatchResult, RunReport, and EvalVerdict.",
            rules=[
                "Agent output must be JSON-shaped before the next state.",
                "Missing required fields are Harness schema errors.",
                "Patch envelopes are dry-run checked before application.",
            ],
        ),
        HarnessLayer(
            name="4. Budget and Recovery",
            purpose="Prevent runaway loops and preserve evidence across repairs.",
            rules=[
                "Search is capped independently from repair loops.",
                "Repeated identical root causes force REPLAN or FAIL_HARD.",
                "Cleanup runs on Runner interruption or hard failure.",
            ],
        ),
        HarnessLayer(
            name="5. Evidence and Artifacts",
            purpose="Store inputs, outputs, diffs, logs, screenshots, traces, and reports.",
            rules=[
                "Every run writes under .harness/runs/run_xxx/.",
                "Search artifacts write under .harness/search/search_xxx/.",
                "Final reports point to evidence, not raw transcript noise.",
            ],
        ),
        HarnessLayer(
            name="6. User-Facing Summary",
            purpose="Normalize raw agent/tool logs into clear user events for the UI.",
            rules=[
                "Default UI shows status, progress, current issue, next step, and approval need.",
                "Raw tool calls and JSON stay in debug views.",
                "Runner script errors are explained without blaming product code by default.",
            ],
        ),
    ]

    POLICY = HarnessPolicy(
        tool_selection=[
            "Planner and Evaluator have no tools.",
            "Generator can read/write scoped files but cannot run commands, browse, or search.",
            "Runner executes only Harness-provided commands and smoke tests.",
            "Search uses external lookup only after Search Gate approval.",
        ],
        context_selection=[
            "All agents receive a bounded ContextBundle with recent messages, working memory, and artifact index.",
            "Planner receives user request, project summary, constraints, previous failures, SearchReports, and ContextBundle.",
            "Generator receives PlanContract, scoped file snapshots, optional RunReport/EvalVerdict/SearchReport, and ContextBundle.",
            "Runner receives PlanContract, PatchResult, optional SearchReport, artifact paths, and ContextBundle.",
            "Evaluator receives contracts, run evidence, screenshots, diff summary, previous verdicts, and ContextBundle.",
        ],
        evidence_flow=[
            "Raw logs are written as artifacts and summarized into RunReport.",
            "Search findings are cited and injected by Harness, never directly by Search.",
            "Evaluator returns concrete repair instructions rather than invoking more tools.",
        ],
        recovery=[
            "FIXABLE routes to Generator until repair budget is exhausted.",
            "needs_search routes to Search only for external API uncertainty.",
            "Infrastructure and Runner script errors do not become product patches unless evidence says product code is at fault.",
        ],
        user_experience=[
            "Render Harness UserEvents in the main timeline.",
            "Hide raw agent/tool names from the primary status copy.",
            "Use debug drawers for stdout, stderr, raw tool calls, and contract JSON.",
        ],
    )

    THIRD_PARTY_ERROR_TYPES = {
        "UNKNOWN_API_USAGE",
        "DEPENDENCY_VERSION_ERROR",
        "THIRD_PARTY_SDK_ERROR",
    }


    AGENT_INPUT_REQUIRED = {
        "Planner": ["task_context", "previous_failures"],
        "Search": [
            "schema_version",
            "task_id",
            "round_id",
            "search_id",
            "triggered_by",
            "reason",
            "research_questions",
            "queries",
            "allowed_domains",
            "blocked_domains",
            "max_results",
            "max_pages_to_scrape",
            "freshness",
            "source_preference",
            "context",
            "permissions",
        ],
        "Generator": [
            "task_id",
            "round_id",
            "mode",
            "workspace",
            "plan_contract",
        ],
        "Runner": [
            "schema_version",
            "task_id",
            "round_id",
            "workspace",
            "run_dir",
            "plan_contract",
            "patch_result",
            "test_commands",
            "dev_server",
            "smoke_tests",
            "runner_limits",
            "permissions",
            "search_reports",
        ],
        "Evaluator": [
            "schema_version",
            "task_id",
            "round_id",
            "plan_contract",
            "patch_result",
            "run_report",
            "git_diff_summary",
            "screenshots",
            "previous_eval_verdicts",
        ],
    }

    ROLE_TOOL_ALIASES = {
        "Planner": set(),
        "Search": {
            "web-search-free",
            "search",
            "web-scraper-pro",
            "firecrawl-scraper",
            "skill-lookup",
            "computer-use",
            "web_search",
            "advanced_web_search",
            "computer",
        },
        "Generator": {
            "filesystem",
            "file-manager",
            "desktop-commander.file_read",
            "desktop-commander.file_write",
            "desktop-commander.str_replace",
            "str_replace_editor",
        },
        "Runner": {
            "desktop-commander.terminal",
            "Skill Management = python runtime",
            "desktop-commander",
            "playwright-e2e",
            "web-testing-playwright-e2e",
            "e2e",
            "computer-use",
            "bash",
            "computer",
        },
        "Evaluator": set(),
    }

    def load_agent_prompt(self, role: str, fallback: str = "") -> str:
        prompt_name = f"{str(role or '').strip().lower()}.prompt.md"
        from utils.paths import identity_prompts_root
        prompt_path = identity_prompts_root() / prompt_name
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        except OSError:
            prompt_text = ""
        return prompt_text or fallback.strip()

    def validate_agent_input(self, role: str, payload: Mapping[str, Any]) -> List[str]:
        required = self.AGENT_INPUT_REQUIRED.get(role)
        if required is None:
            raise HarnessPolicyViolation(f"Unknown agent input contract: {role}")
        missing = [field for field in required if field not in payload]
        if missing:
            raise HarnessPolicyViolation(
                f"{role} input missing required fields: {', '.join(missing)}"
            )
        if role == "Planner":
            task_context = payload.get("task_context") if isinstance(payload.get("task_context"), Mapping) else {}
            if "context_bundle" not in task_context:
                raise HarnessPolicyViolation("Planner input missing task_context.context_bundle")
        elif role == "Search":
            context = payload.get("context") if isinstance(payload.get("context"), Mapping) else {}
            if "context_bundle" not in context:
                raise HarnessPolicyViolation("Search input missing context.context_bundle")
        elif role in {"Generator", "Runner", "Evaluator"} and "context_bundle" not in payload:
            raise HarnessPolicyViolation(f"{role} input missing context_bundle")
        return []

    def filter_tools_for_role(self, role: str, tools: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        allowed_names = set(self.ROLE_TOOL_ALIASES.get(role, set()))
        if not allowed_names:
            return []
        filtered: List[Dict[str, Any]] = []
        for tool in tools:
            name = str(tool.get("name") or "").strip()
            if name and name in allowed_names:
                filtered.append(dict(tool))
        return filtered

    def route_after_search(
        self,
        search_report: Mapping[str, Any],
        *,
        plan: Optional[Mapping[str, Any]] = None,
        verdict: Optional[Mapping[str, Any]] = None,
    ) -> str:
        status = str((search_report or {}).get("status") or "").strip().upper()
        recommended_next = str((search_report or {}).get("recommended_next_agent") or "").strip()
        if status == "FAILED" or bool((search_report or {}).get("insufficient_evidence")):
            return "REPLAN"
        if recommended_next == "Planner":
            return "REPLAN"
        if recommended_next == "Runner":
            return "RUN"
        if recommended_next == "Evaluator":
            return "EVALUATE"
        if recommended_next == "None":
            return "PASS"
        if str((verdict or {}).get("next_agent") or "").strip() == "Search":
            return "RUN"
        if bool(((plan or {}).get("external_research") or {}).get("required")):
            return "GENERATE"
        return "GENERATE"

    def default_strategy(self) -> str:
        return "default"

    def architecture_signature(self) -> Dict[str, Any]:
        return {
            "pattern": "agent + model + harness",
            "orchestrator": "Harness Orchestrator",
            "summary_zh": "所有 Agent 的输入输出都进入 Harness；Harness 负责状态、权限、Search Gate、预算、补丁、证据、回滚和最终状态。",
            "summary_en": "All agent inputs and outputs pass through the Harness, which owns state, permissions, search gate, budgets, patches, evidence, rollback, and final status.",
            "roles": [role.to_dict() for role in self.ROLES],
            "layers": [layer.to_dict() for layer in self.LAYERS],
            "policy": self.POLICY.to_dict(),
            "default_policy": self.default_policy(),
            "default_budgets": self.default_budgets(),
            "state_machine": self.state_machine(),
            "error_taxonomy": dict(self.ERROR_TAXONOMY),
            "schemas": {key: list(value) for key, value in self.SCHEMA_REQUIRED_FIELDS.items()},
            "strategy_routes": {"agent": self.default_strategy()},
            "phase_order": list(self.STATES),
            "artifact_layout": self.artifact_layout(),
            "ui_model": {
                "raw_flow": "Raw Agent Events -> Harness Normalizer -> UserEvent -> UI",
                "default_tabs": ["Overview", "Changes", "Tests", "Logs", "JSON"],
                "primary_fields": ["status", "progress", "current_issue", "next_action", "approval_required"],
            },
        }

    def state_machine(self) -> Dict[str, Any]:
        return {
            "initial": "INIT",
            "terminal": ["PASS", "FAIL_HARD"],
            "flow": {
                "INIT": ["PLAN"],
                "PLAN": ["VALIDATE_PLAN"],
                "VALIDATE_PLAN": ["SEARCH", "GENERATE", "FAIL_HARD"],
                "SEARCH": ["GENERATE", "REPLAN", "FAIL_HARD"],
                "GENERATE": ["APPLY_PATCH", "REPLAN", "FAIL_HARD"],
                "APPLY_PATCH": ["RUN", "FAIL_HARD"],
                "RUN": ["EVALUATE", "FAIL_HARD"],
                "EVALUATE": ["PASS", "GENERATE", "REPLAN", "SEARCH", "FAIL_HARD"],
                "REPLAN": ["PLAN", "FAIL_HARD"],
                "REPAIR": ["GENERATE", "REPLAN", "FAIL_HARD"],
            },
            "hard_rules": [
                "Evaluator cannot call Runner.",
                "Runner cannot call Generator.",
                "Generator cannot call Runner.",
                "Search cannot call Planner, Generator, Runner, or Evaluator.",
                "Harness validates schema before moving to the next state.",
            ],
        }

    def artifact_layout(self) -> Dict[str, Any]:
        return {
            "root": ".harness",
            "top_level": [
                "task.json",
                "session.json",
                "project_summary.json",
                "plan.json",
                "state.json",
                "policy.json",
                "budgets.json",
                "final_report.md",
                "failure_analysis.md",
            ],
            "run_dir": ".harness/runs/run_001",
            "run_children": [
                "input/generator_input.json",
                "input/runner_input.json",
                "input/evaluator_input.json",
                "output/patch_result.json",
                "output/run_report.json",
                "output/eval_verdict.json",
                "diff.patch",
                "stdout/",
                "stderr/",
                "screenshots/",
                "traces/",
                "browser_console.json",
            ],
            "search_dir": ".harness/search/search_001",
            "search_children": [
                "search_request.json",
                "search_report.json",
                "sources.json",
                "pages/",
                "citations.json",
            ],
        }

    def _get_system_config(self, filename: str) -> Optional[Dict[str, Any]]:
        try:
            repo_root = Path(__file__).resolve().parents[2]
            config_file = repo_root / ".harness" / filename
            if config_file.exists():
                custom = safe_loads(config_file.read_text(encoding="utf-8"))
                if isinstance(custom, dict):
                    return custom
        except Exception as e:
            logger.warning(f"Failed to read system config {filename}: {e}")
        return None

    def default_policy(self, workspace_root: Optional[str] = None) -> Dict[str, Any]:
        policy = safe_loads(json.dumps(self.DEFAULT_POLICY))
        sys_policy = self._get_system_config("policy.json")
        if sys_policy:
            _deep_update(policy, sys_policy)
        if workspace_root:
            policy["workspace_root"] = workspace_root
        return policy

    def default_budgets(self) -> Dict[str, Any]:
        sys_budgets = self._get_system_config("budgets.json")
        if not sys_budgets:
            raise HarnessPolicyViolation("Global .harness/budgets.json not found or invalid.")
        return sys_budgets
        
    def get_policy(self, workspace_root: Optional[str] = None) -> Dict[str, Any]:
        policy = self.default_policy(workspace_root)
        if workspace_root:
            try:
                policy_file = Path(workspace_root) / ".harness" / "policy.json"
                if policy_file.exists():
                    custom = safe_loads(policy_file.read_text(encoding="utf-8"))
                    if isinstance(custom, dict):
                        _deep_update(policy, custom)
            except Exception as e:
                logger.warning(f"Failed to read custom policy from {workspace_root}: {e}")
        return policy

    def get_budgets(self, workspace_root: Optional[str] = None) -> Dict[str, Any]:
        budgets = self.default_budgets()
        if workspace_root:
            try:
                budgets_file = Path(workspace_root) / ".harness" / "budgets.json"
                if budgets_file.exists():
                    custom = safe_loads(budgets_file.read_text(encoding="utf-8"))
                    if isinstance(custom, dict):
                        _deep_update(budgets, custom)
            except Exception as e:
                logger.warning(f"Failed to read custom budgets from {workspace_root}: {e}")
        return budgets

    def validate_schema(self, payload: Mapping[str, Any], schema_name: str) -> List[str]:
        required = self.SCHEMA_REQUIRED_FIELDS.get(schema_name)
        if required is None:
            raise HarnessPolicyViolation(f"Unknown schema: {schema_name}")
        missing = [field for field in required if field not in payload]
        if missing:
            raise HarnessPolicyViolation(
                f"{schema_name} missing required fields: {', '.join(missing)}"
            )
        return []

    @staticmethod
    def patch_result_is_empty(patch_result: Optional[Mapping[str, Any]]) -> bool:
        if not patch_result:
            return True
        changed = list(patch_result.get("changed_files") or [])
        created = list(patch_result.get("created_files") or [])
        deleted = list(patch_result.get("deleted_files") or [])
        envelope = patch_result.get("patch_envelope") if isinstance(patch_result.get("patch_envelope"), Mapping) else {}
        operations = list(envelope.get("operations") or [])
        envelope_changed = list(envelope.get("changed_files") or [])
        return not any([changed, created, deleted, operations, envelope_changed])

    @staticmethod
    def required_output_files(plan: Optional[Mapping[str, Any]]) -> List[str]:
        plan = plan or {}
        allowed_files = [str(item).strip().replace("\\", "/") for item in (plan.get("allowed_files") or [])]
        concrete: List[str] = []
        for path in allowed_files:
            if not path or any(token in path for token in ("*", "?", "[")) or path.endswith("/"):
                continue
            if path in {".env", "package.json"} or path.startswith((".git/", "node_modules/", ".harness/")):
                continue
            concrete.append(path)
        seen = set()
        result: List[str] = []
        for path in concrete:
            if path not in seen:
                seen.add(path)
                result.append(path)
        return result

    def plan_requires_file_output(self, plan: Optional[Mapping[str, Any]]) -> bool:
        return bool(self.required_output_files(plan))

    def empty_patch_verdict(
        self,
        plan: Mapping[str, Any],
        patch_result: Mapping[str, Any],
        *,
        round_id: int,
    ) -> Dict[str, Any]:
        required_files = self.required_output_files(plan)
        required_text = ", ".join(required_files) if required_files else "planned implementation files"
        evidence = [
            "PatchResult changed_files, created_files, and deleted_files are empty.",
            "PatchEnvelope operations is empty, so no implementation file was created or modified.",
        ]
        if required_files:
            evidence.append(f"Required output file(s): {required_text}.")
        verdict = {
            "schema_version": "1.0",
            "task_id": str(plan.get("task_id") or patch_result.get("task_id") or "task_runtime_001"),
            "round_id": round_id,
            "verdict": "FAIL_HARD",
            "score": 0.0,
            "passed_criteria": [],
            "failed_criteria": list(plan.get("acceptance_criteria") or ["Generator must create or modify the planned files."]),
            "evidence": evidence,
            "root_cause": f"Generator did not create any implementation files; {required_text} was not produced.",
            "repair_instruction": f"Generator must use the file editing tool to create or modify {required_text}, then return a non-empty PatchEnvelope.",
            "needs_search": False,
            "search_questions": [],
            "next_agent": "Generator",
            "confidence": 0.92,
            "stop_reason": "Empty Generator patch cannot be validated by Runner.",
        }
        verdict["display_summary"] = self.display_summary_for_output("Evaluator", verdict)
        return verdict

    def should_search(
        self,
        ctx: Optional[Mapping[str, Any]] = None,
        *,
        user_request: Optional[str] = None,
        plan: Optional[Mapping[str, Any]] = None,
        run_report: Optional[Mapping[str, Any]] = None,
        eval_verdict: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        ctx = ctx or {}
        external_research = (plan or {}).get("external_research") or {}
        if bool(external_research.get("required") or external_research.get("search_agent_required")):
            return True

        for err in (run_report or {}).get("errors", []) or []:
            err_type = str(err.get("type") or "")
            root_category = str(err.get("root_category") or "")
            if err_type in self.THIRD_PARTY_ERROR_TYPES:
                return True
            if err_type == "RUNNER_SCRIPT_ERROR" and root_category == "UNKNOWN_API_USAGE":
                return True

        if bool((eval_verdict or {}).get("needs_search")):
            return True

        return False

    def build_harness_decision(
        self,
        verdict: Mapping[str, Any],
        *,
        repair_round: int = 0,
        replan_round: int = 0,
        search_call_count: int = 0,
        same_error_repeated: bool = False,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        budgets = budgets or self.DEFAULT_BUDGETS
        result = str(verdict.get("verdict") or "").upper()
        repair_instruction = str(verdict.get("repair_instruction") or "").strip()
        root_cause = str(verdict.get("root_cause") or "").strip()
        if self._should_retry_generator(verdict):
            result = "FIXABLE"
            if not repair_instruction:
                repair_instruction = (
                    root_cause
                    or "Generator should create the missing implementation files and retry validation."
                )
        if result == "PASS":
            decision, next_state, next_agent = "PASS", "PASS", "None"
            reason = "All required checks and acceptance criteria passed."
        elif verdict.get("needs_search") and search_call_count < int(
            budgets.get("max_search_calls_per_task", 2)
        ):
            decision, next_state, next_agent = "CALL_SEARCH", "SEARCH", "Search"
            reason = "Evaluator requested external research for uncertain API or documentation facts."
        elif result == "FIXABLE" and same_error_repeated:
            if replan_round < int(budgets.get("max_replan_rounds", 1)):
                decision, next_state, next_agent = "CALL_PLANNER", "REPLAN", "Planner"
                reason = "The same root cause repeated and must be replanned."
            else:
                decision, next_state, next_agent = "FAIL_HARD", "FAIL_HARD", "None"
                reason = "The same root cause repeated and no replan budget remains."
        elif result == "FIXABLE" and repair_round < int(budgets.get("max_repair_rounds", 3)):
            decision, next_state, next_agent = "CALL_GENERATOR", "GENERATE", "Generator"
            reason = repair_instruction or "Fixable product issue."
        elif result == "FIXABLE" and replan_round < int(budgets.get("max_replan_rounds", 1)):
            decision, next_state, next_agent = "CALL_PLANNER", "REPLAN", "Planner"
            reason = "Repair budget was exhausted; the plan must be revised."
        elif result == "REPLAN" and replan_round < int(budgets.get("max_replan_rounds", 1)):
            decision, next_state, next_agent = "CALL_PLANNER", "REPLAN", "Planner"
            reason = root_cause or "Plan needs revision."
        elif result in ("INFRA", "FAIL_HARD") and replan_round < int(budgets.get("max_replan_rounds", 1)):
            decision, next_state, next_agent = "CALL_PLANNER", "REPLAN", "Planner"
            reason = f"Encountered {result} error. Delegating back to Planner for LLM analysis and replanning."
        else:
            decision, next_state, next_agent = "FAIL_HARD", "FAIL_HARD", "None"
            reason = str(verdict.get("stop_reason") or root_cause or "No safe next step remains.")

        return {
            "task_id": str(verdict.get("task_id") or "task_runtime_001"),
            "round_id": int(verdict.get("round_id") or 1),
            "decision": decision,
            "reason": reason,
            "next_state": next_state,
            "next_agent": next_agent,
            "budget_remaining": {
                "repair_rounds": max(0, int(budgets.get("max_repair_rounds", 3)) - repair_round),
                "replan_rounds": max(0, int(budgets.get("max_replan_rounds", 1)) - replan_round),
                "search_calls": max(0, int(budgets.get("max_search_calls_per_task", 2)) - search_call_count),
            },
        }

    def same_error_repeated(
        self,
        previous_verdicts: Sequence[Mapping[str, Any]],
        current_verdict: Optional[Mapping[str, Any]] = None,
        *,
        max_same_error_repeats: Optional[int] = None,
    ) -> bool:
        limit = max(2, int(max_same_error_repeats or self.DEFAULT_BUDGETS.get("max_same_error_repeats", 2)))
        causes: List[str] = []
        for verdict in previous_verdicts:
            root_cause = str((verdict or {}).get("root_cause") or "").strip().lower()
            if root_cause:
                causes.append(root_cause)
        if current_verdict is not None:
            root_cause = str((current_verdict or {}).get("root_cause") or "").strip().lower()
            if root_cause:
                causes.append(root_cause)
        if len(causes) < limit:
            return False
        tail = causes[-limit:]
        return bool(tail and len(set(tail)) == 1)

    def is_path_allowed(
        self,
        path: str,
        allowed: Sequence[str],
        forbidden: Sequence[str],
        workspace: str | Path,
    ) -> bool:
        safe_path = self._normalize_workspace_path(path)
        if safe_path is None:
            return False
        workspace_root = Path(workspace).expanduser().resolve()
        real_path = (workspace_root / safe_path).resolve(strict=False)
        try:
            real_path.relative_to(workspace_root)
        except ValueError:
            return False
        if self._matches_any(safe_path, forbidden):
            return False
        return self._matches_any(safe_path, allowed)

    def validate_patch_policy(
        self,
        patch_result: Mapping[str, Any],
        plan: Mapping[str, Any],
        *,
        workspace: str | Path,
        policy: Optional[Mapping[str, Any]] = None,
    ) -> List[str]:
        policy = policy or self.DEFAULT_POLICY
        generator_policy = (policy.get("agent_permissions") or {}).get("Generator", {})
        allowed = list(plan.get("allowed_files") or generator_policy.get("allowed_write_paths") or [])
        forbidden = list(plan.get("forbidden_files") or generator_policy.get("forbidden_write_paths") or [])
        changed_paths = set()
        for key in ("changed_files", "created_files", "deleted_files"):
            changed_paths.update(str(item) for item in patch_result.get(key, []) or [])
        envelope = patch_result.get("patch_envelope") or {}
        for op in envelope.get("operations", []) or []:
            if isinstance(op, Mapping) and op.get("path"):
                changed_paths.add(str(op["path"]))
        violations = [
            path
            for path in sorted(changed_paths)
            if not self.is_path_allowed(path, allowed, forbidden, workspace)
        ]
        if violations:
            raise HarnessPolicyViolation(
                "Patch writes outside allowed files or into forbidden files: "
                + ", ".join(violations)
            )
        return []

    def validate_patch_envelope(
        self,
        patch_envelope: Mapping[str, Any],
        plan: Mapping[str, Any],
        *,
        workspace: str | Path,
        policy: Optional[Mapping[str, Any]] = None,
    ) -> List[str]:
        policy = policy or self.DEFAULT_POLICY
        generator_policy = (policy.get("agent_permissions") or {}).get("Generator", {})
        allowed = list(plan.get("allowed_files") or generator_policy.get("allowed_write_paths") or [])
        forbidden = list(plan.get("forbidden_files") or generator_policy.get("forbidden_write_paths") or [])
        operations = list(patch_envelope.get("operations") or [])
        changed_files = [str(item) for item in patch_envelope.get("changed_files", []) or []]
        if not operations and not changed_files:
            return []
        touched_paths = set(changed_files)
        for operation in operations:
            if not isinstance(operation, Mapping):
                raise HarnessPolicyViolation("PatchEnvelope operations must be objects.")
            path = str(operation.get("path") or "").strip()
            if not path:
                raise HarnessPolicyViolation("PatchEnvelope operation missing path.")
            touched_paths.add(path)
        violations = [
            path
            for path in sorted(touched_paths)
            if not self.is_path_allowed(path, allowed, forbidden, workspace)
        ]
        if violations:
            raise HarnessPolicyViolation(
                "PatchEnvelope writes outside allowed files or into forbidden files: "
                + ", ".join(violations)
            )
        return []

    async def apply_patch_envelope(
        self,
        patch_envelope: Mapping[str, Any],
        plan: Mapping[str, Any],
        *,
        workspace: str | Path,
        vllm_client: Optional[Any] = None,
        model: Optional[str] = None,
        policy: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, List[str]]:
        self.validate_patch_envelope(patch_envelope, plan, workspace=workspace, policy=policy)
        workspace_root = Path(workspace).expanduser().resolve()
        applied = {"changed_files": [], "created_files": [], "deleted_files": []}
        operations = list(patch_envelope.get("operations") or [])
        for operation in operations:
            if not isinstance(operation, Mapping):
                raise HarnessPolicyViolation("PatchEnvelope operations must be objects.")
            raw_path = str(operation.get("path") or "").strip()
            normalized_path = self._normalize_workspace_path(raw_path)
            if not normalized_path:
                raise HarnessPolicyViolation("PatchEnvelope operation missing valid path.")
            target_path = (workspace_root / normalized_path).resolve(strict=False)
            try:
                target_path.relative_to(workspace_root)
            except ValueError as exc:
                raise HarnessPolicyViolation("PatchEnvelope path escapes workspace.") from exc
            op_name = str(operation.get("op") or patch_envelope.get("patch_type") or "").strip() or "file_replacement"
            existed_before = target_path.exists()
            if op_name == "file_replacement":
                if operation.get("content") is None:
                    if existed_before and target_path.is_file():
                        continue
                    raise HarnessPolicyViolation(f"file_replacement operation missing content for {normalized_path}.")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(str(operation.get("content") or ""), encoding="utf-8")
                if existed_before:
                    applied["changed_files"].append(normalized_path)
                else:
                    applied["created_files"].append(normalized_path)
                continue
            if op_name == "str_replace":
                if not existed_before or not target_path.is_file():
                    raise HarnessPolicyViolation(f"str_replace target does not exist: {normalized_path}")
                old_text = operation.get("old_text") if operation.get("old_text") is not None else operation.get("old_str")
                new_text = operation.get("new_text") if operation.get("new_text") is not None else operation.get("new_str")
                if old_text is None or new_text is None:
                    raise HarnessPolicyViolation(f"str_replace operation missing old_text/new_text for {normalized_path}.")
                try:
                    original_text = target_path.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise HarnessPolicyViolation(
                        f"Cannot apply text str_replace to non-UTF-8 or binary artifact: {normalized_path}."
                    ) from exc
                old_str_val = str(old_text)
                new_str_val = str(new_text)

                match_count = original_text.count(old_str_val)
                if match_count == 1:
                    target_path.write_text(original_text.replace(old_str_val, new_str_val, 1), encoding="utf-8")
                    applied["changed_files"].append(normalized_path)
                    continue

                if match_count == 0:
                    import re
                    tokens = re.split(r'(\s+)', old_str_val)
                    pattern_parts = []
                    for t in tokens:
                        if not t:
                            continue
                        if t.isspace():
                            pattern_parts.append(r'\s+')
                        else:
                            pattern_parts.append(re.escape(t))
                    pattern = ''.join(pattern_parts)
                    try:
                        matches = list(re.finditer(pattern, original_text))
                        if len(matches) == 1:
                            m = matches[0]
                            new_content = original_text[:m.start()] + new_str_val + original_text[m.end():]
                            target_path.write_text(new_content, encoding="utf-8")
                            applied["changed_files"].append(normalized_path)
                            continue
                        else:
                            if vllm_client is not None:
                                logger.info(f"Fuzzy match failed for {normalized_path}, attempting LLM extraction fallback.")
                                messages = [
                                    {"role": "system", "content": "You are a precise code patch tool. Given the original file content and the intended old/new text snippet, return the COMPLETELY MODIFIED file content. Return ONLY the new file content. Do not output markdown backticks, explanations, or any other text."},
                                    {"role": "user", "content": f"=== ORIGINAL FILE ===\n{original_text}\n\n=== INTENDED OLD TEXT TO REPLACE ===\n{old_str_val}\n\n=== REPLACEMENT TEXT ===\n{new_str_val}\n\nReturn the fully updated file content directly without any backticks or formatting. It must be valid code."}
                                ]
                                try:
                                    response = await vllm_client.chat_completion(messages, model=model, temperature=0.1)
                                    if isinstance(response, dict) and response.get("choices"):
                                        new_content = response["choices"][0]["message"]["content"]
                                        if new_content.startswith("```"):
                                            lines = new_content.splitlines()
                                            if lines and lines[0].startswith("```"): lines = lines[1:]
                                            if lines and lines[-1].startswith("```"): lines = lines[:-1]
                                            new_content = "\n".join(lines) + "\n"
                                        target_path.write_text(new_content, encoding="utf-8")
                                        applied["changed_files"].append(normalized_path)
                                        continue
                                except Exception as llm_exc:
                                    logger.warning(f"LLM extraction fallback failed: {llm_exc}")
                            
                            raise HarnessPolicyViolation(
                                f"str_replace requires exactly one match in {normalized_path}; found 0 exact and {len(matches)} fuzzy matches."
                            )
                    except Exception as exc:
                        if isinstance(exc, HarnessPolicyViolation):
                            raise
                        # Ignore regex compile errors or other unexpected issues and fallback to original error
                        pass

                raise HarnessPolicyViolation(
                    f"str_replace requires exactly one match in {normalized_path}; found {match_count}."
                )
            if op_name == "unified_diff":
                raise HarnessPolicyViolation("unified_diff patch application is not supported by Harness runtime.")
            raise HarnessPolicyViolation(f"Unsupported PatchEnvelope operation: {op_name}")
        for key in applied:
            applied[key] = list(dict.fromkeys(applied[key]))
        return applied

    def command_allowed(
        self,
        command: str,
        *,
        runner_input_commands: Optional[Iterable[str]] = None,
        policy: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        policy = policy or self.DEFAULT_POLICY
        command_policy = policy.get("command_policy") or {}
        text = (command or "").strip()
        if not text:
            return False
        for pattern in command_policy.get("blocked_patterns", []) or []:
            if re.search(pattern, text, re.IGNORECASE):
                return False
        if runner_input_commands is not None:
            normalized_allowed = {self._normalize_command(item) for item in runner_input_commands}
            return self._normalize_command(text) in normalized_allowed
        prefixes = command_policy.get("allowed_commands", []) or []
        return any(text == prefix or text.startswith(f"{prefix} ") for prefix in prefixes)

    def normalize_user_event(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        raw_error = " ".join(
            str(event.get(key) or "")
            for key in ("error", "content", "detail", "message", "summary")
        )
        tool = str(event.get("tool") or event.get("skill") or "").strip()
        status = str(event.get("status") or "").strip()

        if "Locator can't be used in 'await'" in raw_error or "object Locator" in raw_error:
            return {
                "type": "validation_issue",
                "severity": "warning",
                "title": "自动化验证脚本出错",
                "summary": "页面已加载成功，但点击按钮的测试脚本写法有问题。",
                "details": "Playwright locator() 不应直接 await，应创建 locator 后 await locator.click()。",
                "is_user_action_required": False,
                "recommended_action": "修复 Runner 测试脚本并重新验证",
                "debug_ref": event.get("artifactPath") or event.get("debug_ref") or "",
                "hiddenByDefault": False,
            }
        if status in {"running", "queued"} and tool:
            return {
                "type": "work_in_progress",
                "severity": "info",
                "title": self._friendly_tool_title(tool, running=True),
                "summary": str(event.get("description") or event.get("detail") or ""),
                "is_user_action_required": False,
                "recommended_action": "",
                "hiddenByDefault": False,
            }
        if status in {"success", "completed"} or event.get("success") is True:
            return {
                "type": "step_completed",
                "severity": "success",
                "title": self._friendly_tool_title(tool, running=False) if tool else "步骤已完成",
                "summary": str(event.get("description") or event.get("detail") or event.get("summary") or ""),
                "is_user_action_required": False,
                "recommended_action": "",
                "hiddenByDefault": False,
            }
        if status in {"error", "failed"} or event.get("success") is False:
            return {
                "type": "validation_issue",
                "severity": "warning",
                "title": "验证遇到问题",
                "summary": self._humanize_error(raw_error),
                "details": raw_error[:1000],
                "is_user_action_required": False,
                "recommended_action": "根据证据进入修复或重新规划",
                "hiddenByDefault": False,
            }
        return {
            "type": "debug",
            "severity": "info",
            "title": "内部事件",
            "summary": str(event.get("summary") or event.get("detail") or ""),
            "hiddenByDefault": True,
        }

    def display_summary_for_output(self, agent: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        existing = payload.get("display_summary")
        if isinstance(existing, Mapping):
            return dict(existing)
        agent_name = agent.strip().title()
        if agent_name == "Generator":
            files = payload.get("changed_files") or []
            return {
                "title": "已完成代码修改",
                "status": "success",
                "summary": str(payload.get("summary") or f"修改了 {len(files)} 个文件。"),
                "highlights": [str(item) for item in files[:5]],
                "user_visible": True,
            }
        if agent_name == "Runner":
            status = str(payload.get("status") or "UNKNOWN")
            return {
                "title": "验证完成" if status == "PASSED" else "验证遇到问题",
                "status": "success" if status == "PASSED" else "warning",
                "summary": str(payload.get("summary") or ""),
                "highlights": self._runner_highlights(payload),
                "user_visible": True,
            }
        if agent_name == "Evaluator":
            verdict = str(payload.get("verdict") or "")
            next_agent = str(payload.get("next_agent") or "None")
            return {
                "title": "验收通过" if verdict == "PASS" else "需要继续处理",
                "status": "success" if verdict == "PASS" else "blocked",
                "summary": str(payload.get("root_cause") or payload.get("repair_instruction") or ""),
                "next_step": self._friendly_next_step(next_agent),
                "user_visible": True,
            }
        return {
            "title": f"{agent_name} 输出已记录",
            "status": "info",
            "summary": str(payload.get("summary") or payload.get("query_summary") or ""),
            "user_visible": True,
        }

    def create_scaffold(self, workspace: str | Path, *, overwrite: bool = False) -> List[str]:
        root = Path(workspace).expanduser().resolve()
        harness_root = root / ".harness"
        paths = [
            harness_root,
            harness_root / "runs",
            harness_root / "search",
            root / "logs",
            root / "screenshots",
            root / "tmp",
        ]
        created: List[str] = []
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path.relative_to(root)))
        files = {
            harness_root / "policy.json": self.default_policy(str(root)),
            harness_root / "budgets.json": self.default_budgets(),
        }
        for path, payload in files.items():
            if path.exists() and not overwrite:
                continue
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            created.append(str(path.relative_to(root)))
        return created

    def system_addendum(
        self,
        user_message: str,
        tool_names: List[str],
        harness_strategy: Optional[str] = None,
    ) -> str:
        tool_line = ", ".join(tool_names) if tool_names else "none"
        strategy = harness_strategy or self.default_strategy()
        roles = "\n".join(
            f"- {role.name} ({role.role}): {role.goal} Handoff: {role.handoff}."
            for role in self.ROLES
        )
        layers = "\n".join(
            f"- {layer.name}: {layer.purpose} Rules: {'; '.join(layer.rules)}"
            for layer in self.LAYERS
        )
        return (
            "[OBS Harness Orchestrator Contract]\n"
            "All agent inputs and outputs must go through Harness. Agents never call each other directly.\n"
            f"Current harness strategy: {strategy}.\n"
            f"Available tools this turn: {tool_line}.\n"
            f"Current user request excerpt: {(user_message or '')[:300]}\n\n"
            "[Roles]\n"
            f"{roles}\n\n"
            "[State Flow]\n"
            "INIT -> PLAN -> VALIDATE_PLAN -> SEARCH? -> GENERATE -> APPLY_PATCH -> RUN -> EVALUATE -> PASS/REPAIR/REPLAN/SEARCH/FAIL_HARD.\n"
            "Search Gate opens only for LLM-routed research requests, planned external research, third-party API uncertainty, or Evaluator needs_search.\n\n"
            "[Six Layers]\n"
            f"{layers}\n\n"
            "[Hard Rules]\n"
            "Planner only plans. Search only researches. Generator only patches scoped files. Runner only executes and collects evidence. "
            "Evaluator only judges once per round. Runner script errors default to Runner/Harness infra, not Generator. "
            "Raw tool logs must be normalized into user-facing summaries; keep raw stdout/stderr and JSON in debug artifacts.\n"
        )

    @classmethod
    def _normalize_workspace_path(cls, path: str) -> Optional[str]:
        text = str(path or "").strip().replace("\\", "/")
        if not text or text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
            return None
        parts = [part for part in text.split("/") if part not in {"", "."}]
        if any(part == ".." for part in parts):
            return None
        return "/".join(parts)

    @classmethod
    def _matches_any(cls, path: str, patterns: Sequence[str]) -> bool:
        return any(cls._matches(path, pattern) for pattern in patterns)

    @staticmethod
    def _matches(path: str, pattern: str) -> bool:
        normalized_path = path.strip("/")
        normalized_pattern = str(pattern or "").strip().strip("/")
        if not normalized_pattern:
            return False
            
        if normalized_pattern.startswith("**/"):
            if fnmatch.fnmatch(normalized_path, normalized_pattern[3:]):
                return True
                
        if normalized_pattern.endswith("/**"):
            prefix = normalized_pattern[:-3].rstrip("/")
            if any(token in prefix for token in ("*", "?", "[")):
                return fnmatch.fnmatch(normalized_path, prefix) or fnmatch.fnmatch(normalized_path, f"{prefix}/*")
            return normalized_path == prefix or normalized_path.startswith(f"{prefix}/")
            
        return fnmatch.fnmatch(normalized_path, normalized_pattern)

    @staticmethod
    def _normalize_command(command: str) -> str:
        return re.sub(r"\s+", " ", str(command or "").strip())

    @staticmethod
    def _friendly_tool_title(tool: str, *, running: bool) -> str:
        mapping = {
            "bash": "正在运行命令" if running else "命令执行完成",
            "desktop-commander": "正在运行命令" if running else "命令执行完成",
            "desktop-commander.terminal": "正在运行命令" if running else "命令执行完成",
            "computer": "正在验证页面" if running else "页面验证完成",
            "computer-use": "正在验证页面" if running else "页面验证完成",
            "str_replace_editor": "正在修改文件" if running else "文件修改完成",
            "file-manager": "正在修改文件" if running else "文件修改完成",
            "filesystem": "正在修改文件" if running else "文件修改完成",
            "web_search": "正在检索资料" if running else "资料检索完成",
            "advanced_web_search": "正在检索资料" if running else "资料检索完成",
            "web-search-free": "正在检索资料" if running else "资料检索完成",
            "search": "正在检索资料" if running else "资料检索完成",
            "web-scraper-pro": "正在检索资料" if running else "资料检索完成",
            "firecrawl-scraper": "正在检索资料" if running else "资料检索完成",
            "skill-lookup": "正在检索资料" if running else "资料检索完成",
        }
        return mapping.get(tool, "正在处理" if running else "步骤已完成")

    @staticmethod
    def _humanize_error(text: str) -> str:
        if not text:
            return "执行结果没有提供可读错误，已进入调试信息。"
        if "max iterations reached" in text:
            return "验收未完成：自动化验证没有在预算内得到有效结论。"
        if "Traceback" in text or "Exception" in text:
            return "运行过程中出现异常，技术细节已放入调试区。"
        return text[:240]

    @staticmethod
    def _runner_highlights(payload: Mapping[str, Any]) -> List[str]:
        highlights: List[str] = []
        for command in payload.get("commands", []) or []:
            if not isinstance(command, Mapping):
                continue
            name = str(command.get("name") or command.get("cmd") or "command")
            status = str(command.get("status") or "").upper()
            if status == "PASSED" or command.get("passed") is True:
                state = "通过"
            elif status == "SKIPPED" or command.get("skipped") is True:
                state = "跳过"
            elif status == "TIMEOUT":
                state = "超时"
            else:
                state = "失败"
            highlights.append(f"{name}: {state}")
        for browser_test in payload.get("browser_tests", []) or []:
            if not isinstance(browser_test, Mapping):
                continue
            highlights.append(f"{browser_test.get('id', 'browser')}: {browser_test.get('status', 'UNKNOWN')}")
        return highlights[:6]

    @staticmethod
    def _friendly_next_step(next_agent: str) -> str:
        mapping = {
            "Generator": "交由 Generator 修复后重新验证",
            "Planner": "交由 Planner 调整计划后继续",
            "Search": "先补充外部资料，再继续后续阶段",
            "None": "无后续自动步骤",
        }
        return mapping.get(str(next_agent or "None"), str(next_agent or "None"))

    @staticmethod
    def _verdict_signal_text(verdict: Mapping[str, Any]) -> str:
        parts: List[str] = [
            str(verdict.get("root_cause") or ""),
            str(verdict.get("repair_instruction") or ""),
            " ".join(str(item) for item in (verdict.get("failed_criteria") or []) if item),
            " ".join(str(item) for item in (verdict.get("evidence") or []) if item),
        ]
        return " ".join(part.strip().lower() for part in parts if part).strip()

    def _should_retry_generator(self, verdict: Mapping[str, Any]) -> bool:
        result = str(verdict.get("verdict") or "").upper()
        next_agent = str(verdict.get("next_agent") or "").strip()
        if result != "FAIL_HARD":
            return False
        if next_agent == "Generator":
            return True
        signal = self._verdict_signal_text(verdict)
        recoverable_patterns = (
            "did not create any implementation files",
            "never created",
            "missing implementation file",
            "missing implementation files",
            "required file was not created",
            "required files were not created",
            "index.html game file was never created",
            "generator did not create",
            "未创建",
            "没有创建",
        )
        return any(pattern in signal for pattern in recoverable_patterns)


def should_search(
    ctx: Optional[Mapping[str, Any]] = None,
    *,
    user_request: Optional[str] = None,
    plan: Optional[Mapping[str, Any]] = None,
    run_report: Optional[Mapping[str, Any]] = None,
    eval_verdict: Optional[Mapping[str, Any]] = None,
) -> bool:
    return HarnessEngine().should_search(
        ctx,
        user_request=user_request,
        plan=plan,
        run_report=run_report,
        eval_verdict=eval_verdict,
    )
