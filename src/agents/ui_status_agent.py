import json
import re
from typing import Dict, Any

from utils.logger import logger
from agents.base_agent import BaseAgent


class UIStatusAgent(BaseAgent):
    """
    专门用来监听其他 Agent 的思考内容，并生成前端状态栏需要展示的阶段性 Title 和 Detail。
    使用较快的小模型或默认模型，通过非阻塞的调用为 UI 更新状态。
    """
    def __init__(self, vllm_client: Any) -> None:
        super().__init__("UIStatus", vllm_client)

    async def generate_status(self, target_role: str, thinking_content: str, default_title: str) -> Dict[str, str]:
        if not thinking_content or not thinking_content.strip():
            return {"title": default_title, "detail": "整理思路中..."}
            
        prompt = (
            f"目标智能体 '{target_role}' 正在执行任务，以下是它当前的思考或输出片段：\n"
            f"<content>\n{thinking_content[-1200:]}\n</content>\n\n"
            "请根据上述内容，推测该智能体当前处于哪个执行阶段、正在做什么。\n"
            "严格以JSON格式返回（禁止输出其他任何无关解释）：\n"
            "{\n"
            f'  "title": "{default_title}", // 请简短概括阶段，如“分析项目结构”、“编写代码”、“规划方案”等（10字以内）\n'
            '  "detail": "稍微详细的解释，例如：正在读取项目文件目录以确定入口..." // (20字以内)\n'
            "}"
        )
        
        try:
            # 使用较激进的温度以增加速度，不需要很高深推理
            result = await self.vllm_client.generate_text(
                prompt,
                model="MiniMax-Text-01",  # 优先尝试使用小模型保证速度，如果没有该模型底层通常会自动 fallback
                temperature=0.2,
                max_tokens=64
            )
            
            match = re.search(r"\{.*\}", result or "", re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                return {
                    "title": str(parsed.get("title", default_title)).strip()[:15],
                    "detail": str(parsed.get("detail", "处理中...")).strip()[:40]
                }
        except Exception as e:
            logger.debug(f"UIStatusAgent generate_status failed: {e}")
            
        return {"title": default_title, "detail": ""}
