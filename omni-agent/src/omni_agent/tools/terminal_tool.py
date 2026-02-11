"""终端执行工具"""
import asyncio
import subprocess
import os
import signal
import threading
import time
from typing import Dict, List, Optional, Any, Callable, AsyncIterator
from datetime import datetime
from pathlib import Path
import queue

from loguru import logger


class TerminalTool:
    """终端执行工具"""
    
    def __init__(
        self, 
        work_dir: str = "workspace", 
        allow_execution: bool = True,
        timeout: int = 30
    ):
        self.work_dir = Path(work_dir).resolve()
        self.allow_execution = allow_execution
        self.timeout = timeout
        self.running_processes: Dict[str, subprocess.Popen] = {}
        
        # 确保工作目录存在
        self.work_dir.mkdir(exist_ok=True)
        
        # 安全配置
        self.allowed_commands = {
            # 基本命令
            'ls', 'dir', 'pwd', 'cd', 'echo', 'cat', 'type', 'head', 'tail',
            'find', 'grep', 'sort', 'uniq', 'wc', 'du', 'df',
            
            # 文件操作
            'cp', 'copy', 'mv', 'move', 'rm', 'del', 'mkdir', 'rmdir', 'touch',
            
            # 开发工具
            'git', 'python', 'pip', 'uv', 'node', 'npm', 'yarn', 'pnpm',
            'cargo', 'rustc', 'go', 'java', 'javac', 'gcc', 'g++', 'make',
            
            # 系统工具
            'ps', 'tasklist', 'kill', 'taskkill', 'top', 'htop', 'netstat',
            'curl', 'wget', 'ping', 'tracert', 'traceroute',
            
            # 压缩工具
            'zip', 'unzip', 'tar', 'gzip', 'gunzip',
            
            # 文本编辑器
            'nano', 'vim', 'code'
        }
        
        # 危险命令黑名单
        self.dangerous_commands = {
            'rm -rf /', 'del /f /s /q C:\\', 'format', 'fdisk',
            'shutdown', 'reboot', 'halt', 'init 0', 'init 6',
            'dd', 'mkfs', 'parted', 'gparted',
            'sudo rm -rf', 'sudo dd', 'sudo fdisk'
        }
    
    def _is_safe_command(self, command: str) -> bool:
        """检查命令是否安全"""
        if not self.allow_execution:
            return False
        
        # 检查危险命令
        command_lower = command.lower().strip()
        for dangerous in self.dangerous_commands:
            if dangerous in command_lower:
                logger.warning(f"Dangerous command detected: {dangerous}")
                return False
        
        # 检查基本命令是否在允许列表中
        first_word = command.split()[0] if command.split() else ""
        
        # 特殊处理：允许带路径的命令
        if '/' in first_word or '\\' in first_word:
            first_word = Path(first_word).name
        
        # 移除文件扩展名
        if '.' in first_word:
            first_word = first_word.split('.')[0]
        
        if first_word not in self.allowed_commands:
            logger.warning(f"Command not in allowed list: {first_word}")
            return False
        
        return True
    
    def _get_process_id(self, command: str) -> str:
        """生成进程ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"proc_{timestamp}"
    
    async def execute_command(
        self, 
        command: str, 
        working_directory: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
        stream_output: bool = False
    ) -> Dict[str, Any]:
        """执行单个命令"""
        if not self._is_safe_command(command):
            return {
                "success": False,
                "error": "Command not allowed for security reasons",
                "command": command,
                "timestamp": datetime.now().isoformat()
            }
        
        # 设置工作目录
        work_dir = Path(working_directory) if working_directory else self.work_dir
        if not work_dir.exists():
            return {
                "success": False,
                "error": f"Working directory does not exist: {work_dir}",
                "command": command,
                "timestamp": datetime.now().isoformat()
            }
        
        # 设置环境变量
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        
        logger.info(f"Executing command: {command} in {work_dir}")
        
        try:
            if stream_output:
                return await self._execute_streaming(command, work_dir, env)
            else:
                return await self._execute_blocking(command, work_dir, env)
                
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "timestamp": datetime.now().isoformat()
            }
    
    async def _execute_blocking(
        self, 
        command: str, 
        work_dir: Path, 
        env: Dict[str, str]
    ) -> Dict[str, Any]:
        """执行阻塞命令"""
        start_time = time.time()
        
        try:
            # 使用asyncio.create_subprocess_shell执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True
            )
            
            # 等待命令完成或超时
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "success": False,
                    "error": f"Command timed out after {self.timeout} seconds",
                    "command": command,
                    "execution_time": time.time() - start_time,
                    "timestamp": datetime.now().isoformat()
                }
            
            execution_time = time.time() - start_time
            
            result = {
                "success": process.returncode == 0,
                "command": command,
                "return_code": process.returncode,
                "stdout": stdout.decode('utf-8', errors='replace') if stdout else "",
                "stderr": stderr.decode('utf-8', errors='replace') if stderr else "",
                "execution_time": execution_time,
                "working_directory": str(work_dir),
                "timestamp": datetime.now().isoformat()
            }
            
            if process.returncode == 0:
                logger.info(f"Command executed successfully: {command}")
            else:
                logger.warning(f"Command failed with code {process.returncode}: {command}")
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "execution_time": time.time() - start_time,
                "timestamp": datetime.now().isoformat()
            }
    
    async def _execute_streaming(
        self, 
        command: str, 
        work_dir: Path, 
        env: Dict[str, str]
    ) -> Dict[str, Any]:
        """执行流式输出命令"""
        process_id = self._get_process_id(command)
        start_time = time.time()
        
        try:
            # 创建进程
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True
            )
            
            # 存储进程引用
            self.running_processes[process_id] = process
            
            # 收集输出
            stdout_lines = []
            stderr_lines = []
            
            async def read_stream(stream, lines_list):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_str = line.decode('utf-8', errors='replace').rstrip()
                    lines_list.append(line_str)
                    logger.info(f"[{process_id}] {line_str}")
            
            # 同时读取stdout和stderr
            await asyncio.gather(
                read_stream(process.stdout, stdout_lines),
                read_stream(process.stderr, stderr_lines),
                return_exceptions=True
            )
            
            # 等待进程结束
            return_code = await process.wait()
            execution_time = time.time() - start_time
            
            # 从运行进程中移除
            self.running_processes.pop(process_id, None)
            
            result = {
                "success": return_code == 0,
                "process_id": process_id,
                "command": command,
                "return_code": return_code,
                "stdout": '\n'.join(stdout_lines),
                "stderr": '\n'.join(stderr_lines),
                "execution_time": execution_time,
                "working_directory": str(work_dir),
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Streaming command completed: {command}")
            return result
            
        except Exception as e:
            self.running_processes.pop(process_id, None)
            return {
                "success": False,
                "error": str(e),
                "process_id": process_id,
                "command": command,
                "execution_time": time.time() - start_time,
                "timestamp": datetime.now().isoformat()
            }
    
    async def start_background_process(
        self,
        command: str,
        working_directory: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """启动后台进程"""
        if not self._is_safe_command(command):
            return {
                "success": False,
                "error": "Command not allowed for security reasons",
                "command": command,
                "timestamp": datetime.now().isoformat()
            }
        
        process_id = self._get_process_id(command)
        work_dir = Path(working_directory) if working_directory else self.work_dir
        
        if not work_dir.exists():
            return {
                "success": False,
                "error": f"Working directory does not exist: {work_dir}",
                "command": command,
                "timestamp": datetime.now().isoformat()
            }
        
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        
        logger.info(f"Starting background process: {command}")
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True
            )
            
            self.running_processes[process_id] = process
            
            result = {
                "success": True,
                "process_id": process_id,
                "command": command,
                "pid": process.pid,
                "working_directory": str(work_dir),
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Background process started: {process_id} (PID: {process.pid})")
            return result
            
        except Exception as e:
            logger.error(f"Error starting background process: {e}")
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "timestamp": datetime.now().isoformat()
            }
    
    async def stop_process(self, process_id: str) -> Dict[str, Any]:
        """停止进程"""
        if process_id not in self.running_processes:
            return {
                "success": False,
                "error": f"Process not found: {process_id}",
                "timestamp": datetime.now().isoformat()
            }
        
        process = self.running_processes[process_id]
        
        try:
            # 尝试优雅终止
            process.terminate()
            
            # 等待进程结束
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                # 强制杀死进程
                process.kill()
                await process.wait()
            
            # 从列表中移除
            del self.running_processes[process_id]
            
            result = {
                "success": True,
                "process_id": process_id,
                "message": "Process stopped successfully",
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Process stopped: {process_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error stopping process {process_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "process_id": process_id,
                "timestamp": datetime.now().isoformat()
            }
    
    async def list_processes(self) -> Dict[str, Any]:
        """列出运行中的进程"""
        processes = []
        
        for process_id, process in self.running_processes.items():
            try:
                # 检查进程是否还在运行
                if process.poll() is None:
                    processes.append({
                        "process_id": process_id,
                        "pid": process.pid,
                        "status": "running"
                    })
                else:
                    processes.append({
                        "process_id": process_id,
                        "pid": process.pid,
                        "status": "terminated",
                        "return_code": process.returncode
                    })
            except Exception as e:
                processes.append({
                    "process_id": process_id,
                    "status": "error",
                    "error": str(e)
                })
        
        # 清理已终止的进程
        terminated_ids = [
            pid for pid, proc in self.running_processes.items() 
            if proc.poll() is not None
        ]
        for pid in terminated_ids:
            del self.running_processes[pid]
        
        return {
            "success": True,
            "processes": processes,
            "total_processes": len(processes),
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_process_output(self, process_id: str) -> Dict[str, Any]:
        """获取进程输出"""
        if process_id not in self.running_processes:
            return {
                "success": False,
                "error": f"Process not found: {process_id}",
                "timestamp": datetime.now().isoformat()
            }
        
        process = self.running_processes[process_id]
        
        try:
            # 非阻塞读取输出
            stdout_data = ""
            stderr_data = ""
            
            if process.stdout:
                try:
                    stdout_bytes = await asyncio.wait_for(
                        process.stdout.read(8192), 
                        timeout=0.1
                    )
                    stdout_data = stdout_bytes.decode('utf-8', errors='replace')
                except asyncio.TimeoutError:
                    pass
            
            if process.stderr:
                try:
                    stderr_bytes = await asyncio.wait_for(
                        process.stderr.read(8192), 
                        timeout=0.1
                    )
                    stderr_data = stderr_bytes.decode('utf-8', errors='replace')
                except asyncio.TimeoutError:
                    pass
            
            result = {
                "success": True,
                "process_id": process_id,
                "pid": process.pid,
                "stdout": stdout_data,
                "stderr": stderr_data,
                "is_running": process.poll() is None,
                "return_code": process.returncode,
                "timestamp": datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting process output {process_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "process_id": process_id,
                "timestamp": datetime.now().isoformat()
            }
    
    async def cleanup_all_processes(self) -> Dict[str, Any]:
        """清理所有运行中的进程"""
        stopped_processes = []
        errors = []
        
        for process_id in list(self.running_processes.keys()):
            try:
                result = await self.stop_process(process_id)
                if result["success"]:
                    stopped_processes.append(process_id)
                else:
                    errors.append(f"{process_id}: {result['error']}")
            except Exception as e:
                errors.append(f"{process_id}: {str(e)}")
        
        result = {
            "success": len(errors) == 0,
            "stopped_processes": stopped_processes,
            "errors": errors,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"Cleanup completed: {len(stopped_processes)} stopped, {len(errors)} errors")
        return result