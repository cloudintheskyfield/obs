#!/usr/bin/env python3
"""测试 Docker API 路由状态"""

import requests


def test_api():
    base_url = "http://localhost:8000"

    print("=== Docker API测试 ===")

    print("1. 健康检查...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"   状态: {response.status_code}")
        print(f"   响应: {response.json()}")
    except Exception as e:
        print(f"   错误: {e}")
        return False

    print("\n2. 获取技能列表...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=5)
        print(f"   状态: {response.status_code}")
        skills = response.json()
        print(f"   技能数量: {len(skills.get('skills', []))}")
    except Exception as e:
        print(f"   错误: {e}")
        return False

    print("\n3. 查看 OpenAPI 路由...")
    try:
        response = requests.get(f"{base_url}/openapi.json", timeout=10)
        print(f"   状态: {response.status_code}")
        paths = response.json().get("paths", {})
        print(f"   /chat/stream: {'/chat/stream' in paths}")
        print(f"   /execute: {'/execute' in paths}")
    except Exception as e:
        print(f"   错误: {e}")
        return False

    print("\n4. 探测已移除的 /execute...")
    try:
        response = requests.post(f"{base_url}/execute", json={}, timeout=10)
        print(f"   状态: {response.status_code}")
        print(f"   响应: {response.text[:200]}")
    except Exception as e:
        print(f"   错误: {e}")
        return False

    print("\n🎉 API 路由测试完成！")
    print(f"📚 Swagger文档: {base_url}/docs")
    return True


if __name__ == "__main__":
    test_api()
