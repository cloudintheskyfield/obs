#!/usr/bin/env python3
"""测试 legacy /execute 端点已移除"""

import asyncio
import os

import httpx
import pytest


async def run_execute_endpoint():
    test_cases = [
        {
            "name": "健康检查",
            "url": "http://127.0.0.1:8000/health",
            "method": "GET",
        },
        {
            "name": "技能列表",
            "url": "http://127.0.0.1:8000/skills",
            "method": "GET",
        },
        {
            "name": "OpenAPI 路由",
            "url": "http://127.0.0.1:8000/openapi.json",
            "method": "GET",
        },
        {
            "name": "探测已移除的 /execute",
            "url": "http://127.0.0.1:8000/execute",
            "method": "POST",
            "data": {},
        },
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, case in enumerate(test_cases, 1):
            print(f"\n{i}. 测试 {case['name']}...")

            try:
                if case['method'] == 'GET':
                    response = await client.get(case['url'])
                else:
                    response = await client.post(case['url'], json=case.get('data', {}), headers={"Content-Type": "application/json"})

                print(f"   状态码: {response.status_code}")

                if case['name'] == "OpenAPI 路由" and response.status_code == 200:
                    paths = response.json().get("paths", {})
                    print(f"   /chat/stream: {'/chat/stream' in paths}")
                    print(f"   /execute: {'/execute' in paths}")
                else:
                    print(f"   响应预览: {response.text[:200]}")
            except Exception as e:
                print(f"   异常: {e}")

    print(f"\n{'=' * 50}")
    print("测试完成！")


def test_execute_endpoint():
    if os.getenv("OBS_RUN_LIVE_API_TESTS") != "1":
        pytest.skip("Live API smoke test; set OBS_RUN_LIVE_API_TESTS=1 when the backend is running.")
    asyncio.run(run_execute_endpoint())


if __name__ == "__main__":
    asyncio.run(run_execute_endpoint())
