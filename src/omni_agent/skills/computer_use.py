from __future__ import annotations

from ._compat import load_claude_skill_module


_module = load_claude_skill_module(
    ["computer-use", "computer_use.py"],
    "omni_agent.skills._computer_use_impl",
)

ComputerUseSkill = _module.ComputerUseSkill

__all__ = ["ComputerUseSkill"]
