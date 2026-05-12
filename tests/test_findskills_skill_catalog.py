from __future__ import annotations

from pathlib import Path

from skills import SkillManager


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "src" / "skills"
HARNESS_RUNTIME_SKILLS = {
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
REMOVED_SKILL_DIRS = {
    "agent-builder",
    "code-review",
    "code-sandbox",
    "mcp-builder",
    "pdf",
    "skill-manager",
    "weather",
}


def test_skill_catalog_matches_active_src_skills_runtime() -> None:
    manager = SkillManager({
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": True,
        "enable_text_editor": True,
        "enable_bash": True,
        "skills_dir": str(SKILLS_ROOT),
    })

    assert set(manager.list_skill_metadata()) == HARNESS_RUNTIME_SKILLS
    assert {
        item["name"] for item in manager.get_skill_catalog()
    } == HARNESS_RUNTIME_SKILLS
    assert all(
        item["location"].startswith(str(SKILLS_ROOT))
        for item in manager.get_skill_catalog()
    )


def test_active_runtime_skills_exist_under_src_skills() -> None:
    for skill_name in HARNESS_RUNTIME_SKILLS:
        skill_dir = SKILLS_ROOT / skill_name
        assert skill_dir.exists(), skill_name
        assert (skill_dir / "SKILL.md").exists(), skill_name


def test_removed_legacy_skill_dirs_are_absent() -> None:
    assert not (Path(__file__).resolve().parents[1] / ".agents" / "skills").exists()
    for skill_name in REMOVED_SKILL_DIRS:
        assert not (SKILLS_ROOT / skill_name).exists(), skill_name
