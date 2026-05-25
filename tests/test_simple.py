#!/usr/bin/env python3
"""Simple route inspection script"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from api import app

    print("API module imported successfully")

    routes = []
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            methods = getattr(route, 'methods', set())
            routes.append(f"{list(methods)} {route.path}")
        elif hasattr(route, 'path'):
            routes.append(f"[MOUNT] {route.path}")

    print(f"\nRegistered routes ({len(routes)}):")
    for route in routes:
        print(f"   {route}")

    chat_stream_found = any('/chat/stream' in route for route in routes)
    execute_found = any('/execute' in route for route in routes)

    print(f"\n/chat/stream registered: {chat_stream_found}")
    print(f"/execute registered: {execute_found}")

    print(f"\nApp title: {app.title}")
    print(f"App version: {app.version}")
    print(f"OpenAPI URL: {app.openapi_url}")
except ImportError as e:
    print(f"Import error: {e}")
except Exception as e:
    print(f"Other error: {e}")
    import traceback
    traceback.print_exc()
