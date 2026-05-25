#!/usr/bin/env python3
"""快速 API 路由测试脚本"""

import asyncio
import os

import httpx
import pytest


async def run_api_smoke():
    base_url = "http://127.0.0.1:8002"

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
        print(f"发现 {len(skills)} 个技能")
        print()

        print("=== 测试 OpenAPI ===")
        response = await client.get(f"{base_url}/openapi.json")
        print(f"Status: {response.status_code}")
        paths = response.json().get("paths", {})
        print(f"/chat/stream: {'/chat/stream' in paths}")
        print(f"/execute: {'/execute' in paths}")
        print()

        print("=== 探测已移除的 /execute ===")
        response = await client.post(f"{base_url}/execute", json={}, timeout=30.0)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text[:200]}")
        print()


def test_api():
    if os.getenv("OBS_RUN_LIVE_API_TESTS") != "1":
        pytest.skip("Live API smoke test; set OBS_RUN_LIVE_API_TESTS=1 when the backend is running.")
    asyncio.run(run_api_smoke())


if __name__ == "__main__":
    asyncio.run(run_api_smoke())
