#!/usr/bin/env python3
"""Local API test to debug routing issue"""

import os
import sys

sys.path.append('src')

import uvicorn
from main import create_fastapi_app

if __name__ == "__main__":
    app = create_fastapi_app()

    print("=== Testing Local FastAPI App ===")
    print("Registered routes:")
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            print(f"  {list(route.methods)} {route.path}")

    print("\nStarting server on port 8001...")
    print("Test with: curl http://127.0.0.1:8001/openapi.json")
    print("Expect /chat/stream to exist and /execute to be absent.")

    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
