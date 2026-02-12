#!/usr/bin/env python3
"""Test API module import and route registration"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from omni_agent.api import app
    print("✅ API module imported successfully")
    
    routes = []
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            methods = getattr(route, 'methods', set())
            routes.append(f"{list(methods)} {route.path}")
        elif hasattr(route, 'path'):
            routes.append(f"[MOUNT] {route.path}")
    
    print(f"\n📝 Registered routes ({len(routes)}):")
    for route in routes:
        print(f"   {route}")
        
    # Check if /execute is in routes
    execute_found = any('/execute' in route for route in routes)
    if execute_found:
        print(f"\n✅ /execute endpoint is properly registered!")
    else:
        print(f"\n❌ /execute endpoint is MISSING!")
        
except ImportError as e:
    print(f"❌ Import error: {e}")
except Exception as e:
    print(f"❌ Other error: {e}")
    import traceback
    traceback.print_exc()