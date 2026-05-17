from __future__ import annotations

import asyncio
from pathlib import Path

from skills import SkillManager


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills"
EXPECTED_PUBLIC_TOOLS = {
    "desktop-commander",
    "file-manager",
    "filesystem",
    "computer-use",
    "web-e2e",
    "playwright-e2e",
    "web-testing-playwright-e2e",
    "e2e",
    "web-search-free",
    "search",
    "web-scraper-pro",
    "firecrawl-scraper",
    "skill-lookup",
}


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
    assert tool_names == EXPECTED_PUBLIC_TOOLS
    assert len(tool_names) == len(manager.get_skill_catalog())
    assert "bash" not in tool_names
    assert "str_replace_editor" not in tool_names
    assert "computer" not in tool_names

    assert (
        manager.resolve_skill_name_for_tool("desktop-commander.terminal")
        == "desktop-commander"
    )
    assert (
        manager.resolve_skill_name_for_tool("desktop-commander.file_read")
        == "filesystem"
    )
    assert (
        manager.resolve_skill_name_for_tool("desktop-commander.str_replace")
        == "file-manager"
    )
    assert (
        manager.resolve_skill_name_for_tool("Skill Management = python runtime")
        == "desktop-commander"
    )

    assert (SKILLS_ROOT / "desktop-commander" / "SKILL.md").exists()
    assert (SKILLS_ROOT / "file-manager" / "SKILL.md").exists()
    assert (SKILLS_ROOT / "computer-use" / "SKILL.md").exists()

    async def run_health_check() -> None:
        health = await manager.health_check()
        assert health["overall_healthy"] is True
        assert health["skills"]["desktop-commander"]["healthy"] is True
        assert health["skills"]["file-manager"]["healthy"] is True

        instruction_only = await manager.execute_skill(
            "playwright-e2e",
            query="smoke",
        )
        assert instruction_only.success is True
        assert instruction_only.metadata.get("mode") == "instruction_only"

    asyncio.run(run_health_check())
