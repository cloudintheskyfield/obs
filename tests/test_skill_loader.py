"""
测试 SKILL.md 加载和集成
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from skills.skill_manager import SkillManager
def test_skill_loader_integration():
    """测试 Skill Loader 与 Skills 的集成"""
    config = {
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": True,
        "enable_text_editor": True,
        "enable_bash": True
    }

    skill_manager = SkillManager(config)
    metadata = skill_manager.list_skill_metadata()
    assert metadata

    info = skill_manager.get_skill_instructions("file-manager")
    assert info is not None
    assert "mcp" in info.lower() or "file" in info.lower()


if __name__ == "__main__":
    test_skill_loader_integration()
