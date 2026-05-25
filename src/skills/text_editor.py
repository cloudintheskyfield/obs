from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from utils.paths import src_skills_root
_skills_root = src_skills_root()
if str(_skills_root) not in sys.path:
    sys.path.insert(0, str(_skills_root))

_module_path = _skills_root / "file-manager" / "text_editor.py"
_spec = importlib.util.spec_from_file_location("skills._file_manager_text_editor", _module_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load TextEditorSkill from {_module_path}")
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

TextEditorSkill = _module.TextEditorSkill

__all__ = ["TextEditorSkill"]
