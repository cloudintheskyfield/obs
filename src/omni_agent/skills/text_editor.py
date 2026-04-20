from __future__ import annotations

from ._compat import load_claude_skill_module


_module = load_claude_skill_module(
    ["file-operations", "text_editor.py"],
    "omni_agent.skills._text_editor_impl",
)

TextEditorSkill = _module.TextEditorSkill

__all__ = ["TextEditorSkill"]
