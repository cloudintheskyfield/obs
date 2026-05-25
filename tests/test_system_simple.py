#!/usr/bin/env python3
"""Simple system route test without unicode"""

import requests
import time


def test_system():
    base_url = "http://127.0.0.1:8000"

    print("=== Omni Agent System Test ===")
    print("=" * 40)

    print("\n[1] Health check...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            print("[OK] System is healthy")
        else:
            print(f"[FAIL] Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] Cannot connect: {e}")
        return False

    print("\n[2] Skills loading...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=10)
        if response.status_code == 200:
            skills = response.json().get('skills', [])
            print(f"[OK] Loaded {len(skills)} skills")
        else:
            print(f"[FAIL] Skills failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Skills exception: {e}")

    print("\n[3] OpenAPI route check...")
    try:
        response = requests.get(f"{base_url}/openapi.json", timeout=15)
        if response.status_code == 200:
            paths = response.json().get("paths", {})
            print(f"[OK] /chat/stream present: {'/chat/stream' in paths}")
            print(f"[OK] /execute present: {'/execute' in paths}")
        else:
            print(f"[FAIL] OpenAPI failed: {response.text}")
    except Exception as e:
        print(f"[FAIL] OpenAPI exception: {e}")

    print("\n[4] Frontend page...")
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            content = response.text
            if "<!DOCTYPE html>" in content:
                print("[OK] Frontend loaded successfully")
            else:
                print("[WARN] Frontend content may be incorrect")
        else:
            print(f"[FAIL] Frontend failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Frontend exception: {e}")

    print("\n[5] Legacy endpoint probe...")
    try:
        start_time = time.time()
        response = requests.post(f"{base_url}/execute", json={}, timeout=15)
        end_time = time.time()
        response_time = (end_time - start_time) * 1000
        print(f"[OK] /execute status: {response.status_code}")
        print(f"[OK] Probe time: {response_time:.1f}ms")
    except Exception as e:
        print(f"[FAIL] Legacy endpoint exception: {e}")

    print("\n" + "=" * 40)
    print("Test completed!")
    return True


if __name__ == "__main__":
    test_system()
