"""文件处理工具"""
import os
import json
import shutil
import mimetypes
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from datetime import datetime

from loguru import logger


class FileTool:
    """文件处理工具"""
    
    def __init__(self, work_dir: str = "workspace", allow_operations: bool = True):
        self.work_dir = Path(work_dir).resolve()
        self.allow_operations = allow_operations
        
        # 确保工作目录存在
        self.work_dir.mkdir(exist_ok=True)
        
        # 安全配置
        self.allowed_extensions = {
            '.txt', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg',
            '.py', '.js', '.ts', '.html', '.css', '.md', '.rst',
            '.csv', '.xml', '.log', '.sh', '.bat', '.ps1',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx'
        }
        
        # 危险路径模式
        self.dangerous_patterns = [
            '../', '..\\', '/etc/', '/bin/', '/usr/', '/var/',
            'C:\\Windows\\', 'C:\\Program Files\\', 'C:\\Users\\Public\\',
            '~/.ssh/', '~/.aws/', '~/.config/'
        ]
    
    def _is_safe_path(self, file_path: Union[str, Path]) -> bool:
        """检查路径是否安全"""
        if not self.allow_operations:
            return False
        
        try:
            # 转换为绝对路径并解析
            abs_path = Path(file_path).resolve()
            
            # 检查是否在工作目录内
            try:
                abs_path.relative_to(self.work_dir)
            except ValueError:
                logger.warning(f"Path outside work directory: {abs_path}")
                return False
            
            # 检查危险模式
            path_str = str(abs_path)
            for pattern in self.dangerous_patterns:
                if pattern in path_str:
                    logger.warning(f"Dangerous path pattern detected: {pattern}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking path safety: {e}")
            return False
    
    def _get_file_info(self, file_path: Path) -> Dict[str, Any]:
        """获取文件信息"""
        try:
            stat = file_path.stat()
            mime_type, _ = mimetypes.guess_type(str(file_path))
            
            return {
                "name": file_path.name,
                "path": str(file_path),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "is_file": file_path.is_file(),
                "is_dir": file_path.is_dir(),
                "mime_type": mime_type,
                "extension": file_path.suffix.lower()
            }
        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            return {"error": str(e)}
    
    async def read_file(self, file_path: str, encoding: str = "utf-8") -> Dict[str, Any]:
        """读取文件内容"""
        try:
            path = Path(file_path)
            
            if not self._is_safe_path(path):
                return {"success": False, "error": "Unsafe file path"}
            
            if not path.exists():
                return {"success": False, "error": "File not found"}
            
            if not path.is_file():
                return {"success": False, "error": "Path is not a file"}
            
            # 检查文件扩展名
            if path.suffix.lower() not in self.allowed_extensions:
                return {"success": False, "error": f"File type not allowed: {path.suffix}"}
            
            # 读取文件内容
            if path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
                # 图像文件返回路径
                content = f"[Image file: {path}]"
                content_type = "image"
            else:
                # 文本文件
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read()
                content_type = "text"
            
            file_info = self._get_file_info(path)
            
            result = {
                "success": True,
                "content": content,
                "content_type": content_type,
                "file_info": file_info,
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Successfully read file: {path}")
            return result
            
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return {"success": False, "error": str(e)}
    
    async def write_file(
        self, 
        file_path: str, 
        content: str, 
        encoding: str = "utf-8",
        create_dirs: bool = True
    ) -> Dict[str, Any]:
        """写入文件内容"""
        try:
            path = Path(file_path)
            
            if not self._is_safe_path(path):
                return {"success": False, "error": "Unsafe file path"}
            
            # 检查文件扩展名
            if path.suffix.lower() not in self.allowed_extensions:
                return {"success": False, "error": f"File type not allowed: {path.suffix}"}
            
            # 创建目录
            if create_dirs:
                path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入文件
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
            
            file_info = self._get_file_info(path)
            
            result = {
                "success": True,
                "file_info": file_info,
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Successfully wrote file: {path}")
            return result
            
        except Exception as e:
            logger.error(f"Error writing file {file_path}: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_file(self, file_path: str) -> Dict[str, Any]:
        """删除文件"""
        try:
            path = Path(file_path)
            
            if not self._is_safe_path(path):
                return {"success": False, "error": "Unsafe file path"}
            
            if not path.exists():
                return {"success": False, "error": "File not found"}
            
            # 删除文件或目录
            if path.is_file():
                path.unlink()
                logger.info(f"Successfully deleted file: {path}")
            elif path.is_dir():
                shutil.rmtree(path)
                logger.info(f"Successfully deleted directory: {path}")
            else:
                return {"success": False, "error": "Unknown file type"}
            
            result = {
                "success": True,
                "deleted_path": str(path),
                "timestamp": datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")
            return {"success": False, "error": str(e)}
    
    async def list_directory(self, dir_path: str = ".") -> Dict[str, Any]:
        """列出目录内容"""
        try:
            path = Path(dir_path) if dir_path != "." else self.work_dir
            
            if not self._is_safe_path(path):
                return {"success": False, "error": "Unsafe directory path"}
            
            if not path.exists():
                return {"success": False, "error": "Directory not found"}
            
            if not path.is_dir():
                return {"success": False, "error": "Path is not a directory"}
            
            items = []
            
            for item in path.iterdir():
                try:
                    item_info = self._get_file_info(item)
                    items.append(item_info)
                except Exception as e:
                    logger.warning(f"Error getting info for {item}: {e}")
                    continue
            
            # 按名称排序
            items.sort(key=lambda x: x.get("name", ""))
            
            result = {
                "success": True,
                "directory": str(path),
                "items": items,
                "total_items": len(items),
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Successfully listed directory: {path} ({len(items)} items)")
            return result
            
        except Exception as e:
            logger.error(f"Error listing directory {dir_path}: {e}")
            return {"success": False, "error": str(e)}
    
    async def create_directory(self, dir_path: str) -> Dict[str, Any]:
        """创建目录"""
        try:
            path = Path(dir_path)
            
            if not self._is_safe_path(path):
                return {"success": False, "error": "Unsafe directory path"}
            
            # 创建目录
            path.mkdir(parents=True, exist_ok=True)
            
            dir_info = self._get_file_info(path)
            
            result = {
                "success": True,
                "directory_info": dir_info,
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Successfully created directory: {path}")
            return result
            
        except Exception as e:
            logger.error(f"Error creating directory {dir_path}: {e}")
            return {"success": False, "error": str(e)}
    
    async def copy_file(self, src_path: str, dst_path: str) -> Dict[str, Any]:
        """复制文件"""
        try:
            src = Path(src_path)
            dst = Path(dst_path)
            
            if not self._is_safe_path(src) or not self._is_safe_path(dst):
                return {"success": False, "error": "Unsafe file path"}
            
            if not src.exists():
                return {"success": False, "error": "Source file not found"}
            
            # 创建目标目录
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            # 复制文件
            if src.is_file():
                shutil.copy2(src, dst)
                logger.info(f"Successfully copied file: {src} -> {dst}")
            elif src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                logger.info(f"Successfully copied directory: {src} -> {dst}")
            else:
                return {"success": False, "error": "Unknown source type"}
            
            dst_info = self._get_file_info(dst)
            
            result = {
                "success": True,
                "source": str(src),
                "destination": str(dst),
                "destination_info": dst_info,
                "timestamp": datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error copying file {src_path} to {dst_path}: {e}")
            return {"success": False, "error": str(e)}
    
    async def move_file(self, src_path: str, dst_path: str) -> Dict[str, Any]:
        """移动文件"""
        try:
            src = Path(src_path)
            dst = Path(dst_path)
            
            if not self._is_safe_path(src) or not self._is_safe_path(dst):
                return {"success": False, "error": "Unsafe file path"}
            
            if not src.exists():
                return {"success": False, "error": "Source file not found"}
            
            # 创建目标目录
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            # 移动文件
            shutil.move(str(src), str(dst))
            
            dst_info = self._get_file_info(dst)
            
            result = {
                "success": True,
                "source": str(src),
                "destination": str(dst),
                "destination_info": dst_info,
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Successfully moved file: {src} -> {dst}")
            return result
            
        except Exception as e:
            logger.error(f"Error moving file {src_path} to {dst_path}: {e}")
            return {"success": False, "error": str(e)}
    
    async def search_files(
        self, 
        pattern: str, 
        dir_path: str = ".", 
        case_sensitive: bool = False
    ) -> Dict[str, Any]:
        """搜索文件"""
        try:
            path = Path(dir_path) if dir_path != "." else self.work_dir
            
            if not self._is_safe_path(path):
                return {"success": False, "error": "Unsafe directory path"}
            
            if not path.exists() or not path.is_dir():
                return {"success": False, "error": "Invalid directory"}
            
            # 搜索匹配的文件
            matches = []
            search_pattern = pattern if case_sensitive else pattern.lower()
            
            for item in path.rglob("*"):
                try:
                    if not self._is_safe_path(item):
                        continue
                    
                    item_name = item.name if case_sensitive else item.name.lower()
                    
                    if search_pattern in item_name:
                        item_info = self._get_file_info(item)
                        matches.append(item_info)
                        
                except Exception as e:
                    logger.warning(f"Error processing {item}: {e}")
                    continue
            
            # 按名称排序
            matches.sort(key=lambda x: x.get("name", ""))
            
            result = {
                "success": True,
                "pattern": pattern,
                "search_directory": str(path),
                "matches": matches,
                "total_matches": len(matches),
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Search completed: {len(matches)} matches for '{pattern}'")
            return result
            
        except Exception as e:
            logger.error(f"Error searching files: {e}")
            return {"success": False, "error": str(e)}