from __future__ import annotations

from skills import SkillLoader, SkillManager, SkillResult


def test_findskills_harness_skill_surface_resolves() -> None:
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
    metadata = manager.list_skill_metadata()
    assert "desktop-commander" in metadata
    assert "file-manager" in metadata
    assert "desktop-commander" in manager.skills
    assert "file-manager" in manager.skills
    assert "terminal" not in manager.list_skill_metadata()
    assert "file-operations" not in manager.list_skill_metadata()
