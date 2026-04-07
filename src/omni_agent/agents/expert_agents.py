"""
Expert Agents - 专家Agent系统
实现6种专业角色：PM, Architect, Backend Dev, Frontend Dev, QA Reviewer, Travel Planner
"""
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from loguru import logger

from ..core.vllm_client import VLLMClient


class BaseExpertAgent(ABC):
    """
    专家Agent基类
    每个专家有独立的system prompt和工具权限
    """
    
    def __init__(self, vllm_client: VLLMClient, role_name: str, description: str):
        self.vllm_client = vllm_client
        self.role_name = role_name
        self.description = description
        self.available_tools: List[str] = []
        
    @abstractmethod
    def get_system_prompt(self) -> str:
        """返回该专家的系统提示词"""
        pass
    
    async def think(self, task: str, context: str = "") -> str:
        """
        思考并分析任务
        """
        try:
            system_prompt = self.get_system_prompt()
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"任务: {task}\n\n上下文: {context}"}
            ]
            
            response = await self.vllm_client.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
                stream=False
            )
            
            return response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
        except Exception as e:
            logger.error(f"{self.role_name} 思考失败: {e}")
            return f"思考失败: {str(e)}"
    
    async def execute_task(
        self, 
        task: str, 
        context: str = "",
        skill_manager=None
    ) -> Dict[str, Any]:
        """
        执行任务
        """
        try:
            analysis = await self.think(task, context)
            
            return {
                "success": True,
                "role": self.role_name,
                "analysis": analysis,
                "task": task
            }
            
        except Exception as e:
            logger.error(f"{self.role_name} 执行任务失败: {e}")
            return {
                "success": False,
                "role": self.role_name,
                "error": str(e)
            }


class ProductManagerAgent(BaseExpertAgent):
    """
    产品经理 - 负责需求澄清、补充细节、定义验收标准
    """
    
    def __init__(self, vllm_client: VLLMClient):
        super().__init__(
            vllm_client=vllm_client,
            role_name="Product Manager",
            description="需求澄清、用户画像分析、验收标准定义"
        )
        self.available_tools = ["web_search"]
    
    def get_system_prompt(self) -> str:
        return """你是一位经验丰富的产品经理。

你的职责：
1. 澄清模糊的需求，提出关键问题
2. 分析用户画像和使用场景
3. 定义清晰的验收标准（Acceptance Criteria）
4. 识别潜在的边界情况和异常场景
5. 确保需求的完整性和可实现性

输出格式：
- **需求分析**: 对用户需求的理解
- **关键问题**: 需要进一步澄清的问题
- **用户故事**: As a [用户], I want [功能], So that [价值]
- **验收标准**: Given/When/Then 格式的测试场景
- **边界情况**: 需要考虑的特殊情况

请用专业、清晰、结构化的方式输出。"""


class ArchitectAgent(BaseExpertAgent):
    """
    架构师 - 技术选型、数据库设计、API接口定义
    """
    
    def __init__(self, vllm_client: VLLMClient):
        super().__init__(
            vllm_client=vllm_client,
            role_name="Architect",
            description="技术选型、架构设计、数据库Schema、API定义"
        )
        self.available_tools = ["web_search", "str_replace_editor"]
    
    def get_system_prompt(self) -> str:
        return """你是一位资深软件架构师。

你的职责：
1. 技术选型和架构设计
2. 数据库Schema设计（表结构、索引、关系）
3. API接口定义（RESTful/GraphQL）
4. 系统模块划分和依赖关系
5. 性能和扩展性考虑

技术栈偏好：
- 后端: Python (FastAPI), Node.js (Express), Go
- 前端: React, Vue, TypeScript
- 数据库: PostgreSQL, Redis, MongoDB
- 部署: Docker, K8s

输出格式：
- **技术选型**: 选择的技术栈和理由
- **架构图**: 系统模块和数据流
- **数据库设计**: 表结构（SQL DDL）
- **API设计**: 端点、参数、响应格式
- **扩展性**: 如何支持未来扩展

使用Markdown和代码块，清晰专业。"""


class BackendDeveloperAgent(BaseExpertAgent):
    """
    后端开发 - 业务逻辑、SQL、服务器配置
    """
    
    def __init__(self, vllm_client: VLLMClient):
        super().__init__(
            vllm_client=vllm_client,
            role_name="Backend Developer",
            description="编写业务逻辑、数据库操作、API实现"
        )
        self.available_tools = ["str_replace_editor", "bash", "web_search"]
    
    def get_system_prompt(self) -> str:
        return """你是一位专业的后端开发工程师。

你的职责：
1. 实现业务逻辑代码
2. 编写数据库查询（SQL/ORM）
3. 实现RESTful API端点
4. 错误处理和日志记录
5. 编写单元测试

编码规范：
- 使用类型注解（Python typing, TypeScript）
- 遵循PEP 8 / Airbnb Style Guide
- 编写文档字符串
- 使用异步IO提升性能
- 参数验证和异常处理

输出格式：
- **代码实现**: 完整可运行的代码
- **测试用例**: 单元测试代码
- **依赖**: requirements.txt / package.json
- **运行说明**: 如何启动和测试

代码质量优先，注重可读性和可维护性。"""


class FrontendDeveloperAgent(BaseExpertAgent):
    """
    前端开发 - UI组件、API对接、CSS/动画
    """
    
    def __init__(self, vllm_client: VLLMClient):
        super().__init__(
            vllm_client=vllm_client,
            role_name="Frontend Developer",
            description="UI组件开发、状态管理、CSS样式"
        )
        self.available_tools = ["str_replace_editor", "web_search"]
    
    def get_system_prompt(self) -> str:
        return """你是一位资深前端开发工程师。

你的职责：
1. 实现React/Vue组件
2. 状态管理（Redux/Vuex/Context）
3. API集成（Axios/Fetch）
4. CSS样式和动画
5. 响应式设计

技术栈：
- React + TypeScript / Vue 3 + Composition API
- TailwindCSS / Styled Components
- React Query / SWR
- 现代化打包工具（Vite）

设计原则：
- 组件化、可复用
- 性能优化（懒加载、虚拟化）
- 无障碍访问（a11y）
- 优雅降级

输出格式：
- **组件代码**: 完整的.tsx/.vue文件
- **样式**: CSS/SCSS/TailwindCSS
- **状态管理**: Store/Context设计
- **集成说明**: 如何使用组件

代码应优雅、现代、高性能。"""


class QAReviewerAgent(BaseExpertAgent):
    """
    质量保证 - 代码审计、测试运行、逻辑检查
    """
    
    def __init__(self, vllm_client: VLLMClient):
        super().__init__(
            vllm_client=vllm_client,
            role_name="QA Reviewer",
            description="代码审计、自动化测试、质量保证"
        )
        self.available_tools = ["bash", "str_replace_editor", "web_search"]
    
    def get_system_prompt(self) -> str:
        return """你是一位严谨的QA工程师和代码审查专家。

你的职责：
1. 代码审计（安全、性能、规范）
2. 运行单元测试和集成测试
3. 检查逻辑漏洞和边界情况
4. 验证是否满足需求
5. 提供改进建议

审查清单：
- ✅ 代码规范（Linting）
- ✅ 类型安全（TypeScript/Mypy）
- ✅ 测试覆盖率（>80%）
- ✅ 安全漏洞（SQL注入、XSS）
- ✅ 性能问题（N+1查询、内存泄漏）
- ✅ 错误处理（异常捕获）

输出格式：
- **审查结果**: PASS / FAIL
- **发现的问题**: 按严重程度分级
  - 🔴 Critical: 阻塞性问题
  - 🟡 Warning: 需要改进
  - 🟢 Info: 建议优化
- **测试报告**: 通过/失败的测试用例
- **修复建议**: 具体的改进方案

严格、专业、建设性。"""


class TravelPlannerAgent(BaseExpertAgent):
    """
    旅行规划师 - 行程规划、比价、路线优化
    """
    
    def __init__(self, vllm_client: VLLMClient):
        super().__init__(
            vllm_client=vllm_client,
            role_name="Travel Planner",
            description="旅行行程规划、酒店/机票比价、路线优化"
        )
        self.available_tools = ["web_search", "str_replace_editor"]
    
    def get_system_prompt(self) -> str:
        return """你是一位专业的旅行规划师。

你的职责：
1. 搜索旅游信息（景点、餐厅、酒店）
2. 价格比较和预算控制
3. 路线优化（最短路径、避开拥堵）
4. 生成详细的日程安排
5. 考虑用户偏好和限制条件

规划要素：
- 预算控制（交通、住宿、餐饮、门票）
- 时间优化（避免浪费时间）
- 用户偏好（美食/历史/自然/购物）
- 限制条件（不爬山、素食、亲子友好）
- 应急备选方案

输出格式：
- **行程概览**: 天数、城市、主题
- **每日安排**: 
  - 时间: 景点名称（门票价格）
  - 交通方式和费用
  - 用餐建议
- **预算表**: 详细费用清单
- **地图**: 景点坐标（供可视化）
- **贴士**: 注意事项和最佳时间

使用Markdown表格和列表，清晰实用。"""


class ExpertAgentOrchestrator:
    """
    专家Agent编排器
    根据任务类型自动选择合适的专家
    """
    
    def __init__(self, vllm_client: VLLMClient):
        self.vllm_client = vllm_client
        
        # 初始化所有专家
        self.experts: Dict[str, BaseExpertAgent] = {
            "pm": ProductManagerAgent(vllm_client),
            "architect": ArchitectAgent(vllm_client),
            "backend": BackendDeveloperAgent(vllm_client),
            "frontend": FrontendDeveloperAgent(vllm_client),
            "qa": QAReviewerAgent(vllm_client),
            "travel": TravelPlannerAgent(vllm_client),
        }
    
    def select_expert(self, task_description: str) -> Optional[BaseExpertAgent]:
        """
        根据任务描述自动选择专家
        """
        task_lower = task_description.lower()
        
        # 旅行相关
        if any(kw in task_lower for kw in ["旅游", "旅行", "行程", "酒店", "机票", "景点"]):
            return self.experts["travel"]
        
        # 需求分析
        if any(kw in task_lower for kw in ["需求", "用户故事", "验收", "澄清"]):
            return self.experts["pm"]
        
        # 架构设计
        if any(kw in task_lower for kw in ["架构", "设计", "技术选型", "数据库", "api设计"]):
            return self.experts["architect"]
        
        # 前端开发
        if any(kw in task_lower for kw in ["前端", "ui", "界面", "页面", "组件", "react", "vue"]):
            return self.experts["frontend"]
        
        # 后端开发
        if any(kw in task_lower for kw in ["后端", "api", "接口", "数据库", "sql", "服务器"]):
            return self.experts["backend"]
        
        # 测试/审查
        if any(kw in task_lower for kw in ["测试", "审查", "检查", "质量", "bug"]):
            return self.experts["qa"]
        
        # 默认：产品经理（需求分析）
        return self.experts["pm"]
    
    async def execute_with_expert(
        self,
        task: str,
        context: str = "",
        expert_type: Optional[str] = None,
        skill_manager=None
    ) -> Dict[str, Any]:
        """
        使用专家执行任务
        """
        try:
            if expert_type and expert_type in self.experts:
                expert = self.experts[expert_type]
            else:
                expert = self.select_expert(task)
            
            logger.info(f"选择专家: {expert.role_name} 执行任务")
            
            result = await expert.execute_task(task, context, skill_manager)
            
            return {
                "success": result.get("success", False),
                "expert": expert.role_name,
                "analysis": result.get("analysis", ""),
                "error": result.get("error")
            }
            
        except Exception as e:
            logger.error(f"专家执行失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_available_experts(self) -> List[Dict[str, str]]:
        """获取所有可用专家列表"""
        return [
            {
                "key": key,
                "name": expert.role_name,
                "description": expert.description,
                "tools": expert.available_tools
            }
            for key, expert in self.experts.items()
        ]
