from __future__ import annotations

import json
import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .harness_engine import HarnessEngine

RUNNER_SYSTEM_PROMPT = (
    "You are Runner Agent in a five-agent Harness workflow. "
    "Your only responsibility is execution and evidence collection.\n\n"
    "You may use only the provided execution tools to run the commands and smoke checks supplied by the Harness input.\n"
    "Do not modify source code. Do not judge final acceptance.\n"
    "Write artifacts only under .harness/**, logs/**, screenshots/**, or tmp/**.\n"
    "After collecting evidence, return exactly one strict JSON RunReport object with these fields:\n"
    "schema_version, task_id, round_id, status, started_at, finished_at, duration_sec, commands, dev_server, browser_tests, artifacts, cleanup, errors, summary.\n"
    "Use status values from the spec: PASSED, FAILED, PARTIAL, TIMEOUT, SKIPPED, or INFRA_ERROR."
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


def _runner_input_commands(runner_input: Mapping[str, Any]) -> List[str]:
    commands: List[str] = []
    for item in (runner_input.get("test_commands") or []):
        if isinstance(item, Mapping):
            cmd = str(item.get("cmd") or item.get("command") or "").strip()
        else:
            cmd = str(item).strip()
        if cmd:
            commands.append(cmd)
    dev_server = runner_input.get("dev_server") if isinstance(runner_input.get("dev_server"), Mapping) else {}
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
                    "name": str(item.get("name") or f"cmd_{index}").strip() or f"cmd_{index}",
                    "cmd": command,
                    "timeout_sec": int(item.get("timeout_sec") or 120),
                    "required": bool(item.get("required", index == 1)),
                }
            )
        else:
            command = str(item).strip()
            if command:
                specs.append({"name": f"cmd_{index}", "cmd": command, "timeout_sec": 120, "required": index == 1})
    return specs


async def _run_shell_command(command: str, *, cwd: Path, timeout_sec: int) -> Dict[str, Any]:
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
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        await process.wait()
        stdout, stderr = b"", b"Command timed out"
    finished = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "cmd": command,
        "exit_code": -1 if timed_out else int(process.returncode or 0),
        "status": "TIMEOUT" if timed_out else ("PASSED" if process.returncode == 0 else "FAILED"),
        "started_at": started,
        "finished_at": finished,
        "duration_sec": round(time.time() - started_ts, 3),
        "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
        "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
    }


def _normalize_run_report(raw_obj: Optional[Dict[str, Any]], runner_input: Mapping[str, Any], harness: HarnessEngine, *, started_at: Optional[str] = None, finished_at: Optional[str] = None, duration_sec: Optional[float] = None) -> Dict[str, Any]:
    source: Dict[str, Any] = dict(raw_obj or {})
    plan_contract_raw = runner_input.get("plan_contract")
    plan_contract: Dict[str, Any] = dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    default_status = str(source.get("status") or "FAILED").upper()
    if default_status not in {"PASSED", "FAILED", "PARTIAL", "TIMEOUT", "SKIPPED", "INFRA_ERROR"}:
        default_status = "FAILED"
    run_dir = str(source.get("run_dir") or runner_input.get("run_dir") or "")
    artifacts = source.get("artifacts") if isinstance(source.get("artifacts"), Mapping) else {}
    report = {
        "schema_version": str(source.get("schema_version") or "1.0"),
        "task_id": str(source.get("task_id") or runner_input.get("task_id") or plan_contract.get("task_id") or "task_runtime_001"),
        "round_id": int(source.get("round_id") or runner_input.get("round_id") or 1),
        "status": default_status,
        "started_at": str(source.get("started_at") or started_at or ""),
        "finished_at": str(source.get("finished_at") or finished_at or ""),
        "duration_sec": float(source.get("duration_sec") or duration_sec or 0.0),
        "commands": _normalize_list(source.get("commands")),
        "dev_server": source.get("dev_server") if isinstance(source.get("dev_server"), Mapping) else {},
        "browser_tests": _normalize_list(source.get("browser_tests")),
        "artifacts": {
            "run_dir": run_dir,
            "screenshots": _normalize_list(artifacts.get("screenshots")),
            "traces": _normalize_list(artifacts.get("traces")),
            "logs": _normalize_list(artifacts.get("logs")),
            "browser_console": str(artifacts.get("browser_console") or ""),
        },
        "cleanup": source.get("cleanup") if isinstance(source.get("cleanup"), Mapping) else {
            "browser_closed": False,
            "dev_server_stopped": False,
            "orphan_processes_killed": [],
        },
        "errors": _normalize_list(source.get("errors")),
        "summary": str(source.get("summary") or ""),
    }
    report["display_summary"] = harness.display_summary_for_output("Runner", report)
    return report


def _fallback_run_report(runner_input: Mapping[str, Any], error_message: str, harness: HarnessEngine, *, started_at: Optional[str] = None, finished_at: Optional[str] = None, duration_sec: Optional[float] = None) -> Dict[str, Any]:
    plan_contract_raw = runner_input.get("plan_contract")
    plan_contract: Dict[str, Any] = dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    report = {
        "schema_version": "1.0",
        "task_id": str(runner_input.get("task_id") or plan_contract.get("task_id") or "task_runtime_001"),
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
        self.last_run_report: Dict[str, Any] = {}

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def _run_controlled_commands(
        self,
        runner_input: Mapping[str, Any],
        *,
        started_at: str,
        started_ts: float,
    ) -> Dict[str, Any]:
        workspace = Path(str(runner_input.get("workspace") or ".")).expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        run_dir = str(runner_input.get("run_dir") or ".harness/runs/run_001")
        log_dir = workspace / run_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        command_specs = _runner_command_specs(runner_input)
        allowed_commands = _runner_input_commands(runner_input)
        commands: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for spec in command_specs:
            command = str(spec.get("cmd") or "")
            if not self.harness.command_allowed(command, runner_input_commands=allowed_commands):
                errors.append({
                    "type": "HARNESS_POLICY_VIOLATION",
                    "root_category": "HARNESS",
                    "message": f"Blocked command outside Runner input contract: {command}",
                })
                commands.append({**spec, "status": "BLOCKED", "exit_code": None})
                if spec.get("required", True):
                    break
                continue

            result = await _run_shell_command(
                command,
                cwd=workspace,
                timeout_sec=int(spec.get("timeout_sec") or 120),
            )
            log_path = log_dir / f"{str(spec.get('name') or 'command').replace('/', '_')}.log"
            log_path.write_text(
                "\n".join([
                    f"$ {command}",
                    f"status: {result['status']}",
                    f"exit_code: {result['exit_code']}",
                    "",
                    "[stdout]",
                    str(result.get("stdout") or ""),
                    "",
                    "[stderr]",
                    str(result.get("stderr") or ""),
                ]),
                encoding="utf-8",
            )
            command_record = {
                **spec,
                "status": result["status"],
                "exit_code": result["exit_code"],
                "duration_sec": result["duration_sec"],
                "stdout_tail": str(result.get("stdout") or "")[-2000:],
                "stderr_tail": str(result.get("stderr") or "")[-2000:],
                "log": str(log_path.relative_to(workspace)).replace("\\", "/"),
            }
            commands.append(command_record)
            if result["status"] != "PASSED":
                errors.append({
                    "type": "RUNNER_TIMEOUT" if result["status"] == "TIMEOUT" else "PRODUCT_BUILD_ERROR",
                    "root_category": "RUNNER" if result["status"] == "TIMEOUT" else "PRODUCT",
                    "message": str(result.get("stderr") or result.get("stdout") or f"Command failed: {command}")[-2000:],
                    "command": command,
                })
                if spec.get("required", True):
                    break

        required_failed = any(
            command.get("required", True) and command.get("status") not in {"PASSED"}
            for command in commands
        )
        status = "PASSED" if command_specs and not required_failed and not errors else ("SKIPPED" if not command_specs else "FAILED")
        finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        report = {
            "schema_version": "1.0",
            "task_id": str(runner_input.get("task_id") or "task_runtime_001"),
            "round_id": int(runner_input.get("round_id") or 1),
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": round(time.time() - started_ts, 3),
            "commands": commands,
            "dev_server": {},
            "browser_tests": [],
            "artifacts": {
                "run_dir": run_dir,
                "screenshots": [],
                "traces": [],
                "logs": [str(path.relative_to(workspace)).replace("\\", "/") for path in sorted(log_dir.glob("*.log"))],
                "browser_console": "",
            },
            "cleanup": {
                "browser_closed": True,
                "dev_server_stopped": True,
                "orphan_processes_killed": [],
            },
            "errors": errors,
            "summary": "Runner executed Harness-provided commands." if command_specs else "No Runner commands were provided.",
        }
        report["display_summary"] = self.harness.display_summary_for_output("Runner", report)
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
            {"role": "system", "content": RUNNER_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(runner_input)},
        ]

        raw_content = ""
        tool_step = 0
        run_report: Dict[str, Any] = {}
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        started_ts = time.time()

        deterministic_runner = str(runner_input.get("execution_mode") or "").strip().lower() == "harness_controlled"
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
                                tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            if tc.get("id"):
                                tool_calls[idx]["id"] = tc["id"]
                            if "function" in tc:
                                if tc["function"].get("name"):
                                    tool_calls[idx]["function"]["name"] += tc["function"]["name"]
                                if tc["function"].get("arguments"):
                                    tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]
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

                if tool_name == "bash":
                    command = str(tool_args.get("command") or "").strip()
                    if not self.harness.command_allowed(command, runner_input_commands=allowed_commands):
                        tool_args = {}
                        tool_name = "bash"
                        tool_result = f"Blocked command outside Runner input contract: {command}"
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
                        finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
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
                    if tool_name in (self.skill_manager.skills or {}):
                        skill = self.skill_manager.skills[tool_name]
                        result = await skill.execute(**tool_args)
                        tool_result = str(result.content) if result.success else f"Error: {result.error}"
                        success = result.success
                    else:
                        tool_result = f"Tool {tool_name!r} not available for Runner"
                except Exception as exc:
                    tool_result = str(exc)

                yield self._sse(
                    {
                        "type": "task_complete",
                        "task_id": task_id,
                        "success": success,
                        "content": tool_result[:400] + "..." if len(tool_result) > 400 else tool_result,
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
