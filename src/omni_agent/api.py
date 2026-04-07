#!/usr/bin/env python3
"""
FastAPI应用定义 - 独立模块
"""
import logging
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
import httpx

from .config.config import load_config
import sys
from pathlib import Path

# Add .claude/skills and root skills to Python path for skills
claude_skills_path = Path(__file__).parent.parent.parent / ".claude" / "skills"
root_skills_path = Path(__file__).parent.parent.parent / "skills"
if claude_skills_path.exists():
    sys.path.insert(0, str(claude_skills_path))
if root_skills_path.exists():
    sys.path.insert(0, str(root_skills_path))

from skill_manager import SkillManager
from .core.vllm_client import VLLMClient
from .agents.plan_agent import PlanAgent
from .agents.execution_engine import ExecutionEngine


class NoCacheStaticFiles(StaticFiles):
    """禁用缓存的静态文件服务"""
    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

# 禁用uvicorn的访问日志记录
uvicorn_access = logging.getLogger("uvicorn.access")
uvicorn_access.disabled = True

# Pydantic models
class SkillExecuteRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = {}

class LocationUpdateRequest(BaseModel):
    session_id: str
    lat: float
    lon: float
    accuracy_m: Optional[float] = None

class LocationResolveRequest(BaseModel):
    session_id: str

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

# 挂载静态文件服务（禁用缓存）
try:
    frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/static", NoCacheStaticFiles(directory=str(frontend_dir)), name="static")
        print(f"Mounted frontend directory: {frontend_dir}")
except Exception as e:
    print(f"Failed to mount frontend static files: {e}")

# 全局变量
skill_manager: Optional[SkillManager] = None
vllm_client: Optional[VLLMClient] = None
chat_sessions: Dict[str, List[Dict[str, Any]]] = {}
session_locations: Dict[str, Dict[str, Any]] = {}

async def _resolve_location_from_ip(request: Request) -> Optional[Dict[str, Any]]:
    """Resolve approximate location from IP.

    Best-effort only. Returns None if lookup fails.
    """
    ip = None
    try:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            ip = xff.split(",")[0].strip()
    except Exception:
        ip = None
    if not ip:
        try:
            ip = request.client.host if request.client else None
        except Exception:
            ip = None

    if not ip:
        return None

    # Local dev: browser talks to 127.0.0.1, so we need public IP for IP-based geo.
    if ip in {"127.0.0.1", "::1"}:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get("https://api.ipify.org?format=json")
                if r.status_code == 200:
                    ip = (r.json() or {}).get("ip") or ip
        except Exception as e:
            logger.debug(f"Public IP resolve failed: {e}")
            return None

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"https://ipapi.co/{ip}/json/")
            if resp.status_code != 200:
                return None
            data = resp.json()

        lat = data.get("latitude")
        lon = data.get("longitude")
        if lat is None or lon is None:
            return None

        return {
            "source": "ip",
            "lat": float(lat),
            "lon": float(lon),
            "city": data.get("city"),
            "region": data.get("region"),
            "country_name": data.get("country_name"),
            "ip": ip,
        }
    except Exception as e:
        logger.warning(f"IP location resolve failed: {e}")
        return None

async def _execute_tool_call(tool_name: str, tool_input: Dict[str, Any], session_id: Optional[str] = None) -> str:
    """执行工具调用"""
    if not skill_manager:
        return "工具管理器未初始化"
    
    try:
        if tool_name == "web_search" and session_id:
            loc = session_locations.get(session_id)
            if loc and isinstance(loc, dict):
                for k in ["lat", "lon", "city", "region", "country_name"]:
                    if k in loc and k not in tool_input:
                        tool_input[k] = loc.get(k)
                tool_input["location_source"] = loc.get("source")
                if loc.get("accuracy_m") is not None:
                    tool_input["accuracy_m"] = loc.get("accuracy_m")

        result = await skill_manager.execute_skill(tool_name, **tool_input)
        if result.success:
            return result.content or "执行成功"
        else:
            return f"工具执行失败: {result.error}"
    except Exception as e:
        logger.error(f"Tool execution error: {e}")
        return f"工具执行异常: {str(e)}"

@app.post("/location")
async def update_location(payload: LocationUpdateRequest):
    """Update precise location from browser geolocation."""
    session_locations[payload.session_id] = {
        "source": "geolocation",
        "lat": payload.lat,
        "lon": payload.lon,
        "accuracy_m": payload.accuracy_m,
    }
    return JSONResponse({"success": True})

@app.post("/location/resolve")
async def resolve_location(payload: LocationResolveRequest, request: Request):
    """Resolve location automatically (IP-based) and cache for the session."""
    if payload.session_id in session_locations:
        return JSONResponse({"success": True, "location": session_locations[payload.session_id]})

    resolved = await _resolve_location_from_ip(request)
    if resolved:
        session_locations[payload.session_id] = resolved
        return JSONResponse({"success": True, "location": resolved})
    return JSONResponse({"success": False, "error": "Unable to resolve location"})

@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    global skill_manager, vllm_client
    
    skills_config = {
        "work_dir": config.work_dir,
        "screenshot_dir": getattr(config, "screenshot_dir", "screenshots"),
        "enable_computer_use": getattr(config, "enable_computer_use", True),
        "enable_text_editor": getattr(config, "enable_text_editor", True),
        "enable_bash": getattr(config, "enable_bash", True),
        "skills_dir": getattr(config, "skills_dir", None),
    }
    skill_manager = SkillManager(skills_config)
    
    # 初始化VLLM客户端
    vllm_client = VLLMClient(config.vllm)
    await vllm_client.__aenter__()
    
    # 初始化Plan Agent
    available_skills = list(skill_manager.skills.keys())
    plan_agent = PlanAgent(vllm_client, [name for name in skill_manager.skills.keys()])
    
    execution_engine = ExecutionEngine(vllm_client, skill_manager, plan_agent)
    app.state.execution_engine = execution_engine
    
    from .agents.streaming_agent import StreamingAgent
    streaming_agent = StreamingAgent(vllm_client, skill_manager, execution_engine, plan_agent)
    app.state.streaming_agent = streaming_agent
    
    logger.info("Omni Agent API 启动完成")
    
    # 同时存储在app.state中
    app.state.skill_manager = skill_manager
    app.state.vllm_client = vllm_client
    app.state.plan_agent = plan_agent
    app.state.execution_engine = execution_engine
    print("Skill manager initialized successfully")
    print(f"VLLM client initialized: {config.vllm.base_url}")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    global skill_manager, vllm_client
    if skill_manager is not None:
        await skill_manager.cleanup()
    if vllm_client is not None:
        await vllm_client.__aexit__(None, None, None)
    print("Application shutdown complete")

# API 路由定义

@app.get("/")
async def root():
    """根路径 - 返回前端页面"""
    try:
        frontend_dir = Path(__file__).parent.parent.parent / "frontend"
        index_file = frontend_dir / "index.html"
        if index_file.exists():
            response = FileResponse(str(index_file), media_type="text/html")
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
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
    skills_count = len(skill_manager.get_anthropic_tools()) if skill_manager else 0
    return {"status": "ok", "skills_count": skills_count}

@app.get("/runtime")
async def runtime_status():
    """Provide frontend-friendly runtime metadata for Claude Code style status panels."""
    skills_count = len(skill_manager.get_anthropic_tools()) if skill_manager else 0
    return JSONResponse({
        "status": "ok" if vllm_client is not None else "degraded",
        "runtime": {
            "model": config.vllm.model,
            "api_base_url": config.vllm.base_url,
            "work_dir": config.work_dir,
            "screenshot_dir": config.screenshot_dir,
            "allow_file_operations": config.allow_file_operations,
            "allow_terminal_execution": config.allow_terminal_execution,
            "enable_computer_use": config.enable_computer_use,
            "enable_text_editor": config.enable_text_editor,
            "enable_bash": config.enable_bash,
            "skills_count": skills_count,
            "web_headless": config.web_browsing.headless,
            "web_timeout": config.web_browsing.timeout,
            "api_port": config.api_port,
        }
    })

@app.get("/skills")
async def skills():
    """获取技能列表"""
    if skill_manager is None:
        return JSONResponse({"skills": []})
    return JSONResponse({"skills": skill_manager.get_anthropic_tools()})

@app.post("/chat/stream")
async def chat_stream(request_data: SkillExecuteRequest):
    """流式聊天"""
    if vllm_client is None:
        return JSONResponse({"success": False, "error": "VLLM client not initialized"})
    
    message = request_data.parameters.get("message", "")
    session_id = request_data.parameters.get("session_id", "default")
    mode = request_data.parameters.get("mode", "agent")
    permission_mode = request_data.parameters.get("permission_mode", "ask")
    permission_confirmed = bool(request_data.parameters.get("permission_confirmed", False))
    
    async def generate():
        try:
            # 获取或创建会话历史
            if session_id not in chat_sessions:
                chat_sessions[session_id] = []
            
            # 添加用户消息到会话历史
            chat_sessions[session_id].append({
                "role": "user",
                "content": message
            })
            
            # 使用流式引擎处理请求 (取代旧版 execution_engine 块)
            streaming_agent = app.state.streaming_agent
            async for chunk in streaming_agent.chat_stream(
                session_id,
                chat_sessions,
                mode=mode,
                permission_mode=permission_mode,
                permission_confirmed=permission_confirmed,
            ):
                yield chunk
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"Chat stream error: {error_detail}")
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/execute")
async def execute_skill(request_data: SkillExecuteRequest):
    """执行技能"""
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "Skill manager not initialized"})
    
    # 处理聊天请求
    if request_data.tool_name == "chat":
        message = request_data.parameters.get("message", "")
        session_id = request_data.parameters.get("session_id", "default")
        
        if vllm_client is None:
            return JSONResponse({
                "success": False,
                "error": "VLLM client not initialized"
            })
        
        try:
            # 获取或创建会话历史
            if session_id not in chat_sessions:
                chat_sessions[session_id] = [
                    {
                        "role": "system",
                        "content": """你是Omni Agent智能助手。

**工具使用规则**：
当用户询问天气、新闻、股票等实时信息时，直接输出：
<tool_call>
{"tool": "web_search", "query": "搜索内容"}
</tool_call>

**处理搜索结果**：
1. 如果搜索结果包含"**天气查询指南**"、"**新闻资讯指南**"等标题：
   - 说明搜索API暂时无法获取实时数据
   - 提取结果中的**推荐网站**和**快速查询方式**
   - 用友好的语言告知用户可以通过这些途径获取准确信息
   
2. 如果搜索结果包含实际数据：
   - 直接基于数据回答用户

**回复示例**：
"我为您查询了天气信息。由于API限制，建议您通过以下方式查看：中国天气网、微信小程序等都能提供实时准确的天气数据。"

用简洁、友好的Markdown格式回复。"""
                    }
                ]
            
            # 添加用户消息
            chat_sessions[session_id].append({
                "role": "user",
                "content": message
            })
            
            # 调用VLLM API (不传递tools参数)
            response = await vllm_client.chat_completion(
                messages=chat_sessions[session_id],
                temperature=0.7,
                max_tokens=2000
            )
            
            # 检查响应
            if "choices" in response and response["choices"]:
                assistant_message = response["choices"][0]["message"]["content"]
                
                # 检查是否包含tool_call标签
                import re
                tool_call_match = re.search(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', assistant_message, re.DOTALL)
                
                if tool_call_match:
                    try:
                        # 解析工具调用
                        tool_data = json.loads(tool_call_match.group(1))
                        tool_name = tool_data.get("tool")
                        tool_query = tool_data.get("query", "")
                        
                        # 保存助手的工具请求
                        chat_sessions[session_id].append({
                            "role": "assistant",
                            "content": assistant_message
                        })
                        
                        # 执行工具
                        logger.info(f"Executing tool: {tool_name} with query: {tool_query}")
                        tool_result = await _execute_tool_call(tool_name, {"query": tool_query}, session_id=session_id)
                        
                        # 添加工具结果到历史
                        chat_sessions[session_id].append({
                            "role": "user",
                            "content": f"[工具执行结果]\n{tool_result}\n\n请基于以上搜索结果回答我之前的问题。"
                        })
                        
                        # 第二次调用获取最终答案
                        final_response = await vllm_client.chat_completion(
                            messages=chat_sessions[session_id],
                            temperature=0.7,
                            max_tokens=2000
                        )
                        
                        if "choices" in final_response and final_response["choices"]:
                            final_message = final_response["choices"][0]["message"]["content"]
                            
                            chat_sessions[session_id].append({
                                "role": "assistant",
                                "content": final_message
                            })
                            
                            return JSONResponse({
                                "success": True,
                                "content": final_message,
                                "error": None,
                                "metadata": {
                                    "type": "chat",
                                    "session_id": session_id,
                                    "model": config.vllm.model,
                                    "used_tool": tool_name
                                }
                            })
                    except Exception as e:
                        logger.error(f"Tool call error: {e}")
                        # 工具调用失败，返回原始回复
                        chat_sessions[session_id].append({
                            "role": "assistant",
                            "content": assistant_message
                        })
                        
                        return JSONResponse({
                            "success": True,
                            "content": assistant_message,
                            "error": None,
                            "metadata": {
                                "type": "chat",
                                "session_id": session_id,
                                "model": config.vllm.model
                            }
                        })
                else:
                    # 没有工具调用，直接返回
                    chat_sessions[session_id].append({
                        "role": "assistant",
                        "content": assistant_message
                    })
                    
                    return JSONResponse({
                        "success": True,
                        "content": assistant_message,
                        "error": None,
                        "metadata": {
                            "type": "chat",
                            "session_id": session_id,
                            "model": config.vllm.model
                        }
                    })
            else:
                return JSONResponse({
                    "success": False,
                    "error": "Invalid response from VLLM"
                })
                
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"Chat error: {error_detail}")
            return JSONResponse({
                "success": False,
                "error": f"Chat failed: {str(e)}"
            })
    
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

@app.get("/experts")
async def list_experts():
    """获取所有可用专家列表"""
    if not vllm_client:
        return JSONResponse({"success": False, "error": "VLM客户端未初始化"})
    
    from .agents.expert_agents import ExpertAgentOrchestrator
    orchestrator = ExpertAgentOrchestrator(vllm_client)
    
    experts = orchestrator.get_available_experts()
    return JSONResponse({
        "success": True,
        "experts": experts
    })

@app.post("/expert/execute")
async def execute_with_expert(request_data: Dict[str, Any]):
    """使用专家Agent执行任务"""
    if not vllm_client:
        return JSONResponse({"success": False, "error": "VLM客户端未初始化"})
    
    try:
        from .agents.expert_agents import ExpertAgentOrchestrator
        orchestrator = ExpertAgentOrchestrator(vllm_client)
        
        task = request_data.get("task", "")
        context = request_data.get("context", "")
        expert_type = request_data.get("expert_type")
        
        result = await orchestrator.execute_with_expert(
            task=task,
            context=context,
            expert_type=expert_type,
            skill_manager=skill_manager
        )
        
        return JSONResponse(result)
        
    except Exception as e:
        logger.error(f"Expert execution error: {e}")
        return JSONResponse({"success": False, "error": str(e)})

# 导出app实例
__all__ = ["app"]
