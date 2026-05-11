import hashlib
import json
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional, Tuple

from loguru import logger

from .harness_engine import HarnessEngine

GENERATOR_SYSTEM_PROMPT = (
    "You are Generator Agent in a five-agent Harness workflow. "
    "Your only responsibility is scoped code editing.\n\n"
    "Read the supplied PlanContract, optional SearchReport findings, and optional repair instruction. "
    "Use only the provided file editing tool to modify files inside the allowed workspace scope. "
    "Always use workspace-relative paths from PlanContract.allowed_files or harness_constraints.allowed_write_paths; never use absolute paths. "
    "Read required_files_to_inspect before writing when those files exist. "
    "If the task asks to create, generate, or implement an artifact, you must call the file editing tool and create or modify the planned file; an empty patch_envelope.operations array is invalid for implementation work. "
    "Do not run commands. Do not browse. Do not search. Do not judge final acceptance.\n"
    "Return exactly one strict JSON PatchResult object with these fields:\n"
    "schema_version, task_id, round_id, mode, changed_files, created_files, deleted_files, summary, implementation_notes, commands_to_run, risk_points, patch_envelope, needs_replan, replan_reason.\n"
    "If the plan is impossible or unsafe within scope, set needs_replan = true and explain replan_reason."
)

_SKIP_PREFIXES = (
    ".git/",
    "node_modules/",
    "dist/",
    "build/",
    ".harness/",
    "logs/",
    "screenshots/",
    "tmp/",
    "__pycache__/",
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


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_command_specs(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    commands: List[Dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, Mapping):
            cmd = str(item.get("cmd") or item.get("command") or "").strip()
            if not cmd:
                continue
            commands.append(
                {
                    "name": str(item.get("name") or f"cmd_{index}").strip() or f"cmd_{index}",
                    "cmd": cmd,
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
            continue
        cmd = str(item).strip()
        if cmd:
            commands.append({"name": f"cmd_{index}", "cmd": cmd, "reason": ""})
    return commands


def _parse_tool_arguments(raw_args: str) -> Tuple[Dict[str, Any], Optional[str]]:
    text = (raw_args or "").strip()
    if not text:
        return {}, None
    try:
        parsed = json.loads(text)
    except Exception as exc:
        return {}, f"Malformed tool arguments: {exc}"
    if not isinstance(parsed, Mapping):
        return {}, "Malformed tool arguments: expected a JSON object."
    return dict(parsed), None


def _harness_file_tool_schema(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "description": (
            "Harness-scoped file tool for Generator. Use workspace-relative paths only. "
            "Supported command values: view, create, write, str_replace, insert."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "read", "read_file", "create", "write", "write_file", "str_replace", "insert"],
                    "description": "File operation to perform.",
                },
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "file_path": {"type": "string", "description": "Workspace-relative file path alias."},
                "content": {"type": "string", "description": "Content for create/write operations."},
                "file_text": {"type": "string", "description": "Content for create/write operations."},
                "old_str": {"type": "string", "description": "Exact text to replace for str_replace."},
                "new_str": {"type": "string", "description": "Replacement text for str_replace or inserted text for insert."},
                "insert_line": {"type": "integer", "description": "1-based line number after which to insert new_str."},
                "view_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Optional 1-based inclusive line range for view.",
                },
            },
            "required": ["command"],
        },
    }


class GeneratorAgent:
    def __init__(self, vllm_client: Any, skill_manager: Any) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.last_patch_result: Dict[str, Any] = {}

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _workspace_path(self) -> Path:
        workspace = "."
        if self.skill_manager is not None and hasattr(self.skill_manager, "get_current_workspace"):
            try:
                workspace = self.skill_manager.get_current_workspace()
            except Exception:
                workspace = "."
        return Path(workspace).expanduser().resolve()

    def _snapshot_workspace_state(self, max_files: int = 400) -> Dict[str, str]:
        workspace = self._workspace_path()
        snapshot: Dict[str, str] = {}
        try:
            for path in workspace.rglob("*"):
                if len(snapshot) >= max_files:
                    break
                if not path.is_file():
                    continue
                rel = str(path.relative_to(workspace)).replace("\\", "/")
                if rel.startswith(_SKIP_PREFIXES):
                    continue
                try:
                    stat = path.stat()
                    if stat.st_size > 512_000:
                        continue
                    content = path.read_bytes()
                except Exception:
                    continue
                snapshot[rel] = hashlib.sha1(content).hexdigest()
        except Exception:
            return {}
        return snapshot

    def _build_patch_result(
        self,
        before_snapshot: Dict[str, str],
        after_snapshot: Dict[str, str],
        generator_input: Mapping[str, Any],
        raw_obj: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        plan_contract_raw = generator_input.get("plan_contract")
        plan_contract: Dict[str, Any] = dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
        before_files = set(before_snapshot)
        after_files = set(after_snapshot)
        created_files = sorted(after_files - before_files)
        deleted_files = sorted(before_files - after_files)
        changed_files = sorted(
            path for path in before_files & after_files if before_snapshot.get(path) != after_snapshot.get(path)
        )
        touched_files = created_files + changed_files
        source = raw_obj or {}
        patch_result = {
            "schema_version": str(source.get("schema_version") or "1.0"),
            "task_id": str(source.get("task_id") or plan_contract.get("task_id") or "task_runtime_001"),
            "round_id": int(source.get("round_id") or generator_input.get("round_id") or 1),
            "mode": str(source.get("mode") or generator_input.get("mode") or ("repair" if int(generator_input.get("round_id") or 1) > 1 else "initial")),
            "changed_files": touched_files,
            "created_files": created_files,
            "deleted_files": deleted_files,
            "summary": str(
                source.get("summary")
                or f"Created {len(created_files)} files, changed {len(changed_files)} files, deleted {len(deleted_files)} files."
            ),
            "implementation_notes": _normalize_string_list(source.get("implementation_notes")),
            "commands_to_run": _normalize_command_specs(source.get("commands_to_run"))
            or _normalize_command_specs(plan_contract.get("test_commands")),
            "risk_points": _normalize_string_list(source.get("risk_points")),
            "patch_envelope": {
                "schema_version": "1.0",
                "task_id": str(source.get("task_id") or plan_contract.get("task_id") or "task_runtime_001"),
                "round_id": int(source.get("round_id") or generator_input.get("round_id") or 1),
                "patch_type": "file_replacement",
                "operations": [{"op": "file_replacement", "path": path} for path in touched_files],
                "changed_files": touched_files,
            },
            "needs_replan": bool(source.get("needs_replan", False)),
            "replan_reason": str(source.get("replan_reason") or ""),
        }
        patch_result["display_summary"] = self.harness.display_summary_for_output("Generator", patch_result)
        return patch_result

    def _resolve_skill_name(self, tool_name: str) -> str:
        if self.skill_manager is not None and hasattr(self.skill_manager, "resolve_skill_name_for_tool"):
            try:
                resolved = self.skill_manager.resolve_skill_name_for_tool(tool_name)
            except Exception:
                resolved = None
            if resolved:
                return str(resolved)
        return tool_name

    def _generator_tool_defs(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        existing = {str(tool.get("name") or ""): dict(tool) for tool in self.harness.filter_tools_for_role("Generator", tools)}
        for name in ("filesystem", "file-manager"):
            existing[name] = _harness_file_tool_schema(name)
        return [existing[name] for name in sorted(existing) if name]

    def _path_policy(self, generator_input: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
        plan_contract = generator_input.get("plan_contract") if isinstance(generator_input.get("plan_contract"), Mapping) else {}
        constraints = generator_input.get("harness_constraints") if isinstance(generator_input.get("harness_constraints"), Mapping) else {}
        allowed = list(plan_contract.get("allowed_files") or constraints.get("allowed_write_paths") or [])
        forbidden = list(plan_contract.get("forbidden_files") or constraints.get("forbidden_write_paths") or [])
        return [str(item) for item in allowed], [str(item) for item in forbidden]

    def _safe_workspace_file(self, raw_path: str, generator_input: Mapping[str, Any], *, writing: bool) -> Tuple[Optional[Path], Optional[str]]:
        path_text = str(raw_path or "").strip()
        if not path_text:
            return None, "Missing path."
        if Path(path_text).is_absolute():
            return None, "Path must be workspace-relative."
        workspace = self._workspace_path()
        allowed, forbidden = self._path_policy(generator_input)
        if writing and not self.harness.is_path_allowed(path_text, allowed, forbidden, workspace):
            return None, f"Path is outside Generator allowed_files or forbidden by policy: {path_text}"
        full_path = (workspace / path_text).resolve(strict=False)
        try:
            full_path.relative_to(workspace)
        except ValueError:
            return None, "Path escapes workspace."
        return full_path, None

    async def _execute_harness_file_tool(self, tool_args: Mapping[str, Any], generator_input: Mapping[str, Any]) -> Tuple[bool, str]:
        command = str(tool_args.get("command") or "").strip().lower()
        raw_path = str(tool_args.get("path") or tool_args.get("file_path") or "").strip()
        writing = command in {"create", "write", "write_file", "str_replace", "insert"}
        full_path, error = self._safe_workspace_file(raw_path, generator_input, writing=writing)
        if error or full_path is None:
            return False, error or "Invalid path."

        if command in {"view", "read", "read_file"}:
            if not full_path.exists() or not full_path.is_file():
                return False, f"File does not exist: {raw_path}"
            text = full_path.read_text(encoding="utf-8")
            view_range = tool_args.get("view_range")
            if isinstance(view_range, list) and len(view_range) == 2:
                start = max(1, int(view_range[0]))
                end = max(start, int(view_range[1]))
                lines = text.splitlines()
                text = "\n".join(lines[start - 1:end])
            return True, text

        if command in {"create", "write", "write_file"}:
            content = str(tool_args.get("file_text") if tool_args.get("file_text") is not None else tool_args.get("content") or "")
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return True, f"Wrote {raw_path} ({len(content)} chars)."

        if command == "str_replace":
            if not full_path.exists() or not full_path.is_file():
                return False, f"File does not exist: {raw_path}"
            old_str = str(tool_args.get("old_str") or "")
            new_str = str(tool_args.get("new_str") or "")
            if not old_str:
                return False, "old_str is required for str_replace."
            text = full_path.read_text(encoding="utf-8")
            occurrences = text.count(old_str)
            if occurrences != 1:
                return False, f"old_str must match exactly once; found {occurrences} matches."
            full_path.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
            return True, f"Replaced text in {raw_path}."

        if command == "insert":
            if not full_path.exists() or not full_path.is_file():
                return False, f"File does not exist: {raw_path}"
            insert_line = int(tool_args.get("insert_line") or 0)
            new_str = str(tool_args.get("new_str") or tool_args.get("content") or tool_args.get("file_text") or "")
            lines = full_path.read_text(encoding="utf-8").splitlines()
            index = max(0, min(insert_line, len(lines)))
            lines[index:index] = new_str.splitlines()
            full_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True, f"Inserted text into {raw_path}."

        return False, f"Unsupported file command: {command}"

    async def generate(
        self,
        session_id: str,
        generator_input: Mapping[str, Any],
        *,
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_iterations: int = 10,
    ) -> AsyncGenerator[str, None]:
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Generator",
                "status": "running",
                "title": "按 PlanContract 修改代码",
                "detail": "仅在受限范围内编辑文件并准备 PatchResult...",
                "session_id": session_id,
            }
        )

        generator_tools = self._generator_tool_defs(tools)
        messages = [
            {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(generator_input)},
        ]

        before_snapshot = self._snapshot_workspace_state()
        raw_content = ""
        tool_step = 0
        raw_obj: Optional[Dict[str, Any]] = None

        for iteration in range(max_iterations):
            assistant_message: Dict[str, Any] = {"role": "assistant", "content": ""}
            tool_calls: List[Dict[str, Any]] = []
            try:
                stream = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=generator_tools if generator_tools else None,
                    temperature=0.1,
                    max_tokens=2400,
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
                                "agent": "generator",
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
                logger.warning(f"GeneratorAgent iteration {iteration} model error: {exc}")
                break

            if not tool_calls:
                raw_obj = _find_first_json_object(assistant_message["content"])
                break

            assistant_message["tool_calls"] = tool_calls
            messages.append(dict(assistant_message))

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                raw_args = tc["function"].get("arguments") or ""
                tool_args, parse_error = _parse_tool_arguments(raw_args)
                resolved_tool_name = self._resolve_skill_name(tool_name)

                tool_step += 1
                task_id = f"generator_step_{tool_step}"
                yield self._sse(
                    {
                        "type": "task_start",
                        "task_id": task_id,
                        "description": f"[Generator] {tool_name}",
                        "skill": tool_name,
                        "action": "tool",
                        "session_id": session_id,
                    }
                )

                tool_result = ""
                success = False
                if parse_error:
                    tool_result = parse_error
                else:
                    try:
                        if resolved_tool_name in {"filesystem", "file-manager"}:
                            success, tool_result = await self._execute_harness_file_tool(tool_args, generator_input)
                        else:
                            result = await self.skill_manager.execute_skill(resolved_tool_name, **tool_args)
                            tool_result = str(result.content) if result.success else f"Error: {result.error}"
                            success = result.success
                    except Exception as exc:
                        tool_result = str(exc)

                yield self._sse(
                    {
                        "type": "task_complete",
                        "task_id": task_id,
                        "success": success,
                        "content": tool_result[:400] + "..." if len(tool_result) > 400 else tool_result,
                        "description": f"[Generator] {tool_name}",
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

        after_snapshot = self._snapshot_workspace_state()
        self.last_patch_result = self._build_patch_result(before_snapshot, after_snapshot, generator_input, raw_obj)
        passed = not bool(self.last_patch_result.get("needs_replan"))
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Generator",
                "status": "success" if passed else "error",
                "title": "PatchResult 已生成" if passed else "Generator 请求重新规划",
                "detail": self.last_patch_result.get("summary", ""),
                "session_id": session_id,
            }
        )

    @staticmethod
    def _build_user_prompt(generator_input: Mapping[str, Any]) -> str:
        payload = dict(generator_input)
        return json.dumps(payload, ensure_ascii=False, indent=2)
