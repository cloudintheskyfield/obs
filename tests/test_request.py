#!/usr/bin/env python3
"""Test that the legacy execute endpoint is no longer exposed"""

import requests


def test_local_api():
    openapi_url = "http://127.0.0.1:8001/openapi.json"
    execute_url = "http://127.0.0.1:8001/execute"

    try:
        openapi_response = requests.get(openapi_url, timeout=10)
        print(f"OpenAPI status: {openapi_response.status_code}")
        if openapi_response.status_code == 200:
            paths = openapi_response.json().get("paths", {})
            print(f"Has /chat/stream: {'/chat/stream' in paths}")
            print(f"Has /execute: {'/execute' in paths}")

        execute_response = requests.post(execute_url, json={}, timeout=10)
        print(f"/execute status: {execute_response.status_code}")
        print(f"/execute response: {execute_response.text}")
        return execute_response.status_code == 404
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    test_local_api()
