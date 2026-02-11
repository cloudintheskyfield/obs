"""
测试 SKILL.md 加载和集成
"""
import asyncio
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omni_agent.skills.skill_manager import SkillManager
from loguru import logger


async def test_skill_loader_integration():
    """测试 Skill Loader 与 Skills 的集成"""
    
    print("\n" + "="*80)
    print("Test SKILL.md Loading and Integration")
    print("="*80)
    
    config = {
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": True,
        "enable_text_editor": True,
        "enable_bash": True
    }
    
    skill_manager = SkillManager(config)
    
    print(f"\n[OK] Initialized {len(skill_manager.skills)} skills")
    
    print("\n" + "-"*80)
    print("1. Test SKILL.md Metadata Loading")
    print("-"*80)
    
    metadata = skill_manager.list_skill_metadata()
    print(f"Loaded {len(metadata)} SKILL.md files:")
    for name, meta in metadata.items():
        print(f"  - {name}:")
        print(f"    Name: {meta['name']}")
        print(f"    Description: {meta['description'][:60]}...")
    
    print("\n" + "-"*80)
    print("2. Test Skills linked to SKILL.md")
    print("-"*80)
    
    for skill_name, skill in skill_manager.skills.items():
        print(f"\nSkill: {skill_name}")
        print(f"  Python class: {skill.__class__.__name__}")
        
        if skill.skill_definition:
            print(f"  [LINKED] SKILL.md:")
            print(f"    - MD Name: {skill.skill_definition.name}")
            print(f"    - MD Description: {skill.skill_definition.description[:60]}...")
            print(f"    - Instructions length: {len(skill.skill_definition.instructions)} chars")
            print(f"    - Skill directory: {skill.skill_definition.skill_dir}")
        else:
            print(f"  [FALLBACK] Using code definition")
    
    print("\n" + "-"*80)
    print("3. Test Anthropic Tool Definition Generation")
    print("-"*80)
    
    tools = skill_manager.get_anthropic_tools()
    print(f"Generated {len(tools)} Anthropic tool definitions:\n")
    
    for tool in tools:
        print(f"Tool: {tool['name']}")
        print(f"  Description: {tool['description'][:80]}...")
        print(f"  Parameters: {len(tool['input_schema']['properties'])}")
        print(f"  Required: {tool['input_schema'].get('required', [])}")
        print()
    
    print("-"*80)
    print("4. Test Get Full Skill Info (Level 2)")
    print("-"*80)
    
    test_skill = "str_replace_editor"
    info = skill_manager.get_skill_info(test_skill)
    
    if info:
        print(f"\nSkill: {test_skill}")
        print(f"  Name: {info['name']}")
        print(f"  Enabled: {info['enabled']}")
        print(f"  Parameters: {len(info['parameters'])}")
        
        if 'instructions' in info:
            print(f"  [OK] Level 2 Instructions: {len(info['instructions'])} chars")
            print(f"    Preview: {info['instructions'][:150]}...")
        
        if 'skill_md' in info:
            print(f"  [OK] SKILL.md metadata available")
    
    print("\n" + "-"*80)
    print("5. Test Skill Execution")
    print("-"*80)
    
    result = await skill_manager.execute_skill(
        "str_replace_editor",
        command="view",
        path="test.txt"
    )
    
    print(f"\nExecuted: str_replace_editor view test.txt")
    print(f"  Success: {result.success}")
    if result.success:
        print(f"  Content preview: {result.content[:100] if result.content else 'None'}...")
    else:
        print(f"  Error: {result.error}")
    
    print("\n" + "="*80)
    print("[SUCCESS] All tests completed")
    print("="*80)
    
    await skill_manager.cleanup()


if __name__ == "__main__":
    asyncio.run(test_skill_loader_integration())
