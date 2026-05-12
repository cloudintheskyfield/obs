import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def src_skills_root() -> Path:
    return app_root() / "src" / "skills"



def frontend_root() -> Path:
    return app_root() / "frontend"


def frontend_dist_root() -> Path:
    return frontend_root() / "dist"


def frontend_static_root() -> Path:
    dist = frontend_dist_root()
    return dist if dist.exists() else frontend_root()
