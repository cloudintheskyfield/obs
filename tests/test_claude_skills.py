#!/usr/bin/env python3
"""
测试Claude Skills三级结构系统
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from skills.skill_loader import SkillLoader
from skills.skill_manager import SkillManager


def test_skill_loader():
    """测试SkillLoader"""
    print("=== 测试SkillLoader ===")
    
    loader = SkillLoader()
    print(f"Skills目录: {loader.skills_root}")
    
    # 加载所有skills
    skills = loader.load_all_skills()
    print(f"加载了 {len(skills)} 个skills:")
    
    for name, skill_def in skills.items():
        print(f"  - {name}: {skill_def.description}")
        print(f"    目录: {skill_def.skill_dir}")
        print(f"    有Python实现: {skill_def.skill_class is not None}")
        if skill_def.skill_class:
            print(f"    实现类: {skill_def.skill_class.__name__}")
        print()
    
    # 测试Level 1 metadata
    print("Level 1 Metadata:")
    metadata = loader.get_all_skill_metadata()
    for name, meta in metadata.items():
        print(f"  {name}: {meta['description']}")
    
    # 测试Level 2 instructions
    print("\nLevel 2 Instructions (前100字符):")
    for name in skills.keys():
        instructions = loader.get_skill_instructions(name)
        if instructions:
            preview = instructions[:100].replace('\n', ' ')
            print(f"  {name}: {preview}...")
    
    assert len(skills) > 0


def test_skill_manager():
    """测试SkillManager"""
    print("\n=== 测试SkillManager ===")
    
    config = {
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": True,
        "enable_text_editor": True,
        "enable_bash": True
    }
    
    manager = SkillManager(config)
    
    metadata = manager.list_skill_metadata()
    print(f"加载了 {len(metadata)} 个上游 source-backed skills:")
    for name, meta in metadata.items():
        print(f"  - {name}: {meta['description']}")
    
    # Source-backed skills expose instruction-only tools, not legacy local fake adapters.
    print("Anthropic工具定义:")
    tools = manager.get_anthropic_tools()
    for tool in tools:
        print(f"  - {tool['name']}: {tool['description'][:50]}...")
    
    # 测试健康检查
    print("\n健康检查:")
    import asyncio
    
    async def run_health_check():
        health = await manager.health_check()
        print(f"总体健康: {health['overall_healthy']}")
        for name, status in health['skills'].items():
            print(f"  {name}: {'健康' if status['healthy'] else '不健康'}")
            if status['error']:
                print(f"    错误: {status['error']}")
    
    asyncio.run(run_health_check())
    
    assert len(metadata) > 0
    assert "desktop-commander" in manager.skills
    assert all(getattr(skill, "_instructions", "") for skill in manager.skills.values())


def test_skill_execution():
    """测试技能执行"""
    print("\n=== 测试技能执行 ===")
    
    config = {
        "work_dir": "workspace",
        "screenshot_dir": "screenshots",
        "enable_computer_use": False,  # 禁用需要浏览器的
        "enable_text_editor": True,
        "enable_bash": True
    }
    
    manager = SkillManager(config)
    
    async def run_tests():
        result = await manager.execute_skill("bash", command="echo should-not-run")
        assert result.success
        assert result.metadata["mode"] == "instruction_only"
    
    import asyncio
    asyncio.run(run_tests())
    
    assert True


def main():
    """主测试函数"""
    print("Claude Skills 三级结构测试")
    print("=" * 50)
    
    try:
        # 测试SkillLoader
        loader_ok = test_skill_loader()
        
        # 测试SkillManager
        manager_ok = test_skill_manager()
        
        # 测试技能执行
        execution_ok = test_skill_execution()
        
        print("\n" + "=" * 50)
        print("测试结果:")
        print(f"SkillLoader: {'OK' if loader_ok else 'FAIL'}")
        print(f"SkillManager: {'OK' if manager_ok else 'FAIL'}")
        print(f"技能执行: {'OK' if execution_ok else 'FAIL'}")
        
        if all([loader_ok, manager_ok, execution_ok]):
            print("\n[SUCCESS] 所有测试通过！Claude Skills三级结构系统工作正常。")
            return 0
        else:
            print("\n[FAIL] 部分测试失败。")
            return 1
            
    except Exception as e:
        print(f"\n[ERROR] 测试过程中出现异常: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
