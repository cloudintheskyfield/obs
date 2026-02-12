#!/usr/bin/env python3
"""
Omni Agent API 接口交互示例

展示如何与Agent进行交互，包括各种命令格式和API调用方式
"""
import asyncio
import json
import httpx
from typing import Dict, Any, Optional
import base64
from pathlib import Path


class OmniAgentClient:
    """Omni Agent客户端，封装API交互"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip('/')
        
    async def check_health(self) -> Dict[str, Any]:
        """检查服务健康状态"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/health")
            return response.json()
    
    async def get_skills(self) -> Dict[str, Any]:
        """获取可用技能列表"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/skills")
            return response.json()
    
    async def execute_skill(self, skill_name: str, **parameters) -> Dict[str, Any]:
        """执行技能"""
        data = {
            "tool_name": skill_name,
            "parameters": parameters
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/execute",
                json=data,
                headers={"Content-Type": "application/json"}
            )
            return response.json()
    
    # =================
    # 便捷方法
    # =================
    
    async def take_screenshot(self) -> Dict[str, Any]:
        """截取屏幕截图"""
        return await self.execute_skill("computer", action="screenshot")
    
    async def click(self, x: int, y: int) -> Dict[str, Any]:
        """点击屏幕坐标"""
        return await self.execute_skill("computer", action="left_click", coordinate=[x, y])
    
    async def type_text(self, text: str) -> Dict[str, Any]:
        """输入文本"""
        return await self.execute_skill("computer", action="type", text=text)
    
    async def read_file(self, file_path: str) -> Dict[str, Any]:
        """读取文件内容"""
        return await self.execute_skill("str_replace_editor", command="view", path=file_path)
    
    async def create_file(self, file_path: str, content: str) -> Dict[str, Any]:
        """创建文件"""
        return await self.execute_skill("str_replace_editor", 
                                      command="create", 
                                      path=file_path, 
                                      file_text=content)
    
    async def replace_text(self, file_path: str, old_str: str, new_str: str) -> Dict[str, Any]:
        """替换文件中的文本"""
        return await self.execute_skill("str_replace_editor",
                                      command="str_replace",
                                      path=file_path,
                                      old_str=old_str,
                                      new_str=new_str)
    
    async def run_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """执行终端命令"""
        return await self.execute_skill("bash", command=command, timeout=timeout)


async def demo_basic_usage():
    """基础使用示例"""
    client = OmniAgentClient()
    
    print("=== 基础API调用示例 ===\n")
    
    # 1. 检查健康状态
    print("1. 检查服务状态...")
    health = await client.check_health()
    print(f"   状态: {health.get('status')}")
    print(f"   技能数量: {health.get('skills_count')}\n")
    
    # 2. 获取技能列表
    print("2. 获取可用技能...")
    skills = await client.get_skills()
    if 'skills' in skills:
        for skill in skills['skills']:
            print(f"   - {skill.get('name', 'Unknown')}: {skill.get('description', 'No description')}")
    print()
    
    # 3. 截图示例
    print("3. 截取屏幕截图...")
    result = await client.take_screenshot()
    if result.get('success'):
        print("   ✅ 截图成功")
        # 保存截图（如果需要）
        if 'content' in result and isinstance(result['content'], str):
            try:
                image_data = base64.b64decode(result['content'])
                with open("screenshot_demo.png", "wb") as f:
                    f.write(image_data)
                print("   📷 截图已保存为 screenshot_demo.png")
            except Exception as e:
                print(f"   ⚠️ 保存截图失败: {e}")
    else:
        print(f"   ❌ 截图失败: {result.get('error')}")
    print()


async def demo_file_operations():
    """文件操作示例"""
    client = OmniAgentClient()
    
    print("=== 文件操作示例 ===\n")
    
    # 1. 创建示例文件
    print("1. 创建示例文件...")
    content = """# 示例Python脚本
print("Hello from Omni Agent!")
print("当前时间:", __import__('datetime').datetime.now())

def greet(name):
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(greet("World"))
"""
    
    result = await client.create_file("demo_script.py", content)
    if result.get('success'):
        print("   ✅ 文件创建成功")
    else:
        print(f"   ❌ 文件创建失败: {result.get('error')}")
    print()
    
    # 2. 读取文件
    print("2. 读取文件内容...")
    result = await client.read_file("demo_script.py")
    if result.get('success'):
        print("   ✅ 文件读取成功")
        print("   📄 文件内容预览:")
        lines = result.get('content', '').split('\n')[:5]
        for line in lines:
            print(f"      {line}")
        if len(result.get('content', '').split('\n')) > 5:
            print("      ...")
    else:
        print(f"   ❌ 文件读取失败: {result.get('error')}")
    print()
    
    # 3. 修改文件
    print("3. 修改文件内容...")
    result = await client.replace_text(
        "demo_script.py",
        'print("Hello from Omni Agent!")',
        'print("Hello from Updated Omni Agent!")'
    )
    if result.get('success'):
        print("   ✅ 文件修改成功")
    else:
        print(f"   ❌ 文件修改失败: {result.get('error')}")
    print()


async def demo_terminal_operations():
    """终端操作示例"""
    client = OmniAgentClient()
    
    print("=== 终端操作示例 ===\n")
    
    # 1. 查看当前目录
    print("1. 查看当前目录...")
    result = await client.run_command("pwd")
    if result.get('success'):
        print(f"   📁 当前目录: {result.get('content', '').strip()}")
    else:
        print(f"   ❌ 命令执行失败: {result.get('error')}")
    print()
    
    # 2. 列出文件
    print("2. 列出当前目录文件...")
    result = await client.run_command("ls -la")
    if result.get('success'):
        print("   📋 文件列表:")
        lines = result.get('content', '').strip().split('\n')[:10]
        for line in lines:
            if line.strip():
                print(f"      {line}")
    else:
        print(f"   ❌ 命令执行失败: {result.get('error')}")
    print()
    
    # 3. 运行Python脚本（如果存在）
    print("3. 运行示例Python脚本...")
    result = await client.run_command("python demo_script.py")
    if result.get('success'):
        print("   ✅ 脚本执行成功")
        print("   📤 输出:")
        for line in result.get('content', '').strip().split('\n'):
            if line.strip():
                print(f"      {line}")
    else:
        print(f"   ❌ 脚本执行失败: {result.get('error')}")
    print()


async def demo_advanced_usage():
    """高级使用示例"""
    client = OmniAgentClient()
    
    print("=== 高级功能示例 ===\n")
    
    # 1. 模拟网页交互（需要有浏览器界面）
    print("1. 模拟鼠标点击...")
    result = await client.click(100, 100)
    if result.get('success'):
        print("   🖱️ 鼠标点击成功")
    else:
        print(f"   ❌ 点击失败: {result.get('error')}")
    print()
    
    # 2. 输入文本
    print("2. 模拟键盘输入...")
    result = await client.type_text("Hello from Omni Agent!")
    if result.get('success'):
        print("   ⌨️ 文本输入成功")
    else:
        print(f"   ❌ 输入失败: {result.get('error')}")
    print()
    
    # 3. 组合操作：创建并执行脚本
    print("3. 组合操作：创建并执行测试脚本...")
    
    # 创建测试脚本
    test_script = """#!/usr/bin/env python3
import sys
print("系统信息测试脚本")
print(f"Python版本: {sys.version}")
print(f"平台: {sys.platform}")

# 计算斐波那契数列
def fib(n):
    if n <= 1:
        return n
    return fib(n-1) + fib(n-2)

print("斐波那契数列前10项:")
for i in range(10):
    print(f"fib({i}) = {fib(i)}")
"""
    
    # 创建文件
    create_result = await client.create_file("test_script.py", test_script)
    if create_result.get('success'):
        print("   📝 测试脚本创建成功")
        
        # 执行脚本
        exec_result = await client.run_command("python test_script.py", timeout=10)
        if exec_result.get('success'):
            print("   🚀 脚本执行成功")
            print("   📋 执行结果:")
            for line in exec_result.get('content', '').strip().split('\n'):
                if line.strip():
                    print(f"      {line}")
        else:
            print(f"   ❌ 脚本执行失败: {exec_result.get('error')}")
    else:
        print(f"   ❌ 脚本创建失败: {create_result.get('error')}")
    print()


def print_usage_guide():
    """打印使用指南"""
    print("""
=== Omni Agent API 接口使用指南 ===

1. 基本连接
   - 默认地址: http://127.0.0.1:8000 (本地API)
   - Docker地址: http://127.0.0.1:8000 (Docker部署)
   - 健康检查: GET /health
   - 技能列表: GET /skills

2. 主要API端点
   
   POST /execute
   执行技能操作，请求格式:
   {
       "tool_name": "技能名称",
       "parameters": {
           "参数名": "参数值"
       }
   }

3. 三大核心技能

   A. Computer Use (computer)
   - 截图: {"action": "screenshot"}
   - 点击: {"action": "left_click", "coordinate": [x, y]}
   - 输入: {"action": "type", "text": "内容"}
   - 按键: {"action": "key", "text": "Return/Tab/Escape等"}

   B. File Operations (str_replace_editor)
   - 查看文件: {"command": "view", "path": "文件路径"}
   - 创建文件: {"command": "create", "path": "路径", "file_text": "内容"}
   - 替换文本: {"command": "str_replace", "path": "路径", "old_str": "旧文本", "new_str": "新文本"}
   - 插入文本: {"command": "insert", "path": "路径", "insert_line": 行号, "new_str": "内容"}
   - 撤销编辑: {"command": "undo_edit", "path": "文件路径"}

   C. Terminal (bash)
   - 执行命令: {"command": "bash命令", "timeout": 超时秒数}
   - 重启shell: {"command": "命令", "restart": true}

4. 前端界面
   - Web界面: 浏览器打开项目根目录下的 frontend/index.html
   - 支持多会话管理、实时聊天、历史记录
   - 快捷命令: file:、cmd:、screenshot等

5. 命令行客户端
   - python chat_interface.py
   - python test_system_simple.py
   - python api_interface.py

6. 响应格式
   成功: {"success": true, "content": "结果内容", "metadata": {...}}
   失败: {"success": false, "error": "错误信息"}

更多示例请查看本文件的demo函数。
""")


async def main():
    """主函数 - 运行所有示例"""
    print("🤖 Omni Agent API 接口演示")
    print("=" * 50)
    
    try:
        # 检查服务是否可用
        client = OmniAgentClient()
        health = await client.check_health()
        if health.get('status') != 'ok':
            print("❌ Agent服务不可用，请先启动服务")
            print("\n启动命令:")
            print("  本地模式: python test_local_api.py")
            print("  Docker模式: docker-compose up -d")
            return
        
        print(f"✅ 服务状态正常，发现 {health.get('skills_count', 0)} 个技能\n")
        
        # 运行示例
        await demo_basic_usage()
        await demo_file_operations()
        await demo_terminal_operations()
        await demo_advanced_usage()
        
        print("=" * 50)
        print("🎉 所有示例演示完成！")
        
    except Exception as e:
        print(f"❌ 演示过程中出现错误: {e}")
        print("\n请检查:")
        print("1. Agent服务是否正在运行")
        print("2. 网络连接是否正常")
        print("3. 端口是否被占用")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print_usage_guide()
        elif sys.argv[1] == "--demo":
            asyncio.run(main())
        else:
            print("用法:")
            print("  python api_interface.py --help    显示使用指南")
            print("  python api_interface.py --demo    运行API演示")
    else:
        print_usage_guide()
        print("\n运行演示: python api_interface.py --demo")