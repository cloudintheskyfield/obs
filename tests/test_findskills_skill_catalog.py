from __future__ import annotations

from pathlib import Path

from skills import SkillManager


HARNESS_FIND_SKILLS = {
    "desktop-commander",
    "file-manager",
    "agent-skills",
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

MD_PERMISSION_ONLY_SKILLS = {
    "filesystem",
    "Skill Management = python runtime",
}


def test_skill_catalog_is_md_allowlisted_findskills_set() -> None:
    manager = SkillManager({
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": True,
        "enable_text_editor": True,
        "enable_bash": True,
    })

    assert set(manager.list_skill_metadata()) == HARNESS_FIND_SKILLS
    assert {item["name"] for item in manager.get_skill_catalog()} == HARNESS_FIND_SKILLS
    assert all("/source/" in item["location"] or item["location"].endswith("/source/README.md") for item in manager.get_skill_catalog())

    blocked_legacy_names = {"terminal", "file-operations", "web-search", "code-sandbox", "weather", "playwright"}
    assert blocked_legacy_names.isdisjoint(manager.list_skill_metadata())


def test_md_skills_are_backed_by_upstream_source_code() -> None:
    skills_root = Path(__file__).resolve().parents[1] / "skills"

    for skill_name in HARNESS_FIND_SKILLS:
        source_dir = skills_root / skill_name / "source"
        assert source_dir.exists(), skill_name
        assert any(path.is_file() for path in source_dir.rglob("*")), skill_name


def test_md_permission_only_skills_are_not_fabricated_without_source() -> None:
    skills_root = Path(__file__).resolve().parents[1] / "skills"
    for skill_name in {"filesystem", "skill-management-python-runtime"}:
        assert not (skills_root / skill_name / "source").exists()
        assert not (skills_root / skill_name / "SKILL.md").exists()


def test_no_generated_python_skill_adapters_are_left() -> None:
    skills_root = Path(__file__).resolve().parents[1] / "skills"
    generated_adapter_files = [
        skills_root / "base_skill.py",
        skills_root / "desktop-commander" / "bash.py",
        skills_root / "file-manager" / "text_editor.py",
        skills_root / "computer-use" / "computer_use.py",
        skills_root / "web-search-free" / "web_search.py",
    ]
    assert all(not path.exists() for path in generated_adapter_files)
