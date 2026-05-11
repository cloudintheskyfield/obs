"""
Creature 产物管理器
管理 Agent 创建的产物（游戏、网页、应用等）
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote


class CreatureManager:
    """管理 Agent 创建的产物"""
    
    def __init__(self, base_dir: str = "creatures"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        self.processes: Dict[str, subprocess.Popen] = {}
    
    def create_creature_dir(self, session_id: str, creature_name: str) -> Path:
        """
        创建产物目录
        
        Args:
            session_id: Session ID
            creature_name: 产物名称
            
        Returns:
            产物目录路径
        """
        timestamp = int(time.time())
        # 清理产物名称，移除特殊字符
        safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in creature_name)
        creature_dir = self.base_dir / f"session_{session_id}" / f"creature_{timestamp}_{safe_name}"
        creature_dir.mkdir(parents=True, exist_ok=True)
        return creature_dir
    
    def create_run_script(
        self,
        creature_dir: Path,
        creature_type: str = "html",
        port: int = 8080,
        entry_file: str = "index.html"
    ):
        """
        创建启动脚本
        
        Args:
            creature_dir: 产物目录
            creature_type: 产物类型 (html, react, python, node)
            port: 端口号
            entry_file: 入口文件
        """
        script_path = creature_dir / "creature_run.sh"
        
        script_content = f"""#!/bin/bash
# Creature 启动脚本
# 自动生成 - 请勿手动编辑

CREATURE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
CREATURE_NAME="$(basename "$CREATURE_DIR")"

echo "=================================="
echo "🚀 启动 Creature: $CREATURE_NAME"
echo "=================================="
echo ""

# 读取产物信息
if [ -f "$CREATURE_DIR/creature_info.json" ]; then
    TYPE=$(cat "$CREATURE_DIR/creature_info.json" | grep '"type"' | cut -d'"' -f4)
    PORT=$(cat "$CREATURE_DIR/creature_info.json" | grep '"port"' | cut -d':' -f2 | tr -d ' ,')
else
    TYPE="{creature_type}"
    PORT={port}
fi

case "$TYPE" in
    "html")
        echo "📄 类型: 静态 HTML"
        echo "🌐 访问: http://localhost:$PORT"
        echo ""
        cd "$CREATURE_DIR"
        python3 -m http.server $PORT
        ;;
    "react")
        echo "⚛️  类型: React 应用"
        echo "🌐 访问: http://localhost:$PORT"
        echo ""
        cd "$CREATURE_DIR"
        if [ ! -d "node_modules" ]; then
            echo "📦 安装依赖..."
            npm install
        fi
        npm start
        ;;
    "python")
        echo "🐍 类型: Python 应用"
        echo "🌐 访问: http://localhost:$PORT"
        echo ""
        cd "$CREATURE_DIR"
        if [ -f "requirements.txt" ]; then
            echo "📦 安装依赖..."
            pip install -r requirements.txt
        fi
        python3 {entry_file}
        ;;
    "node")
        echo "📗 类型: Node.js 应用"
        echo "🌐 访问: http://localhost:$PORT"
        echo ""
        cd "$CREATURE_DIR"
        if [ ! -d "node_modules" ]; then
            echo "📦 安装依赖..."
            npm install
        fi
        node {entry_file}
        ;;
    *)
        echo "❌ 未知产物类型: $TYPE"
        exit 1
        ;;
esac
"""
        
        script_path.write_text(script_content)
        script_path.chmod(0o755)
    
    def create_creature_info(
        self,
        creature_dir: Path,
        name: str,
        creature_type: str,
        port: int,
        entry_file: str,
        description: str = "",
        session_id: str = "",
        tags: List[str] = None
    ):
        """
        创建产物元数据
        
        Args:
            creature_dir: 产物目录
            name: 产物名称
            creature_type: 产物类型
            port: 端口号
            entry_file: 入口文件
            description: 描述
            session_id: Session ID
            tags: 标签列表
        """
        info = {
            "name": name,
            "type": creature_type,
            "port": port,
            "entry": entry_file,
            "description": description,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id,
            "preview_url": f"http://localhost:{port}",
            "tags": tags or [],
            "status": "ready"
        }
        
        info_path = creature_dir / "creature_info.json"
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
    
    def list_creatures(self, session_id: str) -> List[dict]:
        """
        列出 session 的所有产物
        
        Args:
            session_id: Session ID
            
        Returns:
            产物列表
        """
        session_dir = self.base_dir / f"session_{session_id}"
        if not session_dir.exists():
            return []
        
        creatures = []
        for creature_dir in sorted(session_dir.iterdir(), key=lambda p: p.name):
            if creature_dir.is_dir() and creature_dir.name.startswith("creature_"):
                info_path = creature_dir / "creature_info.json"
                if info_path.exists():
                    try:
                        with open(info_path, encoding="utf-8") as f:
                            info = json.load(f)
                            info["path"] = str(creature_dir.relative_to(self.base_dir))
                            info["absolute_path"] = str(creature_dir.absolute())
                            # 检查运行状态
                            creature_name = info.get("name", "")
                            if creature_name in self.processes:
                                process = self.processes[creature_name]
                                if process.poll() is None:
                                    info["status"] = "running"
                                else:
                                    info["status"] = "stopped"
                                    del self.processes[creature_name]
                            else:
                                info["status"] = "ready"
                            creatures.append(info)
                    except Exception as e:
                        print(f"Error reading creature info: {e}")
        
        return creatures
    
    def find_creature_dir(self, session_id: str, creature_name: str) -> Optional[Path]:
        """
        查找产物目录
        
        Args:
            session_id: Session ID
            creature_name: 产物名称
            
        Returns:
            产物目录路径，如果不存在返回 None
        """
        creatures = self.list_creatures(session_id)
        for creature in creatures:
            if creature.get("name") == creature_name:
                return Path(creature["absolute_path"])
        return None
    
    def start_creature(self, session_id: str, creature_name: str) -> dict:
        """
        启动产物
        
        Args:
            session_id: Session ID
            creature_name: 产物名称
            
        Returns:
            启动结果
        """
        creature_dir = self.find_creature_dir(session_id, creature_name)
        if not creature_dir:
            return {"success": False, "error": "Creature not found"}
        
        script_path = creature_dir / "creature_run.sh"
        if not script_path.exists():
            return {"success": False, "error": "Run script not found"}
        
        # 如果已经在运行，先停止
        if creature_name in self.processes:
            self.stop_creature(creature_name)
        
        # 启动进程
        try:
            process = subprocess.Popen(
                [str(script_path)],
                cwd=creature_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.processes[creature_name] = process
            
            # 读取产物信息获取 URL
            info_path = creature_dir / "creature_info.json"
            with open(info_path, encoding="utf-8") as f:
                info = json.load(f)
            
            return {
                "success": True,
                "status": "started",
                "pid": process.pid,
                "preview_url": info.get("preview_url", ""),
                "port": info.get("port", 8080)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def stop_creature(self, creature_name: str) -> dict:
        """
        停止产物
        
        Args:
            creature_name: 产物名称
            
        Returns:
            停止结果
        """
        if creature_name not in self.processes:
            return {"success": False, "error": "Creature not running"}
        
        try:
            process = self.processes[creature_name]
            process.terminate()
            
            # 等待进程结束
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            
            del self.processes[creature_name]
            
            return {"success": True, "status": "stopped"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_creature_status(self, session_id: str, creature_name: str) -> dict:
        """
        获取产物状态
        
        Args:
            session_id: Session ID
            creature_name: 产物名称
            
        Returns:
            产物状态
        """
        creature_dir = self.find_creature_dir(session_id, creature_name)
        if not creature_dir:
            return {"success": False, "error": "Creature not found"}
        
        info_path = creature_dir / "creature_info.json"
        if not info_path.exists():
            return {"success": False, "error": "Creature info not found"}
        
        with open(info_path, encoding="utf-8") as f:
            info = json.load(f)
        
        # 检查运行状态
        if creature_name in self.processes:
            process = self.processes[creature_name]
            if process.poll() is None:
                info["status"] = "running"
                info["pid"] = process.pid
            else:
                info["status"] = "stopped"
                del self.processes[creature_name]
        else:
            info["status"] = "ready"
        
        return {"success": True, **info}
    
    def detect_creature_type(self, files: List[str]) -> tuple[str, str, int]:
        """
        检测产物类型
        
        Args:
            files: 文件列表
            
        Returns:
            (类型, 入口文件, 端口)
        """
        file_set = set(f.lower() for f in files)
        
        # React 应用
        if "package.json" in file_set and any("react" in f for f in files):
            return ("react", "src/index.js", 3000)
        
        # Node.js 应用
        if "package.json" in file_set and any("server" in f or "app" in f for f in files):
            return ("node", "server.js", 3000)
        
        # Python 应用
        if any(f.endswith(".py") for f in files):
            # 查找 main.py 或 app.py
            for f in files:
                if f.lower() in ["main.py", "app.py", "server.py"]:
                    return ("python", f, 8000)
            # 默认使用第一个 .py 文件
            for f in files:
                if f.endswith(".py"):
                    return ("python", f, 8000)
        
        # HTML 应用（默认）
        entry = "index.html"
        for f in files:
            if f.lower() == "index.html":
                entry = f
                break
        
        return ("html", entry, 8080)


# 全局实例
creature_manager = CreatureManager()
