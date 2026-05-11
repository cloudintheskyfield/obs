"""Agent模块."""

__all__ = ["WebAgent"]


def __getattr__(name: str):
    if name == "WebAgent":
        from .web_agent import WebAgent

        return WebAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
