"""Claude Skills基类"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from loguru import logger


class SkillParameter(BaseModel):
    """Skill参数定义"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Optional[Any] = None


class SkillResult(BaseModel):
    """Skill执行结果"""
    success: bool
    content: Optional[str] = None
    base64_image: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class BaseSkill(ABC):
    """Claude Skills基类"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._parameters: List[SkillParameter] = []
        self._enabled = True
        self.skill_definition = None
    
    @property
    def enabled(self) -> bool:
        """是否启用"""
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        """设置启用状态"""
        self._enabled = value
        logger.info(f"Skill {self.name} {'enabled' if value else 'disabled'}")
    
    @property
    def parameters(self) -> List[SkillParameter]:
        """获取参数定义"""
        return self._parameters
    
    def add_parameter(
        self,
        name: str,
        param_type: str,
        description: str,
        required: bool = True,
        default: Optional[Any] = None
    ):
        """添加参数定义"""
        self._parameters.append(SkillParameter(
            name=name,
            type=param_type,
            description=description,
            required=required,
            default=default
        ))
    
    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """执行Skill"""
        pass
    
    def validate_parameters(self, **kwargs) -> Dict[str, Any]:
        """验证参数"""
        validated = {}
        
        for param in self._parameters:
            value = kwargs.get(param.name)
            
            if param.required and value is None:
                raise ValueError(f"Required parameter '{param.name}' is missing")
            
            if value is None and param.default is not None:
                value = param.default
            
            validated[param.name] = value
        
        return validated
    
    async def safe_execute(self, **kwargs) -> SkillResult:
        """安全执行Skill（带异常处理）"""
        try:
            if not self._enabled:
                return SkillResult(
                    success=False,
                    error=f"Skill '{self.name}' is disabled"
                )
            
            # 验证参数
            validated_params = self.validate_parameters(**kwargs)
            
            # 执行Skill
            logger.info(f"Executing skill: {self.name}")
            result = await self.execute(**validated_params)
            
            logger.info(f"Skill {self.name} executed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Error executing skill {self.name}: {e}")
            return SkillResult(
                success=False,
                error=str(e),
                metadata={"skill_name": self.name}
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "name": self.name,
            "description": self.description,
            "enabled": self._enabled,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default
                }
                for p in self._parameters
            ]
        }
        
        if self.skill_definition:
            result["skill_md"] = {
                "name": self.skill_definition.name,
                "description": self.skill_definition.description,
                "instructions": self.skill_definition.instructions[:200] + "..." if len(self.skill_definition.instructions) > 200 else self.skill_definition.instructions,
                "skill_dir": str(self.skill_definition.skill_dir)
            }
        
        return result
    
    def to_anthropic_tool(self) -> Dict[str, Any]:
        """转换为Anthropic Tool定义格式
        
        符合Claude API的工具定义规范：
        https://docs.anthropic.com/en/docs/agents-and-tools/tool-use
        
        优先使用 SKILL.md 中的 metadata (Level 1)
        """
        properties = {}
        required = []
        
        for param in self._parameters:
            properties[param.name] = {
                "type": self._map_type_to_json_schema(param.type),
                "description": param.description
            }
            
            if param.required:
                required.append(param.name)
        
        description = self.description
        if self.skill_definition:
            description = self.skill_definition.description
            logger.debug(f"Using description from SKILL.md for {self.name}")
        
        tool_def = {
            "name": self.name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties
            }
        }
        
        if required:
            tool_def["input_schema"]["required"] = required
        
        return tool_def
    
    @staticmethod
    def _map_type_to_json_schema(param_type: str) -> str:
        """将参数类型映射为JSON Schema类型"""
        type_mapping = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object"
        }
        return type_mapping.get(param_type, "string")