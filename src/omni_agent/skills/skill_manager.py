from __future__ import annotations

from ._compat import load_claude_skill_module


_module = load_claude_skill_module(["skill_manager.py"], "omni_agent.skills._skill_manager_impl")

SkillManager = _module.SkillManager

__all__ = ["SkillManager"]
