#!/usr/bin/env python3
"""
FastAPI应用定义 - 独立模块
"""
import logging
import json
import asyncio
import os
import re
import threading
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
from .services import RequestLifecycle, SessionStore


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
    message_parts: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None
    mode: Optional[str] = None
    permission_mode: Optional[str] = None
    permission_confirmed: Optional[bool] = None
    context: Optional[str] = None
    tool_context: Optional[str] = None
    thinking_mode: Optional[bool] = None
    enabled_skills: Optional[List[str]] = None
    workspace_path: Optional[str] = None
    model: Optional[str] = None


class WorkspaceUpdateRequest(BaseModel):
    path: str

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
pending_plans: Dict[str, Dict[str, Any]] = {}
session_locations: Dict[str, Dict[str, Any]] = {}

# Skills real-time event bus
_skills_event_queues: List[asyncio.Queue] = []

def _skills_dir_mtime(root: Path) -> float:
    """Return the maximum mtime across SKILL.md and Python source files only (ignores __pycache__)."""
    try:
        return max(
            (
                p.stat().st_mtime
                for p in root.rglob("*")
                if p.is_file()
                and "__pycache__" not in p.parts
                and p.suffix not in (".pyc", ".pyo")
            ),
            default=0.0,
        )
    except Exception:
        return 0.0

async def _broadcast_skills_update() -> None:
    """Push updated catalog to all connected SSE listeners."""
    if not skill_manager:
        return
    catalog = skill_manager.get_skill_catalog()
    payload = json.dumps({"type": "catalog", "skills": catalog})
    dead = []
    for q in _skills_event_queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _skills_event_queues.remove(q)
        except ValueError:
            pass

async def _watch_skills_dir() -> None:
    """Background task: watch skills directory and push SSE events on change."""
    while skill_manager is None:
        await asyncio.sleep(1)

    skills_root: Optional[Path] = getattr(
        getattr(skill_manager, "skill_loader", None), "skills_root", None
    )
    if skills_root is None or not skills_root.exists():
        logger.warning("Skills watcher: could not resolve skills_root, giving up.")
        return

    last_mtime = _skills_dir_mtime(skills_root)
    logger.info(f"Skills watcher started on {skills_root}")
    while True:
        await asyncio.sleep(1)
        try:
            mtime = _skills_dir_mtime(skills_root)
            if mtime != last_mtime:
                last_mtime = mtime
                skill_manager.reload_skills()
                await _broadcast_skills_update()
                logger.info("Skills directory changed – catalog reloaded and broadcast.")
        except Exception as exc:
            logger.warning(f"Skills watcher error: {exc}")
session_store = SessionStore.from_config(config)
request_lifecycle = RequestLifecycle()

HOST_HOME = os.getenv("HOST_HOME")
HOST_HOME_MOUNT = os.getenv("HOST_HOME_MOUNT", "/host-home")
HOST_REPO_ROOT = os.getenv("HOST_REPO_ROOT")
AVAILABLE_MODELS = [
    model.strip()
    for model in os.getenv("AVAILABLE_MODELS", config.vllm.model).split(",")
    if model.strip()
]
WEATHER_REQUEST_PATTERN = re.compile(r"(天气|温度|气温|weather|forecast)", re.IGNORECASE)


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
    return session_store.sanitize_session_id(session_id)


def _llm_trace_file(session_id: str) -> Path:
    return session_store.llm_trace_file(session_id)


def _chat_session_file(session_id: str) -> Path:
    return session_store.chat_session_file(session_id)


def _context_cache_file(session_id: str) -> Path:
    return session_store.context_cache_file(session_id)


def _persist_llm_trace(session_id: str, payload: Dict[str, Any]) -> None:
    session_store.persist_llm_trace(session_id, payload)


def _load_llm_traces(session_id: str) -> List[Dict[str, Any]]:
    return session_store.load_llm_traces(session_id)


def _load_chat_session(session_id: str) -> Optional[List[Dict[str, Any]]]:
    return session_store.load_chat_session(session_id)


def _persist_chat_session(session_id: str) -> None:
    session_store.persist_chat_session(session_id, chat_sessions.get(session_id, []))


def _load_context_cache(session_id: str) -> Optional[Dict[str, Any]]:
    return session_store.load_context_cache(session_id)


def _persist_context_cache(session_id: str, streaming_agent: Any) -> None:
    if streaming_agent is None:
        return
    cache = getattr(streaming_agent, "session_context_cache", {}).get(session_id)
    session_store.persist_context_cache(session_id, cache)


def _ensure_session_state_loaded(session_id: str, streaming_agent: Optional[Any] = None) -> None:
    cache_store = getattr(streaming_agent, "session_context_cache", None) if streaming_agent is not None else None
    session_store.ensure_session_state_loaded(session_id, chat_sessions, cache_store if isinstance(cache_store, dict) else None)


def _resolve_workspace_path(path_str: str) -> Path:
    workspace = _host_to_runtime_path(path_str)
    if not workspace.exists():
        raise FileNotFoundError(f"Workspace does not exist: {path_str}")
    if not workspace.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {path_str}")
    return workspace


def _host_to_runtime_path(path_str: str) -> Path:
    candidate = Path(path_str).expanduser()
    if not candidate.is_absolute():
        candidate = (Path(_current_workspace_runtime()) / candidate).resolve()

    if HOST_REPO_ROOT:
        try:
            repo_root = Path(HOST_REPO_ROOT).expanduser().resolve()
            relative = candidate.resolve().relative_to(repo_root)
            return (Path(config.work_dir).resolve().parent / relative).resolve()
        except Exception:
            pass

    if HOST_HOME:
        try:
            host_home = Path(HOST_HOME).expanduser().resolve()
            relative = candidate.resolve().relative_to(host_home)
            return (Path(HOST_HOME_MOUNT).resolve() / relative).resolve()
        except Exception:
            pass

    return candidate.resolve()


def _runtime_to_host_path(path_str: str) -> str:
    runtime_path = Path(path_str).expanduser().resolve()

    if HOST_HOME:
        try:
            relative = runtime_path.relative_to(Path(HOST_HOME_MOUNT).resolve())
            return str((Path(HOST_HOME).expanduser().resolve() / relative).resolve())
        except Exception:
            pass

    if HOST_REPO_ROOT:
        try:
            app_root_runtime = Path(config.work_dir).resolve().parent
            relative = runtime_path.relative_to(app_root_runtime)
            return str((Path(HOST_REPO_ROOT).expanduser().resolve() / relative).resolve())
        except Exception:
            pass

    return str(runtime_path)


def _current_workspace_runtime() -> str:
    if skill_manager is not None and hasattr(skill_manager, "get_current_workspace"):
        return skill_manager.get_current_workspace()
    return str(Path(config.work_dir).expanduser().resolve())


def _persist_workspace_state(path_str: str) -> None:
    runtime_path = str(_host_to_runtime_path(path_str))
    payload = {
        "path": _runtime_to_host_path(runtime_path),
        "runtime_path": runtime_path,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    session_store.persist_workspace_state(payload)


def _load_workspace_state() -> Optional[str]:
    try:
        payload = session_store.load_workspace_state()
        path_str = (payload or {}).get("runtime_path") or (payload or {}).get("path")
        if path_str:
            return str(_resolve_workspace_path(path_str))
    except Exception as exc:
        logger.warning(f"Failed to load workspace state: {exc}")
    return None


def _current_workspace() -> str:
    return _runtime_to_host_path(_current_workspace_runtime())


def _thread_workspace_for_session(session_id: str) -> str:
    return session_store.thread_runtime_dir(session_id)


def _architecture_runtime_snapshot() -> Dict[str, Any]:
    available_tools = skill_manager.get_anthropic_tools() if skill_manager is not None else []
    return {
        "status": "ok" if vllm_client is not None else "degraded",
        "model": config.vllm.model,
        "available_models": AVAILABLE_MODELS,
        "workspace_path": _current_workspace(),
        "runtime_workspace_path": _current_workspace_runtime(),
        "skills_count": len(getattr(skill_manager, "skills", {}) or {}),
        "tools_count": len(available_tools),
        "tool_names": [tool.get("name") for tool in available_tools if tool.get("name")],
        "thread_count": len(chat_sessions),
        "request_harness": {
            "api": "FastAPI /chat/stream",
            "router": "StreamingAgent.chat_stream()",
            "persistence": "SessionStore",
            "phase_service": "RequestLifecycle",
        },
    }

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
            parts = []
            if result.error:
                parts.append(f"Error: {result.error}")
            if result.content:
                parts.append(result.content)
            return "\n".join(parts) if parts else "工具执行失败"
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
    persisted_workspace = _load_workspace_state()
    if persisted_workspace:
        try:
            skill_manager.set_workspace(persisted_workspace)
        except Exception as exc:
            logger.warning(f"Failed to restore persisted workspace {persisted_workspace}: {exc}")

    asyncio.create_task(_watch_skills_dir())
    
    # 初始化VLLM客户端
    vllm_client = VLLMClient(config.vllm)
    await vllm_client.__aenter__()
    
    # 初始化Plan Agent
    available_skills = list(skill_manager.skills.keys())
    plan_agent = PlanAgent(vllm_client, [name for name in skill_manager.skills.keys()])
    
    execution_engine = ExecutionEngine(vllm_client, skill_manager, plan_agent)
    app.state.execution_engine = execution_engine
    
    from .agents.streaming_agent import StreamingAgent
    streaming_agent = StreamingAgent(
        vllm_client,
        skill_manager,
        execution_engine,
        plan_agent,
        request_lifecycle=request_lifecycle,
    )
    app.state.streaming_agent = streaming_agent
    
    logger.info("Omni Agent API 启动完成")
    
    # 同时存储在app.state中
    app.state.skill_manager = skill_manager
    app.state.vllm_client = vllm_client
    app.state.plan_agent = plan_agent
    app.state.execution_engine = execution_engine
    app.state.session_store = session_store
    app.state.request_lifecycle = request_lifecycle
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
    skills_count = len(skill_manager.skills) if skill_manager else 0
    return {"status": "ok", "skills_count": skills_count}

@app.get("/runtime")
async def runtime_status():
    """Provide frontend-friendly runtime metadata for Claude Code style status panels."""
    skills_count = len(skill_manager.skills) if skill_manager else 0
    return JSONResponse({
        "status": "ok" if vllm_client is not None else "degraded",
        "runtime": {
            "model": config.vllm.model,
            "available_models": AVAILABLE_MODELS,
            "api_base_url": config.vllm.base_url,
            "work_dir": _current_workspace(),
            "runtime_work_dir": _current_workspace_runtime(),
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


@app.get("/architecture")
async def architecture_manifest():
    return JSONResponse({
        "architecture": request_lifecycle.architecture_signature(),
        "runtime": _architecture_runtime_snapshot(),
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


@app.post("/skills/reload")
async def reload_skills():
    """Hot-reload all skills from disk without restarting the server."""
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "skill_manager not initialized"}, status_code=503)
    try:
        info = skill_manager.reload_skills()
        return JSONResponse({
            "success": True,
            "reload": info,
            "skills": skill_manager.get_skill_catalog(),
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


class SkillInstallRequest(BaseModel):
    name: str
    skill_md: str
    python_code: str = ""


@app.post("/skills/install")
async def install_skill(payload: SkillInstallRequest):
    """Install a new skill from SKILL.md content, then hot-reload."""
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "skill_manager not initialized"}, status_code=503)
    try:
        result = skill_manager.install_skill(
            name=payload.name,
            skill_md=payload.skill_md,
            python_code=payload.python_code,
        )
        await _broadcast_skills_update()
        return JSONResponse({
            "success": True,
            **result,
            "skills": skill_manager.get_skill_catalog(),
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


class SkillInstallFromUrlRequest(BaseModel):
    url: str
    name: str = ""
    python_code: str = ""


def _rewrite_localhost_url(url: str) -> str:
    """Rewrite 127.0.0.1 / localhost to host.docker.internal so Docker containers can reach the host."""
    import re as _re
    url = _re.sub(r"127\.0\.0\.1", "host.docker.internal", url)
    url = _re.sub(r"(?<![.\w])localhost(?![.\w])", "host.docker.internal", url)
    return url


def _parse_skill_name_from_md(content: str) -> str:
    """Extract `name:` from YAML frontmatter, fall back to empty string."""
    import re as _re
    m = _re.search(r"^---\s*\n.*?^name:\s*(.+?)\s*$.*?---", content, _re.MULTILINE | _re.DOTALL)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return ""


@app.post("/skills/install-from-url")
async def install_skill_from_url(payload: SkillInstallFromUrlRequest):
    """Fetch a SKILL.md from a URL (rewrites 127.0.0.1→host.docker.internal) and install it."""
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "skill_manager not initialized"}, status_code=503)

    rewritten = _rewrite_localhost_url(payload.url)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(rewritten)
            resp.raise_for_status()
            skill_md = resp.text
    except Exception as exc:
        return JSONResponse({"success": False, "error": f"Failed to fetch {rewritten}: {exc}"}, status_code=400)

    name = payload.name.strip() or _parse_skill_name_from_md(skill_md)
    if not name:
        # Derive from URL path
        name = rewritten.rstrip("/").rsplit("/", 1)[-1].replace(".md", "").replace(".txt", "") or "unnamed-skill"

    # Rewrite any 127.0.0.1/localhost references inside the SKILL.md body so the agent
    # uses host.docker.internal when running commands from within the container.
    import re as _re
    skill_md = _re.sub(r"127\.0\.0\.1", "host.docker.internal", skill_md)
    skill_md = _re.sub(r"(?<![.\w])localhost(?![.\w])", "host.docker.internal", skill_md)

    try:
        result = skill_manager.install_skill(name=name, skill_md=skill_md, python_code=payload.python_code)
        await _broadcast_skills_update()
        return JSONResponse({
            "success": True,
            "fetched_url": payload.url,
            "rewritten_url": rewritten,
            **result,
            "skills": skill_manager.get_skill_catalog(),
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/skills/store/search")
async def search_skill_store(q: str = "", include_github: bool = False):
    """Search the built-in skill registry (and optionally GitHub) for installable skills."""
    import unicodedata

    # Load registry
    registry_path = Path(__file__).parent / "skill_registry.json"
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except Exception as exc:
        return JSONResponse({"success": False, "error": f"Registry unavailable: {exc}"}, status_code=500)

    query = q.strip().lower()

    def _score(skill: dict) -> int:
        if not query:
            return 1
        name = skill.get("name", "").lower()
        display = skill.get("display_name", "").lower()
        desc = skill.get("description", "").lower()
        tags = " ".join(skill.get("tags") or []).lower()
        text = f"{name} {display} {desc} {tags}"
        score = 0
        if query in name:
            score += 10
        if query in display:
            score += 8
        for word in query.split():
            if word in text:
                score += 3
        # Also score individual CJK characters
        for char in query:
            if unicodedata.category(char).startswith("Lo") and char in text:
                score += 2
        return score

    results = []
    for skill in registry.get("skills", []):
        s = _score(skill)
        if not query or s > 0:
            entry = {
                "name": skill["name"],
                "display_name": skill.get("display_name", skill["name"]),
                "description": skill.get("description", ""),
                "tags": skill.get("tags", []),
                "category": skill.get("category", ""),
                "source": "registry",
                "score": s,
            }
            # Include skill_md if present (for direct install)
            if skill.get("skill_md"):
                entry["skill_md"] = skill["skill_md"]
            if skill.get("skill_md_url"):
                entry["skill_md_url"] = skill["skill_md_url"]
            results.append(entry)

    results.sort(key=lambda x: -x["score"])
    if query:
        results = [r for r in results if r["score"] > 0]

    # Optional GitHub search fallback
    github_results = []
    if include_github and query:
        try:
            gh_query = f"{q}+topic:obs-code-skill"
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"https://api.github.com/search/repositories?q={gh_query}&sort=stars&per_page=5",
                    headers={"Accept": "application/vnd.github+json"},
                )
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    for item in items:
                        owner = item["owner"]["login"]
                        repo = item["name"]
                        github_results.append({
                            "name": repo,
                            "display_name": item.get("description") or repo,
                            "description": item.get("description", ""),
                            "tags": item.get("topics", []),
                            "category": "github",
                            "source": "github",
                            "score": item.get("stargazers_count", 0),
                            "skill_md_url": f"https://raw.githubusercontent.com/{owner}/{repo}/main/SKILL.md",
                        })
        except Exception:
            pass  # GitHub search is best-effort

    # Get currently installed skill names to mark already-installed ones
    installed = set()
    if skill_manager is not None:
        catalog = skill_manager.get_skill_catalog()
        catalog_skills = catalog.get("skills", []) if isinstance(catalog, dict) else catalog
        installed = {s["name"] for s in catalog_skills}

    for r in results + github_results:
        r["installed"] = r["name"] in installed

    return JSONResponse({
        "success": True,
        "query": q,
        "results": results,
        "github_results": github_results,
        "total": len(results) + len(github_results),
    })


@app.delete("/skills/{skill_name}")
async def delete_skill(skill_name: str):
    """Remove a skill directory and hot-reload. Protected skills cannot be deleted."""
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "skill_manager not initialized"}, status_code=503)
    skills_root = getattr(getattr(skill_manager, "skill_loader", None), "skills_root", None)
    if skills_root is None:
        return JSONResponse({"success": False, "error": "Cannot resolve skills root"}, status_code=500)
    skill_dir = Path(skills_root) / skill_name
    if not skill_dir.exists():
        return JSONResponse({"success": False, "error": f"Skill '{skill_name}' not found"}, status_code=404)
    # Refuse to delete protected skills
    meta = skill_manager._read_skill_meta(skill_dir)
    if skill_manager._is_protected(skill_dir, meta):
        return JSONResponse(
            {"success": False, "error": f"Skill '{skill_name}' is protected and cannot be deleted."},
            status_code=403,
        )
    import shutil
    try:
        shutil.rmtree(skill_dir)
        skill_manager.reload_skills()
        await _broadcast_skills_update()
        return JSONResponse({"success": True, "deleted": skill_name, "skills": skill_manager.get_skill_catalog()})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/skills/events")
async def skills_events(request: Request):
    """SSE endpoint: push real-time skill catalog updates to the browser."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=16)
    _skills_event_queues.append(queue)

    async def generate():
        try:
            # Send current catalog immediately on connect
            if skill_manager:
                catalog = skill_manager.get_skill_catalog()
                yield f"data: {json.dumps({'type': 'catalog', 'skills': catalog})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield "data: {\"type\":\"heartbeat\"}\n\n"
        finally:
            try:
                _skills_event_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


def _ui_session_file(session_id: str) -> Path:
    return session_store.ui_session_file(session_id)


@app.get("/ui-sessions")
async def list_ui_sessions():
    return JSONResponse({"sessions": session_store.list_ui_sessions()})


@app.get("/ui-sessions/{session_id}")
async def get_ui_session(session_id: str):
    data = session_store.load_ui_session(session_id)
    if data is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    try:
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.put("/ui-sessions/{session_id}")
async def save_ui_session(session_id: str, request: Request):
    try:
        body = await request.json()
        session_store.save_ui_session(session_id, body)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/ui-sessions/{session_id}")
async def delete_ui_session(session_id: str):
    session_store.delete_ui_session(session_id)
    return JSONResponse({"ok": True})


@app.get("/workspace")
async def get_workspace_state():
    path_str = _current_workspace()
    runtime_path = _current_workspace_runtime()
    workspace = Path(path_str)
    return JSONResponse({
        "workspace": {
            "path": path_str,
            "runtime_path": runtime_path,
            "name": workspace.name or path_str,
            "parent": str(workspace.parent) if workspace.parent != workspace else None,
        }
    })


@app.post("/workspace")
async def update_workspace_state(payload: WorkspaceUpdateRequest):
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "Skill manager not initialized"}, status_code=503)
    try:
        workspace = _resolve_workspace_path(payload.path)
        resolved = skill_manager.set_workspace(str(workspace))
        _persist_workspace_state(payload.path)
        display_path = _runtime_to_host_path(resolved)
        return JSONResponse({
            "success": True,
            "workspace": {
                "path": display_path,
                "runtime_path": resolved,
                "name": Path(display_path).name or display_path
            }
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.get("/workspace/browser")
async def browse_workspace(path: Optional[str] = Query(default=None)):
    try:
        current = _resolve_workspace_path(path) if path else Path(_current_workspace_runtime()).resolve()
    except Exception:
        current = Path(_current_workspace_runtime()).resolve()

    entries = []
    try:
        for child in sorted(current.iterdir(), key=lambda item: item.name.lower()):
            try:
                if not child.is_dir():
                    continue
                entries.append({
                    "name": child.name,
                    "path": _runtime_to_host_path(str(child.resolve())),
                })
            except PermissionError:
                continue
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)

    parent = current.parent if current.parent != current else None
    return JSONResponse({
        "success": True,
        "current": _runtime_to_host_path(str(current)),
        "runtime_current": str(current),
        "parent": _runtime_to_host_path(str(parent)) if parent else None,
        "entries": entries[:200],
    })


def _pick_workspace_directory(initial_path: Optional[str]) -> Optional[str]:
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("Native folder picker is unavailable in the current runtime environment") from exc

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(
            initialdir=initial_path or _current_workspace(),
            mustexist=True,
            parent=root,
            title="Select Workspace Folder",
        )
        return selected or None
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass


@app.post("/workspace/pick")
async def pick_workspace_directory():
    try:
        initial_path = _current_workspace()
        if threading.current_thread() is threading.main_thread():
            selected = _pick_workspace_directory(initial_path)
        else:
            selected = await asyncio.to_thread(_pick_workspace_directory, initial_path)
        if not selected:
            return JSONResponse({"success": False, "cancelled": True})

        runtime_path = str(_resolve_workspace_path(selected))
        return JSONResponse({
            "success": True,
            "workspace": {
                "path": _runtime_to_host_path(runtime_path),
                "runtime_path": runtime_path,
                "name": Path(selected).name or selected,
            }
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


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
async def get_session_context_state(session_id: str, model: Optional[str] = Query(default=None)):
    streaming_agent = getattr(app.state, "streaming_agent", None)
    _ensure_session_state_loaded(session_id, streaming_agent)
    messages = chat_sessions.get(session_id, [])
    context_percent = 0
    estimated_context_tokens = 0
    max_context_tokens = 128000
    if streaming_agent is not None:
        cache = getattr(streaming_agent, "session_context_cache", {}).get(session_id, {})
        if cache:
            compact_messages = [
                {"role": "system", "content": "OBS Agent system prompt"},
                {
                    "role": "user",
                    "content": "\n\n".join(
                        part for part in [
                            (cache.get("historical_summary") or "").strip(),
                            (cache.get("recent_summary") or "").strip(),
                            (messages[-1].get("content") or "").strip() if messages else "",
                        ] if part
                    ),
                },
            ]
            context_percent = streaming_agent._estimate_context_percent(compact_messages)
            estimated_context_tokens = streaming_agent._estimate_context_tokens(compact_messages)
        else:
            context_percent = streaming_agent._estimate_context_percent(messages)
            estimated_context_tokens = streaming_agent._estimate_context_tokens(messages)
        max_context_tokens = streaming_agent._get_context_window_tokens(model)
    return JSONResponse({
        "session_id": session_id,
        "messages_count": len(messages),
        "context_percent": context_percent,
        "estimated_context_tokens": estimated_context_tokens,
        "max_context_tokens": max_context_tokens,
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
    workspace_path = request_data.workspace_path if request_data.workspace_path is not None else params.get("workspace_path")
    message_parts = request_data.message_parts if request_data.message_parts is not None else params.get("message_parts")
    selected_model = request_data.model if request_data.model is not None else params.get("model") or config.vllm.model
    temporal_context = _get_runtime_temporal_context()
    
    async def generate():
        streaming_agent = getattr(app.state, "streaming_agent", None)
        try:
            _ensure_session_state_loaded(session_id, streaming_agent)
            location = session_locations.get(session_id)
            if location is None and WEATHER_REQUEST_PATTERN.search(message or ""):
                try:
                    location = await asyncio.wait_for(_resolve_location_from_ip(request), timeout=2.5)
                except Exception as location_exc:
                    logger.debug(f"On-demand weather location resolve failed for session {session_id}: {location_exc}")
                    location = None
                if location:
                    session_locations[session_id] = location

            if workspace_path and skill_manager is not None:
                try:
                    runtime_workspace = _resolve_workspace_path(workspace_path)
                    skill_manager.set_workspace(str(runtime_workspace))
                    _persist_workspace_state(workspace_path)
                except Exception as workspace_exc:
                    logger.debug(f"Ignoring workspace override for session {session_id}: {workspace_exc}")

            # 添加用户消息到会话历史
            chat_sessions[session_id].append({
                "role": "user",
                "content": message,
                "message_parts": message_parts or [],
            })
            _persist_chat_session(session_id)
            
            # 使用流式引擎处理请求 (取代旧版 execution_engine 块)
            async for chunk in streaming_agent.chat_stream(
                session_id,
                chat_sessions,
                mode=mode,
                permission_mode=permission_mode,
                permission_confirmed=permission_confirmed,
                context=context,
                tool_context=tool_context,
                enabled_skills=enabled_skills or [],
                request_context={
                    **temporal_context,
                    "location": location,
                    "workspace_display_path": _current_workspace(),
                    "workspace_runtime_path": _current_workspace_runtime(),
                    "thread_runtime_dir": _thread_workspace_for_session(session_id),
                    "message_parts": message_parts or [],
                    "model": selected_model,
                },
            ):
                if chunk.startswith("data: "):
                    try:
                        payload = json.loads(chunk[6:].strip())
                        if payload.get("type") == "llm_log":
                            _persist_llm_trace(session_id, payload)
                        elif payload.get("type") == "plan" and payload.get("plan_id"):
                            pending_plans[payload["plan_id"]] = {
                                "plan_id": payload["plan_id"],
                                "user_message": message,
                                "session_id": session_id,
                                "chat_history": list(chat_sessions.get(session_id, [])),
                                "plan": payload.get("plan"),
                                "task_graph": payload.get("task_graph"),
                                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                            }
                    except Exception:
                        pass
                yield chunk
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            logger.error(f"Chat stream error: {error_detail}")
            # Include error type and truncated traceback so the frontend can display
            # a meaningful diagnostic message instead of a generic "failed" notice.
            last_line = error_detail.strip().rsplit("\n", 1)[-1].strip() if error_detail else str(e)
            yield f"data: {json.dumps({'error': str(e), 'error_type': type(e).__name__, 'error_detail': last_line, 'done': True})}\n\n"
        finally:
            try:
                _persist_chat_session(session_id)
                _persist_context_cache(session_id, streaming_agent)
            except Exception as persist_exc:
                logger.warning(f"Failed to persist session state for {session_id}: {persist_exc}")
    
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

@app.get("/plan/pending")
async def list_pending_plans():
    """List plans awaiting human approval."""
    return JSONResponse({
        "pending_plans": [
            {
                "plan_id": v["plan_id"],
                "session_id": v["session_id"],
                "user_message": v["user_message"],
                "created_at": v["created_at"],
                "steps_count": len((v.get("plan") or {}).get("steps") or []),
            }
            for v in pending_plans.values()
        ]
    })


@app.post("/plan/approve/{plan_id}")
async def approve_plan(plan_id: str):
    """Approve a pending plan and stream its execution."""
    plan_data = pending_plans.pop(plan_id, None)
    if plan_data is None:
        return JSONResponse({"error": "Plan not found or already executed"}, status_code=404)

    execution_engine = getattr(app.state, "execution_engine", None)
    if execution_engine is None:
        return JSONResponse({"error": "Execution engine not initialized"}, status_code=503)

    session_id = plan_data["session_id"]

    async def generate():
        try:
            async for event in execution_engine.execute_user_request(
                user_message=plan_data["user_message"],
                session_id=session_id,
                chat_history=plan_data.get("chat_history") or [],
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc), 'done': True}, ensure_ascii=False)}\n\n"
        finally:
            yield f"data: {json.dumps({'done': True, 'session_id': session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.delete("/plan/{plan_id}")
async def reject_plan(plan_id: str):
    """Reject (discard) a pending plan."""
    pending_plans.pop(plan_id, None)
    return JSONResponse({"ok": True})


# 导出app实例
__all__ = ["app"]
