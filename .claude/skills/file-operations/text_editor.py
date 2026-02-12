"""Text Editor Skill - Claude官方文本编辑技能"""
import os
from typing import Optional, Dict, Any
from pathlib import Path

from loguru import logger

# 相对导入修复 - 根据实际运行环境调整
import sys
from pathlib import Path

# 添加src目录到Python路径
src_path = Path(__file__).parent.parent.parent.parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

try:
    from omni_agent.skills.base_skill import BaseSkill, SkillResult
except ImportError:
    # 如果还是导入失败，使用本地基类定义
    class SkillResult:
        def __init__(self, success: bool, content: Any = None, error: str = None, metadata: Dict[str, Any] = None):
            self.success = success
            self.content = content
            self.error = error
            self.metadata = metadata or {}
    
    class BaseSkill:
        def __init__(self, name: str, description: str):
            self.name = name
            self.description = description
            self.enabled = True
            self.parameters = {}
        
        def add_parameter(self, name: str, type_: str, description: str, required: bool = True):
            self.parameters[name] = {
                "type": type_,
                "description": description, 
                "required": required
            }
        
        def to_dict(self) -> Dict[str, Any]:
            return {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
                "enabled": self.enabled
            }
        
        async def execute(self, **kwargs) -> SkillResult:
            raise NotImplementedError


class TextEditorSkill(BaseSkill):
    """Text Editor Skill - 模拟Claude的文本编辑能力"""
    
    def __init__(self, work_dir: str = "workspace"):
        super().__init__(
            name="str_replace_editor",
            description="A text editor tool for viewing, creating and editing files. All edits made are to the contents of the file ONLY and are not executed. Commands: view, create, str_replace, insert, undo_edit"
        )
        
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(exist_ok=True)
        
        self.allowed_extensions = {
            '.txt', '.md', '.py', '.js', '.ts', '.html', '.css', '.json',
            '.yaml', '.yml', '.toml', '.ini', '.cfg', '.xml', '.csv',
            '.log', '.sh', '.bat', '.ps1', '.sql', '.dockerfile', '.go',
            '.rs', '.java', '.c', '.cpp', '.h', '.hpp', '.rb', '.php'
        }
        
        self.add_parameter(
            "command",
            "str",
            "The command to execute. Available commands: view, create, str_replace, insert, undo_edit",
            True
        )
        self.add_parameter(
            "path",
            "str",
            "The path to the file to edit, relative to workspace. Required for all commands",
            True
        )
        self.add_parameter(
            "file_text",
            "str",
            "The full content of the file for create command. Required for create",
            False
        )
        self.add_parameter(
            "old_str",
            "str",
            "The string in the file to replace. Required for str_replace",
            False
        )
        self.add_parameter(
            "new_str",
            "str",
            "The new string to replace old_str with. Required for str_replace",
            False
        )
        self.add_parameter(
            "insert_line",
            "int",
            "The line number to insert text after. Required for insert command",
            False
        )
        self.add_parameter(
            "new_str",
            "str",
            "The text to insert. Required for insert command (reused parameter)",
            False
        )
        self.add_parameter(
            "view_range",
            "list",
            "Optional line range [start, end] for view command to see specific lines",
            False
        )
    
    def _is_safe_path(self, file_path: str) -> bool:
        """检查路径是否安全"""
        try:
            # 转换为绝对路径并解析
            abs_path = (self.work_dir / file_path).resolve()
            
            # 检查是否在工作目录内
            try:
                abs_path.relative_to(self.work_dir)
            except ValueError:
                logger.warning(f"Path outside work directory: {abs_path}")
                return False
            
            # 检查文件扩展名
            if abs_path.suffix.lower() not in self.allowed_extensions:
                logger.warning(f"File type not allowed: {abs_path.suffix}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking path safety: {e}")
            return False
    
    def _get_file_path(self, path: str) -> Optional[Path]:
        """获取安全的文件路径"""
        if not self._is_safe_path(path):
            return None
        
        return (self.work_dir / path).resolve()
    
    def _read_file_with_backup(self, file_path: Path) -> str:
        """读取文件并创建备份"""
        if not file_path.exists():
            return ""
        
        content = file_path.read_text(encoding='utf-8')
        
        # 创建备份
        backup_path = file_path.with_suffix(f"{file_path.suffix}.backup")
        backup_path.write_text(content, encoding='utf-8')
        
        return content
    
    def _format_file_content(
        self, 
        content: str, 
        view_range: Optional[list] = None, 
        highlight_line: Optional[int] = None
    ) -> str:
        """格式化文件内容显示"""
        lines = content.split('\n')
        
        # 应用视图范围
        if view_range and len(view_range) == 2:
            start, end = max(1, view_range[0]), min(len(lines), view_range[1])
            lines = lines[start-1:end]
            line_offset = start - 1
        else:
            line_offset = 0
        
        # 添加行号
        formatted_lines = []
        for i, line in enumerate(lines, 1):
            line_num = i + line_offset
            prefix = f"{line_num:4d}: "
            
            # 高亮特定行
            if highlight_line and line_num == highlight_line:
                prefix = f"{line_num:4d}→ "
            
            formatted_lines.append(f"{prefix}{line}")
        
        return '\n'.join(formatted_lines)
    
    async def execute(self, **kwargs) -> SkillResult:
        """执行文本编辑操作"""
        command = kwargs.get("command")
        path = kwargs.get("path")
        
        if not path:
            return SkillResult(
                success=False,
                error="Path parameter is required for all commands"
            )
        
        file_path = self._get_file_path(path)
        if not file_path:
            return SkillResult(
                success=False,
                error=f"Invalid or unsafe file path: {path}"
            )
        
        try:
            if command == "view":
                return await self._handle_view(file_path, kwargs.get("view_range"))
            
            elif command == "create":
                return await self._handle_create(file_path, kwargs.get("file_text", ""))
            
            elif command == "str_replace":
                return await self._handle_str_replace(
                    file_path,
                    kwargs.get("old_str"),
                    kwargs.get("new_str")
                )
            
            elif command == "insert":
                return await self._handle_insert(
                    file_path,
                    kwargs.get("insert_line"),
                    kwargs.get("new_str")
                )
            
            elif command == "undo_edit":
                return await self._handle_undo(file_path)
            
            else:
                return SkillResult(
                    success=False,
                    error=f"Unsupported command: {command}. Available commands: view, create, str_replace, insert, undo_edit"
                )
                
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error executing {command}: {str(e)}",
                metadata={"command": command, "path": path}
            )
    
    async def _handle_view(
        self, 
        file_path: Path, 
        view_range: Optional[list]
    ) -> SkillResult:
        """处理view命令"""
        if not file_path.exists():
            return SkillResult(
                success=False,
                error=f"File not found: {file_path.name}"
            )
        
        try:
            content = file_path.read_text(encoding='utf-8')
            formatted_content = self._format_file_content(content, view_range)
            
            total_lines = len(content.split('\n'))
            
            if view_range:
                start, end = view_range
                range_info = f" (showing lines {start}-{end} of {total_lines})"
            else:
                range_info = f" ({total_lines} lines)"
            
            return SkillResult(
                success=True,
                content=f"File: {file_path.name}{range_info}\n\n{formatted_content}",
                metadata={
                    "command": "view",
                    "path": str(file_path),
                    "total_lines": total_lines,
                    "view_range": view_range
                }
            )
            
        except UnicodeDecodeError:
            return SkillResult(
                success=False,
                error=f"Cannot read file - appears to be binary: {file_path.name}"
            )
    
    async def _handle_create(self, file_path: Path, file_text: str) -> SkillResult:
        """处理create命令"""
        if file_path.exists():
            # 先备份已存在的文件
            self._read_file_with_backup(file_path)
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_text, encoding='utf-8')
        
        # 格式化显示创建的内容
        formatted_content = self._format_file_content(file_text)
        
        return SkillResult(
            success=True,
            content=f"File created: {file_path.name}\n\n{formatted_content}",
            metadata={
                "command": "create",
                "path": str(file_path),
                "lines_created": len(file_text.split('\n'))
            }
        )
    
    async def _handle_str_replace(
        self,
        file_path: Path,
        old_str: Optional[str],
        new_str: Optional[str]
    ) -> SkillResult:
        """处理str_replace命令"""
        if not old_str:
            return SkillResult(
                success=False,
                error="old_str parameter is required for str_replace command"
            )
        
        if new_str is None:
            new_str = ""
        
        if not file_path.exists():
            return SkillResult(
                success=False,
                error=f"File not found: {file_path.name}"
            )
        
        # 读取文件内容（并创建备份）
        content = self._read_file_with_backup(file_path)
        
        # 检查字符串是否存在
        if old_str not in content:
            return SkillResult(
                success=False,
                error=f"String not found in file: '{old_str[:50]}...'" if len(old_str) > 50 else f"String not found in file: '{old_str}'"
            )
        
        # 检查是否有多个匹配
        if content.count(old_str) > 1:
            return SkillResult(
                success=False,
                error=f"Multiple matches found for string: '{old_str[:50]}...'. Please make the string more specific." if len(old_str) > 50 else f"Multiple matches found for string: '{old_str}'. Please make the string more specific."
            )
        
        # 执行替换
        new_content = content.replace(old_str, new_str)
        file_path.write_text(new_content, encoding='utf-8')
        
        # 找出修改的行号用于高亮显示
        lines_before = content.split('\n')
        lines_after = new_content.split('\n')
        
        changed_line = None
        for i, (before, after) in enumerate(zip(lines_before, lines_after), 1):
            if before != after:
                changed_line = i
                break
        
        # 显示修改后的内容（周围几行）
        if changed_line:
            start_line = max(1, changed_line - 2)
            end_line = min(len(lines_after), changed_line + 2)
            view_range = [start_line, end_line]
        else:
            view_range = None
        
        formatted_content = self._format_file_content(new_content, view_range, changed_line)
        
        return SkillResult(
            success=True,
            content=f"String replaced in {file_path.name}\n\n{formatted_content}",
            metadata={
                "command": "str_replace",
                "path": str(file_path),
                "old_str": old_str,
                "new_str": new_str,
                "changed_line": changed_line
            }
        )
    
    async def _handle_insert(
        self,
        file_path: Path,
        insert_line: Optional[int],
        new_str: Optional[str]
    ) -> SkillResult:
        """处理insert命令"""
        if insert_line is None:
            return SkillResult(
                success=False,
                error="insert_line parameter is required for insert command"
            )
        
        if new_str is None:
            new_str = ""
        
        if not file_path.exists():
            return SkillResult(
                success=False,
                error=f"File not found: {file_path.name}"
            )
        
        # 读取文件内容（并创建备份）
        content = self._read_file_with_backup(file_path)
        lines = content.split('\n')
        
        if insert_line < 0 or insert_line > len(lines):
            return SkillResult(
                success=False,
                error=f"Invalid line number: {insert_line}. File has {len(lines)} lines"
            )
        
        # 插入新内容
        lines.insert(insert_line, new_str)
        new_content = '\n'.join(lines)
        file_path.write_text(new_content, encoding='utf-8')
        
        # 显示插入位置周围的内容
        start_line = max(1, insert_line)
        end_line = min(len(lines), insert_line + 4)
        view_range = [start_line, end_line]
        
        formatted_content = self._format_file_content(new_content, view_range, insert_line + 1)
        
        return SkillResult(
            success=True,
            content=f"Text inserted in {file_path.name} at line {insert_line + 1}\n\n{formatted_content}",
            metadata={
                "command": "insert",
                "path": str(file_path),
                "insert_line": insert_line + 1,
                "new_str": new_str
            }
        )
    
    async def _handle_undo(self, file_path: Path) -> SkillResult:
        """处理undo_edit命令"""
        backup_path = file_path.with_suffix(f"{file_path.suffix}.backup")
        
        if not backup_path.exists():
            return SkillResult(
                success=False,
                error=f"No backup found for {file_path.name}"
            )
        
        # 恢复备份内容
        backup_content = backup_path.read_text(encoding='utf-8')
        file_path.write_text(backup_content, encoding='utf-8')
        
        # 删除备份文件
        backup_path.unlink()
        
        formatted_content = self._format_file_content(backup_content)
        
        return SkillResult(
            success=True,
            content=f"Edit undone for {file_path.name}\n\n{formatted_content}",
            metadata={
                "command": "undo_edit",
                "path": str(file_path)
            }
        )