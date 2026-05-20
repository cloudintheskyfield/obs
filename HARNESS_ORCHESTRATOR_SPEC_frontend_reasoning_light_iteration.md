# Iteration Update: Light Mode Contrast / Readability Fix

> 本节是一个**迭代版本修改说明**，应放在 `HARNESS_ORCHESTRATOR_SPEC.md` 的最开头。目标是修复 OBS Code 在亮色模式下“文字发灰、边界不明显、状态不突出、卡片层级弱”的问题，让前端在 light mode 下也有接近 Codex / Claude Code 的清晰层级和可读性。

---

## 0.0.0.1 当前问题

当前亮色模式存在以下视觉问题：

1. 文本颜色偏灰，正文、说明文字、时间戳、状态标签不够清晰。
2. 卡片边界太浅，Timeline item、IssueCard、Composer 和 Sidebar card 融在一起。
3. 状态色不明显，成功、运行中、警告、阻塞之间区分弱。
4. 主区域大面积白色，缺少内容层级。
5. 输入框、按钮、Tab、Debug 面板的边界不够强。
6. 左侧 Thread card 的选中态不明显。
7. 代码块、inline code、日志文本在亮色背景下对比度不足。
8. 滚动条、分隔线、hover 态太淡，用户很难判断可交互区域。

目标不是把亮色模式做得很“花”，而是建立一套稳定的视觉 token，让所有状态、文字、边界、卡片都有明确层级。

---

## 0.0.0.2 Light Mode 设计原则

### Principle 1：不要使用过浅灰字

亮色模式下，普通正文至少使用：

```css
--text-primary: #111827;
--text-secondary: #374151;
--text-muted: #6b7280;
```

避免使用：

```css
#9ca3af
#d1d5db
rgba(0,0,0,0.35)
```

作为正文或关键状态文字。

---

### Principle 2：背景必须分层

推荐背景层级：

```css
--bg-app: #f6f7f9;
--bg-sidebar: #ffffff;
--bg-main: #f8fafc;
--bg-card: #ffffff;
--bg-subtle: #f3f4f6;
--bg-hover: #eef2f7;
```

不要让整个页面都是纯白，否则 Timeline、卡片和输入区会没有空间层次。

---

### Principle 3：边框必须可见但不刺眼

推荐：

```css
--border-subtle: #e5e7eb;
--border-default: #d1d5db;
--border-strong: #9ca3af;
```

用法：

- 普通卡片：`1px solid var(--border-subtle)`
- 当前步骤卡片：`1px solid var(--border-default)`
- Issue / Blocked 卡片：使用状态色边框
- Composer：使用 `border-default`，focus 时使用 accent 色

---

## 0.0.0.3 推荐 Light Theme Tokens

前端应统一定义一套 light theme token，而不是在组件里散写颜色。

```css
:root[data-theme="light"] {
  /* Background */
  --bg-app: #f6f7f9;
  --bg-sidebar: #ffffff;
  --bg-main: #f8fafc;
  --bg-card: #ffffff;
  --bg-card-muted: #f3f4f6;
  --bg-hover: #eef2f7;
  --bg-active: #e8f0ff;

  /* Text */
  --text-primary: #111827;
  --text-secondary: #374151;
  --text-muted: #6b7280;
  --text-disabled: #9ca3af;
  --text-inverse: #ffffff;

  /* Border */
  --border-subtle: #e5e7eb;
  --border-default: #d1d5db;
  --border-strong: #9ca3af;

  /* Accent */
  --accent: #2563eb;
  --accent-hover: #1d4ed8;
  --accent-soft: #dbeafe;
  --accent-border: #93c5fd;

  /* Status */
  --success: #16a34a;
  --success-soft: #dcfce7;
  --success-border: #86efac;

  --warning: #d97706;
  --warning-soft: #fef3c7;
  --warning-border: #fbbf24;

  --error: #dc2626;
  --error-soft: #fee2e2;
  --error-border: #fca5a5;

  --blocked: #c2410c;
  --blocked-soft: #ffedd5;
  --blocked-border: #fdba74;

  --running: #7c3aed;
  --running-soft: #ede9fe;
  --running-border: #c4b5fd;

  /* Code / Logs */
  --code-bg: #f3f4f6;
  --code-text: #111827;
  --code-border: #d1d5db;

  /* Shadow */
  --shadow-card: 0 1px 2px rgba(16, 24, 40, 0.06), 0 1px 3px rgba(16, 24, 40, 0.08);
  --shadow-floating: 0 8px 24px rgba(16, 24, 40, 0.12);
}
```

---

## 0.0.0.4 Text Contrast Rules

### 正文

```css
body {
  color: var(--text-primary);
  background: var(--bg-app);
}
```

### 次级说明

```css
.secondary-text {
  color: var(--text-secondary);
}
```

### 弱说明 / 时间戳

```css
.muted-text {
  color: var(--text-muted);
}
```

时间戳、Agent 标签、细节说明可以使用 `text-muted`，但不要低于这个对比度。

---

## 0.0.0.5 Timeline Light Mode 样式

Timeline 是主工作流区域，必须清晰。

推荐结构：

```text
[icon]  Title                         time / agent
        Summary
        Optional details
```

推荐样式：

```css
.timeline-item {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  box-shadow: var(--shadow-card);
}

.timeline-item:hover {
  background: var(--bg-hover);
  border-color: var(--border-default);
}

.timeline-item.current {
  border-color: var(--accent-border);
  background: var(--accent-soft);
}
```

状态左边线：

```css
.timeline-item.success { border-left: 4px solid var(--success); }
.timeline-item.running { border-left: 4px solid var(--running); }
.timeline-item.warning { border-left: 4px solid var(--warning); }
.timeline-item.error { border-left: 4px solid var(--error); }
.timeline-item.blocked { border-left: 4px solid var(--blocked); }
```

---

## 0.0.0.6 IssueCard Light Mode 样式

IssueCard 不能只是淡粉色背景，要让问题足够明显。

```css
.issue-card.warning {
  background: var(--warning-soft);
  border: 1px solid var(--warning-border);
  border-left: 4px solid var(--warning);
  color: var(--text-primary);
}

.issue-card.error {
  background: var(--error-soft);
  border: 1px solid var(--error-border);
  border-left: 4px solid var(--error);
  color: var(--text-primary);
}

.issue-card.blocked {
  background: var(--blocked-soft);
  border: 1px solid var(--blocked-border);
  border-left: 4px solid var(--blocked);
  color: var(--text-primary);
}
```

IssueCard 文案层级：

```text
标题：16px / 600 / text-primary
问题：14px / 500 / text-primary
证据：13px / text-secondary
下一步：14px / 500 / text-primary
```

---

## 0.0.0.7 Composer Light Mode 样式

当前 Composer 在亮色模式下边界不够明显。建议：

```css
.composer {
  background: var(--bg-card);
  border: 1px solid var(--border-default);
  border-radius: 20px;
  box-shadow: var(--shadow-card);
}

.composer:focus-within {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
```

输入框文字：

```css
.composer textarea {
  color: var(--text-primary);
}

.composer textarea::placeholder {
  color: var(--text-muted);
}
```

按钮：

```css
.send-button {
  background: #111827;
  color: #ffffff;
}

.send-button:hover {
  background: #000000;
}
```

---

## 0.0.0.8 Sidebar Light Mode 样式

左侧 Thread card 需要更明确的选中态。

```css
.thread-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
}

.thread-card:hover {
  background: var(--bg-hover);
  border-color: var(--border-default);
}

.thread-card.active {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  box-shadow: var(--shadow-card);
}
```

Thread 状态 badge：

```css
.thread-status.done { color: var(--success); }
.thread-status.running { color: var(--running); }
.thread-status.blocked { color: var(--blocked); }
.thread-status.failed { color: var(--error); }
```

---

## 0.0.0.9 Inline Code / Logs / JSON 样式

亮色模式下 inline code 需要清楚，但不要太重。

```css
.inline-code,
code {
  background: var(--code-bg);
  color: var(--code-text);
  border: 1px solid var(--code-border);
  border-radius: 6px;
  padding: 2px 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
```

日志区域：

```css
.log-panel {
  background: #0f172a;
  color: #e5e7eb;
  border-radius: 12px;
  border: 1px solid #1e293b;
}
```

说明：即使是亮色模式，日志/终端区域也可以保留深色背景，这样更像真实开发工具，也更容易阅读 stdout/stderr。

---

## 0.0.0.10 Detail Tabs 样式

Tabs 在亮色模式下需要明确 active 状态。

```css
.tab {
  color: var(--text-secondary);
  border-bottom: 2px solid transparent;
}

.tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}
```

---

## 0.0.0.11 Status Badge 样式

统一所有状态 badge。

```css
.badge.success {
  color: var(--success);
  background: var(--success-soft);
  border: 1px solid var(--success-border);
}

.badge.warning {
  color: var(--warning);
  background: var(--warning-soft);
  border: 1px solid var(--warning-border);
}

.badge.error {
  color: var(--error);
  background: var(--error-soft);
  border: 1px solid var(--error-border);
}

.badge.blocked {
  color: var(--blocked);
  background: var(--blocked-soft);
  border: 1px solid var(--blocked-border);
}

.badge.running {
  color: var(--running);
  background: var(--running-soft);
  border: 1px solid var(--running-border);
}
```

---

## 0.0.0.12 Light Mode 可访问性要求

必须满足：

```text
正文文字对比度 >= 4.5:1
大号文字对比度 >= 3:1
状态信息不能只依赖颜色，必须同时有 icon / 文案
可点击元素 hover/focus 必须明显
输入框 focus 必须有可见 outline 或 ring
```

不要使用纯颜色传达状态。必须组合：

```text
icon + color + label
```

例如：

```text
⚠️ 验证遇到问题
✅ 构建通过
⏸ 等待确认
```

---

## 0.0.0.13 当前截图对应的 Light Mode 修复

当前截图问题：

```text
主区域太白
Timeline 卡片几乎没有边界
“内部事件”过淡
“任务遇到阻塞”层级不明显
底部输入区边框弱
左侧选中线程不够突出
Debug / Skills / Architecture 按钮过重但不清晰
```

建议修改后：

```text
App 背景改为 #f6f7f9
Main 背景改为 #f8fafc
Timeline item 使用白底 + 明确边框 + 轻阴影
当前步骤使用 accent-soft 背景
阻塞卡片使用 blocked-soft + 左边 4px 状态线
正文使用 #111827
说明使用 #374151 / #6b7280
Composer 增加明显 border 和 focus ring
Thread active 使用 accent-soft + accent-border
Logs 默认折叠，展开后使用深色 terminal 风格
```

---

## 0.0.0.14 Light Mode Implementation Checklist

### P0：必须修

- [ ] 建立统一 light theme tokens
- [ ] 提高正文和说明文字对比度
- [ ] Timeline item 增加边框、阴影、状态左边线
- [ ] IssueCard 使用状态色背景和边框
- [ ] Composer 增加明显 border 和 focus ring
- [ ] ThreadCard active 状态增强
- [ ] Inline code 样式增强
- [ ] Raw logs 默认折叠

### P1：体验增强

- [ ] DetailTabs active 状态增强
- [ ] StatusBadge 统一设计
- [ ] Hover / focus 状态统一
- [ ] Scrollbar 可见性增强
- [ ] Dark terminal logs in light mode
- [ ] Screenshot / artifact card 增强边框

### P2：质量保障

- [ ] 增加 visual regression screenshots
- [ ] 增加 light/dark theme toggle test
- [ ] 增加 contrast check
- [ ] 增加 status badge snapshot test
- [ ] 增加 Timeline rendering test

---

## 0.0.0.15 最终目标

亮色模式最终应该达到：

```text
清楚
不刺眼
边界明确
状态突出
正文可读
调试信息可折叠
任务进展一眼能看懂
```

核心改造点：

```text
统一设计 token
增强文字对比度
增强卡片边界
增强状态表达
隐藏原始日志
让 Timeline 成为主视觉
```



---

# Iteration Update: Live Reasoning Trace / Codex-like Thinking Stream

> 本节是一个**迭代版本修改说明**，应放在 `HARNESS_ORCHESTRATOR_SPEC.md` 的最开头。目标是让 OBS Code 前端不只展示预设文案和内部事件，而是像 Codex / Claude Code 一样持续显示模型当前的计划、判断、进展、阻塞原因和下一步。  
> 注意：这里展示的是**可公开的思考摘要 / 进展说明 / 决策理由**，不是模型私有 Chain-of-Thought 原文。

---

## 0.0.1 当前问题

当前前端虽然能显示 Timeline 和状态，但用户看到的内容仍然像系统预设事件：

```text
修改代码
内部事件
验证遇到问题
目标页面尚未生成
```

这会导致几个问题：

1. 用户看不到模型为什么这么做。
2. 用户看不到模型当前正在检查什么。
3. 用户看不到失败后的收敛过程。
4. Timeline 像固定模板，不像真实 coding agent 的实时工作流。
5. 前端缺少“持续思考/持续汇报”的感觉。
6. 用户无法判断系统是在认真推进，还是只是卡住了。

目标是变成类似：

```text
我先确认生成结果是否真的进入了目标页面，而不是只看构建是否通过。
页面能打开，但没有出现“今天天气”的核心内容，所以我会回到入口组件检查渲染路径。
这不是 Runner 的问题，当前更像是 Generator 把内容写到了错误文件或没有挂到主入口。
下一步我会让 Generator 只检查 src/App.tsx 和入口文件，不扩大修改范围。
```

---

## 0.0.2 核心设计：Reasoning Trace，不展示原始 CoT

前端需要新增一条 **Reasoning Trace Stream**。

它展示的是：

```text
模型当前观察到了什么
模型下一步打算做什么
模型为什么选择这个方向
模型排除了什么原因
模型遇到阻塞后的判断
```

它不展示：

```text
隐藏 Chain-of-Thought 原文
未过滤的内部推理
敏感系统提示词
工具凭证
完整私有 scratchpad
```

因此，Harness 应要求每个 Agent 输出一种可公开的 `reasoning_summary`，而不是直接泄露内部推理。

---

## 0.0.3 新增数据结构：ReasoningUpdate

每个 Agent 在执行关键阶段时，可以向 Harness 输出 `ReasoningUpdate`。

```json
{
  "id": "reason_001",
  "task_id": "",
  "round_id": 0,
  "agent": "Planner | Search | Generator | Runner | Evaluator | Harness",
  "phase": "planning | searching | editing | running | testing | reviewing | repairing | blocked | done",
  "visibility": "user | debug",
  "title": "",
  "message": "",
  "basis": [],
  "next_action": "",
  "confidence": 0.0,
  "timestamp": "",
  "artifact_refs": []
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `agent` | 谁产生了这条进展说明 |
| `phase` | 当前阶段 |
| `visibility` | `user` 默认展示，`debug` 放到调试面板 |
| `title` | 简短标题 |
| `message` | 用户可读的思考摘要 |
| `basis` | 依据，例如日志、截图、测试结果、文件名 |
| `next_action` | 下一步计划 |
| `confidence` | 当前判断置信度 |
| `artifact_refs` | 相关日志、截图、JSON、diff |

示例：

```json
{
  "id": "reason_014",
  "task_id": "task_weather_page",
  "round_id": 1,
  "agent": "Evaluator",
  "phase": "reviewing",
  "visibility": "user",
  "title": "页面验证未通过",
  "message": "页面可以打开，但没有出现目标内容“今天天气”。这更像是页面渲染入口或组件挂载问题，而不是浏览器自动化问题。",
  "basis": [
    "browser_tests.page_load completed",
    "expected text not found",
    "no fatal console error"
  ],
  "next_action": "让 Generator 检查入口组件和目标页面渲染逻辑，只做最小修复。",
  "confidence": 0.84,
  "timestamp": "2026-05-19T11:12:00+08:00",
  "artifact_refs": [
    ".harness/runs/run_001/output/run_report.json",
    ".harness/runs/run_001/screenshots/page_load.png"
  ]
}
```

---

## 0.0.4 Agent 输出中新增 `reasoning_updates`

所有 Agent 的输出结构中都应允许包含：

```json
{
  "reasoning_updates": []
}
```

它和 `display_summary` 的区别：

| 字段 | 用途 |
|---|---|
| `display_summary` | 当前阶段完成后的摘要，一般只有一条 |
| `reasoning_updates` | 执行过程中的多条动态进展说明 |

### Planner 示例

```json
{
  "reasoning_updates": [
    {
      "agent": "Planner",
      "phase": "planning",
      "visibility": "user",
      "title": "正在收敛任务范围",
      "message": "用户要的是一个天气页面，不需要数据库、登录或外部部署。我会把计划限制在前端入口文件和样式文件内。",
      "basis": ["user_request", "project_summary.project_type = frontend"],
      "next_action": "生成最小可运行 PlanContract。",
      "confidence": 0.9
    }
  ]
}
```

### Generator 示例

```json
{
  "reasoning_updates": [
    {
      "agent": "Generator",
      "phase": "editing",
      "visibility": "user",
      "title": "正在做最小代码修改",
      "message": "计划只要求生成天气页面，所以我不会新增依赖或改 package.json，只会修改入口组件和样式。",
      "basis": ["PlanContract.allowed_files", "package_json_policy.allow_modify = false"],
      "next_action": "输出 PatchEnvelope 给 Harness 校验。",
      "confidence": 0.88
    }
  ]
}
```

### Runner 示例

```json
{
  "reasoning_updates": [
    {
      "agent": "Runner",
      "phase": "testing",
      "visibility": "user",
      "title": "正在验证页面是否真实可见",
      "message": "构建检查之后，我会启动本地预览并用浏览器确认页面不是空白，同时检查控制台错误。",
      "basis": ["test_commands.build", "smoke_tests.page_load"],
      "next_action": "启动 dev server 并执行页面加载测试。",
      "confidence": 0.86
    }
  ]
}
```

### Evaluator 示例

```json
{
  "reasoning_updates": [
    {
      "agent": "Evaluator",
      "phase": "reviewing",
      "visibility": "user",
      "title": "正在判断失败归因",
      "message": "Runner 能打开页面，但目标文本没有出现；没有证据表明是浏览器工具错误，因此当前更可能是产品代码没有正确渲染目标页面。",
      "basis": ["RunReport.browser_tests", "screenshot", "acceptance_criteria"],
      "next_action": "输出 FIXABLE，并给 Generator 一个文件范围很小的修复指令。",
      "confidence": 0.82
    }
  ]
}
```

---

## 0.0.5 Harness 需要增加 Reasoning Composer

Agent 原始输出不能直接展示。Harness 应增加一个组件：

```text
Agent Output
  ↓
Reasoning Composer
  ↓
ReasoningUpdate Stream
  ↓
Frontend Thinking Timeline
```

Reasoning Composer 的职责：

1. 接收各 Agent 的 `reasoning_updates`。
2. 过滤敏感内容。
3. 删除私有 CoT、系统提示词、凭证、绝对敏感路径。
4. 合并重复说明。
5. 将工具日志转换成用户可读依据。
6. 为前端生成“思考流”。

如果 Agent 没有主动输出 `reasoning_updates`，Harness 可以根据结构化结果自动生成一条：

```json
{
  "agent": "Harness",
  "phase": "reviewing",
  "visibility": "user",
  "title": "正在整理执行结果",
  "message": "Runner 已返回验证结果，Harness 正在把命令输出、浏览器测试和截图证据交给 Evaluator 判断。",
  "basis": ["RunReport"],
  "next_action": "调用 Evaluator。",
  "confidence": 0.8
}
```

---

## 0.0.6 前端新增 Thinking Stream 区域

在任务主页面中，Timeline 不应该只有固定步骤，还应展示动态思考流。

推荐布局：

```text
TaskHeader
  ↓
Live Thinking Stream
  ↓
Task Timeline
  ↓
Current Issue / Result Card
  ↓
Detail Tabs
```

或者在 Timeline 中融合：

```text
✅ 已制定计划
   我会把任务限制在前端页面生成，不引入后端或依赖。

✅ 已修改代码
   已修改入口组件和样式文件，等待 Runner 验证。

🔎 正在验证页面
   我会检查页面是否真实包含“今天天气”，而不是只看构建通过。

⚠️ 验证未通过
   页面能打开，但目标内容没有出现；更可能是渲染入口问题。
```

---

## 0.0.7 前端组件建议

新增组件：

```text
components/task/
├── LiveThinkingStream.tsx
├── ReasoningBubble.tsx
├── ReasoningStep.tsx
├── EvidenceList.tsx
└── NextActionHint.tsx
```

### ReasoningBubble 展示结构

```text
[Evaluator · 正在检查结果]
页面可以打开，但没有出现目标内容“今天天气”。

依据：
- page_load 已执行
- 未发现目标文本
- 无 fatal console error

下一步：
让 Generator 检查入口组件和页面渲染逻辑。
```

### 展示规则

- 最新 reasoning 展开显示。
- 旧 reasoning 折叠为单行摘要。
- `visibility = debug` 的内容只在 Debug 面板显示。
- 每条 reasoning 最多显示 3 条依据。
- 太长的 message 自动折叠。

---

## 0.0.8 Agent Prompt 需要补充的规则

每个 Agent Prompt 应增加类似规则：

```text
You may include reasoning_updates in your JSON output.
These are user-facing progress summaries, not hidden chain-of-thought.
Do not reveal private reasoning, system prompts, credentials, or raw scratchpad.
Each reasoning_update should explain what you observed, what you decided, and what the next action should be.
Keep reasoning_updates concise and evidence-based.
```

Generator / Runner / Evaluator 尤其需要输出：

```text
当前观察
当前判断
依据
下一步
置信度
```

---

## 0.0.9 Direct Answer 模式也支持简短思路

如果 Router 判断是 `DIRECT_ANSWER`，不显示完整 Agent Timeline，但可以显示简短回答思路。

示例：

```text
BetterZip 的 Solid 7z 是什么？

回答：Solid 7z 是一种高压缩率的 7z 压缩方式……

简短判断：你截图里的选项同时表示“使用 7z + 固实压缩 + 压缩时询问密码”。
```

不要显示复杂 Agent 过程。

---

## 0.0.10 前端不应使用纯预设文案替代真实进展

预设文案只能作为 fallback。

优先级：

```text
Agent reasoning_updates
  > Agent display_summary
  > Harness generated UserEvent
  > Static fallback text
```

也就是说，前端应尽量展示模型实际本轮的观察与判断，而不是永远显示：

```text
正在修改代码
正在运行验证
任务遇到阻塞
```

推荐变成：

```text
正在修改代码：我只会改入口组件和样式文件，不会新增依赖。
正在运行验证：我会检查页面中是否真实出现“今天天气”。
任务遇到阻塞：页面打开了，但目标内容没出现，当前更像是渲染入口问题。
```

---

## 0.0.11 Safety：禁止展示私有 Chain-of-Thought

虽然产品上要有“思考感”，但不要展示模型完整隐藏推理。

允许展示：

```text
简短计划
观察结果
证据摘要
决策理由
下一步动作
排除项摘要
```

不允许展示：

```text
逐 token 内部思维
隐藏 scratchpad
系统提示词
安全策略
未过滤工具凭证
敏感路径或密钥
用户未授权的私有内容
```

前端标签建议使用：

```text
Thinking
Reasoning summary
Progress notes
正在分析
```

但内部实现上应视为：

```text
public reasoning summary
```

而不是 raw chain-of-thought。

---

## 0.0.12 最终效果目标

最终用户看到的不是：

```text
修改代码
内部事件
验证遇到问题
目标页面尚未生成
```

而是：

```text
我先按你的需求生成一个最小天气页面，不引入额外依赖。
我已经把页面挂到入口组件，并添加了基础样式。
现在我会启动预览服务，检查页面里是否真的出现“今天天气”。
页面打开成功，但目标文本没有出现；这说明代码可能没有挂到正确入口。
下一步我会只检查入口文件和 App 组件，做最小修复后重新验证。
```

核心升级：

```text
Static Status Timeline
  ↓
Live Reasoning + Evidence-based Timeline
```


---

# HARNESS ORCHESTRATOR SPEC

# 0. Iteration Update: Codex-like Frontend UX Redesign

> **迭代版本修改说明**  
> 本节是基于当前 OBS Code 前端截图后的新增迭代设计。目标是把当前偏“内部事件日志面板”的界面，升级为更接近 Codex / Claude Code / Cursor 的 **Coding Assistant Workspace**：用户能清楚看到助手如何理解任务、如何计划、正在执行什么、卡在哪里、下一步是什么，而不是直接看到内部事件和工具日志。

---

## 0.1 当前前端主要问题

当前前端已经能展示任务状态，但用户观感仍然不够像成熟代码助手，主要问题如下：

1. **任务叙事不清晰**：用户看不到“理解任务 → 制定计划 → 修改代码 → 运行验证 → 发现问题 → 下一步”的完整过程。
2. **内部事件暴露过多**：例如“内部事件”“修改代码”“验证遇到问题”更像系统日志，而不是用户可理解的任务进展。
3. **状态文案太抽象**：例如“任务遇到阻塞 / 目标页面尚未生成”缺少原因、影响、证据和建议。
4. **视觉层级不明确**：页面中间区域很空，但任务重点不突出；滚动区域和卡片布局显得松散。
5. **缺少当前动作说明**：用户不知道系统现在到底是在规划、修改、运行、验证，还是等待用户确认。
6. **Debug 信息和用户信息混在一起**：原始日志、内部事件、Agent 执行细节应默认折叠，而不是直接影响主视图。
7. **简单问答和工程任务界面没有分离**：简单问题应直接用聊天气泡回答，复杂任务才显示 Agent Timeline。

本次迭代目标：

```text
Raw Agent Logs / Internal Events
  ↓
Harness UserEvent Normalizer
  ↓
Codex-like Task Timeline
  ↓
User-Friendly Workspace UI
```

---

## 0.2 目标体验

最终用户默认看到的不是 Agent 内部执行细节，而是清晰的任务进展：

```text
我理解了你的需求
我制定了实现计划
我修改了哪些文件
我运行了哪些验证
现在卡在哪里
为什么卡住
下一步建议是什么
是否需要你批准
最终完成了什么
```

对于当前截图中的任务，例如“今天天气”，理想展示应该是：

```text
今天天气

目标：创建一个展示今天天气的页面
状态：验证遇到阻塞
用时：48s

✅ 1. 理解任务
   用户希望生成一个“今天天气”页面。

✅ 2. 制定计划
   准备创建页面结构、天气展示区域和基础样式。

✅ 3. 修改代码
   已完成页面代码修改。

⚠️ 4. 验证页面
   浏览器验证未找到目标页面内容。

阻塞原因
目标页面尚未生成，Runner 无法确认页面是否正确显示。

建议下一步
修复页面渲染入口后重新运行验证。

[自动修复并重试] [查看测试结果] [查看日志]
```

而不是：

```text
任务遇到阻塞
内部事件
修改代码
修改代码
验证遇到问题
目标页面尚未生成
```

---

## 0.3 前端信息架构

建议采用三层主布局：

```text
┌──────────────────────────────────────────────┐
│ Top Bar                                      │
│ Project / Mode / Status / Round / Permission │
├───────────────┬──────────────────────────────┤
│ Sidebar       │ Main Workspace                │
│ Threads       │ Task Header                   │
│ Recent Tasks  │ Timeline                      │
│               │ Current Action / Issue Card   │
│               │ Detail Tabs                    │
├───────────────┴──────────────────────────────┤
│ Composer                                     │
│ Model / Permission / Input / Send             │
└──────────────────────────────────────────────┘
```

推荐组件结构：

```text
AppShell
├── Sidebar
│   ├── Logo
│   ├── NewThreadButton
│   └── ThreadList
│
├── Workspace
│   ├── TopStatusBar
│   ├── TaskHeader
│   ├── TaskTimeline
│   ├── CurrentActionCard
│   ├── IssueCard
│   ├── FinalSummary
│   └── DetailTabs
│       ├── Overview
│       ├── Changes
│       ├── Tests
│       ├── Logs
│       └── JSON
│
└── Composer
    ├── ModelSelector
    ├── PermissionMode
    ├── InputBox
    └── SendButton
```

---

## 0.4 TopStatusBar 设计

顶部状态栏应显示当前任务关键状态，而不是只显示 context 数字。

推荐展示：

```text
● Running · Round 1/3 · 48s · Permission: ask · Context 4/128K
```

状态文案：

| State | Display | Color |
|---|---|---|
| Idle | 空闲 | gray |
| Planning | 正在制定计划 | blue |
| Searching | 正在查找资料 | cyan |
| Editing | 正在修改代码 | green |
| Running | 正在运行验证 | purple |
| Reviewing | 正在检查结果 | yellow |
| Repairing | 正在修复问题 | orange |
| Blocked | 任务遇到阻塞 | red/orange |
| Needs Approval | 等待确认 | orange |
| Done | 已完成 | green |
| Failed | 任务失败 | red |

---

## 0.5 TaskHeader 设计

TaskHeader 应该清楚说明任务目标和当前状态。

推荐结构：

```json
{
  "title": "今天天气",
  "goal": "创建一个展示今天天气的页面",
  "status": "blocked",
  "status_text": "验证遇到阻塞",
  "progress": {
    "current": 3,
    "total": 5
  },
  "duration_sec": 48,
  "round_id": 1
}
```

推荐 UI：

```text
今天天气

目标：创建一个展示今天天气的页面
状态：验证遇到阻塞 · 第 1 轮 · 48s
```

---

## 0.6 TaskTimeline 设计

Timeline 是 Codex-like 体验的核心。每个步骤都应是用户可理解的任务动作，而不是内部事件。

推荐 Timeline：

```text
✅ 理解任务
   识别到用户希望生成一个“今天天气”页面。

✅ 制定计划
   计划创建页面结构、天气展示卡片和基础样式。

✅ 修改代码
   已完成代码修改。

⚠️ 验证页面
   浏览器验证未找到目标页面内容。

⏸ 等待下一步
   建议修复页面渲染入口后重新验证。
```

Timeline item schema：

```json
{
  "id": "evt_001",
  "task_id": "",
  "round_id": 1,
  "status": "completed | running | warning | failed | blocked | pending",
  "title": "修改代码",
  "summary": "已完成页面代码修改。",
  "agent": "Generator",
  "timestamp": "11:11:57",
  "duration_sec": 2,
  "details_ref": ".harness/runs/run_001/output/patch_result.json",
  "artifact_refs": [],
  "user_visible": true
}
```

---

## 0.7 Raw Event 到 UserEvent 的映射

前端不要直接渲染 Raw Harness Event。必须先做归一化。

```text
RawHarnessEvent
  ↓
normalizeToUserEvent()
  ↓
UserEvent
  ↓
UI Render
```

映射示例：

| Raw Event | User-Facing Event |
|---|---|
| Planner completed | 已制定实现计划 |
| Search completed | 已完成资料检索 |
| Generator patch completed | 已修改代码 |
| Runner command started | 正在运行验证命令 |
| Runner dev server started | 正在启动预览服务 |
| Runner browser goto | 正在打开页面 |
| Runner screenshot captured | 已截取页面快照 |
| Evaluator FIXABLE | 发现可修复问题 |
| Evaluator INFRA | 验证被环境或工具问题阻塞 |
| Evaluator PASS | 任务已通过验收 |
| Evaluator REPLAN | 当前方案需要重新规划 |

禁止默认展示：

```text
内部事件
bash
code_sandbox
tool_call
stdout
stderr
max iterations reached
raw JSON
```

这些只放入 Debug / Logs / JSON tabs。

---

## 0.8 UserEvent Schema

```json
{
  "id": "",
  "task_id": "",
  "round_id": 0,
  "type": "planning | searching | editing | running | testing | reviewing | approval | issue | done | debug",
  "severity": "info | success | warning | error | blocked",
  "title": "",
  "summary": "",
  "details": "",
  "agent": "",
  "timestamp": "",
  "duration_sec": 0,
  "next_step": "",
  "debug_ref": "",
  "artifact_refs": [],
  "user_visible": true
}
```

UI 默认只展示 `user_visible = true` 的事件，Debug 面板才展示 `user_visible = false` 的事件。

---

## 0.9 CurrentActionCard 设计

Timeline 下方应展示当前动作卡片，告诉用户系统正在做什么。

运行中示例：

```text
正在验证页面

Runner 正在启动本地预览服务，并准备打开浏览器进行页面检查。

当前步骤：
1. npm run build
2. npm run dev
3. 打开 http://localhost:5173
4. 检查页面是否白屏
```

阻塞示例：

```text
任务遇到阻塞

目标页面尚未生成，浏览器验证无法确认页面内容。

可能原因：
- 页面代码没有正确渲染
- 路由没有指向目标页面
- 代码没有被应用到正确入口文件

建议下一步：
让 Generator 修复页面渲染逻辑，然后重新运行验证。
```

---

## 0.10 IssueCard 设计

失败或阻塞时使用 IssueCard，不要只显示一行错误。

IssueCard schema：

```json
{
  "title": "验证未通过",
  "severity": "warning | error | blocked",
  "problem": "目标页面尚未生成。",
  "impact": "无法确认页面是否正确显示。",
  "evidence": [
    "browser_tests.page_load failed",
    "expected text not found"
  ],
  "suggested_next_step": "修复页面渲染入口后重新验证。",
  "actions": [
    {
      "label": "自动修复并重试",
      "action": "continue_repair"
    },
    {
      "label": "查看日志",
      "action": "open_logs"
    },
    {
      "label": "停止任务",
      "action": "stop_task"
    }
  ]
}
```

推荐展示：

```text
验证未通过

问题：目标页面尚未生成。
影响：Runner 无法确认“今天天气”页面是否正确显示。
证据：smoke test 未找到预期文本。
建议：修复页面渲染入口后重新验证。

[自动修复并重试] [查看日志] [停止任务]
```

---

## 0.11 DetailTabs 设计

主 Timeline 不应承载所有信息。详细信息通过 tabs 展开。

```text
Overview | Changes | Tests | Logs | JSON
```

- **Overview**：当前状态、已完成步骤、阻塞原因、下一步建议
- **Changes**：changed_files、created_files、deleted_files、diff summary
- **Tests**：build/dev server/browser/console/screenshots
- **Logs**：stdout/stderr，默认折叠
- **JSON**：PlanContract、SearchReport、PatchResult、RunReport、EvalVerdict、HarnessDecision

---

## 0.12 display_summary 使用规范

所有 Agent 输出中都应该包含 `display_summary`，用于前端用户友好展示。

推荐 schema：

```json
{
  "title": "",
  "status": "success | warning | error | blocked",
  "summary": "",
  "highlights": [],
  "next_step_hint": ""
}
```

前端优先展示 `display_summary`，而不是 raw JSON。

---

## 0.13 Direct Answer UI 与 Workflow UI 分离

如果 Harness Router 输出：

```json
{
  "route": "DIRECT_ANSWER"
}
```

前端显示普通聊天气泡，不显示 Agent Timeline。

如果 Router 输出：

```json
{
  "route": "CODE_WORKFLOW"
}
```

前端才显示：

```text
Planning → Editing → Running → Reviewing → Done
```

这样可以避免简单问题也进入复杂任务界面。

---

## 0.14 Composer 优化

当前输入区应根据任务状态改变 placeholder。

```text
普通状态：Ask anything or describe a task...
Agent 模式：Describe a coding task, mention files, or ask for a coordinated refactor...
阻塞状态：Reply with instructions, approve next step, or ask for details...
```

---

## 0.15 Sidebar ThreadCard 优化

左侧任务卡片应显示状态和摘要。

当前：

```text
今天天气
Start a new thread...
```

推荐：

```text
今天天气
Blocked · 48s
目标页面尚未生成
```

ThreadCard schema：

```json
{
  "title": "今天天气",
  "status": "blocked",
  "subtitle": "目标页面尚未生成",
  "duration_sec": 48,
  "updated_at": "11:11"
}
```

---

## 0.16 视觉样式建议

### 页面布局

```text
主区域最大宽度：960px ~ 1120px
主内容居中
Timeline 卡片宽度统一
Composer 固定底部
Debug 默认折叠
```

### 颜色

```text
页面背景：#f7f8fa
卡片背景：#ffffff
边框：#e5e7eb
主文本：#111827
次级文本：#6b7280
成功：#16a34a
警告：#f59e0b
错误：#dc2626
阻塞：#ef4444
信息：#2563eb
```

### 卡片

```text
圆角：12px ~ 16px
阴影：轻阴影
状态色只用于 icon / 左边线 / badge
不要大面积使用强色背景
```

---

## 0.17 前端组件建议

```text
components/
├── layout/
│   ├── AppShell.tsx
│   ├── Sidebar.tsx
│   ├── TopStatusBar.tsx
│   └── Composer.tsx
│
├── task/
│   ├── TaskHeader.tsx
│   ├── TaskTimeline.tsx
│   ├── TimelineItem.tsx
│   ├── CurrentActionCard.tsx
│   ├── IssueCard.tsx
│   ├── FinalSummary.tsx
│   └── ApprovalCard.tsx
│
├── details/
│   ├── DetailTabs.tsx
│   ├── OverviewTab.tsx
│   ├── ChangesTab.tsx
│   ├── TestsTab.tsx
│   ├── LogsTab.tsx
│   └── JsonTab.tsx
│
└── events/
    ├── normalizeHarnessEvent.ts
    ├── userEventTypes.ts
    └── statusText.ts
```

---

## 0.18 Implementation Checklist

### P0：必须先做

- [ ] 增加 `UserEvent` 归一化层
- [ ] 默认隐藏 raw logs
- [ ] Timeline 使用用户友好文案
- [ ] 增加 TaskHeader
- [ ] 增加 CurrentActionCard
- [ ] 增加 IssueCard
- [ ] 增加 `display_summary` 渲染
- [ ] Direct Answer 不显示 Agent Timeline

### P1：体验增强

- [ ] 增加 DetailTabs
- [ ] 增加 ChangesTab
- [ ] 增加 TestsTab
- [ ] 增加 ApprovalCard
- [ ] 左侧 ThreadCard 显示状态和摘要
- [ ] TopStatusBar 显示任务状态

### P2：高级能力

- [ ] 支持任务恢复后的 Timeline Replay
- [ ] 支持 Artifact 点击跳转
- [ ] 支持截图预览
- [ ] 支持 diff 高亮
- [ ] 支持 JSON schema viewer
- [ ] 支持 route badge：Direct / Search / Workflow

---

## 0.19 本次迭代验收标准

本次前端迭代完成后，应满足：

1. 简单问答不会进入 Agent Timeline
2. 复杂任务显示清晰 Timeline
3. 用户默认看不到 raw tool logs
4. 每个任务都有明确状态、阻塞原因和下一步
5. 失败时展示 IssueCard，而不是只展示一行错误
6. 成功时展示 FinalSummary
7. Debug 信息可查看，但默认折叠
8. 左侧任务卡片能显示任务状态
9. `display_summary` 能被前端优先渲染
10. 当前截图中的“内部事件”不再出现在主视图

---

## 0.20 最终目标

OBS Code 前端最终应该让用户感觉：

```text
这个助手正在像真实 coding agent 一样逐步处理任务：
理解需求 → 制定计划 → 修改代码 → 运行验证 → 发现问题 → 给出下一步。
```

而不是：

```text
系统只是在展示内部工具日志和模糊状态。
```

核心原则：

```text
Raw Agent Logs are for Debug.
UserEvent Timeline is for users.
```

```text
RawHarnessEvent → UserEvent → Codex-like Timeline → Friendly UI
```

---

# 0. Harness Router / Direct Answer Gate

> 不是所有用户输入都应该进入 5-Agent 工作流。简单问题应由 Harness 直接回答；只有需要改代码、跑命令、查外部资料、修改文档或处理项目文件时，才进入对应 Agent 流程。

## 0.1 设计目标

OBS Code 需要同时支持两种体验：

```text
简单问题 → 直接回答，像普通 Chat 一样快速
复杂工程任务 → 进入 Harness-controlled Agent Workflow
```

这样可以避免用户问简单问题时也触发：

```text
Planner → Search → Generator → Runner → Evaluator
```

从而降低延迟、减少 token 消耗，并提升用户观感。

---

## 0.2 新增 Harness Router

在所有 Agent 前面增加一个 **Harness Router / Intent Gate**。

它不是第 6 个 Agent，而是 Harness 的入口路由模块。

```text
User Message
  ↓
Harness Router / Intent Gate
  ↓
┌───────────────────────────────┬───────────────────────────────┐
│ Simple Answer Path             │ Agent Workflow Path            │
│ 直接回答                        │ 进入 5-Agent 工作流             │
└───────────────────────────────┴───────────────────────────────┘
```

Router 只负责判断用户请求应该走哪条路径，不负责执行任务。

---

## 0.3 Router 路由类型

Router 输出以下路由之一：

```text
DIRECT_ANSWER
SEARCH_ANSWER
CODE_WORKFLOW
DOC_WORKFLOW
CLARIFY
```

### DIRECT_ANSWER

用于简单问答，不进入 Agent 工作流。

适合：

```text
概念解释
简单工具用法
简单命令解释
简单报错含义
简单对比
普通建议
不需要读取项目
不需要修改文件
不需要执行命令
不需要浏览器验证
不需要外部搜索
```

示例：

```text
BetterZip 的 Solid 7z 是什么意思？
pwd 是什么意思？
React useEffect 是什么？
FlashAttention 优化了什么？
这个报错大概是什么意思？
```

流程：

```text
User → Router → Direct Answer Composer → User
```

---

### SEARCH_ANSWER

用于需要当前外部信息，但不需要修改项目的问答。

适合：

```text
最新价格
最新政策
最新版本
某平台是否支持免费试用
某家公司是哪家
某工具当前是否可用
```

流程：

```text
User → Router → Search Agent → SearchReport → Answer Composer → User
```

不进入 Generator / Runner / Evaluator。

---

### CODE_WORKFLOW

用于需要修改代码、修复项目、执行测试或验证应用的任务。

适合：

```text
实现一个功能
修改项目代码
修复构建错误
根据报错修 bug
生成页面或游戏
运行测试
启动应用
浏览器验证
```

流程：

```text
User → Router → Planner → Search Gate → Generator → Runner → Evaluator → Harness Decision
```

---

### DOC_WORKFLOW

用于创建、修改、整理文档或 Prompt。

适合：

```text
修改 md 文档
整理方案
生成 Agent Prompt
改写规范
更新 spec
```

可以走轻量流程：

```text
User → Router → Planner → Generator → Harness
```

如果只是不涉及文件写入的文档生成，也可以直接走：

```text
User → Router → Direct Answer Composer → User
```

---

### CLARIFY

用于请求不明确，无法安全路由的情况。

适合：

```text
“帮我改一下”
“这个有问题”
“优化一下”
“修复它”
```

但没有提供足够上下文。

流程：

```text
User → Router → Ask Clarifying Question → User
```

---

## 0.4 Router 输出结构

Router 必须输出严格 JSON：

```json
{
  "route": "DIRECT_ANSWER",
  "confidence": 0.92,
  "reason": "The user asks a conceptual explanation and does not request project modification, command execution, browser testing, or external search.",
  "requires_search": false,
  "requires_project_context": false,
  "requires_file_edit": false,
  "requires_command_execution": false,
  "requires_browser": false,
  "next": "ANSWER_DIRECTLY"
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `route` | 路由类型 |
| `confidence` | 路由置信度 |
| `reason` | 简短路由原因 |
| `requires_search` | 是否需要外部搜索 |
| `requires_project_context` | 是否需要项目上下文 |
| `requires_file_edit` | 是否需要修改文件 |
| `requires_command_execution` | 是否需要执行命令 |
| `requires_browser` | 是否需要浏览器或 E2E |
| `next` | Harness 下一步动作 |

---

## 0.5 Router Prompt

```md
# Harness Router Prompt

You are the Harness Router.

Your job is to classify the user message before invoking any agent workflow.

Return only JSON.

Routes:

- DIRECT_ANSWER: simple explanation, advice, comparison, command meaning, tool usage, no project modification.
- SEARCH_ANSWER: answer needs current public information, but no project modification.
- CODE_WORKFLOW: user asks to modify code, generate code in project, run tests, fix bugs, start app, or inspect project.
- DOC_WORKFLOW: user asks to create, rewrite, or update a document, prompt, spec, markdown, or local text artifact.
- CLARIFY: user request is too ambiguous to safely route.

Rules:
- Do not invoke Planner for simple questions.
- Do not invoke Generator unless file/code changes are requested.
- Do not invoke Runner unless command execution, tests, app startup, or browser validation is required.
- Do not invoke Search unless the answer needs current external information or the user explicitly asks to search.
- Prefer DIRECT_ANSWER for short conceptual questions.
- Prefer CLARIFY when the user asks to "fix this" without enough context.

Output JSON:

{
  "route": "DIRECT_ANSWER | SEARCH_ANSWER | CODE_WORKFLOW | DOC_WORKFLOW | CLARIFY",
  "confidence": 0.0,
  "reason": "",
  "requires_search": false,
  "requires_project_context": false,
  "requires_file_edit": false,
  "requires_command_execution": false,
  "requires_browser": false,
  "next": ""
}
```

---

## 0.6 Direct Answer Path

简单问题不进入 5-Agent 工作流，由 Harness 调用 Direct Answer Composer 直接回答。

输入：

```json
{
  "user_message": "",
  "conversation_summary": "",
  "relevant_recent_messages": [],
  "active_task": {
    "exists": false,
    "task_id": "",
    "state": ""
  },
  "project_context_available": false,
  "style": "concise"
}
```

输出：

```json
{
  "type": "direct_answer",
  "answer": "",
  "used_agents": [],
  "used_tools": [],
  "confidence": 0.9
}
```

前端表现：

```text
普通聊天气泡
不显示 Planner / Generator / Runner / Evaluator
不显示 Agent Timeline
不显示 Raw Tool Logs
```

---

## 0.7 Search Answer Path

如果用户问题需要当前外部信息，但不需要改项目，则走 Search Answer Path。

流程：

```text
User
  ↓
Router: SEARCH_ANSWER
  ↓
Search Agent
  ↓
SearchReport
  ↓
Answer Composer
  ↓
User
```

该路径不调用：

```text
Planner
Generator
Runner
Evaluator
```

适合：

```text
最新工具政策
官网信息查询
公司主体查询
当前价格/免费试用情况
最新版本/兼容性
```

---

## 0.8 Agent Workflow Path

只有当 Router 判定为 `CODE_WORKFLOW` 时，才进入完整 5-Agent 工作流：

```text
User
  ↓
Router: CODE_WORKFLOW
  ↓
Planner
  ↓
Search Gate
  ↓
Generator
  ↓
Runner
  ↓
Evaluator
  ↓
Harness Decision
```

`DOC_WORKFLOW` 可按任务复杂度选择：

```text
轻量文档生成 → Direct Answer Composer
需要写入本地文件 → Planner → Generator
需要验证文档格式 → Planner → Generator → Runner
```

---

## 0.9 对 5 个 Agent 的影响

### Planner

Planner 只在 Router 判定为 `CODE_WORKFLOW` 或复杂 `DOC_WORKFLOW` 时调用。

补充规则：

```text
Planner is invoked only after Harness Router determines that the user request requires a workflow plan. Do not handle simple Q&A.
```

### Search

Search 可用于两种模式：

```text
workflow_support
direct_answer_support
```

建议在 SearchReport 中加入：

```json
{
  "answer_mode": "workflow_support"
}
```

或：

```json
{
  "answer_mode": "direct_answer_support"
}
```

### Generator

Generator 只在需要文件修改或 patch 时调用。

补充规则：

```text
Generator is never invoked for simple Q&A. Generator only produces patches.
```

### Runner

Runner 只在需要命令执行、应用启动、测试或浏览器验证时调用。

补充规则：

```text
Runner is never invoked for explanation-only questions.
```

### Evaluator

Evaluator 只评估工作流证据，不用于普通聊天回答。

补充规则：

```text
Evaluator only evaluates workflow evidence. It is not used for normal chat answers.
```

---

## 0.10 对话上下文压缩

### 给 Router 的上下文

Router 只需要轻量上下文：

```json
{
  "current_user_message": "",
  "recent_dialogue_summary": "",
  "active_task": {
    "exists": false,
    "task_id": "",
    "state": ""
  },
  "project_context_available": true,
  "uploaded_files_available": false
}
```

不需要把完整项目、完整历史、完整日志塞给 Router。

---

### 给 Planner 的上下文

Planner 只接收结构化压缩上下文：

```json
{
  "task_context": {
    "task_id": "",
    "user_request": "",
    "resolved_intent": "",
    "constraints": [],
    "non_goals": [],
    "user_preferences": []
  },
  "project_summary": {
    "project_type": "",
    "package_manager": "",
    "scripts": {},
    "entry_files": [],
    "important_files": []
  },
  "conversation_summary": {
    "relevant_requirements": [],
    "decisions_already_made": [],
    "previous_user_corrections": [],
    "style_preferences": []
  },
  "previous_failures": []
}
```

Planner 不应接收完整聊天原文，而应接收：

```text
需求
约束
已决定事项
用户偏好
非目标
失败历史
项目摘要
```

---

## 0.11 前端显示规则

### DIRECT_ANSWER / SEARCH_ANSWER

显示为普通聊天气泡：

```text
User: BetterZip 的 Solid 7z 是什么意思？
Assistant: Solid 7z 是……
```

不显示：

```text
Agent Process
Planner 卡片
Generator 卡片
Runner 卡片
Evaluator 卡片
Raw tool logs
```

---

### CODE_WORKFLOW / DOC_WORKFLOW

显示 Codex-like Timeline：

```text
Planning
Editing
Running
Evaluating
Done
```

复杂任务才展示：

```text
Agent Timeline
Diff
Tests
Logs
Approvals
Artifacts
Final Report
```

---

## 0.12 推荐最终结构

```text
Harness
├── Router / Intent Gate
├── Direct Answer Composer
├── Search Answer Composer
├── Context Compressor
├── Workflow Orchestrator
│   ├── Planner
│   ├── Search
│   ├── Generator
│   ├── Runner
│   └── Evaluator
└── Frontend Event Normalizer
```

核心原则：

```text
能直接回答时，不进 Agent。
需要外部信息时，只搜索并回答。
需要修改项目时，才进入完整 Harness Workflow。
需要执行验证时，才调用 Runner。
需要验收工作流结果时，才调用 Evaluator。
```

---



> 所有 Agent 不直接互相调用，不直接掌控流程。所有输入输出都进 Harness，由 Harness 决定下一步、权限、预算、工具调用、回滚和最终状态。

## 你这 5 个 Agent 是
- Planner Agent
- Generator Agent
- Runner Agent
- Evaluator Agent
- Search Agent

## 真正的核心是
- Harness Orchestrator

## 职责边界
- Planner：只规划
- Generator：只改代码
- Runner：只执行命令  / 采证据
- Evaluator：只判断
- Search：只负责外部信息检索、网页内容抽取、文档摘要、API/库用法确认，不负责写代码、不负责跑代码、不负责判断最终结果
- Harness：只负责控制流

## 流程

```text
User Task
  ↓
Harness Orchestrator
  ↓
Planner Agent
  ↓ PlanContract
  ↓
Harness Search Gate
  ├── need_search = true  → Search Agent → SearchReport
  └── need_search = false → skip
  ↓
Generator Agent
  ↓ PatchResult
Runner Agent
  ↓ RunReport
Evaluator Agent
  ↓ EvalVerdict
Harness Decision
  ↓
PASS / CALL_GENERATOR / CALL_PLANNER / CALL_SEARCH / FAIL_HARD
```

## 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│                    Harness Orchestrator                     │
│  - 状态机                                                   │
│  - 权限控制                                                 │
│  - 工具路由                                                 │
│  - Search Gate                                              │
│  - budget 控制                                              │
│  - patch / diff 管理                                        │
│  - 日志 / 截图 / evidence 管理                              │
│  - 输入输出 schema 校验                                     │
└──────────────────────────────────────────────────────────────┘
                        │
                        ▼
                ┌───────────────┐
                │ Planner Agent │
                └───────────────┘
                        │ PlanContract
                        ▼
                ┌────────────────────┐
                │ Harness Search Gate│
                └────────────────────┘
                 │ need_search = true      │ need_search = false
                 ▼                         ▼
           ┌──────────────┐              skip
           │ Search Agent │
           └──────────────┘
                 │ SearchReport
                 ▼
           ┌────────────────┐
           │ Generator Agent│
           └────────────────┘
                 │ PatchResult
                 ▼
           ┌──────────────┐
           │ Runner Agent │
           └──────────────┘
                 │ RunReport
                 ▼
           ┌────────────────┐
           │Evaluator Agent │
           └────────────────┘
                 │ EvalVerdict
                 ▼
           ┌────────────────┐
           │Harness Decision│
           └────────────────┘
```

## 当前按能力分为 4 类 Skill

```text
1. 文件 / 代码编辑类
   - desktop-commander
   - file-manager
   - filesystem
   - agent-skills

2. 终端 / Runtime 类
   - Skill Management = python runtime

3. 浏览器 / E2E 类
   - computer-use
   - web-e2e
   - playwright-e2e
   - web-testing-playwright-e2e
   - e2e

4. 搜索 / 爬取类
   - web-search-free
   - search：Brave / Serper / Exa / Perplexity
   - web-scraper-pro
   - firecrawl-scraper
   - skill-lookup
```

## 权限矩阵

```text
	┌────────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
	│ Agent      │ 读需求 │ 读文件 │ 写文件 │ Bash   │ Browser│ Search │ 判断   │
	├────────────┼────────┼────────┼────────┼────────┼────────┼────────┼────────┤
	│ Planner    │ ✅     │ ⚠️摘要 │ ❌     │ ❌     │ ❌     │ ❌     │ ✅规划  │
	│ Search     │ ✅     │ ⚠️摘要 │ ❌     │ ❌     │ ⚠️抓取 │ ✅     │ ✅资料  │
	│ Generator  │ ✅     │ ✅     │ ✅     │ ❌     │ ❌     │ ❌     │ ❌     │
	│ Runner     │ ✅     │ ✅     │ ❌     │ ✅     │ ✅     │ ❌     │ ❌     │
	│ Evaluator  │ ✅     │ ✅只读 │ ❌     │ ❌     │ ❌     │ ❌     │ ✅验收  │
	└────────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┘
```

---

## skill 权限

```text
searcher：
	只处理下面的
		1. 搜索外部资料
		2. 抓取网页内容
		3. 摘要关键 API / 文档 / 示例
		4. 判断资料新旧和可信度
		5. 输出 SearchReport
		6. 给 Generator 提供引用依据和实现建议
	不处理
		不修改代码
		不执行命令
		不启动浏览器测试
		不判断任务是否最终通过
		不直接调用 Generator
		不直接调用 Runner
		不自己扩大搜索范围
		不无限搜索
	可以用的skill：
		Search:
		  tools:
		    - web-search-free
		    - search
		    - web-scraper-pro
		    - firecrawl-scraper
		    - skill-lookup
		  optional_tools:
		    - computer-use
	不要每次都调用 Search。Harness 应该有一个 Search Gate
		需要search情况
			1. 用户明确要求查资料、联网、找最新信息
			2. 任务依赖外部 API / SDK / 框架最新用法
			3. Generator 或 Runner 遇到依赖版本/API 用法错误
			4. Planner 标记 need_search = true
			5. 项目要接入第三方服务
			6. 用户要求参考某个网页 / GitHub / 文档
			7. 本地信息不足以完成任务
		不需要 Search 的情况
			1. 普通前端小游戏
			2. 本地代码修 bug
			3. 简单样式修改
			4. 只需要根据现有项目实现功能
			5. Runner 的脚本错误且不涉及第三方 API 用法不确定
			6. TypeScript 变量未定义这类本地错误
		只有当 Runner 错误属于第三方 API 用法不确定，例如 Playwright API 变更、SDK 文档不清楚时，才允许 Search。

Planner：不应该自己打开项目到处查。Harness 可以先给它一个项目摘要
	agent: Planner
	tools: []
	allowed_inputs:
	  - user_request
	  - project_summary
	  - previous_failures
	  - constraints
	allowed_outputs:
	  - PlanContract
	forbidden:
	  - write_file
	  - bash
	  - browser
	  - e2e
	  - web_search
Generator：Generator 最好不要有 bash、如果必须给 bash，只允许
												pwd
												ls
												find
												cat
												grep
												sed -n
	agent: Generator
	tools:
	  - filesystem
	  - file-manager
	  - desktop-commander.file_read
	  - desktop-commander.file_write
	  - desktop-commander.str_replace
	allowed:
	  - read_project_files
	  - create_files_inside_workspace
	  - modify_allowed_files
	forbidden:
	  - bash
	  - npm run build
	  - npm run dev
	  - browser
	  - playwright
	  - web_search
	  - edit .env
	  - edit .git
	  - edit node_modules
	  - delete large directories
Runner：Runner 允许写的只有
							.harness/**
							logs/**
							screenshots/**
							tmp/**
				不能写
						src/**
						app/**
						components/**
						package.json
						.env

	agent: Runner
	tools:
	  - desktop-commander.terminal
	  - Skill Management = python runtime
	  - playwright-e2e
	  - web-testing-playwright-e2e
	  - e2e
	  - computer-use
	allowed:
	  - run_build
	  - run_lint
	  - run_test
	  - start_dev_server
	  - run_playwright
	  - capture_screenshot
	  - collect_console_errors
	  - collect_network_errors
	  - collect_stdout_stderr
	forbidden:
	  - modify_source_code
	  - write_business_files
	  - edit package.json unless explicitly allowed by Harness
	  - install dependencies unless PlanContract.allow_install = true
	  - web_search
Evaluator：Evaluator 必须一次性输出 verdict，不允许循环验证
	agent: Evaluator
	tools: []
	allowed_inputs:
	  - PlanContract
	  - PatchResult
	  - RunReport
	  - screenshots
	  - browser_console
	  - git_diff
	  - previous_eval_verdicts
	allowed_outputs:
	  - EvalVerdict
	forbidden:
	  - bash
	  - browser
	  - write_file
	  - repair_code
	  - call_runner
	  - call_generator
```

---

```text
建议在你的项目根目录下加这些目录（其他多余没用文件不要）：
	obs/
	├── .harness/
	│   ├── task.json
	│   ├── session.json
	│   ├── project_summary.json
	│   ├── plan.json
	│   ├── state.json
	│   ├── policy.json
	│   ├── budgets.json
	│   ├── runs/
	│   │   ├── run_001/
	│   │   │   ├── input/
	│   │   │   │   ├── generator_input.json
	│   │   │   │   ├── runner_input.json
	│   │   │   │   └── evaluator_input.json
	│   │   │   ├── output/
	│   │   │   │   ├── patch_result.json
	│   │   │   │   ├── run_report.json
	│   │   │   │   └── eval_verdict.json
	│   │   │   ├── diff.patch
	│   │   │   ├── stdout/
	│   │   │   ├── stderr/
	│   │   │   ├── screenshots/
	│   │   │   ├── traces/
	│   │   │   └── browser_console.json
	│   │   ├── run_002/
	│   │   └── run_003/
	│   ├── final_report.md
	│   └── failure_analysis.md
	│
	├── .agents/
	│   ├── planner.prompt.md
	│   ├── generator.prompt.md
	│   ├── runner.prompt.md
	│   └── evaluator.prompt.md
	│
	├── skills/
	│   ├── web-e2e/
	│   ├── playwright-e2e/
	│   ├── file-manager/
	│   └── ...
	│
	├── logs/
	├── screenshots/
	├── src/
	├── tests/
	├── package.json
	└── AGENTS.md

	加入 search 产物
		.harness/
		├── task.json
		├── session.json
		├── plan.json
		├── policy.json
		├── budgets.json
		├── search/
		│   ├── search_001/
		│   │   ├── search_request.json
		│   │   ├── search_report.json
		│   │   ├── sources.json
		│   │   ├── pages/
		│   │   │   ├── S1.md
		│   │   │   └── S2.md
		│   │   └── citations.json
		│   └── search_002/
		├── runs/
		│   ├── run_001/
		│   └── run_002/
		└── final_report.md
```

---

## Harness 状态机

```text
class HarnessState:
    INIT = "INIT"
    PLAN = "PLAN"
    SEARCH = "SEARCH"
    VALIDATE_PLAN = "VALIDATE_PLAN"
    GENERATE = "GENERATE"
    APPLY_PATCH = "APPLY_PATCH"
    RUN = "RUN"
    EVALUATE = "EVALUATE"
    REPAIR = "REPAIR"
    REPLAN = "REPLAN"
    PASS = "PASS"
    FAIL_HARD = "FAIL_HARD"

状态流
    INIT
     ↓
    PLAN
     ↓
    VALIDATE_PLAN
     ↓
    Harness Search Gate
     ├── need_search = true  → SEARCH
     └── need_search = false → GENERATE
    SEARCH
     ↓
    GENERATE
     ↓
    APPLY_PATCH
     ↓
    RUN
     ↓
    EVALUATE
     ├── PASS         → PASS
     ├── FIXABLE      → GENERATE
     ├── REPLAN       → REPLAN
     ├── needs_search → SEARCH
     └── FAIL_HARD    → FAIL_HARD

核心规则
    1. Evaluator 不能直接触发 Runner。
    2. Runner 不能直接触发 Generator。
    3. Generator 不能直接触发 Runner。
    4. Search 不能直接触发 Generator、Runner、Planner 或 Evaluator。
    5. 所有 Agent 输出必须先给 Harness。
    6. Harness 校验 JSON schema 后才进入下一步。
```

## 完整权限配置

```text
	agents:
	  Planner:
	    role: planning_only
	    tools: []
	    input:
	      - TaskContext
	      - ProjectSummary
	      - PreviousFailures
	      - SearchReport optional
	    output:
	      - PlanContract

	  Search:
	    role: external_research_only
	    tools:
	      - web-search-free
	      - search
	      - web-scraper-pro
	      - firecrawl-scraper
	      - skill-lookup
	    input:
	      - SearchRequest
	    output:
	      - SearchReport

	  Generator:
	    role: code_patch_only
	    tools:
	      - filesystem
	      - file-manager
	    input:
	      - PlanContract
	      - ProjectFilesSnapshot
	      - EvalVerdict optional
	      - RunReport optional
	      - SearchReport optional
	    output:
	      - PatchResult

	  Runner:
	    role: execution_and_evidence_only
	    tools:
	      - desktop-commander
	      - Skill Management = python runtime
	      - playwright-e2e
	      - web-testing-playwright-e2e
	      - e2e
	      - computer-use
	    input:
	      - PlanContract
	      - PatchResult
	      - SearchReport optional
	    output:
	      - RunReport

	  Evaluator:
	    role: judgment_only
	    tools: []
	    input:
	      - PlanContract
	      - PatchResult
	      - RunReport
	      - SearchReport optional
	      - Screenshots
	      - GitDiffSummary
	    output:
	      - EvalVerdict
```

---

## 闭环

```text
	1. Planner 生成 PlanContract
	2. Harness 检查 external_research.required
	3. 如果需要，调用 Search
	4. Search 输出 SearchReport
	5. Harness 把 SearchReport 注入 Generator 输入
	6. Generator 修改代码
	7. Runner 执行 build / test / e2e
	8. Evaluator 判断
	9. 如果是 API/文档不确定问题，Evaluator 标记 needs_search
	10. Harness 再调用 Search
	11. 根据 SearchReport 回到 Planner / Generator / Runner

	Planner：决定怎么做，是否需要外部资料
	Search：查资料，只输出 SearchReport
	Generator：根据计划和资料改代码
	Runner：运行和采证据
	Evaluator：根据证据判断是否通过
	Harness：控制所有输入输出、权限、预算、状态流
```

---

## 全局输入输出数据结构

TaskContext

```json
{
  "task_id": "task_20260510_001",
  "session_id": "session_1778229077123",
  "user_request": "生成一个忍者跑酷小游戏",
  "workspace": "/Users/wangshuang/PycharmProjects/obs",
  "created_at": "2026-05-10T18:21:00+08:00",
  "mode": "agent",
  "permission_policy": "ask",
  "sandbox_mode": "workspace-write",
  "project_summary": {
    "project_type": "vite-react",
    "package_manager": "npm",
    "entry_files": [
      "src/main.tsx",
      "src/App.tsx"
    ],
    "scripts": {
      "dev": "vite",
      "build": "vite build",
      "lint": "eslint ."
    }
  },
  "global_constraints": {
    "max_total_steps": 14,
    "max_repair_rounds": 3,
    "max_replan_rounds": 1,
    "max_search_calls_per_task": 2,
    "overall_timeout_sec": 600
  }
}
```

### Search Agent

#### Search Agent Prompt

- **角色**：你是 Search Agent。
- **职责**：根据 Harness 提供的 `SearchRequest` 执行外部检索、网页抓取和资料摘要。
- **边界**：只能搜索、抓取、阅读和总结资料，不能修改代码、不能执行 shell 命令、不能启动本地应用、不能调用 Generator / Runner / Planner / Evaluator、不能判断最终任务是否通过。
- **输出要求**：必须输出严格 JSON 格式的 `SearchReport`。

**可使用的工具**

- `web-search-free`
- `search：Brave / Serper / Exa / Perplexity`
- `web-scraper-pro`
- `firecrawl-scraper`
- `skill-lookup`

**搜索原则**

1. 优先官方文档、GitHub README、框架文档、API 文档。
2. 如果是库/API 用法，优先查官方文档。
3. 如果是 bug/error，优先查官方 issue、StackOverflow、GitHub issue，但要标记可信度。
4. 不要无限搜索。
5. 不要抓取与任务无关的网页。
6. 不要使用低可信来源作为唯一依据。
7. 如果资料之间冲突，必须说明冲突。
8. 如果没有找到可靠资料，必须明确说明 `insufficient_evidence = true`。
9. 对每条关键结论提供 `source`。
10. 输出内容要服务于 Generator 或 Planner，不要写长篇科普。

**安全规则**

- 不允许登录网站。
- 不允许访问用户私有账号。
- 不允许下载可执行文件。
- 不允许绕过付费墙。
- 不允许访问恶意网站。
- 不允许把网页代码直接执行。
- 不允许把搜索结果直接写入项目文件。

**输出必须是 JSON**

```json
{
  "schema_version": "1.0",
  "task_id": "",
  "round_id": 0,
  "search_id": "",
  "query_summary": "",
  "status": "SUCCESS | PARTIAL | FAILED",
  "insufficient_evidence": false,
  "sources": [],
  "key_findings": [],
  "implementation_guidance": [],
  "risks": [],
  "recommended_next_agent": "Planner | Generator | Runner | Evaluator | None",
  "raw_artifacts": []
}
```

#### Search Agent 输入结构：SearchRequest

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "search_id": "search_001",
  "triggered_by": "Planner | Generator | Runner | Evaluator | Harness",
  "reason": "需要确认 Playwright Python locator 的正确用法",
  "research_questions": [
    {
      "id": "Q1",
      "question": "Playwright Python 中 page.locator() 是否需要 await？",
      "priority": "high"
    },
    {
      "id": "Q2",
      "question": "Playwright Python 中正确点击 locator 的写法是什么？",
      "priority": "high"
    }
  ],
  "queries": [
    "Playwright Python page.locator await usage",
    "Playwright Python locator click async"
  ],
  "allowed_domains": [
    "playwright.dev"
  ],
  "blocked_domains": [],
  "max_results": 5,
  "max_pages_to_scrape": 3,
  "freshness": "recent",
  "source_preference": [
    "official_docs",
    "github_repo",
    "github_issues",
    "stackoverflow",
    "blog"
  ],
  "context": {
    "error_message": "object Locator can't be used in 'await' expression",
    "related_component": "Runner playwright-e2e script",
    "current_assumption": "可能错误地 await 了 page.locator()"
  },
  "permissions": {
    "allow_web_search": true,
    "allow_scrape": true,
    "allow_login": false,
    "allow_download": false,
    "allow_execute_remote_code": false
  }
}
```

#### Search Agent 输出结构：SearchReport

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "search_id": "search_001",
  "query_summary": "确认 Playwright Python locator 的 async 用法",
  "status": "SUCCESS",
  "insufficient_evidence": false,
  "sources": [
    {
      "id": "S1",
      "title": "Playwright Python Locators",
      "url": "https://playwright.dev/python/docs/locators",
      "source_type": "official_docs",
      "retrieved_at": "2026-05-10T18:40:00+08:00",
      "credibility": "high",
      "relevance": "high"
    }
  ],
  "key_findings": [
    {
      "id": "F1",
      "question_id": "Q1",
      "finding": "在 Playwright Python 中 page.locator() 返回 Locator 对象，本身不需要 await。",
      "source_ids": [
        "S1"
      ],
      "confidence": 0.95
    },
    {
      "id": "F2",
      "question_id": "Q2",
      "finding": "异步 API 中通常是 locator = page.locator(selector)，然后 await locator.click()。",
      "source_ids": [
        "S1"
      ],
      "confidence": 0.95
    }
  ],
  "implementation_guidance": [
    {
      "target": "Runner playwright-e2e script",
      "guidance": "把 button = await page.locator('text=开始游戏') 改为 button = page.locator('text=开始游戏')，点击时使用 await button.click()。",
      "applies_to": "Runner",
      "risk": "low"
    }
  ],
  "risks": [
    "如果项目使用的是 JS Playwright 而不是 Python Playwright，API 写法略有不同，需要 Runner 根据运行环境选择模板。"
  ],
  "recommended_next_agent": "Runner",
  "raw_artifacts": [
    {
      "type": "scraped_markdown",
      "path": ".harness/search/search_001/pages/S1.md"
    }
  ]
}
```

#### Harness 中 Search Gate 设计

```python
def should_search(ctx, plan=None, run_report=None, eval_verdict=None):
    if ctx.user_request_contains_web_lookup:
        return True

    if plan and plan.get("external_research", {}).get("required"):
        return True

    if run_report:
        for err in run_report.get("errors", []):
            if err["type"] in [
                "UNKNOWN_API_USAGE",
                "DEPENDENCY_VERSION_ERROR",
                "THIRD_PARTY_SDK_ERROR"
            ]:
                return True

            if err["type"] == "RUNNER_SCRIPT_ERROR" and err.get("root_category") == "UNKNOWN_API_USAGE":
                return True

    if eval_verdict and eval_verdict.get("needs_search"):
        return True

    return False
```

- **默认规则**：`RUNNER_SCRIPT_ERROR` 默认归类为 `INFRA`，不直接交给 Generator，也不默认触发 Search。
- **例外规则**：只有当 Runner 错误属于第三方 API 用法不确定，例如 Playwright API 变更、SDK 文档不清楚时，才允许 Search。

#### Search Agent 在流程中的位置

```text
Planner 后 Search 适合：任务一开始就需要资料
    PLAN
      ↓
    if PlanContract.external_research.required:
      SEARCH
      ↓
    GENERATE

    例子：
        帮我接入 Stripe 支付
        帮我用最新 OpenAI Responses API
        帮我爬某个网页做 RAG

Runner 后 Search 适合：第三方 API / SDK 用法不确定
    RUN
      ↓
    RunReport 出现 UNKNOWN_API_USAGE / THIRD_PARTY_SDK_ERROR
      ↓
    SEARCH
      ↓
    GENERATE 或 EVALUATE

    例如：
        Module API changed
        Playwright locator await error
        第三方 SDK 文档不清楚

Evaluator 后 Search 适合：Evaluator 判断“信息不足”
    EVALUATE
      ↓
    needs_search = true
      ↓
    SEARCH
      ↓
    REPLAN or GENERATE
```

- **注意**：普通 Runner 脚本错误默认不进入 Search；只有同时命中 `UNKNOWN_API_USAGE` 时才进入 Search。

#### Search Budget: Search Agent 很容易失控，所以必须有独立 budget

```json
{
  "search_budget": {
    "max_search_calls_per_task": 2,
    "max_queries_per_search": 4,
    "max_results_per_query": 5,
    "max_pages_to_scrape": 3,
    "max_total_scraped_tokens": 20000,
    "timeout_sec": 120,
    "allow_recursive_search": false
  }
}
```

**硬规则**

1. Search Agent 不能连续调用自己。
2. 每次最多 4 个 query。
3. 每个 query 最多取 5 条结果。
4. 最多 scrape 3 个页面。
5. 默认只采官方文档和高可信来源。
6. 搜索完成必须回 Harness。

#### Search 权限策略 .harness/policy.json

```json
{
  "agent_permissions": {
    "Search": {
      "tools": [
        "web-search-free",
        "search",
        "web-scraper-pro",
        "firecrawl-scraper",
        "skill-lookup"
      ],
      "can_read_files": false,
      "can_write_files": false,
      "can_run_commands": false,
      "can_use_browser": false,
      "can_use_search": true,
      "can_scrape_web": true,
      "allowed_write_paths": [
        ".harness/search/**"
      ],
      "forbidden_write_paths": [
        "src/**",
        "app/**",
        "components/**",
        "package.json",
        ".env",
        ".git/**",
        "node_modules/**"
      ],
      "allow_login": false,
      "allow_download": false,
      "allow_execute_remote_code": false,
      "max_pages_to_scrape": 3
    }
  }
}
```

#### Search Agent 和其他 Agent 的关系

```text
		Search 不直接把结果发给 Generator。
		SearchReport 先进入 Harness。
		Harness 校验后，再决定是否给 Generator / Planner / Runner / Evaluator。

		Search Agent → SearchReport → Harness → Generator
```

### Planner Agent

#### Planner Prompt

- **角色**：你是 Planner Agent。
- **职责**：把用户任务转换成可执行的 `PlanContract`。
- **边界**：不能修改代码、不能执行命令、不能启动浏览器、不能调用工具，只能根据用户需求、项目摘要、历史失败信息进行规划。
- **输出要求**：只能输出严格 JSON，不能输出 Markdown，不能输出解释文字。

**PlanContract 必须包含**

1. `goal`
2. `assumptions`
3. `implementation_strategy`
4. `allowed_files`
5. `forbidden_files`
6. `required_files_to_inspect`
7. `implementation_steps`
8. `test_commands`
9. `dev_server`
10. `smoke_tests`
11. `acceptance_criteria`
12. `repair_policy`
13. `rollback_policy`
14. `external_research`
15. `package_json_policy`
16. `risks`

**规划原则**

- 优先最小可运行版本 MVP。
- 不要一次性设计过度复杂功能。
- 每个 step 必须可验证。
- `allowed_files` 必须尽量收窄。
- `forbidden_files` 必须保护 `.env`、`.git`、`node_modules`、lock 文件、系统目录。
- `test_commands` 必须根据 `project_summary` 中的 `package_manager` 和 `scripts` 生成。
- `smoke_tests` 只定义测试意图，不执行测试。
- 如果项目信息不足，输出需要 Generator 检查的文件列表，而不是自己执行检查。
- 如果用户任务是网页应用或小游戏，必须包含 browser smoke test。
- 默认不允许修改 `package.json`，只有任务确实需要时才通过 `package_json_policy` 显式放开。
- 如果任务有明显风险，写入 `risks`，但不要拒绝。

**你只能输出如下 JSON 结构**

```json
{
  "schema_version": "1.0",
  "task_id": "",
  "goal": "",
  "assumptions": [],
  "implementation_strategy": "",
  "allowed_files": [],
  "forbidden_files": [],
  "required_files_to_inspect": [],
  "implementation_steps": [],
  "test_commands": [],
  "dev_server": {},
  "smoke_tests": [],
  "acceptance_criteria": [],
  "repair_policy": {},
  "rollback_policy": {},
  "external_research": {
    "required": false,
    "reason": "",
    "queries": [],
    "allowed_domains": [],
    "max_results": 5,
    "max_pages_to_scrape": 3,
    "freshness": "stable",
    "search_agent_required": false
  },
  "package_json_policy": {
    "allow_modify": false,
    "allow_add_scripts": false,
    "allow_add_dependencies": false,
    "requires_approval": true
  },
  "risks": []
}
```

#### Planner 输入

```json
{
  "task_context": {
    "task_id": "task_20260510_001",
    "user_request": "生成一个忍者跑酷小游戏",
    "workspace": "/Users/wangshuang/PycharmProjects/obs",
    "project_summary": {
      "project_type": "vite-react",
      "package_manager": "npm",
      "entry_files": [
        "src/main.tsx",
        "src/App.tsx"
      ],
      "scripts": {
        "dev": "vite",
        "build": "vite build",
        "lint": "eslint ."
      }
    }
  },
  "previous_failures": []
}
```

#### Planner 输出：PlanContract

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "goal": "实现一个可运行的忍者跑酷小游戏 MVP",
  "assumptions": [
    "项目是前端 Web 项目",
    "可以使用现有 src 目录实现游戏",
    "优先保证可运行和可交互，不追求复杂美术"
  ],
  "implementation_strategy": "先实现单页面 MVP，包括开始游戏、跳跃、投掷、加速、障碍物、碰撞、得分和重新开始。",
  "allowed_files": [
    "src/**",
    "app/**",
    "components/**",
    "public/**",
    "index.html"
  ],
  "forbidden_files": [
    ".env",
    ".env.*",
    ".git/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".harness/**",
    "logs/**",
    "screenshots/**",
    "package.json"
  ],
  "required_files_to_inspect": [
    "package.json",
    "src/main.tsx",
    "src/App.tsx",
    "src/index.css"
  ],
  "implementation_steps": [
    {
      "id": "S1",
      "title": "检查项目入口",
      "description": "确认前端入口文件和样式文件位置。",
      "expected_output": "确定需要修改的文件。"
    },
    {
      "id": "S2",
      "title": "实现游戏 MVP",
      "description": "实现忍者角色、障碍物、分数、生命、开始和重开逻辑。",
      "expected_output": "页面显示游戏 UI，按钮和键盘操作可用。"
    },
    {
      "id": "S3",
      "title": "补充基础样式",
      "description": "让页面在浏览器中清晰可见。",
      "expected_output": "无明显布局错乱。"
    }
  ],
  "test_commands": [
    {
      "name": "build",
      "cmd": "npm run build",
      "timeout_sec": 120,
      "required": true
    },
    {
      "name": "lint",
      "cmd": "npm run lint",
      "timeout_sec": 60,
      "required": false
    }
  ],
  "dev_server": {
    "enabled": true,
    "start_cmd": "npm run dev -- --host 0.0.0.0",
    "url": "http://localhost:5173",
    "ready_patterns": [
      "Local:",
      "ready in",
      "localhost"
    ],
    "timeout_sec": 60
  },
  "smoke_tests": [
    {
      "id": "page_load",
      "type": "browser",
      "action": "goto",
      "target": "http://localhost:5173",
      "expect": {
        "page_loaded": true,
        "text_contains_any": [
          "忍者",
          "跑酷",
          "开始"
        ],
        "no_fatal_console_error": true
      },
      "timeout_sec": 15,
      "required": true
    },
    {
      "id": "click_start",
      "type": "browser",
      "action": "click",
      "selector_candidates": [
        "text=开始游戏",
        "#startBtn",
        "[data-testid='start-button']",
        "button"
      ],
      "expect": {
        "no_fatal_console_error": true,
        "visual_change": true
      },
      "timeout_sec": 10,
      "required": true
    },
    {
      "id": "keyboard_space",
      "type": "browser",
      "action": "keyboard",
      "key": "Space",
      "expect": {
        "no_fatal_console_error": true
      },
      "timeout_sec": 5,
      "required": true
    }
  ],
  "acceptance_criteria": [
    "构建命令 npm run build 必须通过",
    "页面必须能打开，不能白屏",
    "页面必须展示游戏标题或开始按钮",
    "开始游戏按钮必须可点击",
    "按 Space 后不能出现致命错误",
    "失败或结束后应可以重新开始"
  ],
  "repair_policy": {
    "max_repair_rounds": 3,
    "repair_scope": "minimal_patch",
    "do_not_rewrite_whole_project": true,
    "if_same_error_repeats": "REPLAN"
  },
  "rollback_policy": {
    "snapshot_before_patch": true,
    "rollback_on_invalid_patch": true,
    "preserve_harness_artifacts": true
  },
  "external_research": {
    "required": false,
    "reason": "",
    "queries": [],
    "allowed_domains": [],
    "max_results": 5,
    "max_pages_to_scrape": 3,
    "freshness": "stable",
    "search_agent_required": false
  },
  "package_json_policy": {
    "allow_modify": false,
    "allow_add_scripts": false,
    "allow_add_dependencies": false,
    "requires_approval": true
  },
  "risks": [
    "如果项目没有 npm scripts，需要 Runner 返回 INFRA_ERROR",
    "如果端口 5173 被占用，需要 Runner 自动选择备用端口并写入 RunReport"
  ]
}
```

### Generator Agent

#### Generator Prompt

- **角色**：你是 Generator Agent。
- **职责**：根据 Harness 提供的 `PlanContract` 或 `EvalVerdict` 进行代码修改。
- **边界**：只能修改 `PlanContract.allowed_files` 中允许的文件，不能修改 `PlanContract.forbidden_files` 中的任何文件，不能执行构建、测试、启动服务、浏览器自动化，不能调用 Runner，也不能自行判断最终是否完成。
- **输出要求**：必须输出严格 JSON。

**如果输入中包含 SearchReport**

- 只能使用 `key_findings` 和 `implementation_guidance` 中与当前任务相关的信息。
- 优先采用官方文档来源。
- 不要复制大段网页内容。
- 不要实现 `SearchReport` 未覆盖的额外功能。
- 如果 `SearchReport.insufficient_evidence = true`，不要凭空实现不确定 API。

**工作模式**

1. **首次生成**
   - 阅读 `required_files_to_inspect` 中的文件。
   - 根据 `implementation_steps` 做最小可运行实现。
   - 尽量少改文件。
   - 输出 `PatchResult` 与 `PatchEnvelope`。
2. **修复模式**
   - 只根据 `EvalVerdict.repair_instruction` 修复问题。
   - 不要重写整个项目。
   - 不要扩大修改范围。
   - 如果无法修复，输出 `needs_replan = true`。

**代码修改原则**

- 保证代码可构建。
- 优先简单稳定，不追求复杂效果。
- 避免引入新依赖，除非 `PlanContract` 明确允许。
- 默认不允许修改 `package.json`，除非 `package_json_policy.allow_modify = true`。
- 不要删除用户已有核心代码，除非任务明确要求。
- 不要修改 `.env`、`.git`、`node_modules`、`dist`、`build`、`.harness`、`logs`。
- 每次输出 `changed_files`、`summary`、`commands_to_run`。
- `commands_to_run` 只是建议，不能自己执行。

**输出 JSON 格式**

```json
{
  "schema_version": "1.0",
  "task_id": "",
  "round_id": 0,
  "mode": "initial | repair",
  "changed_files": [],
  "created_files": [],
  "deleted_files": [],
  "summary": "",
  "implementation_notes": [],
  "commands_to_run": [],
  "risk_points": [],
  "patch_envelope": {
    "schema_version": "1.0",
    "task_id": "",
    "round_id": 0,
    "patch_type": "unified_diff | file_replacement | str_replace",
    "operations": []
  },
  "needs_replan": false,
  "replan_reason": ""
}
```

#### Generator 输入：首次生成

```json
{
  "task_id": "task_20260510_001",
  "round_id": 1,
  "mode": "initial",
  "workspace": "/Users/wangshuang/PycharmProjects/obs",
  "plan_contract": {
    "...": "PlanContract"
  },
  "project_files_snapshot": {
    "package.json": "{...}",
    "src/main.tsx": "...",
    "src/App.tsx": "...",
    "src/index.css": "..."
  },
  "harness_constraints": {
    "allowed_write_paths": [
      "src/**",
      "app/**",
      "components/**",
      "public/**",
      "index.html"
    ],
    "forbidden_write_paths": [
      ".env",
      ".env.*",
      ".git/**",
      "node_modules/**",
      "dist/**",
      "build/**",
      ".harness/**",
      "logs/**",
      "screenshots/**",
      "package.json"
    ],
    "package_json_policy": {
      "allow_modify": false,
      "allow_add_scripts": false,
      "allow_add_dependencies": false,
      "requires_approval": true
    },
    "allow_new_dependencies": false
  }
}
```

#### Generator 输入：修复模式

```json
{
  "task_id": "task_20260510_001",
  "round_id": 2,
  "mode": "repair",
  "workspace": "/Users/wangshuang/PycharmProjects/obs",
  "plan_contract": {
    "...": "PlanContract"
  },
  "previous_patch_result": {
    "...": "PatchResult"
  },
  "search_reports": [
    {
      "...": "SearchReport"
    }
  ],
  "run_report": {
    "...": "RunReport"
  },
  "eval_verdict": {
    "verdict": "FIXABLE",
    "failed_criteria": [
      "构建失败"
    ],
    "root_cause": "src/App.tsx 中 playerSpeed 未定义",
    "repair_instruction": "只在 src/App.tsx 中补充 playerSpeed 的定义，不要重写整个项目。"
  },
  "repair_round": 1,
  "max_repair_rounds": 3
}
```

#### Generator 输出：PatchResult

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "mode": "initial",
  "changed_files": [
    "src/App.tsx",
    "src/index.css"
  ],
  "created_files": [],
  "deleted_files": [],
  "summary": "实现忍者跑酷游戏 MVP，包括开始按钮、跳跃、投掷、加速、障碍物、碰撞、得分和重开。",
  "implementation_notes": [
    "使用 React state 管理游戏状态",
    "使用 requestAnimationFrame 驱动游戏循环",
    "使用键盘事件处理 Space、J、K"
  ],
  "commands_to_run": [
    {
      "name": "build",
      "cmd": "npm run build",
      "reason": "确认 TypeScript 和 Vite 构建通过"
    },
    {
      "name": "dev",
      "cmd": "npm run dev -- --host 0.0.0.0",
      "reason": "启动浏览器 smoke test"
    }
  ],
  "risk_points": [
    "如果 lint 规则严格，可能需要 Runner 返回具体 lint 信息后再修复"
  ],
  "patch_envelope": {
    "schema_version": "1.0",
    "task_id": "task_20260510_001",
    "round_id": 1,
    "patch_type": "str_replace",
    "operations": [
      {
        "op": "str_replace",
        "path": "src/App.tsx",
        "old_text": "...",
        "new_text": "..."
      }
    ]
  },
  "needs_replan": false,
  "replan_reason": ""
}
```

#### PatchEnvelope

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "patch_type": "unified_diff | file_replacement | str_replace",
  "operations": [
    {
      "op": "str_replace",
      "path": "src/App.tsx",
      "old_text": "...",
      "new_text": "..."
    }
  ],
  "changed_files": [
    "src/App.tsx"
  ]
}
```

#### Harness 应用 Patch 的顺序

```text
Generator 输出 PatchEnvelope
  ↓
Harness 校验路径
  ↓
Harness 校验 forbidden_files
  ↓
Harness dry-run
  ↓
Harness apply
  ↓
Harness 记录 diff.patch
```

### Runner Agent

#### Runner Prompt

- **角色**：你是 Runner Agent。
- **职责**：执行 Harness 指定的命令、启动应用、执行浏览器 smoke test，并采集证据。
- **边界**：不能修改业务代码、不能修复问题、不能判断最终是否通过、不能调用 Generator、不能调用 Planner。
- **输出要求**：只能输出严格 JSON 格式的 `RunReport`。

**可使用的能力**

- `terminal / bash`
- `python runtime`
- `playwright-e2e`
- `web-testing-playwright-e2e`
- `computer-use`
- `screenshot`
- `log collector`

**执行规则**

1. 按 `RunnerInput.test_commands` 顺序执行命令。
2. required 命令失败时，后续非必要命令可以跳过，但必须记录 `skip_reason`。
3. 如果 build 失败，一般不启动 dev server，除非 `RunnerInput.allow_dev_on_build_fail = true`。
4. 启动 dev server 时必须设置 timeout。
5. dev server 启动后必须检测 URL 是否可访问。
6. 执行 `smoke_tests` 时必须记录 `status`、`action`、`selector_used`、`console_errors`、`network_errors`、`screenshot path`。
7. 如果 `selector_candidates` 有多个，按顺序尝试。
8. 如果出现错误，只记录事实，不要修复。
9. 所有日志写入 `.harness/runs/run_xxx/`。
10. 测试结束后必须执行 cleanup，关闭 browser、停止 dev server、清理 orphan process。
11. Runner 脚本错误默认归因给 Runner / Harness，不归因给业务代码；只有命中第三方 API 用法不确定时才允许 Search。
12. 输出 `RunReport` JSON，不要输出额外解释。

**安全规则**

- 不允许写 `src/**`、`app/**`、`components/**`、`package.json`，除非 Harness 显式授权。
- 不允许执行 `rm -rf`。
- 不允许 `sudo`。
- 不允许 `curl | bash` 或 `wget | bash`。
- 不允许访问 workspace 外路径。
- 不允许安装依赖，除非 `allow_install = true`。
- 不允许联网搜索。

#### Runner 输入：RunnerInput

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "workspace": "/Users/wangshuang/PycharmProjects/obs",
  "run_dir": ".harness/runs/run_001",
  "plan_contract": {
    "...": "PlanContract"
  },
  "patch_result": {
    "...": "PatchResult"
  },
  "test_commands": [
    {
      "name": "build",
      "cmd": "npm run build",
      "timeout_sec": 120,
      "required": true
    },
    {
      "name": "lint",
      "cmd": "npm run lint",
      "timeout_sec": 60,
      "required": false
    }
  ],
  "dev_server": {
    "enabled": true,
    "start_cmd": "npm run dev -- --host 0.0.0.0",
    "url": "http://localhost:5173",
    "ready_patterns": [
      "Local:",
      "ready in",
      "localhost"
    ],
    "timeout_sec": 60
  },
  "smoke_tests": [
    {
      "id": "page_load",
      "type": "browser",
      "action": "goto",
      "target": "http://localhost:5173",
      "expect": {
        "page_loaded": true,
        "text_contains_any": [
          "忍者",
          "跑酷",
          "开始"
        ],
        "no_fatal_console_error": true
      },
      "timeout_sec": 15,
      "required": true
    },
    {
      "id": "click_start",
      "type": "browser",
      "action": "click",
      "selector_candidates": [
        "text=开始游戏",
        "#startBtn",
        "[data-testid='start-button']",
        "button"
      ],
      "expect": {
        "no_fatal_console_error": true,
        "visual_change": true
      },
      "timeout_sec": 10,
      "required": true
    }
  ],
  "runner_limits": {
    "max_command_retries": 0,
    "max_dev_server_retries": 2,
    "max_smoke_test_steps": 10,
    "overall_timeout_sec": 300
  },
  "permissions": {
    "allow_install": false,
    "allow_network": false,
    "can_write_project_files": false,
    "can_write_artifacts": true,
    "allow_write_paths": [
      ".harness/**",
      "logs/**",
      "screenshots/**",
      "tmp/**"
    ],
    "forbidden_write_paths": [
      "src/**",
      "app/**",
      "components/**",
      "package.json",
      ".env",
      ".git/**",
      "node_modules/**"
    ]
  },
  "search_reports": [
    {
      "search_id": "search_001",
      "implementation_guidance": [
        {
          "target": "Runner playwright-e2e script",
          "guidance": "page.locator() 不需要 await，locator.click() 需要 await。"
        }
      ]
    }
  ]
}
```

#### Runner 输出：RunReport

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "status": "FAILED",
  "started_at": "2026-05-10T18:30:00+08:00",
  "finished_at": "2026-05-10T18:31:12+08:00",
  "duration_sec": 72,
  "commands": [
    {
      "name": "build",
      "cmd": "npm run build",
      "exit_code": 1,
      "timeout": false,
      "duration_sec": 8,
      "required": true,
      "passed": false,
      "skipped": false,
      "stdout_log": ".harness/runs/run_001/stdout/build.stdout.log",
      "stderr_log": ".harness/runs/run_001/stderr/build.stderr.log",
      "stdout_tail": "vite v5.0.0 building...",
      "stderr_tail": "src/App.tsx:42:13 - error TS2304: Cannot find name 'playerSpeed'."
    },
    {
      "name": "lint",
      "cmd": "npm run lint",
      "exit_code": null,
      "timeout": false,
      "duration_sec": 0,
      "required": false,
      "passed": false,
      "skipped": true,
      "skip_reason": "Skipped because required command build failed.",
      "stdout_log": null,
      "stderr_log": null,
      "stdout_tail": "",
      "stderr_tail": ""
    }
  ],
  "dev_server": {
    "attempted": false,
    "start_cmd": "npm run dev -- --host 0.0.0.0",
    "url": "http://localhost:5173",
    "ready": false,
    "pid": null,
    "port": null,
    "stdout_log": null,
    "stderr_log": null,
    "stdout_tail": "",
    "stderr_tail": "Skipped because build failed."
  },
  "browser_tests": [
    {
      "id": "page_load",
      "status": "SKIPPED",
      "required": true,
      "reason": "dev server was not started",
      "screenshot": null,
      "console_errors": [],
      "network_errors": []
    }
  ],
  "artifacts": {
    "run_dir": ".harness/runs/run_001",
    "screenshots": [],
    "traces": [],
    "logs": [
      ".harness/runs/run_001/stdout/build.stdout.log",
      ".harness/runs/run_001/stderr/build.stderr.log"
    ],
    "browser_console": ".harness/runs/run_001/browser_console.json"
  },
  "cleanup": {
    "browser_closed": true,
    "dev_server_stopped": true,
    "orphan_processes_killed": []
  },
  "errors": [
    {
      "type": "PRODUCT_BUILD_ERROR",
      "message": "Cannot find name 'playerSpeed'",
      "file": "src/App.tsx",
      "line": 42,
      "column": 13,
      "severity": "error"
    }
  ],
  "summary": "Required build command failed, browser smoke tests were skipped."
}
```

#### Runner status 枚举

```text
		PASSED
		FAILED
		PARTIAL
		TIMEOUT
		SKIPPED
		INFRA_ERROR
		PASSED：所有 required command 和 required smoke test 通过
		FAILED：业务构建或页面测试失败
		PARTIAL：必需项通过，非必需项失败
		TIMEOUT：命令或整体执行超时
		SKIPPED：前置条件失败导致跳过
		INFRA_ERROR：环境问题，例如端口占用、依赖不存在、浏览器无法启动
```

### Evaluator Agent

#### Evaluator Prompt

- **角色**：你是 Evaluator Agent。
- **职责**：读取 `PlanContract`、`PatchResult`、`RunReport`、截图和日志摘要，然后判断任务是否通过。
- **边界**：不能执行命令、不能启动浏览器、不能修改代码、不能调用任何工具、不能调用 Generator、不能调用 Runner、不能进入自循环。
- **输出要求**：必须一次性输出 `EvalVerdict` JSON。

**判断规则**

1. 如果所有 required `test_commands` 和 required `smoke_tests` 都通过，并且满足 `acceptance_criteria`，输出 `PASS`。
2. 如果存在明确代码错误，例如 TypeScript 报错、变量未定义、selector 错误、按钮不可点，输出 `FIXABLE`。
3. 如果实现方向明显错误、目标理解错误、文件结构选择错误，输出 `REPLAN`。
4. 如果是 Runner 脚本、端口、浏览器环境、权限等问题，优先输出 `INFRA`，不要把问题丢给 Generator。
5. 只有当 Runner 错误同时属于第三方 API 用法不确定时，才设置 `needs_search = true` 并把 `next_agent` 设为 `Search`。
6. 如果同一 `root_cause` 已连续出现 2 次，建议 `REPLAN`。
7. `repair_instruction` 必须具体、可执行、范围小。
8. 不允许说“继续验证”或“我再试一次”。
9. 不允许输出 Markdown，只输出 JSON。

**输出 JSON 格式**

```json
{
  "schema_version": "1.0",
  "task_id": "",
  "round_id": 0,
  "verdict": "PASS | FIXABLE | REPLAN | FAIL_HARD | INFRA",
  "score": 0.0,
  "passed_criteria": [],
  "failed_criteria": [],
  "evidence": [],
  "root_cause": "",
  "repair_instruction": "",
  "needs_search": false,
  "search_questions": [],
  "next_agent": "None | Generator | Planner | Search",
  "confidence": 0.0,
  "stop_reason": ""
}
```

#### Evaluator 输入

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "plan_contract": {
    "...": "PlanContract"
  },
  "patch_result": {
    "...": "PatchResult"
  },
  "run_report": {
    "...": "RunReport"
  },
  "git_diff_summary": {
    "changed_files": [
      "src/App.tsx",
      "src/index.css"
    ],
    "diff_path": ".harness/runs/run_001/diff.patch"
  },
  "screenshots": [],
  "previous_eval_verdicts": []
}
```

#### Evaluator 输出：EvalVerdict

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 1,
  "verdict": "FIXABLE",
  "score": 0.45,
  "passed_criteria": [],
  "failed_criteria": [
    "构建命令 npm run build 必须通过",
    "页面必须能打开，不能白屏",
    "开始游戏按钮必须可点击"
  ],
  "evidence": [
    {
      "source": "run_report.commands[0].stderr_tail",
      "detail": "src/App.tsx:42:13 - error TS2304: Cannot find name 'playerSpeed'."
    }
  ],
  "root_cause": "Generator 在 src/App.tsx 中引用了未定义变量 playerSpeed，导致构建失败，Runner 无法启动 dev server 进行浏览器测试。",
  "repair_instruction": "Generator 只修改 src/App.tsx，补充 playerSpeed 的定义或移除错误引用，确保 npm run build 可以通过。不要重写整个游戏实现。",
  "needs_search": false,
  "search_questions": [],
  "next_agent": "Generator",
  "confidence": 0.95,
  "stop_reason": ""
}
```

#### 路由到Search的示范：

```json
{
  "schema_version": "1.0",
  "task_id": "task_20260510_001",
  "round_id": 2,
  "verdict": "INFRA",
  "score": 0.3,
  "passed_criteria": [],
  "failed_criteria": [
    "Runner 脚本执行失败"
  ],
  "evidence": [
    {
      "source": "run_report.errors[0]",
      "detail": "Runner 的 Playwright 脚本可能使用了错误的 Python async API。"
    }
  ],
  "root_cause": "Runner 的 Playwright 脚本错误，且属于第三方 API 用法不确定。",
  "repair_instruction": "",
  "needs_search": true,
  "search_questions": [
    "Playwright Python 中 page.locator() 是否需要 await？",
    "异步 Playwright Python 中 locator.click() 的正确写法是什么？"
  ],
  "next_agent": "Search",
  "confidence": 0.8,
  "stop_reason": "需要先确认外部 API 用法，再决定后续修复。"
}
```

## Harness Policy 设计（建议单独做一个 .harness/policy.json）

```json
{
  "schema_version": "1.0",
  "sandbox_mode": "workspace-write",
  "approval_policy": "ask",
  "workspace_root": "/Users/wangshuang/PycharmProjects/obs",
  "protected_paths": [
    ".env",
    ".env.*",
    ".git/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".harness/state.json"
  ],
  "package_json_policy": {
    "allow_modify": false,
    "allow_add_scripts": false,
    "allow_add_dependencies": false,
    "requires_approval": true
  },
  "agent_permissions": {
    "Planner": {
      "tools": [],
      "can_read_files": false,
      "can_write_files": false,
      "can_run_commands": false,
      "can_use_browser": false,
      "can_use_search": false
    },
    "Search": {
      "tools": [
        "web-search-free",
        "search",
        "web-scraper-pro",
        "firecrawl-scraper",
        "skill-lookup"
      ],
      "can_read_files": false,
      "can_write_files": false,
      "can_run_commands": false,
      "can_use_browser": false,
      "can_use_search": true,
      "can_scrape_web": true,
      "allowed_write_paths": [
        ".harness/search/**"
      ],
      "forbidden_write_paths": [
        "src/**",
        "app/**",
        "components/**",
        "package.json",
        ".env",
        ".git/**",
        "node_modules/**"
      ],
      "allow_login": false,
      "allow_download": false,
      "allow_execute_remote_code": false,
      "max_pages_to_scrape": 3
    },
    "Generator": {
      "tools": [
        "filesystem",
        "file-manager"
      ],
      "can_read_files": true,
      "can_write_files": true,
      "can_run_commands": false,
      "can_use_browser": false,
      "can_use_search": false,
      "allowed_write_paths": [
        "src/**",
        "app/**",
        "components/**",
        "public/**",
        "index.html"
      ],
      "forbidden_write_paths": [
        ".env",
        ".env.*",
        ".git/**",
        "node_modules/**",
        "dist/**",
        "build/**",
        ".harness/**",
        "package.json"
      ]
    },
    "Runner": {
      "tools": [
        "desktop-commander",
        "Skill Management = python runtime",
        "playwright-e2e",
        "web-testing-playwright-e2e",
        "e2e",
        "computer-use"
      ],
      "can_read_files": true,
      "can_write_project_files": false,
      "can_write_artifacts": true,
      "can_run_commands": true,
      "can_use_browser": true,
      "can_use_search": false,
      "allowed_write_paths": [
        ".harness/**",
        "logs/**",
        "screenshots/**",
        "tmp/**"
      ],
      "forbidden_write_paths": [
        "src/**",
        "app/**",
        "components/**",
        "package.json",
        ".env",
        ".git/**",
        "node_modules/**"
      ]
    },
    "Evaluator": {
      "tools": [],
      "can_read_files": true,
      "can_write_files": false,
      "can_run_commands": false,
      "can_use_browser": false,
      "can_use_search": false
    }
  },
  "command_policy": {
    "allowed_commands": [
      "npm run build",
      "npm run lint",
      "npm test",
      "npm run test",
      "npm run dev",
      "pnpm build",
      "pnpm lint",
      "pnpm test",
      "pnpm dev",
      "yarn build",
      "yarn lint",
      "yarn test",
      "yarn dev",
      "python",
      "pytest",
      "node"
    ],
    "blocked_patterns": [
      "rm -rf /",
      "sudo",
      "curl .*\\|.*bash",
      "wget .*\\|.*bash",
      "chmod -R 777",
      "chown -R",
      "kill -9 -1",
      "dd if=",
      "mkfs",
      "diskutil erase"
    ],
    "network_default": false,
    "install_default": false,
    "restrict_to_runner_input_commands": true,
    "require_timeout": true,
    "command_mode": "argv_or_escaped_shell"
  }
}
```

## Path Safety Rules

1. 所有路径必须 canonicalize。
2. 禁止绝对路径写入。
3. 禁止使用 `../` 逃出 workspace。
4. 禁止跟随 symlink 写入 workspace 外。
5. `forbidden_files` 优先级高于 `allowed_files`。
6. 如果 `allowed_files` 和 `forbidden_files` 冲突，以 `forbidden_files` 为准。

```python
def is_path_allowed(path, allowed, forbidden, workspace):
    real_path = resolve_realpath(workspace / path)
    if not str(real_path).startswith(str(resolve_realpath(workspace))):
        return False
    if matches_any(path, forbidden):
        return False
    if not matches_any(path, allowed):
        return False
    return True
```

## Command Safety Rules

1. Runner 只能执行 `test_commands` 和 `dev_server.start_cmd`。
2. 命令必须是数组形式或经过 shell escaping。
3. 禁止 shell 拼接用户输入。
4. 每个命令必须有 timeout。
5. dev server 必须记录 pid，并在结束时 kill。
6. 后台进程必须进入 process group，避免残留。
7. 如果端口占用，Runner 可以切换端口，但必须写入 `RunReport`。

## Runner Process Lifecycle

1. 启动 dev server 前检查端口。
2. 启动后记录 `pid`、`port`、`url`。
3. ready check 通过后再跑 browser smoke tests。
4. 测试结束后必须关闭 browser。
5. 测试结束后必须停止 dev server。
6. 如果 Runner 崩溃，Harness cleanup 阶段负责 kill orphan process。

## Budget 控制（.harness/budgets.json）

```json
{
  "schema_version": "1.0",
  "max_total_steps": 14,
  "max_planner_calls": 2,
  "max_generator_calls": 4,
  "max_runner_calls": 4,
  "max_evaluator_calls": 4,
  "max_search_calls_per_task": 2,
  "max_repair_rounds": 3,
  "max_replan_rounds": 1,
  "max_same_error_repeats": 2,
  "timeouts": {
    "planner_sec": 60,
    "generator_sec": 180,
    "runner_sec": 300,
    "evaluator_sec": 60,
    "search_sec": 120,
    "command_default_sec": 120,
    "dev_server_sec": 60,
    "browser_test_sec": 60
  }
}
```

#### 最关键的硬规则：

```text
Evaluator 每轮最多调用 1 次。
Runner 每轮最多调用 1 次。
Generator 每轮最多调用 1 次。
Search 每个任务最多调用 2 次。
同一错误连续出现 2 次，不能继续 FIXABLE，必须 REPLAN 或 FAIL_HARD。
```

## Harness 主流程伪代码

```python
def run_task(user_request: str):
    ctx = create_task_context(user_request)
    ctx.search_reports = []
    state = "PLAN"

    repair_round = 0
    replan_round = 0
    total_steps = 0
    history = []
    plan = None
    patch_result = None
    run_report = None
    verdict = None

    while total_steps < ctx.budget.max_total_steps:
        total_steps += 1
        save_state(ctx, state, repair_round, replan_round)

        if state == "PLAN":
            planner_input = build_planner_input(ctx, history)
            save_agent_input("Planner", planner_input)
            plan = call_agent("Planner", planner_input)
            validate_schema(plan, "PlanContract")
            validate_plan_policy(plan, ctx.policy)
            save_json(".harness/plan.json", plan)
            state = "SEARCH" if should_search(ctx, plan=plan) else "GENERATE"

        elif state == "SEARCH":
            search_request = build_search_request(ctx, plan, run_report, verdict, history)
            save_agent_input("Search", search_request)
            search_report = call_agent("Search", search_request)
            validate_schema(search_report, "SearchReport")
            save_json(search_path(ctx.search_id, "search_report.json"), search_report)
            ctx.search_reports.append(search_report)

            if search_report["status"] == "FAILED" or search_report["insufficient_evidence"]:
                state = "REPLAN"
            else:
                state = route_after_search(search_report, plan=plan, verdict=verdict)

        elif state == "GENERATE":
            generator_input = build_generator_input(
                ctx,
                plan,
                history,
                search_reports=ctx.search_reports,
                eval_verdict=verdict,
                run_report=run_report,
            )
            save_agent_input("Generator", generator_input)
            patch_result = call_agent("Generator", generator_input)
            validate_schema(patch_result, "PatchResult")

            if patch_result.get("needs_replan"):
                state = "REPLAN"
                continue

            patch_envelope = patch_result["patch_envelope"]
            validate_patch_policy(patch_result, plan, ctx.policy)
            validate_patch_envelope(patch_envelope, plan, ctx.policy)
            dry_run_patch(patch_envelope)
            apply_patch_envelope(patch_envelope)
            save_diff_for_round(ctx.round_id)
            state = "RUN"

        elif state == "RUN":
            runner_input = build_runner_input(ctx, plan, patch_result, ctx.search_reports)
            save_agent_input("Runner", runner_input)
            run_report = call_agent("Runner", runner_input)
            validate_schema(run_report, "RunReport")
            save_json(run_path("run_report.json"), run_report)
            state = "EVALUATE"

        elif state == "EVALUATE":
            evaluator_input = build_evaluator_input(
                ctx,
                plan,
                patch_result,
                run_report,
                history,
                search_reports=ctx.search_reports,
            )
            save_agent_input("Evaluator", evaluator_input)
            verdict = call_agent("Evaluator", evaluator_input)
            validate_schema(verdict, "EvalVerdict")
            save_json(run_path("eval_verdict.json"), verdict)

            history.append({
                "round_id": ctx.round_id,
                "run_report": run_report,
                "eval_verdict": verdict,
            })

            decision = build_harness_decision(ctx, verdict, repair_round, replan_round)
            save_json(run_path("harness_decision.json"), decision)

            if verdict["verdict"] == "PASS":
                state = "PASS"
            elif verdict.get("needs_search"):
                state = "SEARCH"
            elif verdict["verdict"] == "FIXABLE":
                repair_round += 1
                if repair_round > ctx.budget.max_repair_rounds:
                    state = "REPLAN"
                elif same_error_repeated(history, ctx.budget.max_same_error_repeats):
                    state = "REPLAN"
                else:
                    ctx.round_id += 1
                    state = "GENERATE"
            elif verdict["verdict"] == "REPLAN":
                state = "REPLAN"
            elif verdict["verdict"] in ["FAIL_HARD", "INFRA"]:
                state = "FAIL_HARD"

        elif state == "REPLAN":
            replan_round += 1
            if replan_round > ctx.budget.max_replan_rounds:
                state = "FAIL_HARD"
            else:
                repair_round = 0
                state = "PLAN"

        elif state == "PASS":
            return finalize_success(ctx, history)

        elif state == "FAIL_HARD":
            cleanup_orphans(ctx)
            return finalize_failure(ctx, history)

    cleanup_orphans(ctx)
    return finalize_failure(ctx, history, reason="max_total_steps reached")
```

## HarnessDecision 输出结构

```json
{
  "task_id": "task_20260510_001",
  "round_id": 1,
  "decision": "PASS | CALL_GENERATOR | CALL_PLANNER | CALL_SEARCH | FAIL_HARD",
  "reason": "",
  "next_state": "GENERATE",
  "next_agent": "Generator",
  "budget_remaining": {
    "repair_rounds": 2,
    "replan_rounds": 1,
    "search_calls": 1
  }
}
```

## Resume / Recovery

1. 每次状态变化都写入 `.harness/state.json`。
2. 每个 Agent 调用前保存 input。
3. 每个 Agent 返回后保存 output。
4. 如果进程中断，Harness 从 `state.json` 恢复。
5. 如果上一次停在 `RUN`，先执行 cleanup，再决定是否重跑 Runner。
6. 如果上一次停在 `APPLY_PATCH`，检查 `diff.patch` 是否已经应用。

#### .harness/state.json 示例

```json
{
  "task_id": "task_20260510_001",
  "round_id": 2,
  "state": "EVALUATE",
  "last_completed_state": "RUN",
  "last_artifact": ".harness/runs/run_002/output/run_report.json",
  "repair_round": 1,
  "replan_round": 0,
  "search_call_count": 1
}
```

## Artifact Manifest

```json
{
  "task_id": "task_20260510_001",
  "artifacts": [
    {
      "type": "plan",
      "path": ".harness/plan.json"
    },
    {
      "type": "patch",
      "path": ".harness/runs/run_001/diff.patch"
    },
    {
      "type": "run_report",
      "path": ".harness/runs/run_001/output/run_report.json"
    },
    {
      "type": "screenshot",
      "path": ".harness/runs/run_001/screenshots/page_load.png"
    }
  ]
}
```

## 错误分类 Taxonomy

```text
Harness 固定错误类型
    PRODUCT_BUILD_ERROR
    PRODUCT_RUNTIME_ERROR
    PRODUCT_UI_ERROR
    PRODUCT_REQUIREMENT_MISS

    RUNNER_SCRIPT_ERROR
    RUNNER_TIMEOUT
    RUNNER_BROWSER_ERROR
    RUNNER_PORT_ERROR

    INFRA_DEPENDENCY_MISSING
    INFRA_INSTALL_FORBIDDEN
    INFRA_NETWORK_FORBIDDEN
    INFRA_PERMISSION_DENIED

    HARNESS_SCHEMA_ERROR
    HARNESS_POLICY_VIOLATION
    HARNESS_MAX_ITERATION
```

**Evaluator 根据错误类型决定**

- `PRODUCT_*` → `FIXABLE / REPLAN`
- `RUNNER_*` → `INFRA`，默认不交给 Generator
- `RUNNER_SCRIPT_ERROR + UNKNOWN_API_USAGE` → `Search`
- `INFRA_*` → `FAIL_HARD / INFRA`
- `HARNESS_*` → `FAIL_HARD`

| 错误类型 | 处理方 |
| --- | --- |
| `PRODUCT_BUILD_ERROR` | Generator |
| `PRODUCT_RUNTIME_ERROR` | Generator |
| `PRODUCT_UI_ERROR` | Generator |
| `PRODUCT_REQUIREMENT_MISS` | Planner 或 Generator |
| `RUNNER_SCRIPT_ERROR` | Harness / Runner Skill |
| `RUNNER_TIMEOUT` | Runner 或 Harness |
| `RUNNER_BROWSER_ERROR` | Runner / Harness |
| `RUNNER_PORT_ERROR` | Runner / Harness |
| `INFRA_DEPENDENCY_MISSING` | Harness，必要时 Ask 用户 |
| `INFRA_INSTALL_FORBIDDEN` | Harness / User Approval |
| `INFRA_NETWORK_FORBIDDEN` | Harness / Search Gate |
| `INFRA_PERMISSION_DENIED` | Harness |
| `HARNESS_SCHEMA_ERROR` | Harness |
| `HARNESS_POLICY_VIOLATION` | Harness |
| `HARNESS_MAX_ITERATION` | Harness |

- **目标**：避免把 Runner 的 Playwright 脚本错误错误地丢给 Generator。

## 建议优先级

```text
	1. playwright-e2e
	2. web-testing-playwright-e2e
	3. e2e 基础模板
	4. computer-use

	playwright-e2e：最可复现，适合自动测试
	web-testing-playwright-e2e：适合封装页面断言
	e2e：适合基础模板
	computer-use：更像视觉操作，适合兜底，不适合作为第一选择

	默认都不开放
		web-search-free
		search：Brave / Serper / Exa / Perplexity
		web-scraper-pro
		firecrawl-scraper
	只有这些任务才启用
		用户明确要求查网页
		需要读取外部文档
		需要查 API 最新用法
		需要抓网页内容做 RAG
	权限分配
		Planner：可以提出 need_web_research = true，但不能自己搜
		Harness：判断是否允许
		Runner 或 Research Worker：执行搜索
		Evaluator：只读搜索结果
```

---

## AGENTS.md 建议内容

```text
	# AGENTS.md

	## Project Rules

	- 所有 Agent 的输入输出必须通过 Harness。
	- Agent 之间不能直接调用。
	- Planner 和 Evaluator 不允许使用工具。
	- Generator 只允许修改 allowed_files。
	- Runner 只允许执行命令和浏览器测试，不允许修改业务代码。
	- 所有运行产物必须写入 `.harness/runs/run_xxx/`。
	- 失败时必须结构化输出错误类型。

	## Coding Rules

	- 优先最小可运行实现。
	- 不要引入新依赖，除非明确允许。
	- 不要修改 `.env`、`.git`、`node_modules`、`dist`、`build`。
	- 修复时只做最小 patch，不要重写整个项目。

	## Testing Rules

	- 前端项目必须执行 build。
	- Web 项目必须执行至少一个页面加载 smoke test。
	- 游戏类项目必须测试开始按钮和至少一个键盘操作。
	- Runner 脚本错误不能归因于业务代码
```

---

## 前端体验改造建议：面向用户视图的 Codex-like 交互层

### 目标

当前前端的主要问题不是功能少，而是**信息呈现过于接近 Agent 内部日志**。像下面这类信息：

- `[Evaluator] bash`
- `[Evaluator] code_sandbox`
- `max iterations reached`
- `object Locator can't be used in await expression`

这些内容对开发者调试有用，但对普通用户观感较差。

前端应当默认展示：

- **我正在做什么**
- **已经完成什么**
- **当前卡在哪里**
- **下一步准备做什么**
- **是否需要用户批准**

而不是直接展示：

- 哪个 Agent 调用了哪个底层工具
- Python / Playwright / shell 的原始异常
- 内部重试次数、迭代次数、子任务限制

### 核心原则

前端不应直接渲染 Agent 内部日志，而应增加一层 **面向用户的摘要映射层**：

```text
Raw Agent Log
  ↓
Harness User-Facing Summary
  ↓
UI
```

更具体地说：

```text
Raw Agent Events
  ↓
Harness Normalizer
  ↓
UserEvent
  ↓
UI Components
```

### 三层展示模型

#### Level 1：用户视图

默认只展示：

- 任务状态
- 步骤进度
- 当前问题
- 下一步动作
- 是否需要确认

#### Level 2：开发者视图

按需展示：

- 文件 diff
- 测试结果
- 错误摘要
- 运行证据

#### Level 3：调试视图

仅在 Debug 模式展开：

- Raw logs
- stdout / stderr
- tool calls
- PlanContract / RunReport / EvalVerdict JSON

### 页面信息架构

建议页面改成 4 个区域：

```text
┌──────────────────────────────────────────────┐
│ Header: 任务名 / 状态 / 进度 / 权限 / 用时      │
├───────────────────────┬──────────────────────┤
│ Main Timeline          │ Right Preview Panel   │
│ 清晰步骤流              │ 预览/截图/差异/建议     │
├───────────────────────┴──────────────────────┤
│ Composer: 输入框 / Send / Permission / Model   │
└──────────────────────────────────────────────┘
```

布局建议：

- **顶部**：任务状态总览
- **中间左侧**：线性的步骤时间线
- **中间右侧**：当前结果、截图、预览、修复建议
- **底部**：用户输入区
- **隐藏区**：Debug Logs / Raw Tool Calls

### 任务状态栏

顶部建议增加一个任务状态胶囊，展示：

- 当前状态
- 当前轮次
- 已用时长
- 剩余修复预算
- 当前阶段

示例：

```text
● 正在验证 · 第 2/4 轮 · 已用 1m 42s · 还可修复 2 次
当前阶段：Runner
```

#### 推荐状态文案

| 英文状态 | 中文文案 | 颜色 |
| --- | --- | --- |
| `Thinking` | 正在分析 | 蓝色 |
| `Planning` | 正在制定计划 | 蓝色 |
| `Editing` | 正在修改文件 | 绿色 |
| `Running` | 正在运行命令 | 紫色 |
| `Testing` | 正在验证页面 | 紫色 |
| `Reviewing` | 正在检查结果 | 黄色 |
| `Needs approval` | 等待确认 | 橙色 |
| `Blocked` | 遇到阻塞 | 红色 |
| `Done` | 已完成 | 绿色 |

不要把下面这些直接当成用户主状态：

- `code_sandbox`
- `bash completed`
- `max iterations`
- `subtask limit`

这些只应进入调试视图。

### 中间区域改成 Timeline，而不是 Agent 卡片

当前 `Planner / Generator / Evaluator` 三张并排卡片，不利于用户理解当前流程卡在哪一步。

建议改成线性的 `Timeline`：

```text
任务进度
✅ 1. 分析项目结构
   识别到 Vite / React 项目，入口文件 src/App.tsx
✅ 2. 制定实现计划
   生成 5 个实施步骤和 6 条验收标准
✅ 3. 修改代码
   修改 2 个文件：src/App.tsx、src/index.css
⚠️ 4. 运行验证
   页面已打开，但自动点击脚本失败
⏸ 5. 等待处理
   这是测试脚本问题，不是游戏代码问题
```

每个 Timeline item 建议控制在 **3 行以内**，展开后再显示详情。

### 每一步的简短状态卡

示例：

```text
✅ 修改代码
2 files changed · +184 -12
实现了开始、跳跃、投掷、加速、碰撞检测

⚠️ 浏览器验证
页面已加载，但点击测试脚本失败
不是业务代码错误

✅ 构建通过
npm run build · 8.4s

❌ 构建失败
src/App.tsx:42 未定义 playerSpeed
可自动修复
```

### 当前问题卡片

当任务卡住时，不应该把原始异常直接展示为主内容，而应该转成用户能理解的问题卡：

```text
验证脚本出错
页面已经成功打开，但自动化测试脚本在点击按钮时写法有问题。
这不是游戏代码本身的问题。

建议操作：
[自动修复测试脚本] [查看技术细节] [停止任务]
```

### 下一步动作区

每次 `HarnessDecision` 后，前端应显示一段面向用户的下一步说明：

```text
下一步
建议修复 Runner 测试脚本，然后重新验证页面交互。
即将执行：
1. 修复 Playwright locator await 用法
2. 重新启动 dev server
3. 重新点击“开始游戏”
4. 截图并生成验收结果

[继续] [修改计划] [查看详情]
```

这样用户会感觉系统知道自己在做什么，而不是单纯“报错了”。

### 原始日志进入二级面板

底部可以保留日志区，但建议改成 Tab：

- `Overview`
- `Changes`
- `Tests`
- `Logs`
- `JSON`

#### Tab 内容建议

- **Overview**：用户友好摘要
- **Changes**：文件变化、diff
- **Tests**：build / lint / e2e 状态
- **Logs**：stdout / stderr / tool call
- **JSON**：PlanContract / RunReport / EvalVerdict

默认展示 `Overview`，不要默认展示 Raw Tool Calls。

### 用户可读事件类型

Harness 内部事件不要直接显示给用户，应增加一层 `UserEvent` 映射。

#### 原始内部事件示例

```json
{
  "agent": "Evaluator",
  "tool": "code_sandbox",
  "status": "failed",
  "error": "object Locator can't be used in 'await' expression"
}
```

#### 转换后的用户事件

```json
{
  "type": "validation_issue",
  "severity": "warning",
  "title": "自动化验证脚本出错",
  "summary": "页面已成功打开，但点击按钮的测试脚本写法有问题。",
  "details": "Playwright 的 locator() 不能直接 await，应改为 locator = page.locator(...); await locator.click()。",
  "is_user_action_required": false,
  "recommended_action": "修复 Runner 测试脚本并重新验证",
  "debug_ref": ".harness/runs/run_001/output/run_report.json"
}
```

前端默认只显示 `UserEvent`，原始日志放到 Debug 区域。

### 建议新增 `display_summary` 字段

每个 Agent 输出给 Harness 的 JSON，建议都增加一个面向 UI 的摘要字段。

#### Generator 示例

```json
{
  "display_summary": {
    "title": "已完成代码修改",
    "status": "success",
    "summary": "实现了忍者跑酷小游戏 MVP。",
    "highlights": [
      "新增开始 / 重新开始逻辑",
      "支持 Space 跳跃、J 投掷、K 加速",
      "添加障碍物、得分和生命值"
    ],
    "user_visible": true
  }
}
```

#### Runner 示例

```json
{
  "display_summary": {
    "title": "验证遇到问题",
    "status": "warning",
    "summary": "页面已打开，但自动点击测试脚本出错。",
    "highlights": [
      "页面加载成功",
      "错误来自测试脚本，不是游戏代码",
      "可以自动修复后重新验证"
    ],
    "user_visible": true
  }
}
```

#### Evaluator 示例

```json
{
  "display_summary": {
    "title": "需要修复 Runner 验证脚本",
    "status": "blocked",
    "summary": "Evaluator 未能完成验收，因为 Runner 的 Playwright 脚本写法错误。",
    "next_step": "修复测试脚本后重新运行浏览器验证。"
  }
}
```

### 错误文案翻译规则

不要直接把底层错误当主文案展示。

#### 不推荐

- `Evaluator max iterations reached without verdict`
- `[Evaluator] bash 完成`
- `[Evaluator] code_sandbox 失败`
- `Error during test: object Locator can't be used in 'await' expression`

#### 推荐文案

- **验收未完成**
  - 原因：自动化验证脚本出错，未能得到有效验收结果。
  - 建议：修复 Runner 测试脚本后重新验证。
- **已运行浏览器验证**
- **验证脚本执行失败**
- **测试脚本写法错误：Playwright locator 不应直接 await**

### 最终结果区域

任务结束时，前端应给用户一个清晰的成功或失败总结。

#### 成功示例

```text
完成情况
✅ 已实现忍者跑酷小游戏 MVP
✅ 已通过 npm run build
✅ 页面可以正常打开
✅ 开始按钮可以点击
✅ Space / J / K 操作无控制台致命错误

修改文件
- src/App.tsx
- src/index.css

验证
- build: 通过，8.4s
- browser smoke test: 通过
- console errors: 0

你可以继续让我：
- 加音效
- 加排行榜
- 加移动端触控
```

#### 失败示例

```text
任务暂未完成
卡在：浏览器自动化验证
原因：Runner 的 Playwright 脚本使用了错误的 await 写法
影响：无法确认“开始游戏”按钮是否能被自动点击
建议：先修复 Runner 测试脚本，再重新验证
这不是当前游戏代码的构建错误。
```

### 主标题不要直接显示 Agent 名称

用户更关心的是**当前任务阶段**，而不是哪个 Agent 在工作。

#### 不推荐

- Planner
- Generator
- Evaluator

#### 推荐

- **主标题**：正在生成小游戏
- **副标题**：计划完成 · 代码已修改 · 验证遇到测试脚本问题
- **辅助标签**：由 Evaluator 发现 / 由 Runner 执行

### 推荐页面组件

#### 1. `TaskHeader`

```text
任务：生成一个小游戏：玩家控制忍者跑酷
状态：验证遇到问题
进度：3 / 5
用时：1m 24s
权限：ask
```

#### 2. `ProgressTimeline`

```text
✅ 分析项目
✅ 制定计划
✅ 修改代码
⚠️ 运行验证
⏸ 等待处理
```

#### 3. `CurrentIssueCard`

```text
验证脚本出错
页面已加载成功，但自动点击“开始游戏”时测试脚本失败。
这不是游戏代码错误。
建议操作：
[修复测试脚本并重试] [查看日志]
```

#### 4. `EvidencePanel`

```text
证据
- Page loaded successfully
- Error: object Locator can't be used in 'await' expression
- Screenshot: page_load.png
```

#### 5. `DebugDrawer`

```text
Raw Tool Calls
- [Evaluator] bash
- [Evaluator] code_sandbox
- stdout
- stderr
- RunReport JSON
```

### 前端事件归一化逻辑

```javascript
function normalizeEvent(event) {
  if (event.error?.includes("Locator can't be used in 'await'")) {
    return {
      type: "validation_issue",
      severity: "warning",
      title: "自动化验证脚本出错",
      summary: "页面已加载成功，但点击按钮的测试脚本写法有问题。",
      detail: "Playwright locator() 不应直接 await。",
      nextAction: "修复 Runner 测试脚本后重新验证",
      debugRef: event.artifactPath
    };
  }

  if (event.tool === "bash" && event.status === "completed") {
    return {
      type: "command_completed",
      severity: "success",
      title: "命令执行完成",
      summary: event.displayName ?? event.command
    };
  }

  return {
    type: "debug",
    severity: "info",
    title: "内部事件",
    summary: event.summary,
    hiddenByDefault: true
  };
}
```

### 针对当前界面的直接改法

当前类似：

```text
Planner 完成
Generator 完成
Evaluator 失败
[Evaluator] bash
[Evaluator] code_sandbox
```

建议改为：

```text
生成小游戏：玩家控制忍者跑酷
状态：验证遇到问题

✅ 已完成规划
   生成 5 个计划步骤
✅ 已完成代码修改
   实现 HTML / JS 绑定和游戏逻辑
⚠️ 自动化验证未完成
   页面已加载成功，但测试脚本点击按钮时出错

原因
Playwright 的 locator() 不能直接 await。
这属于 Runner 测试脚本问题，不是游戏代码问题。

下一步
修复 Runner 的 Playwright 脚本，然后重新运行浏览器验证。

[自动修复并重试] [查看日志] [停止]
```

技术细节作为折叠区：

```text
技术细节
Error during test: object Locator can't be used in 'await' expression
```

### 最重要的结论

你要的 Codex 观感，本质上不是换 UI 颜色，而是加一层：

```text
Raw Agent Log → Harness User-Facing Summary → UI
```

最终用户应该看到的是：

- 我完成了什么
- 现在卡在哪里
- 为什么卡住
- 下一步怎么做
- 需不需要我确认

而不是看到：

- 哪个 Agent 调了哪个底层工具
- 哪个 Python / Playwright / shell 报了什么内部异常
