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
            'sleep', 'wait', 'timeout', 'watch',
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

            # Filter out benign filesystem noise (e.g. stale .rnd symlink on macOS hosts)
            BENIGN_STDERR_PATTERNS = [".rnd", "No such file or directory"]
            filtered_stderr_lines = [
                ln for ln in stderr_text.splitlines()
                if not all(pat in ln for pat in BENIGN_STDERR_PATTERNS)
            ]
            clean_stderr = "\n".join(filtered_stderr_lines)

            # If exit code 1 and stdout has real content and all stderr was benign, treat as success
            returncode = process.returncode
            if returncode == 1 and stdout_text.strip() and not clean_stderr.strip():
                returncode = 0

            # 组合输出
            output_text = ""
            if stdout_text:
                output_text += stdout_text
            if clean_stderr:
                if output_text:
                    output_text += "\n"
                output_text += clean_stderr

            success = returncode == 0

            # curl exit code 7 = connection refused; if targeting localhost/127.0.0.1
            # from inside Docker the host service is unreachable — give the agent an
            # actionable hint so it retries with host.docker.internal.
            docker_hint = ""
            if not success and returncode == 7:
                import re as _re
                if _re.search(r"https?://(127\.0\.0\.1|localhost)\b", command):
                    fixed_cmd = _re.sub(
                        r"(https?://)(?:127\.0\.0\.1|localhost)(\b)",
                        r"\1host.docker.internal\2",
                        command,
                    )
                    docker_hint = (
                        "\n\n⚠️ Docker networking: this agent runs inside a container. "
                        "Services on the host are NOT reachable via 127.0.0.1 or localhost. "
                        f"Use host.docker.internal instead.\n"
                        f"Corrected command: {fixed_cmd}"
                    )

            result = SkillResult(
                success=success,
                content=(output_text or f"Command executed {'successfully' if success else 'with errors'}") + docker_hint,
                metadata={
                    "command": command,
                    "return_code": returncode,
                    "execution_time": execution_time,
                    "stdout": stdout_text,
                    "stderr": clean_stderr,
                    "working_directory": str(self.work_dir)
                }
            )
            
            if success:
                logger.info(f"Command executed successfully: {command}")
            else:
                logger.warning(f"Command failed with code {returncode}: {command}")
            
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
        """执行后台命令，实时捕获输出供轮询"""
        process_id = self._get_process_id()

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy()
            )

            # State buffer for this process
            state = {
                "process": process,
                "command": command,
                "stdout_lines": [],
                "stderr_lines": [],
                "running": True,
                "exit_code": None,
                "started_at": asyncio.get_event_loop().time(),
            }
            self.running_processes[process_id] = state

            async def _drain_stream(stream, target_list):
                try:
                    async for raw in stream:
                        line = raw.decode("utf-8", errors="replace").rstrip("\n")
                        target_list.append(line)
                except Exception:
                    pass

            async def _watch():
                await asyncio.gather(
                    _drain_stream(process.stdout, state["stdout_lines"]),
                    _drain_stream(process.stderr, state["stderr_lines"]),
                )
                await process.wait()
                state["running"] = False
                state["exit_code"] = process.returncode

            asyncio.create_task(_watch())

            logger.info(f"Background process started: {process_id} (PID: {process.pid})")
            return SkillResult(
                success=True,
                content=(
                    f"Background process started.\n"
                    f"process_id: {process_id}\n"
                    f"PID: {process.pid}\n"
                    f"Use: get_output {process_id}  — to poll output\n"
                    f"Use: stop_process {process_id} — to terminate"
                ),
                metadata={
                    "command": command,
                    "process_id": process_id,
                    "pid": process.pid,
                    "working_directory": str(self.work_dir),
                    "background": True,
                },
            )

        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                metadata={"command": command, "background": True},
            )

    async def get_output(self, process_id: str) -> SkillResult:
        """轮询后台进程的实时输出和状态"""
        state = self.running_processes.get(process_id)
        if state is None:
            return SkillResult(
                success=False,
                error=f"No background process found with id: {process_id}. Use list_processes to see active processes."
            )

        stdout_text = "\n".join(state["stdout_lines"])
        stderr_text = "\n".join(state["stderr_lines"])
        running = state["running"]
        exit_code = state["exit_code"]
        elapsed = asyncio.get_event_loop().time() - state["started_at"]

        if running:
            status_line = f"Status: RUNNING  (elapsed: {elapsed:.1f}s)"
        else:
            status_line = f"Status: FINISHED  exit_code={exit_code}  elapsed={elapsed:.1f}s"

        parts = [status_line]
        if stdout_text:
            parts.append(f"--- stdout ---\n{stdout_text}")
        if stderr_text:
            parts.append(f"--- stderr ---\n{stderr_text}")
        if not stdout_text and not stderr_text:
            parts.append("(no output yet)")

        return SkillResult(
            success=True,
            content="\n".join(parts),
            metadata={
                "process_id": process_id,
                "running": running,
                "exit_code": exit_code,
                "elapsed_s": round(elapsed, 1),
                "stdout_lines": len(state["stdout_lines"]),
                "stderr_lines": len(state["stderr_lines"]),
            },
        )
    
    async def stop_process(self, process_id: str) -> SkillResult:
        """停止后台进程"""
        state = self.running_processes.get(process_id)
        if state is None:
            return SkillResult(
                success=False,
                error=f"Process not found: {process_id}"
            )

        process = state["process"]
        try:
            if state["running"]:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                state["running"] = False
                state["exit_code"] = process.returncode

            del self.running_processes[process_id]
            logger.info(f"Process stopped: {process_id}")
            return SkillResult(
                success=True,
                content=f"Process {process_id} stopped (exit_code={state['exit_code']})",
                metadata={"process_id": process_id, "exit_code": state["exit_code"]}
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                metadata={"process_id": process_id}
            )
    
    async def list_processes(self) -> SkillResult:
        """列出后台进程状态"""
        rows = []
        finished_ids = []
        for process_id, state in self.running_processes.items():
            status = "RUNNING" if state["running"] else f"DONE(exit={state['exit_code']})"
            elapsed = asyncio.get_event_loop().time() - state["started_at"]
            rows.append(
                f"  {process_id}  {status}  elapsed={elapsed:.1f}s  "
                f"stdout_lines={len(state['stdout_lines'])}  "
                f"cmd={state['command'][:60]}"
            )
            if not state["running"]:
                finished_ids.append(process_id)

        if not rows:
            summary = "No background processes."
        else:
            summary = "Background processes:\n" + "\n".join(rows)
            summary += "\n\nTip: use  get_output <process_id>  to read output."

        return SkillResult(
            success=True,
            content=summary,
            metadata={"total": len(rows), "finished": len(finished_ids)},
        )
    
    async def cleanup_all_processes(self) -> SkillResult:
        """清理所有后台进程"""
        stopped, errors = [], []
        for process_id in list(self.running_processes.keys()):
            try:
                r = await self.stop_process(process_id)
                (stopped if r.success else errors).append(process_id)
            except Exception as e:
                errors.append(f"{process_id}: {e}")
        logger.info(f"Cleanup: {len(stopped)} stopped, {len(errors)} errors")
        return SkillResult(
            success=len(errors) == 0,
            content=f"Cleanup done: {len(stopped)} stopped, {len(errors)} errors",
            metadata={"stopped": stopped, "errors": errors},
        )
    
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

        elif command.startswith("get_output "):
            process_id = command.split(" ", 1)[1].strip()
            return await self.get_output(process_id)

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
