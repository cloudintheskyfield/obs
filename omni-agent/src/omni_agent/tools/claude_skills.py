"""Claude Skills工具集成"""
import asyncio
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pathlib import Path

import httpx
from anthropic import Anthropic
from loguru import logger

from ..core.vllm_client import VLLMClient


class ClaudeSkillsTool:
    """Claude Skills工具集成"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        vllm_client: Optional[VLLMClient] = None
    ):
        self.api_key = api_key
        self.vllm_client = vllm_client
        self.anthropic_client = None
        
        if api_key:
            self.anthropic_client = Anthropic(api_key=api_key)
        
        # Claude Skills定义
        self.skills = {
            "web_search": self._web_search_skill,
            "code_analysis": self._code_analysis_skill,
            "data_processing": self._data_processing_skill,
            "text_generation": self._text_generation_skill,
            "image_analysis": self._image_analysis_skill,
            "reasoning": self._reasoning_skill,
            "planning": self._planning_skill,
            "translation": self._translation_skill,
            "summarization": self._summarization_skill,
            "qa_answering": self._qa_answering_skill
        }
    
    async def list_skills(self) -> Dict[str, Any]:
        """列出可用的技能"""
        skill_descriptions = {
            "web_search": "网页搜索和信息提取",
            "code_analysis": "代码分析和理解",
            "data_processing": "数据处理和分析",
            "text_generation": "文本生成和创作",
            "image_analysis": "图像分析和理解",
            "reasoning": "逻辑推理和问题解决",
            "planning": "任务规划和分解",
            "translation": "多语言翻译",
            "summarization": "内容摘要和总结",
            "qa_answering": "问答系统"
        }
        
        return {
            "success": True,
            "skills": [
                {
                    "name": name,
                    "description": desc,
                    "available": True
                }
                for name, desc in skill_descriptions.items()
            ],
            "total_skills": len(skill_descriptions),
            "timestamp": datetime.now().isoformat()
        }
    
    async def execute_skill(
        self,
        skill_name: str,
        parameters: Dict[str, Any],
        use_claude: bool = True
    ) -> Dict[str, Any]:
        """执行指定技能"""
        if skill_name not in self.skills:
            return {
                "success": False,
                "error": f"Unknown skill: {skill_name}",
                "available_skills": list(self.skills.keys()),
                "timestamp": datetime.now().isoformat()
            }
        
        logger.info(f"Executing skill: {skill_name}")
        
        try:
            # 选择执行引擎
            if use_claude and self.anthropic_client:
                result = await self._execute_with_claude(skill_name, parameters)
            elif self.vllm_client:
                result = await self._execute_with_vllm(skill_name, parameters)
            else:
                result = await self.skills[skill_name](parameters)
            
            result["skill_name"] = skill_name
            result["execution_engine"] = "claude" if (use_claude and self.anthropic_client) else "vllm"
            result["timestamp"] = datetime.now().isoformat()
            
            logger.info(f"Skill {skill_name} executed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Error executing skill {skill_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "skill_name": skill_name,
                "timestamp": datetime.now().isoformat()
            }
    
    async def _execute_with_claude(
        self,
        skill_name: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用Claude API执行技能"""
        if not self.anthropic_client:
            raise ValueError("Claude API client not initialized")
        
        # 构建技能提示词
        prompt = self._build_skill_prompt(skill_name, parameters)
        
        try:
            response = await asyncio.to_thread(
                self.anthropic_client.messages.create,
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text
            
            # 尝试解析JSON响应
            try:
                result = json.loads(content)
                if isinstance(result, dict):
                    result["success"] = True
                    return result
            except json.JSONDecodeError:
                pass
            
            # 如果不是JSON，返回原始文本
            return {
                "success": True,
                "result": content,
                "format": "text"
            }
            
        except Exception as e:
            raise RuntimeError(f"Claude API error: {e}")
    
    async def _execute_with_vllm(
        self,
        skill_name: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用VLLM执行技能"""
        if not self.vllm_client:
            raise ValueError("VLLM client not initialized")
        
        prompt = self._build_skill_prompt(skill_name, parameters)
        
        # 检查是否有图像参数
        images = parameters.get("images", [])
        
        try:
            if images:
                # 多模态请求
                messages = self.vllm_client.prepare_messages(prompt, images)
            else:
                # 纯文本请求
                messages = [{"role": "user", "content": prompt}]
            
            response = await self.vllm_client.chat_completion(messages)
            
            if "choices" in response and response["choices"]:
                content = response["choices"][0]["message"]["content"]
                
                # 尝试解析JSON响应
                try:
                    result = json.loads(content)
                    if isinstance(result, dict):
                        result["success"] = True
                        return result
                except json.JSONDecodeError:
                    pass
                
                return {
                    "success": True,
                    "result": content,
                    "format": "text"
                }
            else:
                raise ValueError("Invalid VLLM response")
                
        except Exception as e:
            raise RuntimeError(f"VLLM error: {e}")
    
    def _build_skill_prompt(self, skill_name: str, parameters: Dict[str, Any]) -> str:
        """构建技能提示词"""
        skill_prompts = {
            "web_search": self._build_web_search_prompt,
            "code_analysis": self._build_code_analysis_prompt,
            "data_processing": self._build_data_processing_prompt,
            "text_generation": self._build_text_generation_prompt,
            "image_analysis": self._build_image_analysis_prompt,
            "reasoning": self._build_reasoning_prompt,
            "planning": self._build_planning_prompt,
            "translation": self._build_translation_prompt,
            "summarization": self._build_summarization_prompt,
            "qa_answering": self._build_qa_prompt
        }
        
        if skill_name in skill_prompts:
            return skill_prompts[skill_name](parameters)
        else:
            return f"执行技能: {skill_name}, 参数: {json.dumps(parameters, ensure_ascii=False)}"
    
    def _build_web_search_prompt(self, params: Dict[str, Any]) -> str:
        query = params.get("query", "")
        max_results = params.get("max_results", 5)
        
        return f"""
作为网页搜索专家，请帮我搜索以下关键词并提供相关信息：

搜索查询: {query}
最大结果数: {max_results}

请提供：
1. 相关网站和链接
2. 关键信息摘要
3. 可信度评估
4. 进一步搜索建议

请以JSON格式返回结果：
{{
    "results": [
        {{
            "title": "标题",
            "url": "链接",
            "summary": "摘要",
            "relevance": "相关性分数(1-10)"
        }}
    ],
    "summary": "总体摘要",
    "suggestions": ["进一步搜索建议"]
}}
"""
    
    def _build_code_analysis_prompt(self, params: Dict[str, Any]) -> str:
        code = params.get("code", "")
        language = params.get("language", "python")
        analysis_type = params.get("type", "general")
        
        return f"""
作为代码分析专家，请分析以下{language}代码：

```{language}
{code}
```

分析类型: {analysis_type}

请提供：
1. 代码功能说明
2. 代码质量评估
3. 潜在问题和建议
4. 性能优化建议
5. 安全性考量

请以JSON格式返回分析结果。
"""
    
    def _build_data_processing_prompt(self, params: Dict[str, Any]) -> str:
        data_description = params.get("data_description", "")
        processing_task = params.get("task", "")
        data_format = params.get("format", "")
        
        return f"""
作为数据处理专家，请帮我处理以下数据：

数据描述: {data_description}
数据格式: {data_format}
处理任务: {processing_task}

请提供：
1. 数据处理步骤
2. 推荐的工具和方法
3. 代码示例
4. 预期结果格式
5. 注意事项

请以JSON格式返回处理方案。
"""
    
    def _build_text_generation_prompt(self, params: Dict[str, Any]) -> str:
        topic = params.get("topic", "")
        style = params.get("style", "formal")
        length = params.get("length", "medium")
        purpose = params.get("purpose", "general")
        
        return f"""
作为文本生成专家，请根据以下要求创作内容：

主题: {topic}
风格: {style}
长度: {length}
目的: {purpose}

请生成高质量的文本内容，确保：
1. 内容准确且相关
2. 风格符合要求
3. 结构清晰
4. 语言流畅

请以JSON格式返回生成的内容和元信息。
"""
    
    def _build_image_analysis_prompt(self, params: Dict[str, Any]) -> str:
        task = params.get("task", "general_analysis")
        focus_areas = params.get("focus_areas", [])
        
        return f"""
作为图像分析专家，请分析提供的图像：

分析任务: {task}
关注领域: {', '.join(focus_areas) if focus_areas else '全面分析'}

请提供：
1. 图像内容描述
2. 关键对象识别
3. 场景分析
4. 技术质量评估
5. 相关建议或见解

请以JSON格式返回分析结果。
"""
    
    def _build_reasoning_prompt(self, params: Dict[str, Any]) -> str:
        problem = params.get("problem", "")
        context = params.get("context", "")
        reasoning_type = params.get("type", "logical")
        
        return f"""
作为推理专家，请帮我分析以下问题：

问题: {problem}
背景信息: {context}
推理类型: {reasoning_type}

请提供：
1. 问题分解
2. 推理步骤
3. 关键假设
4. 可能的结论
5. 不确定性分析

请以JSON格式返回推理过程和结论。
"""
    
    def _build_planning_prompt(self, params: Dict[str, Any]) -> str:
        goal = params.get("goal", "")
        constraints = params.get("constraints", [])
        timeline = params.get("timeline", "")
        
        return f"""
作为规划专家，请帮我制定以下目标的实现计划：

目标: {goal}
约束条件: {', '.join(constraints) if constraints else '无特殊约束'}
时间框架: {timeline}

请提供：
1. 目标分解
2. 执行步骤
3. 时间安排
4. 资源需求
5. 风险评估
6. 里程碑设定

请以JSON格式返回详细的执行计划。
"""
    
    def _build_translation_prompt(self, params: Dict[str, Any]) -> str:
        text = params.get("text", "")
        source_lang = params.get("source_language", "auto")
        target_lang = params.get("target_language", "en")
        style = params.get("style", "standard")
        
        return f"""
作为翻译专家，请将以下文本翻译：

原文: {text}
源语言: {source_lang}
目标语言: {target_lang}
翻译风格: {style}

请提供：
1. 准确的翻译
2. 语言质量评估
3. 文化适应性说明
4. 备选翻译（如有）

请以JSON格式返回翻译结果。
"""
    
    def _build_summarization_prompt(self, params: Dict[str, Any]) -> str:
        content = params.get("content", "")
        summary_type = params.get("type", "abstract")
        length = params.get("length", "brief")
        key_points = params.get("key_points", [])
        
        return f"""
作为摘要专家，请为以下内容生成摘要：

原始内容: {content}
摘要类型: {summary_type}
摘要长度: {length}
重点关注: {', '.join(key_points) if key_points else '全面总结'}

请提供：
1. 主要摘要
2. 关键要点
3. 重要数据/事实
4. 结论或建议

请以JSON格式返回摘要结果。
"""
    
    def _build_qa_prompt(self, params: Dict[str, Any]) -> str:
        question = params.get("question", "")
        context = params.get("context", "")
        answer_style = params.get("style", "comprehensive")
        
        return f"""
作为问答专家，请回答以下问题：

问题: {question}
背景信息: {context}
回答风格: {answer_style}

请提供：
1. 直接答案
2. 详细解释
3. 相关信息
4. 信息来源或推理依据
5. 进一步建议

请以JSON格式返回回答结果。
"""
    
    # 本地技能实现（当无法使用外部API时）
    async def _web_search_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地网页搜索技能实现"""
        return {
            "success": True,
            "message": "Local web search skill - requires external API integration",
            "suggestion": "Use Claude or VLLM for better results"
        }
    
    async def _code_analysis_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地代码分析技能实现"""
        code = params.get("code", "")
        
        basic_analysis = {
            "lines": len(code.split('\n')),
            "characters": len(code),
            "has_functions": "def " in code or "function " in code,
            "has_classes": "class " in code,
            "has_imports": "import " in code or "#include" in code
        }
        
        return {
            "success": True,
            "basic_analysis": basic_analysis,
            "message": "Basic code analysis completed - use Claude/VLLM for detailed analysis"
        }
    
    async def _data_processing_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地数据处理技能实现"""
        return {
            "success": True,
            "message": "Local data processing skill - limited functionality",
            "suggestion": "Use Claude or VLLM for comprehensive data processing guidance"
        }
    
    async def _text_generation_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地文本生成技能实现"""
        topic = params.get("topic", "")
        
        return {
            "success": True,
            "generated_text": f"This is a basic template about {topic}. For high-quality content generation, please use Claude or VLLM.",
            "message": "Basic text generation - use Claude/VLLM for better results"
        }
    
    async def _image_analysis_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地图像分析技能实现"""
        return {
            "success": True,
            "message": "Image analysis requires VLLM multimodal capabilities",
            "suggestion": "Use VLLM client for image analysis"
        }
    
    async def _reasoning_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地推理技能实现"""
        return {
            "success": True,
            "message": "Complex reasoning requires advanced AI models",
            "suggestion": "Use Claude or VLLM for sophisticated reasoning"
        }
    
    async def _planning_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地规划技能实现"""
        goal = params.get("goal", "")
        
        basic_steps = [
            f"Define clear objectives for: {goal}",
            "Identify required resources",
            "Create timeline",
            "Execute plan",
            "Monitor progress"
        ]
        
        return {
            "success": True,
            "basic_plan": basic_steps,
            "message": "Basic planning template - use Claude/VLLM for detailed planning"
        }
    
    async def _translation_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地翻译技能实现"""
        return {
            "success": True,
            "message": "Translation requires specialized AI models",
            "suggestion": "Use Claude or VLLM for accurate translation"
        }
    
    async def _summarization_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地摘要技能实现"""
        content = params.get("content", "")
        
        # 简单的摘要逻辑
        words = content.split()
        summary = " ".join(words[:50]) + "..." if len(words) > 50 else content
        
        return {
            "success": True,
            "summary": summary,
            "word_count": len(words),
            "message": "Basic summarization - use Claude/VLLM for better results"
        }
    
    async def _qa_answering_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """本地问答技能实现"""
        return {
            "success": True,
            "message": "Question answering requires advanced AI models",
            "suggestion": "Use Claude or VLLM for comprehensive answers"
        }