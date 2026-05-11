#!/usr/bin/env python3
"""
测试 Creature 产物系统
"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.creature_manager import creature_manager


def test_create_creature():
    """测试创建产物"""
    print("=" * 60)
    print("测试 1: 创建产物目录")
    print("=" * 60)
    
    session_id = "test_session"
    creature_name = "test_game"
    
    # 创建产物目录
    creature_dir = creature_manager.create_creature_dir(session_id, creature_name)
    print(f"✅ 创建产物目录: {creature_dir}")
    
    # 创建测试文件
    (creature_dir / "index.html").write_text("""
<!DOCTYPE html>
<html>
<head>
    <title>Test Game</title>
</head>
<body>
    <h1>Hello, Creature!</h1>
</body>
</html>
    """)
    print(f"✅ 创建测试文件: index.html")
    
    # 生成启动脚本
    creature_manager.create_run_script(
        creature_dir=creature_dir,
        creature_type="html",
        port=8080,
        entry_file="index.html"
    )
    print(f"✅ 生成启动脚本: creature_run.sh")
    
    # 生成元数据
    creature_manager.create_creature_info(
        creature_dir=creature_dir,
        name=creature_name,
        creature_type="html",
        port=8080,
        entry_file="index.html",
        description="测试游戏",
        session_id=session_id,
        tags=["test", "game"]
    )
    print(f"✅ 生成元数据: creature_info.json")
    
    print()
    return session_id, creature_name


def test_list_creatures(session_id):
    """测试列出产物"""
    print("=" * 60)
    print("测试 2: 列出产物")
    print("=" * 60)
    
    creatures = creature_manager.list_creatures(session_id)
    print(f"✅ 找到 {len(creatures)} 个产物")
    
    for creature in creatures:
        print(f"\n产物信息:")
        print(f"  名称: {creature['name']}")
        print(f"  类型: {creature['type']}")
        print(f"  端口: {creature['port']}")
        print(f"  状态: {creature['status']}")
        print(f"  路径: {creature['path']}")
    
    print()
    return creatures


def test_detect_type():
    """测试类型检测"""
    print("=" * 60)
    print("测试 3: 检测产物类型")
    print("=" * 60)
    
    test_cases = [
        (["index.html", "style.css"], "html"),
        (["package.json", "src/App.jsx"], "react"),
        (["main.py", "requirements.txt"], "python"),
        (["package.json", "server.js"], "node"),
    ]
    
    for files, expected_type in test_cases:
        detected_type, entry, port = creature_manager.detect_creature_type(files)
        status = "✅" if detected_type == expected_type else "❌"
        print(f"{status} {files} -> {detected_type} (期望: {expected_type})")
    
    print()


def test_start_stop(session_id, creature_name):
    """测试启动和停止"""
    print("=" * 60)
    print("测试 4: 启动和停止产物")
    print("=" * 60)
    
    # 启动产物
    print(f"启动产物: {creature_name}")
    result = creature_manager.start_creature(session_id, creature_name)
    
    if result.get("success"):
        print(f"✅ 启动成功")
        print(f"  PID: {result.get('pid')}")
        print(f"  URL: {result.get('preview_url')}")
        
        # 等待一下
        import time
        print("等待 2 秒...")
        time.sleep(2)
        
        # 停止产物
        print(f"\n停止产物: {creature_name}")
        result = creature_manager.stop_creature(creature_name)
        
        if result.get("success"):
            print(f"✅ 停止成功")
        else:
            print(f"❌ 停止失败: {result.get('error')}")
    else:
        print(f"❌ 启动失败: {result.get('error')}")
    
    print()


def test_get_status(session_id, creature_name):
    """测试获取状态"""
    print("=" * 60)
    print("测试 5: 获取产物状态")
    print("=" * 60)
    
    result = creature_manager.get_creature_status(session_id, creature_name)
    
    if result.get("success"):
        print(f"✅ 获取状态成功")
        print(f"  名称: {result.get('name')}")
        print(f"  类型: {result.get('type')}")
        print(f"  状态: {result.get('status')}")
        print(f"  端口: {result.get('port')}")
    else:
        print(f"❌ 获取状态失败: {result.get('error')}")
    
    print()


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("🧪 Creature 产物系统测试")
    print("=" * 60)
    print()
    
    try:
        # 测试 1: 创建产物
        session_id, creature_name = test_create_creature()
        
        # 测试 2: 列出产物
        creatures = test_list_creatures(session_id)
        
        # 测试 3: 检测类型
        test_detect_type()
        
        # 测试 4: 启动和停止
        if creatures:
            test_start_stop(session_id, creature_name)
        
        # 测试 5: 获取状态
        if creatures:
            test_get_status(session_id, creature_name)
        
        print("=" * 60)
        print("🎉 所有测试完成！")
        print("=" * 60)
        print()
        print("📁 产物目录: creatures/")
        print("🌐 启动服务后访问: http://localhost:8000/api/creatures/session/test_session")
        print()
        
        return 0
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
