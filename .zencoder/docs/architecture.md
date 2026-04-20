# OBS Code — 架构设计

> 参考 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) Harness Engineering 核心设计，映射并扩展为 OBS Code 的功能流程。

---

## 核心理念

> Agency comes from the model. The harness makes agency real.

```
OBS Code Harness = Agent Loop
                 + Tools (bash, file, web, computer, code-sandbox)
                 + On-demand Skills (3-level SKILL.md)
                 + Context Compaction
                 + Session Persistence
                 + Workspace Isolation
                 + Mode-aware Routing (agent / plan / review / battle)
                 + Expert Agent Orchestration
                 + DAG Task Graph
                 + Web UI + macOS Desktop
```

模型是司机，Harness 是车。OBS Code 的全部工程工作都在造车，不在造司机。

---

## 功能流程总览

```
┌─────────────────────────────────────────────────────────────┐
│                    用户输入层                                  │
│   Web UI (chat + skills + workspace + logs 抽屉)             │
│   macOS Desktop App (PyInstaller 打包)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP / SSE streaming
┌──────────────────────▼──────────────────────────────────────┐
│                  FastAPI API 层                               │
│   POST /chat/stream   GET /skills   POST /execute            │
│   GET /experts        POST /expert/execute                   │
│   GET /workspace      POST /workspace                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│               StreamingAgent (核心 Agent Loop)                │
│                                                              │
│   while True:                                                │
│       response = vllm_client.chat(messages, tools)           │
│       if stop_reason != "tool_use": break                    │
│       results = dispatch_tools(response.tool_calls)          │
│       messages.append(tool_results)                          │
│       yield SSE chunks → 前端实时渲染                          │
│                                                              │
│   Mode Router:                                               │
│   ├── agent  → 原生工具调用循环（默认）                          │
│   ├── plan   → PlanAgent → TaskGraph → yield DAG only        │
│   ├── review → ExecutionEngine 结构化执行转录                   │
│   └── battle → 直接回答 vs 工具辅助回答 → LLM 裁判               │
└──────────────────────┬──────────────────────────────────────┘
                       │
         ┌─────────────┴──────────────┐
         │                            │
┌────────▼────────┐         ┌─────────▼──────────────────────┐
│  SkillManager   │         │  PlanAgent + ExecutionEngine   │
│  (工具分发)       │         │  (计划 → DAG → 并行执行)         │
│                 │         │                                │
│  bash           │         │  1. 分析用户请求                 │
│  str_replace_   │         │  2. LLM 生成 ExecutionPlan      │
│    editor       │         │  3. analyze_task_dependencies   │
│  web_search     │         │     → NetworkX DAG             │
│  computer       │         │  4. topological_generations    │
│  code_sandbox   │         │     → 分层并行调度               │
│  weather        │         │  5. asyncio.gather 并行执行      │
│  pdf / custom   │         │  6. 自愈重试（最多5次 + LLM修复）   │
└────────┬────────┘         └─────────┬──────────────────────┘
         │                            │
┌────────▼────────────────────────────▼──────────────────────┐
│              3-Level Skill System (技能三级架构)               │
│                                                            │
│  Level 1: 元数据 (始终加载)                                   │
│    .claude/skills/<name>/SKILL.md — YAML front-matter      │
│    name / description / trigger keywords                   │
│                                                            │
│  Level 2: 指令 (触发时注入 system prompt)                     │
│    SKILL.md 正文 — Quick Start / Workflows / Best Practices │
│                                                            │
│  Level 3: 实现 (按需执行)                                    │
│    *.py — class XxxSkill(BaseSkill): async def execute()   │
└────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│                 Context Compaction (上下文压缩)               │
│                                                            │
│  Layer 1: Sliding Window — 保留最近 N 轮原始消息               │
│  Layer 2: Checkpoint   — 关键里程碑摘要持久化到磁盘             │
│  Layer 3: Summary      — LLM 压缩超出窗口的历史为 1 条摘要      │
│                                                            │
│  触发条件: token_count > context_window_threshold           │
│  存储路径: logs/context_cache/<session_id>/                  │
└────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────────┐
│                  Session Persistence (会话持久化)             │
│                                                            │
│  logs/chat_sessions/<session_id>.json    — 完整对话历史       │
│  logs/llm_traces/<session_id>/           — LLM 请求/响应日志  │
│  logs/context_cache/<session_id>/        — 压缩摘要缓存       │
│  logs/workspace_state.json               — 当前工作区状态     │
│                                                            │
│  (规划中) PostgreSQL — 跨进程会话持久化                         │
│  (规划中) Redis       — 高频状态缓存                           │
└────────────────────────────────────────────────────────────┘
```

---

## learn-claude-code → OBS Code 映射

| learn-claude-code Session | 核心机制 | OBS Code 对应实现 |
|---|---|---|
| **s01** Agent Loop | `while + stop_reason` | `StreamingAgent` 核心循环，SSE 实时推流 |
| **s02** Tool Use | `dispatch map: name→handler` | `SkillManager.dispatch()` |
| **s03** TodoWrite | Plan-first execution | `PlanAgent.create_plan()` → `ExecutionPlan` |
| **s04** Subagents | 独立 messages[] 隔离上下文 | `ExpertAgentOrchestrator` — 每个专家 Agent 独立上下文 |
| **s05** Skills | On-demand SKILL.md 注入 | 3-Level Skill System — Level 1/2 按需加载 |
| **s06** Context Compact | 3层压缩策略 | `session_context_cache` + `logs/context_cache/` |
| **s07** Task System | 文件化 DAG + 依赖图 | `TaskGraph` (NetworkX) + `analyze_task_dependencies()` |
| **s08** Background Tasks | daemon threads + 通知队列 | `asyncio.gather()` 并行执行层 |
| **s09** Agent Teams | 持久队友 + JSONL 信箱 | `ExpertAgentOrchestrator` 六大专家 + 任务路由 |
| **s10** Team Protocols | Request-Response FSM | `plan_approval` / `review` 模式执行协议 |
| **s11** Autonomous Agents | 自主认领任务 | `ExecutionEngine` 自愈重试 + 错误 LLM 修复 |
| **s12** Worktree Isolation | 每任务独立目录 | Workspace 切换 + Code Sandbox Docker 隔离 |

---

## Expert Agent 系统

六大专家 Agent 按任务类型智能路由，每个专家有独立 system prompt 和工具子集：

```
用户任务
    ↓
ExpertAgentOrchestrator.select_expert(task)
    ↓
关键词路由（旅游/前端/后端/架构/测试/产品）
    ↓
┌─────────────────────────────────────────────────────┐
│  ProductManagerAgent  → web_search                  │
│  ArchitectAgent       → web_search, str_replace_editor│
│  BackendDeveloperAgent→ str_replace_editor, bash, web│
│  FrontendDeveloperAgent→ str_replace_editor, web     │
│  QAReviewerAgent      → bash, str_replace_editor, web│
│  TravelPlannerAgent   → web_search, str_replace_editor│
└─────────────────────────────────────────────────────┘
    ↓
独立 agent loop → 结果聚合 → 返回给主 StreamingAgent
```

---

## DAG 任务图执行流程

```
PlanAgent.create_plan(user_message)
    ↓
ExecutionPlan { steps: [PlanStep, ...] }
    ↓
analyze_task_dependencies(steps)
    → NetworkX DiGraph
    → 环检测
    → 拓扑排序
    ↓
get_execution_layers()
    → Layer 0: [独立任务, ...]     ← asyncio.gather 并行
    → Layer 1: [依赖L0的任务, ...] ← 等待L0完成后并行
    → Layer N: ...
    ↓
_execute_single_task_with_retry(task, context)
    ├── 执行成功 → 结果写入 shared context
    └── 执行失败 → _analyze_and_fix_error(task, error)
                    → LLM 生成修复后的 step
                    → 重试（最多5次，指数退避）
```

---

## 执行模式路由

```
POST /chat/stream  { mode: "agent" | "plan" | "review" | "battle" }
    ↓
StreamingAgent.run(mode=...)
    │
    ├── mode="agent"   → 原生 tool-calling 循环
    │                    适合: 日常对话、单步工具调用
    │
    ├── mode="plan"    → PlanAgent → TaskGraph → 返回 DAG JSON
    │                    适合: 任务拆解预览，Human-in-the-loop 确认
    │
    ├── mode="review"  → ExecutionEngine 逐步执行 + 结构化日志
    │                    适合: 复杂多步骤任务，需要可观测性
    │
    └── mode="battle"  → 直接回答 vs 工具辅助回答
                         → LLM 裁判评分
                         适合: 评估工具调用收益
```

---

## 目录结构

```
obs/
├── src/omni_agent/
│   ├── api.py                    # FastAPI 应用 + 路由
│   ├── main.py                   # 启动入口
│   ├── desktop_app.py            # macOS 原生桌面封装
│   ├── core/
│   │   ├── agent.py              # OmniAgent 主调度器
│   │   ├── vllm_client.py        # LLM 客户端（MiniMax/自定义 VLLM）
│   │   └── logger.py             # 日志系统
│   ├── agents/
│   │   ├── streaming_agent.py    # 核心 Agent Loop（2300+ 行）
│   │   ├── plan_agent.py         # 计划生成
│   │   ├── execution_engine.py   # DAG 并行执行 + 自愈
│   │   ├── task_graph.py         # NetworkX DAG 管理
│   │   ├── expert_agents.py      # 六大专家 Agent
│   │   └── web_agent.py          # Web 访问能力
│   └── config/config.py          # 配置加载（env + yaml）
│
├── .claude/skills/               # 技能三级架构
│   ├── computer-use/             # 计算机视觉操作
│   ├── file-operations/          # 文件读写编辑
│   ├── terminal/                 # 终端执行
│   ├── code-sandbox/             # Docker 隔离执行
│   ├── web-search/               # 实时搜索
│   └── weather/                  # 天气查询
│
├── frontend/                     # 原生 JS 前端（生产构建）
│   ├── index.html
│   ├── app.js                    # 会话管理 + 工具调用渲染
│   └── styles.css
│
├── ui/                           # Vite + 现代前端开发环境
│
├── agents/                       # learn-claude-code 教学实现（s01-s12）
│
├── logs/                         # 本地持久化数据
│   ├── chat_sessions/
│   ├── llm_traces/
│   ├── context_cache/
│   └── workspace_state.json
│
└── docker-compose.yml            # omni-agent + postgres + redis
```

---

## 技术栈

| 层次 | 技术选型 |
|---|---|
| **LLM 后端** | MiniMax M2 (200K context) / 自定义 VLLM endpoint |
| **API 框架** | FastAPI + SSE streaming |
| **Agent 循环** | asyncio + 原生 tool-calling |
| **任务图** | NetworkX (DAG + 拓扑排序) |
| **代码沙箱** | Docker (--network none, --memory 256m) |
| **前端** | 原生 JS + Vite (开发) |
| **桌面** | PyInstaller → macOS .app + .dmg |
| **持久化** | 文件系统 (当前) / PostgreSQL + Redis (规划中) |
| **部署** | Docker Compose / 本地 uvicorn |

---

## 下一步演进方向

按 learn-claude-code 的 harness 完备性标准，OBS Code 还缺失：

1. **Human-in-the-loop** — `plan` 模式生成 DAG 后需前端确认再执行（s10 team protocols）
2. **PostgreSQL 会话持久化** — 替换内存存储，支持多进程 / 重启恢复
3. **Artifacts 面板** — Monaco Editor + iframe 预览 + Mermaid DAG 实时渲染
4. **Autonomous heartbeat** — 定时扫描待完成任务，自主认领执行（s11 pattern）
5. **Worktree 隔离** — 为并行 Expert Agent 任务分配独立工作目录（s12 pattern）
6. **MCP 协议** — 将技能暴露为标准 MCP tools，对接外部 Agent 生态
