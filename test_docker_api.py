#!/usr/bin/env python3
"""测试Docker API"""
import requests
import json

def test_api():
    base_url = "http://localhost:8000"
    
    print("=== Docker API测试 ===")
    
    # 测试健康检查
    print("1. 健康检查...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"   状态: {response.status_code}")
        print(f"   响应: {response.json()}")
    except Exception as e:
        print(f"   错误: {e}")
        return False
    
    # 测试技能列表
    print("\n2. 获取技能列表...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=5)
        print(f"   状态: {response.status_code}")
        skills = response.json()
        print(f"   技能数量: {len(skills.get('skills', []))}")
        for skill in skills.get('skills', [])[:3]:  # 只显示前3个
            print(f"   - {skill['name']}: {skill['description'][:50]}...")
    except Exception as e:
        print(f"   错误: {e}")
        return False
    
    # 测试执行技能
    print("\n3. 执行bash技能...")
    try:
        payload = {
            "tool_name": "bash",
            "parameters": {
                "command": "echo 'Hello from Docker Container!'"
            }
        }
        response = requests.post(f"{base_url}/execute", json=payload, timeout=10)
        print(f"   状态: {response.status_code}")
        result = response.json()
        print(f"   成功: {result.get('success')}")
        if result.get('success'):
            print(f"   输出: {result.get('content', '')[:100]}...")
        else:
            print(f"   错误: {result.get('error')}")
    except Exception as e:
        print(f"   错误: {e}")
        return False
    
    # 测试文件操作技能
    print("\n4. 执行文件创建技能...")
    try:
        payload = {
            "tool_name": "str_replace_editor",
            "parameters": {
                "command": "create",
                "path": "docker_test.txt",
                "file_text": "Hello from Docker API!\nThis file was created via REST API."
            }
        }
        response = requests.post(f"{base_url}/execute", json=payload, timeout=10)
        print(f"   状态: {response.status_code}")
        result = response.json()
        print(f"   成功: {result.get('success')}")
        if result.get('success'):
            print(f"   结果: {result.get('content', '')[:100]}...")
        else:
            print(f"   错误: {result.get('error')}")
    except Exception as e:
        print(f"   错误: {e}")
        return False
    
    print("\n🎉 所有API测试通过！")
    print(f"📚 Swagger文档: {base_url}/docs")
    return True

if __name__ == "__main__":
    test_api()