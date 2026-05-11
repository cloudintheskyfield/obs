"""
Task Graph - DAG任务依赖图管理
支持并行/串行任务调度
"""
import networkx as nx
from typing import List, Dict, Any, Set, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class TaskNode:
    """任务节点"""
    task_id: str
    action: str  # 'skill' | 'response' | 'analysis'
    skill: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务ID
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "action": self.action,
            "skill": self.skill,
            "params": self.params,
            "description": self.description,
            "dependencies": self.dependencies
        }


class TaskGraph:
    """
    任务依赖图 - 使用DAG管理任务执行顺序
    支持并行和串行调度
    """
    
    def __init__(self):
        self.graph = nx.DiGraph()  # 有向无环图
        self.tasks: Dict[str, TaskNode] = {}
        
    def add_task(self, task: TaskNode) -> bool:
        """添加任务到图中"""
        try:
            # 添加节点
            self.graph.add_node(task.task_id, task=task)
            self.tasks[task.task_id] = task
            
            # 添加依赖边
            for dep_id in task.dependencies:
                if dep_id not in self.tasks:
                    logger.warning(f"依赖任务 {dep_id} 不存在，将被忽略")
                    continue
                self.graph.add_edge(dep_id, task.task_id)
            
            # 检查是否形成环
            if not nx.is_directed_acyclic_graph(self.graph):
                logger.error(f"添加任务 {task.task_id} 后形成环，回滚")
                self.graph.remove_node(task.task_id)
                del self.tasks[task.task_id]
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"添加任务失败: {e}")
            return False
    
    def get_execution_layers(self) -> List[List[str]]:
        """
        获取分层执行计划
        每一层的任务可以并行执行，层与层之间串行
        
        返回: [[task_id1, task_id2], [task_id3], ...]
        """
        if not self.graph:
            return []
        
        try:
            # 拓扑排序生成
            layers = []
            
            # 使用拓扑分代算法
            for generation in nx.topological_generations(self.graph):
                layers.append(list(generation))
            
            return layers
            
        except Exception as e:
            logger.error(f"生成执行层失败: {e}")
            return []
    
    def get_parallel_groups(self) -> List[List[TaskNode]]:
        """
        获取并行执行组
        返回可以并行执行的任务组列表
        """
        layers = self.get_execution_layers()
        
        parallel_groups = []
        for layer in layers:
            group = [self.tasks[task_id] for task_id in layer if task_id in self.tasks]
            parallel_groups.append(group)
        
        return parallel_groups
    
    def get_task_dependencies(self, task_id: str) -> List[str]:
        """获取任务的所有依赖（直接和间接）"""
        if task_id not in self.graph:
            return []
        
        try:
            # 获取所有前驱节点
            predecessors = list(nx.ancestors(self.graph, task_id))
            return predecessors
        except Exception as e:
            logger.error(f"获取依赖失败: {e}")
            return []
    
    def is_ready_to_execute(self, task_id: str, completed_tasks: Set[str]) -> bool:
        """
        检查任务是否准备好执行
        所有依赖任务都必须完成
        """
        if task_id not in self.tasks:
            return False
        
        task = self.tasks[task_id]
        
        # 检查所有直接依赖是否完成
        for dep_id in task.dependencies:
            if dep_id not in completed_tasks:
                return False
        
        return True
    
    def visualize(self) -> str:
        """
        生成任务图的文本可视化
        """
        if not self.graph:
            return "空任务图"
        
        try:
            lines = ["任务依赖图:"]
            layers = self.get_execution_layers()
            
            for i, layer in enumerate(layers):
                lines.append(f"\n层 {i+1} (并行执行):")
                for task_id in layer:
                    task = self.tasks.get(task_id)
                    if task:
                        deps = f" [依赖: {', '.join(task.dependencies)}]" if task.dependencies else ""
                        lines.append(f"  - {task_id}: {task.description}{deps}")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"可视化失败: {e}")
            return f"可视化失败: {e}"
    
    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "tasks": [task.to_dict() for task in self.tasks.values()],
            "execution_layers": self.get_execution_layers(),
            "visualization": self.visualize()
        }


def analyze_task_dependencies(steps: List[Dict[str, Any]]) -> TaskGraph:
    """
    分析任务步骤的依赖关系
    自动检测哪些任务可以并行，哪些需要串行
    """
    graph = TaskGraph()
    
    for i, step_data in enumerate(steps):
        task_id = f"task_{i+1}"
        
        # 创建任务节点
        task = TaskNode(
            task_id=task_id,
            action=step_data.get("action", "response"),
            skill=step_data.get("skill"),
            params=step_data.get("params", {}),
            description=step_data.get("description", f"任务 {i+1}"),
            dependencies=[]
        )
        
        # 分析依赖关系
        if i > 0:
            # 规则1: 如果当前任务需要前一个任务的结果，则依赖
            if _requires_previous_result(step_data, steps[i-1]):
                task.dependencies.append(f"task_{i}")
            
            # 规则2: 如果是文件编辑操作，且前面有文件创建，需要依赖
            if step_data.get("action") == "skill" and step_data.get("skill") == "str_replace_editor":
                if steps[i-1].get("skill") == "str_replace_editor":
                    task.dependencies.append(f"task_{i}")
            
            # 规则3: 如果是代码执行，需要依赖代码生成
            if step_data.get("action") == "skill" and step_data.get("skill") == "bash":
                # 检查前面是否有代码生成任务
                for j in range(i):
                    if steps[j].get("skill") == "str_replace_editor":
                        task.dependencies.append(f"task_{j+1}")
                        break
        
        graph.add_task(task)
    
    return graph


def _requires_previous_result(current_step: Dict[str, Any], previous_step: Dict[str, Any]) -> bool:
    """
    判断当前步骤是否需要前一步骤的结果
    """
    # 简单规则：如果是response或analysis类型，通常需要前置结果
    if current_step.get("action") in ["response", "analysis"]:
        return True
    
    # 如果当前步骤的参数中引用了上一步
    current_params = current_step.get("params", {})
    if any("previous" in str(v).lower() or "result" in str(v).lower() 
           for v in current_params.values() if isinstance(v, str)):
        return True
    
    return False
