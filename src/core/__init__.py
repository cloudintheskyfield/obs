"""核心模块."""

__all__ = [
    "setup_logger",
    "start_live_logging",
    "VLLMClient",
]


def __getattr__(name: str):
    if name in {"setup_logger", "start_live_logging"}:
        from .logger import setup_logger, start_live_logging

        return {
            "setup_logger": setup_logger,
            "start_live_logging": start_live_logging,
        }[name]
    if name == "VLLMClient":
        from .vllm_client import VLLMClient

        return VLLMClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
