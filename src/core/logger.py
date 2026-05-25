"""日志管理系统 — 统一配置 loguru，控制台 + 文件双输出"""
import sys
from pathlib import Path

from loguru import logger

from config.config import LogConfig


# 详细格式：时间 | 级别 | 模块:函数:行 — 消息
_DETAILED_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
    "— <level>{message}</level>"
)

# 文件日志格式（无 ANSI 颜色码）
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} "
    "— {message}"
)

_DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "OBSAgent"


def _default_log_path() -> Path:
    """当配置未指定日志路径时，使用默认位置。"""
    try:
        _DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        return _DEFAULT_LOG_DIR / "obs_agent.log"
    except OSError:
        return Path("/tmp/obs_agent.log")


def setup_logger(config: LogConfig) -> "logger":
    """
    初始化日志系统：
    - 始终输出到 stderr（控制台）
    - 始终写入日志文件（rotation 10 MB，保留 14 天）
    - DEBUG 级别及以上全量记录到文件，便于排查问题
    """
    logger.remove()

    # ── 控制台：用配置级别，带颜色 ──
    logger.add(
        sys.stderr,
        level=config.level,
        format=_DETAILED_FORMAT,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # ── 文件：固定写 DEBUG 及以上，无颜色，始终启用 ──
    log_file = Path(config.file_path) if config.file_path else _default_log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_file),
        level="DEBUG",
        format=_FILE_FORMAT,
        rotation=config.rotation,
        retention="14 days",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
        enqueue=True,            # 异步写文件，不阻塞主线程
    )

    logger.info(f"Logger initialised | console_level={config.level} | file={log_file}")
    return logger


def start_live_logging():
    """启动实时日志显示（保留兼容性）"""
    logger.info("Live logging started")


def stop_live_logging():
    """停止实时日志显示（保留兼容性）"""
    logger.info("Live logging stopped")