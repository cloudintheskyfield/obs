from __future__ import annotations

from omni_agent.skills import SkillLoader, SkillManager, SkillResult


def test_legacy_skill_import_surface_still_resolves() -> None:
    loader = SkillLoader()
    skills = loader.load_all_skills()
    assert skills
    assert isinstance(SkillResult(success=True), SkillResult)

    manager = SkillManager({
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": False,
        "enable_text_editor": True,
        "enable_bash": True,
    })
    assert "bash" in manager.skills
    assert "str_replace_editor" in manager.skills
