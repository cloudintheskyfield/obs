#!/usr/bin/env python3
"""Simple system test without unicode"""

import requests
import json
import time

def test_system():
    base_url = "http://127.0.0.1:8000"
    
    print("=== Omni Agent System Test ===")
    print("=" * 40)
    
    # Test 1: Health check
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
    
    # Test 2: Skills
    print("\n[2] Skills loading...")
    try:
        response = requests.get(f"{base_url}/skills", timeout=10)
        if response.status_code == 200:
            skills = response.json().get('skills', [])
            print(f"[OK] Loaded {len(skills)} skills:")
            for skill in skills:
                print(f"     - {skill['name']}")
        else:
            print(f"[FAIL] Skills failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Skills exception: {e}")
    
    # Test 3: Execute command
    print("\n[3] Command execution...")
    try:
        payload = {
            "tool_name": "bash",
            "parameters": {"command": "echo 'Test successful'"}
        }
        response = requests.post(f"{base_url}/execute", json=payload, timeout=15)
        if response.status_code == 200 and response.json().get('success'):
            result = response.json()
            print("[OK] Command executed")
            print(f"     Output: {result.get('content', '')[:50]}...")
        else:
            print(f"[FAIL] Command failed: {response.text}")
    except Exception as e:
        print(f"[FAIL] Command exception: {e}")
    
    # Test 4: Frontend
    print("\n[4] Frontend page...")
    try:
        response = requests.get(f"{base_url}/", timeout=5)
        if response.status_code == 200:
            content = response.text
            if "Omni Agent" in content and "<!DOCTYPE html>" in content:
                print("[OK] Frontend loaded successfully")
                print(f"     Page size: {len(content)} chars")
            else:
                print("[WARN] Frontend content may be incorrect")
        else:
            print(f"[FAIL] Frontend failed: {response.status_code}")
    except Exception as e:
        print(f"[FAIL] Frontend exception: {e}")
    
    # Test 5: Performance
    print("\n[5] Performance test...")
    try:
        start_time = time.time()
        payload = {"tool_name": "bash", "parameters": {"command": "echo 'perf'"}}
        response = requests.post(f"{base_url}/execute", json=payload, timeout=15)
        end_time = time.time()
        
        if response.status_code == 200 and response.json().get('success'):
            response_time = (end_time - start_time) * 1000
            print(f"[OK] Response time: {response_time:.1f}ms")
            if response_time < 1000:
                print("     Performance: Excellent")
            elif response_time < 3000:
                print("     Performance: Good")
            else:
                print("     Performance: Needs optimization")
        else:
            print("[FAIL] Performance test failed")
    except Exception as e:
        print(f"[FAIL] Performance exception: {e}")
    
    print("\n" + "=" * 40)
    print("Test completed!")
    print("\nUsage:")
    print("  Frontend: http://127.0.0.1:8000")
    print("  API Docs: http://127.0.0.1:8000/docs") 
    print("  CLI:      python chat_interface.py")
    print("\nSupported commands:")
    print("  file:create test.txt Hello")
    print("  cmd:ls -la")
    print("  screenshot")
    
    return True

if __name__ == "__main__":
    test_system()