#!/usr/bin/env python3
"""Test the API with proper requests"""

import requests
import json

def test_local_api():
    url = "http://127.0.0.1:8001/execute"
    payload = {
        "tool_name": "bash",
        "parameters": {
            "command": "echo 'Hello from local API'"
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        if response.status_code == 200:
            print("SUCCESS!")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    test_local_api()