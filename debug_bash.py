#!/usr/bin/env python3
"""Debug bash技能"""
import asyncio
import httpx
import json

async def debug_bash():
    base_url = "http://127.0.0.1:8002"
    
    commands_to_test = [
        "echo hello",
        "dir",
        "pwd",
        "echo 'test message'"
    ]
    
    async with httpx.AsyncClient() as client:
        for cmd in commands_to_test:
            print(f"\n=== 测试命令: {cmd} ===")
            
            data = {
                "tool_name": "bash",
                "parameters": {
                    "command": cmd
                }
            }
            
            try:
                response = await client.post(
                    f"{base_url}/execute",
                    json=data,
                    timeout=10.0
                )
                
                print(f"Status Code: {response.status_code}")
                result = response.json()
                print(f"Success: {result.get('success')}")
                print(f"Content: {result.get('content')}")
                print(f"Error: {result.get('error')}")
                if result.get('metadata'):
                    print(f"Metadata: {result.get('metadata')}")
                    
            except Exception as e:
                print(f"请求异常: {e}")

if __name__ == "__main__":
    asyncio.run(debug_bash())