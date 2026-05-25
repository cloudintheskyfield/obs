import hashlib
import asyncio
import json
from utils.json_utils import safe_loads
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional, Tuple

from loguru import logger

from .harness_engine import HarnessEngine
from .base_agent import BaseAgent

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


class GeneratorAgent(BaseAgent):
    def __init__(self, vllm_client: Any, skill_manager: Any) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt("Generator", "")
        self.last_patch_result: Dict[str, Any] = {}

    