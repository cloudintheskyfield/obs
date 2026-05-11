"""Text Editor Skill - Claude官方文本编辑技能"""
import os
import re
import shutil
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from loguru import logger

from base_skill import BaseSkill, SkillResult


# Extra directories always readable (read-only, no write allowed)
_READONLY_ROOTS: List[Path] = []

def _build_readonly_roots() -> List[Path]:
    """Resolve read-only root directories at import time."""
    roots: List[Path] = []
    skills_env = os.environ.get("SKILLS_DIR")
    if skills_env:
        p = Path(skills_env).resolve()
        if p.exists():
            roots.append(p)
    for candidate in [Path("/app/.claude/skills"), Path("/app/skills")]:
        if candidate.exists():
            roots.append(candidate)
    return roots

_READONLY_ROOTS = _build_readonly_roots()


class TextEditorSkill(BaseSkill):
    """Text Editor Skill - 模拟Claude的文本编辑能力"""
    
    def __init__(self, work_dir: str = "workspace"):
        super().__init__(
            name="str_replace_editor",
            description=(
                "A text editor tool for viewing, creating and editing files. "
                "Commands: view, create, write, append, str_replace, insert, delete, find, undo_edit. "
                "view: read file or directory. "
                "create: create a new file. "
                "write: overwrite a file (creates if missing). "
                "append: append text to file. "
                "str_replace: replace exact text (must be unique). "
                "insert: insert text after a line number. "
                "delete: delete a file or empty directory. "
                "find: search for text pattern across files in a path. "
                "undo_edit: revert last str_replace/insert. "
                "For HTML/CSS/JS games or large files, do not use create with a full source blob; "
                "use write for a tiny skeleton, then append chunks under 1500 characters each."
            )
        )
        
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(exist_ok=True)
        
        self.allowed_extensions = {
            '.txt', '.md', '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json',
            '.yaml', '.yml', '.toml', '.ini', '.cfg', '.xml', '.csv',
            '.log', '.sh', '.bat', '.ps1', '.sql', '.dockerfile', '.go',
            '.rs', '.java', '.c', '.cpp', '.h', '.hpp', '.rb', '.php',
            '.env', '.lock', '.gitignore', '.editorconfig', '.nvmrc',
            '',
        }
        
        self.add_parameter("command", "str",
            "Command: view, create, write, append, str_replace, insert, delete, find, undo_edit. For large files and HTML/CSS/JS use write then append chunks under 1500 chars.", True)
        self.add_parameter("path", "str",
            "Path to the file or directory, relative to workspace", True)
        self.add_parameter("file_text", "str",
            "Content for small create/write, or one append chunk. Keep large HTML/CSS/JS chunks under 1500 characters.", False)
        self.add_parameter("old_str", "str",
            "The exact string to replace (must appear exactly once). Required for str_replace", False)
        self.add_parameter("new_str", "str",
            "Replacement text for str_replace, or text for insert", False)
        self.add_parameter("insert_line", "int",
            "Line number to insert after (0 = before first line). Required for insert", False)
        self.add_parameter("view_range", "list",
            "Optional [start, end] line range for view command", False)
        self.add_parameter("pattern", "str",
            "Text or regex pattern to search for. Required for find command", False)
        self.add_parameter("recursive", "bool",
            "Whether find should recurse into subdirectories (default true)", False)
    
    def _resolve_path(self, file_path: str) -> Path:
        p = Path(file_path)
        if p.is_absolute():
            return p.resolve()
        return (self.work_dir / file_path).resolve()

    def _is_safe_path(self, file_path: str, write: bool = False) -> bool:
        try:
            abs_path = self._resolve_path(file_path)
            in_workdir = False
            try:
                abs_path.relative_to(self.work_dir)
                in_workdir = True
            except ValueError:
                pass

            if in_workdir:
                if abs_path.is_dir():
                    return True
                if abs_path.suffix.lower() not in self.allowed_extensions:
                    logger.warning(f"File type not allowed: {abs_path.suffix}")
                    return False
                return True

            if write:
                logger.warning(f"Write not allowed outside work directory: {abs_path}")
                return False

            for root in _READONLY_ROOTS:
                try:
                    abs_path.relative_to(root)
                    if abs_path.is_dir():
                        return True
                    if abs_path.suffix.lower() in self.allowed_extensions:
                        return True
                    logger.warning(f"File type not allowed in readonly root: {abs_path.suffix}")
                    return False
                except ValueError:
                    continue

            logger.warning(f"Path outside work directory: {abs_path}")
            return False

        except Exception as e:
            logger.error(f"Error checking path safety: {e}")
            return False

    def _get_full_path(self, file_path: str) -> Path:
        return self._resolve_path(file_path)
    
    def _format_content_with_line_numbers(self, content: str, start_line: int = 1) -> str:
        lines = content.split('\n')
        return '\n'.join(f"{i:4d}│{line}" for i, line in enumerate(lines, start=start_line))

    def _context_around_line(self, content: str, line_no: int, context: int = 3) -> str:
        """Return a few lines of context around a 1-based line number, with line numbers."""
        lines = content.split('\n')
        start = max(0, line_no - 1 - context)
        end = min(len(lines), line_no + context)
        return self._format_content_with_line_numbers('\n'.join(lines[start:end]), start + 1)

    def _find_line_of_str(self, content: str, s: str) -> int:
        """Return 1-based line number where s first appears, or -1."""
        idx = content.find(s)
        if idx == -1:
            return -1
        return content[:idx].count('\n') + 1

    @staticmethod
    def _normalize_ws(s: str) -> str:
        """Normalize line endings and trailing whitespace for fuzzy matching."""
        return re.sub(r'[ \t]+$', '', s.replace('\r\n', '\n').replace('\r', '\n'), flags=re.MULTILINE)

    def _fuzzy_find_and_replace(self, original: str, old_str: str, new_str: str) -> Tuple[bool, str, int, str]:
        """Try exact match first; fall back to whitespace-normalized match.

        Returns (success, new_content, line_no, match_note).
        """
        if old_str in original:
            line_no = self._find_line_of_str(original, old_str)
            return True, original.replace(old_str, new_str, 1), line_no, ""

        norm_orig = self._normalize_ws(original)
        norm_old = self._normalize_ws(old_str)
        if norm_old in norm_orig:
            occurrences = norm_orig.count(norm_old)
            if occurrences > 1:
                return False, original, -1, f"normalized match found {occurrences} times — make old_str more specific"
            idx = norm_orig.find(norm_old)
            line_no = norm_orig[:idx].count('\n') + 1
            end_idx = idx + len(norm_old)
            new_content = norm_orig[:idx] + new_str + norm_orig[end_idx:]
            return True, new_content, line_no, " (matched after whitespace normalization)"

        return False, original, -1, ""
    
    async def view_file(self, file_path: str, view_range: Optional[list] = None) -> SkillResult:
        if not self._is_safe_path(file_path):
            return SkillResult(success=False, error=f"Unsafe file path: {file_path}")
        
        full_path = self._get_full_path(file_path)
        
        if not full_path.exists():
            return SkillResult(success=False, error=f"File not found: {file_path}")
        
        if full_path.is_dir():
            try:
                entries = sorted(full_path.iterdir(), key=lambda p: (p.is_file(), p.name))
                lines = [f"  {'DIR ' if e.is_dir() else 'FILE'}  {e.name}" for e in entries]
                listing = "\n".join(lines) if lines else "  (empty directory)"
                return SkillResult(
                    success=True,
                    content=f"Directory listing: {file_path}\n\n{listing}",
                    metadata={"file_path": file_path, "command": "view", "is_dir": True}
                )
            except Exception as e:
                return SkillResult(success=False, error=f"Error listing directory {file_path}: {e}")
        
        try:
            content = full_path.read_text(encoding='utf-8')
            lines = content.split('\n')
            total_lines = len(lines)
            
            if view_range and len(view_range) == 2:
                start, end = view_range
                start = max(1, int(start)) - 1
                end = min(total_lines, int(end))
                if start >= end:
                    return SkillResult(success=False, error=f"Invalid range: start {start+1} >= end {end}")
                display_lines = lines[start:end]
                formatted = self._format_content_with_line_numbers('\n'.join(display_lines), start + 1)
                info = f"Lines {start+1}-{end} of {file_path} ({total_lines} total)"
            else:
                LIMIT = 500
                if total_lines > LIMIT:
                    formatted = self._format_content_with_line_numbers('\n'.join(lines[:LIMIT]))
                    info = f"{file_path} — showing first {LIMIT} of {total_lines} lines. Use view_range=[{LIMIT+1},{total_lines}] to see more."
                else:
                    formatted = self._format_content_with_line_numbers(content)
                    info = f"{file_path} ({total_lines} lines)"
            
            return SkillResult(
                success=True,
                content=f"{info}\n\n{formatted}",
                metadata={"file_path": file_path, "total_lines": total_lines, "command": "view"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error reading {file_path}: {e}")

    def _is_compacted_history_placeholder(self, content: str) -> bool:
        normalized = (content or "").strip().lower()
        return (
            normalized.startswith("[omitted ")
            or normalized.startswith("<large ")
            or "omitted from history" in normalized
            or "do not copy or execute this placeholder" in normalized
        )

    def _placeholder_error(self) -> SkillResult:
        return SkillResult(
            success=False,
            error=(
                "file_text/new_str is a compacted-history placeholder, not real source. "
                "Regenerate the actual file content and write it with `write` plus `append` chunks under 1500 chars."
            )
        )
    
    async def create_file(self, file_path: str, content: str) -> SkillResult:
        if not self._is_safe_path(file_path, write=True):
            return SkillResult(success=False, error=f"Unsafe file path: {file_path}")
        if self._is_compacted_history_placeholder(content):
            return self._placeholder_error()
        full_path = self._get_full_path(file_path)
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            if full_path.exists():
                return SkillResult(
                    success=False,
                    error=f"File already exists: {file_path}. Use write to overwrite or str_replace to edit."
                )
            full_path.write_text(content, encoding='utf-8')
            return SkillResult(
                success=True,
                content=f"Created {file_path} ({len(content.splitlines())} lines)",
                metadata={"file_path": file_path, "command": "create"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error creating {file_path}: {e}")

    async def write_file(self, file_path: str, content: str) -> SkillResult:
        if not self._is_safe_path(file_path, write=True):
            return SkillResult(success=False, error=f"Unsafe file path: {file_path}")
        if self._is_compacted_history_placeholder(content):
            return self._placeholder_error()
        full_path = self._get_full_path(file_path)
        WARN_BYTES = 80_000
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            n_lines = len(content.splitlines())
            n_bytes = len(content.encode('utf-8'))
            extra = ""
            if n_bytes > WARN_BYTES:
                extra = f" ⚠ Large write ({n_bytes//1024}KB). If content was truncated by the model, use append to add remaining chunks."
            return SkillResult(
                success=True,
                content=f"Wrote {file_path} ({n_bytes} bytes, {n_lines} lines).{extra}",
                metadata={"file_path": file_path, "bytes": n_bytes, "lines": n_lines, "command": "write"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error writing {file_path}: {e}")

    async def append_file(self, file_path: str, content: str) -> SkillResult:
        if not self._is_safe_path(file_path, write=True):
            return SkillResult(success=False, error=f"Unsafe file path: {file_path}")
        if self._is_compacted_history_placeholder(content):
            return self._placeholder_error()
        full_path = self._get_full_path(file_path)
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            joining_newline = ""
            if full_path.exists() and full_path.stat().st_size > 0:
                with open(full_path, 'rb') as f:
                    f.seek(-1, 2)
                    last_byte = f.read(1)
                if last_byte not in (b'\n', b'\r'):
                    joining_newline = "\n"
            with open(full_path, 'a', encoding='utf-8') as f:
                f.write(joining_newline + content)
            total_lines = len(full_path.read_text(encoding='utf-8').splitlines())
            return SkillResult(
                success=True,
                content=f"Appended {len(content)} chars to {file_path} (total {total_lines} lines)",
                metadata={"file_path": file_path, "total_lines": total_lines, "command": "append"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error appending to {file_path}: {e}")
    
    async def str_replace(self, file_path: str, old_str: str, new_str: str) -> SkillResult:
        if not self._is_safe_path(file_path, write=True):
            return SkillResult(success=False, error=f"Unsafe file path: {file_path}")
        full_path = self._get_full_path(file_path)
        if not full_path.exists():
            return SkillResult(success=False, error=f"File not found: {file_path}")
        try:
            original = full_path.read_text(encoding='utf-8')

            occurrences = original.count(old_str)
            if occurrences > 1:
                return SkillResult(
                    success=False,
                    error=f"Found {occurrences} occurrences of the search string in {file_path}. Make old_str more specific."
                )

            success, new_content, replaced_line, note = self._fuzzy_find_and_replace(original, old_str, new_str)
            if not success:
                if note:
                    return SkillResult(success=False, error=f"str_replace failed in {file_path}: {note}")
                hint = (
                    f"String not found in {file_path}. "
                    f"Tip: use view_range to re-read the exact lines, then copy the text precisely."
                )
                return SkillResult(success=False, error=hint)

            total_lines = len(new_content.splitlines())
            full_path.write_text(new_content, encoding='utf-8')
            context = self._context_around_line(new_content, replaced_line, context=3)
            return SkillResult(
                success=True,
                content=f"Replaced at line {replaced_line}{note} in {file_path} (total {total_lines} lines):\n\n{context}",
                metadata={"file_path": file_path, "line": replaced_line, "total_lines": total_lines, "command": "str_replace"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error replacing in {file_path}: {e}")

    async def insert(self, file_path: str, insert_line: int, new_str: str) -> SkillResult:
        if not self._is_safe_path(file_path, write=True):
            return SkillResult(success=False, error=f"Unsafe file path: {file_path}")
        full_path = self._get_full_path(file_path)
        if not full_path.exists():
            return SkillResult(success=False, error=f"File not found: {file_path}")
        try:
            original = full_path.read_text(encoding='utf-8')
            lines = original.splitlines(keepends=True)
            line_count = len(lines)
            if insert_line < 0 or insert_line > line_count:
                return SkillResult(success=False, error=f"Invalid insert_line {insert_line}. Must be 0–{line_count}.")
            insert_text = new_str if new_str.endswith('\n') else new_str + '\n'
            if insert_line == 0:
                new_content = insert_text + original
            else:
                prefix = "".join(lines[:insert_line])
                suffix = "".join(lines[insert_line:])
                if prefix and not prefix.endswith(('\n', '\r')):
                    prefix += '\n'
                new_content = prefix + insert_text + suffix
            full_path.write_text(new_content, encoding='utf-8')
            context = self._context_around_line(new_content, insert_line + 1, context=3)
            return SkillResult(
                success=True,
                content=f"Inserted after line {insert_line} in {file_path}:\n\n{context}",
                metadata={"file_path": file_path, "insert_line": insert_line, "command": "insert"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error inserting in {file_path}: {e}")

    async def delete_path(self, file_path: str) -> SkillResult:
        """Delete a file or empty directory."""
        if not self._is_safe_path(file_path, write=True):
            return SkillResult(success=False, error=f"Unsafe file path: {file_path}")
        full_path = self._get_full_path(file_path)
        if not full_path.exists():
            return SkillResult(success=False, error=f"Not found: {file_path}")
        try:
            if full_path.is_dir():
                shutil.rmtree(full_path)
                return SkillResult(
                    success=True,
                    content=f"Deleted directory {file_path}",
                    metadata={"file_path": file_path, "command": "delete"}
                )
            else:
                full_path.unlink()
                return SkillResult(
                    success=True,
                    content=f"Deleted file {file_path}",
                    metadata={"file_path": file_path, "command": "delete"}
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Error deleting {file_path}: {e}")

    async def find_in_files(self, search_path: str, pattern: str, recursive: bool = True) -> SkillResult:
        """Search for a text pattern in files under search_path."""
        import re
        if not self._is_safe_path(search_path):
            return SkillResult(success=False, error=f"Unsafe path: {search_path}")
        full_path = self._get_full_path(search_path)
        if not full_path.exists():
            return SkillResult(success=False, error=f"Not found: {search_path}")
        try:
            try:
                regex = re.compile(pattern)
            except re.error:
                regex = re.compile(re.escape(pattern))

            results: List[str] = []
            MAX_RESULTS = 200
            glob_fn = full_path.rglob if recursive else full_path.glob
            candidates = [full_path] if full_path.is_file() else list(glob_fn("*"))

            for candidate in candidates:
                if not candidate.is_file():
                    continue
                if candidate.suffix.lower() not in self.allowed_extensions:
                    continue
                try:
                    text = candidate.read_text(encoding='utf-8', errors='replace')
                except Exception:
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel = candidate.relative_to(self.work_dir) if candidate.is_relative_to(self.work_dir) else candidate
                        results.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(results) >= MAX_RESULTS:
                            break
                if len(results) >= MAX_RESULTS:
                    break

            if not results:
                return SkillResult(
                    success=True,
                    content=f"No matches for {pattern!r} in {search_path}",
                    metadata={"pattern": pattern, "matches": 0, "command": "find"}
                )
            truncated = len(results) >= MAX_RESULTS
            output = "\n".join(results)
            if truncated:
                output += f"\n... (showing first {MAX_RESULTS} matches)"
            return SkillResult(
                success=True,
                content=f"Found {len(results)} match(es) for {pattern!r}:\n\n{output}",
                metadata={"pattern": pattern, "matches": len(results), "truncated": truncated, "command": "find"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error searching {search_path}: {e}")

    async def undo_edit(self, file_path: str) -> SkillResult:
        backup_path = self._get_full_path(f"{file_path}.backup")
        original_path = self._get_full_path(file_path)
        if not backup_path.exists():
            return SkillResult(success=False, error=f"No backup found for {file_path}")
        try:
            original_path.write_text(backup_path.read_text(encoding='utf-8'), encoding='utf-8')
            backup_path.unlink()
            return SkillResult(
                success=True,
                content=f"Undid last edit to {file_path}",
                metadata={"file_path": file_path, "command": "undo_edit"}
            )
        except Exception as e:
            return SkillResult(success=False, error=f"Error undoing edit for {file_path}: {e}")
    
    def _create_backup(self, file_path: str):
        try:
            original_path = self._get_full_path(file_path)
            backup_path = self._get_full_path(f"{file_path}.backup")
            if original_path.exists():
                backup_path.write_text(original_path.read_text(encoding='utf-8'), encoding='utf-8')
        except Exception as e:
            logger.warning(f"Could not create backup for {file_path}: {e}")
    
    async def execute(self, **kwargs) -> SkillResult:
        command = kwargs.get("command")
        file_path = kwargs.get("path")
        
        if not file_path:
            return SkillResult(success=False, error="path parameter is required")
        
        try:
            if command == "view":
                return await self.view_file(file_path, kwargs.get("view_range"))
            
            elif command == "create":
                return await self.create_file(file_path, kwargs.get("file_text", ""))

            elif command == "write":
                return await self.write_file(file_path, kwargs.get("file_text", ""))

            elif command == "append":
                content = kwargs.get("file_text") or kwargs.get("new_str")
                if content is None:
                    return SkillResult(success=False, error="file_text or new_str is required for append")
                return await self.append_file(file_path, content)
            
            elif command == "str_replace":
                old_str = kwargs.get("old_str")
                new_str = kwargs.get("new_str", "")
                if not old_str:
                    return SkillResult(success=False, error="old_str is required for str_replace")
                self._create_backup(file_path)
                return await self.str_replace(file_path, old_str, new_str)

            elif command == "insert":
                insert_line = kwargs.get("insert_line")
                new_str = kwargs.get("new_str")
                if insert_line is None:
                    return SkillResult(success=False, error="insert_line is required for insert")
                if new_str is None:
                    return SkillResult(success=False, error="new_str is required for insert")
                try:
                    insert_line = int(insert_line)
                except (TypeError, ValueError):
                    return SkillResult(success=False, error="insert_line must be an integer")
                self._create_backup(file_path)
                return await self.insert(file_path, insert_line, new_str)

            elif command == "delete":
                return await self.delete_path(file_path)

            elif command == "find":
                pattern = kwargs.get("pattern")
                if not pattern:
                    return SkillResult(success=False, error="pattern is required for find")
                recursive = kwargs.get("recursive", True)
                if isinstance(recursive, str):
                    recursive = recursive.lower() != "false"
                return await self.find_in_files(file_path, pattern, recursive)
            
            elif command == "undo_edit":
                return await self.undo_edit(file_path)
            
            else:
                return SkillResult(
                    success=False,
                    error=f"Unknown command: {command!r}. Supported: view, create, write, append, str_replace, insert, delete, find, undo_edit"
                )
        
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error executing {command}: {e}",
                metadata={"command": command, "file_path": file_path}
            )
