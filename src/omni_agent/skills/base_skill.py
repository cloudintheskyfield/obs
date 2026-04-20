from __future__ import annotations

from ._compat import load_claude_skill_module


_module = load_claude_skill_module(["base_skill.py"], "omni_agent.skills._base_skill_impl")

BaseSkill = _module.BaseSkill
SkillParameter = _module.SkillParameter
SkillResult = _module.SkillResult

__all__ = ["BaseSkill", "SkillParameter", "SkillResult"]
