"""主入口点和CLI接口"""
import asyncio
import json
import sys
from typing import Dict, Any, Optional
from pathlib import Path

import typer
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.json import JSON
from rich.progress import Progress, SpinnerColumn, TextColumn
from loguru import logger

from .core.agent import OmniAgent
from .config.config import load_config
from .core.logger import start_live_logging, stop_live_logging
import sys
from pathlib import Path

# Add .claude/skills to Python path for skills
claude_skills_path = Path(__file__).parent.parent.parent / ".claude" / "skills"
if claude_skills_path.exists():
    sys.path.insert(0, str(claude_skills_path))

from skill_manager import SkillManager

app = typer.Typer(
    name="omni-agent",
    help="全能AI Agent - 支持多模态网页浏览、文件处理和终端执行",
    add_completion=False
)

console = Console()

# 全局Agent实例
agent: Optional[OmniAgent] = None


class SkillExecuteRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = {}


def create_fastapi_app() -> FastAPI:
    config = load_config()
    
    # 禁用uvicorn的访问日志记录
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.disabled = True

    fastapi_app = FastAPI(
        title="Omni Agent API",
        description="全能AI Agent - 支持Claude Skills三级架构",
        version="1.0.0"
    )
    
    # 添加CORS支持
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    skill_manager: Optional[SkillManager] = None

    # 挂载静态文件服务
    try:
        frontend_dir = Path(__file__).parent.parent.parent / "frontend"
        if frontend_dir.exists():
            fastapi_app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
            logger.info(f"Mounted frontend directory: {frontend_dir}")
    except Exception as e:
        logger.warning(f"Failed to mount frontend static files: {e}")

    @fastapi_app.on_event("startup")
    async def _startup() -> None:
        nonlocal skill_manager
        skills_config = {
            "work_dir": config.work_dir,
            "screenshot_dir": getattr(config, "screenshot_dir", "screenshots"),
            "enable_computer_use": getattr(config, "enable_computer_use", True),
            "enable_text_editor": getattr(config, "enable_text_editor", True),
            "enable_bash": getattr(config, "enable_bash", True),
            "skills_dir": getattr(config, "skills_dir", None),
        }
        skill_manager = SkillManager(skills_config)
        # 同时存储在 app.state 中
        fastapi_app.state.skill_manager = skill_manager

    @fastapi_app.on_event("shutdown")
    async def _shutdown() -> None:
        if skill_manager is not None:
            await skill_manager.cleanup()

    @fastapi_app.get("/")
    async def root():
        # 尝试返回前端页面，如果不存在则返回API信息
        try:
            frontend_dir = Path(__file__).parent.parent.parent / "frontend"
            index_file = frontend_dir / "index.html"
            if index_file.exists():
                return FileResponse(str(index_file))
        except Exception as e:
            logger.warning(f"Failed to serve frontend: {e}")
        
        # 如果前端不存在，返回API信息
        return JSONResponse({
            "name": "Omni Agent API",
            "version": "1.0.0",
            "description": "全能AI Agent - 支持Claude Skills三级架构",
            "endpoints": {
                "health": "/health",
                "skills": "/skills", 
                "execute": "/execute",
                "docs": "/docs",
                "frontend": "/static/"
            }
        })

    @fastapi_app.get("/health")
    async def health() -> JSONResponse:
        # 不打印健康检查日志，直接返回
        return JSONResponse({"status": "ok", "skills_count": len(skill_manager.skills) if skill_manager else 0})

    @fastapi_app.get("/skills")
    async def skills() -> JSONResponse:
        current_skill_manager = getattr(fastapi_app.state, 'skill_manager', None)
        if current_skill_manager is None:
            return JSONResponse({"skills": []})
        return JSONResponse({"skills": current_skill_manager.get_anthropic_tools()})
    
    @fastapi_app.post("/execute")
    async def execute_skill(request_data: SkillExecuteRequest) -> JSONResponse:
        current_skill_manager = getattr(fastapi_app.state, 'skill_manager', None)
        if current_skill_manager is None:
            return JSONResponse({"success": False, "error": "Skill manager not initialized"})
        
        try:
            result = await current_skill_manager.execute_skill(request_data.tool_name, **request_data.parameters)
            return JSONResponse({
                "success": result.success,
                "content": result.content,
                "error": result.error,
                "metadata": result.metadata
            })
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})

    return fastapi_app


fastapi_app = create_fastapi_app()


@app.command()
def start(
    live_logs: bool = typer.Option(False, "--live-logs", help="启用实时日志显示"),
    config_file: Optional[str] = typer.Option(None, "--config", help="配置文件路径")
):
    """启动Omni Agent交互式会话"""
    global agent
    
    console.print(Panel.fit(
        "🚀 [bold blue]Omni Agent[/bold blue] - 全能AI助手\n"
        "支持多模态网页浏览、文件处理、终端执行和Claude Skills",
        border_style="blue"
    ))
    
    try:
        # 加载配置
        if config_file:
            # TODO: 支持自定义配置文件
            pass
        config = load_config()
        
        # 启动实时日志（如果需要）
        if live_logs:
            start_live_logging()
        
        # 运行主循环
        asyncio.run(interactive_session(config, live_logs))
        
    except KeyboardInterrupt:
        console.print("\n👋 再见！")
    except Exception as e:
        console.print(f"❌ 启动失败: {e}", style="red")
        sys.exit(1)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload", help="启用代码热重载")
):
    config = load_config()
    
    if reload:
        # 开发模式：使用模块路径字符串以支持热重载
        uvicorn.run(
            "omni_agent.main:fastapi_app",
            host=host,
            port=port or getattr(config, "api_port", 8000),
            reload=True,
            reload_dirs=["src", ".claude", "frontend"],
            log_level="info",
            access_log=True
        )
    else:
        # 生产模式：直接传递app实例
        app_instance = create_fastapi_app()
        uvicorn.run(
            app_instance,
            host=host,
            port=port or getattr(config, "api_port", 8000),
            log_level="warning",  # 减少健康检查日志噪音
            access_log=False,     # 禁用访问日志
        )


async def interactive_session(config, live_logs: bool):
    """交互式会话"""
    global agent
    
    # 初始化Agent
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("正在初始化Agent...", total=None)
        
        async with OmniAgent(config) as agent:
            progress.update(task, description="✅ Agent初始化完成")
            
            if live_logs:
                await agent.start_live_monitoring()
            
            console.print("🎯 Agent已就绪！输入 'help' 查看帮助，输入 'quit' 退出。\n")
            
            while True:
                try:
                    # 获取用户输入
                    user_input = typer.prompt("\n📝 请输入命令或请求")
                    
                    if user_input.lower() in ['quit', 'exit', 'q']:
                        break
                    
                    if user_input.lower() == 'help':
                        show_help()
                        continue
                    
                    if user_input.lower() == 'status':
                        show_status()
                        continue
                    
                    if user_input.lower() == 'history':
                        show_history()
                        continue
                    
                    # 解析并处理请求
                    request = parse_user_input(user_input)
                    
                    # 处理请求
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        console=console
                    ) as progress:
                        task = progress.add_task("正在处理请求...", total=None)
                        
                        result = await agent.process_request(request)
                        
                        progress.update(task, description="✅ 请求处理完成")
                    
                    # 显示结果
                    display_result(result)
                    
                except KeyboardInterrupt:
                    console.print("\n⏹️ 请求已取消")
                    continue
                except Exception as e:
                    console.print(f"❌ 处理请求时出错: {e}", style="red")
                    continue
            
            if live_logs:
                await agent.stop_live_monitoring()


def parse_user_input(user_input: str) -> Dict[str, Any]:
    """解析用户输入为请求格式"""
    # 尝试解析JSON格式
    try:
        return json.loads(user_input)
    except json.JSONDecodeError:
        pass
    
    # 检查是否是特定命令格式
    if user_input.startswith("web:"):
        url = user_input[4:].strip()
        return {
            "type": "web_browsing",
            "url": url,
            "task": "浏览并分析网页内容"
        }
    
    elif user_input.startswith("file:"):
        parts = user_input[5:].strip().split(" ", 1)
        operation = parts[0]
        params = parts[1] if len(parts) > 1 else ""
        
        if operation == "read":
            return {
                "type": "file_operation",
                "operation": "read",
                "file_path": params
            }
        elif operation == "list":
            return {
                "type": "file_operation",
                "operation": "list",
                "directory": params or "."
            }
    
    elif user_input.startswith("terminal:"):
        command = user_input[9:].strip()
        return {
            "type": "terminal_execution",
            "operation": "execute",
            "command": command
        }
    
    elif user_input.startswith("skill:"):
        parts = user_input[6:].strip().split(" ", 1)
        skill_name = parts[0]
        params_str = parts[1] if len(parts) > 1 else "{}"
        
        try:
            parameters = json.loads(params_str)
        except json.JSONDecodeError:
            parameters = {"query": params_str}
        
        return {
            "type": "claude_skill",
            "skill": skill_name,
            "parameters": parameters
        }
    
    # 默认作为一般请求处理
    return {
        "type": "general",
        "prompt": user_input
    }


def display_result(result: Dict[str, Any]):
    """显示处理结果"""
    if result.get("success"):
        console.print("✅ [green]请求处理成功[/green]")
        
        # 显示任务ID
        if "task_id" in result:
            console.print(f"📋 任务ID: {result['task_id']}")
        
        # 显示具体结果
        if "result" in result:
            result_data = result["result"]
            
            # 根据结果类型选择显示方式
            if isinstance(result_data, dict):
                console.print("\n📊 结果详情:")
                console.print(JSON(json.dumps(result_data, ensure_ascii=False, indent=2)))
            elif isinstance(result_data, str):
                console.print(f"\n💬 结果: {result_data}")
            else:
                console.print(f"\n📄 结果: {result_data}")
    else:
        console.print("❌ [red]请求处理失败[/red]")
        if "error" in result:
            console.print(f"🔍 错误信息: {result['error']}")


def show_help():
    """显示帮助信息"""
    help_table = Table(title="🔧 Omni Agent 命令帮助", show_header=True)
    help_table.add_column("命令格式", style="cyan")
    help_table.add_column("描述", style="white")
    help_table.add_column("示例", style="green")
    
    help_table.add_row(
        "web:<URL>",
        "浏览网页并分析内容",
        "web:https://example.com"
    )
    help_table.add_row(
        "file:<操作> <路径>",
        "文件操作 (read/list等)",
        "file:read example.txt"
    )
    help_table.add_row(
        "terminal:<命令>",
        "执行终端命令",
        "terminal:ls -la"
    )
    help_table.add_row(
        "skill:<技能> <参数>",
        "执行Claude技能",
        "skill:web_search {\"query\": \"AI news\"}"
    )
    help_table.add_row(
        "JSON格式",
        "完整的请求格式",
        '{\"type\": \"web_browsing\", \"url\": \"...\"}'
    )
    help_table.add_row(
        "自然语言",
        "直接描述任务",
        "帮我分析这个网页的内容"
    )
    help_table.add_row(
        "status",
        "查看Agent状态",
        "status"
    )
    help_table.add_row(
        "history",
        "查看任务历史",
        "history"
    )
    help_table.add_row(
        "help",
        "显示此帮助",
        "help"
    )
    help_table.add_row(
        "quit/exit/q",
        "退出程序",
        "quit"
    )
    
    console.print(help_table)


def show_status():
    """显示Agent状态"""
    global agent
    
    if not agent:
        console.print("❌ Agent未初始化", style="red")
        return
    
    status = agent.get_status()
    
    status_table = Table(title="🔍 Agent 状态", show_header=True)
    status_table.add_column("项目", style="cyan")
    status_table.add_column("状态", style="white")
    
    status_table.add_row("运行状态", "🟢 运行中" if status["is_running"] else "🔴 已停止")
    status_table.add_row("总任务数", str(status["total_tasks"]))
    
    # 组件状态
    components = status["components"]
    for name, enabled in components.items():
        status_table.add_row(
            f"组件: {name}",
            "✅ 已加载" if enabled else "❌ 未加载"
        )
    
    # 配置信息
    config = status["config"]
    status_table.add_row("工作目录", config["work_dir"])
    status_table.add_row("VLLM地址", config["vllm_url"])
    status_table.add_row("文件操作", "✅ 允许" if config["allow_file_operations"] else "❌ 禁止")
    status_table.add_row("终端执行", "✅ 允许" if config["allow_terminal_execution"] else "❌ 禁止")
    
    console.print(status_table)


def show_history():
    """显示任务历史"""
    global agent
    
    if not agent:
        console.print("❌ Agent未初始化", style="red")
        return
    
    history = agent.get_task_history(limit=10)
    
    if not history:
        console.print("📝 暂无任务历史")
        return
    
    history_table = Table(title="📋 最近10个任务", show_header=True)
    history_table.add_column("任务ID", style="cyan")
    history_table.add_column("状态", style="white")
    history_table.add_column("请求类型", style="yellow")
    history_table.add_column("开始时间", style="green")
    
    for task in history:
        status_icon = {
            "completed": "✅",
            "failed": "❌",
            "in_progress": "🔄"
        }.get(task["status"], "❓")
        
        history_table.add_row(
            task["task_id"],
            f"{status_icon} {task['status']}",
            task["request"].get("type", "unknown"),
            task["start_time"][:19]  # 只显示日期时间部分
        )
    
    console.print(history_table)


@app.command()
def test(
    vllm_url: str = typer.Option(
        "http://223.109.239.14:10002/v1/chat/completions",
        "--vllm-url",
        help="VLLM服务地址"
    )
):
    """测试VLLM连接"""
    console.print("🔍 测试VLLM连接...")
    
    async def test_connection():
        from .core.vllm_client import VLLMClient
        from .config.config import VLLMConfig
        
        config = VLLMConfig(base_url=vllm_url)
        
        try:
            async with VLLMClient(config) as client:
                result = await client.chat_completion([
                    {"role": "user", "content": "Hello! 请回复'连接测试成功'"}
                ])
                
                if "choices" in result and result["choices"]:
                    response = result["choices"][0]["message"]["content"]
                    console.print(f"✅ 连接成功！回复: {response}", style="green")
                else:
                    console.print("❌ 连接失败：无效响应", style="red")
                    
        except Exception as e:
            console.print(f"❌ 连接失败: {e}", style="red")
    
    asyncio.run(test_connection())


@app.command()
def version():
    """显示版本信息"""
    from . import __version__
    console.print(f"🤖 Omni Agent v{__version__}")


if __name__ == "__main__":
    app()