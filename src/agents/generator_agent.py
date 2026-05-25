import hashlib
import asyncio
import json
from utils.json_utils import safe_loads
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional, Tuple

from loguru import logger

from .harness_engine import HarnessEngine

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

_BINARY_FILE_SUFFIXES = {
    ".pptx",
    ".ppt",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".zip",
    ".gz",
    ".tar",
    ".mp4",
    ".mov",
    ".mp3",
    ".wav",
}


def _strip_provider_thinking(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", str(text or ""), flags=re.IGNORECASE).lstrip()


def _read_utf8_text_for_tool(path: Path, normalized_path: str) -> Tuple[bool, str]:
    try:
        size = path.stat().st_size
    except Exception:
        size = 0
    suffix = path.suffix.lower()
    if suffix in _BINARY_FILE_SUFFIXES:
        return False, (
            f"Binary artifact {normalized_path} ({size} bytes) cannot be displayed or edited as UTF-8 text. "
            "Use Runner artifact checks for this file instead of text read/replace operations."
        )
    try:
        return True, path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, (
            f"File {normalized_path} is not valid UTF-8 text ({size} bytes). "
            "Treat it as a binary artifact and verify existence/format with Runner commands."
        )


def _example_path_for_policy(allowed: List[str]) -> str:
    for item in allowed:
        path = str(item or "").strip().replace("\\", "/")
        if not path:
            continue
        if not any(token in path for token in ("*", "?", "[")) and not path.endswith("/"):
            return path
    for item in allowed:
        path = str(item or "").strip().replace("\\", "/")
        if path in {"*.pptx", "**/*.pptx"}:
            return "presentation.pptx"
        if path in {"*.docx", "**/*.docx"}:
            return "document.docx"
        if path in {"*.xlsx", "**/*.xlsx"}:
            return "workbook.xlsx"
        if path in {"*.pdf", "**/*.pdf"}:
            return "document.pdf"
        if path in {"*.py", "**/*.py"}:
            return "script.py"
        if path in {"*.html", "**/*.html"}:
            return "index.html"
        if path.startswith("docs/"):
            return "docs/output.md"
        if path.startswith("output/"):
            return "output/artifact.md"
    return "output.txt"


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


def _normalize_string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _unique_paths(*groups: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for group in groups:
        for item in group:
            path = str(item).strip()
            if not path or path in seen:
                continue
            seen.add(path)
            ordered.append(path)
    return ordered


def _normalize_patch_operations(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    operations: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            operations.append(dict(item))
    return operations


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
        parsed = safe_loads(text)
    except Exception as exc:
        return {}, f"Malformed tool arguments: {exc}"
    if not isinstance(parsed, Mapping):
        return {}, "Malformed tool arguments: expected a JSON object."
    return dict(parsed), None


def _invalid_tool_call_feedback(
    error: str,
    *,
    force_patch_envelope: bool = False,
    example_path: str = "output.txt",
) -> str:
    base = (
        f"{error} Retry the file tool with one valid JSON object only. "
        f"Use workspace-relative paths allowed by PlanContract, such as '{example_path}', never absolute paths, "
        "and escape embedded quotes or newlines inside content/file_text. "
        "If you need to inspect the workspace, use command='view' with path='.'."
    )
    if not force_patch_envelope:
        return base
    return (
        base
        + " Do not call the file tool again for this file if JSON escaping keeps failing. "
        "Instead, return the final PatchResult now with patch_envelope.patch_type='file_replacement' and "
        "include complete operation content for every remaining file that still needs to be created or updated."
    )


def _is_invalid_tool_arguments_api_error(error: Exception) -> bool:
    text = str(error)
    return "invalid function arguments json string" in text.lower()


def _provider_invalid_tool_feedback(error: Exception) -> str:
    return _invalid_tool_call_feedback(
        "Provider rejected the previous tool call before execution because the tool arguments were not valid JSON."
    )


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
        self.system_prompt = self.harness.load_agent_prompt("Generator", GENERATOR_SYSTEM_PROMPT)
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
        actual_created_files = sorted(after_files - before_files)
        actual_deleted_files = sorted(before_files - after_files)
        actual_changed_files = sorted(
            path for path in before_files & after_files if before_snapshot.get(path) != after_snapshot.get(path)
        )
        source = raw_obj or {}
        source_created_files = _normalize_string_list(source.get("created_files"))
        source_changed_files = _normalize_string_list(source.get("changed_files"))
        source_deleted_files = _normalize_string_list(source.get("deleted_files"))
        created_files = _unique_paths(actual_created_files, source_created_files)
        changed_files = _unique_paths(actual_changed_files, source_changed_files)
        deleted_files = _unique_paths(actual_deleted_files, source_deleted_files)
        touched_files = _unique_paths(created_files, changed_files)
        patch_envelope_raw = source.get("patch_envelope") if isinstance(source.get("patch_envelope"), Mapping) else {}
        patch_operations = _normalize_patch_operations(patch_envelope_raw.get("operations"))
        envelope_changed_files = _normalize_string_list(patch_envelope_raw.get("changed_files"))
        envelope_changed_files = _unique_paths(
            touched_files,
            envelope_changed_files,
            [str(op.get("path") or "").strip() for op in patch_operations if isinstance(op, Mapping)],
        )
        patch_result = {
            "schema_version": str(source.get("schema_version") or "1.0"),
            "task_id": str(source.get("task_id") or plan_contract.get("task_id") or "task_runtime_001"),
            "round_id": int(source.get("round_id") or generator_input.get("round_id") or 1),
            "mode": str(source.get("mode") or generator_input.get("mode") or ("repair" if int(generator_input.get("round_id") or 1) > 1 else "initial")),
            "changed_files": changed_files,
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
                "schema_version": str(patch_envelope_raw.get("schema_version") or source.get("schema_version") or "1.0"),
                "task_id": str(patch_envelope_raw.get("task_id") or source.get("task_id") or plan_contract.get("task_id") or "task_runtime_001"),
                "round_id": int(patch_envelope_raw.get("round_id") or source.get("round_id") or generator_input.get("round_id") or 1),
                "patch_type": str(patch_envelope_raw.get("patch_type") or "file_replacement"),
                "operations": patch_operations or [{"op": "file_replacement", "path": path} for path in touched_files],
                "changed_files": envelope_changed_files,
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
        plan_contract_raw = generator_input.get("plan_contract")
        constraints_raw = generator_input.get("harness_constraints")
        plan_contract = dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
        constraints = dict(constraints_raw) if isinstance(constraints_raw, Mapping) else {}
        allowed = list(plan_contract.get("allowed_files") or constraints.get("allowed_write_paths") or [])
        forbidden = list(plan_contract.get("forbidden_files") or constraints.get("forbidden_write_paths") or [])
        return [str(item) for item in allowed], [str(item) for item in forbidden]

    def _render_directory_view(self, full_path: Path, *, workspace: Path) -> str:
        target = "." if full_path == workspace else str(full_path.relative_to(workspace)).replace("\\", "/")
        entries: List[str] = []
        try:
            for child in sorted(full_path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                rel = str(child.relative_to(workspace)).replace("\\", "/")
                if any(rel == prefix[:-1] or rel.startswith(prefix) for prefix in _SKIP_PREFIXES):
                    continue
                suffix = "/" if child.is_dir() else ""
                entries.append(f"- {rel}{suffix}")
                if len(entries) >= 80:
                    break
        except Exception as exc:
            return f"Failed to inspect directory {target}: {exc}"
        if not entries:
            return f"Directory listing for {target}:\n(empty)"
        return f"Directory listing for {target}:\n" + "\n".join(entries)

    def _safe_workspace_file(
        self,
        raw_path: str,
        generator_input: Mapping[str, Any],
        *,
        writing: bool,
    ) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
        path_text = str(raw_path or "").strip()
        allowed, forbidden = self._path_policy(generator_input)
        example_path = _example_path_for_policy(allowed)
        if not path_text:
            return None, None, f"Missing path. Use a workspace-relative file path allowed by PlanContract, such as '{example_path}'."
        workspace = self._workspace_path()
        candidate = Path(path_text).expanduser()
        if candidate.is_absolute():
            resolved_candidate = candidate.resolve(strict=False)
            try:
                path_text = str(resolved_candidate.relative_to(workspace)).replace("\\", "/") or "."
            except ValueError:
                return None, None, f"Path must be workspace-relative. Use a path like '{example_path}', not an absolute path."
        else:
            path_text = str(Path(path_text)).replace("\\", "/") or "."
        if writing and path_text == ".":
            return None, None, "Path must point to a file, not the workspace root '.'."
        if writing and not self.harness.is_path_allowed(path_text, allowed, forbidden, workspace):
            return None, None, f"Path is outside Generator allowed_files or forbidden by policy: {path_text}"
        full_path = (workspace / path_text).resolve(strict=False)
        try:
            full_path.relative_to(workspace)
        except ValueError:
            return None, None, "Path escapes workspace."
        normalized_path = "." if full_path == workspace else str(full_path.relative_to(workspace)).replace("\\", "/")
        return full_path, normalized_path, None

    async def _execute_harness_file_tool(self, tool_args: Mapping[str, Any], generator_input: Mapping[str, Any]) -> Tuple[bool, str]:
        command = str(tool_args.get("command") or "").strip().lower()
        raw_path = str(tool_args.get("path") or tool_args.get("file_path") or "").strip()
        writing = command in {"create", "write", "write_file", "str_replace", "insert"}
        full_path, normalized_path, error = self._safe_workspace_file(raw_path, generator_input, writing=writing)
        if error or full_path is None or normalized_path is None:
            return False, error or "Invalid path."

        if command in {"view", "read", "read_file", "ls", "list", "list_dir"}:
            if full_path.exists() and full_path.is_dir():
                return True, self._render_directory_view(full_path, workspace=self._workspace_path())
            if not full_path.exists() or not full_path.is_file():
                return False, f"File does not exist: {normalized_path}"
            is_text, text = _read_utf8_text_for_tool(full_path, normalized_path)
            if not is_text:
                return True, text
            view_range = tool_args.get("view_range")
            if isinstance(view_range, list) and len(view_range) == 2:
                start = max(1, int(view_range[0]))
                end = max(start, int(view_range[1]))
                lines = text.splitlines()
                text = "\n".join(lines[start - 1:end])
            return True, text

        if command in {"create", "write", "write_file"}:
            content = _strip_provider_thinking(str(tool_args.get("file_text") if tool_args.get("file_text") is not None else tool_args.get("content") or ""))
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return True, f"Wrote {normalized_path} ({len(content)} chars)."

        if command == "str_replace":
            if not full_path.exists() or not full_path.is_file():
                return False, f"File does not exist: {normalized_path}"
            old_str_val = tool_args.get("old_str") if tool_args.get("old_str") is not None else tool_args.get("old_text")
            new_str_val = tool_args.get("new_str") if tool_args.get("new_str") is not None else tool_args.get("new_text")
            old_str = str(old_str_val or "")
            new_str = _strip_provider_thinking(str(new_str_val or ""))
            if not old_str:
                return False, "old_str is required for str_replace."
            is_text, text = _read_utf8_text_for_tool(full_path, normalized_path)
            if not is_text:
                return False, text
            occurrences = text.count(old_str)
            if occurrences == 1:
                full_path.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
                return True, f"Replaced text in {normalized_path}."
            if occurrences == 0:
                import re
                tokens = re.split(r'(\s+)', old_str)
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
                    matches = list(re.finditer(pattern, text))
                    if len(matches) == 1:
                        m = matches[0]
                        new_content = text[:m.start()] + new_str + text[m.end():]
                        full_path.write_text(new_content, encoding="utf-8")
                        return True, f"Replaced text in {normalized_path} (using fuzzy whitespace match)."
                    else:
                        if getattr(self, "vllm_client", None) is not None:
                            logger.info(f"Fuzzy match failed for {normalized_path}, attempting LLM extraction fallback.")
                            messages = [
                                {"role": "system", "content": "You are a precise code patch tool. Given the original file content and the intended old/new text snippet, return the COMPLETELY MODIFIED file content. Return ONLY the new file content. Do not output markdown backticks, explanations, or any other text."},
                                {"role": "user", "content": f"=== ORIGINAL FILE ===\n{text}\n\n=== INTENDED OLD TEXT TO REPLACE ===\n{old_str}\n\n=== REPLACEMENT TEXT ===\n{new_str}\n\nReturn the fully updated file content directly without any backticks or formatting. It must be valid code."}
                            ]
                            try:
                                response = await self.vllm_client.chat_completion(messages, temperature=0.1)
                                if isinstance(response, dict) and response.get("choices"):
                                    new_content = response["choices"][0]["message"]["content"]
                                    if new_content.startswith("```"):
                                        lines = new_content.splitlines()
                                        if lines and lines[0].startswith("```"): lines = lines[1:]
                                        if lines and lines[-1].startswith("```"): lines = lines[:-1]
                                        new_content = "\n".join(lines) + "\n"
                                    full_path.write_text(new_content, encoding="utf-8")
                                    return True, f"Replaced text in {normalized_path} (using LLM extraction fallback)."
                            except Exception as llm_exc:
                                logger.warning(f"LLM extraction fallback failed: {llm_exc}")
                        
                        return False, f"old_str must match exactly once; found 0 exact and {len(matches)} fuzzy matches."
                except Exception:
                    pass
            return False, f"old_str must match exactly once; found {occurrences} matches."

        if command == "insert":
            if not full_path.exists() or not full_path.is_file():
                return False, f"File does not exist: {normalized_path}"
            insert_line = int(tool_args.get("insert_line") or 0)
            new_str = _strip_provider_thinking(str(tool_args.get("new_str") or tool_args.get("content") or tool_args.get("file_text") or ""))
            is_text, text = _read_utf8_text_for_tool(full_path, normalized_path)
            if not is_text:
                return False, text
            lines = text.splitlines()
            index = max(0, min(insert_line, len(lines)))
            lines[index:index] = new_str.splitlines()
            full_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True, f"Inserted text into {normalized_path}."

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
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_user_prompt(generator_input)},
        ]

        before_snapshot = self._snapshot_workspace_state()
        raw_content = ""
        tool_step = 0
        raw_obj: Optional[Dict[str, Any]] = None
        invalid_tool_call_count = 0
        incomplete_json_retry_count = 0
        transient_model_error_count = 0
        allowed_paths, _ = self._path_policy(generator_input)
        example_path = _example_path_for_policy(allowed_paths)

        for iteration in range(max_iterations):
            assistant_message: Dict[str, Any] = {"role": "assistant", "content": ""}
            tool_calls: List[Dict[str, Any]] = []
            try:
                stream = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=generator_tools if generator_tools else None,
                    temperature=0.1,
                    max_tokens=8000,
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
                if _is_invalid_tool_arguments_api_error(exc):
                    invalid_tool_call_count += 1
                    feedback = _invalid_tool_call_feedback(
                        "Provider rejected the previous tool call before execution because the tool arguments were not valid JSON.",
                        force_patch_envelope=invalid_tool_call_count >= 2,
                        example_path=example_path,
                    )
                    yield self._sse(
                        {
                            "type": "agent_step",
                            "role": "Generator",
                            "status": "error",
                            "title": "验证遇到问题",
                            "detail": feedback,
                            "session_id": session_id,
                        }
                    )
                    if assistant_message.get("content"):
                        messages.append({"role": "assistant", "content": assistant_message["content"]})
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Harness rejected the previous response before tool execution. {feedback}",
                        }
                    )
                    continue
                transient_model_error_count += 1
                if transient_model_error_count < 3:
                    yield self._sse(
                        {
                            "type": "agent_step",
                            "role": "Generator",
                            "status": "error",
                            "title": "Generator 模型调用失败，正在重试",
                            "detail": str(exc) or "transient model stream error",
                            "session_id": session_id,
                        }
                    )
                    await asyncio.sleep(min(2 * transient_model_error_count, 5))
                    continue
                raw_obj = {
                    "schema_version": "1.0",
                    "task_id": str(
                        generator_input.get("task_id")
                        or (
                            dict(generator_input.get("plan_contract") or {}).get(
                                "task_id"
                            )
                            if isinstance(
                                generator_input.get("plan_contract"), Mapping
                            )
                            else ""
                        )
                        or "task_runtime_001"
                    ),
                    "round_id": int(generator_input.get("round_id") or 1),
                    "mode": str(generator_input.get("mode") or "initial"),
                    "changed_files": [],
                    "created_files": [],
                    "deleted_files": [],
                    "summary": "Generator model call failed before producing file edits.",
                    "implementation_notes": [],
                    "commands_to_run": [],
                    "risk_points": [str(exc) or "transient model stream error"],
                    "patch_envelope": {
                        "schema_version": "1.0",
                        "operations": [],
                        "changed_files": [],
                    },
                    "needs_replan": True,
                    "replan_reason": (
                        "Generator model call failed repeatedly before producing "
                        "file edits; retry the generation step."
                    ),
                }
                break

            if not tool_calls:
                raw_obj = _find_first_json_object(assistant_message["content"])
                if raw_obj is not None:
                    break
                if assistant_message.get("content"):
                    incomplete_json_retry_count += 1
                    messages.append({"role": "assistant", "content": assistant_message["content"]})
                    if incomplete_json_retry_count < 3:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "The previous response was not a complete valid JSON PatchResult object. "
                                    "Return the full PatchResult again as one complete JSON object only, with all braces closed. "
                                    "Do not call tools unless you still need to write missing files."
                                ),
                            }
                        )
                        continue
                break

            sanitized_tool_calls: List[Dict[str, Any]] = []
            tool_messages: List[Dict[str, Any]] = []
            correction_messages: List[Dict[str, str]] = []

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
                    invalid_tool_call_count += 1
                    tool_result = _invalid_tool_call_feedback(
                        parse_error,
                        force_patch_envelope=invalid_tool_call_count >= 2,
                        example_path=example_path,
                    )
                    correction_messages.append(
                        {
                            "role": "user",
                            "content": f"Harness rejected the previous {tool_name} tool call. {tool_result}",
                        }
                    )
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
                    sanitized_tool_calls.append(
                        {
                            "id": tc.get("id", "unknown"),
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_args, ensure_ascii=False),
                            },
                        }
                    )
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", "unknown"),
                            "name": tool_name,
                            "content": tool_result[:8000],
                        }
                    )

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

            if sanitized_tool_calls:
                history_message = dict(assistant_message)
                history_message["tool_calls"] = sanitized_tool_calls
                messages.append(history_message)
                messages.extend(tool_messages)
            elif assistant_message.get("content"):
                messages.append({"role": "assistant", "content": assistant_message["content"]})

            if correction_messages:
                messages.extend(correction_messages)

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
