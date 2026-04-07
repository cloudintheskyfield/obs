#!/usr/bin/env python3
"""快速API测试脚本"""
import asyncio
import httpx
import json

async def test_api():
    base_url = "http://127.0.0.1:8002"
    
    # 测试健康检查
    async with httpx.AsyncClient() as client:
        print("=== 测试健康检查 ===")
        response = await client.get(f"{base_url}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        print()
        
        print("=== 测试技能列表 ===")
        response = await client.get(f"{base_url}/skills")
        print(f"Status: {response.status_code}")
        skills = response.json()["skills"]
        print(f"发现 {len(skills)} 个技能:")
        for skill in skills:
            print(f"- {skill['name']}: {skill['description']}")
        print()
        
        print("=== 测试Bash技能 ===")
        data = {
            "tool_name": "bash",
            "parameters": {
                "command": "echo 'Hello from Omni Agent'"
            }
        }
        response = await client.post(
            f"{base_url}/execute",
            json=data,
            timeout=30.0
        )
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Success: {result.get('success')}")
        if result.get('success'):
            print(f"Output: {result.get('content')}")
        else:
            print(f"Error: {result.get('error')}")
        print()
        
        print("=== 测试文件技能 ===")
        data = {
            "tool_name": "str_replace_editor",
            "parameters": {
                "command": "view",
                "path": "test.txt"
            }
        }
        response = await client.post(
            f"{base_url}/execute",
            json=data,
            timeout=30.0
        )
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Success: {result.get('success')}")
        if result.get('success'):
            content = result.get('content', '')
            lines = content.split('\n')[:5]  # 前5行
            print(f"README.md前5行:")
            for line in lines:
                print(f"  {line}")
        else:
            print(f"Error: {result.get('error')}")
        print()

if __name__ == "__main__":
    asyncio.run(test_api())