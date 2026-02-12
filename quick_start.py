#!/usr/bin/env python3
"""快速启动本地API服务"""

import uvicorn
from src.omni_agent.api import app

if __name__ == "__main__":
    print("启动 Omni Agent 本地服务...")
    print("前端访问: http://127.0.0.1:8002")
    print("API文档: http://127.0.0.1:8002/docs")
    print("代码修改将自动重载")
    print("=" * 50)
    
    uvicorn.run(
        "src.omni_agent.api:app",
        host="127.0.0.1",
        port=8002,
        reload=True,
        reload_dirs=["src", ".claude", "frontend"],
        reload_delay=0.1,
        log_level="info"
    )