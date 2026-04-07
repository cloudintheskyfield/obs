"""测试Anthropic Skills实现"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omni_agent.skills.skill_manager import SkillManager
from omni_agent.skills.computer_use import ComputerUseSkill
from omni_agent.skills.text_editor import TextEditorSkill
from omni_agent.skills.bash import BashSkill


async def test_skill_tools():
    """测试Skills转换为Anthropic Tool格式"""
    print("=" * 60)
    print("测试Anthropic Skills实现")
    print("=" * 60)
    
    config = {
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": True,
        "enable_text_editor": True,
        "enable_bash": True
    }
    
    skill_manager = SkillManager(config)
    
    print(f"\n已初始化 {len(skill_manager.skills)} 个 Skills:")
    for name in skill_manager.skills.keys():
        print(f"  - {name}")
    
    tools = skill_manager.get_anthropic_tools()
    
    print(f"\n生成了 {len(tools)} 个 Anthropic Tool 定义:\n")
    
    for tool in tools:
        print(f"Tool: {tool['name']}")
        print(f"Description: {tool['description'][:100]}...")
        print(f"Parameters:")
        for param_name, param_def in tool['input_schema']['properties'].items():
            required = param_name in tool['input_schema'].get('required', [])
            print(f"  - {param_name} ({param_def['type']}){'*' if required else ''}: {param_def['description'][:80]}")
        print()
    
    print("\n" + "=" * 60)
    print("测试Computer Use Skill定义")
    print("=" * 60)
    
    computer_skill = skill_manager.get_skill("computer")
    if computer_skill:
        print(f"\nTool名称: {computer_skill.name}")
        print(f"描述: {computer_skill.description}")
        print(f"参数数量: {len(computer_skill.parameters)}")
        
        tool_def = computer_skill.to_anthropic_tool()
        print(f"\nAnthropic Tool定义:")
        print(f"  name: {tool_def['name']}")
        print(f"  required params: {tool_def['input_schema'].get('required', [])}")
        print("  (跳过浏览器初始化测试 - 需要安装Playwright browsers)")
    
    print("\n" + "=" * 60)
    print("测试Text Editor Skill")
    print("=" * 60)
    
    editor_skill = skill_manager.get_skill("str_replace_editor")
    if editor_skill:
        print(f"\nTool名称: {editor_skill.name}")
        print(f"描述: {editor_skill.description}")
        
        print("\n测试创建文件...")
        result = await editor_skill.execute(
            command="create",
            path="test_anthropic.txt",
            file_text="Hello from Anthropic Skills!\nThis is a test file."
        )
        print(f"结果: success={result.success}")
        print(f"内容: {result.content[:100] if result.content else 'None'}")
        
        print("\n测试查看文件...")
        result = await editor_skill.execute(
            command="view",
            path="test_anthropic.txt"
        )
        print(f"结果: success={result.success}")
        print(f"内容:\n{result.content[:200] if result.content else 'None'}")
    
    print("\n" + "=" * 60)
    print("测试Bash Skill")
    print("=" * 60)
    
    bash_skill = skill_manager.get_skill("bash")
    if bash_skill:
        print(f"\nTool名称: {bash_skill.name}")
        print(f"描述: {bash_skill.description}")
        
        print("\n测试执行命令...")
        result = await bash_skill.execute(
            command="echo 'Hello from Bash Skill!'",
            timeout=10
        )
        print(f"结果: success={result.success}")
        print(f"输出: {result.content[:100] if result.content else 'None'}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
    
    await skill_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(test_skill_tools())
