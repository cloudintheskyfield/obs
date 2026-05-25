#!/usr/bin/env python3
"""
FastAPI应用定义 - 独立模块
"""
import logging
import json
import asyncio
import ipaddress
import mimetypes
import os
import re
import socket
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import parse_qs, quote, unquote, urlsplit
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
import httpx

from config.config import load_config
from utils.paths import frontend_root, frontend_static_root, src_skills_root
import sys
from pathlib import Path

# Add src/skills to Python path for skills
skills_path = src_skills_root()
if skills_path.exists():
    sys.path.insert(0, str(skills_path))
os.environ.setdefault("SKILLS_DIR", str(skills_path))

from skills.skill_manager import SkillManager
from core.vllm_client import VLLMClient
from agents.harness_runtime import HarnessRuntime, normalize_llm_message_content
from services import RequestLifecycle, SessionStore


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
    tool_name: Optional[str] = None  # 工具名称，通常是 "chat"，代表这是一次普通的对话请求
    parameters: Dict[str, Any] = {}  # 扩展参数字典，通常包含请求字段的冗余副本或特定的额外配置
    message: Optional[str] = None  # 用户在输入框中输入的纯文本内容
    message_parts: Optional[List[Dict[str, Any]]] = None  # 结构化消息体，例如包含用户上传的图片(data_url)和文本的组合
    session_id: Optional[str] = None  # 前端生成的会话 ID，对应左侧边栏的每一个 Thread (对话卡片)
    mode: Optional[str] = None  # 对话模式，例如 "agent" (默认的智能体模式) 或 "create" (用于生成新应用的模式)
    permission_mode: Optional[str] = None  # 权限模式："ask" (危险操作需用户手动点击确认) 或 "auto" (全自动执行，无需确认)
    permission_confirmed: Optional[bool] = None  # 布尔值，当 permission_mode 不是 "ask" 时通常传 True，表示已自动授权
    context: Optional[str] = None  # 附加的上下文文本信息，供大模型参考
    tool_context: Optional[str] = None  # 前端每次发送前收集的工作区概览（例如当前目录下有哪些文件），作为底层环境提示
    thinking_mode: Optional[bool] = None  # 是否开启了“思考”模式（让大模型先展示内部的推理过程，然后再输出结果）
    workspace_path: Optional[str] = None  # 可选项：用于强制指定本次对话的工作区绝对路径
    model: Optional[str] = None  # 用户在前端顶部选择的大模型名称，例如 "MiniMax-M2" 或 "gpt-5.5"


class WorkspaceUpdateRequest(BaseModel):
    path: str
    session_id: Optional[str] = None

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


class PreviewResolveRequest(BaseModel):
    urls: List[str] = []


class PublishProjectRequest(BaseModel):
    session_id: str
    title: str
    prompt: Optional[str] = None
    description: Optional[str] = None
    preview_url: Optional[str] = None
    preview_label: Optional[str] = None
    workspace_path: Optional[str] = None
    mode: Optional[str] = "create"
    tags: Optional[List[str]] = None
    remixable: Optional[bool] = True


class TitleSuggestionRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    session_id: Optional[str] = None
    mode: Optional[str] = None


# 创建FastAPI应用
config = load_config()
app = FastAPI(
    title="OBS Code API",
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
workspace_request_lock = asyncio.Lock()

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
PREVIEW_HTML_SUFFIXES = {".html", ".htm"}
PREVIEW_SWITCHABLE_SUFFIXES = {
    ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg",
    ".mp4", ".webm", ".mp3", ".wav", ".ogg",
    ".json", ".pdf",
}
PREVIEW_SCAN_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    ".next",
    ".nuxt",
    ".vite",
    ".pytest_cache",
    "coverage",
}
PREVIEW_SCAN_MAX_FILES = 5000
PREVIEW_SCAN_MAX_RESULTS = 120


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


def _candidate_host_ipv4s() -> List[str]:
    candidates: List[str] = []

    def _add(value: Optional[str]) -> None:
        text = (value or "").strip()
        if not text or text.startswith("127.") or text == "0.0.0.0":
            return
        if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", text) and text not in candidates:
            candidates.append(text)

    for env_name in ("OBS_PUBLIC_HOST", "PUBLIC_HOST"):
        _add(os.getenv(env_name))

    try:
        host_name = socket.gethostname()
        for item in socket.gethostbyname_ex(host_name)[2]:
            _add(item)
    except Exception:
        pass

    for command in (
        ["ipconfig", "getifaddr", "en0"],
        ["ipconfig", "getifaddr", "en1"],
        ["hostname", "-I"],
    ):
        try:
            output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=1.5).strip()
        except Exception:
            continue
        for token in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", output):
            _add(token)

    return candidates


def _resolve_public_host_context(request: Request) -> Dict[str, Any]:
    explicit_base_url = (os.getenv("OBS_PUBLIC_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    forwarded_proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").strip()
    forwarded_host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or ""
    ).strip()

    candidate_ips = _candidate_host_ipv4s()
    forwarded_host_name = forwarded_host.split(":", 1)[0] if forwarded_host else ""
    forwarded_host_is_public = bool(forwarded_host_name and not _looks_like_local_service_host(forwarded_host_name))

    authoritative_base_url = explicit_base_url
    if not authoritative_base_url:
        if forwarded_host and forwarded_host_is_public:
            authoritative_base_url = f"{forwarded_proto}://{forwarded_host}"
        elif candidate_ips:
            port = int(os.getenv("OBS_PUBLIC_PORT") or getattr(config, "api_port", 0) or request.url.port or 0)
            port_suffix = f":{port}" if port else ""
            authoritative_base_url = f"{forwarded_proto}://{candidate_ips[0]}{port_suffix}"
        else:
            authoritative_base_url = str(request.base_url).rstrip("/")

    host_match = re.match(r"^[a-z]+://([^/:?#]+)", authoritative_base_url, re.IGNORECASE)
    authoritative_host = host_match.group(1) if host_match else ""

    return {
        "authoritative_public_base_url": authoritative_base_url,
        "authoritative_public_host": authoritative_host,
        "host_ipv4_candidates": candidate_ips,
    }


def _url_origin(url: str) -> str:
    match = re.match(r"^(https?://[^/?#]+)", url or "", re.IGNORECASE)
    return match.group(1).rstrip("/") if match else ""


def _looks_like_local_service_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    if normalized in {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"}:
        return True
    try:
        parsed = ipaddress.ip_address(normalized)
        return parsed.is_private or parsed.is_loopback or parsed.is_unspecified
    except ValueError:
        return False


def _preview_url_variants(raw_url: str, authoritative_host: str) -> List[str]:
    text = (raw_url or "").strip().strip("`'\" ")
    if not text:
        return []
    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = f"http://{text}"
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(text)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return []
        variants: List[str] = []
        if _looks_like_local_service_host(parts.hostname or "") and authoritative_host:
            netloc = authoritative_host
            if parts.port:
                netloc = f"{authoritative_host}:{parts.port}"
            variants.append(urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, parts.fragment)))
        variants.append(urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, parts.fragment)))

        deduped: List[str] = []
        for item in variants:
            if item not in deduped:
                deduped.append(item)
        return deduped
    except Exception:
        return []


PREVIEW_REWRITABLE_ATTR_PATTERN = re.compile(
    r"""(?P<prefix>\b(?:href|src|poster)\s*=\s*)(?P<quote>["'])(?P<value>[^"']+)(?P=quote)""",
    re.IGNORECASE,
)
PREVIEW_SRCSET_ATTR_PATTERN = re.compile(
    r"""(?P<prefix>\bsrcset\s*=\s*)(?P<quote>["'])(?P<value>[^"']+)(?P=quote)""",
    re.IGNORECASE,
)
PREVIEW_CSS_URL_PATTERN = re.compile(r"""url\(\s*(?P<quote>["']?)(?P<value>[^"')]+)(?P=quote)\s*\)""", re.IGNORECASE)
PREVIEW_ASSET_ALLOWED_SUFFIXES = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico", ".pdf",
    ".mp3", ".wav", ".ogg", ".mp4", ".webm",
    ".woff", ".woff2", ".ttf", ".otf",
    ".pptx", ".ppt", ".doc", ".docx", ".xls", ".xlsx", ".py", ".txt", ".md", ".zip", ".tar.gz", ".csv"
}


def _resolve_local_preview_file(raw_path: str, *, html_only: bool = True) -> Optional[Path]:
    text = (raw_path or "").strip().strip("`'\" ")
    if not text:
        return None

    if text.startswith("file://"):
        text = unquote(urlsplit(text).path)
    elif text.startswith("/preview/local-file"):
        parsed = urlsplit(text)
        text = (parse_qs(parsed.query).get("path") or [""])[0]
    elif re.match(r"^https?://", text, re.IGNORECASE):
        parsed = urlsplit(text)
        if parsed.path != "/preview/local-file":
            return None
        text = (parse_qs(parsed.query).get("path") or [""])[0]

    text = text.strip()
    if not text:
        return None

    try:
        candidate = _host_to_runtime_path(text)
    except Exception:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = Path(_current_workspace_runtime()) / candidate

    try:
        resolved = candidate.resolve()
    except Exception:
        return None

    suffix = resolved.suffix.lower()
    if not resolved.is_file():
        return None
    if html_only and suffix not in {".html", ".htm"}:
        return None
    if not html_only and suffix not in PREVIEW_ASSET_ALLOWED_SUFFIXES:
        return None

    allowed_roots = [
        Path(_current_workspace_runtime()).resolve(),
        Path(config.work_dir).resolve().parent,
        Path.cwd().resolve(),
        Path.home().resolve(),
    ]
    if HOST_HOME:
        allowed_roots.append(Path(HOST_HOME).expanduser().resolve())
    if HOST_HOME_MOUNT:
        allowed_roots.append(Path(HOST_HOME_MOUNT).expanduser().resolve())
    if HOST_REPO_ROOT:
        allowed_roots.append(Path(HOST_REPO_ROOT).expanduser().resolve())

    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except Exception:
            continue
    return None


def _local_preview_url_for_file(path: Path, request: Request) -> str:
    host_context = _resolve_public_host_context(request)
    base_url = host_context.get("authoritative_public_base_url") or str(request.base_url).rstrip("/")
    return f"{base_url.rstrip('/')}/preview/local-file?path={quote(str(path), safe='')}"


def _is_external_preview_ref(value: str) -> bool:
    text = (value or "").strip()
    if not text or text.startswith("#") or text.startswith("/"):
        return True
    if text.startswith(("?", "data:", "blob:", "mailto:", "tel:", "javascript:")):
        return True
    parsed = urlsplit(text)
    return bool(parsed.scheme or parsed.netloc)


def _preview_asset_url_for_ref(base_dir: Path, value: str) -> str:
    if _is_external_preview_ref(value):
        return value
    parsed = urlsplit(value)
    target = (base_dir / unquote(parsed.path)).resolve()
    rewritten = f"/preview/local-file?path={quote(str(target), safe='')}"
    if parsed.fragment:
        rewritten = f"{rewritten}#{parsed.fragment}"
    return rewritten


def _rewrite_preview_srcset(base_dir: Path, value: str) -> str:
    rewritten_items: List[str] = []
    for item in value.split(","):
        segment = item.strip()
        if not segment:
            continue
        parts = segment.split()
        parts[0] = _preview_asset_url_for_ref(base_dir, parts[0])
        rewritten_items.append(" ".join(parts))
    return ", ".join(rewritten_items)


def _rewrite_preview_html_assets(html: str, base_dir: Path) -> str:
    def replace_attr(match: re.Match[str]) -> str:
        value = match.group("value")
        rewritten = _preview_asset_url_for_ref(base_dir, value)
        return f"{match.group('prefix')}{match.group('quote')}{rewritten}{match.group('quote')}"

    def replace_srcset(match: re.Match[str]) -> str:
        value = match.group("value")
        rewritten = _rewrite_preview_srcset(base_dir, value)
        return f"{match.group('prefix')}{match.group('quote')}{rewritten}{match.group('quote')}"

    html = PREVIEW_REWRITABLE_ATTR_PATTERN.sub(replace_attr, html)
    return PREVIEW_SRCSET_ATTR_PATTERN.sub(replace_srcset, html)


def _rewrite_preview_css_assets(css: str, base_dir: Path) -> str:
    def replace_url(match: re.Match[str]) -> str:
        value = match.group("value").strip()
        rewritten = _preview_asset_url_for_ref(base_dir, value)
        quote_char = match.group("quote") or ""
        return f"url({quote_char}{rewritten}{quote_char})"

    return PREVIEW_CSS_URL_PATTERN.sub(replace_url, css)


def _scan_workspace_preview_files(workspace: Path) -> List[Dict[str, Any]]:
    try:
        root = workspace.resolve()
    except Exception:
        return []
    if not root.is_dir():
        return []

    preview_files: List[Dict[str, Any]] = []
    visited_files = 0
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if name not in PREVIEW_SCAN_IGNORED_DIRS and not name.endswith(".egg-info")
        ]
        for filename in filenames:
            visited_files += 1
            if visited_files > PREVIEW_SCAN_MAX_FILES:
                break
            suffix = Path(filename).suffix.lower()
            if suffix not in PREVIEW_SWITCHABLE_SUFFIXES:
                continue
            absolute_path = (Path(current_root) / filename).resolve()
            try:
                relative = absolute_path.relative_to(root).as_posix()
                stat = absolute_path.stat()
            except Exception:
                continue
            insertions = 0
            if suffix in {".html", ".htm", ".json"}:
                try:
                    insertions = len(absolute_path.read_text(encoding="utf-8", errors="ignore").splitlines())
                except Exception:
                    pass
            preview_files.append({
                "path": relative,
                "status": "preview",
                "insertions": insertions,
                "deletions": 0,
                "mtime": stat.st_mtime,
                "kind": suffix.lstrip("."),
                "absolute_path": _runtime_to_host_path(str(absolute_path)),
            })
            if len(preview_files) >= PREVIEW_SCAN_MAX_RESULTS:
                break
        if visited_files > PREVIEW_SCAN_MAX_FILES or len(preview_files) >= PREVIEW_SCAN_MAX_RESULTS:
            break

    def _rank(item: Dict[str, Any]) -> tuple:
        path = str(item.get("path") or "").lower()
        suffix = Path(path).suffix.lower()
        kind_score = {
            ".html": 6,
            ".htm": 6,
            ".svg": 5,
            ".png": 4,
            ".jpg": 4,
            ".jpeg": 4,
            ".webp": 4,
            ".gif": 4,
            ".avif": 4,
            ".pdf": 3,
            ".mp4": 3,
            ".webm": 3,
            ".json": 2,
            ".mp3": 1,
            ".wav": 1,
            ".ogg": 1,
        }.get(suffix, 0)
        name_score = 2 if path.endswith("index.html") else 1 if any(
            token in path for token in ("game", "play", "demo", "app", "preview", "result", "output")
        ) else 0
        return (kind_score, name_score, float(item.get("mtime") or 0))

    preview_files.sort(key=_rank, reverse=True)
    return preview_files


async def _probe_preview_url(url: str) -> Optional[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=2.2) as client:
            response = await client.get(url)
    except Exception:
        return None
    if response.status_code >= 400:
        return None

    content_type = response.headers.get("content-type", "")
    body_prefix = response.text[:1200] if response.text else ""
    html_like = "text/html" in content_type.lower() or "<html" in body_prefix.lower() or "<!doctype html" in body_prefix.lower()
    return {
        "url": str(response.url),
        "status": response.status_code,
        "content_type": content_type,
        "html_like": html_like,
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


def _persist_context_cache(session_id: str, runtime_agent: Any) -> None:
    if runtime_agent is None:
        return
    cache = getattr(runtime_agent, "session_context_cache", {}).get(session_id)
    session_store.persist_context_cache(session_id, cache)


def _ensure_session_state_loaded(session_id: str, runtime_agent: Optional[Any] = None) -> None:
    cache_store = getattr(runtime_agent, "session_context_cache", None) if runtime_agent is not None else None
    session_store.ensure_session_state_loaded(session_id, chat_sessions, cache_store if isinstance(cache_store, dict) else None)


def _resolve_workspace_path(path_str: str) -> Path:
    workspace = _host_to_runtime_path(path_str)
    if not workspace.exists():
        raise FileNotFoundError(f"Workspace does not exist: {path_str}")
    if not workspace.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {path_str}")
    return workspace


def _resolve_or_create_workspace_path(path_str: str) -> Path:
    workspace = _host_to_runtime_path(path_str)
    workspace.mkdir(parents=True, exist_ok=True)
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
            result = (Path(config.work_dir).resolve().parent / relative).resolve()
            if result.exists():
                return result
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


def _default_workspace_runtime() -> str:
    return str(Path(config.work_dir).expanduser().resolve())


def _default_workspace() -> str:
    return _runtime_to_host_path(_default_workspace_runtime())


def _workspace_payload_for_runtime_path(runtime_path: str) -> Dict[str, Any]:
    runtime = str(Path(runtime_path).expanduser().resolve())
    display = _runtime_to_host_path(runtime)
    display_path = Path(display)
    return {
        "path": display,
        "runtime_path": runtime,
        "name": display_path.name or display,
        "parent": str(display_path.parent) if display_path.parent != display_path else None,
    }


def _resolve_request_workspace(session_id: str, workspace_path: Optional[str]) -> Dict[str, Any]:
    path_str = (workspace_path or "").strip()
    if path_str:
        runtime_workspace = _resolve_or_create_workspace_path(path_str)
    else:
        runtime_workspace = Path(_thread_workspace_for_session(session_id)).resolve()
    return _workspace_payload_for_runtime_path(str(runtime_workspace))


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
            "router": "HarnessRuntime.chat_stream()",
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
        resolved_name = (
            skill_manager.resolve_skill_name_for_tool(tool_name)
            or tool_name
        )
        search_skills = {
            "web-search-free",
            "search",
            "web-scraper-pro",
            "firecrawl-scraper",
            "skill-lookup",
        }
        if resolved_name in search_skills and session_id:
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
    try:
        skill_manager.set_workspace(_default_workspace_runtime())
    except Exception as exc:
        logger.warning(f"Failed to initialize default workspace {_default_workspace_runtime()}: {exc}")

    asyncio.create_task(_watch_skills_dir())
    
    # 初始化VLLM客户端
    vllm_client = VLLMClient(
        config.vllm, 
        vision_config=config.vision_vllm,
        gpt55_config=config.gpt55
    )
    await vllm_client.__aenter__()
    
    harness_runtime = HarnessRuntime(
        vllm_client,
        skill_manager,
        request_lifecycle=request_lifecycle,
    )
    app.state.harness_runtime = harness_runtime
    
    logger.info("OBS Code API 启动完成")
    
    # 同时存储在app.state中
    app.state.skill_manager = skill_manager
    app.state.vllm_client = vllm_client
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
        "name": "OBS Code API",
        "version": "1.0.0",
        "description": "全能AI Agent - 支持Claude Skills三级架构",
        "message": "前端页面未找到，请访问 /docs 查看API文档"
    })


@app.get("/health")
async def health():
    """健康检查 - 静默模式"""
    skills_count = len(skill_manager.skills) if skill_manager else 0
    return {"status": "ok", "version": app.version, "skills_count": skills_count}

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
            "work_dir": _default_workspace(),
            "runtime_work_dir": _default_workspace_runtime(),
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


@app.post("/preview/resolve")
async def resolve_preview_url(payload: PreviewResolveRequest, request: Request):
    """Resolve a transcript-derived preview URL to a reachable local app page."""
    host_context = _resolve_public_host_context(request)
    authoritative_host = host_context.get("authoritative_public_host") or ""
    own_origin = _url_origin(host_context.get("authoritative_public_base_url") or str(request.base_url).rstrip("/"))

    seen: set[str] = set()
    probes: List[Dict[str, Any]] = []
    html_fallback: Optional[Dict[str, Any]] = None
    any_fallback: Optional[Dict[str, Any]] = None

    for raw_url in (payload.urls or [])[:12]:
        local_file = _resolve_local_preview_file(raw_url, html_only=True)
        if local_file:
            url = _local_preview_url_for_file(local_file, request)
            probe = {
                "url": url,
                "status": 200,
                "content_type": "text/html; charset=utf-8",
                "html_like": True,
                "source": "local-file",
                "path": _runtime_to_host_path(str(local_file)),
            }
            return JSONResponse({"success": True, "url": url, "probe": probe, "probes": [probe]})

        for candidate in _preview_url_variants(raw_url, authoritative_host):
            if candidate in seen:
                continue
            seen.add(candidate)
            if own_origin and _url_origin(candidate) == own_origin:
                probes.append({"url": candidate, "skipped": "own-origin"})
                continue

            probe = await _probe_preview_url(candidate)
            if not probe:
                probes.append({"url": candidate, "reachable": False})
                continue
            probes.append({"url": candidate, "reachable": True, **probe})
            any_fallback = any_fallback or probe
            if probe.get("html_like"):
                html_fallback = probe
                return JSONResponse({"success": True, "url": probe["url"], "probe": probe, "probes": probes})

    fallback = html_fallback or any_fallback
    if fallback:
        return JSONResponse({"success": True, "url": fallback["url"], "probe": fallback, "probes": probes})
    return JSONResponse({"success": False, "url": "", "probes": probes})


@app.get("/preview/local-file")
async def serve_local_preview_file(path: str = Query(default="")):
    """Serve a generated local HTML file inside the live preview iframe."""
    resolved = _resolve_local_preview_file(path, html_only=False)
    if not resolved:
        return JSONResponse({"detail": "Preview file not found or not allowed"}, status_code=404)
    suffix = resolved.suffix.lower()
    media_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
    if suffix in {".html", ".htm"}:
        html = resolved.read_text(encoding="utf-8", errors="ignore")
        response = Response(
            _rewrite_preview_html_assets(html, resolved.parent),
            media_type="text/html; charset=utf-8",
        )
    elif suffix == ".css":
        css = resolved.read_text(encoding="utf-8", errors="ignore")
        response = Response(
            _rewrite_preview_css_assets(css, resolved.parent),
            media_type="text/css; charset=utf-8",
        )
    else:
        response = FileResponse(str(resolved), media_type=media_type)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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


def _published_project_score(project: Dict[str, Any]) -> int:
    leaderboard = int(project.get("leaderboard_score") or 0)
    remixes = int(project.get("remix_count") or 0)
    launches = int(project.get("launch_count") or 0)
    return leaderboard + remixes * 6 + launches * 2


def _published_project_summary(project: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(project)
    summary["leaderboard_score"] = _published_project_score(summary)
    return summary


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


def _fallback_title_from_prompt(prompt: str) -> str:
    cleaned = (prompt or "").strip()
    cleaned = re.sub(r"[：:]", " ", cleaned)
    cleaned = re.sub(r"[，,。！!？?].*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:12].strip()


@app.post("/ui/title-suggestion")
async def suggest_ui_title(payload: TitleSuggestionRequest):
    prompt = (payload.prompt or "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt is required"}, status_code=400)
    fallback_title = _fallback_title_from_prompt(prompt)
    if vllm_client is None:
        return JSONResponse({"title": fallback_title, "fallback": True})
    title_prompt = (
        "你是一个作品命名助手。请根据下面的创建需求，为即将生成的作品起一个简短、自然、面向用户的中文标题。\n"
        "要求：\n"
        "1. 标题长度 4 到 12 个汉字优先。\n"
        "2. 不要使用引号、书名号、句号、冒号。\n"
        "3. 不要出现‘生成一个’‘帮我做’‘网页游戏’这类命令式前缀。\n"
        "4. 禁止输出思考过程、解释、列表或 markdown。\n"
        "5. 只返回标题本身。\n\n"
        f"创建需求：{prompt}"
    )
    try:
        title = await vllm_client.generate_text(title_prompt, model=payload.model, temperature=0.2, max_tokens=32)
        raw = str(title or "")
        cleaned = re.sub(r"<think>[\s\S]*?<\/think>", "", raw, flags=re.I).strip()
        cleaned = cleaned.replace("\r", "\n")
        lines = [re.sub(r"^[#*\-\d.\s]+", "", line).strip() for line in cleaned.split("\n") if line.strip()]
        picked = ""
        for candidate in reversed(lines):
            candidate = candidate.strip('"“”「」[]()《》')
            candidate = candidate.replace("**", "").replace("`", "").strip()
            if candidate:
                picked = candidate
                break
        final_title = re.sub(r"\s+", " ", picked or cleaned).strip()
        final_title = final_title.strip('"“”「」[]()《》')
        final_title = re.sub(r"^[#*\-\d.\s]+", "", final_title)
        final_title = final_title[:24].strip() or fallback_title
        return JSONResponse({"title": final_title, "fallback": final_title == fallback_title})
    except Exception as exc:
        logger.warning(f"Failed to generate UI title suggestion: {exc}")
        return JSONResponse({"title": fallback_title, "fallback": True})


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


@app.get("/published-projects")
async def list_published_projects():
    projects = [_published_project_summary(item) for item in session_store.list_published_projects()]
    latest = sorted(
        projects,
        key=lambda item: item.get("published_at") or item.get("updated_at") or "",
        reverse=True,
    )
    leaderboard = sorted(
        projects,
        key=lambda item: (item.get("leaderboard_score") or 0, item.get("published_at") or ""),
        reverse=True,
    )
    return JSONResponse({
        "projects": latest,
        "discover": latest[:24],
        "leaderboard": leaderboard[:24],
    })


@app.post("/published-projects")
async def publish_project(payload: PublishProjectRequest):
    project_id = f"project_{int(datetime.now().timestamp() * 1000)}"
    published_at = datetime.now().astimezone().isoformat(timespec="seconds")
    session_snapshot = session_store.load_ui_session(payload.session_id) or {}
    transcript = session_snapshot.get("transcript") if isinstance(session_snapshot, dict) else None
    user_prompt = payload.prompt
    if not user_prompt and isinstance(transcript, list):
        for entry in transcript:
            if entry.get("role") == "user" and entry.get("content"):
                user_prompt = str(entry.get("content"))
                break
    record = {
        "id": project_id,
        "session_id": payload.session_id,
        "title": payload.title.strip() or "未命名作品",
        "prompt": (user_prompt or "").strip(),
        "description": (payload.description or "").strip(),
        "preview_url": (payload.preview_url or "").strip(),
        "preview_label": (payload.preview_label or "").strip(),
        "workspace_path": (payload.workspace_path or "").strip(),
        "mode": payload.mode or "create",
        "tags": [str(tag).strip() for tag in (payload.tags or []) if str(tag).strip()],
        "remixable": bool(payload.remixable),
        "published_at": published_at,
        "updated_at": published_at,
        "remix_count": 0,
        "launch_count": 0,
        "leaderboard_score": 0,
    }
    session_store.save_published_project(project_id, record)
    return JSONResponse({"ok": True, "project": _published_project_summary(record)})


@app.delete("/published-projects/{project_id}")
async def delete_published_project(project_id: str):
    session_store.delete_published_project(project_id)
    return JSONResponse({"ok": True})


@app.get("/workspace")
async def get_workspace_state(session_id: Optional[str] = Query(default=None)):
    runtime_path = _thread_workspace_for_session(session_id) if session_id else _default_workspace_runtime()
    return JSONResponse({"workspace": _workspace_payload_for_runtime_path(runtime_path)})


@app.post("/workspace")
async def update_workspace_state(payload: WorkspaceUpdateRequest):
    if skill_manager is None:
        return JSONResponse({"success": False, "error": "Skill manager not initialized"}, status_code=503)
    try:
        workspace = _resolve_or_create_workspace_path(payload.path)
        return JSONResponse({
            "success": True,
            "workspace": _workspace_payload_for_runtime_path(str(workspace))
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


@app.get("/workspace/browser")
async def browse_workspace(path: Optional[str] = Query(default=None), session_id: Optional[str] = Query(default=None)):
    try:
        current = _resolve_workspace_path(path) if path else Path(
            _thread_workspace_for_session(session_id) if session_id else _default_workspace_runtime()
        ).resolve()
    except Exception:
        current = Path(_thread_workspace_for_session(session_id) if session_id else _default_workspace_runtime()).resolve()

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


@app.get("/workspace/changes")
async def workspace_changes(path: Optional[str] = Query(default=None)):
    try:
        workspace = _resolve_workspace_path(path) if path else Path(_default_workspace_runtime()).resolve()
    except Exception:
        workspace = Path(_default_workspace_runtime()).resolve()

    def _git(args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    try:
        inside = _git(["rev-parse", "--is-inside-work-tree"])
        preview_files = _scan_workspace_preview_files(workspace)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return JSONResponse({
                "success": True,
                "workspace": _runtime_to_host_path(str(workspace)),
                "is_git": False,
                "changed_files": 0,
                "insertions": 0,
                "deletions": 0,
                "branch": "",
                "files": [],
                "preview_files": preview_files,
            })

        status_proc = _git(["status", "--short", "--untracked-files=all", "--", "."])
        diff_proc = _git(["diff", "--numstat", "HEAD", "--", "."])
        top_proc = _git(["rev-parse", "--show-toplevel"])
        prefix_proc = _git(["rev-parse", "--show-prefix"])
        branch_proc = _git(["branch", "--show-current"])

        repo_root = Path(top_proc.stdout.strip()).resolve() if top_proc.returncode == 0 and top_proc.stdout.strip() else workspace
        workspace_prefix = prefix_proc.stdout.strip() if prefix_proc.returncode == 0 else ""
        numstat_map: Dict[str, Dict[str, int]] = {}
        for line in diff_proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            ins_raw, del_raw, file_path = parts[:3]
            numstat_map[file_path] = {
                "insertions": int(ins_raw) if ins_raw.isdigit() else 0,
                "deletions": int(del_raw) if del_raw.isdigit() else 0,
            }
            if workspace_prefix and file_path.startswith(workspace_prefix):
                numstat_map[file_path[len(workspace_prefix):]] = numstat_map[file_path]

        files = []
        total_insertions = 0
        total_deletions = 0
        for raw in status_proc.stdout.splitlines():
            if not raw.strip():
                continue
            status = raw[:2]
            relative = raw[3:].strip()
            if " -> " in relative:
                relative = relative.split(" -> ", 1)[1].strip()
            stats = numstat_map.get(relative) or numstat_map.get(f"{workspace_prefix}{relative}") or {"insertions": 0, "deletions": 0}
            absolute_path = (workspace / relative).resolve()
            if status == "??" and absolute_path.is_file():
                try:
                    content = absolute_path.read_text(encoding="utf-8", errors="ignore")
                    stats = {**stats, "insertions": len(content.splitlines())}
                except Exception:
                    pass
            total_insertions += stats["insertions"]
            total_deletions += stats["deletions"]
            files.append({
                "path": relative,
                "status": status,
                "insertions": stats["insertions"],
                "deletions": stats["deletions"],
                "absolute_path": _runtime_to_host_path(str(absolute_path)),
            })

        return JSONResponse({
            "success": True,
            "workspace": _runtime_to_host_path(str(workspace)),
            "repo_root": _runtime_to_host_path(str(repo_root)),
            "scope": "workspace",
            "is_git": True,
            "branch": branch_proc.stdout.strip() if branch_proc.returncode == 0 else "",
            "changed_files": len(files),
            "insertions": total_insertions,
            "deletions": total_deletions,
            "files": files[:120],
            "preview_files": preview_files,
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=400)


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
async def pick_workspace_directory(session_id: Optional[str] = Query(default=None)):
    try:
        initial_path = _runtime_to_host_path(_thread_workspace_for_session(session_id)) if session_id else _default_workspace()
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
    harness_runtime = getattr(app.state, "harness_runtime", None)
    _ensure_session_state_loaded(session_id, harness_runtime)
    messages = chat_sessions.get(session_id, [])
    context_percent = 0
    estimated_context_tokens = 0
    max_context_tokens = 128000
    if harness_runtime is not None:
        cache = getattr(harness_runtime, "session_context_cache", {}).get(session_id, {})
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
            context_percent = harness_runtime._estimate_context_percent(compact_messages)
            estimated_context_tokens = harness_runtime._estimate_context_tokens(compact_messages)
        else:
            context_percent = harness_runtime._estimate_context_percent(messages)
            estimated_context_tokens = harness_runtime._estimate_context_tokens(messages)
        max_context_tokens = harness_runtime._get_context_window_tokens(model)
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
    workspace_path = request_data.workspace_path if request_data.workspace_path is not None else params.get("workspace_path")
    message_parts = request_data.message_parts if request_data.message_parts is not None else params.get("message_parts")
    selected_model = request_data.model if request_data.model is not None else params.get("model") or config.vllm.model
    temporal_context = _get_runtime_temporal_context()
    
    async def generate():
        harness_runtime = getattr(app.state, "harness_runtime", None)
        async with workspace_request_lock:
            try:
                _ensure_session_state_loaded(session_id, harness_runtime)
                location = session_locations.get(session_id)
                host_context = _resolve_public_host_context(request)
                request_workspace = _resolve_request_workspace(session_id, workspace_path)
                if skill_manager is not None:
                    skill_manager.set_workspace(request_workspace["runtime_path"])

                # 添加用户消息到会话历史
                chat_sessions[session_id].append({
                    "role": "user",
                    "content": message,
                    "message_parts": message_parts or [],
                })
                _persist_chat_session(session_id)

                # 使用 HarnessRuntime 流式状态机处理请求
                async for chunk in harness_runtime.chat_stream(
                    session_id,
                    chat_sessions,
                    mode=mode,
                    permission_mode=permission_mode,
                    permission_confirmed=permission_confirmed,
                    context=context,
                    tool_context=tool_context,
                    enabled_skills=None,
                    request_context={
                    **temporal_context,
                    "session_id": session_id,
                    "mode": mode,
                    "permission_mode": permission_mode,
                    "location": location,
                        "workspace_display_path": request_workspace["path"],
                        "workspace_runtime_path": request_workspace["runtime_path"],
                        "thread_runtime_dir": _thread_workspace_for_session(session_id),
                        **host_context,
                        "message_parts": message_parts or [],
                        "model": selected_model,
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
                logger.error(f"Chat stream error: {error_detail}")
                # Include error type and truncated traceback so the frontend can display
                # a meaningful diagnostic message instead of a generic "failed" notice.
                last_line = error_detail.strip().rsplit("\n", 1)[-1].strip() if error_detail else str(e)
                yield f"data: {json.dumps({'error': str(e), 'error_type': type(e).__name__, 'error_detail': last_line, 'done': True})}\n\n"
            finally:
                try:
                    _persist_chat_session(session_id)
                    _persist_context_cache(session_id, harness_runtime)
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
                        "content": """你是OBS Code智能助手。

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
                assistant_message = normalize_llm_message_content(
                    response["choices"][0]["message"].get("content")
                )
                
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
                            final_message = normalize_llm_message_content(
                                final_response["choices"][0]["message"].get("content")
                            )
                            
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

# 导出app实例
__all__ = ["app"]
