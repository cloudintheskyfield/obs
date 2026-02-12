#!/usr/bin/env python3
"""
FastAPI应用定义 - 独立模块
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config.config import load_config
from .skills.skill_manager import SkillManager

# 禁用uvicorn的访问日志记录
uvicorn_access = logging.getLogger("uvicorn.access")
uvicorn_access.disabled = True

# Pydantic models
class SkillExecuteRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = {}

# 创建FastAPI应用
config = load_config()
app = FastAPI(
    title="Omni Agent API",
    description="全能AI Agent - 支持Claude Skills三级架构",
    version="1.0.0"
)

# 添加CORS支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件服务
try:
    frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")
        print(f"Mounted frontend directory: {frontend_dir}")
except Exception as e:
    print(f"Failed to mount frontend static files: {e}")

# 全局skill manager
skill_manager: Optional[SkillManager] = None

@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    global skill_manager
    
    skills_config = {
        "work_dir": config.work_dir,
        "screenshot_dir": getattr(config, "screenshot_dir", "screenshots"),
        "enable_computer_use": getattr(config, "enable_computer_use", True),
        "enable_text_editor": getattr(config, "enable_text_editor", True),
        "enable_bash": getattr(config, "enable_bash", True),
        "skills_dir": getattr(config, "skills_dir", None),
    }
    skill_manager = SkillManager(skills_config)
    
    # 同时存储在app.state中
    app.state.skill_manager = skill_manager
    print("Skill manager initialized successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    global skill_manager
    if skill_manager is not None:
        await skill_manager.cleanup()
    print("Application shutdown complete")

# API 路由定义

@app.get("/")
async def root():
    """根路径 - 返回前端页面"""
    try:
        frontend_dir = Path(__file__).parent.parent.parent / "frontend"
        index_file = frontend_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file), media_type="text/html")
    except Exception as e:
        print(f"Failed to serve frontend: {e}")
    
    return JSONResponse({
        "name": "Omni Agent API",
        "version": "1.0.0",
        "description": "全能AI Agent - 支持Claude Skills三级架构",
        "message": "前端页面未找到，请访问 /docs 查看API文档"
    })

@app.get("/health")
async def health():
    """健康检查 - 静默模式"""
    skills_count = len(skill_manager.skills) if skill_manager else 0
    return {"status": "ok", "skills_count": skills_count}

@app.get("/skills")
async def skills():
    """获取技能列表"""
    if skill_manager is None:
        return JSONResponse({"skills": []})
    return JSONResponse({"skills": skill_manager.get_anthropic_tools()})

@app.post("/execute")
async def execute_skill(request_data: SkillExecuteRequest):
    """执行技能"""
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "Skill manager not initialized"})
    
    try:
        result = await skill_manager.execute_skill(request_data.tool_name, **request_data.parameters)
        return JSONResponse({
            "success": result.success,
            "content": result.content,
            "error": result.error,
            "metadata": result.metadata
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

# 导出app实例
__all__ = ["app"]