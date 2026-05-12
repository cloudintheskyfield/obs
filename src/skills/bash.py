from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_skills_root = Path(__file__).resolve().parent
if str(_skills_root) not in sys.path:
    sys.path.insert(0, str(_skills_root))

_module_path = _skills_root / "desktop-commander" / "bash.py"
_spec = importlib.util.spec_from_file_location("skills._desktop_commander_bash", _module_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load BashSkill from {_module_path}")
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

BashSkill = _module.BashSkill

__all__ = ["BashSkill"]
