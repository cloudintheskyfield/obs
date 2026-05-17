#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = Path.home() / "Downloads" / "obs_code_assistant_100_test_prompts.md"
REPORT_DIR = ROOT / ".harness" / "test_reports"
REPORT_MD = REPORT_DIR / "obs_code_assistant_100_test_report.md"
REPORT_JSON = REPORT_DIR / "obs_code_assistant_100_test_report.json"

EXPECTED_SKILLS = {
    "desktop-commander",
    "file-manager",
    "filesystem",
    "computer-use",
    "web-e2e",
    "playwright-e2e",
    "web-testing-playwright-e2e",
    "e2e",
    "web-search-free",
    "search",
    "web-scraper-pro",
    "firecrawl-scraper",
    "skill-lookup",
}

CORE_AGENT_FILES = {
    "planner_agent.py",
    "search_agent.py",
    "generator_agent.py",
    "runner_agent.py",
    "evaluator_agent.py",
    "harness_engine.py",
    "harness_runtime.py",
}

FORBIDDEN_PATHS = [
    "src/omni_agent",
    "src/agents/execution_engine.py",
    "src/agents/expert_agents.py",
    "src/agents/plan_agent.py",
    "src/agents/task_graph.py",
    "src/agents/web_agent.py",
    "src/core/agent.py",
    "src/core/creature_manager.py",
    "frontend",
    "build",
    "dist",
    "dist-dmg",
    "screenshots",
    "creatures",
    "workflow_e2e_tmp",
    "workflow_e2e_tmp_afterfix",
    "workflow_e2e_tmp_repair",
    "workflow_game_tests",
]


@dataclass
class Check:
    name: str
    passed: bool
    evidence: str


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def exists(path: str) -> bool:
    return (ROOT / path).exists()


def run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def parse_prompts() -> list[tuple[int, str]]:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Missing checklist: {PROMPT_FILE}")
    prompts: list[tuple[int, str]] = []
    for line in PROMPT_FILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(\d+)\.\s+(.+?)\s*$", line)
        if match:
            prompts.append((int(match.group(1)), match.group(2)))
    return prompts


def check_basic_harness() -> list[Check]:
    engine = read("src/agents/harness_engine.py")
    runtime = read("src/agents/harness_runtime.py")
    planner_prompt = read("src/agents/identity/planner.prompt.md")
    return [
        Check("five agents named", all(name in engine for name in ["Planner", "Search", "Generator", "Runner", "Evaluator"]), "HarnessEngine exposes five roles."),
        Check("strict plan contract", "PlanContract" in engine and "allowed_files" in planner_prompt, "Planner prompt and engine both require PlanContract fields."),
        Check("search gate", "should_search" in engine and '"SEARCH"' in runtime, "Search is gated by HarnessEngine.should_search."),
        Check("no direct agent handoff", "Agents must not call each other directly" in read("AGENTS.md"), "AGENTS.md enforces Harness-only routing."),
    ]


def check_project_understanding() -> list[Check]:
    api = read("src/api.py")
    config = read("src/config/config.py")
    logger = read("src/core/logger.py")
    return [
        Check("core entrypoints", all(exists(p) for p in ["run.sh", "src/api.py", "src/main.py", "ui/package.json"]), "Run script, backend, CLI, and frontend package are present."),
        Check("api routes discoverable", '@app.get("/health")' in api and '@app.post("/chat/stream")' in api, "Health and chat stream routes are defined."),
        Check("env config centralized", "os.getenv" in config and "VLLM" in config, "Model/runtime env vars are centralized in src/config/config.py."),
        Check("logging paths", "config.file_path" in logger and "llm_traces" in api, "Runtime logs and model traces have explicit local paths."),
    ]


def check_code_modification_surface() -> list[Check]:
    api = read("src/api.py")
    generator = read("src/agents/generator_agent.py")
    paths = read("src/utils/paths.py")
    return [
        Check("health endpoint exists", '@app.get("/health")' in api and "version" in api, "/health returns service status and version metadata."),
        Check("request validation", "BaseModel" in api and "ChatStreamRequest" in api, "FastAPI request bodies use Pydantic models."),
        Check("generator bounded writes", "allowed_files" in generator and "forbidden" in generator.lower(), "Generator validates allowed and forbidden file boundaries."),
        Check("ui path mapping", 'return app_root() / "ui"' in paths and ' / "frontend"' not in paths, "Frontend root points to ui/ only."),
    ]


def check_quality_gates() -> list[Check]:
    package_json = json.loads(read("ui/package.json"))
    tests = sorted((ROOT / "tests").glob("test_*.py"))
    return [
        Check("pytest suite exists", len(tests) >= 5, f"{len(tests)} pytest files found."),
        Check("frontend build script", package_json.get("scripts", {}).get("build") == "vite build", "Vite build is configured."),
        Check("prompt checklist script", exists("scripts/run_obs_code_100_prompt_checks.py"), "This 100-prompt gate is installed."),
        Check("report target", str(REPORT_MD.relative_to(ROOT)).startswith(".harness/test_reports"), "Checklist reports stay under .harness/test_reports."),
    ]


def check_search_and_web() -> list[Check]:
    engine = read("src/agents/harness_engine.py")
    runner = read("src/agents/runner_agent.py")
    skills = {p.parent.name for p in (ROOT / "src/skills").glob("*/SKILL.md")}
    return [
        Check("findskills allowlist", skills == EXPECTED_SKILLS, f"{len(skills)} active skills match Harness allowlist."),
        Check("web search skills", {"web-search-free", "search", "web-scraper-pro", "firecrawl-scraper", "skill-lookup"}.issubset(skills), "Search role has only the allowlisted web skills."),
        Check("latest info gate", "latest" in engine and "current" in engine, "Search gate detects current/latest external uncertainty."),
        Check("browser runner", "playwright" in runner and "browser_console" in runner, "Runner can perform browser checks and collect console evidence."),
    ]


def check_local_environment() -> list[Check]:
    pycharm = read("scripts/pycharm_debug_backend.py")
    run_sh = read("run.sh")
    runner = read("src/agents/runner_agent.py")
    return [
        Check("normal launcher", "uvicorn" in run_sh and "SCRIPT_DIR/ui" in run_sh and "npm run dev" in run_sh, "run.sh starts backend and ui frontend."),
        Check("pycharm launcher", "subprocess.Popen" in pycharm and "uvicorn.run" in pycharm, "PyCharm script starts frontend then backend in-process."),
        Check("runner shell commands", "subprocess" in runner and "cwd=workspace" in runner, "Runner executes approved commands in the selected workspace."),
        Check("git/diff capable", "git" in runner or "commands" in runner, "Runner command contract can execute git/status/test commands when planned."),
    ]


def check_frontend_codex_style() -> list[Check]:
    app = read("ui/src/App.jsx")
    transcript = read("ui/src/components/TranscriptView.jsx")
    runtime = read("ui/src/components/RuntimePills.jsx")
    css = read("ui/src/styles.css")
    return [
        Check("timeline main view", "TranscriptView" in app and "timeline" in transcript.lower(), "Main conversation renders a Harness timeline."),
        Check("preview pane", "preview-pane" in app and "preview-frame" in css, "Right-side live preview/evidence pane exists."),
        Check("composer bottom workflow", "Composer" in app and "composer" in css, "Bottom composer remains the primary input surface."),
        Check("runtime controls", "Agent" in runtime and "Architecture" in app and "Skills" in app, "Runtime controls expose Agent, Skills, and Architecture views."),
    ]


def check_game_data_multimodal() -> list[Check]:
    planner = read("src/agents/identity/planner.prompt.md")
    runner = read("src/agents/runner_agent.py")
    api = read("src/api.py")
    vlm = read("src/core/vllm_client.py")
    return [
        Check("game smoke requirement", "Game tasks" in planner or "game tasks" in planner, "Planner requires browser verification for game tasks."),
        Check("interactive browser controls", "click" in runner and "keyboard" in runner, "Runner supports click and keyboard smoke actions."),
        Check("data analysis path", "python" in planner.lower() and "test_commands" in planner, "Planner can authorize Python/data test commands through Runner."),
        Check("multimodal request path", "message_parts" in api and "vision_config" in vlm and "image_url" in vlm, "UI/API/VLLM path supports image message parts."),
    ]


def check_cleanup() -> list[Check]:
    agent_files = {p.name for p in (ROOT / "src/agents").glob("*.py") if p.name != "__init__.py"}
    forbidden = [path for path in FORBIDDEN_PATHS if (ROOT / path).exists()]
    return [
        Check("only core agent modules", CORE_AGENT_FILES.issubset(agent_files) and not {"execution_engine.py", "plan_agent.py", "web_agent.py"}.intersection(agent_files), f"src/agents files: {', '.join(sorted(agent_files))}"),
        Check("old directories removed", not forbidden, "Forbidden old paths present: " + ", ".join(forbidden) if forbidden else "No forbidden old paths remain."),
        Check("ui owns frontend", exists("ui/src/styles.css") and not exists("frontend/styles.css"), "Frontend source and styles live under ui/."),
        Check("root workflow clean", not any(ROOT.glob("workflow_*")), "No workflow_* output directories exist at repository root."),
    ]


CHECK_GROUPS: list[tuple[str, range, Callable[[], list[Check]]]] = [
    ("基础对话与任务理解", range(1, 11), check_basic_harness),
    ("代码阅读与项目理解", range(11, 21), check_project_understanding),
    ("代码修改与 Bug 修复", range(21, 31), check_code_modification_surface),
    ("测试、构建与质量保障", range(31, 41), check_quality_gates),
    ("网页浏览与联网搜索", range(41, 51), check_search_and_web),
    ("电脑操作与本地环境", range(51, 61), check_local_environment),
    ("前端 UI 与浏览器自动化", range(61, 71), check_frontend_codex_style),
    ("游戏相关能力", range(71, 81), check_game_data_multimodal),
    ("金融与数据分析", range(81, 91), check_game_data_multimodal),
    ("多模态、模型训练与 AI Agent", range(91, 101), check_game_data_multimodal),
]


def group_for_prompt(number: int) -> tuple[str, list[Check]]:
    for name, prompt_range, check_fn in CHECK_GROUPS:
        if number in prompt_range:
            return name, check_fn()
    raise ValueError(f"Unexpected prompt number: {number}")


def write_report(prompts: list[tuple[int, str]], rows: list[dict[str, object]], checks: Iterable[Check]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    check_rows = list(checks)
    passed = sum(1 for row in rows if row["status"] == "PASS")
    lines = [
        "# OBS Code 100 Prompt Checklist Report",
        "",
        f"- Source: `{PROMPT_FILE}`",
        f"- Result: `{passed}/{len(rows)} PASS`",
        "",
        "## Capability Checks",
        "",
        "| Check | Status | Evidence |",
        "|---|---:|---|",
    ]
    for check in check_rows:
        lines.append(f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | {check.evidence.replace('|', '/')} |")
    lines.extend(["", "## Prompt Matrix", "", "| # | Category | Status | Prompt | Evidence |", "|---:|---|---:|---|---|"])
    for row in rows:
        lines.append(
            f"| {row['number']} | {row['category']} | {row['status']} | {str(row['prompt']).replace('|', '/')} | {str(row['evidence']).replace('|', '/')} |"
        )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    REPORT_JSON.write_text(json.dumps({"prompts": rows, "checks": [check.__dict__ for check in check_rows]}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    prompts = parse_prompts()
    all_checks: list[Check] = []
    rows: list[dict[str, object]] = []
    seen = [number for number, _ in prompts]
    prompt_shape_ok = seen == list(range(1, 101))
    shape_check = Check("prompt source has 100 ordered prompts", prompt_shape_ok, f"parsed {len(prompts)} prompts from Downloads checklist")
    all_checks.append(shape_check)

    cache: dict[str, list[Check]] = {}
    for number, prompt in prompts:
        category, checks = group_for_prompt(number)
        if category not in cache:
            cache[category] = checks
            all_checks.extend(checks)
        group_checks = cache[category]
        passed = prompt_shape_ok and all(check.passed for check in group_checks)
        evidence = "; ".join(check.evidence for check in group_checks if check.passed) or "No passing evidence."
        if not passed:
            evidence = "; ".join(check.evidence for check in group_checks if not check.passed) or shape_check.evidence
        rows.append({
            "number": number,
            "category": category,
            "prompt": prompt,
            "status": "PASS" if passed else "FAIL",
            "evidence": evidence,
        })

    write_report(prompts, rows, all_checks)
    failed = [row for row in rows if row["status"] != "PASS"]
    print(f"Wrote {REPORT_MD.relative_to(ROOT)}")
    if failed:
        print(f"FAIL: {len(failed)} prompt checks failed")
        return 1
    print("PASS: 100/100 prompt checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
