"""Skills管理器 - 管理Claude官方Skills"""
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from loguru import logger

from base_skill import BaseSkill, SkillResult
from skill_loader import SkillLoader


class SkillManager:
    """Skills管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.skills: Dict[str, BaseSkill] = {}
        self.skill_loader = SkillLoader(skills_root=config.get("skills_dir"))
        self._initialize_skills()
    
    def _initialize_skills(self):
        """初始化Skills - 从.claude/skills目录加载完整的三级结构"""
        work_dir = self.config.get("work_dir", "workspace")
        screenshot_dir = self.config.get("screenshot_dir", "screenshots")
        
        # Load advanced web search skill from web-search directory
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).parent / "web-search"))
            from advanced_web_search import AdvancedWebSearchSkill
            web_search_skill = AdvancedWebSearchSkill()
            # Override the regular web_search with our enhanced version
            self.skills["web_search"] = web_search_skill
            self.skills["advanced_web_search"] = web_search_skill
            logger.info("Initialized advanced web_search skill, overriding regular web_search")
        except Exception as e:
            logger.error(f"Failed to load advanced web_search skill: {e}")
        
        skill_definitions = self.skill_loader.load_all_skills()
        logger.info(f"Loaded {len(skill_definitions)} skill definitions from .claude/skills")
        
        # 从skill definitions创建skill实例
        for skill_name, skill_def in skill_definitions.items():
            if self._should_enable_skill(skill_name):
                try:
                    # 尝试从Level 3 Python实现创建实例
                    skill_instance = self._create_skill_instance(skill_name, skill_def, work_dir, screenshot_dir)
                    
                    if skill_instance:
                        # 关联SKILL.md定义
                        skill_instance.skill_definition = skill_def
                        
                        # Skip regular web_search if we already have advanced web_search loaded
                        if skill_instance.name == "web_search" and "web_search" in self.skills:
                            logger.info(f"Skipping regular web_search, using enhanced version")
                            continue
                            
                        self.skills[skill_instance.name] = skill_instance
                        logger.info(f"Initialized skill from .claude/skills: {skill_name} -> {skill_instance.name}")
                    else:
                        logger.warning(f"Failed to create instance for skill: {skill_name}")
                        
                except Exception as e:
                    logger.error(f"Error initializing skill {skill_name}: {e}")
        
        logger.info(f"Initialized {len(self.skills)} skills: {list(self.skills.keys())}")
    
    def _should_enable_skill(self, skill_name: str) -> bool:
        """检查skill是否应该启用"""
        skill_config_map = {
            "computer-use": "enable_computer_use",
            "file-operations": "enable_text_editor", 
            "terminal": "enable_bash"
        }
        
        config_key = skill_config_map.get(skill_name)
        if config_key:
            return self.config.get(config_key, True)
        
        # 默认启用未知的skills
        return True
    
    def _create_skill_instance(self, skill_name: str, skill_def, work_dir: str, screenshot_dir: str) -> Optional[BaseSkill]:
        """从skill definition创建skill实例"""
        if skill_def.skill_class:
            # 使用Level 3的Python实现
            try:
                # 根据skill类型传递适当的参数
                if skill_name == "computer-use":
                    return skill_def.skill_class(screenshot_dir=screenshot_dir)
                elif skill_name in ["file-operations", "terminal"]:
                    return skill_def.skill_class(work_dir=work_dir)
                elif skill_name == "code-sandbox":
                    return skill_def.skill_class(config={"workspace_dir": work_dir})
                else:
                    # 尝试通用初始化
                    return skill_def.skill_class()
                    
            except Exception as e:
                logger.error(f"Failed to create instance from Level 3 implementation for {skill_name}: {e}")
        
        # 如果没有Level 3实现，返回None（或可以创建一个基础的skill实例）
        logger.warning(f"No Level 3 implementation found for skill: {skill_name}")
        return None
    
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
        """获取Skill详细信息 - 包含SKILL.md的完整instructions (Level 2)"""
        if skill_name not in self.skills:
            return None
        
        skill = self.skills[skill_name]
        info = {
            **skill.to_dict(),
            "usage_examples": self._get_usage_examples(skill_name)
        }
        
        if skill.skill_definition:
            info["instructions"] = skill.skill_definition.instructions
            info["skill_directory"] = str(skill.skill_definition.skill_dir)
        
        return info
    
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
    
    def get_anthropic_tools(self) -> List[Dict[str, Any]]:
        """获取符合Anthropic API规范的Tool定义列表
        
        使用SKILL.md的Level 1 metadata (name + description)
        
        返回格式符合Claude API的tools参数：
        [
            {
                "name": "tool_name",
                "description": "Tool description from SKILL.md",
                "input_schema": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            },
            ...
        ]
        """
        tools = []
        seen_tool_names = set()
        
        for skill_name, skill in self.get_enabled_skills().items():
            try:
                tool_def = skill.to_anthropic_tool()
                tool_name = tool_def.get("name")
                if tool_name in seen_tool_names:
                    logger.debug(f"Skipping duplicate tool definition: {tool_name}")
                    continue

                tools.append(tool_def)
                if tool_name:
                    seen_tool_names.add(tool_name)
                
                if skill.skill_definition:
                    logger.debug(f"Generated tool from SKILL.md: {skill.skill_definition.name}")
                else:
                    logger.warning(f"No SKILL.md found for {skill_name}, using fallback")
                    
            except Exception as e:
                logger.error(f"Error generating tool definition for {skill_name}: {e}")
        
        logger.info(f"Generated {len(tools)} Anthropic tool definitions from SKILL.md")
        return tools
    
    def get_skill_instructions(self, skill_name: str) -> Optional[str]:
        """获取Skill的Level 2 instructions (当skill被触发时加载)"""
        if skill_name not in self.skills:
            return None
        
        skill = self.skills[skill_name]
        if skill.skill_definition:
            return skill.skill_definition.instructions
        
        return None
    
    def list_skill_metadata(self) -> Dict[str, Dict[str, str]]:
        """列出所有Skills的Level 1 metadata (轻量级)"""
        return self.skill_loader.get_all_skill_metadata()
