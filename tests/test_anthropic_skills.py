from __future__ import annotations

import asyncio
from pathlib import Path

from skills.skill_manager import SkillManager


def test_harness_skills_emit_source_backed_instruction_tools_without_legacy_aliases() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    manager = SkillManager({
        "work_dir": str(repo_root),
        "screenshot_dir": str(repo_root / "screenshots"),
        "enable_computer_use": True,
        "enable_text_editor": True,
        "enable_bash": True,
    })

    tool_names = {tool["name"] for tool in manager.get_anthropic_tools()}
    assert "desktop-commander" in tool_names
    assert "file-manager" in tool_names
    assert "computer-use" in tool_names
    assert "bash" not in tool_names
    assert "str_replace_editor" not in tool_names
    assert manager.get_skill_instructions("web-search-free")
    assert manager.get_skill_instructions("desktop-commander")

    async def run_checks() -> None:
        bash_result = await manager.execute_skill("desktop-commander", command="pwd")
        assert bash_result.success is True
        assert bash_result.metadata["mode"] == "instruction_only"

        view_result = await manager.execute_skill("file-manager", command="view", path="AGENTS.md")
        assert view_result.success is True
        assert view_result.metadata["mode"] == "instruction_only"

        search_result = await manager.execute_skill("search", query="obs harness orchestrator spec")
        assert search_result.success is True
        assert search_result.metadata["mode"] == "instruction_only"

    asyncio.run(run_checks())
