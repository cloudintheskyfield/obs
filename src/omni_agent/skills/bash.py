from __future__ import annotations

from ._compat import load_claude_skill_module


_module = load_claude_skill_module(
    ["terminal", "bash.py"],
    "omni_agent.skills._bash_impl",
)

BashSkill = _module.BashSkill

__all__ = ["BashSkill"]
