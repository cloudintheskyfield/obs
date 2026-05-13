import json
import asyncio
import os
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .harness_engine import HarnessEngine

RUNNER_SYSTEM_PROMPT = (
    "You are Runner Agent in a five-agent Harness workflow. "
    "Your only responsibility is execution and evidence collection.\n\n"
    "You may use only the provided execution tools to run the commands "
    "and smoke checks supplied by the Harness input.\n"
    "Do not modify source code. Do not judge final acceptance.\n"
    "Write artifacts only under .harness/**, logs/**, screenshots/**, "
    "or tmp/**.\n"
    "After collecting evidence, return exactly one strict JSON "
    "RunReport object with these fields:\n"
    "schema_version, task_id, round_id, status, started_at, finished_at, "
    "duration_sec, commands, dev_server, browser_tests, artifacts, "
    "cleanup, errors, summary.\n"
    "Use status values from the spec: PASSED, FAILED, PARTIAL, TIMEOUT, "
    "SKIPPED, or INFRA_ERROR."
)


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


def _normalize_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _tail_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "")
    return text[-limit:]


def _runner_input_commands(runner_input: Mapping[str, Any]) -> List[str]:
    commands: List[str] = []
    for item in runner_input.get("test_commands") or []:
        if isinstance(item, Mapping):
            cmd = str(item.get("cmd") or item.get("command") or "").strip()
        else:
            cmd = str(item).strip()
        if cmd:
            commands.append(cmd)
    dev_server: Dict[str, Any] = (
        dict(runner_input.get("dev_server") or {})
        if isinstance(runner_input.get("dev_server"), Mapping)
        else {}
    )
    start_cmd = str(dev_server.get("start_cmd") or "").strip()
    if start_cmd:
        commands.append(start_cmd)
    seen = set()
    result: List[str] = []
    for command in commands:
        if command not in seen:
            seen.add(command)
            result.append(command)
    return result


def _runner_command_specs(runner_input: Mapping[str, Any]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for index, item in enumerate(runner_input.get("test_commands") or [], start=1):
        if isinstance(item, Mapping):
            command = str(item.get("cmd") or item.get("command") or "").strip()
            if not command:
                continue
            specs.append(
                {
                    "name": str(item.get("name") or f"cmd_{index}").strip()
                    or f"cmd_{index}",
                    "cmd": command,
                    "timeout_sec": int(item.get("timeout_sec") or 120),
                    "required": bool(item.get("required", index == 1)),
                }
            )
        else:
            command = str(item).strip()
            if command:
                specs.append(
                    {
                        "name": f"cmd_{index}",
                        "cmd": command,
                        "timeout_sec": 120,
                        "required": index == 1,
                    }
                )
    return specs


async def _run_shell_command(
    command: str, *, cwd: Path, timeout_sec: int
) -> Dict[str, Any]:
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    started_ts = time.time()
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        env=os.environ.copy(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        await process.wait()
        stdout, stderr = b"", b"Command timed out"
    finished = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "cmd": command,
        "exit_code": -1 if timed_out else int(process.returncode or 0),
        "status": (
            "TIMEOUT"
            if timed_out
            else ("PASSED" if process.returncode == 0 else "FAILED")
        ),
        "started_at": started,
        "finished_at": finished,
        "duration_sec": round(time.time() - started_ts, 3),
        "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
        "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
    }


async def _read_process_stream(
    stream: Optional[asyncio.StreamReader], buffer: List[str]
) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.readline()
        if not chunk:
            return
        buffer.append(chunk.decode("utf-8", errors="replace"))


async def _http_probe(url: str, *, timeout_sec: int) -> Dict[str, Any]:
    def _fetch() -> Dict[str, Any]:
        request = urllib.request.Request(
            url, headers={"User-Agent": "OBS-HarnessRunner/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                body = response.read(200000).decode("utf-8", errors="replace")
                return {
                    "ok": 200 <= int(response.status or 0) < 400,
                    "status_code": int(response.status or 0),
                    "body": body,
                    "headers": dict(response.headers.items()),
                    "final_url": str(response.geturl() or url),
                    "error": "",
                }
        except urllib.error.HTTPError as exc:
            body = exc.read(200000).decode("utf-8", errors="replace")
            return {
                "ok": False,
                "status_code": int(exc.code or 0),
                "body": body,
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "final_url": str(exc.geturl() or url),
                "error": str(exc),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status_code": 0,
                "body": "",
                "headers": {},
                "final_url": url,
                "error": str(exc),
            }

    return await asyncio.to_thread(_fetch)


def _resolve_smoke_target(target: str, base_url: str) -> str:
    candidate = str(target or "").strip()
    base = str(base_url or "").strip()
    if not candidate:
        return base
    if candidate.startswith(("http://", "https://")):
        return candidate
    if base:
        return urllib.parse.urljoin(
            base if base.endswith("/") else f"{base}/", candidate.lstrip("/")
        )
    return candidate


async def _terminate_process(process: asyncio.subprocess.Process) -> List[str]:
    killed: List[str] = []
    if process.returncode is not None:
        return killed
    try:
        pgid = os.getpgid(process.pid)
    except Exception:
        pgid = None
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
            killed.append(str(pgid))
        else:
            process.kill()
            killed.append(str(process.pid))
        await process.wait()
    except ProcessLookupError:
        pass
    return killed


def _normalize_run_report(
    raw_obj: Optional[Dict[str, Any]],
    runner_input: Mapping[str, Any],
    harness: HarnessEngine,
    *,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    source: Dict[str, Any] = dict(raw_obj or {})
    plan_contract_raw = runner_input.get("plan_contract")
    plan_contract: Dict[str, Any] = (
        dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    )
    default_status = str(source.get("status") or "FAILED").upper()
    if default_status not in {
        "PASSED",
        "FAILED",
        "PARTIAL",
        "TIMEOUT",
        "SKIPPED",
        "INFRA_ERROR",
    }:
        default_status = "FAILED"
    run_dir = str(source.get("run_dir") or runner_input.get("run_dir") or "")
    artifacts: Dict[str, Any] = (
        dict(source.get("artifacts") or {})
        if isinstance(source.get("artifacts"), Mapping)
        else {}
    )
    report = {
        "schema_version": str(source.get("schema_version") or "1.0"),
        "task_id": str(
            source.get("task_id")
            or runner_input.get("task_id")
            or plan_contract.get("task_id")
            or "task_runtime_001"
        ),
        "round_id": int(source.get("round_id") or runner_input.get("round_id") or 1),
        "status": default_status,
        "started_at": str(source.get("started_at") or started_at or ""),
        "finished_at": str(source.get("finished_at") or finished_at or ""),
        "duration_sec": float(source.get("duration_sec") or duration_sec or 0.0),
        "commands": _normalize_list(source.get("commands")),
        "dev_server": (
            source.get("dev_server")
            if isinstance(source.get("dev_server"), Mapping)
            else {}
        ),
        "browser_tests": _normalize_list(source.get("browser_tests")),
        "artifacts": {
            "run_dir": run_dir,
            "screenshots": _normalize_list(artifacts.get("screenshots")),
            "traces": _normalize_list(artifacts.get("traces")),
            "logs": _normalize_list(artifacts.get("logs")),
            "browser_console": str(artifacts.get("browser_console") or ""),
        },
        "cleanup": (
            source.get("cleanup")
            if isinstance(source.get("cleanup"), Mapping)
            else {
                "browser_closed": False,
                "dev_server_stopped": False,
                "orphan_processes_killed": [],
            }
        ),
        "errors": _normalize_list(source.get("errors")),
        "summary": str(source.get("summary") or ""),
    }
    report["display_summary"] = harness.display_summary_for_output("Runner", report)
    return report


def _fallback_run_report(
    runner_input: Mapping[str, Any],
    error_message: str,
    harness: HarnessEngine,
    *,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    plan_contract_raw = runner_input.get("plan_contract")
    plan_contract: Dict[str, Any] = (
        dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    )
    report = {
        "schema_version": "1.0",
        "task_id": str(
            runner_input.get("task_id")
            or plan_contract.get("task_id")
            or "task_runtime_001"
        ),
        "round_id": int(runner_input.get("round_id") or 1),
        "status": "INFRA_ERROR",
        "started_at": str(started_at or ""),
        "finished_at": str(finished_at or ""),
        "duration_sec": float(duration_sec or 0.0),
        "commands": [],
        "dev_server": {},
        "browser_tests": [],
        "artifacts": {
            "run_dir": str(runner_input.get("run_dir") or ""),
            "screenshots": [],
            "traces": [],
            "logs": [],
            "browser_console": "",
        },
        "cleanup": {
            "browser_closed": False,
            "dev_server_stopped": False,
            "orphan_processes_killed": [],
        },
        "errors": [
            {
                "type": "RUNNER_SCRIPT_ERROR",
                "root_category": "RUNNER",
                "message": error_message,
            }
        ],
        "summary": error_message,
    }
    report["display_summary"] = harness.display_summary_for_output("Runner", report)
    return report


class RunnerAgent:
    def __init__(self, vllm_client: Any, skill_manager: Any) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt(
            "Runner", RUNNER_SYSTEM_PROMPT
        )
        self.last_run_report: Dict[str, Any] = {}

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def _start_dev_server(
        self,
        *,
        workspace: Path,
        run_dir: str,
        dev_server: Mapping[str, Any],
        allowed_commands: List[str],
        default_timeout_sec: int,
    ) -> Dict[str, Any]:
        start_cmd = str(dev_server.get("start_cmd") or "").strip()
        url = str(dev_server.get("url") or "").strip()
        ready_patterns = [
            str(item).strip()
            for item in (dev_server.get("ready_patterns") or [])
            if str(item).strip()
        ]
        timeout_sec = int(dev_server.get("timeout_sec") or default_timeout_sec or 60)
        log_path = workspace / run_dir / "logs" / "dev_server.log"
        relative_log = str(log_path.relative_to(workspace)).replace("\\", "/")

        report = {
            "enabled": bool(dev_server.get("enabled")),
            "start_cmd": start_cmd,
            "url": url,
            "ready_patterns": ready_patterns,
            "timeout_sec": timeout_sec,
            "status": "SKIPPED",
            "pid": None,
            "started_at": "",
            "finished_at": "",
            "duration_sec": 0.0,
            "ready": False,
            "ready_source": "",
            "matched_pattern": "",
            "log": relative_log,
        }

        if not start_cmd:
            report["status"] = "FAILED"
            report["finished_at"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            return {
                "report": report,
                "errors": [
                    {
                        "type": "RUNNER_SCRIPT_ERROR",
                        "root_category": "RUNNER",
                        "message": "dev_server.enabled is true but start_cmd is empty.",
                    }
                ],
                "process": None,
                "stdout_buffer": [],
                "stderr_buffer": [],
                "stdout_task": None,
                "stderr_task": None,
            }

        if not self.harness.command_allowed(
            start_cmd, runner_input_commands=allowed_commands
        ):
            report["status"] = "FAILED"
            report["finished_at"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            return {
                "report": report,
                "errors": [
                    {
                        "type": "HARNESS_POLICY_VIOLATION",
                        "root_category": "HARNESS",
                        "message": (
                            "Blocked dev server command outside Runner "
                            f"input contract: {start_cmd}"
                        ),
                    }
                ],
                "process": None,
                "stdout_buffer": [],
                "stderr_buffer": [],
                "stdout_task": None,
                "stderr_task": None,
            }

        started_ts = time.time()
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        report["started_at"] = started_at
        process = await asyncio.create_subprocess_shell(
            start_cmd,
            cwd=str(workspace),
            env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        report["pid"] = int(process.pid or 0)
        stdout_buffer: List[str] = []
        stderr_buffer: List[str] = []
        stdout_task = asyncio.create_task(
            _read_process_stream(process.stdout, stdout_buffer)
        )
        stderr_task = asyncio.create_task(
            _read_process_stream(process.stderr, stderr_buffer)
        )
        probe_result: Dict[str, Any] = {
            "ok": False,
            "status_code": 0,
            "body": "",
            "error": "",
        }

        ready = False
        ready_source = ""
        matched_pattern = ""
        timeout_at = time.time() + timeout_sec
        while time.time() < timeout_at:
            combined = "".join(stdout_buffer[-200:]) + "".join(stderr_buffer[-200:])
            for pattern in ready_patterns:
                if pattern.lower() in combined.lower():
                    ready = True
                    ready_source = "log"
                    matched_pattern = pattern
                    break
            if ready:
                break
            if url:
                probe_result = await _http_probe(url, timeout_sec=2)
                if probe_result.get("ok"):
                    ready = True
                    ready_source = "http"
                    break
            if process.returncode is not None:
                break
            await asyncio.sleep(0.5)

        report["ready"] = ready
        report["ready_source"] = ready_source
        report["matched_pattern"] = matched_pattern
        report["duration_sec"] = round(time.time() - started_ts, 3)
        report["finished_at"] = (
            datetime.now().astimezone().isoformat(timespec="seconds")
        )

        errors: List[Dict[str, Any]] = []
        if ready:
            report["status"] = "PASSED"
        elif process.returncode is not None:
            report["status"] = "FAILED"
            errors.append(
                {
                    "type": "RUNNER_SCRIPT_ERROR",
                    "root_category": "RUNNER",
                    "message": _tail_text(
                        "".join(stderr_buffer)
                        or "".join(stdout_buffer)
                        or "Dev server exited before becoming ready."
                    ),
                }
            )
        else:
            report["status"] = "TIMEOUT"
            detail = (
                probe_result.get("error")
                or "Ready patterns were not observed before timeout."
            )
            errors.append(
                {
                    "type": "RUNNER_TIMEOUT",
                    "root_category": "RUNNER",
                    "message": f"Dev server did not become ready: {detail}",
                }
            )
        return {
            "report": report,
            "errors": errors,
            "process": process,
            "stdout_buffer": stdout_buffer,
            "stderr_buffer": stderr_buffer,
            "stdout_task": stdout_task,
            "stderr_task": stderr_task,
        }

    async def _stop_dev_server(
        self, ctx: Mapping[str, Any], *, workspace: Path
    ) -> Dict[str, Any]:
        process = ctx.get("process")
        stdout_task = ctx.get("stdout_task")
        stderr_task = ctx.get("stderr_task")
        stdout_buffer = list(ctx.get("stdout_buffer") or [])
        stderr_buffer = list(ctx.get("stderr_buffer") or [])
        report = dict(ctx.get("report") or {})
        orphan_processes_killed: List[str] = []

        if process is not None:
            orphan_processes_killed = await _terminate_process(process)
        if stdout_task is not None:
            await stdout_task
        if stderr_task is not None:
            await stderr_task

        log_rel = str(report.get("log") or "")
        if log_rel:
            log_path = workspace / log_rel
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                "".join(
                    [
                        f"$ {report.get('start_cmd') or ''}\n",
                        "[stdout]\n",
                        "".join(stdout_buffer),
                        "\n[stderr]\n",
                        "".join(stderr_buffer),
                    ]
                ),
                encoding="utf-8",
            )

        return {
            "report": report,
            "stdout": "".join(stdout_buffer),
            "stderr": "".join(stderr_buffer),
            "orphan_processes_killed": orphan_processes_killed,
        }

    async def _run_browser_smoke_test(
        self,
        smoke_test: Mapping[str, Any],
        *,
        workspace: Path,
        base_url: str,
        default_timeout_sec: int,
    ) -> Dict[str, Any]:
        started_ts = time.time()
        test_id = str(smoke_test.get("id") or smoke_test.get("action") or "smoke")
        action = str(smoke_test.get("action") or "goto").strip() or "goto"
        target = _resolve_smoke_target(str(smoke_test.get("target") or ""), base_url)
        timeout_sec = int(smoke_test.get("timeout_sec") or default_timeout_sec or 15)
        required = bool(smoke_test.get("required", True))
        expect = (
            dict(smoke_test.get("expect") or {})
            if isinstance(smoke_test.get("expect"), Mapping)
            else {}
        )

        evidence: List[str] = []
        result: Dict[str, Any] = {
            "id": test_id,
            "type": str(smoke_test.get("type") or "browser"),
            "action": action,
            "target": target,
            "required": required,
            "status": "SKIPPED",
            "duration_sec": 0.0,
            "http_status": None,
            "passed": False,
            "evidence": evidence,
            "error": "",
        }

        if not target:
            result["status"] = "FAILED"
            result["error"] = (
                "Smoke test target is empty and no dev server url is available."
            )
            result["duration_sec"] = round(time.time() - started_ts, 3)
            return result

        if action != "goto":
            result["status"] = "FAILED"
            result["error"] = (
                f"Unsupported smoke test action in deterministic Runner: {action}"
            )
            result["duration_sec"] = round(time.time() - started_ts, 3)
            return result

        if target.startswith(("http://", "https://")):
            probe = await _http_probe(target, timeout_sec=timeout_sec)
        else:
            local_path = Path(target)
            if not local_path.is_absolute():
                local_path = (workspace / target).resolve()
            if local_path.exists() and local_path.is_file():
                body = local_path.read_text(encoding="utf-8", errors="replace")
                probe = {
                    "ok": True,
                    "status_code": 200,
                    "body": body,
                    "headers": {},
                    "final_url": str(local_path),
                    "error": "",
                }
            else:
                probe = {
                    "ok": False,
                    "status_code": 0,
                    "body": "",
                    "headers": {},
                    "final_url": str(local_path),
                    "error": f"Local smoke test target not found: {local_path}",
                }
        result["http_status"] = int(probe.get("status_code") or 0) or None
        if probe.get("ok"):
            body = str(probe.get("body") or "")
            contains = str(expect.get("contains") or expect.get("text") or "").strip()
            page_loaded = bool(expect.get("page_loaded", True))
            failed_reason = ""
            if page_loaded and not body:
                failed_reason = "Page responded but body was empty."
            elif contains and contains not in body:
                failed_reason = f"Expected text not found: {contains}"
            if failed_reason:
                result["status"] = "FAILED"
                result["error"] = failed_reason
                result["evidence"] = [f"GET {target} -> {probe.get('status_code')}"]
            else:
                result["status"] = "PASSED"
                result["passed"] = True
                result["evidence"] = [f"GET {target} -> {probe.get('status_code')}"]
                if expect.get("no_fatal_console_error"):
                    result["evidence"].append(
                        "No browser console was collected in deterministic mode."
                    )
        else:
            result["status"] = "FAILED"
            result["error"] = str(probe.get("error") or f"GET {target} failed")
            result["evidence"] = [
                f"GET {target} -> {probe.get('status_code') or 'ERR'}"
            ]
        result["duration_sec"] = round(time.time() - started_ts, 3)
        return result

    async def _run_controlled_commands(
        self,
        runner_input: Mapping[str, Any],
        *,
        started_at: str,
        started_ts: float,
    ) -> Dict[str, Any]:
        workspace = (
            Path(str(runner_input.get("workspace") or ".")).expanduser().resolve()
        )
        workspace.mkdir(parents=True, exist_ok=True)
        run_dir = str(runner_input.get("run_dir") or ".harness/runs/run_001")
        log_dir = workspace / run_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        command_specs = _runner_command_specs(runner_input)
        smoke_tests = [
            dict(item)
            for item in (runner_input.get("smoke_tests") or [])
            if isinstance(item, Mapping)
        ]
        runner_limits = (
            dict(runner_input.get("runner_limits") or {})
            if isinstance(runner_input.get("runner_limits"), Mapping)
            else {}
        )
        allowed_commands = _runner_input_commands(runner_input)
        dev_server_cfg = (
            dict(runner_input.get("dev_server") or {})
            if isinstance(runner_input.get("dev_server"), Mapping)
            else {}
        )
        dev_server_enabled = bool(dev_server_cfg.get("enabled"))
        commands: List[Dict[str, Any]] = []
        browser_tests: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        artifact_logs: List[str] = []
        dev_server_report: Dict[str, Any] = {}
        cleanup = {
            "browser_closed": True,
            "dev_server_stopped": not dev_server_enabled,
            "orphan_processes_killed": [],
        }
        dev_server_ctx: Optional[Dict[str, Any]] = None

        try:
            for spec in command_specs:
                command = str(spec.get("cmd") or "")
                if not self.harness.command_allowed(
                    command, runner_input_commands=allowed_commands
                ):
                    errors.append(
                        {
                            "type": "HARNESS_POLICY_VIOLATION",
                            "root_category": "HARNESS",
                            "message": (
                                "Blocked command outside Runner input "
                                f"contract: {command}"
                            ),
                        }
                    )
                    commands.append({**spec, "status": "BLOCKED", "exit_code": None})
                    if spec.get("required", True):
                        break
                    continue

                result = await _run_shell_command(
                    command,
                    cwd=workspace,
                    timeout_sec=int(
                        spec.get("timeout_sec")
                        or runner_limits.get("command_timeout_sec")
                        or 120
                    ),
                )
                log_path = (
                    log_dir
                    / f"{str(spec.get('name') or 'command').replace('/', '_')}.log"
                )
                log_path.write_text(
                    "\n".join(
                        [
                            f"$ {command}",
                            f"status: {result['status']}",
                            f"exit_code: {result['exit_code']}",
                            "",
                            "[stdout]",
                            str(result.get("stdout") or ""),
                            "",
                            "[stderr]",
                            str(result.get("stderr") or ""),
                        ]
                    ),
                    encoding="utf-8",
                )
                relative_log = str(log_path.relative_to(workspace)).replace("\\", "/")
                artifact_logs.append(relative_log)
                command_record = {
                    **spec,
                    "status": result["status"],
                    "exit_code": result["exit_code"],
                    "duration_sec": result["duration_sec"],
                    "stdout_tail": _tail_text(result.get("stdout")),
                    "stderr_tail": _tail_text(result.get("stderr")),
                    "log": relative_log,
                }
                commands.append(command_record)
                if result["status"] != "PASSED":
                    errors.append(
                        {
                            "type": (
                                "RUNNER_TIMEOUT"
                                if result["status"] == "TIMEOUT"
                                else "PRODUCT_BUILD_ERROR"
                            ),
                            "root_category": (
                                "RUNNER" if result["status"] == "TIMEOUT" else "PRODUCT"
                            ),
                            "message": _tail_text(
                                result.get("stderr")
                                or result.get("stdout")
                                or f"Command failed: {command}"
                            ),
                            "command": command,
                        }
                    )
                    if spec.get("required", True):
                        break

            required_command_failed = any(
                command.get("required", True)
                and command.get("status") not in {"PASSED"}
                for command in commands
            )

            if not required_command_failed and dev_server_enabled:
                dev_server_ctx = await self._start_dev_server(
                    workspace=workspace,
                    run_dir=run_dir,
                    dev_server=dev_server_cfg,
                    allowed_commands=allowed_commands,
                    default_timeout_sec=int(
                        runner_limits.get("dev_server_timeout_sec") or 60
                    ),
                )
                dev_server_report = dict(dev_server_ctx.get("report") or {})
                errors.extend(list(dev_server_ctx.get("errors") or []))
                if dev_server_report.get("log"):
                    artifact_logs.append(str(dev_server_report.get("log")))

            dev_server_ready = not dev_server_enabled or bool(
                dev_server_report.get("ready")
            )
            if smoke_tests and dev_server_ready:
                base_url = str(
                    dev_server_report.get("url") or dev_server_cfg.get("url") or ""
                )
                for smoke_test in smoke_tests:
                    browser_test = await self._run_browser_smoke_test(
                        smoke_test,
                        workspace=workspace,
                        base_url=base_url,
                        default_timeout_sec=int(
                            runner_limits.get("browser_test_timeout_sec") or 60
                        ),
                    )
                    browser_tests.append(browser_test)
                    if browser_test["status"] != "PASSED" and browser_test.get(
                        "required", True
                    ):
                        message = str(
                            browser_test.get("error")
                            or f"Smoke test failed: {browser_test.get('id')}"
                        )
                        error_type = "RUNNER_BROWSER_ERROR"
                        root_category = "RUNNER"
                        if browser_test.get("http_status"):
                            error_type = "PRODUCT_RUNTIME_ERROR"
                            root_category = "PRODUCT"
                        errors.append(
                            {
                                "type": error_type,
                                "root_category": root_category,
                                "message": message,
                                "smoke_test_id": browser_test.get("id"),
                            }
                        )
                        break
            elif smoke_tests and dev_server_enabled and not dev_server_ready:
                for smoke_test in smoke_tests:
                    browser_tests.append(
                        {
                            "id": str(
                                smoke_test.get("id")
                                or smoke_test.get("action")
                                or "smoke"
                            ),
                            "type": str(smoke_test.get("type") or "browser"),
                            "action": str(smoke_test.get("action") or "goto"),
                            "target": _resolve_smoke_target(
                                str(smoke_test.get("target") or ""),
                                str(dev_server_cfg.get("url") or ""),
                            ),
                            "required": bool(smoke_test.get("required", True)),
                            "status": "SKIPPED",
                            "duration_sec": 0.0,
                            "http_status": None,
                            "passed": False,
                            "evidence": [
                                "Smoke test skipped because dev server was not ready."
                            ],
                            "error": "",
                        }
                    )
        finally:
            if dev_server_ctx is not None:
                stopped = await self._stop_dev_server(
                    dev_server_ctx, workspace=workspace
                )
                cleanup["dev_server_stopped"] = True
                cleanup["orphan_processes_killed"] = list(
                    stopped.get("orphan_processes_killed") or []
                )
                if dev_server_report and not dev_server_report.get("status"):
                    dev_server_report = dict(stopped.get("report") or dev_server_report)
            elif not dev_server_enabled:
                cleanup["dev_server_stopped"] = True

        has_work = bool(command_specs or dev_server_enabled or smoke_tests)
        required_browser_failed = any(
            item.get("required", True)
            and item.get("status") not in {"PASSED", "SKIPPED"}
            for item in browser_tests
        )
        optional_failures = any(
            not item.get("required", True)
            and item.get("status") not in {"PASSED", "SKIPPED"}
            for item in commands + browser_tests
        )

        if not has_work:
            status = "SKIPPED"
        elif any(error.get("type") == "RUNNER_TIMEOUT" for error in errors):
            status = "TIMEOUT"
        elif (
            required_command_failed
            or required_browser_failed
            or any(error.get("type") == "RUNNER_SCRIPT_ERROR" for error in errors)
        ):
            status = "FAILED"
        elif errors or optional_failures:
            status = "PARTIAL"
        else:
            status = "PASSED"

        finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        summary_parts: List[str] = []
        if commands:
            summary_parts.append(f"Executed {len(commands)} command(s)")
        if dev_server_enabled:
            if dev_server_report.get("ready"):
                summary_parts.append("started dev server")
            else:
                summary_parts.append("dev server was not ready")
        if browser_tests:
            passed_tests = sum(
                1 for item in browser_tests if item.get("status") == "PASSED"
            )
            summary_parts.append(
                f"completed {passed_tests}/{len(browser_tests)} smoke test(s)"
            )
        if not summary_parts:
            summary_parts.append("No Runner commands or smoke tests were provided.")

        report = {
            "schema_version": "1.0",
            "task_id": str(runner_input.get("task_id") or "task_runtime_001"),
            "round_id": int(runner_input.get("round_id") or 1),
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": round(time.time() - started_ts, 3),
            "commands": commands,
            "dev_server": dev_server_report,
            "browser_tests": browser_tests,
            "artifacts": {
                "run_dir": run_dir,
                "screenshots": [],
                "traces": [],
                "logs": list(dict.fromkeys(artifact_logs)),
                "browser_console": "",
            },
            "cleanup": cleanup,
            "errors": errors,
            "summary": "; ".join(summary_parts),
        }
        report["display_summary"] = self.harness.display_summary_for_output(
            "Runner", report
        )
        return report

    async def run(
        self,
        session_id: str,
        runner_input: Mapping[str, Any],
        *,
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_iterations: int = 8,
    ) -> AsyncGenerator[str, None]:
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Runner",
                "status": "running",
                "title": "执行验证与采集证据",
                "detail": "运行命令、页面检查与日志采集...",
                "session_id": session_id,
            }
        )

        runner_tools = self.harness.filter_tools_for_role("Runner", tools)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_user_prompt(runner_input)},
        ]

        raw_content = ""
        tool_step = 0
        run_report: Dict[str, Any] = {}
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        started_ts = time.time()

        deterministic_runner = (
            str(runner_input.get("execution_mode") or "").strip().lower()
            == "harness_controlled"
        )
        if self.vllm_client is None or deterministic_runner:
            run_report = await self._run_controlled_commands(
                runner_input,
                started_at=started_at,
                started_ts=started_ts,
            )

        for iteration in range(0 if run_report else max_iterations):
            assistant_message: Dict[str, Any] = {"role": "assistant", "content": ""}
            tool_calls: List[Dict[str, Any]] = []
            try:
                stream = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=runner_tools if runner_tools else None,
                    temperature=0.1,
                    max_tokens=2200,
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
                        assistant_message["content"] += piece
                        yield self._sse(
                            {
                                "type": "agent_thinking",
                                "agent": "runner",
                                "delta": piece,
                                "session_id": session_id,
                            }
                        )
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", len(tool_calls))
                            while len(tool_calls) <= idx:
                                tool_calls.append(
                                    {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                )
                            if tc.get("id"):
                                tool_calls[idx]["id"] = tc["id"]
                            if "function" in tc:
                                if tc["function"].get("name"):
                                    tool_calls[idx]["function"]["name"] += tc[
                                        "function"
                                    ]["name"]
                                if tc["function"].get("arguments"):
                                    tool_calls[idx]["function"]["arguments"] += tc[
                                        "function"
                                    ]["arguments"]
            except Exception as exc:
                logger.warning(f"RunnerAgent iteration {iteration} model error: {exc}")
                finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
                run_report = _fallback_run_report(
                    runner_input,
                    str(exc),
                    self.harness,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_sec=round(time.time() - started_ts, 3),
                )
                break

            if not tool_calls:
                finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
                run_report = _normalize_run_report(
                    _find_first_json_object(assistant_message["content"]),
                    runner_input,
                    self.harness,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_sec=round(time.time() - started_ts, 3),
                )
                break

            assistant_message["tool_calls"] = tool_calls
            messages.append(dict(assistant_message))

            allowed_commands = _runner_input_commands(runner_input)
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    raw_args = tc["function"]["arguments"]
                    tool_args = json.loads(raw_args) if raw_args else {}
                except Exception:
                    tool_args = {}

                resolved_tool_name = (
                    self.skill_manager.resolve_skill_name_for_tool(tool_name)
                    or tool_name
                )
                if resolved_tool_name == "desktop-commander":
                    command = str(tool_args.get("command") or "").strip()
                    if not self.harness.command_allowed(
                        command,
                        runner_input_commands=allowed_commands,
                    ):
                        tool_args = {}
                        tool_name = tool_name or "desktop-commander.terminal"
                        tool_result = (
                            f"Blocked command outside Runner input contract: {command}"
                        )
                        yield self._sse(
                            {
                                "type": "agent_step",
                                "role": "Runner",
                                "status": "error",
                                "title": "Runner 命令被 Harness 拦截",
                                "detail": tool_result,
                                "session_id": session_id,
                            }
                        )
                        finished_at = (
                            datetime.now().astimezone().isoformat(timespec="seconds")
                        )
                        run_report = _fallback_run_report(
                            runner_input,
                            tool_result,
                            self.harness,
                            started_at=started_at,
                            finished_at=finished_at,
                            duration_sec=round(time.time() - started_ts, 3),
                        )
                        break

                tool_step += 1
                task_id = f"runner_step_{tool_step}"
                yield self._sse(
                    {
                        "type": "task_start",
                        "task_id": task_id,
                        "description": f"[Runner] {tool_name}",
                        "skill": tool_name,
                        "action": "tool",
                        "session_id": session_id,
                    }
                )

                tool_result = ""
                success = False
                try:
                    result = await self.skill_manager.execute_skill(
                        tool_name, **tool_args
                    )
                    tool_result = (
                        str(result.content)
                        if result.success
                        else f"Error: {result.error}"
                    )
                    success = result.success
                except Exception as exc:
                    tool_result = str(exc)

                yield self._sse(
                    {
                        "type": "task_complete",
                        "task_id": task_id,
                        "success": success,
                        "content": (
                            tool_result[:400] + "..."
                            if len(tool_result) > 400
                            else tool_result
                        ),
                        "description": f"[Runner] {tool_name}",
                        "session_id": session_id,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", "unknown"),
                        "name": tool_name,
                        "content": tool_result[:8000],
                    }
                )

        if not run_report:
            finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
            run_report = _fallback_run_report(
                runner_input,
                "Runner did not return a valid RunReport.",
                self.harness,
                started_at=started_at,
                finished_at=finished_at,
                duration_sec=round(time.time() - started_ts, 3),
            )

        self.last_run_report = run_report
        passed = run_report.get("status") == "PASSED"
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Runner",
                "status": "success" if passed else "error",
                "title": "执行与证据采集完成" if passed else "执行与证据采集遇到问题",
                "detail": run_report.get("summary", ""),
                "session_id": session_id,
            }
        )

    @staticmethod
    def _build_user_prompt(runner_input: Mapping[str, Any]) -> str:
        return json.dumps(dict(runner_input), ensure_ascii=False, indent=2)
