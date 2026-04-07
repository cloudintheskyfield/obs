"""Bash Skill - Claude官方Bash技能"""
import asyncio
import subprocess
import os
import signal
from typing import Optional, Dict, Any
from pathlib import Path

from loguru import logger

from base_skill import BaseSkill, SkillResult


class BashSkill(BaseSkill):
    """Bash Skill - 模拟Claude的Bash执行能力"""
    
    def __init__(self, work_dir: str = "workspace"):
        super().__init__(
            name="bash",
            description="Run commands in a bash shell. Commands will be executed in the workspace directory. Use this to perform system operations, run scripts, install packages, and interact with the filesystem"
        )
        
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(exist_ok=True)
        
        self.allowed_commands = {
            'ls', 'dir', 'pwd', 'cd', 'echo', 'cat', 'head', 'tail',
            'find', 'grep', 'sort', 'uniq', 'wc', 'du', 'df', 'which',
            'cp', 'mv', 'rm', 'mkdir', 'rmdir', 'touch', 'chmod', 'chown',
            'git', 'python', 'python3', 'pip', 'pip3', 'uv',
            'node', 'npm', 'yarn', 'pnpm',
            'cargo', 'rustc', 'go', 'java', 'javac', 
            'gcc', 'g++', 'make', 'cmake',
            'ps', 'kill', 'top', 'htop', 'free', 'uptime',
            'curl', 'wget', 'ping', 'netstat', 'ss',
            'zip', 'unzip', 'tar', 'gzip', 'gunzip',
            'awk', 'sed', 'cut', 'tr',
            'apt', 'yum', 'dnf', 'pacman', 'brew'
        }
        
        self.dangerous_commands = {
            'rm -rf /', 'rm -rf /*', 'rm -rf .*',
            'dd if=/dev/random', 'dd if=/dev/zero',
            'mkfs', 'fdisk', 'parted', 'gparted',
            'shutdown', 'reboot', 'halt', 'poweroff',
            'init 0', 'init 6', 'systemctl poweroff', 'systemctl reboot',
            'killall -9', 'pkill -9',
            'chmod -R 777 /', 'chown -R root:root /',
            ':(){ :|:& };:',
        }
        
        self.running_processes: Dict[str, subprocess.Popen] = {}
        
        self.add_parameter(
            "command",
            "str",
            "The bash command to execute. Can be a simple command or a complex shell script with pipes, redirects, etc.",
            True
        )
        self.add_parameter(
            "timeout",
            "int",
            "Command execution timeout in seconds. Defaults to 30 seconds",
            False,
            30
        )
        self.add_parameter(
            "restart",
            "bool",
            "Whether to restart the shell session before running this command",
            False,
            False
        )
    
    def _is_safe_command(self, command: str) -> bool:
        """检查命令是否安全"""
        command_lower = command.lower().strip()
        
        # 检查危险命令
        for dangerous in self.dangerous_commands:
            if dangerous in command_lower:
                logger.warning(f"Dangerous command detected: {dangerous}")
                return False
        
        # 检查基本命令是否在允许列表中
        first_word = command.split()[0] if command.split() else ""
        
        # 特殊处理：允许带路径的命令
        if '/' in first_word:
            first_word = Path(first_word).name
        
        # 移除sudo前缀检查实际命令
        if first_word == 'sudo' and len(command.split()) > 1:
            first_word = command.split()[1]
        
        if first_word not in self.allowed_commands:
            logger.warning(f"Command not in allowed list: {first_word}")
            return False
        
        return True
    
    def _get_process_id(self) -> str:
        """生成进程ID"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"bash_{timestamp}"
    
    async def execute_command(
        self,
        command: str,
        timeout: int = 30,
        background: bool = False
    ) -> SkillResult:
        """执行Bash命令"""
        if not self._is_safe_command(command):
            return SkillResult(
                success=False,
                error="Command not allowed for security reasons",
                metadata={"command": command}
            )
        
        logger.info(f"Executing bash command: {command}")
        
        try:
            if background:
                return await self._execute_background(command)
            else:
                return await self._execute_blocking(command, timeout)
                
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return SkillResult(
                success=False,
                error=str(e),
                metadata={"command": command}
            )
    
    async def _execute_blocking(self, command: str, timeout: int) -> SkillResult:
        """执行阻塞命令"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            # 使用asyncio.create_subprocess_shell执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy()
            )
            
            # 等待命令完成或超时
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return SkillResult(
                    success=False,
                    error=f"Command timed out after {timeout} seconds",
                    metadata={
                        "command": command,
                        "timeout": timeout,
                        "execution_time": asyncio.get_event_loop().time() - start_time
                    }
                )
            
            execution_time = asyncio.get_event_loop().time() - start_time
            
            # 解码输出
            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""
            
            # 组合输出
            output_text = ""
            if stdout_text:
                output_text += stdout_text
            if stderr_text:
                if output_text:
                    output_text += "\n"
                output_text += stderr_text
            
            success = process.returncode == 0
            
            result = SkillResult(
                success=success,
                content=output_text or f"Command executed {'successfully' if success else 'with errors'}",
                metadata={
                    "command": command,
                    "return_code": process.returncode,
                    "execution_time": execution_time,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "working_directory": str(self.work_dir)
                }
            )
            
            if success:
                logger.info(f"Command executed successfully: {command}")
            else:
                logger.warning(f"Command failed with code {process.returncode}: {command}")
            
            return result
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                metadata={
                    "command": command,
                    "execution_time": asyncio.get_event_loop().time() - start_time
                }
            )
    
    async def _execute_background(self, command: str) -> SkillResult:
        """执行后台命令"""
        process_id = self._get_process_id()
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
                env=os.environ.copy()
            )
            
            self.running_processes[process_id] = process
            
            result = SkillResult(
                success=True,
                content=f"Command started in background with process ID: {process_id}",
                metadata={
                    "command": command,
                    "process_id": process_id,
                    "pid": process.pid,
                    "working_directory": str(self.work_dir),
                    "background": True
                }
            )
            
            logger.info(f"Background process started: {process_id} (PID: {process.pid})")
            return result
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                metadata={"command": command, "background": True}
            )
    
    async def stop_process(self, process_id: str) -> SkillResult:
        """停止后台进程"""
        if process_id not in self.running_processes:
            return SkillResult(
                success=False,
                error=f"Process not found: {process_id}"
            )
        
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
            
            result = SkillResult(
                success=True,
                content=f"Process {process_id} stopped successfully",
                metadata={"process_id": process_id}
            )
            
            logger.info(f"Process stopped: {process_id}")
            return result
            
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                metadata={"process_id": process_id}
            )
    
    async def list_processes(self) -> SkillResult:
        """列出运行中的进程"""
        processes = []
        
        for process_id, process in self.running_processes.items():
            try:
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
        
        result = SkillResult(
            success=True,
            content=f"Found {len(processes)} processes",
            metadata={
                "processes": processes,
                "total_processes": len(processes)
            }
        )
        
        return result
    
    async def cleanup_all_processes(self) -> SkillResult:
        """清理所有运行中的进程"""
        stopped_processes = []
        errors = []
        
        for process_id in list(self.running_processes.keys()):
            try:
                result = await self.stop_process(process_id)
                if result.success:
                    stopped_processes.append(process_id)
                else:
                    errors.append(f"{process_id}: {result.error}")
            except Exception as e:
                errors.append(f"{process_id}: {str(e)}")
        
        result = SkillResult(
            success=len(errors) == 0,
            content=f"Cleanup completed: {len(stopped_processes)} stopped, {len(errors)} errors",
            metadata={
                "stopped_processes": stopped_processes,
                "errors": errors
            }
        )
        
        logger.info(f"Cleanup completed: {len(stopped_processes)} stopped, {len(errors)} errors")
        return result
    
    async def execute(self, **kwargs) -> SkillResult:
        """执行Bash操作"""
        command = kwargs.get("command")
        timeout = kwargs.get("timeout", 30)
        background = kwargs.get("background", False)
        
        if not command:
            return SkillResult(
                success=False,
                error="Command parameter is required"
            )
        
        # 处理特殊命令
        if command == "list_processes":
            return await self.list_processes()
        
        elif command.startswith("stop_process "):
            process_id = command.split(" ", 1)[1].strip()
            return await self.stop_process(process_id)
        
        elif command == "cleanup_all":
            return await self.cleanup_all_processes()
        
        else:
            return await self.execute_command(command, timeout, background)
    
    async def cleanup(self):
        """清理资源"""
        await self.cleanup_all_processes()
        logger.info("Bash Skill cleaned up")
