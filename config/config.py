"""配置管理模块"""
import os
from typing import Optional
from pydantic import BaseModel


class VLLMConfig(BaseModel):
    """VLLM配置"""
    base_url: str = "http://223.109.239.14:10002/v1/chat/completions"
    api_key: str = "dummy_key"  # VLLM通常不需要API密钥
    model: str = "/mnt2/data3/nlp/ws/model/Qwen3_omni/thinking"
    timeout: int = 30
    max_retries: int = 3


class WebBrowsingConfig(BaseModel):
    """网页浏览配置"""
    headless: bool = False  # 为了调试可以设为False
    timeout: int = 10
    screenshot_dir: str = "screenshots"
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class LogConfig(BaseModel):
    """日志配置"""
    level: str = "INFO"
    file_path: str = "logs/omni_agent.log"
    max_file_size: str = "10MB"
    backup_count: int = 5
    console_output: bool = True


class AgentConfig(BaseModel):
    """主Agent配置"""
    vllm: VLLMConfig = VLLMConfig()
    web_browsing: WebBrowsingConfig = WebBrowsingConfig()
    log: LogConfig = LogConfig()
    
    # Claude Skills配置
    claude_api_key: Optional[str] = None
    
    # 工作目录
    work_dir: str = "workspace"
    
    # 安全配置
    allow_file_operations: bool = True
    allow_terminal_execution: bool = True
    allowed_domains: list[str] = []  # 空列表表示允许所有域名


def load_config() -> AgentConfig:
    """加载配置"""
    # 从环境变量中读取配置
    config_dict = {
        "vllm": {
            "base_url": os.getenv("VLLM_BASE_URL", "http://223.109.239.14:10002/v1/chat/completions"),
            "api_key": os.getenv("VLLM_API_KEY", "dummy_key"),
            "model": os.getenv("VLLM_MODEL", "/mnt2/data3/nlp/ws/model/Qwen3_omni/thinking")
        },
        "claude_api_key": os.getenv("CLAUDE_API_KEY"),
        "work_dir": os.getenv("WORK_DIR", "workspace"),
        "allow_file_operations": os.getenv("ALLOW_FILE_OPS", "true").lower() == "true",
        "allow_terminal_execution": os.getenv("ALLOW_TERMINAL", "true").lower() == "true"
    }
    
    return AgentConfig(**config_dict)