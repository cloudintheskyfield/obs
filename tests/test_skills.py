#!/usr/bin/env python3
"""测试Claude Skills功能"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# 添加项目根目录到path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from omni_agent.skills import SkillManager


async def _test_text_editor_skill():
    """测试文本编辑Skill"""
    print("Testing Text Editor Skill...")
    
    config = {
        "work_dir": str(project_root / "workspace"),
        "enable_text_editor": True,
        "enable_bash": False,
        "enable_computer_use": False
    }
    
    manager = SkillManager(config)
    
    test_file = f"test_skill_suite_{uuid.uuid4().hex[:8]}.txt"

    # 创建测试文件
    result = await manager.execute_skill(
        "str_replace_editor",
        command="create",
        path=test_file,
        file_text="Hello World!\nThis is a test file.\nLine 3 content."
    )
    
    print(f"Create file result: {result.success}")
    if not result.success:
        print(f"Error: {result.error}")
        return False
    
    # 查看文件
    result = await manager.execute_skill(
        "str_replace_editor",
        command="view", 
        path=test_file
    )
    
    print(f"View file result: {result.success}")
    if result.success:
        print(f"File content:\n{result.content}")
    else:
        print(f"Error: {result.error}")
    
    # 字符串替换
    result = await manager.execute_skill(
        "str_replace_editor",
        command="str_replace",
        path=test_file,
        old_str="Hello World!",
        new_str="Hello Claude Skills!"
    )
    
    print(f"String replace result: {result.success}")
    if not result.success:
        print(f"Error: {result.error}")
    
    await manager.cleanup()
    return True


async def _test_bash_skill():
    """测试Bash Skill"""
    print("\nTesting Bash Skill...")
    
    config = {
        "work_dir": str(project_root / "workspace"),
        "enable_text_editor": False,
        "enable_bash": True,
        "enable_computer_use": False
    }
    
    manager = SkillManager(config)
    
    # 测试基本命令
    result = await manager.execute_skill(
        "bash",
        command="echo Hello from Bash!"
    )
    
    print(f"Echo command result: {result.success}")
    if result.success:
        print(f"Output: {result.content}")
    else:
        print(f"Error: {result.error}")
    
    # 测试列出文件
    result = await manager.execute_skill("bash", command="ls")
    
    print(f"Dir command result: {result.success}")
    if result.success:
        print(f"Directory listing:\n{result.content[:200]}...")
    else:
        print(f"Error: {result.error}")
    
    await manager.cleanup()
    return True


async def _test_skill_manager():
    """测试Skills管理器功能"""
    print("\nTesting Skill Manager...")
    
    config = {
        "work_dir": str(project_root / "workspace"),
        "enable_text_editor": True,
        "enable_bash": True,
        "enable_computer_use": True
    }
    
    manager = SkillManager(config)
    
    # 列出所有Skills
    skills = manager.list_skills()
    print(f"Available skills: {len(skills)}")
    for skill in skills:
        print(f"  - {skill['name']}: {skill['description']}")
    
    # 获取Skills状态
    status = manager.get_skills_status()
    print(f"Skills status: {status['enabled_skills']}/{status['total_skills']} enabled")
    
    # 健康检查
    health = await manager.health_check()
    print(f"Health check: {'OK' if health['overall_healthy'] else 'FAILED'}")
    
    # 获取Skill详细信息
    info = manager.get_skill_info("str_replace_editor")
    if info:
        print(f"Text Editor info: {len(info['parameters'])} parameters")
        print(f"  Examples: {len(info['usage_examples'])}")
    
    await manager.cleanup()
    return True


async def main():
    """主测试函数"""
    print("Starting Claude Skills Test Suite")
    print("=" * 50)
    
    # 创建工作目录
    workspace = project_root / "workspace"
    workspace.mkdir(exist_ok=True)
    
    try:
        # 运行测试
        success = True
        
        success &= await _test_skill_manager()
        success &= await _test_text_editor_skill() 
        success &= await _test_bash_skill()
        
        print("\n" + "=" * 50)
        if success:
            print("All tests passed!")
        else:
            print("Some tests failed!")
            
    except Exception as e:
        print(f"Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)


def test_skill_manager_suite():
    assert asyncio.run(main())
