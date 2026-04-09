"""配置管理"""
import os
import sys
from typing import Optional, Dict, Any, List, Iterable
from pathlib import Path

from pydantic import BaseModel, Field
from loguru import logger
from dotenv import load_dotenv

from ..utils.paths import app_root, claude_skills_root


def _runtime_data_root() -> Path:
    """Return a writable per-user directory for packaged/native desktop runs."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OBS Agent Desktop"
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "OBS Agent Desktop"
        return Path.home() / "AppData" / "Roaming" / "OBS Agent Desktop"
    xdg_config = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "obs-agent"


def _config_base_dir() -> Path:
    """Choose the base directory for relative runtime paths."""
    if getattr(sys, "frozen", False):
        root = _runtime_data_root()
        root.mkdir(parents=True, exist_ok=True)
        return root
    return app_root()


def _iter_env_candidates() -> Iterable[Path]:
    """Yield candidate .env files in descending priority order."""
    seen: set[Path] = set()
    explicit_env = os.getenv("OMNI_AGENT_ENV_FILE")
    if explicit_env:
        candidate = Path(explicit_env).expanduser()
        if candidate not in seen:
            seen.add(candidate)
            yield candidate

    candidates = [
        Path.cwd() / ".env",
        _runtime_data_root() / ".env",
        Path(sys.executable).resolve().parent / ".env",
        app_root() / ".env",
    ]

    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def _load_env_files() -> None:
    for env_file in _iter_env_candidates():
        if env_file.exists():
            load_dotenv(env_file, override=False)


def _ensure_directory(path: Path, fallback: Path, label: str) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError as exc:
        logger.warning(f"Failed to create {label} at {path}: {exc}. Falling back to {fallback}")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _resolve_dir_setting(raw_value: str, default_name: str, label: str) -> str:
    base_dir = _config_base_dir()
    fallback = base_dir / default_name
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return str(_ensure_directory(candidate, fallback, label))


def _resolve_file_setting(raw_value: Optional[str], fallback_relative: str, label: str) -> Optional[str]:
    if not raw_value:
        return None

    base_dir = _config_base_dir()
    fallback = base_dir / fallback_relative
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate

    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return str(candidate)
    except OSError as exc:
        logger.warning(f"Failed to prepare {label} path {candidate}: {exc}. Falling back to {fallback}")
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return str(fallback)


def _resolve_skills_dir(raw_value: Optional[str]) -> Optional[str]:
    bundled_skills = claude_skills_root()
    candidates: List[Path] = []

    if raw_value:
        candidate = Path(raw_value).expanduser()
        if not candidate.is_absolute():
            candidate = _config_base_dir() / candidate
        candidates.append(candidate)

    candidates.extend(
        [
            Path.cwd() / ".claude" / "skills",
            bundled_skills,
            _runtime_data_root() / ".claude" / "skills",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return str(bundled_skills) if bundled_skills.exists() else None


class VLLMConfig(BaseModel):
    """VLLM客户端配置"""
    base_url: str = "https://api.minimaxi.com/v1/chat/completions"
    api_key: str = "dummy_key"
    model: str = "MiniMax-M2"
    timeout: int = 60
    max_retries: int = 3


class WebBrowsingConfig(BaseModel):
    """网页浏览配置"""
    headless: bool = False
    timeout: int = 30
    screenshot_dir: str = "screenshots"
    viewport_width: int = 1280
    viewport_height: int = 720


class LogConfig(BaseModel):
    """日志配置"""
    level: str = "INFO"
    file_path: Optional[str] = None
    rotation: str = "10 MB"
    retention: str = "7 days"
    format: str = "<green>{time}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"


class AgentConfig(BaseModel):
    """Agent配置"""
    # 核心配置
    work_dir: str = "workspace"
    screenshot_dir: str = "screenshots"
    skills_dir: Optional[str] = None
    
    # 组件配置
    vllm: VLLMConfig = Field(default_factory=VLLMConfig)
    web_browsing: WebBrowsingConfig = Field(default_factory=WebBrowsingConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    
    # Claude API
    claude_api_key: Optional[str] = None
    
    # Skills启用配置
    enable_computer_use: bool = True
    enable_text_editor: bool = True
    enable_bash: bool = True
    
    # 安全配置
    allow_file_operations: bool = True
    allow_terminal_execution: bool = True
    
    # 服务配置
    api_port: int = 8000
    web_port: int = 8080
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        """从环境变量加载配置"""
        config = cls()
        
        # VLLM配置
        if os.getenv("VLLM_BASE_URL"):
            config.vllm.base_url = os.getenv("VLLM_BASE_URL")
        if os.getenv("VLLM_API_KEY"):
            config.vllm.api_key = os.getenv("VLLM_API_KEY")
        if os.getenv("VLLM_MODEL"):
            config.vllm.model = os.getenv("VLLM_MODEL")
        
        # 工作目录
        if os.getenv("WORK_DIR"):
            config.work_dir = os.getenv("WORK_DIR")
        if os.getenv("SCREENSHOT_DIR"):
            config.screenshot_dir = os.getenv("SCREENSHOT_DIR")
            config.web_browsing.screenshot_dir = os.getenv("SCREENSHOT_DIR")
        
        # Claude API
        if os.getenv("CLAUDE_API_KEY"):
            config.claude_api_key = os.getenv("CLAUDE_API_KEY")
        
        # 安全配置
        if os.getenv("ALLOW_FILE_OPS"):
            config.allow_file_operations = os.getenv("ALLOW_FILE_OPS").lower() == "true"
        if os.getenv("ALLOW_TERMINAL"):
            config.allow_terminal_execution = os.getenv("ALLOW_TERMINAL").lower() == "true"
        
        # 日志配置
        if os.getenv("LOG_LEVEL"):
            config.log.level = os.getenv("LOG_LEVEL")
        if os.getenv("LOG_FILE"):
            config.log.file_path = os.getenv("LOG_FILE")
        
        # 网页浏览配置
        if os.getenv("WEB_HEADLESS"):
            config.web_browsing.headless = os.getenv("WEB_HEADLESS").lower() == "true"
        if os.getenv("WEB_TIMEOUT"):
            config.web_browsing.timeout = int(os.getenv("WEB_TIMEOUT"))
        
        # Skills配置
        if os.getenv("ENABLE_COMPUTER_USE"):
            config.enable_computer_use = os.getenv("ENABLE_COMPUTER_USE").lower() == "true"
        if os.getenv("ENABLE_TEXT_EDITOR"):
            config.enable_text_editor = os.getenv("ENABLE_TEXT_EDITOR").lower() == "true"
        if os.getenv("ENABLE_BASH"):
            config.enable_bash = os.getenv("ENABLE_BASH").lower() == "true"

        if os.getenv("SKILLS_DIR"):
            config.skills_dir = os.getenv("SKILLS_DIR")
        
        return config


def load_config(config_file: Optional[str] = None) -> AgentConfig:
    """加载配置"""
    _load_env_files()

    # 首先从环境变量加载
    config = AgentConfig.from_env()
    
    # 如果指定了配置文件，加载并合并
    if config_file and os.path.exists(config_file):
        try:
            import json
            with open(config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
            
            # 简单合并（文件配置覆盖环境变量）
            for key, value in file_config.items():
                if hasattr(config, key):
                    if isinstance(value, dict) and hasattr(getattr(config, key), '__dict__'):
                        # 嵌套对象合并
                        nested_obj = getattr(config, key)
                        for nested_key, nested_value in value.items():
                            if hasattr(nested_obj, nested_key):
                                setattr(nested_obj, nested_key, nested_value)
                    else:
                        setattr(config, key, value)
                        
        except Exception as e:
            logger.warning(f"Failed to load config file {config_file}: {e}")
    
    config.work_dir = _resolve_dir_setting(config.work_dir, "workspace", "work_dir")
    config.screenshot_dir = _resolve_dir_setting(config.screenshot_dir, "screenshots", "screenshot_dir")
    config.web_browsing.screenshot_dir = config.screenshot_dir
    config.log.file_path = _resolve_file_setting(config.log.file_path, "logs/omni_agent.log", "log_file")
    config.skills_dir = _resolve_skills_dir(config.skills_dir)
    
    return config
