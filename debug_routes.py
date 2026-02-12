#!/usr/bin/env python3
"""Debug script to check which routes are registered in the FastAPI app"""
import asyncio
import httpx
import json

async def debug_routes():
    """Debug the registered routes"""
    
    print("Checking FastAPI routes registration...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Get OpenAPI schema
        try:
            response = await client.get("http://127.0.0.1:8000/openapi.json")
            if response.status_code == 200:
                schema = response.json()
                
                print("\n=== Registered Paths ===")
                paths = schema.get("paths", {})
                for path, methods in paths.items():
                    print(f"  {path}")
                    for method, details in methods.items():
                        print(f"    {method.upper()}: {details.get('summary', 'No summary')}")
                
                # Check if /execute is in paths
                if "/execute" in paths:
                    print(f"\n✅ /execute endpoint is registered!")
                    print(f"   Methods: {list(paths['/execute'].keys())}")
                else:
                    print(f"\n❌ /execute endpoint is NOT registered!")
                    
            else:
                print(f"Failed to get OpenAPI schema: {response.status_code}")
                
        except Exception as e:
            print(f"Error getting OpenAPI schema: {e}")
        
        # Test direct requests
        print(f"\n=== Direct Endpoint Tests ===")
        
        test_urls = [
            ("GET", "/"),
            ("GET", "/health"), 
            ("GET", "/skills"),
            ("POST", "/execute"),
            ("GET", "/docs"),
        ]
        
        for method, path in test_urls:
            try:
                if method == "GET":
                    response = await client.get(f"http://127.0.0.1:8000{path}")
                else:
                    response = await client.post(
                        f"http://127.0.0.1:8000{path}",
                        json={"tool_name": "bash", "parameters": {"command": "echo test"}}
                    )
                    
                print(f"  {method} {path}: {response.status_code}")
                if response.status_code == 404:
                    print(f"    Error: {response.text}")
                elif response.status_code == 422:
                    print(f"    Validation Error (expected for POST without data)")
                    
            except Exception as e:
                print(f"  {method} {path}: Error - {e}")

if __name__ == "__main__":
    asyncio.run(debug_routes())