#!/usr/bin/env python3
"""Final test to verify the legacy execute endpoint is removed"""

import asyncio

import httpx


async def final_test():
    print("=== Final Route Validation Test ===\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get("http://127.0.0.1:8000/health")
            print(f"1. Health check: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Status: {data.get('status')}")
                print(f"   Skills: {data.get('skills_count')}")
            print()
        except Exception as e:
            print(f"1. Health check failed: {e}\n")

        try:
            response = await client.get("http://127.0.0.1:8000/skills")
            print(f"2. Skills list: {response.status_code}")
            if response.status_code == 200:
                skills = response.json().get('skills', [])
                print(f"   Found {len(skills)} skills")
            print()
        except Exception as e:
            print(f"2. Skills list failed: {e}\n")

        try:
            response = await client.get("http://127.0.0.1:8000/openapi.json")
            print(f"3. OpenAPI schema: {response.status_code}")
            if response.status_code == 200:
                paths = response.json().get("paths", {})
                print(f"   /chat/stream present: {'/chat/stream' in paths}")
                print(f"   /execute present: {'/execute' in paths}")
            print()
        except Exception as e:
            print(f"3. OpenAPI schema failed: {e}\n")

        try:
            response = await client.post("http://127.0.0.1:8000/execute", json={})
            print(f"4. Legacy /execute probe: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
        except Exception as e:
            print(f"4. Legacy /execute probe failed: {e}")

        print(f"\n{'=' * 50}")
        print("Test completed!")


if __name__ == "__main__":
    asyncio.run(final_test())
