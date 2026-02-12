#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Omni Agent 聊天演示脚本
"""
import asyncio
import json
import httpx
from typing import Dict, Any
import sys
import os

# 设置Windows环境编码
if os.name == 'nt':  # Windows
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

class OmniAgentChat:
    def __init__(self, base_url: str = "http://127.0.0.1:8002"):
        self.base_url = base_url.rstrip('/')
        print(f"[Agent] 连接到 Omni Agent: {self.base_url}")
        
    async def send_message(self, message: str) -> Dict[str, Any]:
        """发送消息到Agent并返回响应"""
        # 解析命令格式
        if message.startswith("file:"):
            # 文件操作命令
            file_cmd = message[5:].strip()
            if "view" in file_cmd:
                parts = file_cmd.split()
                if len(parts) >= 2:
                    return await self.execute_skill("str_replace_editor", 
                                                  command="view", 
                                                  path=parts[1])
            elif "create" in file_cmd:
                return {"success": False, "message": "请指定文件内容"}
                
        elif message.startswith("cmd:"):
            # 终端命令
            cmd = message[4:].strip()
            return await self.execute_skill("bash", command=cmd)
            
        elif message == "screenshot":
            # 截图
            return await self.execute_skill("computer", action="screenshot")
            
        elif message == "help":
            return await self.get_help()
            
        else:
            # 普通对话 - 这里需要接入LLM
            return {
                "success": True,
                "message": f"收到消息: {message}",
                "note": "完整的LLM对话功能需要配置VLLM连接"
            }
    
    async def execute_skill(self, skill_name: str, **params) -> Dict[str, Any]:
        """执行技能"""
        data = {
            "tool_name": skill_name,
            "parameters": params
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/execute",
                    json=data,
                    headers={"Content-Type": "application/json"}
                )
                return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_health(self) -> Dict[str, Any]:
        """检查健康状态"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/health")
                return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_skills(self) -> Dict[str, Any]:
        """获取技能列表"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/skills")
                return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def get_help(self) -> Dict[str, Any]:
        """显示帮助信息"""
        skills_info = await self.get_skills()
        
        help_text = """
[Agent] Omni Agent 使用指南

[命令格式]:
• file:view <文件路径>     - 查看文件内容
• cmd:<shell命令>         - 执行终端命令  
• screenshot             - 获取屏幕截图
• help                   - 显示此帮助

[示例]:
• file:view README.md
• cmd:ls -la
• cmd:python --version
• screenshot

[可用技能]:
"""
        
        if skills_info.get("skills"):
            for skill in skills_info["skills"]:
                help_text += f"• {skill['name']}: {skill['description']}\n"
        
        help_text += "\n[前端界面]: http://127.0.0.1:8002"
        
        return {"success": True, "message": help_text}

async def main():
    """主聊天循环"""
    chat = OmniAgentChat()
    
    # 检查连接
    print("[检查] 检查Agent连接...")
    health = await chat.get_health()
    if health.get("status") == "ok":
        skills_count = health.get("skills_count", 0)
        print(f"[成功] Agent运行正常，已加载 {skills_count} 个技能")
    else:
        print("[错误] Agent连接失败，请确保服务正在运行")
        return
    
    print("\n" + "="*50)
    print("[启动] Omni Agent 聊天界面")
    print("输入 'help' 查看命令帮助")
    print("输入 'exit' 或 'quit' 退出")
    print("="*50 + "\n")
    
    while True:
        try:
            user_input = input("[你] ").strip()
            
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("[退出] 再见！")
                break
                
            if not user_input:
                continue
            
            print("[处理] 处理中...")
            response = await chat.send_message(user_input)
            
            print(f"[Agent] ")
            
            if response.get("success"):
                content = response.get("content")
                message = response.get("message")
                
                if content:
                    if isinstance(content, str):
                        print(content)
                    else:
                        print(json.dumps(content, indent=2, ensure_ascii=False))
                elif message:
                    print(message)
                else:
                    print("[完成] 操作完成")
                    
                # 显示额外信息
                if response.get("metadata"):
                    print(f"\n[元数据]: {response['metadata']}")
                    
            else:
                error = response.get("error", "未知错误")
                print(f"[错误]: {error}")
                
            print()  # 空行分隔
            
        except KeyboardInterrupt:
            print("\n[退出] 再见！")
            break
        except Exception as e:
            print(f"[错误] 发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())