#!/usr/bin/env python3
"""完整系统路由测试脚本"""

import requests
import time


def test_complete_system():
    base_url = "http://127.0.0.1:8000"

    print("=== Omni Agent Complete System Test ===")
    print("=" * 50)

    print("\n[1] Testing system health...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print("[OK] System health: OK")
        else:
            print(f"[FAIL] Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] Cannot connect to system: {e}")
        return False

    print("\n[2] Testing skills loading...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=10)
        if response.status_code == 200:
            skills = response.json().get('skills', [])
            print(f"[OK] Successfully loaded {len(skills)} skills")
        else:
            print(f"[FAIL] Skills loading failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Skills loading exception: {e}")

    print("\n[3] Testing OpenAPI routes...")
    try:
        response = requests.get(f"{base_url}/openapi.json", timeout=15)
        if response.status_code == 200:
            paths = response.json().get("paths", {})
            print(f"[OK] /chat/stream present: {'/chat/stream' in paths}")
            print(f"[OK] /execute present: {'/execute' in paths}")
        else:
            print(f"[FAIL] OpenAPI failed: {response.text}")
    except Exception as e:
        print(f"[FAIL] OpenAPI test failed: {e}")

    print("\n[4] Testing frontend page...")
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            content = response.text
            if "<!DOCTYPE html>" in content:
                print("[OK] Frontend page loaded")
            else:
                print("[WARN] Frontend page content unexpected")
        else:
            print(f"[FAIL] Frontend page failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Frontend test failed: {e}")

    print("\n[5] Testing API docs...")
    try:
        response = requests.get(f"{base_url}/docs", timeout=5)
        if response.status_code == 200:
            print("[OK] API docs available")
        else:
            print(f"[FAIL] API docs unavailable: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] API docs test failed: {e}")

    print("\n[6] Performance test for removed endpoint probe...")
    try:
        start_time = time.time()
        response = requests.post(f"{base_url}/execute", json={}, timeout=15)
        end_time = time.time()
        response_time = (end_time - start_time) * 1000
        print(f"[OK] /execute status: {response.status_code}")
        print(f"[OK] Response time: {response_time:.1f}ms")
    except Exception as e:
        print(f"[FAIL] Legacy endpoint probe exception: {e}")

    print("\n" + "=" * 50)
    print("System test completed!")
    print("\nFrontend: http://127.0.0.1:8000")
    print("API Docs: http://127.0.0.1:8000/docs")
    return True


if __name__ == "__main__":
    test_complete_system()
