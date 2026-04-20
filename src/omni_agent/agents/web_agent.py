"""网页浏览Agent"""
from typing import Dict, Any, Optional
from loguru import logger

from ..config.config import WebBrowsingConfig
from ..core.vllm_client import VLLMClient


class WebAgent:
    """网页浏览Agent"""
    
    def __init__(self, vllm_client: VLLMClient, config: WebBrowsingConfig, skill_manager=None):
        self.vllm_client = vllm_client
        self.config = config
        self.skill_manager = skill_manager
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        pass
    
    async def execute_task(self, task: str, url: Optional[str] = None) -> Dict[str, Any]:
        """执行网页浏览任务"""
        logger.info(f"Executing web task: {task}")
        if self.skill_manager is None:
            return {
                "success": False,
                "task": task,
                "url": url,
                "error": "Skill manager is unavailable for web browsing",
            }

        skills_used = []
        artifacts: Dict[str, Any] = {}

        if url:
            computer_skill = self.skill_manager.skills.get("computer")
            if computer_skill is not None and hasattr(computer_skill, "navigate_to"):
                try:
                    screenshot = await computer_skill.navigate_to(url)
                    artifacts["navigation_screenshot_base64"] = screenshot
                    skills_used.append("computer-use (computer)")
                    try:
                        page_analysis = await self.vllm_client.analyze_images(
                            [f"data:image/png;base64,{screenshot}"],
                            prompt=f"Inspect this web page for the following task and summarize the visible result:\n{task}\nURL: {url}",
                        )
                        artifacts["page_analysis"] = page_analysis
                    except Exception as exc:
                        logger.warning(f"Page analysis failed for {url}: {exc}")
                        artifacts["page_analysis_error"] = str(exc)
                except Exception as exc:
                    logger.warning(f"Computer navigation failed for {url}: {exc}")
                    artifacts["navigation_error"] = str(exc)

        search_skill = self.skill_manager.skills.get("advanced_web_search") or self.skill_manager.skills.get("web_search")
        if search_skill is None:
            return {
                "success": False,
                "task": task,
                "url": url,
                "error": "No web search skill is available",
                "skills_used": skills_used,
                "artifacts": artifacts,
            }

        query = task.strip()
        if url:
            query = f"{query}\nTarget URL: {url}".strip()

        result = await search_skill.safe_execute(query=query, type="general")
        if result.success:
            skills_used.append("web-search (advanced_web_search)" if search_skill.name == "advanced_web_search" else "web-search (web_search)")
            message_parts = []
            if artifacts.get("page_analysis"):
                message_parts.append(f"Page analysis:\n{artifacts['page_analysis']}")
            if result.content:
                message_parts.append(f"Search result:\n{result.content}")
            return {
                "success": True,
                "task": task,
                "url": url,
                "message": "\n\n".join(message_parts) if message_parts else result.content,
                "skills_used": skills_used,
                "artifacts": artifacts,
            }

        return {
            "success": False,
            "task": task,
            "url": url,
            "error": result.error or "Web browsing failed",
            "skills_used": skills_used,
            "artifacts": artifacts,
        }
