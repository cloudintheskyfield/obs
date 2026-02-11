"""
Omni Agent - Full-featured AI agent with multimodal capabilities
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

from .core.agent import OmniAgent
from .core.logger import setup_logger

__all__ = ["OmniAgent", "setup_logger"]