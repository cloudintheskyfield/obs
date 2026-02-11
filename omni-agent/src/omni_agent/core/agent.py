"""主Agent调度器"""
import asyncio
import json
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pathlib import Path

from loguru import logger

from ..config.config import AgentConfig, load_config
from ..core.vllm_client import VLLMClient
from ..core.logger import setup_logger, start_live_logging
from ..agents.web_agent import WebAgent
from ..skills.skill_manager import SkillManager


class OmniAgent:
    """全能Agent - 主调度器"""
    
    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or load_config()
        
        # 初始化日志系统
        self.logger = setup_logger(self.config.log)
        
        # 初始化核心组件
        self.vllm_client: Optional[VLLMClient] = None
        self.web_agent: Optional[WebAgent] = None
        self.skill_manager: Optional[SkillManager] = None
        
        # 任务历史和状态
        self.task_history: List[Dict[str, Any]] = []
        self.current_task: Optional[Dict[str, Any]] = None
        self.is_running = False
        
        logger.info("OmniAgent initialized successfully")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.cleanup()
    
    async def initialize(self):
        """初始化所有组件"""
        logger.info("Initializing OmniAgent components...")
        
        try:
            # 初始化VLLM客户端
            self.vllm_client = VLLMClient(self.config.vllm)
            logger.info("VLLM client initialized")
            
            # 初始化Skills管理器
            skills_config = {
                "work_dir": self.config.work_dir,
                "screenshot_dir": getattr(self.config, 'screenshot_dir', 'screenshots'),
                "enable_computer_use": getattr(self.config, 'enable_computer_use', True),
                "enable_text_editor": getattr(self.config, 'enable_text_editor', True),
                "enable_bash": getattr(self.config, 'enable_bash', True),
            }
            self.skill_manager = SkillManager(skills_config)
            logger.info("Skills manager initialized")
            
            self.is_running = True
            logger.info("All components initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing components: {e}")
            raise
    
    async def cleanup(self):
        """清理资源"""
        logger.info("Cleaning up OmniAgent...")
        
        try:
            # 清理Skills
            if self.skill_manager:
                await self.skill_manager.cleanup()
            
            # 关闭网页代理
            if self.web_agent:
                await self.web_agent.__aexit__(None, None, None)
            
            # 关闭VLLM客户端
            if self.vllm_client:
                await self.vllm_client.__aexit__(None, None, None)
            
            self.is_running = False
            logger.info("Cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    async def process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理用户请求"""
        if not self.is_running:
            return {
                "success": False,
                "error": "Agent not initialized. Please call initialize() first.",
                "timestamp": datetime.now().isoformat()
            }
        
        # 生成任务ID
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        # 记录任务开始
        task_info = {
            "task_id": task_id,
            "request": request,
            "start_time": datetime.now().isoformat(),
            "status": "in_progress"
        }
        
        self.current_task = task_info
        logger.info(f"Processing request: {task_id}")
        
        try:
            # 解析请求类型
            request_type = request.get("type", "")
            
            if request_type == "web_browsing":
                result = await self._handle_web_browsing(request)
            elif request_type == "skill":
                result = await self._handle_skill_execution(request)
            elif request_type == "multimodal_analysis":
                result = await self._handle_multimodal_analysis(request)
            elif request_type == "complex_task":
                result = await self._handle_complex_task(request)
            else:
                result = await self._handle_general_request(request)
            
            # 记录任务完成
            task_info["end_time"] = datetime.now().isoformat()
            task_info["status"] = "completed"
            task_info["result"] = result
            
            # 添加到历史记录
            self.task_history.append(task_info)
            
            # 限制历史记录大小
            if len(self.task_history) > 1000:
                self.task_history = self.task_history[-1000:]
            
            self.current_task = None
            logger.info(f"Request completed: {task_id}")
            
            return {
                "success": True,
                "task_id": task_id,
                "result": result,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            # 记录任务失败
            task_info["end_time"] = datetime.now().isoformat()
            task_info["status"] = "failed"
            task_info["error"] = str(e)
            
            self.task_history.append(task_info)
            self.current_task = None
            
            logger.error(f"Error processing request {task_id}: {e}")
            
            return {
                "success": False,
                "task_id": task_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def _handle_web_browsing(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理网页浏览请求"""
        logger.info("Handling web browsing request")
        
        # 初始化WebAgent（如果需要）
        if not self.web_agent:
            self.web_agent = WebAgent(
                vllm_client=self.vllm_client,
                config=self.config.web_browsing
            )
            await self.web_agent.__aenter__()
        
        # 执行网页任务
        url = request.get("url")
        task_description = request.get("task", "浏览网页")
        
        return await self.web_agent.execute_task(task_description, url)
    
    async def _handle_skill_execution(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理Skills执行请求"""
        logger.info("Handling skill execution request")
        
        skill_name = request.get("skill", "")
        if not skill_name:
            return {
                "success": False,
                "error": "Skill name is required",
                "available_skills": list(self.skill_manager.skills.keys()) if self.skill_manager else []
            }
        
        # 特殊处理：列出所有Skills
        if skill_name == "list":
            return {
                "success": True,
                "skills": self.skill_manager.list_skills() if self.skill_manager else [],
                "skills_status": self.skill_manager.get_skills_status() if self.skill_manager else {}
            }
        
        # 特殊处理：获取Skills信息
        if skill_name == "info":
            target_skill = request.get("target_skill", "")
            if not target_skill:
                return {
                    "success": False,
                    "error": "target_skill parameter is required for info command"
                }
            
            skill_info = self.skill_manager.get_skill_info(target_skill) if self.skill_manager else None
            if skill_info:
                return {
                    "success": True,
                    "skill_info": skill_info
                }
            else:
                return {
                    "success": False,
                    "error": f"Skill not found: {target_skill}"
                }
        
        # 特殊处理：健康检查
        if skill_name == "health":
            return {
                "success": True,
                "health_status": await self.skill_manager.health_check() if self.skill_manager else {"overall_healthy": False, "error": "Skills not initialized"}
            }
        
        # 执行普通Skills
        if not self.skill_manager:
            return {
                "success": False,
                "error": "Skills manager not initialized"
            }
        
        # 获取Skills参数
        parameters = request.get("parameters", {})
        
        # 执行Skill
        result = await self.skill_manager.execute_skill(skill_name, **parameters)
        
        # 转换SkillResult为字典
        return {
            "success": result.success,
            "content": result.content,
            "base64_image": result.base64_image,
            "error": result.error,
            "metadata": result.metadata,
            "timestamp": result.timestamp
        }
    

    
    async def _handle_multimodal_analysis(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理多模态分析请求"""
        logger.info("Handling multimodal analysis request")
        
        try:
            async with self.vllm_client:
                prompt = request.get("prompt", "请分析这张图片")
                images = request.get("images", [])
                
                if not images:
                    return {
                        "success": False,
                        "error": "No images provided for multimodal analysis"
                    }
                
                result = await self.vllm_client.analyze_images(images, prompt)
                
                return {
                    "success": True,
                    "analysis": result,
                    "image_count": len(images)
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Multimodal analysis failed: {str(e)}"
            }
    
    async def _handle_complex_task(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理复杂任务（需要多个工具协作）"""
        logger.info("Handling complex task request")
        
        task_description = request.get("description", "")
        steps = request.get("steps", [])
        
        results = []
        
        # 如果没有明确的步骤，创建默认步骤
        if not steps:
            steps = [{"description": task_description, "type": "skill", "skill": "text_editor", "parameters": {"command": "view", "path": "README.md"}}]
            logger.info("Created default task steps")
        
        # 执行任务步骤
        for i, step in enumerate(steps):
            step_result = {
                "step_number": i + 1,
                "description": step.get("description", f"Step {i+1}"),
                "timestamp": datetime.now().isoformat()
            }
            
            try:
                # 根据步骤类型执行相应操作
                step_type = step.get("type", "general")
                
                if step_type == "web_browsing":
                    result = await self._handle_web_browsing(step)
                elif step_type == "skill":
                    result = await self._handle_skill_execution(step)
                else:
                    # 通用处理
                    result = await self._handle_general_request(step)
                
                step_result["success"] = True
                step_result["result"] = result
                
            except Exception as e:
                step_result["success"] = False
                step_result["error"] = str(e)
                logger.error(f"Error in step {i+1}: {e}")
            
            results.append(step_result)
        
        # 统计结果
        successful_steps = sum(1 for r in results if r.get("success", False))
        total_steps = len(results)
        
        return {
            "success": successful_steps > 0,
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "failed_steps": total_steps - successful_steps,
            "results": results
        }
    
    async def _handle_general_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理一般请求"""
        logger.info("Handling general request")
        
        # 使用VLLM进行一般性处理
        try:
            async with self.vllm_client:
                prompt = request.get("prompt", str(request))
                
                messages = [{"role": "user", "content": prompt}]
                response = await self.vllm_client.chat_completion(messages)
                
                if "choices" in response and response["choices"]:
                    content = response["choices"][0]["message"]["content"]
                    
                    return {
                        "success": True,
                        "response": content,
                        "model": self.config.vllm.model
                    }
                else:
                    return {
                        "success": False,
                        "error": "Invalid response from VLLM"
                    }
                    
        except Exception as e:
            logger.error(f"General request failed: {e}")
            return {
                "success": False,
                "error": f"General request processing failed: {str(e)}"
            }
    
    def get_status(self) -> Dict[str, Any]:
        """获取Agent状态"""
        return {
            "is_running": self.is_running,
            "current_task": self.current_task,
            "total_tasks": len(self.task_history),
            "components": {
                "vllm_client": self.vllm_client is not None,
                "web_agent": self.web_agent is not None,
                "file_tool": self.file_tool is not None,
                "terminal_tool": self.terminal_tool is not None,
                "claude_skills": self.claude_skills is not None
            },
            "config": {
                "work_dir": str(self.config.work_dir),
                "allow_file_operations": self.config.allow_file_operations,
                "allow_terminal_execution": self.config.allow_terminal_execution,
                "vllm_url": self.config.vllm.base_url
            },
            "timestamp": datetime.now().isoformat()
        }
    
    def get_task_history(
        self,
        limit: Optional[int] = None,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取任务历史"""
        history = self.task_history.copy()
        
        # 状态过滤
        if status_filter:
            history = [task for task in history if task.get("status") == status_filter]
        
        # 限制数量
        if limit:
            history = history[-limit:]
        
        return history
    
    async def start_live_monitoring(self):
        """启动实时监控"""
        start_live_logging()
        logger.info("Live monitoring started")
    
    async def stop_live_monitoring(self):
        """停止实时监控"""
        if self.logger:
            self.logger.stop_live_display()
        logger.info("Live monitoring stopped")