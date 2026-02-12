#!/usr/bin/env python3
"""快速测试API"""
import uvicorn
from omni_agent.main import fastapi_app

if __name__ == "__main__":
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8003, log_level="info")