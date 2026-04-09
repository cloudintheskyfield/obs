from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    """Resolve the project/resource root in source and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[3]


def claude_skills_root() -> Path:
    return app_root() / ".claude" / "skills"


def frontend_root() -> Path:
    return app_root() / "frontend"


def frontend_dist_root() -> Path:
    return frontend_root() / "dist"


def frontend_static_root() -> Path:
    if not getattr(sys, "frozen", False):
        source = frontend_root()
        if (source / "index.html").exists():
            return source
    dist = frontend_dist_root()
    return dist if dist.exists() else frontend_root()


def repo_skills_root() -> Path:
    return app_root() / "skills"
