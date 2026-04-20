from __future__ import annotations

from ._compat import load_claude_skill_module


_module = load_claude_skill_module(["skill_loader.py"], "omni_agent.skills._skill_loader_impl")

SkillDefinition = _module.SkillDefinition
SkillLoader = _module.SkillLoader

__all__ = ["SkillDefinition", "SkillLoader"]
