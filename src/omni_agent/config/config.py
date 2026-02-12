"""配置管理"""
import os
from typing import Optional, Dict, Any, List
from pathlib import Path

from pydantic import BaseModel, Field
from loguru import logger


class VLLMConfig(BaseModel):
    """VLLM客户端配置"""
    base_url: str = "http://223.109.239.14:10002/v1/chat/completions"
    api_key: str = "dummy_key"
    model: str = "multimodal_model"
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
    
    # 确保工作目录存在
    Path(config.work_dir).mkdir(parents=True, exist_ok=True)
    Path(config.screenshot_dir).mkdir(parents=True, exist_ok=True)
    
    return config