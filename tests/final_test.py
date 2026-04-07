#!/usr/bin/env python3
"""Final test to check execute endpoint"""

import asyncio
import httpx
import json

async def final_test():
    """Final comprehensive test"""
    
    print("=== Final Execute Endpoint Test ===\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        
        # Test 1: Health check
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
        
        # Test 2: Skills list
        try:
            response = await client.get("http://127.0.0.1:8000/skills")
            print(f"2. Skills list: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                skills = data.get('skills', [])
                print(f"   Found {len(skills)} skills:")
                for skill in skills:
                    print(f"     - {skill.get('name')}")
            print()
        except Exception as e:
            print(f"2. Skills list failed: {e}\n")
        
        # Test 3: Execute endpoint with proper data
        try:
            test_data = {
                "tool_name": "bash",
                "parameters": {
                    "command": "echo Hello World",
                    "timeout": 10
                }
            }
            
            response = await client.post(
                "http://127.0.0.1:8000/execute",
                json=test_data,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"3. Execute endpoint: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"   Success: {result.get('success')}")
                if result.get('content'):
                    print(f"   Output: {result['content'].strip()}")
                if result.get('error'):
                    print(f"   Error: {result['error']}")
                print("   SUCCESS: Execute endpoint working!")
                    
            elif response.status_code == 404:
                print("   ERROR: Execute endpoint not found (404)")
                print(f"   Response: {response.text}")
                
            elif response.status_code == 422:
                print("   ERROR: Validation error (422)")
                print(f"   Response: {response.text}")
                
            else:
                print(f"   ERROR: Unexpected status {response.status_code}")
                print(f"   Response: {response.text}")
            
        except Exception as e:
            print(f"3. Execute endpoint failed: {e}")
        
        print(f"\n{'='*50}")
        print("Test completed!")

if __name__ == "__main__":
    asyncio.run(final_test())