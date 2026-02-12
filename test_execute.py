#!/usr/bin/env python3
"""测试Docker中的/execute端点"""
import asyncio
import httpx
import json

async def test_execute_endpoint():
    """测试execute端点"""
    
    # 测试数据
    test_cases = [
        {
            "name": "健康检查",
            "url": "http://127.0.0.1:8000/health",
            "method": "GET"
        },
        {
            "name": "技能列表",
            "url": "http://127.0.0.1:8000/skills",
            "method": "GET"
        },
        {
            "name": "执行bash命令",
            "url": "http://127.0.0.1:8000/execute",
            "method": "POST",
            "data": {
                "tool_name": "bash",
                "parameters": {
                    "command": "pwd"
                }
            }
        },
        {
            "name": "查看文件",
            "url": "http://127.0.0.1:8000/execute",
            "method": "POST",
            "data": {
                "tool_name": "str_replace_editor",
                "parameters": {
                    "command": "view",
                    "path": "pyproject.toml"
                }
            }
        }
    ]
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, case in enumerate(test_cases, 1):
            print(f"\n{i}. 测试 {case['name']}...")
            
            try:
                if case['method'] == 'GET':
                    response = await client.get(case['url'])
                else:
                    response = await client.post(
                        case['url'],
                        json=case['data'],
                        headers={"Content-Type": "application/json"}
                    )
                
                print(f"   状态码: {response.status_code}")
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        if case['name'] == "健康检查":
                            print(f"   结果: {result}")
                        elif case['name'] == "技能列表":
                            skills = result.get('skills', [])
                            print(f"   技能数量: {len(skills)}")
                            for skill in skills:
                                print(f"     - {skill.get('name')}: {skill.get('description', '')[:50]}...")
                        else:
                            print(f"   成功: {result.get('success')}")
                            if result.get('content'):
                                content = result['content'][:200]
                                print(f"   内容预览: {content}...")
                            if result.get('error'):
                                print(f"   错误: {result['error']}")
                    except json.JSONDecodeError:
                        print(f"   响应内容: {response.text[:200]}...")
                else:
                    print(f"   错误响应: {response.text}")
                    
            except Exception as e:
                print(f"   异常: {e}")
    
    print(f"\n{'='*50}")
    print("测试完成！")

if __name__ == "__main__":
    asyncio.run(test_execute_endpoint())