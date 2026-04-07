# Workflow Visualization 工作流可视化

基于React Flow的DAG任务依赖图可视化组件，支持实时状态更新和交互式节点探索。

## 🎯 功能特性

### 核心功能
- **DAG可视化**: 基于React Flow的有向无环图展示
- **自动布局**: 使用Dagre算法智能排列节点
- **实时状态**: WebSocket实时更新任务执行状态
- **节点交互**: 点击节点查看详情信息
- **状态动画**: 丰富的视觉状态指示和过渡动画

### 支持的节点状态
- 🔵 **Pending** (等待中): 灰色/半透明，沙漏图标
- 🟦 **Running** (执行中): 蓝色渐变，旋转Spinner，流动动画
- 🟢 **Success** (完成): 绿色，对勾图标
- 🔴 **Failed** (失败): 红色，错误图标

### 角色图标映射
- 👔 **Product Manager**: 用户角色图标
- 📐 **Architect**: 绘图工具图标
- 🖥️ **Backend Developer**: 服务器图标
- 🎨 **Frontend Developer**: 画笔图标
- 🔍 **QA Reviewer**: 搜索图标
- 🗺️ **Travel Planner**: 地图图标

## 📁 文件结构

```
frontend/
├── index.html                 # 主应用页面
├── workflow-demo.html          # 独立演示页面
├── app.js                     # 主应用逻辑
├── styles.css                 # 样式文件（包含工作流样式）
└── test_workflow_data.json    # 测试数据

src/omni_agent/agents/
├── task_graph.py              # DAG任务图管理
├── execution_engine.py        # 执行引擎（集成可视化）
└── plan_agent.py              # 计划代理（集成专家选择）
```

## 🚀 快速开始

### 1. 启动演示

```bash
# 启动前端服务器
cd frontend/
python -m http.server 8080

# 访问演示页面
open http://localhost:8080/workflow-demo.html
```

### 2. 集成到主应用

工作流可视化已集成到主应用中，当执行计划生成时会自动显示：

```bash
# 启动完整应用
docker compose up -d

# 访问主应用
open http://localhost:8000
```

## 💻 API集成

### 前端JavaScript集成

```javascript
// 创建工作流可视化实例
const workflowViz = new WorkflowVisualization();

// 更新DAG数据
workflowViz.updateFromDAG({
  tasks: [
    {
      task_id: "T1",
      role: "Product Manager", 
      description: "需求分析",
      dependencies: []
    },
    {
      task_id: "T2",
      role: "Architect",
      description: "架构设计", 
      dependencies: ["T1"]
    }
  ]
});

// 更新任务状态
workflowViz.updateTaskStatus("T1", "running");
workflowViz.updateTaskStatus("T1", "success");
```

### 后端Python集成

```python
from omni_agent.agents.task_graph import analyze_task_dependencies

# 从执行计划生成DAG
steps_dict = [step.to_dict() for step in plan.steps]
task_graph = analyze_task_dependencies(steps_dict)

# 导出给前端
dag_data = task_graph.to_dict()
```

## 🎨 界面组件

### 工作流面板
- **标题栏**: 显示"执行状态"和控制按钮
- **控制按钮**:
  - 🔄 自动布局
  - 🔍 适应视图  
  - ⬆️/⬇️ 展开/收起面板

### 节点详情面板
- **基本信息**: 任务ID、状态、角色
- **任务描述**: 详细的任务说明
- **依赖关系**: 显示前置任务列表
- **执行详情**: 运行时的详细信息（可选）

### 视觉设计
- **毛玻璃效果**: `backdrop-filter: blur(20px)`
- **渐变边框**: 动态颜色主题支持
- **流畅动画**: 状态变化的平滑过渡
- **响应式布局**: 适配不同屏幕尺寸

## 🔧 技术实现

### 依赖库
- **React 18**: UI框架
- **ReactFlow 11.10**: 流程图组件库
- **Dagre 0.8.5**: 图布局算法
- **Font Awesome 6**: 图标库

### 核心类

#### WorkflowVisualization
- `updateFromDAG(dagData)`: 更新工作流数据
- `updateTaskStatus(taskId, status)`: 更新任务状态
- `autoLayout()`: 执行自动布局
- `showNodeDetails(node)`: 显示节点详情

#### TaskGraph (后端)
- `analyze_task_dependencies(steps)`: 分析任务依赖
- `get_execution_layers()`: 获取并行执行层
- `visualize()`: 生成文本可视化

## 📊 测试和验证

### 运行测试
```bash
# 运行集成测试
python test_workflow_integration.py

# 生成测试数据
# 文件: frontend/test_workflow_data.json
```

### 测试场景
1. **简单线性工作流**: 4个串行任务
2. **复杂并行工作流**: 7个任务，6层执行
3. **实时状态更新**: 模拟执行过程
4. **节点交互**: 点击查看详情

### 性能指标
- **初始化时间**: < 500ms
- **状态更新延迟**: < 100ms  
- **布局计算**: < 200ms (100个节点内)
- **动画流畅度**: 60fps

## 🔮 未来计划

### 短期优化 (1-2周)
- [ ] 添加缩放和平移控制
- [ ] 支持节点拖拽重排
- [ ] 增加更多状态类型
- [ ] 优化移动端体验

### 长期规划 (1-3个月)  
- [ ] 支持子任务展开/折叠
- [ ] 添加时间轴视图
- [ ] 集成性能监控
- [ ] 支持工作流模板保存

### 高级功能
- [ ] 实时协作编辑
- [ ] 工作流版本管理
- [ ] 数据流可视化
- [ ] AI驱动的布局优化

## 📝 使用示例

### 示例1: 基础集成

```html
<!DOCTYPE html>
<html>
<head>
    <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/reactflow@11.10.1/dist/umd/index.js"></script>
    <script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div id="workflow-graph"></div>
    <script src="app.js"></script>
    <script>
        const workflowViz = new WorkflowVisualization();
        
        // 加载示例工作流
        workflowViz.updateFromDAG({
            tasks: [
                {
                    task_id: "START",
                    role: "Product Manager",
                    description: "项目启动",
                    dependencies: []
                }
            ]
        });
    </script>
</body>
</html>
```

### 示例2: 状态更新

```javascript
// 模拟任务执行流程
async function simulateWorkflow() {
    const tasks = ["T1", "T2", "T3"];
    
    for (const taskId of tasks) {
        // 开始执行
        workflowViz.updateTaskStatus(taskId, "running");
        await sleep(2000);
        
        // 完成任务
        const success = Math.random() > 0.2;
        workflowViz.updateTaskStatus(taskId, success ? "success" : "failed");
        await sleep(500);
    }
}
```

## 🐛 问题排查

### 常见问题

1. **React Flow未加载**
   - 确认CDN链接正确
   - 检查网络连接
   - 使用本地文件备份

2. **节点不显示**  
   - 检查数据格式是否正确
   - 验证task_id唯一性
   - 确认依赖关系有效

3. **布局异常**
   - 重新执行autoLayout()
   - 检查Dagre库加载
   - 验证节点尺寸设置

4. **状态更新失效**
   - 确认taskId匹配
   - 检查updateReactFlow()调用
   - 验证React组件状态

### 调试工具

```javascript
// 调试工作流状态
console.log("Nodes:", workflowViz.nodes);
console.log("Edges:", workflowViz.edges); 
console.log("Task States:", workflowViz.taskStates);

// 强制重新渲染
workflowViz.updateReactFlow();

// 检查React Flow实例
console.log("ReactFlow Instance:", workflowViz.reactFlowInstance);
```

---

**开发者**: Omni Agent Team  
**版本**: 1.0.0  
**最后更新**: 2026-02-15

更多技术文档请参考 [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)