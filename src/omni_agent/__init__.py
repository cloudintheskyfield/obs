"""
Omni Agent - Full-featured AI agent with multimodal capabilities.

Keep package import lightweight so subpackages such as `omni_agent.skills`
remain usable even when optional runtime dependencies are missing.
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

__all__ = ["OmniAgent", "setup_logger"]


def __getattr__(name: str):
    if name == "OmniAgent":
        from .core.agent import OmniAgent

        return OmniAgent
    if name == "setup_logger":
        from .core.logger import setup_logger

        return setup_logger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
