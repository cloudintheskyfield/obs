#!/usr/bin/env python3
"""Simple test script for Omni Agent API"""

import requests


def test_api():
    base_url = "http://127.0.0.1:8000"

    print("=== Omni Agent API Test ===\n")

    print("1. Testing health...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"[OK] Health: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"[FAIL] Health test failed: {e}")
        return False

    print("\n2. Testing skills list...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=10)
        if response.status_code == 200:
            skills = response.json().get('skills', [])
            print(f"[OK] Found {len(skills)} skills")
        else:
            print(f"[FAIL] Skills list failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Skills test failed: {e}")

    print("\n3. Testing API docs...")
    try:
        response = requests.get(f"{base_url}/openapi.json", timeout=5)
        if response.status_code == 200:
            paths = response.json().get('paths', {})
            print(f"[OK] /chat/stream present: {'/chat/stream' in paths}")
            print(f"[OK] /execute present: {'/execute' in paths}")
        else:
            print(f"[FAIL] API docs failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] API docs test failed: {e}")

    print("\n4. Probing removed /execute endpoint...")
    try:
        response = requests.post(f"{base_url}/execute", json={}, timeout=15)
        print(f"[OK] /execute status: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] /execute probe failed: {e}")

    print("\n=== Test Complete ===")
    return True


if __name__ == "__main__":
    test_api()
