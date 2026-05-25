# HARNESS ORCHESTRATOR SPEC

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
    "max_replan_rounds": 3,
    "max_search_calls_per_task": 2,
    "overall_timeout_sec": 600
  }
}
```

ContextBundle

`ContextBundle` 是 Harness 的统一记忆结构。它不是某个 Agent 私有的长期聊天历史，而是由 Harness 在每一轮状态转换前重新构造的一份有界上下文包，用来让 Planner、Search、Generator、Runner、Evaluator 在同一事实基础上工作。

核心目标：

1. **统一上下文来源**：所有 Agent 只读取 Harness 注入的 `ContextBundle` 和自己的角色契约输入，不直接读取彼此私有输出。
2. **控制上下文体积**：只保留最近消息摘要、上轮结构化结论和 artifact 索引，避免把完整日志、完整聊天历史、完整模型输出塞进模型。
3. **保留可追溯证据**：原始 stdout/stderr、浏览器 trace、截图、diff、SearchReport、RunReport、EvalVerdict 仍落在 `.harness/**`，`ContextBundle` 只保存它们的路径索引。
4. **支持修复闭环**：下一轮 Agent 能看到上一轮 `last_verdict`、`last_decision`、`open_failures`，但不会被无关历史污染。

当前内存边界：

| 字段 | 当前值 | 说明 |
|---|---:|---|
| `CONTEXT_MEMORY_MAX_MESSAGES` | `8` | 每个 session 最近最多保留 8 条对话消息摘要 |
| `CONTEXT_TEXT_LIMIT` | `1200` | 每条消息摘要最多 1200 字符 |
| `CONTEXT_BUNDLE_MAX_TEXT_CHARS` | `12000` | 整个 `ContextBundle` 序列化后最多约 12000 字符，超出后优先裁剪 artifact 索引和最长消息 |
| `artifact_index.max_items` | `24` | 每轮最多索引 24 个最新 Harness artifact |

构造来源：

| 来源 | 进入字段 | 处理方式 |
|---|---|---|
| 当前 `chat_sessions[session_id]` | `recent_messages` | 取最近 8 条，清理 provider thinking，单条截断 |
| 当前用户请求 | `current_user_request` | 截断后保留，用于本轮任务目标 |
| `session_context_cache[session_id]` | `working_memory` | 保留上一轮 plan/verdict/decision 的结构化摘要 |
| `previous_failures` | `working_memory.open_failures` | 保留最近失败原因，最多 6 条 |
| `.harness/**` | `artifact_index` | 只索引路径、类型、大小、更新时间，不内联原始日志 |
| Search / Eval 计数 | `search_report_count`、`previous_verdict_count` | 给 Agent 判断当前轮次证据密度 |

落盘路径：

```text
.harness/context/context_bundle.json
```

每次进入 Planner / Search / Generator / Runner / Evaluator 前，Harness 都应重建并落盘最新 `ContextBundle`。这保证后续调试可以复现某一轮 Agent 实际看到的记忆上下文。

注入规则：

| Agent | 注入位置 | 说明 |
|---|---|---|
| Planner | `task_context.context_bundle`，同时放入 `project_summary.context_bundle` | Planner 用它理解最近会话、失败历史和现有 artifact，但仍只能输出 PlanContract |
| Search | `context.context_bundle` | Search 用它理解为什么搜索、上一轮错误是什么，但不能写代码或判断最终通过 |
| Generator | 顶层 `context_bundle` | Generator 用它理解修复背景，同时仍必须遵守 `PlanContract.allowed_files` |
| Runner | 顶层 `context_bundle` | Runner 用它理解 artifact 目标和上一轮证据，但只能执行 Harness 给定命令 |
| Evaluator | 顶层 `context_bundle` | Evaluator 用它理解历史 verdict 和证据索引，但每轮只输出一个 EvalVerdict |

强制校验：

- Planner 输入必须包含 `task_context.context_bundle`
- Search 输入必须包含 `context.context_bundle`
- Generator / Runner / Evaluator 输入必须包含顶层 `context_bundle`
- 缺失时 Harness 应判为 `HARNESS_SCHEMA_ERROR` 或 policy violation，不允许 Agent 在无统一记忆的情况下继续运行

上下文裁剪策略：

1. 先构造完整 bundle。
2. 如果序列化长度超过 `CONTEXT_BUNDLE_MAX_TEXT_CHARS`，优先从 `artifact_index` 尾部删除较旧项目，保留至少 8 个 artifact。
3. 如果仍超限，找到最长 `recent_messages[*].content`，截到较小长度。
4. 如果仍超限，设置 `truncated = true`，保留剩余结构化字段。
5. 不裁剪 `session_id`、`workspace`、`current_user_request`、`working_memory.last_verdict`、`working_memory.open_failures` 等关键控制字段，除非字段内部文本按上限截断。

禁止事项：

- 不允许把完整 stdout/stderr 内联进 `ContextBundle`。
- 不允许把完整浏览器 trace、截图 base64、二进制文件内容内联进 `ContextBundle`。
- 不允许 Agent 自行扩展私有长期记忆后绕过 Harness。
- 不允许 SearchReport、RunReport、EvalVerdict 只存在于聊天文本中；必须落盘为 artifact 并由 `artifact_index` 引用。
- 不允许用关键词/正则从历史里硬推断任务类型；任务类型和搜索需求由 Router / Planner / Evaluator 的 LLM 语义判断与结构化契约决定。

```json
{
  "schema_version": "1.0",
  "session_id": "session_1778229077123",
  "workspace": "/Users/wangshuang/PycharmProjects/obs",
  "current_user_request": "生成一个忍者跑酷小游戏",
  "model": "minimax-m2",
  "request_mode": "agent",
  "history_policy": {
    "recent_messages_limit": 8,
    "text_limit_per_message": 1200,
    "max_bundle_chars": 12000,
    "raw_logs_policy": "artifact_only",
    "agent_context_rule": "Each agent receives this bounded ContextBundle plus its role-specific contract. Raw stdout, stderr, browser traces, and model transcripts stay in artifacts."
  },
  "recent_messages": [
    {
      "index": 1,
      "role": "user",
      "content": "生成一个忍者跑酷小游戏"
    }
  ],
  "working_memory": {
    "last_user_message": "生成一个忍者跑酷小游戏",
    "last_plan_goal": "",
    "last_decision": {
      "decision": "",
      "reason": "",
      "next_agent": ""
    },
    "last_verdict": {
      "verdict": "",
      "root_cause": "",
      "repair_instruction": ""
    },
    "open_failures": []
  },
  "artifact_index": [
    {
      "path": ".harness/runs/run_001/output/run_report.json",
      "kind": "run_report",
      "bytes": 2048,
      "modified_at": "2026-05-10T18:22:31+08:00"
    }
  ],
  "search_report_count": 0,
  "previous_verdict_count": 0
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
    "current_assumption": "可能错误地 await 了 page.locator()",
    "context_bundle": {}
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
      },
      "context_bundle": {}
    },
    "context_bundle": {}
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
