"""Bash Skill - Claude官方Bash技能"""
import asyncio
import subprocess
import os
import signal
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
    
    def _clean_command(self, command: str) -> str:
        """清理和预处理命令"""
        # 移除可能的恶意字符
        command = command.strip()
        
        # 基本清理
        command = command.replace('\r\n', '\n').replace('\r', '\n')
        
        return command
    
    async def _execute_command(
        self,
        command: str,
        timeout: int = 30,
        restart: bool = False
    ) -> tuple[int, str, str]:
        """执行bash命令"""
        
        if restart:
            # 清理正在运行的进程
            await self._cleanup_processes()
        
        # 在工作目录中执行命令
        try:
            # Windows系统使用cmd，Linux使用bash
            if os.name == 'nt':
                # Windows命令处理
                if command.strip().startswith('cd '):
                    target_dir = command.strip()[3:].strip()
                    if target_dir:
                        abs_target = (self.work_dir / target_dir).resolve()
                        try:
                            # 检查目标目录是否在工作目录内
                            abs_target.relative_to(self.work_dir)
                            os.chdir(abs_target)
                            return 0, f"Changed directory to: {abs_target}", ""
                        except (ValueError, OSError) as e:
                            return 1, "", f"Cannot change directory: {e}"
                    else:
                        return 0, f"Current directory: {os.getcwd()}", ""
                
                # 使用shell=True在Windows上执行命令
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.work_dir),
                    shell=True
                )
            else:
                # Linux使用bash
                process = await asyncio.create_subprocess_exec(
                    '/bin/bash', '-c', command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.work_dir)
                )
            
            full_command = shell_cmd + [command]
            
            process = await asyncio.create_subprocess_exec(
                *full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir
            )
            
            # 存储进程以便后续清理
            process_key = f"proc_{id(process)}"
            self.running_processes[process_key] = process
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                
                return_code = process.returncode
                stdout_str = stdout.decode('utf-8', errors='replace')
                stderr_str = stderr.decode('utf-8', errors='replace')
                
                return return_code, stdout_str, stderr_str
                
            except asyncio.TimeoutError:
                # 超时，终止进程
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                
                return 124, "", f"Command timed out after {timeout} seconds"
            
            finally:
                # 清理进程记录
                if process_key in self.running_processes:
                    del self.running_processes[process_key]
                
        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return 1, "", f"Execution error: {str(e)}"
    
    async def _cleanup_processes(self):
        """清理正在运行的进程"""
        for process_key, process in list(self.running_processes.items()):
            try:
                if process.poll() is None:  # 进程还在运行
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass
            finally:
                if process_key in self.running_processes:
                    del self.running_processes[process_key]
    
    async def execute(self, **kwargs) -> SkillResult:
        """执行Bash命令"""
        command = kwargs.get("command")
        timeout = kwargs.get("timeout", 30)
        restart = kwargs.get("restart", False)
        
        if not command:
            return SkillResult(
                success=False,
                error="Command parameter is required"
            )
        
        # 清理命令
        command = self._clean_command(command)
        
        # 安全检查
        if not self._is_safe_command(command):
            return SkillResult(
                success=False,
                error=f"Command not allowed for security reasons: {command.split()[0] if command.split() else 'empty'}"
            )
        
        try:
            logger.info(f"Executing command: {command}")
            
            return_code, stdout, stderr = await self._execute_command(
                command, timeout, restart
            )
            
            # 准备输出
            output_parts = []
            
            if stdout:
                output_parts.append(f"STDOUT:\n{stdout}")
            
            if stderr:
                output_parts.append(f"STDERR:\n{stderr}")
            
            if not output_parts:
                output_parts.append("No output")
            
            output = "\n\n".join(output_parts)
            
            # 记录执行结果
            logger.info(f"Command completed with return code: {return_code}")
            
            return SkillResult(
                success=(return_code == 0),
                content=output,
                metadata={
                    "command": command,
                    "return_code": return_code,
                    "timeout": timeout,
                    "restart": restart,
                    "work_dir": str(self.work_dir)
                }
            )
            
        except Exception as e:
            logger.error(f"Error in bash execution: {e}")
            return SkillResult(
                success=False,
                error=f"Bash execution failed: {str(e)}",
                metadata={
                    "command": command,
                    "timeout": timeout,
                    "restart": restart
                }
            )
    
    async def cleanup(self):
        """清理资源"""
        await self._cleanup_processes()
        logger.info("Bash Skill cleaned up")