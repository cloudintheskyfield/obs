#!/usr/bin/env python3
"""
FastAPI应用定义 - 独立模块
"""
import logging
import json
import asyncio
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
import httpx

from .config.config import load_config
from .utils.paths import claude_skills_root, frontend_root, frontend_static_root, repo_skills_root
import sys
from pathlib import Path

# Add .claude/skills and root skills to Python path for skills
claude_skills_path = claude_skills_root()
root_skills_path = repo_skills_root()
if claude_skills_path.exists():
    sys.path.insert(0, str(claude_skills_path))
if root_skills_path.exists():
    sys.path.insert(0, str(root_skills_path))
os.environ.setdefault("SKILLS_DIR", str(claude_skills_path))

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


class ChatStreamRequest(BaseModel):
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = {}
    message: Optional[str] = None
    session_id: Optional[str] = None
    mode: Optional[str] = None
    permission_mode: Optional[str] = None
    permission_confirmed: Optional[bool] = None
    context: Optional[str] = None
    tool_context: Optional[str] = None
    thinking_mode: Optional[bool] = None
    enabled_skills: Optional[List[str]] = None

class LocationUpdateRequest(BaseModel):
    session_id: str
    lat: float
    lon: float
    accuracy_m: Optional[float] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country_name: Optional[str] = None
    source: Optional[str] = None
    ip: Optional[str] = None
    provider: Optional[str] = None

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
    frontend_dir = frontend_static_root()
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
llm_trace_dir = Path(config.log.file_path).parent / "llm_traces" if config.log.file_path else Path(config.work_dir).parent / "logs" / "llm_traces"
llm_trace_dir.mkdir(parents=True, exist_ok=True)


def _get_runtime_temporal_context() -> Dict[str, Any]:
    now = datetime.now().astimezone()
    return {
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S"),
        "timezone": now.tzname() or "local",
        "utc_offset": now.strftime("%z"),
        "weekday": now.strftime("%A"),
    }


def _format_runtime_context(context: Dict[str, Any], location: Optional[Dict[str, Any]]) -> str:
    lines = [
        "Runtime context you must treat as authoritative:",
        f"- Current date: {context['current_date']}",
        f"- Current time: {context['current_time']}",
        f"- Current datetime: {context['current_datetime']}",
        f"- Timezone: {context['timezone']} (UTC{context['utc_offset']})",
        f"- Weekday: {context['weekday']}",
        "- Interpret relative references like today / 今日 / 今天 using the exact current date above.",
    ]
    if location:
        city = location.get("city")
        region = location.get("region")
        country = location.get("country_name")
        lat = location.get("lat")
        lon = location.get("lon")
        source = location.get("source")
        place_bits = [part for part in [city, region, country] if part]
        if place_bits:
            lines.append(f"- Approximate user location: {', '.join(place_bits)}")
        if lat is not None and lon is not None:
            lines.append(f"- Approximate coordinates: {lat}, {lon}")
        if source:
            lines.append(f"- Location source: {source}")
        lines.append("- Prefer local relevance when the request depends on user location.")
    return "\n".join(lines)


def _sanitize_session_id(session_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", session_id)[:120]


def _llm_trace_file(session_id: str) -> Path:
    return llm_trace_dir / f"{_sanitize_session_id(session_id)}.jsonl"


def _persist_llm_trace(session_id: str, payload: Dict[str, Any]) -> None:
    record = {
        "session_id": session_id,
        "timestamp": payload.get("timestamp") or datetime.now().astimezone().isoformat(timespec="seconds"),
        "phase": payload.get("phase"),
        "direction": payload.get("direction"),
        "payload": payload.get("payload"),
        "type": "llm_log",
    }
    trace_file = _llm_trace_file(session_id)
    with trace_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_llm_traces(session_id: str) -> List[Dict[str, Any]]:
    trace_file = _llm_trace_file(session_id)
    if not trace_file.exists():
        return []
    records: List[Dict[str, Any]] = []
    with trace_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records

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

    if ip in {"127.0.0.1", "::1"}:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("https://ipwho.is/")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") is not False:
                        lat = data.get("latitude")
                        lon = data.get("longitude")
                        if lat is not None and lon is not None:
                            return {
                                "source": "ip",
                                "provider": "ipwhois",
                                "lat": float(lat),
                                "lon": float(lon),
                                "city": data.get("city"),
                                "region": data.get("region"),
                                "country_name": data.get("country_name") or data.get("country"),
                                "ip": data.get("ip") or ip,
                            }
        except Exception as e:
            logger.debug(f"Fallback IP location resolve failed: {e}")

    candidates = [
        ("ipapi", f"https://ipapi.co/{ip}/json/"),
        ("ipwhois", f"https://ipwho.is/{ip}"),
    ]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            for source_name, url in candidates:
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    if source_name == "ipwhois" and data.get("success") is False:
                        continue

                    lat = data.get("latitude")
                    lon = data.get("longitude")
                    if lat is None or lon is None:
                        continue

                    return {
                        "source": "ip",
                        "provider": source_name,
                        "lat": float(lat),
                        "lon": float(lon),
                        "city": data.get("city"),
                        "region": data.get("region"),
                        "country_name": data.get("country_name") or data.get("country"),
                        "ip": ip,
                    }
                except Exception as inner_exc:
                    logger.debug(f"IP location provider {source_name} failed: {inner_exc}")
                    continue
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
        "source": payload.source or "geolocation",
        "lat": payload.lat,
        "lon": payload.lon,
        "accuracy_m": payload.accuracy_m,
        "city": payload.city,
        "region": payload.region,
        "country_name": payload.country_name,
        "ip": payload.ip,
        "provider": payload.provider,
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
        frontend_dir = frontend_static_root()
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


@app.get("/skill-catalog")
async def skill_catalog():
    if skill_manager is None:
        return JSONResponse({"skills": []})
    return JSONResponse({"skills": skill_manager.get_skill_catalog()})


@app.get("/logs/{session_id}")
async def get_session_logs(
    session_id: str,
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    records = _load_llm_traces(session_id)
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None

    filtered: List[Dict[str, Any]] = []
    for record in records:
        try:
            ts = datetime.fromisoformat(record.get("timestamp"))
        except Exception:
            ts = None
        if start_dt and ts and ts < start_dt:
            continue
        if end_dt and ts and ts > end_dt:
            continue
        filtered.append(record)

    return JSONResponse({
        "session_id": session_id,
        "logs": filtered[-limit:],
    })


@app.get("/session/{session_id}/context")
async def get_session_context_state(session_id: str):
    messages = chat_sessions.get(session_id, [])
    context_percent = 0
    streaming_agent = getattr(app.state, "streaming_agent", None)
    if streaming_agent is not None:
        context_percent = streaming_agent._estimate_context_percent(messages)
    return JSONResponse({
        "session_id": session_id,
        "messages_count": len(messages),
        "context_percent": context_percent,
    })

@app.post("/chat/stream")
async def chat_stream(request_data: ChatStreamRequest, request: Request):
    """流式聊天"""
    if vllm_client is None:
        return JSONResponse({"success": False, "error": "VLLM client not initialized"})

    params = request_data.parameters or {}
    message = request_data.message if request_data.message is not None else params.get("message", "")
    session_id = request_data.session_id if request_data.session_id is not None else params.get("session_id", "default")
    mode = request_data.mode if request_data.mode is not None else params.get("mode", "agent")
    permission_mode = (
        request_data.permission_mode
        if request_data.permission_mode is not None
        else params.get("permission_mode", "ask")
    )
    permission_confirmed = bool(
        request_data.permission_confirmed
        if request_data.permission_confirmed is not None
        else params.get("permission_confirmed", False)
    )
    context = request_data.context if request_data.context is not None else params.get("context", "")
    tool_context = request_data.tool_context if request_data.tool_context is not None else params.get("tool_context", "workspace")
    enabled_skills = request_data.enabled_skills if request_data.enabled_skills is not None else params.get("enabled_skills")
    temporal_context = _get_runtime_temporal_context()
    
    async def generate():
        try:
            location = session_locations.get(session_id)
            if location is None:
                location = await _resolve_location_from_ip(request)
                if location:
                    session_locations[session_id] = location

            runtime_context_text = _format_runtime_context(temporal_context, location)
            merged_context = "\n\n".join(part for part in [context, runtime_context_text] if part)

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
                context=merged_context,
                tool_context=tool_context,
                enabled_skills=enabled_skills or [],
                request_context={
                    **temporal_context,
                    "location": location,
                },
            ):
                if chunk.startswith("data: "):
                    try:
                        payload = json.loads(chunk[6:].strip())
                        if payload.get("type") == "llm_log":
                            _persist_llm_trace(session_id, payload)
                    except Exception:
                        pass
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
