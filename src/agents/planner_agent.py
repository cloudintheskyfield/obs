from __future__ import annotations

import ast
import json
from utils.json_utils import safe_loads
import re
import shlex
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .base_agent import BaseAgent
from .harness_engine import HarnessEngine
from .plan_compiler import PlanCompiler

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


def _normalize_smoke_tests(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    tests: List[Dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, Mapping):
            test = dict(item)
            test.setdefault("id", f"smoke_{index}")
            test.setdefault("type", "browser")
            action = str(test.get("action") or "goto").strip().lower()
            if action not in {"goto", "click", "keyboard", "evaluate"}:
                action = "evaluate"
            test["action"] = action
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
        parsed = safe_loads(text)
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
                    parsed = safe_loads(candidate)
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


def _default_file_output_commands(allowed_files: List[str], goal: str = "", task_id: str = "") -> List[Dict[str, Any]]:
    concrete_files = _concrete_allowed_files(allowed_files)
    seen = set()
    concrete_files = [path for path in concrete_files if not (path in seen or seen.add(path))]
    if not concrete_files:
        return []
    files_literal = repr(concrete_files)
    cmd = (
        "python -c \"from pathlib import Path; "
        f"files={files_literal}; "
        "present=[p for p in files if Path(p).is_file() and Path(p).stat().st_size > 0]; "
        "missing=[p for p in files if p not in present]; "
        "print(f'Present files: {present}'); "
        "print(f'Missing or empty files: {missing}'); "
        "assert present, 'Error: None of the allowed concrete files were generated or they are all empty!'\""
    )
    return [
        {
            "name": "verify_generated_files",
            "cmd": cmd,
            "timeout_sec": 30,
            "required": False,
        }
    ]


def _verify_generated_files_targets(command: str) -> List[str]:
    text = str(command or "")
    if "missing or empty generated files" not in text:
        return []
    match = re.search(r"files=(\[[^\]]*\])", text)
    if not match:
        return []
    try:
        parsed = ast.literal_eval(match.group(1))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _prune_stale_output_checks(
    commands: List[Dict[str, Any]],
    allowed_files: List[str],
    expected_files: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    concrete = set(_concrete_allowed_files(allowed_files))
    expected = {str(item).strip() for item in (expected_files or []) if str(item).strip()}
    expected_or_concrete = expected or concrete
    if not expected_or_concrete:
        return commands
    pruned: List[Dict[str, Any]] = []
    seen_cmds = set()
    for command in commands:
        cmd = str(command.get("cmd") or "")
        targets = _verify_generated_files_targets(cmd)
        if targets and not all(target in expected_or_concrete for target in targets):
            continue
        if cmd in seen_cmds:
            continue
        seen_cmds.add(cmd)
        pruned.append(command)
    return pruned


def _html_targets_from_contract(contract: Mapping[str, Any]) -> List[str]:
    targets: List[str] = []
    dev_server = contract.get("dev_server") if isinstance(contract.get("dev_server"), Mapping) else {}
    for value in [dev_server.get("url") if isinstance(dev_server, Mapping) else ""]:
        path = str(value or "").split("?", 1)[0].rstrip("/")
        name = path.rsplit("/", 1)[-1]
        if name.endswith((".html", ".htm")):
            targets.append(name)
    for smoke_test in contract.get("smoke_tests") or []:
        if not isinstance(smoke_test, Mapping):
            continue
        target = str(smoke_test.get("target") or "").split("?", 1)[0].rstrip("/")
        name = target.rsplit("/", 1)[-1]
        if name.endswith((".html", ".htm")):
            targets.append(name)
    seen = set()
    result: List[str] = []
    for target in targets:
        if target not in seen:
            seen.add(target)
            result.append(target)
    return result


def _ensure_game_smoke_tests(
    goal: str, smoke_tests: List[Dict[str, Any]], allowed_files: List[str]
) -> List[Dict[str, Any]]:
    return [dict(item) for item in smoke_tests]


def _default_smoke_tests(existing_files: Optional[List[str]]) -> List[Dict[str, Any]]:
    files = existing_files or []
    html_files = [f for f in files if str(f).endswith(".html")]
    if html_files:
        target = html_files[0]
        return [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": target,
                "expect": {
                    "page_loaded": True,
                    "no_fatal_console_error": True,
                },
                "timeout_sec": 15,
                "required": True,
            }
        ]
    return []

def _default_dev_server(
    existing_files: Optional[List[str]], planned_outputs: Optional[List[str]] = None
) -> Dict[str, Any]:
    files = existing_files or []
    outputs = planned_outputs or []

    # If the task outputs standalone HTML files and doesn't modify project config/source
    html_outputs = [f for f in outputs if str(f).endswith(".html")]
    if html_outputs and "package.json" not in outputs and not any(f.startswith("src/") for f in outputs):
        import sys
        return {
            "enabled": True,
            "start_cmd": f"{sys.executable} -m http.server 8080",
            "url": "http://localhost:8080",
            "ready_patterns": ["Serving HTTP"],
            "timeout_sec": 10,
        }

    if "package.json" in files:
        # Avoid 5173 to prevent clashing with host UI
        return {
            "enabled": True,
            "start_cmd": "npm run dev -- --host 0.0.0.0 --port 8080",
            "url": "http://localhost:8080",
            "ready_patterns": ["Local:", "ready in", "localhost", "8080"],
            "timeout_sec": 60,
        }

    html_files = [f for f in [*files, *outputs] if str(f).endswith(".html")]
    if html_files:
        import sys
        return {
            "enabled": True,
            "start_cmd": f"{sys.executable} -m http.server 8080",
            "url": "http://localhost:8080",
            "ready_patterns": ["Serving HTTP"],
            "timeout_sec": 10,
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
    test_commands = [
        *_default_file_output_commands(allowed_files, user_message, "task_plan_001"),
        *_default_test_commands(existing_files),
    ]
    smoke_tests = _ensure_game_smoke_tests(
        user_message,
        _default_smoke_tests(existing_files),
        allowed_files,
    )
    concrete_outputs = _concrete_allowed_files(allowed_files)
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
        "dev_server": _default_dev_server(existing_files, concrete_outputs),
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
    output_commands = _default_file_output_commands(contract["allowed_files"], contract["goal"], contract["task_id"])
    if output_commands:
        existing_cmds = {str(item.get("cmd") or "") for item in contract["test_commands"]}
        contract["test_commands"] = [
            *[item for item in output_commands if str(item.get("cmd") or "") not in existing_cmds],
            *contract["test_commands"],
        ]
    contract["test_commands"] = _prune_stale_output_checks(
        contract["test_commands"],
        contract["allowed_files"],
    )

    dev_server_raw = source.get("dev_server")
    dev_server: Dict[str, Any] = dict(dev_server_raw) if isinstance(dev_server_raw, Mapping) else {}
    default_dev_server = _default_dev_server(
        existing_files,
        _concrete_allowed_files(contract["allowed_files"]),
    )
    contract["dev_server"] = {
        "enabled": bool(dev_server.get("enabled", default_dev_server.get("enabled"))),
        "start_cmd": str(dev_server.get("start_cmd") or default_dev_server.get("start_cmd") or ""),
        "url": str(dev_server.get("url") or default_dev_server.get("url") or ""),
        "ready_patterns": _normalize_string_list(dev_server.get("ready_patterns")) or default_dev_server.get("ready_patterns", []),
        "timeout_sec": int(dev_server.get("timeout_sec", default_dev_server.get("timeout_sec", 60)) or 60),
    }

    if "smoke_tests" in source:
        source_smoke_tests = _normalize_smoke_tests(source.get("smoke_tests"))
    else:
        source_smoke_tests = []
    contract["smoke_tests"] = _ensure_game_smoke_tests(
        contract["goal"],
        source_smoke_tests,
        contract["allowed_files"],
    )
    if contract["smoke_tests"] and not contract["dev_server"].get("enabled"):
        fallback_dev_server = _default_dev_server(
            existing_files,
            _concrete_allowed_files(contract["allowed_files"]),
        )
        if fallback_dev_server.get("enabled"):
            contract["dev_server"] = dict(fallback_dev_server)
    contract["test_commands"] = _prune_stale_output_checks(
        contract["test_commands"],
        contract["allowed_files"],
        _html_targets_from_contract(contract),
    )
    source_steps = source.get("implementation_steps")
    normalized_source_steps = _normalize_steps(source_steps) if isinstance(source_steps, list) else []
    if normalized_source_steps:
        contract["implementation_steps"] = normalized_source_steps
    elif (
        isinstance(source_steps, list)
        and not contract["allowed_files"]
        and not contract["test_commands"]
        and not contract["smoke_tests"]
    ):
        contract["implementation_steps"] = []
    else:
        contract["implementation_steps"] = _derive_implementation_steps(
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


class PlannerAgent(BaseAgent):
    def __init__(self, vllm_client: Any) -> None:
        super().__init__("Planner", vllm_client)
        self.last_plan_contract: Dict[str, Any] = {}
        self.last_plan_markdown: str = ""
        self.last_compiler_report: Dict[str, Any] = {}
        self.last_tasks: List[Dict[str, Any]] = []
        self.last_thinking: str = ""

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
        recent_messages: Optional[List[Mapping[str, Any]]] = None,
        memory: Optional[Mapping[str, Any]] = None,
        working_memory: Optional[Mapping[str, Any]] = None,
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
                    recent_messages=recent_messages,
                    memory=memory,
                    working_memory=working_memory,
                ),
            },
        ]

        raw_content = ""
        thinking_content = ""
        chunk_count = 0
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
                chunk_count += 1
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
                    
                    # 动态更新前端展示的状态
                    if chunk_count % 15 == 0 and thinking_content:
                        dynamic_detail = self._extract_thinking_summary(thinking_content, default_detail="整理目标、范围、验证方式与约束...")
                        yield self._status("running", role="Planner", title="生成 PlanContract", detail=dynamic_detail, session_id=session_id)
        except Exception as exc:
            logger.warning(f"PlannerAgent model call failed: {exc}")
            plan_contract = _default_plan_contract(user_message, existing_files)
            self.last_plan_contract = plan_contract
            self.last_plan_markdown = ""
            self.last_compiler_report = {}
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
        self.last_plan_markdown = raw_content
        
        task_context = {
            "task_id": "task_plan_001",
            "user_request": user_message
        }
        
        compiler = PlanCompiler(self.vllm_client, self.skill_manager)
        compile_result = None
        
        async for item in compiler.compile(
            raw_content, 
            task_context, 
            dict(project_summary or {}),
            model=model,
            session_id=session_id,
            previous_failures=previous_failures,
            search_reports=search_reports
        ):
            if isinstance(item, dict) and "ok" in item:
                compile_result = item
            elif isinstance(item, str):
                yield item
        
        if not compile_result:
            compile_result = {
                "ok": False,
                "plan_contract": None,
                "errors": [{"type": "COMPILER_ERROR", "message": "No compile result received."}],
                "warnings": []
            }
            
        self.last_compiler_report = compile_result
        
        if compile_result["ok"] and compile_result["plan_contract"]:
            self.last_plan_contract = _normalize_plan_contract(compile_result["plan_contract"], user_message, existing_files)
        else:
            # Fallback if parsing failed completely
            self.last_plan_contract = _normalize_plan_contract(_find_first_json_object(raw_content), user_message, existing_files)
            
        self.last_tasks = _plan_contract_to_tasks(self.last_plan_contract)
        
        if compile_result["ok"]:
            yield self._sse(
                {
                    "type": "agent_step",
                    "role": "Planner",
                    "status": "success",
                    "title": "PlanContract 已生成",
                    "detail": f"已生成 {len(self.last_tasks)} 个实施步骤与 {len(self.last_plan_contract.get('acceptance_criteria', []))} 条验收标准。",
                    "session_id": session_id,
                }
            )
        else:
            yield self._sse(
                {
                    "type": "agent_step",
                    "role": "Planner",
                    "status": "error",
                    "title": "Planner 输出格式错误，已回退默认方案",
                    "detail": compile_result.get("errors", [{"message": "Unknown parse error"}])[0].get("message"),
                    "session_id": session_id,
                }
            )
    @classmethod
    def _build_user_prompt(
        cls,
        user_message: str,
        existing_files: Optional[List[str]],
        *,
        project_summary: Optional[Mapping[str, Any]] = None,
        previous_failures: Optional[List[str]] = None,
        constraints: Optional[Mapping[str, Any]] = None,
        search_reports: Optional[List[Mapping[str, Any]]] = None,
        recent_messages: Optional[List[Mapping[str, Any]]] = None,
        memory: Optional[Mapping[str, Any]] = None,
        working_memory: Optional[Mapping[str, Any]] = None,
    ) -> str:
        payload = {
            "user_request": user_message,
        }
        if memory:
            payload["memory"] = dict(memory)
        if working_memory:
            payload["working_memory"] = dict(working_memory)
        if recent_messages:
            payload["recent_messages"] = [
                {"role": m.get("role"), "content": m.get("content")}
                for m in recent_messages
            ]
        
        payload.update({
            "project_summary": dict(project_summary or {}),
            "previous_failures": [str(item) for item in (previous_failures or []) if str(item).strip()],
            "constraints": dict(constraints or {}),
            "search_reports": list(search_reports or []),
            "existing_files": list(existing_files or [])[:30],
        })
        return cls._format_as_markdown(payload)

    def tasks_as_labels(self) -> List[str]:
        return [task["label"] for task in self.last_tasks]
