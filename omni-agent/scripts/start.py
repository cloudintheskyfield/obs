#!/usr/bin/env python3
"""Omni Agent 启动脚本"""
import os
import sys
import subprocess
from pathlib import Path

def check_requirements():
    """检查运行环境"""
    # 检查Python版本
    if sys.version_info < (3, 11):
        print("❌ 需要 Python 3.11 或更高版本")
        sys.exit(1)
    
    # 检查uv
    try:
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ 需要安装 uv 包管理器")
        print("安装命令: curl -LsSf https://astral.sh/uv/install.sh | sh")
        sys.exit(1)
    
    print("✅ 环境检查通过")


def setup_environment():
    """设置环境"""
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # 创建必要的目录
    dirs = ["workspace", "logs", "screenshots", "config"]
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        print(f"✅ 目录已创建: {dir_name}")
    
    # 检查环境变量文件
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if not env_file.exists() and env_example.exists():
        print("⚠️  未发现 .env 文件，复制示例文件...")
        env_file.write_text(env_example.read_text())
        print("✅ 已创建 .env 文件，请根据需要修改配置")


def install_dependencies():
    """安装依赖"""
    print("📦 安装Python依赖...")
    try:
        subprocess.run(["uv", "sync"], check=True)
        print("✅ Python依赖安装完成")
    except subprocess.CalledProcessError:
        print("❌ 依赖安装失败")
        sys.exit(1)
    
    # 安装Playwright浏览器
    print("🌐 安装Playwright浏览器...")
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
        print("✅ Playwright浏览器安装完成")
    except subprocess.CalledProcessError:
        print("⚠️  Playwright浏览器安装失败，网页功能可能无法使用")


def main():
    """主函数"""
    print("🚀 Omni Agent 启动脚本")
    print("=" * 50)
    
    # 环境检查
    check_requirements()
    
    # 环境设置
    setup_environment()
    
    # 安装依赖
    install_dependencies()
    
    print("\n" + "=" * 50)
    print("✅ 初始化完成！")
    print("\n启动命令:")
    print("  uv run omni-agent start              # 启动交互式会话")
    print("  uv run omni-agent start --live-logs  # 启动并显示实时日志")
    print("  uv run omni-agent test               # 测试VLLM连接")
    print("  uv run omni-agent --help             # 查看帮助")
    
    # 询问是否立即启动
    try:
        choice = input("\n是否立即启动Omni Agent？[y/N]: ").strip().lower()
        if choice in ['y', 'yes']:
            print("\n🎯 启动 Omni Agent...")
            subprocess.run(["uv", "run", "omni-agent", "start"])
    except KeyboardInterrupt:
        print("\n👋 再见！")


if __name__ == "__main__":
    main()