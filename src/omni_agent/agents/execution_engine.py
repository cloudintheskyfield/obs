"""
Execution Engine - 基于计划的任务执行引擎
模仿 Windsurf 的工作流程：制定计划 -> 逐步执行 -> 检查验证
支持并行/串行任务调度和自愈机制
"""
import json
import asyncio
from typing import Dict, List, Any, Optional, AsyncGenerator, Set
from loguru import logger

from .plan_agent import PlanAgent, ExecutionPlan, PlanStep
from .task_graph import TaskGraph, TaskNode, analyze_task_dependencies
from ..core.vllm_client import VLLMClient


class TaskResult:
    """任务结果"""
    def __init__(self, success: bool, content: Any = None, error: str = None):
        self.success = success
        self.content = content
        self.error = error


class ExecutionEngine:
    """执行引擎 - 负责计划制定和任务执行"""
    
    def __init__(self, vllm_client: VLLMClient, skill_manager, plan_agent: PlanAgent):
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.plan_agent = plan_agent
        
    async def execute_user_request(
        self, 
        user_message: str, 
        session_id: str, 
        chat_history: List[Dict[str, Any]]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        执行用户请求的完整流程（支持并行执行）
        """
        try:
            # Phase 1: 制定执行计划
            logger.info(f"Phase 1: Creating execution plan for: {user_message}")
            yield {"type": "phase", "content": "正在制定执行计划...", "phase": "planning"}
            
            plan = await self.plan_agent.create_plan(user_message, chat_history)
            
            # 构建任务依赖图
            steps_dict = [step.to_dict() for step in plan.steps]
            task_graph = analyze_task_dependencies(steps_dict)
            
            yield {
                "type": "plan", 
                "content": plan.to_dict(),
                "task_graph": task_graph.to_dict(),
                "phase": "planning"
            }
            
            # Phase 2: 并行/串行执行任务
            parallel_groups = task_graph.get_parallel_groups()
            total_tasks = len(plan.steps)
            logger.info(f"Phase 2: Executing {total_tasks} tasks in {len(parallel_groups)} layers")
            yield {"type": "phase", "content": f"开始执行 {total_tasks} 个任务（{len(parallel_groups)} 层并行）...", "phase": "execution"}
            
            execution_results = {}
            context = ""
            completed_tasks: Set[str] = set()
            
            # 逐层执行（层内并行，层间串行）
            for layer_idx, task_group in enumerate(parallel_groups):
                yield {
                    "type": "layer_start",
                    "content": f"执行第 {layer_idx+1} 层（{len(task_group)} 个并行任务）",
                    "layer_index": layer_idx,
                    "tasks_count": len(task_group),
                    "phase": "execution"
                }

                for task_node in task_group:
                    yield {
                        "type": "task_start",
                        "task_id": task_node.task_id,
                        "description": task_node.description,
                        "skill": task_node.skill,
                        "action": task_node.action,
                        "phase": "execution"
                    }
                
                # 并行执行当前层的所有任务
                layer_results = await self._execute_parallel_tasks(
                    task_group, context, chat_history, layer_idx
                )
                
                # 收集结果并更新上下文
                for task_node, task_result in layer_results:
                    execution_results[task_node.task_id] = task_result
                    
                    yield {
                        "type": "task_complete",
                        "content": task_result.content if task_result.success else f"任务失败: {task_result.error}",
                        "success": task_result.success,
                        "task_id": task_node.task_id,
                        "description": task_node.description,
                        "phase": "execution"
                    }
                    
                    if task_result.success:
                        completed_tasks.add(task_node.task_id)
                        if task_result.content:
                            context += f"\n\n[{task_node.task_id}结果]: {task_result.content}"
            
            # Phase 3: 生成最终响应
            logger.info("Phase 3: Generating final response")
            yield {"type": "phase", "content": "整合结果并生成回复...", "phase": "synthesis"}
            
            # 转换execution_results为列表格式（兼容旧接口）
            results_list = [execution_results.get(f"task_{i+1}") for i in range(len(plan.steps))]
            results_list = [r for r in results_list if r is not None]
            
            final_response = await self._synthesize_final_response(
                user_message, plan, results_list, context, chat_history
            )
            
            yield {
                "type": "final_response",
                "content": final_response,
                "phase": "synthesis"
            }
            
            # Phase 4: 验证检查
            yield {"type": "phase", "content": "检查任务完成情况...", "phase": "verification"}
            
            verification_result = await self._verify_completion(
                user_message, plan, execution_results, final_response
            )
            
            yield {
                "type": "verification",
                "content": verification_result,
                "phase": "verification"
            }
            
            yield {"type": "complete", "content": "所有任务已完成", "phase": "complete"}
            
        except Exception as e:
            logger.error(f"Execution engine error: {e}")
            yield {
                "type": "error",
                "content": f"执行过程中发生错误: {str(e)}",
                "phase": "error"
            }
    
    async def _execute_single_task(
        self, 
        step: PlanStep, 
        context: str,
        chat_history: List[Dict[str, Any]]
    ) -> TaskResult:
        """执行单个任务"""
        try:
            if step.action == "skill":
                # 执行技能调用
                return await self._execute_skill_task(step, context)
                
            elif step.action == "response":
                # 直接生成响应
                return await self._execute_response_task(step, context, chat_history)
                
            elif step.action == "analysis":
                # 分析任务
                return await self._execute_analysis_task(step, context, chat_history)
                
            else:
                return TaskResult(False, None, f"未知任务类型: {step.action}")
                
        except Exception as e:
            logger.error(f"Task execution error: {e}")
            return TaskResult(False, None, str(e))
    
    async def _execute_skill_task(self, step: PlanStep, context: str) -> TaskResult:
        """执行技能任务"""
        try:
            skill_name = step.skill
            if not skill_name or skill_name not in self.skill_manager.skills:
                return TaskResult(False, None, f"技能 {skill_name} 不存在")
            
            # 获取技能实例
            skill = self.skill_manager.skills[skill_name]
            
            # 执行技能
            result = await skill.execute(**step.params)
            
            if result.success:
                return TaskResult(True, result.content)
            else:
                return TaskResult(False, None, result.error or "技能执行失败")
                
        except Exception as e:
            return TaskResult(False, None, f"技能执行错误: {str(e)}")
    
    async def _execute_response_task(
        self, 
        step: PlanStep, 
        context: str,
        chat_history: List[Dict[str, Any]]
    ) -> TaskResult:
        """执行回复任务"""
        try:
            # 构建回复提示
            messages = chat_history.copy()
            
            if context:
                messages.append({
                    "role": "system",
                    "content": f"基于以下上下文信息回复用户:\n{context}"
                })
            
            response = await self.vllm_client.chat_completion(
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                stream=False
            )
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return TaskResult(True, content)
            
        except Exception as e:
            return TaskResult(False, None, f"回复生成错误: {str(e)}")
    
    async def _execute_analysis_task(
        self,
        step: PlanStep,
        context: str, 
        chat_history: List[Dict[str, Any]]
    ) -> TaskResult:
        """执行分析任务"""
        try:
            analysis_prompt = f"""
分析以下信息:
任务描述: {step.description}
上下文: {context}

请提供详细的分析结果。
"""
            
            messages = [{"role": "user", "content": analysis_prompt}]
            
            response = await self.vllm_client.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=800,
                stream=False
            )
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return TaskResult(True, content)
            
        except Exception as e:
            return TaskResult(False, None, f"分析任务错误: {str(e)}")
    
    async def _synthesize_final_response(
        self,
        user_message: str,
        plan: ExecutionPlan, 
        results: List[TaskResult],
        context: str,
        chat_history: List[Dict[str, Any]]
    ) -> str:
        """整合最终响应"""
        try:
            # 收集成功的结果
            successful_results = []
            failed_results = []
            
            for i, result in enumerate(results):
                if result.success:
                    successful_results.append(f"任务{i+1}: {result.content}")
                else:
                    failed_results.append(f"任务{i+1}失败: {result.error}")
            
            synthesis_prompt = f"""
用户问题: {user_message}

执行计划推理: {plan.reasoning}

成功完成的任务:
{chr(10).join(successful_results) if successful_results else '无'}

失败的任务:
{chr(10).join(failed_results) if failed_results else '无'}

请基于以上执行结果，为用户提供一个完整、准确、友好的回复。使用Markdown格式。
"""
            
            messages = [{"role": "user", "content": synthesis_prompt}]
            
            response = await self.vllm_client.chat_completion(
                messages=messages,
                temperature=0.7,
                max_tokens=1500,
                stream=False
            )
            
            return response.get("choices", [{}])[0].get("message", {}).get("content", "抱歉，无法生成回复。")
            
        except Exception as e:
            logger.error(f"Response synthesis error: {e}")
            return f"在整合回复时发生错误: {str(e)}"
    
    async def _verify_completion(
        self,
        user_message: str,
        plan: ExecutionPlan,
        results: List[TaskResult],
        final_response: str
    ) -> str:
        """验证任务完成情况"""
        try:
            success_count = sum(1 for r in results if r.success)
            total_count = len(results)
            
            verification_prompt = f"""
用户原始问题: {user_message}
计划步骤数: {total_count}
成功完成: {success_count}
失败: {total_count - success_count}

最终回复: {final_response[:200]}...

请评估:
1. 是否充分回答了用户的问题？
2. 执行过程是否顺利？
3. 有无需要改进的地方？

请简洁回答。
"""
            
            messages = [{"role": "user", "content": verification_prompt}]
            
            response = await self.vllm_client.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=300,
                stream=False
            )
            
            verification_content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            return f"✅ 任务完成情况: {success_count}/{total_count} 成功\n{verification_content}"
            
        except Exception as e:
            return f"验证过程出错: {str(e)}"
    
    async def _execute_parallel_tasks(
        self,
        task_group: List[TaskNode],
        context: str,
        chat_history: List[Dict[str, Any]],
        layer_idx: int
    ) -> List[tuple[TaskNode, TaskResult]]:
        """
        并行执行一组任务
        返回: [(TaskNode, TaskResult), ...]
        """
        logger.info(f"并行执行第 {layer_idx+1} 层的 {len(task_group)} 个任务")
        
        async def execute_with_node(task_node: TaskNode):
            # 转换TaskNode为PlanStep格式
            step = PlanStep(
                action=task_node.action,
                skill=task_node.skill,
                params=task_node.params,
                description=task_node.description
            )
            
            # 使用自愈机制执行任务
            result = await self._execute_single_task_with_retry(step, context, chat_history)
            return (task_node, result)
        
        # 使用asyncio.gather并行执行
        results = await asyncio.gather(*[execute_with_node(task) for task in task_group])
        
        return results
    
    async def _execute_single_task_with_retry(
        self,
        step: PlanStep,
        context: str,
        chat_history: List[Dict[str, Any]],
        max_retries: int = 5
    ) -> TaskResult:
        """
        执行单个任务（带自愈重试机制）
        """
        for retry in range(max_retries):
            try:
                logger.info(f"执行任务: {step.description} (尝试 {retry+1}/{max_retries})")
                
                # 执行任务
                result = await self._execute_single_task(step, context, chat_history)
                
                # 如果成功，直接返回
                if result.success:
                    if retry > 0:
                        logger.info(f"任务在第 {retry+1} 次尝试后成功")
                    return result
                
                # 如果失败且还有重试机会，进行错误分析和修复
                if retry < max_retries - 1:
                    logger.warning(f"任务失败: {result.error}, 尝试修复...")
                    
                    # 分析错误并生成修复建议
                    fixed_step = await self._analyze_and_fix_error(step, result.error, context)
                    
                    if fixed_step:
                        step = fixed_step  # 使用修复后的步骤重试
                        logger.info(f"应用修复建议，准备第 {retry+2} 次尝试")
                    else:
                        # 如果无法修复，等待一段时间后重试
                        await asyncio.sleep(1)
                else:
                    # 最后一次尝试失败，返回失败结果
                    logger.error(f"任务在 {max_retries} 次尝试后仍然失败")
                    return result
                    
            except Exception as e:
                logger.error(f"任务执行异常: {e}")
                if retry == max_retries - 1:
                    return TaskResult(False, None, str(e))
                await asyncio.sleep(1)
        
        return TaskResult(False, None, "达到最大重试次数")
    
    async def _analyze_and_fix_error(
        self,
        step: PlanStep,
        error: str,
        context: str
    ) -> Optional[PlanStep]:
        """
        分析错误并生成修复后的步骤
        """
        try:
            analysis_prompt = f"""
任务失败，需要分析错误并提供修复方案。

原始任务:
- 动作: {step.action}
- 技能: {step.skill}
- 参数: {json.dumps(step.params, ensure_ascii=False)}
- 描述: {step.description}

错误信息:
{error}

上下文:
{context[:500]}...

请分析错误原因，并提供修复后的参数。输出JSON格式:
{{
    "error_analysis": "错误原因分析",
    "fix_suggestion": "修复建议",
    "fixed_params": {{"修复后的参数"}}
}}
"""
            
            messages = [{"role": "user", "content": analysis_prompt}]
            
            response = await self.vllm_client.chat_completion(
                messages=messages,
                temperature=0.2,
                max_tokens=500,
                stream=False
            )
            
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # 尝试解析JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                fix_data = json.loads(json_match.group())
                fixed_params = fix_data.get("fixed_params", {})
                
                if fixed_params:
                    # 创建修复后的步骤
                    fixed_step = PlanStep(
                        action=step.action,
                        skill=step.skill,
                        params=fixed_params,
                        description=step.description
                    )
                    
                    logger.info(f"错误分析: {fix_data.get('error_analysis', 'N/A')}")
                    logger.info(f"修复建议: {fix_data.get('fix_suggestion', 'N/A')}")
                    
                    return fixed_step
            
            return None
            
        except Exception as e:
            logger.error(f"错误分析失败: {e}")
            return None
