"""日志管理系统"""
import sys
from typing import Optional
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.table import Table

from ..config.config import LogConfig


def setup_logger(config: LogConfig) -> logger:
    """设置日志系统"""
    # 移除默认处理器
    logger.remove()
    
    # 控制台处理器
    logger.add(
        sys.stderr,
        level=config.level,
        format=config.format,
        colorize=True
    )
    
    # 文件处理器（如果指定）
    if config.file_path:
        log_path = Path(config.file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            str(log_path),
            level=config.level,
            format=config.format,
            rotation=config.rotation,
            retention=config.retention,
            encoding="utf-8"
        )
    
    return logger


def start_live_logging():
    """启动实时日志显示"""
    console = Console()
    
    def create_log_table():
        table = Table(title="🤖 Omni Agent Live Logs")
        table.add_column("Time", style="cyan", width=12)
        table.add_column("Level", style="bold", width=8)
        table.add_column("Message", style="white")
        return table
    
    # 这是一个简单的实现
    # 在实际项目中可以使用更复杂的实时日志显示
    logger.info("Live logging started")
    return console