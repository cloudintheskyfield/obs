from __future__ import annotations

import json
import re
import shlex
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .harness_engine import HarnessEngine

_PROTECTED_PATHS = [
    ".env",
    ".env.*",
    ".git/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".harness/**",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "workflow_*/**",
    "workflow_game_tests/**",
]

_DEFAULT_ACCEPTANCE_CRITERIA = [
    "产物能在当前项目中成功加载或构建",
    "核心用户路径可以完成一次主流程",
    "无阻塞性的控制台或运行时致命错误",
    "实现范围与用户请求保持一致",
]

PLANNER_SYSTEM_PROMPT = (
    "You are Planner Agent in a five-agent Harness workflow: Planner, Search, Generator, Runner, Evaluator. "
    "Your only job is to convert the user request, project summary, previous failures, and optional search findings into one strict JSON PlanContract object. "
    "All outputs go to the Harness. You do not call other agents directly.\n\n"

    "You do not have tools. "
    "You must not inspect files directly, run commands, edit code, open browsers, perform web searches, or verify results. "
    "Do not claim that you inspected files, executed commands, opened a browser, or confirmed that the task works. "
    "If information is missing, list the needed files in required_files_to_inspect instead of guessing their contents.\n\n"

    "Return exactly one JSON object. "
    "Do not output markdown. "
    "Do not wrap the JSON in code fences. "
    "Do not output explanations before or after the JSON object.\n\n"

    "The JSON object must contain exactly these top-level fields:\n"
    "schema_version, task_id, goal, assumptions, implementation_strategy, allowed_files, forbidden_files, "
    "required_files_to_inspect, implementation_steps, test_commands, dev_server, smoke_tests, "
    "acceptance_criteria, repair_policy, rollback_policy, external_research, package_json_policy, risks.\n\n"

    "Stable field type rules:\n"
    "- schema_version must be a string.\n"
    "- task_id must be a string.\n"
    "- goal must be a string.\n"
    "- assumptions must be an array of strings.\n"
    "- implementation_strategy must be a string.\n"
    "- allowed_files must be an array of strings.\n"
    "- forbidden_files must be an array of strings.\n"
    "- required_files_to_inspect must be an array of strings.\n"
    "- implementation_steps must be an array of objects.\n"
    "- test_commands must be an array of objects.\n"
    "- dev_server must be an object.\n"
    "- smoke_tests must be an array of objects.\n"
    "- acceptance_criteria must be an array of strings.\n"
    "- repair_policy must be an object.\n"
    "- rollback_policy must be an object.\n"
    "- external_research must be an object.\n"
    "- package_json_policy must be an object.\n"
    "- risks must be an array of strings.\n\n"

    "implementation_steps item schema:\n"
    "- Each implementation_steps item must include id, title, description, and expected_output.\n"
    "- id must be a short stable string such as S1, S2, S3.\n"
    "- Each step must be small, ordered, and verifiable.\n\n"

    "test_commands item schema:\n"
    "- Each test_commands item must include name, cmd, timeout_sec, and required.\n"
    "- name must be a short string such as build, lint, test, typecheck.\n"
    "- cmd must be an executable shell command only, such as npm run build, npm run lint, pytest, node ..., or python -c ... .\n"
    "- timeout_sec must be a positive integer.\n"
    "- required must be a boolean.\n"
    "- Do not put browser instructions, page-load checks, clicking steps, or prose in test_commands.\n\n"

    "dev_server object schema:\n"
    "- dev_server must include enabled, start_cmd, url, ready_patterns, and timeout_sec.\n"
    "- enabled must be true only when a browser preview or smoke test is needed.\n"
    "- start_cmd must be an executable command string when enabled is true, otherwise an empty string.\n"
    "- url must be the expected local URL when enabled is true, otherwise an empty string.\n"
    "- ready_patterns must be an array of strings.\n"
    "- timeout_sec must be a positive integer.\n\n"

    "smoke_tests item schema:\n"
    "- Each smoke_tests item must include id, type, action, expect, timeout_sec, and required.\n"
    "- Browser/page-load/click/keyboard checks must go in smoke_tests, not in test_commands.\n"
    "- If action is goto, include target.\n"
    "- If action is click, include selector_candidates.\n"
    "- If action is keyboard, include key.\n"
    "- expect must be an object describing observable checks such as page_loaded, text_contains_any, no_fatal_console_error, visual_change.\n"
    "- timeout_sec must be a positive integer.\n"
    "- required must be a boolean.\n\n"

    "File safety rules:\n"
    "- Keep allowed_files as narrow as possible.\n"
    "- Always protect .env, .env.*, .git/**, node_modules/**, dist/**, build/**, .harness/**, logs/**, screenshots/**, root workflow_* test directories, and lock files unless explicitly allowed.\n"
    "- Lock files include package-lock.json, pnpm-lock.yaml, yarn.lock, poetry.lock, Pipfile.lock, Cargo.lock, go.sum.\n"
    "- forbidden_files has priority over allowed_files.\n"
    "- Do not allow editing files outside the workspace.\n"
    "- Do not allow writing to absolute paths.\n"
    "- Do not allow path traversal such as ../ .\n\n"

    "Planning rules:\n"
    "- Prefer a minimal viable implementation.\n"
    "- Do not plan unnecessary features, new frameworks, databases, authentication, payments, deployment, or complex infrastructure unless explicitly requested.\n"
    "- Do not change the user's goal.\n"
    "- Do not over-plan. Keep implementation_steps focused and practical.\n"
    "- Do not claim the task is completed or verified. Only define how Generator and Runner should implement and verify it.\n"
    "- For web, UI, frontend, or game requests, include build checks and browser smoke tests when the project supports them.\n"
    "- For backend or Python requests, include appropriate tests such as pytest, python -m pytest, python -m compileall, or a minimal smoke command when available.\n\n"

    "package_json_policy rules:\n"
    "- package_json_policy must include allow_modify, allow_add_scripts, allow_add_dependencies, and requires_approval.\n"
    "- package_json_policy.allow_modify must default to false unless the user request or project summary clearly requires changing package.json.\n"
    "- package_json_policy.allow_add_scripts must default to false unless needed to run existing project workflows.\n"
    "- package_json_policy.allow_add_dependencies must default to false.\n"
    "- If new dependencies are necessary, set allow_add_dependencies = true and requires_approval = true.\n"
    "- Prefer using existing dependencies and existing scripts.\n\n"

    "external_research rules:\n"
    "- external_research must include required, reason, queries, allowed_domains, max_results, max_pages_to_scrape, freshness, and search_agent_required.\n"
    "- external_research.required must default to false.\n"
    "- Set external_research.required = true only when current external facts, third-party API docs, referenced URLs, version-sensitive documentation, or unknown external behavior are necessary.\n"
    "- Do not request external research for ordinary local coding, UI changes, simple games, basic bug fixes, or errors that can be solved from local build/test output.\n"
    "- If external_research.required is true, provide specific queries.\n"
    "- If possible, restrict allowed_domains to official documentation or authoritative sources.\n"
    "- max_results must be <= 5.\n"
    "- max_pages_to_scrape must be <= 3.\n"
    "- freshness must be one of: stable, recent, latest.\n\n"

    "repair_policy rules:\n"
    "- repair_policy must include max_repair_rounds, repair_scope, do_not_rewrite_whole_project, and if_same_error_repeats.\n"
    "- max_repair_rounds should usually be 3.\n"
    "- repair_scope should usually be minimal_patch.\n"
    "- do_not_rewrite_whole_project should usually be true.\n"
    "- if_same_error_repeats should usually be REPLAN.\n\n"

    "rollback_policy rules:\n"
    "- rollback_policy must include snapshot_before_patch, rollback_on_invalid_patch, and preserve_harness_artifacts.\n"
    "- snapshot_before_patch should usually be true.\n"
    "- rollback_on_invalid_patch should usually be true.\n"
    "- preserve_harness_artifacts should usually be true.\n\n"

    "Default protected forbidden_files should include at least:\n"
    "[\".env\", \".env.*\", \".git/**\", \"node_modules/**\", \"dist/**\", \"build/**\", \".harness/**\", \"logs/**\", \"screenshots/**\", \"workflow_*/**\", \"workflow_game_tests/**\", "
    "\"package-lock.json\", \"pnpm-lock.yaml\", \"yarn.lock\", \"poetry.lock\", \"Pipfile.lock\", \"Cargo.lock\", \"go.sum\"].\n\n"

    "Return only the JSON PlanContract object."
)

_EXECUTABLE_COMMANDS = {
    "npm",
    "pnpm",
    "yarn",
    "node",
    "npx",
    "python",
    "python3",
    "pytest",
    "bash",
    "sh",
    "uv",
    "make",
    "go",
    "cargo",
}

_BROWSER_DESCRIPTION_RE = re.compile(
    r"(浏览器|打开.*\.html|直接打开|页面打开|page\s*load|browser|visit|open\s+.*\.html)",
    re.IGNORECASE,
)


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_steps(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: List[Dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, Mapping):
            title = str(item.get("title") or item.get("label") or item.get("step") or item.get("description") or "").strip()
            description = str(item.get("description") or title).strip()
            expected_output = str(item.get("expected_output") or "").strip()
            step_id = str(item.get("id") or f"S{index}").strip()
        else:
            title = str(item).strip()
            description = title
            expected_output = ""
            step_id = f"S{index}"
        if title:
            items.append(
                {
                    "id": step_id,
                    "title": title,
                    "description": description,
                    "expected_output": expected_output,
                }
            )
    return items


def _is_executable_shell_command(cmd: str) -> bool:
    text = (cmd or "").strip()
    if not text:
        return False
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    if not parts:
        return False
    executable = parts[0]
    while "=" in executable and not executable.startswith(("./", "../")) and len(parts) > 1:
        parts = parts[1:]
        executable = parts[0]
    executable_name = executable.rsplit("/", 1)[-1]
    if executable.startswith("./") or executable.startswith("../"):
        return True
    if executable_name in _EXECUTABLE_COMMANDS:
        return True
    if _BROWSER_DESCRIPTION_RE.search(text):
        return False
    return False


def _normalize_command_specs(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    commands: List[Dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, Mapping):
            cmd = str(item.get("cmd") or item.get("command") or "").strip()
            if not cmd or not _is_executable_shell_command(cmd):
                continue
            name = str(item.get("name") or f"cmd_{index}").strip() or f"cmd_{index}"
            timeout_sec = int(item.get("timeout_sec", 120) or 120)
            required = bool(item.get("required", index == 1))
        else:
            cmd = str(item).strip()
            if not cmd or not _is_executable_shell_command(cmd):
                continue
            parts = cmd.split()
            name = parts[2] if len(parts) >= 3 and parts[0] in {"npm", "pnpm", "yarn"} and parts[1] == "run" else parts[0]
            timeout_sec = 120
            required = index == 1
        commands.append(
            {
                "name": name,
                "cmd": cmd,
                "timeout_sec": timeout_sec,
                "required": required,
            }
        )
    return commands


def _browser_descriptions_from_commands(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    descriptions: List[str] = []
    for item in value:
        cmd = ""
        if isinstance(item, Mapping):
            cmd = str(item.get("cmd") or item.get("command") or item.get("description") or "").strip()
        else:
            cmd = str(item).strip()
        if cmd and not _is_executable_shell_command(cmd) and _BROWSER_DESCRIPTION_RE.search(cmd):
            descriptions.append(cmd)
    return descriptions


def _normalize_smoke_tests(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    tests: List[Dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, Mapping):
            test = dict(item)
            test.setdefault("id", f"smoke_{index}")
            test.setdefault("type", "browser")
            test.setdefault("timeout_sec", 15)
            test.setdefault("required", True)
            tests.append(test)
            continue
        title = str(item).strip()
        if title:
            tests.append(
                {
                    "id": f"smoke_{index}",
                    "type": "browser",
                    "action": "goto",
                    "target": "",
                    "expect": {"note": title},
                    "timeout_sec": 15,
                    "required": True,
                }
            )
    return tests


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


def _default_allowed_files(existing_files: Optional[List[str]]) -> List[str]:
    files = existing_files or []
    candidates: List[str] = []
    if any(path.startswith("src/") for path in files):
        candidates.append("src/**")
    if any(path.startswith("app/") for path in files):
        candidates.append("app/**")
    if any(path.startswith("components/") for path in files):
        candidates.append("components/**")
    if any(path.startswith("public/") for path in files):
        candidates.append("public/**")
    if "index.html" in files:
        candidates.append("index.html")
    if not candidates:
        candidates = ["src/**", "app/**", "components/**", "public/**", "index.html"]
    seen = set()
    result: List[str] = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _default_test_commands(existing_files: Optional[List[str]]) -> List[Dict[str, Any]]:
    files = existing_files or []
    if "package.json" in files:
        return [
            {"name": "build", "cmd": "npm run build", "timeout_sec": 120, "required": True},
            {"name": "lint", "cmd": "npm run lint", "timeout_sec": 60, "required": False},
        ]
    if any(path.endswith("pyproject.toml") for path in files):
        return [
            {"name": "pytest", "cmd": "pytest", "timeout_sec": 120, "required": True},
        ]
    return []


def _concrete_allowed_files(allowed_files: List[str]) -> List[str]:
    concrete: List[str] = []
    for item in allowed_files:
        path = str(item or "").strip().replace("\\", "/")
        if not path or any(token in path for token in ("*", "?", "[")):
            continue
        if path.endswith("/"):
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
    return result[:6]


def _default_file_output_commands(allowed_files: List[str]) -> List[Dict[str, Any]]:
    concrete_files = _concrete_allowed_files(allowed_files)
    if not concrete_files:
        return []
    files_literal = repr(concrete_files)
    cmd = (
        "python -c \"from pathlib import Path; "
        f"files={files_literal}; "
        "missing=[p for p in files if not Path(p).is_file() or Path(p).stat().st_size == 0]; "
        "assert not missing, 'missing or empty generated files: '+', '.join(missing); "
        "print('generated files ok: '+', '.join(files))\""
    )
    return [
        {
            "name": "verify_generated_files",
            "cmd": cmd,
            "timeout_sec": 30,
            "required": True,
        }
    ]


def _default_smoke_tests(existing_files: Optional[List[str]]) -> List[Dict[str, Any]]:
    files = existing_files or []
    if "index.html" in files or any(path.startswith("src/") for path in files):
        return [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "http://localhost:5173",
                "expect": {
                    "page_loaded": True,
                    "no_fatal_console_error": True,
                },
                "timeout_sec": 15,
                "required": True,
            }
        ]
    return []


def _browser_smoke_tests_from_descriptions(descriptions: List[str], allowed_files: List[str]) -> List[Dict[str, Any]]:
    if not descriptions:
        return []
    target = "index.html" if "index.html" in allowed_files else ""
    tests: List[Dict[str, Any]] = []
    for index, description in enumerate(descriptions, start=1):
        tests.append(
            {
                "id": f"browser_from_command_{index}",
                "type": "browser",
                "action": "goto",
                "target": target,
                "expect": {"note": description, "page_loaded": True},
                "timeout_sec": 15,
                "required": True,
            }
        )
    return tests


def _default_dev_server(existing_files: Optional[List[str]]) -> Dict[str, Any]:
    files = existing_files or []
    if "package.json" in files:
        return {
            "enabled": True,
            "start_cmd": "npm run dev -- --host 0.0.0.0",
            "url": "http://localhost:5173",
            "ready_patterns": ["Local:", "ready in", "localhost"],
            "timeout_sec": 60,
        }
    return {
        "enabled": False,
        "start_cmd": "",
        "url": "",
        "ready_patterns": [],
        "timeout_sec": 60,
    }


def _short_join(items: List[str], *, fallback: str, limit: int = 3) -> str:
    selected = [item for item in items if item][:limit]
    if not selected:
        return fallback
    suffix = "" if len(items) <= limit else f" 等 {len(items)} 项"
    return "、".join(selected) + suffix


def _derive_implementation_steps(
    user_message: str,
    existing_files: Optional[List[str]],
    allowed_files: List[str],
    required_files_to_inspect: List[str],
    test_commands: List[Dict[str, Any]],
    smoke_tests: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    request = (user_message or "当前请求").strip()
    existing = existing_files or []
    concrete_outputs = _concrete_allowed_files(allowed_files)
    inspect_targets = required_files_to_inspect or [path for path in existing if path in concrete_outputs][:3]
    editable_scope = _short_join(allowed_files, fallback="PlanContract.allowed_files")
    output_scope = _short_join(concrete_outputs or allowed_files, fallback=editable_scope)
    command_names = [str(item.get("name") or item.get("cmd") or "").strip() for item in test_commands]
    smoke_names = [str(item.get("id") or item.get("action") or "").strip() for item in smoke_tests]
    verification_scope = _short_join([*command_names, *smoke_names], fallback="Runner 契约验证")

    steps: List[Dict[str, Any]] = []
    if inspect_targets:
        target_text = _short_join(inspect_targets, fallback="required_files_to_inspect")
        steps.append(
            {
                "id": f"S{len(steps) + 1}",
                "title": f"读取 {target_text}",
                "description": f"Generator 先读取 {target_text}，只基于实际文件结构实现“{request}”。",
                "expected_output": "获得可编辑入口、依赖关系和现有约定。",
            }
        )

    steps.append(
        {
            "id": f"S{len(steps) + 1}",
            "title": f"在 {editable_scope} 内实施",
            "description": f"Generator 仅修改允许范围，完成“{request}”的最小可运行实现。",
            "expected_output": f"{output_scope} 包含本轮实际代码改动。",
        }
    )

    if smoke_tests:
        steps.append(
            {
                "id": f"S{len(steps) + 1}",
                "title": "补齐可观察交互",
                "description": "确保 smoke_tests 中的页面加载、交互或可见状态具备稳定可观察结果。",
                "expected_output": "Runner 能从页面或输出中采集到明确证据。",
            }
        )

    steps.append(
        {
            "id": f"S{len(steps) + 1}",
            "title": f"准备 {verification_scope}",
            "description": "Runner 只执行 PlanContract 中的可执行命令和浏览器 smoke tests。",
            "expected_output": "验证项能证明核心产物已生成且主路径可运行。",
        }
    )
    return steps


def _default_plan_contract(user_message: str, existing_files: Optional[List[str]]) -> Dict[str, Any]:
    allowed_files = _default_allowed_files(existing_files)
    required_files_to_inspect = list((existing_files or [])[:8])
    test_commands = _default_test_commands(existing_files)
    smoke_tests = _default_smoke_tests(existing_files)
    return {
        "schema_version": "1.0",
        "task_id": "task_plan_001",
        "goal": (user_message or "完成当前用户请求").strip(),
        "assumptions": [],
        "implementation_strategy": "先确认项目入口和受限改动范围，再实现主功能并执行最小必要验证。",
        "allowed_files": allowed_files,
        "forbidden_files": list(_PROTECTED_PATHS),
        "required_files_to_inspect": required_files_to_inspect,
        "implementation_steps": _derive_implementation_steps(
            user_message,
            existing_files,
            allowed_files,
            required_files_to_inspect,
            test_commands,
            smoke_tests,
        ),
        "test_commands": test_commands,
        "dev_server": _default_dev_server(existing_files),
        "smoke_tests": smoke_tests,
        "acceptance_criteria": list(_DEFAULT_ACCEPTANCE_CRITERIA),
        "repair_policy": {
            "max_repair_rounds": 3,
            "repair_scope": "minimal_patch",
            "do_not_rewrite_whole_project": True,
            "if_same_error_repeats": "REPLAN",
        },
        "rollback_policy": {
            "snapshot_before_patch": True,
            "rollback_on_invalid_patch": True,
            "preserve_harness_artifacts": True,
        },
        "external_research": {
            "required": False,
            "reason": "",
            "queries": [],
            "allowed_domains": [],
            "max_results": 5,
            "max_pages_to_scrape": 3,
            "freshness": "stable",
            "search_agent_required": False,
        },
        "package_json_policy": {
            "allow_modify": False,
            "allow_add_scripts": False,
            "allow_add_dependencies": False,
            "requires_approval": True,
        },
        "risks": [],
    }


def _normalize_plan_contract(raw_obj: Optional[Dict[str, Any]], user_message: str, existing_files: Optional[List[str]]) -> Dict[str, Any]:
    base = _default_plan_contract(user_message, existing_files)
    source: Dict[str, Any] = dict(raw_obj or {})

    contract = dict(base)
    contract["schema_version"] = str(source.get("schema_version") or "1.0")
    contract["task_id"] = str(source.get("task_id") or base["task_id"])
    contract["goal"] = str(source.get("goal") or base["goal"])
    contract["assumptions"] = _normalize_string_list(source.get("assumptions"))
    contract["implementation_strategy"] = str(source.get("implementation_strategy") or base["implementation_strategy"])
    contract["allowed_files"] = _normalize_string_list(source.get("allowed_files")) or base["allowed_files"]
    contract["forbidden_files"] = _normalize_string_list(source.get("forbidden_files")) or base["forbidden_files"]
    contract["required_files_to_inspect"] = _normalize_string_list(source.get("required_files_to_inspect")) or base["required_files_to_inspect"]
    contract["test_commands"] = _normalize_command_specs(source.get("test_commands")) or base["test_commands"]
    output_commands = _default_file_output_commands(contract["allowed_files"])
    if output_commands:
        existing_cmds = {str(item.get("cmd") or "") for item in contract["test_commands"]}
        contract["test_commands"] = [
            *[item for item in output_commands if str(item.get("cmd") or "") not in existing_cmds],
            *contract["test_commands"],
        ]

    dev_server_raw = source.get("dev_server")
    dev_server: Dict[str, Any] = dict(dev_server_raw) if isinstance(dev_server_raw, Mapping) else {}
    contract["dev_server"] = {
        "enabled": bool(dev_server.get("enabled", base["dev_server"].get("enabled"))),
        "start_cmd": str(dev_server.get("start_cmd") or base["dev_server"].get("start_cmd") or ""),
        "url": str(dev_server.get("url") or base["dev_server"].get("url") or ""),
        "ready_patterns": _normalize_string_list(dev_server.get("ready_patterns")) or base["dev_server"].get("ready_patterns", []),
        "timeout_sec": int(dev_server.get("timeout_sec", base["dev_server"].get("timeout_sec", 60)) or 60),
    }

    browser_descriptions = _browser_descriptions_from_commands(source.get("test_commands"))
    converted_smoke_tests = _browser_smoke_tests_from_descriptions(browser_descriptions, contract["allowed_files"])
    contract["smoke_tests"] = [
        *(_normalize_smoke_tests(source.get("smoke_tests")) or base["smoke_tests"]),
        *converted_smoke_tests,
    ]
    contract["implementation_steps"] = _normalize_steps(source.get("implementation_steps")) or _derive_implementation_steps(
        contract["goal"],
        existing_files,
        contract["allowed_files"],
        contract["required_files_to_inspect"],
        contract["test_commands"],
        contract["smoke_tests"],
    )
    contract["acceptance_criteria"] = _normalize_string_list(source.get("acceptance_criteria")) or base["acceptance_criteria"]

    repair_policy_raw = source.get("repair_policy")
    repair_policy: Dict[str, Any] = dict(repair_policy_raw) if isinstance(repair_policy_raw, Mapping) else {}
    contract["repair_policy"] = {
        "max_repair_rounds": int(repair_policy.get("max_repair_rounds", base["repair_policy"]["max_repair_rounds"])),
        "repair_scope": str(repair_policy.get("repair_scope") or base["repair_policy"]["repair_scope"]),
        "do_not_rewrite_whole_project": bool(repair_policy.get("do_not_rewrite_whole_project", base["repair_policy"]["do_not_rewrite_whole_project"])),
        "if_same_error_repeats": str(repair_policy.get("if_same_error_repeats") or base["repair_policy"]["if_same_error_repeats"]),
    }

    rollback_policy_raw = source.get("rollback_policy")
    rollback_policy: Dict[str, Any] = dict(rollback_policy_raw) if isinstance(rollback_policy_raw, Mapping) else {}
    contract["rollback_policy"] = {
        "snapshot_before_patch": bool(rollback_policy.get("snapshot_before_patch", base["rollback_policy"]["snapshot_before_patch"])),
        "rollback_on_invalid_patch": bool(rollback_policy.get("rollback_on_invalid_patch", base["rollback_policy"]["rollback_on_invalid_patch"])),
        "preserve_harness_artifacts": bool(rollback_policy.get("preserve_harness_artifacts", base["rollback_policy"]["preserve_harness_artifacts"])),
    }

    external_research_raw = source.get("external_research")
    external_research: Dict[str, Any] = dict(external_research_raw) if isinstance(external_research_raw, Mapping) else {}
    contract["external_research"] = {
        "required": bool(external_research.get("required", False)),
        "reason": str(external_research.get("reason") or ""),
        "queries": _normalize_string_list(external_research.get("queries")),
        "allowed_domains": _normalize_string_list(external_research.get("allowed_domains")),
        "max_results": int(external_research.get("max_results", 5) or 5),
        "max_pages_to_scrape": int(external_research.get("max_pages_to_scrape", 3) or 3),
        "freshness": str(external_research.get("freshness") or "stable"),
        "search_agent_required": bool(external_research.get("search_agent_required", False)),
    }

    package_json_policy_raw = source.get("package_json_policy")
    package_json_policy: Dict[str, Any] = dict(package_json_policy_raw) if isinstance(package_json_policy_raw, Mapping) else {}
    contract["package_json_policy"] = {
        "allow_modify": bool(package_json_policy.get("allow_modify", False)),
        "allow_add_scripts": bool(package_json_policy.get("allow_add_scripts", False)),
        "allow_add_dependencies": bool(package_json_policy.get("allow_add_dependencies", False)),
        "requires_approval": bool(package_json_policy.get("requires_approval", True)),
    }
    contract["risks"] = _normalize_string_list(source.get("risks"))
    return contract


def _plan_contract_to_tasks(plan_contract: Mapping[str, Any]) -> List[Dict[str, str]]:
    steps = _normalize_steps(plan_contract.get("implementation_steps"))
    criteria = _normalize_string_list(plan_contract.get("acceptance_criteria"))
    tasks: List[Dict[str, str]] = []
    for idx, step in enumerate(steps):
        success_criteria = criteria[idx] if idx < len(criteria) else "完成该实施步骤并保持契约范围一致"
        label = str(step.get("title") or step.get("description") or f"步骤 {idx + 1}")
        tasks.append(
            {
                "id": str(step.get("id") or f"task_{idx}"),
                "label": label[:40],
                "success_criteria": success_criteria,
            }
        )
    return tasks


class PlannerAgent:
    def __init__(self, vllm_client: Any) -> None:
        self.vllm_client = vllm_client
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt("Planner", PLANNER_SYSTEM_PROMPT)
        self.last_plan_contract: Dict[str, Any] = {}
        self.last_tasks: List[Dict[str, Any]] = []
        self.last_thinking: str = ""

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def plan(
        self,
        session_id: str,
        user_message: str,
        *,
        model: Optional[str] = None,
        existing_files: Optional[List[str]] = None,
        project_summary: Optional[Mapping[str, Any]] = None,
        previous_failures: Optional[List[str]] = None,
        constraints: Optional[Mapping[str, Any]] = None,
        search_reports: Optional[List[Mapping[str, Any]]] = None,
    ) -> AsyncGenerator[str, None]:
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Planner",
                "status": "running",
                "title": "生成 PlanContract",
                "detail": "整理目标、范围、验证方式与约束...",
                "session_id": session_id,
            }
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": self._build_user_prompt(
                    user_message,
                    existing_files,
                    project_summary=project_summary,
                    previous_failures=previous_failures,
                    constraints=constraints,
                    search_reports=search_reports,
                ),
            },
        ]

        raw_content = ""
        thinking_content = ""
        try:
            stream = await self.vllm_client.chat_completion(
                messages=messages,
                tools=None,
                temperature=0.2,
                max_tokens=1800,
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
                    visible = re.sub(r"<think>[\s\S]*?</think>", "", raw_content, flags=re.IGNORECASE)
                    thinking_match = re.search(r"<think>([\s\S]*?)(?:</think>|$)", raw_content, re.IGNORECASE)
                    if thinking_match:
                        thinking_content = thinking_match.group(1)
                    yield self._sse(
                        {
                            "type": "agent_thinking",
                            "agent": "planner",
                            "delta": piece if visible else piece,
                            "session_id": session_id,
                        }
                    )
        except Exception as exc:
            logger.warning(f"PlannerAgent model call failed: {exc}")
            plan_contract = _default_plan_contract(user_message, existing_files)
            self.last_plan_contract = plan_contract
            self.last_tasks = _plan_contract_to_tasks(plan_contract)
            self.last_thinking = ""
            yield self._sse(
                {
                    "type": "agent_step",
                    "role": "Planner",
                    "status": "error",
                    "title": "PlanContract 生成失败，已回退默认方案",
                    "detail": str(exc),
                    "session_id": session_id,
                }
            )
            yield self._sse(
                {
                    "type": "agent_step",
                    "role": "Planner",
                    "status": "success",
                    "title": "PlanContract 已生成",
                    "detail": f"已回退为 {len(self.last_tasks)} 个实施步骤。",
                    "session_id": session_id,
                }
            )
            return

        self.last_thinking = thinking_content
        plan_contract = _normalize_plan_contract(_find_first_json_object(raw_content), user_message, existing_files)
        self.last_plan_contract = plan_contract
        self.last_tasks = _plan_contract_to_tasks(plan_contract)
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Planner",
                "status": "success",
                "title": "PlanContract 已生成",
                "detail": f"已生成 {len(self.last_tasks)} 个实施步骤与 {len(plan_contract.get('acceptance_criteria', []))} 条验收标准。",
                "session_id": session_id,
            }
        )

    @staticmethod
    def _build_user_prompt(
        user_message: str,
        existing_files: Optional[List[str]],
        *,
        project_summary: Optional[Mapping[str, Any]] = None,
        previous_failures: Optional[List[str]] = None,
        constraints: Optional[Mapping[str, Any]] = None,
        search_reports: Optional[List[Mapping[str, Any]]] = None,
    ) -> str:
        payload = {
            "user_request": user_message,
            "project_summary": dict(project_summary or {}),
            "previous_failures": [str(item) for item in (previous_failures or []) if str(item).strip()],
            "constraints": dict(constraints or {}),
            "search_reports": list(search_reports or []),
            "existing_files": list(existing_files or [])[:30],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def tasks_as_labels(self) -> List[str]:
        return [task["label"] for task in self.last_tasks]
