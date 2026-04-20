"""
测试 SKILL.md 加载和集成
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omni_agent.skills.skill_manager import SkillManager
def test_skill_loader_integration():
    """测试 Skill Loader 与 Skills 的集成"""
    async def _run():
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

        tools = skill_manager.get_anthropic_tools()
        assert tools

        info = skill_manager.get_skill_info("str_replace_editor")
        assert info is not None
        assert info["name"] == "str_replace_editor"

        test_file = f"test_loader_{uuid.uuid4().hex[:8]}.txt"
        result = await skill_manager.execute_skill(
            "str_replace_editor",
            command="create",
            path=test_file,
            file_text="loader integration"
        )
        assert result.success

        await skill_manager.cleanup()

    asyncio.run(_run())


if __name__ == "__main__":
    test_skill_loader_integration()
