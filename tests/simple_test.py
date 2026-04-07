#!/usr/bin/env python3
"""Simple test script for Omni Agent API"""

import requests
import json
import time

def test_api():
    base_url = "http://127.0.0.1:8000"
    
    print("=== Omni Agent API Test ===\n")
    
    # Test health
    print("1. Testing health...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        print(f"[OK] Health: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"[FAIL] Health test failed: {e}")
        return False
    
    # Test skills list
    print("\n2. Testing skills list...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=10)
        if response.status_code == 200:
            skills = response.json().get('skills', [])
            print(f"[OK] Found {len(skills)} skills:")
            for skill in skills:
                print(f"   - {skill['name']}: {skill['description'][:50]}...")
        else:
            print(f"[FAIL] Skills list failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Skills test failed: {e}")
    
    # Test API docs
    print("\n3. Testing API docs...")
    try:
        response = requests.get(f"{base_url}/openapi.json", timeout=5)
        if response.status_code == 200:
            openapi = response.json()
            paths = openapi.get('paths', {})
            print(f"[OK] Available endpoints ({len(paths)}):")
            for path in paths.keys():
                print(f"   - {path}")
        else:
            print(f"[FAIL] API docs failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] API docs test failed: {e}")
    
    # Test command execution (if execute endpoint exists)
    print("\n4. Testing command execution...")
    try:
        test_payload = {
            "tool_name": "bash",
            "parameters": {"command": "echo 'Hello from API test!'"}
        }
        response = requests.post(
            f"{base_url}/execute", 
            json=test_payload, 
            timeout=15
        )
        if response.status_code == 200:
            result = response.json()
            print(f"[OK] Command executed: {result.get('success')}")
            if result.get('content'):
                print(f"   Output: {result['content'][:100]}...")
        else:
            print(f"[FAIL] Command failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[FAIL] Command test failed: {e}")
    
    print("\n=== Test Complete ===")
    return True

if __name__ == "__main__":
    test_api()