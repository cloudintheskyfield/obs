"""Skills管理器 - 管理Claude官方Skills"""
import os
from typing import Dict, List, Optional, Any
from datetime import datetime

from loguru import logger

from .base_skill import BaseSkill, SkillResult
from .computer_use import ComputerUseSkill
from .text_editor import TextEditorSkill
from .bash import BashSkill


class SkillManager:
    """Skills管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.skills: Dict[str, BaseSkill] = {}
        self._initialize_skills()
    
    def _initialize_skills(self):
        """初始化Skills"""
        work_dir = self.config.get("work_dir", "workspace")
        screenshot_dir = self.config.get("screenshot_dir", "screenshots")
        
        # Computer Use Skill
        if self.config.get("enable_computer_use", True):
            self.skills["computer_use"] = ComputerUseSkill(screenshot_dir=screenshot_dir)
            logger.info("Computer Use Skill initialized")
        
        # Text Editor Skill
        if self.config.get("enable_text_editor", True):
            self.skills["text_editor"] = TextEditorSkill(work_dir=work_dir)
            logger.info("Text Editor Skill initialized")
        
        # Bash Skill
        if self.config.get("enable_bash", True):
            self.skills["bash"] = BashSkill(work_dir=work_dir)
            logger.info("Bash Skill initialized")
        
        logger.info(f"Initialized {len(self.skills)} skills: {list(self.skills.keys())}")
    
    def get_skill(self, name: str) -> Optional[BaseSkill]:
        """获取指定Skill"""
        return self.skills.get(name)
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """列出所有Skills"""
        return [skill.to_dict() for skill in self.skills.values()]
    
    def get_enabled_skills(self) -> Dict[str, BaseSkill]:
        """获取所有启用的Skills"""
        return {name: skill for name, skill in self.skills.items() if skill.enabled}
    
    def enable_skill(self, name: str) -> bool:
        """启用Skill"""
        if name in self.skills:
            self.skills[name].enabled = True
            return True
        return False
    
    def disable_skill(self, name: str) -> bool:
        """禁用Skill"""
        if name in self.skills:
            self.skills[name].enabled = False
            return True
        return False
    
    async def execute_skill(
        self,
        skill_name: str,
        **kwargs
    ) -> SkillResult:
        """执行指定Skill"""
        if skill_name not in self.skills:
            return SkillResult(
                success=False,
                error=f"Unknown skill: {skill_name}",
                metadata={
                    "available_skills": list(self.skills.keys()),
                    "requested_skill": skill_name
                }
            )
        
        skill = self.skills[skill_name]
        
        if not skill.enabled:
            return SkillResult(
                success=False,
                error=f"Skill '{skill_name}' is disabled",
                metadata={"skill_name": skill_name}
            )
        
        logger.info(f"Executing skill: {skill_name}")
        
        try:
            result = await skill.safe_execute(**kwargs)
            result.metadata["skill_name"] = skill_name
            result.metadata["execution_timestamp"] = datetime.now().isoformat()
            
            if result.success:
                logger.info(f"Skill {skill_name} executed successfully")
            else:
                logger.warning(f"Skill {skill_name} execution failed: {result.error}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error executing skill {skill_name}: {e}")
            return SkillResult(
                success=False,
                error=f"Unexpected error executing {skill_name}: {str(e)}",
                metadata={"skill_name": skill_name}
            )
    
    async def cleanup(self):
        """清理所有Skills资源"""
        logger.info("Cleaning up skills...")
        
        for skill_name, skill in self.skills.items():
            try:
                if hasattr(skill, 'cleanup'):
                    await skill.cleanup()
                    logger.debug(f"Cleaned up skill: {skill_name}")
            except Exception as e:
                logger.error(f"Error cleaning up skill {skill_name}: {e}")
        
        logger.info("Skills cleanup completed")
    
    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """获取Skill详细信息"""
        if skill_name not in self.skills:
            return None
        
        skill = self.skills[skill_name]
        return {
            **skill.to_dict(),
            "usage_examples": self._get_usage_examples(skill_name)
        }
    
    def _get_usage_examples(self, skill_name: str) -> List[Dict[str, str]]:
        """获取Skill使用示例"""
        examples = {
            "computer_use": [
                {
                    "description": "Take a screenshot",
                    "command": '{"action": "screenshot"}'
                },
                {
                    "description": "Click at coordinates",
                    "command": '{"action": "click", "coordinate": [640, 360]}'
                },
                {
                    "description": "Type text",
                    "command": '{"action": "type", "text": "Hello World"}'
                },
                {
                    "description": "Navigate to URL",
                    "command": '{"action": "navigate", "url": "https://example.com"}'
                }
            ],
            "text_editor": [
                {
                    "description": "View a file",
                    "command": '{"command": "view", "path": "example.txt"}'
                },
                {
                    "description": "Create a new file",
                    "command": '{"command": "create", "path": "new_file.txt", "file_text": "Hello World"}'
                },
                {
                    "description": "Replace text in file",
                    "command": '{"command": "str_replace", "path": "example.txt", "old_str": "old", "new_str": "new"}'
                },
                {
                    "description": "View specific lines",
                    "command": '{"command": "view", "path": "example.txt", "view_range": [1, 10]}'
                }
            ],
            "bash": [
                {
                    "description": "List files",
                    "command": '{"command": "ls -la"}'
                },
                {
                    "description": "Run Python script",
                    "command": '{"command": "python script.py"}'
                },
                {
                    "description": "Install package",
                    "command": '{"command": "pip install requests"}'
                },
                {
                    "description": "Background process",
                    "command": '{"command": "python server.py", "background": true}'
                }
            ]
        }
        
        return examples.get(skill_name, [])
    
    def get_skills_status(self) -> Dict[str, Any]:
        """获取所有Skills状态"""
        status = {
            "total_skills": len(self.skills),
            "enabled_skills": len(self.get_enabled_skills()),
            "disabled_skills": len(self.skills) - len(self.get_enabled_skills()),
            "skills": {}
        }
        
        for name, skill in self.skills.items():
            status["skills"][name] = {
                "enabled": skill.enabled,
                "description": skill.description,
                "parameters_count": len(skill.parameters)
            }
        
        return status
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查所有Skills"""
        health_status = {
            "overall_healthy": True,
            "timestamp": datetime.now().isoformat(),
            "skills": {}
        }
        
        for skill_name, skill in self.skills.items():
            try:
                # 简单的健康检查 - 尝试获取skill信息
                skill_healthy = skill.enabled and hasattr(skill, 'execute')
                
                health_status["skills"][skill_name] = {
                    "healthy": skill_healthy,
                    "enabled": skill.enabled,
                    "error": None
                }
                
                if not skill_healthy:
                    health_status["overall_healthy"] = False
                    
            except Exception as e:
                health_status["skills"][skill_name] = {
                    "healthy": False,
                    "enabled": skill.enabled,
                    "error": str(e)
                }
                health_status["overall_healthy"] = False
                logger.error(f"Health check failed for skill {skill_name}: {e}")
        
        return health_status