#!/usr/bin/env python3
"""
测试工作流可视化与后端API的集成
"""
import asyncio
import json
from pathlib import Path
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from omni_agent.agents.task_graph import TaskGraph, TaskNode, analyze_task_dependencies
from omni_agent.agents.plan_agent import PlanAgent, PlanStep, ExecutionPlan
from omni_agent.core.vllm_client import VLLMClient

def create_test_plan():
    """创建测试执行计划"""
    steps = [
        PlanStep(
            action="skill",
            skill="web_search",
            params={"query": "React组件开发最佳实践"},
            description="搜索React组件开发资料"
        ),
        PlanStep(
            action="skill", 
            skill="str_replace_editor",
            params={
                "command": "create",
                "path": "component.jsx",
                "file_text": "// React组件代码"
            },
            description="创建React组件文件"
        ),
        PlanStep(
            action="skill",
            skill="bash",
            params={"command": "npm test"},
            description="运行测试"
        ),
        PlanStep(
            action="response",
            params={},
            description="生成最终响应"
        )
    ]
    
    return ExecutionPlan(steps, "创建并测试React组件的执行计划")

def test_task_graph_generation():
    """测试DAG任务图生成"""
    print("🧪 测试DAG任务图生成...")
    
    plan = create_test_plan()
    steps_dict = [step.to_dict() for step in plan.steps]
    
    # 生成任务依赖图
    task_graph = analyze_task_dependencies(steps_dict)
    
    # 获取执行层
    layers = task_graph.get_execution_layers()
    
    print(f"✅ 生成了 {len(task_graph.tasks)} 个任务")
    print(f"✅ 执行层数: {len(layers)}")
    
    # 可视化
    visualization = task_graph.visualize()
    print("\n📊 任务图可视化:")
    print(visualization)
    
    # 导出为前端可用的格式
    dag_data = task_graph.to_dict()
    
    return dag_data

def simulate_expert_plan():
    """模拟专家Agent规划的任务"""
    print("\n🎭 模拟专家Agent任务规划...")
    
    # 模拟一个Web开发项目的任务分配
    tasks = [
        {
            "task_id": "REQ_ANALYSIS",
            "role": "Product Manager",
            "description": "分析用户需求，编写用户故事",
            "dependencies": []
        },
        {
            "task_id": "TECH_DESIGN", 
            "role": "Architect",
            "description": "技术选型和系统架构设计",
            "dependencies": ["REQ_ANALYSIS"]
        },
        {
            "task_id": "DB_SCHEMA",
            "role": "Backend Developer", 
            "description": "设计数据库Schema",
            "dependencies": ["TECH_DESIGN"]
        },
        {
            "task_id": "API_DEV",
            "role": "Backend Developer",
            "description": "开发RESTful API接口",
            "dependencies": ["DB_SCHEMA"]
        },
        {
            "task_id": "UI_COMPONENTS",
            "role": "Frontend Developer",
            "description": "开发React组件",
            "dependencies": ["TECH_DESIGN"]
        },
        {
            "task_id": "INTEGRATION",
            "role": "Frontend Developer", 
            "description": "前后端集成",
            "dependencies": ["API_DEV", "UI_COMPONENTS"]
        },
        {
            "task_id": "TESTING",
            "role": "QA Reviewer",
            "description": "功能测试和代码审查",
            "dependencies": ["INTEGRATION"]
        }
    ]
    
    # 创建TaskGraph
    graph = TaskGraph()
    
    for task_data in tasks:
        task_node = TaskNode(
            task_id=task_data["task_id"],
            action="skill",
            skill="expert_agent",
            params={"role": task_data["role"]},
            description=task_data["description"],
            dependencies=task_data["dependencies"]
        )
        graph.add_task(task_node)
    
    print(f"✅ 创建了包含 {len(tasks)} 个专家任务的工作流")
    
    # 获取并行执行组
    parallel_groups = graph.get_parallel_groups()
    print(f"✅ 生成了 {len(parallel_groups)} 个执行层")
    
    for i, group in enumerate(parallel_groups):
        task_names = [task.task_id for task in group]
        print(f"  层 {i+1}: {task_names} (并行执行)")
    
    return {
        "tasks": [
            {
                "task_id": task.task_id,
                "role": task.params.get("role", "Unknown"),
                "description": task.description,
                "dependencies": task.dependencies
            }
            for task in graph.tasks.values()
        ],
        "execution_layers": graph.get_execution_layers(),
        "visualization": graph.visualize()
    }

def generate_frontend_data():
    """生成前端测试数据"""
    print("\n🎨 生成前端测试数据...")
    
    # 测试基础计划
    basic_dag = test_task_graph_generation()
    
    # 测试专家系统
    expert_dag = simulate_expert_plan()
    
    # 生成完整的前端数据包
    frontend_data = {
        "basic_workflow": basic_dag,
        "expert_workflow": expert_dag,
        "test_scenarios": [
            {
                "name": "简单线性工作流",
                "tasks": basic_dag["tasks"]
            },
            {
                "name": "复杂并行工作流", 
                "tasks": expert_dag["tasks"]
            }
        ]
    }
    
    # 保存到文件供前端测试使用
    output_file = Path(__file__).parent / "frontend" / "test_workflow_data.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(frontend_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 测试数据已保存到: {output_file}")
    
    return frontend_data

def main():
    """主测试函数"""
    print("🚀 开始测试Workflow可视化集成\n")
    
    try:
        # 生成测试数据
        data = generate_frontend_data()
        
        print("\n" + "="*50)
        print("📋 测试总结:")
        print("="*50)
        
        basic_tasks = len(data["basic_workflow"]["tasks"])
        expert_tasks = len(data["expert_workflow"]["tasks"])
        
        print(f"✅ 基础工作流: {basic_tasks} 个任务")
        print(f"✅ 专家工作流: {expert_tasks} 个任务")
        print(f"✅ 前端测试数据已生成")
        
        print("\n🌐 可以访问以下URL测试:")
        print("   http://localhost:8080/workflow-demo.html")
        print("   http://localhost:8080/index.html")
        
        print("\n💡 测试建议:")
        print("   1. 打开浏览器访问演示页面")
        print("   2. 点击不同的工作流按钮")
        print("   3. 测试节点点击和详情面板")
        print("   4. 运行模拟执行查看状态变化")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()