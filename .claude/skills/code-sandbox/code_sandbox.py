"""
Code Sandbox Skill - Docker隔离代码执行
支持多种编程语言的安全代码执行
"""
import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger

try:
    from .base_skill import BaseSkill, SkillResult
except ImportError:
    from base_skill import BaseSkill, SkillResult


class CodeSandboxSkill(BaseSkill):
    """代码沙箱技能 - Docker容器隔离执行"""
    
    LANGUAGE_CONFIGS = {
        "python": {
            "image": "python:3.11-slim",
            "cmd_template": "python /workspace/code.py",
            "file_ext": ".py"
        },
        "javascript": {
            "image": "node:18-alpine",
            "cmd_template": "node /workspace/code.js",
            "file_ext": ".js"
        },
        "go": {
            "image": "golang:1.21-alpine",
            "cmd_template": "cd /workspace && go run code.go",
            "file_ext": ".go"
        },
        "rust": {
            "image": "rust:1.75-slim",
            "cmd_template": "cd /workspace && rustc code.rs && ./code",
            "file_ext": ".rs"
        },
        "java": {
            "image": "openjdk:17-slim",
            "cmd_template": "cd /workspace && javac Code.java && java Code",
            "file_ext": ".java"
        }
    }
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(
            name="code_sandbox",
            description="Execute code in isolated Docker containers"
        )
        self.config = config or {}
        self.workspace_dir = Path(self.config.get("workspace_dir", "/tmp/code_sandbox"))
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.add_parameter(
            "language",
            "str",
            "Programming language to run. Options: python, javascript, go, rust, java",
            True
        )
        self.add_parameter(
            "code",
            "str",
            "Source code to execute inside the sandbox",
            True
        )
        self.add_parameter(
            "files",
            "dict",
            "Optional supporting files as a filename-to-content map",
            False,
            {}
        )
        self.add_parameter(
            "timeout",
            "int",
            "Maximum execution time in seconds",
            False,
            30
        )
        self.add_parameter(
            "memory_limit",
            "str",
            "Docker memory limit such as 256m",
            False,
            "256m"
        )
        self.add_parameter(
            "cpu_limit",
            "str",
            "Docker CPU limit such as 1.0",
            False,
            "1.0"
        )
    
    async def execute(self, **kwargs) -> SkillResult:
        """
        执行代码沙箱
        
        参数:
            language: 编程语言 (python/javascript/go/rust/java)
            code: 要执行的代码
            files: 可选，输入文件字典 {filename: content}
            timeout: 超时时间（秒），默认30
            memory_limit: 内存限制，默认256m
            cpu_limit: CPU限制，默认1.0
        """
        try:
            language = kwargs.get("language", "python").lower()
            code = kwargs.get("code", "")
            files = kwargs.get("files", {})
            timeout = kwargs.get("timeout", 30)
            memory_limit = kwargs.get("memory_limit", "256m")
            cpu_limit = kwargs.get("cpu_limit", "1.0")
            
            if not code:
                return SkillResult(
                    success=False,
                    error="代码不能为空"
                )
            
            if language not in self.LANGUAGE_CONFIGS:
                return SkillResult(
                    success=False,
                    error=f"不支持的语言: {language}. 支持: {', '.join(self.LANGUAGE_CONFIGS.keys())}"
                )
            
            # 执行代码
            result = await self._run_in_docker(
                language=language,
                code=code,
                files=files,
                timeout=timeout,
                memory_limit=memory_limit,
                cpu_limit=cpu_limit
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Code sandbox execution failed: {e}")
            return SkillResult(
                success=False,
                error=f"执行失败: {str(e)}"
            )
    
    async def _run_in_docker(
        self,
        language: str,
        code: str,
        files: Dict[str, str],
        timeout: int,
        memory_limit: str,
        cpu_limit: str
    ) -> SkillResult:
        """在Docker容器中运行代码"""
        
        # 创建临时工作目录
        with tempfile.TemporaryDirectory(dir=self.workspace_dir) as temp_dir:
            temp_path = Path(temp_dir)
            
            # 获取语言配置
            lang_config = self.LANGUAGE_CONFIGS[language]
            code_filename = f"code{lang_config['file_ext']}"
            if language == "java":
                code_filename = "Code.java"
            
            # 写入代码文件
            code_file = temp_path / code_filename
            code_file.write_text(code, encoding="utf-8")
            
            # 写入额外文件
            for filename, content in files.items():
                file_path = temp_path / filename
                file_path.write_text(content, encoding="utf-8")
            
            # 构建Docker命令
            docker_cmd = [
                "docker", "run",
                "--rm",  # 自动删除容器
                "--network", "none",  # 禁用网络
                "--memory", memory_limit,  # 内存限制
                "--cpus", cpu_limit,  # CPU限制
                "--pids-limit", "100",  # 进程数限制
                "-v", f"{temp_path}:/workspace:ro",  # 只读挂载
                "-w", "/workspace",
                lang_config["image"],
                "sh", "-c", lang_config["cmd_template"]
            ]
            
            # 执行Docker命令
            start_time = time.time()
            
            try:
                process = await asyncio.create_subprocess_exec(
                    *docker_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # 等待执行完成（带超时）
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )
                    execution_time = time.time() - start_time
                    
                    # 解码输出
                    stdout_text = stdout.decode("utf-8", errors="replace")
                    stderr_text = stderr.decode("utf-8", errors="replace")
                    exit_code = process.returncode
                    
                    # 读取输出文件
                    output_files = {}
                    for file_path in temp_path.iterdir():
                        if file_path.name not in [code_filename] and not file_path.name.startswith('.'):
                            if file_path.is_file():
                                try:
                                    output_files[file_path.name] = file_path.read_text(encoding="utf-8")
                                except:
                                    output_files[file_path.name] = "<binary file>"
                    
                    # 构建结果
                    success = exit_code == 0
                    content = {
                        "stdout": stdout_text,
                        "stderr": stderr_text,
                        "exit_code": exit_code,
                        "execution_time": execution_time,
                        "output_files": output_files,
                        "language": language
                    }
                    
                    # 格式化输出信息
                    info_parts = [
                        f"**语言**: {language}",
                        f"**执行时间**: {execution_time:.2f}s",
                        f"**退出码**: {exit_code}"
                    ]
                    
                    if stdout_text:
                        info_parts.append(f"\n**标准输出**:\n```\n{stdout_text.strip()}\n```")
                    
                    if stderr_text:
                        info_parts.append(f"\n**错误输出**:\n```\n{stderr_text.strip()}\n```")
                    
                    if output_files:
                        info_parts.append(f"\n**生成文件**: {', '.join(output_files.keys())}")
                    
                    formatted_output = "\n".join(info_parts)

                    if not success and self._should_fallback_to_local(exit_code, stderr_text, language):
                        logger.warning("Docker sandbox unavailable, falling back to local execution")
                        return await self._run_locally(language, code, files, timeout)
                    
                    return SkillResult(
                        success=success,
                        content=formatted_output,
                        metadata=content,
                        error=stderr_text if not success else None
                    )
                    
                except asyncio.TimeoutError:
                    # 超时，杀死进程
                    process.kill()
                    await process.wait()
                    
                    return SkillResult(
                        success=False,
                        error=f"执行超时（>{timeout}秒）"
                    )
                    
            except Exception as e:
                logger.error(f"Docker execution error: {e}")
                if self._should_fallback_to_local(None, str(e), language):
                    logger.warning("Docker execution failed before start, falling back to local execution")
                    return await self._run_locally(language, code, files, timeout)
                return SkillResult(
                    success=False,
                    error=f"Docker执行错误: {str(e)}"
                )

    def _should_fallback_to_local(self, exit_code: Optional[int], error_text: str, language: str) -> bool:
        if language not in {"python", "javascript"}:
            return False

        normalized = (error_text or "").lower()
        fallback_markers = [
            "unable to find image",
            "tls handshake timeout",
            "docker执行错误",
            "cannot connect to the docker daemon",
            "docker: error response from daemon",
            "pull access denied",
        ]
        return exit_code == 125 or any(marker in normalized for marker in fallback_markers)

    async def _run_locally(
        self,
        language: str,
        code: str,
        files: Dict[str, str],
        timeout: int,
    ) -> SkillResult:
        with tempfile.TemporaryDirectory(dir=self.workspace_dir) as temp_dir:
            temp_path = Path(temp_dir)
            lang_config = self.LANGUAGE_CONFIGS[language]
            code_filename = f"code{lang_config['file_ext']}"
            code_file = temp_path / code_filename
            code_file.write_text(code, encoding="utf-8")

            for filename, content in files.items():
                file_path = temp_path / filename
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")

            if language == "python":
                command = [sys.executable, str(code_file)]
            elif language == "javascript":
                node_bin = shutil.which("node")
                if not node_bin:
                    return SkillResult(success=False, error="本地回退执行失败：未找到 node")
                command = [node_bin, str(code_file)]
            else:
                return SkillResult(success=False, error=f"本地回退不支持语言: {language}")

            start_time = time.time()
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(temp_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return SkillResult(success=False, error=f"本地回退执行超时（>{timeout}秒）")

            execution_time = time.time() - start_time
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            exit_code = process.returncode

            info_parts = [
                f"**语言**: {language}",
                f"**执行方式**: local fallback",
                f"**执行时间**: {execution_time:.2f}s",
                f"**退出码**: {exit_code}"
            ]
            if stdout_text:
                info_parts.append(f"\n**标准输出**:\n```\n{stdout_text.strip()}\n```")
            if stderr_text:
                info_parts.append(f"\n**错误输出**:\n```\n{stderr_text.strip()}\n```")

            return SkillResult(
                success=exit_code == 0,
                content="\n".join(info_parts),
                error=stderr_text if exit_code != 0 else None,
                metadata={
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "exit_code": exit_code,
                    "execution_time": execution_time,
                    "language": language,
                    "execution_mode": "local_fallback",
                }
            )
    
    async def cleanup(self):
        """清理资源"""
        logger.info("Code sandbox cleanup completed")
    
    def get_metadata(self) -> Dict[str, Any]:
        """返回技能元数据"""
        return {
            "name": self.name,
            "description": self.description,
            "supported_languages": list(self.LANGUAGE_CONFIGS.keys()),
            "parameters": {
                "language": {
                    "type": "string",
                    "required": True,
                    "options": list(self.LANGUAGE_CONFIGS.keys())
                },
                "code": {
                    "type": "string",
                    "required": True
                },
                "files": {
                    "type": "object",
                    "required": False
                },
                "timeout": {
                    "type": "integer",
                    "default": 30
                },
                "memory_limit": {
                    "type": "string",
                    "default": "256m"
                },
                "cpu_limit": {
                    "type": "string",
                    "default": "1.0"
                }
            }
        }
