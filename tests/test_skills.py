from __future__ import annotations

import asyncio
from pathlib import Path

from skills import SkillManager


def test_skills_are_source_backed_instruction_tools() -> None:
    manager = SkillManager({
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_text_editor": True,
        "enable_bash": True,
        "enable_computer_use": True,
    })

    catalog_names = {item["name"] for item in manager.get_skill_catalog()}
    assert "desktop-commander" in catalog_names
    assert "file-manager" in catalog_names
    assert "computer-use" in catalog_names
    assert "desktop-commander" in manager.skills
    assert "file-manager" in manager.skills
    assert "computer-use" in manager.skills
    tool_names = {tool["name"] for tool in manager.get_anthropic_tools()}
    assert "desktop-commander" in tool_names
    assert "file-manager" in tool_names
    assert "bash" not in tool_names
    assert "str_replace_editor" not in tool_names

    skills_root = Path(__file__).resolve().parents[1] / "skills"
    assert (skills_root / "desktop-commander" / "source" / "src" / "server.ts").exists()
    assert (skills_root / "file-manager" / "source" / "main.py").exists()
    assert (skills_root / "computer-use" / "source" / "src" / "server.ts").exists()

    async def run_health_check() -> None:
        health = await manager.health_check()
        assert health["overall_healthy"] is True
        assert health["skills"]["desktop-commander"]["healthy"] is True
        assert health["skills"]["file-manager"]["healthy"] is True

    asyncio.run(run_health_check())
