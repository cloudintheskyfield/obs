"""
Plan Agent - 决策规划代理
负责分析用户输入，制定执行计划
集成专家Agent系统进行智能任务分配
"""
import json
import re
from typing import List, Dict, Any, Optional
from loguru import logger

from ..core.vllm_client import VLLMClient
from .expert_agents import ExpertAgentOrchestrator


class PlanStep:
    """计划步骤"""
    def __init__(self, action: str, skill: Optional[str] = None, params: Optional[Dict[str, Any]] = None, description: str = ""):
        self.action = action  # 'skill' | 'response' | 'analysis'
        self.skill = skill    # 技能名称
        self.params = params or {}  # 技能参数
        self.description = description  # 步骤描述
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "skill": self.skill,
            "params": self.params,
            "description": self.description
        }


class ExecutionPlan:
    """执行计划"""
    def __init__(self, steps: List[PlanStep], reasoning: str = ""):
        self.steps = steps
        self.reasoning = reasoning  # 规划推理过程
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reasoning": self.reasoning,
            "steps": [step.to_dict() for step in self.steps]
        }


class PlanAgent:
    """计划决策代理"""
    
    def __init__(self, vllm_client: VLLMClient, available_skills: List[str]):
        self.vllm_client = vllm_client
        self.available_skills = available_skills
        
        # 初始化专家Agent编排器
        self.expert_orchestrator = ExpertAgentOrchestrator(vllm_client)
        
        # 技能描述
        self.skill_descriptions = {
            "bash": "执行bash命令和脚本，用于系统操作、运行程序、文件管理",
            "str_replace_editor": "查看、创建、编辑文本文件，支持多种格式",
            "web_search": "搜索互联网获取实时信息，如天气、新闻、股价等",
            "computer": "通过视觉界面与计算机交互，截图、点击、输入等",
            "code_sandbox": "在Docker容器中安全执行代码，支持Python/JS/Go等语言"
        }
    
    async def create_plan(self, user_input: str, context: List[Dict[str, Any]] = None) -> ExecutionPlan:
        """
        根据用户输入创建执行计划
        """
        try:
            # 构建提示词
            prompt = self._build_planning_prompt(user_input, context)
            
            # 调用VLLM进行推理
            messages = [{"role": "user", "content": prompt}]
            response = await self.vllm_client.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
                stream=False
            )
            
            # 解析计划
            plan_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return self._parse_plan_response(plan_text, user_input)
            
        except Exception as e:
            logger.error(f"Plan creation failed: {e}")
            # 返回默认计划
            return self._create_fallback_plan(user_input)
    
    def _build_planning_prompt(self, user_input: str, context: List[Dict[str, Any]] = None) -> str:
        """构建规划提示词"""
        
        skills_info = "\n".join([
            f"- {skill}: {desc}" 
            for skill, desc in self.skill_descriptions.items()
            if skill in self.available_skills
        ])
        
        context_str = ""
        if context:
            recent_context = context[-3:] if len(context) > 3 else context
            context_str = "最近的对话上下文:\n" + "\n".join([
                f"- {msg.get('role', 'user')}: {msg.get('content', '')[:100]}..." 
                for msg in recent_context
            ]) + "\n\n"
        
        prompt = f"""你是一个智能规划代理。根据用户输入分析需要执行的步骤，制定详细的执行计划。

{context_str}用户输入: {user_input}

可用技能:
{skills_info}

请分析用户的需求，制定执行计划。输出格式为JSON:
{{
    "reasoning": "分析用户需求的推理过程",
    "steps": [
        {{
            "action": "skill|response|analysis",
            "skill": "技能名称(如果action是skill)",
            "params": {{"参数名": "参数值"}},
            "description": "步骤描述"
        }}
    ]
}}

规则:
1. 如果需要实时信息(天气、新闻、股价)，使用web_search
2. 如果需要文件操作，使用str_replace_editor  
3. 如果需要系统操作，使用bash
4. 如果需要图形界面操作，使用computer
5. 简单问候或不需要工具的对话，直接response
6. 复杂任务可分解为多个步骤

请直接输出JSON，不要其他内容。"""
        
        return prompt
    
    def _parse_plan_response(self, plan_text: str, user_input: str) -> ExecutionPlan:
        """解析计划响应"""
        candidates = self._extract_json_candidates(plan_text)

        for candidate in candidates:
            parsed = self._try_parse_plan_json(candidate)
            if parsed is not None:
                return parsed

        logger.warning("Plan response parsing fell back to heuristic plan")
        return self._create_fallback_plan(user_input)

    def _extract_json_candidates(self, plan_text: str) -> List[str]:
        """提取可能的 JSON 候选文本"""
        candidates: List[str] = []

        fenced_match = re.findall(r"```json\s*([\s\S]*?)```", plan_text, re.IGNORECASE)
        candidates.extend(fenced_match)

        raw_match = re.search(r'\{[\s\S]*\}', plan_text)
        if raw_match:
            candidates.append(raw_match.group())

        cleaned = plan_text.strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

        return candidates

    def _try_parse_plan_json(self, json_text: str) -> Optional[ExecutionPlan]:
        """尝试解析并修复模型输出的 JSON"""
        try:
            normalized = self._repair_json_text(json_text)
            plan_data = json.loads(normalized)

            steps = []
            for step_data in plan_data.get("steps", []):
                step = PlanStep(
                    action=step_data.get("action", "response"),
                    skill=step_data.get("skill"),
                    params=step_data.get("params", {}),
                    description=step_data.get("description", "")
                )
                steps.append(step)

            return ExecutionPlan(
                steps=steps,
                reasoning=plan_data.get("reasoning", "")
            )
        except Exception as e:
            logger.error(f"Plan parsing failed: {e}")
            return None

    def _repair_json_text(self, text: str) -> str:
        """修复常见的 JSON 输出问题"""
        cleaned = text.strip()
        cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.replace("“", '"').replace("”", '"').replace("’", "'")
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        cleaned = re.sub(r"(\w+)\s*:", r'"\1":', cleaned)
        return cleaned
    
    def _create_fallback_plan(self, user_input: str) -> ExecutionPlan:
        """创建备用计划"""
        # 简单的关键词检测
        user_lower = user_input.lower()
        
        if any(word in user_lower for word in ["天气", "weather", "温度", "气温"]):
            return ExecutionPlan(
                steps=[
                    PlanStep(
                        action="skill",
                        skill="web_search", 
                        params={"query": user_input},
                        description="搜索天气信息"
                    )
                ],
                reasoning="检测到天气查询，使用web_search获取实时天气"
            )
        
        elif any(word in user_lower for word in ["新闻", "news", "资讯"]):
            return ExecutionPlan(
                steps=[
                    PlanStep(
                        action="skill",
                        skill="web_search",
                        params={"query": user_input}, 
                        description="搜索新闻资讯"
                    )
                ],
                reasoning="检测到新闻查询，使用web_search获取最新资讯"
            )
        
        elif any(word in user_lower for word in ["文件", "创建", "编辑", "查看", "file"]):
            return ExecutionPlan(
                steps=[
                    PlanStep(
                        action="skill",
                        skill="str_replace_editor",
                        params={"command": "view", "path": "."}, 
                        description="处理文件相关操作"
                    )
                ],
                reasoning="检测到文件操作需求，使用文件编辑器"
            )
        
        else:
            return ExecutionPlan(
                steps=[
                    PlanStep(
                        action="response",
                        description="直接响应用户"
                    )
                ],
                reasoning="普通对话，直接响应"
            )
