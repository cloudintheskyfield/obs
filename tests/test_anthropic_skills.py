"""测试Anthropic Skills实现"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omni_agent.skills.skill_manager import SkillManager
def test_skill_tools():
    """测试Skills转换为Anthropic Tool格式"""
    async def _run():
        config = {
            "work_dir": "workspace",
            "screenshot_dir": "screenshots",
            "enable_computer_use": True,
            "enable_text_editor": True,
            "enable_bash": True
        }

        skill_manager = SkillManager(config)
        tools = skill_manager.get_anthropic_tools()
        assert tools

        computer_skill = skill_manager.get_skill("computer")
        if computer_skill:
            tool_def = computer_skill.to_anthropic_tool()
            assert tool_def["name"] == "computer"

        editor_skill = skill_manager.get_skill("str_replace_editor")
        if editor_skill:
            test_file = f"test_anthropic_{uuid.uuid4().hex[:8]}.txt"
            result = await editor_skill.execute(
                command="create",
                path=test_file,
                file_text="Hello from Anthropic Skills!\nThis is a test file."
            )
            assert result.success

            result = await editor_skill.execute(
                command="view",
                path=test_file
            )
            assert result.success

        bash_skill = skill_manager.get_skill("bash")
        if bash_skill:
            result = await bash_skill.execute(
                command="echo 'Hello from Bash Skill!'",
                timeout=10
            )
            assert result.success

        await skill_manager.cleanup()

    asyncio.run(_run())


if __name__ == "__main__":
    test_skill_tools()
