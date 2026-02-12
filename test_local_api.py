#!/usr/bin/env python3
"""Local API test to debug routing issue"""

import sys
import os
sys.path.append('src')

import uvicorn
from omni_agent.main import create_fastapi_app

if __name__ == "__main__":
    app = create_fastapi_app()
    
    print("=== Testing Local FastAPI App ===")
    print("Registered routes:")
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            print(f"  {list(route.methods)} {route.path}")
    
    print("\nStarting server on port 8001...")
    print("Test with: curl http://127.0.0.1:8001/execute -X POST -H 'Content-Type: application/json' -d '{\"tool_name\": \"bash\", \"parameters\": {\"command\": \"echo test\"}}'")
    
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")