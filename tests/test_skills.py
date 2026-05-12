from __future__ import annotations

import asyncio
from pathlib import Path

from skills import SkillManager


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills"


def test_skills_are_loaded_from_src_skills_runtime() -> None:
    manager = SkillManager({
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_text_editor": True,
        "enable_bash": True,
        "enable_computer_use": True,
        "skills_dir": str(SKILLS_ROOT),
    })

    catalog_names = {item["name"] for item in manager.get_skill_catalog()}
    assert "desktop-commander" in catalog_names
    assert "file-manager" in catalog_names
    assert "computer-use" in catalog_names
    assert "desktop-commander" in manager.skills
    assert "file-manager" in manager.skills
    assert "computer-use" in manager.skills

    tool_names = {tool["name"] for tool in manager.get_anthropic_tools()}
    assert "bash" in tool_names
    assert "str_replace_editor" in tool_names
    assert "computer" in tool_names
    assert "desktop-commander" not in tool_names
    assert "file-manager" not in tool_names

    assert (SKILLS_ROOT / "desktop-commander" / "SKILL.md").exists()
    assert (SKILLS_ROOT / "file-manager" / "SKILL.md").exists()
    assert (SKILLS_ROOT / "computer-use" / "SKILL.md").exists()

    async def run_health_check() -> None:
        health = await manager.health_check()
        assert health["overall_healthy"] is True
        assert health["skills"]["desktop-commander"]["healthy"] is True
        assert health["skills"]["file-manager"]["healthy"] is True

    asyncio.run(run_health_check())
