<p align="center">
  <img src="assets/obs-code-logo.svg" alt="OBS Code logo" width="120" />
</p>

# OBS Code

把一个会聊天的 Agent，升级成一个真正能干活的工作台。

OBS Code 是一套面向真实任务的本地 AI 控制台。它不是单纯的聊天框，而是把会话、工具调用、工作区、日志、上下文压缩、架构可视化和桌面壳整合到同一套界面里，让 Agent 能在真实项目目录中读文件、改代码、跑命令、调用搜索和浏览器能力，并把运行过程完整落盘。

## 当前版本能做什么

- 在指定工作区内执行真实任务：读写文件、运行终端命令、调用 Python / 沙箱、搜索实时信息、控制浏览器。
- 在同一套 UI 里切换 `Agent / Plan / Battle / Review` 四种模式。
- 用 `Skills` 面板约束模型能力，只开放当前需要的工具。
- 用 `Logs` 查看完整 LLM request / response、工具执行和运行阶段。
- 用 `Architecture` 查看当前运行时对应的真实代码链路和数据流。
- 自动保存会话、UI 状态、线程工作区、上下文压缩结果和 LLM trace。
- 既支持浏览器版，也支持复用同一套前后端的 macOS / Windows 桌面版打包产物。

## 核心体验

- `Workspace`
  为每个线程绑定当前项目目录，Agent 的文件与命令执行都围绕这个目录展开。
- `Skills`
  按需勾选工具，把 schema 暴露控制在最小范围内，减少上下文膨胀。
- `Thinking`
  查看工具执行轨迹、中间过程和压缩提示，并支持折叠历史过程。
- `Context`
  同时展示当前 thread 的累计上下文和本轮真正送入模型的 working set。
- `Logs`
  落地完整会话与推理日志，方便排查“模型慢”“工具失败”“上下文跑偏”等问题。
- `Architecture`
  用流程图/数据流方式展示当前请求从 UI 到 FastAPI、Agent Loop、Skill 执行再到 SSE 输出的完整链路。

## 运行界面

当前版本的控制台已经是完整工作台形态：左侧线程栏，中间主会话区，上方模式切换与上下文计量，底部统一输入区，以及 `Workspace / Logs / Skills / Architecture` 四个抽屉入口。

![OBS Code Runtime Screenshot](screenshots/chat-ui-20260410.png)

> 说明：仓库里当前可直接引用的运行截图仍使用 `screenshots/chat-ui-20260410.png`。如果你把最新截图文件放进 `screenshots/`，README 可以继续切到那张图。

## 快速开始

### 1. 本地 Web 控制台

```bash
cd /Users/wangshuang/PycharmProjects/obs/obs
docker-compose up -d omni-agent
```

启动后访问：

- Web 控制台：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`

### 2. 启动完整依赖

```bash
docker-compose up -d
```

### 3. macOS 桌面版

调试运行：

```bash
cd /Users/wangshuang/PycharmProjects/obs/obs
chmod +x scripts/run_macos_desktop.sh
./scripts/run_macos_desktop.sh
```

构建 `.app` 与 `.dmg`：

```bash
cd /Users/wangshuang/PycharmProjects/obs/obs
chmod +x scripts/build_macos_app.sh
./scripts/build_macos_app.sh
```

生成物位置：

- `dist/OBS Code.app`
- `dist/OBS-Code-<timestamp>.dmg`

### 4. Windows 桌面版

调试运行：

```powershell
cd C:\Users\wangshuang\PycharmProjects\obs\obs
.\scripts\run_windows_desktop.ps1
```

也可以直接双击：

- `scripts\run_windows_desktop.cmd`

构建 Windows 桌面应用目录与压缩包：

```powershell
cd C:\Users\wangshuang\PycharmProjects\obs\obs
.\scripts\build_windows_app.ps1
```

> Windows `.exe` 需要在 Windows 机器上执行打包脚本生成，仓库里提供的是完整打包脚本与图标链路。

Windows 打包前建议先准备：

```powershell
python -m pip install pyinstaller pywebview pillow pythonnet
```

也可以直接双击：

- `scripts\build_windows_app.cmd`

生成物位置：

- `dist\OBS Code\`
- `dist\OBS-Code-<timestamp>-windows.zip`

## 上手示例

你可以直接在控制台里输入：

- `列出当前目录文件`
- `读取 README.md 并总结这个项目`
- `打开 https://example.com 并告诉我标题`
- `北京现在天气怎么样`
- `今日热点新闻`
- `使用 python 画一个折线图`

如果你希望模型只在有限能力内工作，可以先打开 `Skills` 抽屉，只保留：

- `Terminal`
- `File`
- `Python`
- `Web Search`

## 模式说明

### Agent

默认模式。模型可以直接选择并执行当前已开放的工具，适合“帮我做事”。

### Plan

只生成执行计划，不实际运行工具，适合先拆任务、再决定是否执行。

### Battle

并行生成多路回答并进行比较，适合需要对比不同策略或不同工具参与程度的场景。

### Review

更偏结构化审查和检查流程，适合代码审核、方案审阅和结果复核。

## 当前项目结构

```text
obs/
├── src/omni_agent/
│   ├── api.py                    # FastAPI + SSE 入口
│   ├── agents/
│   │   ├── streaming_agent.py    # 主 Agent Loop / 模式路由 / 快路径 / 压缩逻辑
│   │   ├── execution_engine.py   # review / 执行引擎
│   │   └── web_agent.py          # 浏览器/网页相关能力
│   ├── services/
│   │   ├── session_store.py      # 会话、trace、UI 状态、本地持久化
│   │   └── request_lifecycle.py  # 请求生命周期整理
│   └── desktop_app.py            # 复用同一套 Web UI 的原生桌面壳（macOS / Windows）
├── ui/src/
│   ├── App.jsx
│   └── components/
│       ├── RuntimePills.jsx
│       ├── TranscriptView.jsx
│       ├── LogsDrawer.jsx
│       ├── SkillsDrawer.jsx
│       └── ArchitectureDrawer.jsx
├── screenshots/                  # README 与文档截图
├── scripts/
│   ├── run_macos_desktop.sh
│   ├── build_macos_app.sh
│   ├── run_windows_desktop.ps1
│   ├── run_windows_desktop.cmd
│   ├── build_windows_app.ps1
│   ├── build_windows_app.cmd
│   └── generate_desktop_icons.py
└── tests/
```

## 数据和持久化

所有关键运行数据都保存在本地，便于排查、恢复和长期使用：

- 会话历史：`logs/chat_sessions`
- 上下文压缩缓存：`logs/context_cache`
- LLM 输入输出日志：`logs/llm_traces`
- UI 会话快照：`logs/ui_sessions`
- 线程工作目录：`logs/thread_workspaces`
- 当前工作区状态：`logs/workspace_state.json`

## 上下文策略

当前版本的上下文管理遵循这套策略：

- 当前 thread 的总量会持续累计并显示在顶部 `Context` 区。
- 每轮真正送入模型的是独立的 `working set`。
- 最近 `10` 轮对话保留原文。
- 更早历史只在超过阈值时进入压缩摘要。
- 压缩过程会在 UI 中给出独立提示，并保留压缩后的缓存。

这套设计的目标是兼顾三件事：

- 长会话下的可持续使用
- 工具调用时的上下文稳定性
- 模型响应速度与推理质量的平衡

## 已经落地的真实能力

- `terminal`：列目录、执行命令、读项目文件
- `file-operations`：查看和修改文本文件
- `weather`：查询实时天气
- `web-search`：热点新闻、实时搜索、信息汇总
- `code-sandbox`：隔离执行代码
- `computer-use`：打开页面、截图、识别界面
- `workspace`：切换工作区并在新目录继续任务
- `context compaction`：长会话自动压缩并继续回答
- `image paste`：粘贴图片后保留预览和上下文
- `battle`：直接回答与工具辅助回答的真实对战
- `architecture`：根据当前运行态渲染真实流程图与数据流图
- `desktop`：macOS / Windows 桌面壳加载同一套 FastAPI + Web UI

## 架构总览

OBS Code 的核心设计是把“模型推理”和“本地执行”拆开，再用一条稳定的 Harness 把它们串起来：

```text
Web UI / macOS Desktop / Windows Desktop
    ↓
FastAPI /chat/stream
    ↓
SessionStore 恢复会话、UI 状态、工作区、context cache
    ↓
StreamingAgent.chat_stream()
    ├── agent   -> 原生工具调用循环
    ├── plan    -> 只生成计划
    ├── battle  -> 多路结果对比
    └── review  -> 审查/执行引擎
    ↓
SkillManager / Tool Runtime
    ↓
SSE 推流到前端 Transcript / Logs / Thinking
    ↓
SessionStore 持久化 traces / sessions / compacted context
```

如果你想看更细的运行链路，可以直接在应用里打开 `Architecture` 抽屉。

## 测试与验证

常用验证命令：

```bash
cd /Users/wangshuang/PycharmProjects/obs/obs
pytest -q tests
npm --prefix ui run build
```

如果需要构建桌面版：

```bash
cd /Users/wangshuang/PycharmProjects/obs/obs
bash scripts/build_macos_app.sh
```

Windows 打包：

```powershell
cd C:\Users\wangshuang\PycharmProjects\obs\obs
.\scripts\build_windows_app.ps1
```

## Learn Claude Code

本项目仍保留了 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的结构和教学内容，可作为 Agent Harness / Skills 设计学习材料：

- `agents/`：多阶段课程代码
- `docs/zh/`：中文教程
- `skills/`：技能说明和工具样例

## 说明

这份 README 现在更偏“当前版本使用说明”和“真实能力总览”。如果你要继续补充：

- 最新运行截图
- 更细的 Architecture 图示
- 桌面版安装说明
- 对外发布文案

可以继续在这个基础上扩展。
