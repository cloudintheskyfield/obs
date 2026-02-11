"""Text Editor Skill - Claude官方文本编辑技能"""
import os
from typing import Optional, Dict, Any
from pathlib import Path

from loguru import logger

from .base_skill import BaseSkill, SkillResult


class TextEditorSkill(BaseSkill):
    """Text Editor Skill - 模拟Claude的文本编辑能力"""
    
    def __init__(self, work_dir: str = "workspace"):
        super().__init__(
            name="text_editor",
            description="Create, read, edit, and manage text files"
        )
        
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(exist_ok=True)
        
        # 安全配置
        self.allowed_extensions = {
            '.txt', '.md', '.py', '.js', '.ts', '.html', '.css', '.json',
            '.yaml', '.yml', '.toml', '.ini', '.cfg', '.xml', '.csv',
            '.log', '.sh', '.bat', '.ps1', '.sql', '.dockerfile'
        }
        
        # 定义参数
        self.add_parameter("command", "str", "Command: view, create, str_replace, undo_edit", True)
        self.add_parameter("path", "str", "File path relative to workspace", True)
        self.add_parameter("file_text", "str", "Content for create command", False)
        self.add_parameter("old_str", "str", "String to replace", False)
        self.add_parameter("new_str", "str", "Replacement string", False)
        self.add_parameter("view_range", "list", "Line range [start, end] for view command", False)
    
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
    
    def _get_full_path(self, file_path: str) -> Path:
        """获取完整路径"""
        return (self.work_dir / file_path).resolve()
    
    def _format_content_with_line_numbers(self, content: str, start_line: int = 1) -> str:
        """格式化内容，添加行号"""
        lines = content.split('\n')
        numbered_lines = []
        
        for i, line in enumerate(lines, start=start_line):
            numbered_lines.append(f"{i:4d}│{line}")
        
        return '\n'.join(numbered_lines)
    
    async def view_file(
        self, 
        file_path: str, 
        view_range: Optional[list] = None
    ) -> SkillResult:
        """查看文件内容"""
        if not self._is_safe_path(file_path):
            return SkillResult(
                success=False,
                error=f"Unsafe file path: {file_path}"
            )
        
        full_path = self._get_full_path(file_path)
        
        if not full_path.exists():
            return SkillResult(
                success=False,
                error=f"File not found: {file_path}"
            )
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            total_lines = len(lines)
            
            # 处理行范围
            if view_range and len(view_range) == 2:
                start, end = view_range
                start = max(1, start) - 1  # 转换为0索引
                end = min(total_lines, end)
                
                if start >= end:
                    return SkillResult(
                        success=False,
                        error=f"Invalid range: start line {start+1} >= end line {end}"
                    )
                
                display_lines = lines[start:end]
                formatted_content = self._format_content_with_line_numbers(
                    '\n'.join(display_lines), 
                    start + 1
                )
                
                content_info = f"Viewing lines {start+1}-{end} of {file_path} ({total_lines} total lines)"
            else:
                # 如果文件太长，只显示前100行
                if total_lines > 100:
                    display_lines = lines[:100]
                    formatted_content = self._format_content_with_line_numbers('\n'.join(display_lines))
                    content_info = f"Viewing first 100 lines of {file_path} ({total_lines} total lines)"
                else:
                    formatted_content = self._format_content_with_line_numbers(content)
                    content_info = f"Viewing {file_path} ({total_lines} lines)"
            
            return SkillResult(
                success=True,
                content=f"{content_info}\n\n{formatted_content}",
                metadata={
                    "file_path": file_path,
                    "total_lines": total_lines,
                    "command": "view"
                }
            )
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error reading file {file_path}: {str(e)}"
            )
    
    async def create_file(self, file_path: str, content: str) -> SkillResult:
        """创建文件"""
        if not self._is_safe_path(file_path):
            return SkillResult(
                success=False,
                error=f"Unsafe file path: {file_path}"
            )
        
        full_path = self._get_full_path(file_path)
        
        try:
            # 创建目录（如果不存在）
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 检查文件是否已存在
            if full_path.exists():
                return SkillResult(
                    success=False,
                    error=f"File already exists: {file_path}. Use str_replace to modify existing files."
                )
            
            # 写入文件
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            lines = content.split('\n')
            line_count = len(lines)
            
            return SkillResult(
                success=True,
                content=f"Created file {file_path} with {line_count} lines",
                metadata={
                    "file_path": file_path,
                    "lines_written": line_count,
                    "command": "create"
                }
            )
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error creating file {file_path}: {str(e)}"
            )
    
    async def str_replace(
        self, 
        file_path: str, 
        old_str: str, 
        new_str: str
    ) -> SkillResult:
        """字符串替换"""
        if not self._is_safe_path(file_path):
            return SkillResult(
                success=False,
                error=f"Unsafe file path: {file_path}"
            )
        
        full_path = self._get_full_path(file_path)
        
        if not full_path.exists():
            return SkillResult(
                success=False,
                error=f"File not found: {file_path}"
            )
        
        try:
            # 读取原文件
            with open(full_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            # 检查是否找到要替换的字符串
            if old_str not in original_content:
                return SkillResult(
                    success=False,
                    error=f"String not found in {file_path}: '{old_str}'"
                )
            
            # 计算替换次数
            occurrences = original_content.count(old_str)
            
            if occurrences > 1:
                return SkillResult(
                    success=False,
                    error=f"Multiple occurrences of '{old_str}' found ({occurrences}). Please be more specific."
                )
            
            # 执行替换
            new_content = original_content.replace(old_str, new_str)
            
            # 写入文件
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # 计算行数变化
            old_lines = len(original_content.split('\n'))
            new_lines = len(new_content.split('\n'))
            
            return SkillResult(
                success=True,
                content=f"Replaced '{old_str}' with '{new_str}' in {file_path}",
                metadata={
                    "file_path": file_path,
                    "old_lines": old_lines,
                    "new_lines": new_lines,
                    "command": "str_replace"
                }
            )
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error replacing string in {file_path}: {str(e)}"
            )
    
    async def undo_edit(self, file_path: str) -> SkillResult:
        """撤销编辑（简单实现，基于备份文件）"""
        backup_path = self._get_full_path(f"{file_path}.backup")
        original_path = self._get_full_path(file_path)
        
        if not backup_path.exists():
            return SkillResult(
                success=False,
                error=f"No backup found for {file_path}"
            )
        
        try:
            # 恢复备份
            backup_content = backup_path.read_text(encoding='utf-8')
            original_path.write_text(backup_content, encoding='utf-8')
            
            # 删除备份文件
            backup_path.unlink()
            
            return SkillResult(
                success=True,
                content=f"Undid last edit to {file_path}",
                metadata={
                    "file_path": file_path,
                    "command": "undo_edit"
                }
            )
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error undoing edit for {file_path}: {str(e)}"
            )
    
    def _create_backup(self, file_path: str):
        """创建备份文件"""
        try:
            original_path = self._get_full_path(file_path)
            backup_path = self._get_full_path(f"{file_path}.backup")
            
            if original_path.exists():
                backup_path.write_text(
                    original_path.read_text(encoding='utf-8'),
                    encoding='utf-8'
                )
                
        except Exception as e:
            logger.warning(f"Could not create backup for {file_path}: {e}")
    
    async def execute(self, **kwargs) -> SkillResult:
        """执行Text Editor操作"""
        command = kwargs.get("command")
        file_path = kwargs.get("path")
        
        if not file_path:
            return SkillResult(
                success=False,
                error="File path is required"
            )
        
        try:
            if command == "view":
                view_range = kwargs.get("view_range")
                return await self.view_file(file_path, view_range)
            
            elif command == "create":
                content = kwargs.get("file_text", "")
                return await self.create_file(file_path, content)
            
            elif command == "str_replace":
                old_str = kwargs.get("old_str")
                new_str = kwargs.get("new_str")
                
                if not old_str:
                    return SkillResult(
                        success=False,
                        error="old_str parameter is required for str_replace command"
                    )
                
                if new_str is None:
                    new_str = ""
                
                # 创建备份
                self._create_backup(file_path)
                
                return await self.str_replace(file_path, old_str, new_str)
            
            elif command == "undo_edit":
                return await self.undo_edit(file_path)
            
            else:
                return SkillResult(
                    success=False,
                    error=f"Unsupported command: {command}. Supported commands: view, create, str_replace, undo_edit"
                )
        
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error executing {command}: {str(e)}",
                metadata={"command": command, "file_path": file_path}
            )