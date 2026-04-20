from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from ..utils.paths import claude_skills_root


def _load_module_from_path(module_name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module {module_name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_claude_skill_module(relative_parts: list[str], module_name: str) -> ModuleType:
    skills_root = claude_skills_root()
    module_path = skills_root.joinpath(*relative_parts)
    module_parent = str(module_path.parent)
    if module_parent not in sys.path:
        sys.path.insert(0, module_parent)
    skills_root_str = str(skills_root)
    if skills_root_str not in sys.path:
        sys.path.insert(0, skills_root_str)
    return _load_module_from_path(module_name, module_path)
