#!/usr/bin/env python3
"""
Omni Agent 交互接口
提供多种方式与Agent进行交互
"""
import requests
import json
import sys
from typing import Dict, Any, Optional
import time

class OmniAgentClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        
    def health_check(self) -> bool:
        """检查服务健康状态"""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_skills(self) -> Dict[str, Any]:
        """获取可用技能列表"""
        try:
            response = self.session.get(f"{self.base_url}/skills", timeout=10)
            return response.json() if response.status_code == 200 else {}
        except Exception as e:
            print(f"获取技能列表失败: {e}")
            return {}
    
    def execute_skill(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """执行技能"""
        payload = {
            "tool_name": tool_name,
            "parameters": parameters
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/execute", 
                json=payload, 
                timeout=30
            )
            return response.json()
        except Exception as e:
            return {
                "success": False,
                "error": f"请求失败: {str(e)}"
            }
    
    def chat_with_files(self, action: str, path: str, content: str = None) -> Dict[str, Any]:
        """文件操作快捷方法"""
        if action == "read":
            return self.execute_skill("str_replace_editor", {
                "command": "view", 
                "path": path
            })
        elif action == "create":
            return self.execute_skill("str_replace_editor", {
                "command": "create", 
                "path": path,
                "file_text": content or ""
            })
        elif action == "edit":
            return self.execute_skill("str_replace_editor", {
                "command": "str_replace", 
                "path": path,
                "old_str": content.split("|")[0] if content else "",
                "new_str": content.split("|")[1] if content and "|" in content else ""
            })
    
    def run_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """执行命令快捷方法"""
        return self.execute_skill("bash", {
            "command": command,
            "timeout": timeout
        })
    
    def take_screenshot(self) -> Dict[str, Any]:
        """截图快捷方法"""
        return self.execute_skill("computer", {
            "action": "screenshot"
        })
    
    def click(self, x: int, y: int) -> Dict[str, Any]:
        """点击快捷方法"""
        return self.execute_skill("computer", {
            "action": "left_click",
            "coordinate": [x, y]
        })
    
    def type_text(self, text: str) -> Dict[str, Any]:
        """输入文本快捷方法"""
        return self.execute_skill("computer", {
            "action": "type",
            "text": text
        })


def interactive_chat():
    """交互式聊天界面"""
    client = OmniAgentClient()
    
    print("=== Omni Agent 交互界面 ===")
    print("正在连接Agent...")
    
    if not client.health_check():
        print("❌ 无法连接到Agent服务，请确保服务正在运行:")
        print("   docker-compose up 或 python test_api.py")
        return
    
    print("✅ 连接成功!")
    
    # 显示可用技能
    skills_data = client.get_skills()
    skills = skills_data.get('skills', [])
    print(f"\n📋 可用技能 ({len(skills)} 个):")
    for skill in skills:
        print(f"   • {skill['name']}: {skill['description'][:60]}...")
    
    print("\n💡 使用示例:")
    print("   file:create hello.txt Hello World!")
    print("   cmd:echo Hello from Agent")
    print("   screenshot:")
    print("   click:100,200")
    print("   type:Hello World")
    print("   help - 显示帮助")
    print("   quit - 退出")
    
    while True:
        try:
            user_input = input("\n🤖 Agent> ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            
            if user_input.lower() == 'help':
                show_help()
                continue
            
            # 解析命令
            result = process_command(client, user_input)
            
            # 显示结果
            if result.get('success'):
                print(f"✅ 成功: {result.get('content', '完成')[:200]}...")
                if result.get('base64_image'):
                    print("📸 截图已生成 (base64数据)")
            else:
                print(f"❌ 失败: {result.get('error', '未知错误')}")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ 错误: {e}")
    
    print("\n👋 再见!")


def process_command(client: OmniAgentClient, command: str) -> Dict[str, Any]:
    """处理用户命令"""
    
    # 文件操作
    if command.startswith("file:"):
        parts = command[5:].split(" ", 2)
        if len(parts) >= 2:
            action, path = parts[0], parts[1]
            content = parts[2] if len(parts) > 2 else None
            return client.chat_with_files(action, path, content)
    
    # 命令执行
    elif command.startswith("cmd:"):
        cmd = command[4:].strip()
        return client.run_command(cmd)
    
    # 截图
    elif command.lower() == "screenshot":
        return client.take_screenshot()
    
    # 点击
    elif command.startswith("click:"):
        coords = command[6:].split(",")
        if len(coords) == 2:
            try:
                x, y = int(coords[0].strip()), int(coords[1].strip())
                return client.click(x, y)
            except ValueError:
                return {"success": False, "error": "坐标格式错误"}
    
    # 输入文本
    elif command.startswith("type:"):
        text = command[5:].strip()
        return client.type_text(text)
    
    # JSON格式命令
    elif command.startswith("{") and command.endswith("}"):
        try:
            data = json.loads(command)
            return client.execute_skill(data["tool_name"], data.get("parameters", {}))
        except json.JSONDecodeError:
            return {"success": False, "error": "JSON格式错误"}
    
    # 直接技能调用
    else:
        return {"success": False, "error": "命令格式不正确，输入 help 查看帮助"}


def show_help():
    """显示帮助信息"""
    print("""
📖 命令帮助:

文件操作:
  file:create <路径> <内容>  - 创建文件
  file:read <路径>          - 读取文件
  file:edit <路径> <旧文本>|<新文本> - 编辑文件

命令执行:
  cmd:<命令>               - 执行系统命令
  例: cmd:ls -la, cmd:python --version

计算机操作:
  screenshot               - 截取屏幕
  click:<x>,<y>           - 点击坐标
  type:<文本>             - 输入文本

高级用法:
  JSON格式: {"tool_name": "bash", "parameters": {"command": "echo hi"}}
  
其他:
  help                    - 显示此帮助
  quit/exit/q            - 退出程序
""")


def api_examples():
    """API使用示例"""
    print("=== Omni Agent API 使用示例 ===\n")
    
    examples = [
        {
            "name": "创建Python文件并执行",
            "steps": [
                ("创建文件", "file:create test.py print('Hello from Agent!')"),
                ("执行文件", "cmd:python test.py"),
                ("查看文件", "file:read test.py")
            ]
        },
        {
            "name": "系统信息收集",
            "steps": [
                ("系统信息", "cmd:uname -a"),
                ("磁盘使用", "cmd:df -h"),
                ("内存信息", "cmd:free -m")
            ]
        },
        {
            "name": "网页自动化",
            "steps": [
                ("截图", "screenshot"),
                ("点击位置", "click:640,360"),
                ("输入文本", "type:Hello World")
            ]
        }
    ]
    
    for example in examples:
        print(f"📋 {example['name']}:")
        for i, (desc, cmd) in enumerate(example['steps'], 1):
            print(f"   {i}. {desc}: {cmd}")
        print()


def test_all_skills():
    """测试所有技能"""
    client = OmniAgentClient()
    
    print("=== 完整技能测试 ===")
    
    if not client.health_check():
        print("❌ 服务未运行")
        return False
    
    tests = [
        ("文件创建", "str_replace_editor", {
            "command": "create", 
            "path": "test_all.txt", 
            "file_text": "Omni Agent 技能测试\n时间: " + time.strftime("%Y-%m-%d %H:%M:%S")
        }),
        ("文件读取", "str_replace_editor", {
            "command": "view", 
            "path": "test_all.txt"
        }),
        ("命令执行", "bash", {
            "command": "echo 'Skills测试成功' && date"
        }),
        ("屏幕截图", "computer", {
            "action": "screenshot"
        })
    ]
    
    for name, tool, params in tests:
        print(f"\n🧪 测试 {name}...")
        result = client.execute_skill(tool, params)
        
        if result.get('success'):
            print(f"   ✅ 成功")
            content = result.get('content', '')
            if content and len(content) > 100:
                print(f"   📄 输出: {content[:100]}...")
            elif content:
                print(f"   📄 输出: {content}")
        else:
            print(f"   ❌ 失败: {result.get('error')}")
    
    print(f"\n🎉 测试完成!")
    return True


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "examples":
            api_examples()
        elif command == "test":
            test_all_skills()
        elif command == "help":
            show_help()
        else:
            print("使用方法:")
            print("  python chat_interface.py         - 交互式聊天")
            print("  python chat_interface.py examples - 显示使用示例")
            print("  python chat_interface.py test     - 测试所有技能")
            print("  python chat_interface.py help     - 显示命令帮助")
    else:
        interactive_chat()