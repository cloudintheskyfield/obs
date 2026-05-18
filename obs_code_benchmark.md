# OBS Code Benchmark 评测方案

## 1. 目标

本文档用于规划 **OBS Code 助手** 的 Benchmark 测试方案。

OBS Code 是一个基于 Harness 的多 Agent 编程助手，包含：

- Planner Agent
- Search Agent
- Generator Agent
- Runner Agent
- Evaluator Agent
- Harness Orchestrator
- Codex-like Frontend UI

因此，测试不能只看“代码是否写对”，还要测试完整链路是否稳定：

1. Planner 是否能生成可执行计划
2. Generator 是否能输出安全 patch
3. Runner 是否能执行命令和浏览器验证
4. Evaluator 是否能正确归因错误
5. Search 是否只在必要时触发
6. Harness 是否能控制权限、状态、回滚和预算
7. 前端是否能给出 Codex-like 清晰反馈

---

## 2. 推荐 Benchmark 分层

| 层级 | Benchmark | 主要测试对象 | 推荐阶段 |
|---|---|---|---|
| L1 | OBS Mini Benchmark | Harness / 多 Agent 基础链路 | 必做，第一阶段 |
| L2 | CanItEdit | Generator 代码编辑能力 | 第二阶段 |
| L3 | OBS Web Bench | 前端 / 浏览器 / E2E 能力 | 第三阶段 |
| L4 | Terminal-Bench | Runner / 终端执行 / 环境处理 | 第四阶段 |
| L5 | SWE-bench Lite | 真实工程 issue 修复 | 第五阶段 |
| L6 | SWE-bench Verified | 最终真实工程对标 | 稳定后再做 |

---

## 3. L1：OBS Mini Benchmark

### 3.1 用途

OBS Mini Benchmark 是自建小型测试集，主要用来测试 OBS Code 的 Harness 和 Agent 架构是否稳定。

重点不是模型能力，而是验证：

- Planner 输出是否稳定
- JSON schema 是否正确
- patch 是否能被 Harness 应用
- Runner 是否正确执行命令
- Evaluator 是否正确路由错误
- Search 是否不会乱触发
- 禁止修改文件是否真的被保护
- 前端是否能显示清晰状态

---

### 3.2 建议任务数量

初期建议：

```text
30 ~ 50 个任务
```

后续可以扩展到：

```text
100 ~ 200 个任务
```

---

### 3.3 推荐任务类型

| 类型 | 示例 | 主要测试点 |
|---|---|---|
| React/Vite 小功能 | 添加按钮、计数器、小游戏 | Planner + Generator + Runner |
| TypeScript 构建错误 | undefined variable、type mismatch | Generator 修复能力 |
| CSS/UI 修改 | 修改布局、修复样式错位 | 小范围 patch |
| Python 小 bug | 修复函数逻辑错误 | 非前端链路 |
| 测试失败修复 | pytest / npm test fail | Runner + Evaluator |
| Runner 脚本错误 | Playwright API 用错 | 错误归因 |
| 禁止改文件 | `.env`、lock file、`.harness/**` | Policy Guard |
| package.json 限制 | 禁止新增依赖 | package_json_policy |
| Search 判定 | 普通任务不搜索，外部 API 才搜索 | Search Gate |
| 前端展示 | 用户友好 summary | Codex-like UI |

---

### 3.4 目录结构

```text
benchmarks/obs-mini/
├── task_001_react_counter/
│   ├── repo/
│   ├── task.md
│   ├── expected.json
│   └── tests/
├── task_002_ts_undefined_var/
│   ├── repo/
│   ├── task.md
│   ├── expected.json
│   └── tests/
├── task_003_runner_script_error/
│   ├── repo/
│   ├── task.md
│   ├── expected.json
│   └── tests/
└── task_004_package_json_forbidden/
    ├── repo/
    ├── task.md
    ├── expected.json
    └── tests/
```

---

### 3.5 `expected.json` 示例

```json
{
  "task_id": "task_001_react_counter",
  "must_pass": [
    "npm run build"
  ],
  "must_not_modify": [
    ".env",
    ".env.*",
    ".git/**",
    "node_modules/**",
    ".harness/**",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock"
  ],
  "expected_final_verdict": "PASS",
  "expected_error_route": "Generator",
  "max_rounds": 3,
  "requires_browser_smoke_test": true,
  "requires_search": false
}
```

---

## 4. L2：CanItEdit

### 4.1 用途

CanItEdit 适合测试 **Generator Agent 的代码编辑能力**。

CanItEdit 是一个代码编辑 benchmark，包含 105 个手写 Python 代码编辑任务，每个任务包含修改前代码、修改后代码、自然语言编辑指令和隐藏测试。它的目标是评估模型根据自然语言指令更新代码的能力。 [oai_citation:0‡arXiv](https://arxiv.org/html/2312.12450v6?utm_source=chatgpt.com)

---

### 4.2 适合测试什么

| 模块 | 是否适合 |
|---|---|
| Generator Agent | 非常适合 |
| PatchEnvelope | 非常适合 |
| str_replace | 非常适合 |
| file_replacement | 适合 |
| Runner | 一般 |
| Browser E2E | 不适合 |
| Search Agent | 不适合 |

---

### 4.3 接入方式

```text
CanItEdit task
  ↓
Harness 构造 PlanContract
  ↓
Generator 输出 PatchEnvelope
  ↓
Harness 应用 patch
  ↓
Runner 执行 hidden/public tests
  ↓
Evaluator 判断 PASS / FIXABLE / REPLAN
```

---

### 4.4 主要指标

```text
edit_success_rate
patch_apply_success_rate
test_pass_rate
needs_replan_rate
invalid_json_rate
```

---

## 5. L3：OBS Web Bench

### 5.1 用途

OBS Web Bench 是自建前端 Benchmark，用来测试 OBS Code 的前端应用开发能力和浏览器验证能力。

SWE-bench 更偏真实 GitHub issue 和后端/Python 项目，而 OBS Code 如果要做 Codex-like 网页应用开发，就必须单独测试：

- 页面是否白屏
- 按钮是否能点击
- 控制台是否报错
- 键盘交互是否工作
- Runner 是否能截图
- Evaluator 是否能区分产品错误和 Runner 错误
- 前端 UI 是否能展示用户友好反馈

---

### 5.2 推荐任务

```text
obs-web-bench/
├── vite-react-counter-bug/
├── vite-react-todo-add-feature/
├── react-button-click-console-error/
├── react-router-page-load/
├── css-layout-regression/
├── canvas-game-keyboard-control/
├── ninja-runner-game-mvp/
├── form-validation-error/
├── modal-close-bug/
└── playwright-selector-failure/
```

---

### 5.3 每题验证内容

```text
npm run build
npm run dev
browser goto
click primary button
keyboard interaction
screenshot
console errors
network errors
cleanup dev server
```

---

### 5.4 推荐 smoke tests

```json
[
  {
    "id": "page_load",
    "type": "browser",
    "action": "goto",
    "target": "http://localhost:5173",
    "expect": {
      "page_loaded": true,
      "no_fatal_console_error": true
    },
    "timeout_sec": 15,
    "required": true
  },
  {
    "id": "primary_button_click",
    "type": "browser",
    "action": "click",
    "selector_candidates": [
      "button",
      "[data-testid='start-button']",
      "text=开始"
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
    "required": false
  }
]
```

---

## 6. L4：Terminal-Bench

### 6.1 用途

Terminal-Bench 适合测试 **Runner Agent 和 Harness 的终端执行能力**。

Terminal-Bench 是用于评估 AI Agent 在真实终端环境中完成任务能力的 benchmark，覆盖编译代码、训练模型、设置服务等端到端任务。其 GitHub 说明中将它定位为测试 AI agents in real terminal environments 的 benchmark。 [oai_citation:1‡GitHub](https://github.com/harbor-framework/terminal-bench?utm_source=chatgpt.com)

Terminal-Bench 2.0 论文摘要提到，它包含 89 个困难任务，任务来自真实工作流启发的终端环境问题。 [oai_citation:2‡arXiv](https://arxiv.org/abs/2601.11868?utm_source=chatgpt.com)

---

### 6.2 适合测试什么

| 能力 | 说明 |
|---|---|
| 命令执行 | Runner 是否能按顺序执行命令 |
| 超时处理 | command timeout / overall timeout |
| 环境处理 | 缺依赖、权限、端口、路径 |
| 日志采集 | stdout / stderr / tail |
| cleanup | 是否清理进程 |
| 错误归因 | INFRA vs PRODUCT |
| Harness 状态机 | 是否能中断、恢复、回滚 |

---

### 6.3 不适合测试什么

```text
前端浏览器交互
UI 截图质量
Search Agent
用户友好前端展示
```

这些应交给 OBS Web Bench 和自建 Mini Benchmark。

---

## 7. L5：SWE-bench Lite

### 7.1 用途

SWE-bench Lite 适合做 OBS Code 的真实工程修复能力起步评测。

SWE-bench 是一个评估 AI 系统解决真实 GitHub 软件问题的 benchmark；给定代码库和 issue，系统需要生成能解决问题的 patch。 [oai_citation:3‡swebench.com](https://www.swebench.com/SWE-bench/?utm_source=chatgpt.com)

SWE-bench Lite 是 SWE-bench 的 300 任务子集，目标是降低评估成本、支持更快迭代，同时保持 benchmark 质量；官方说明它更聚焦自包含的功能 bug fix。 [oai_citation:4‡swebench.com](https://www.swebench.com/lite.html?utm_source=chatgpt.com)

---

### 7.2 推荐使用方式

不要一开始跑完整 300 题。

建议分阶段：

```text
Phase 1: 抽样 10 题
Phase 2: 抽样 50 题
Phase 3: 完整 300 题
```

---

### 7.3 测试完整链路

```text
Issue
  ↓
Planner 生成 PlanContract
  ↓
Generator 修改真实项目代码
  ↓
Runner 跑测试
  ↓
Evaluator 判断
  ↓
Harness 多轮修复 / 回滚 / 终止
```

---

### 7.4 主要指标

```text
resolved_rate
avg_rounds
avg_time_per_task
patch_apply_fail_rate
test_execution_fail_rate
infra_error_rate
wrong_route_rate
search_trigger_rate
schema_error_rate
```

---

## 8. L6：SWE-bench Verified

### 8.1 用途

SWE-bench Verified 适合作为 OBS Code 稳定后的最终真实工程对标。

SWE-bench Verified 是经过人工验证的 500 个 SWE-bench 实例子集，用于更可靠地评估 coding agents 和语言模型。 [oai_citation:5‡swebench.com](https://www.swebench.com/verified.html?utm_source=chatgpt.com)

---

### 8.2 使用建议

只有当以下条件满足后再跑 Verified：

```text
OBS Mini Benchmark pass rate > 90%
OBS Web Bench pass rate > 80%
CanItEdit pass rate 达到稳定水平
SWE-bench Lite 50 题抽样稳定
Runner infra error rate 可控
Evaluator wrong route rate 可控
```

---

### 8.3 最终对外指标

可以最终汇报：

```text
OBS Code on SWE-bench Lite: xx%
OBS Code on SWE-bench Verified: xx%
Average rounds per solved task: xx
Average time per task: xx
Infrastructure failure rate: xx%
Wrong routing rate: xx%
```

---

## 9. OBS Code 专属指标

除了 benchmark 的 pass rate，还必须记录 Harness 专属指标。

### 9.1 Schema 指标

```text
json_schema_success_rate
invalid_json_rate
missing_required_field_rate
wrong_field_type_rate
```

---

### 9.2 Patch 指标

```text
patch_apply_success_rate
patch_reject_rate
forbidden_file_touch_rate
absolute_path_attempt_rate
path_traversal_attempt_rate
lock_file_modify_attempt_rate
```

---

### 9.3 Runner 指标

```text
command_success_rate
command_timeout_rate
dev_server_start_success_rate
browser_smoke_test_success_rate
cleanup_success_rate
orphan_process_count
```

---

### 9.4 Evaluator 指标

```text
correct_error_route_rate
wrong_route_rate
runner_error_to_generator_rate
repeated_fix_loop_rate
false_pass_rate
false_fail_rate
```

---

### 9.5 Search 指标

```text
search_trigger_rate
unnecessary_search_rate
missed_search_rate
search_success_rate
insufficient_evidence_rate
official_source_ratio
```

---

### 9.6 UI 指标

```text
display_summary_present_rate
user_event_normalization_rate
raw_log_leak_rate
approval_card_correctness
final_summary_quality
```

---

## 10. 推荐执行路线

### Week 1：OBS Mini Benchmark

目标：

```text
验证 Harness + 5 Agent 基础链路
```

任务：

```text
30 个自建任务
覆盖前端、Python、Runner 错误、权限、Search Gate
```

通过标准：

```text
schema success rate > 95%
patch apply success rate > 90%
wrong route rate < 10%
Evaluator self-loop = 0
```

---

### Week 2：CanItEdit

目标：

```text
验证 Generator 的小范围代码编辑能力
```

任务：

```text
跑 105 个 CanItEdit 编辑任务
```

通过标准：

```text
patch apply success rate > 90%
test pass rate 稳定提升
needs_replan_rate 可控
```

---

### Week 3：OBS Web Bench

目标：

```text
验证前端开发 + 浏览器验证 + Codex-like UI
```

任务：

```text
20 个前端任务
```

通过标准：

```text
build pass rate > 85%
browser smoke pass rate > 80%
raw_log_leak_rate = 0
display_summary_present_rate > 95%
```

---

### Week 4：SWE-bench Lite 抽样

目标：

```text
验证真实工程 issue 修复能力
```

任务：

```text
先跑 10 题，再跑 50 题
```

通过标准：

```text
infra_error_rate 可控
wrong_route_rate 可控
resolved_rate 有稳定基线
```

---

### 稳定后：SWE-bench Lite 300 + Verified 500

目标：

```text
形成可对外展示的真实工程 benchmark 数据
```

---

## 11. Benchmark Runner 输出建议

每个任务统一输出：

```json
{
  "task_id": "",
  "benchmark": "",
  "final_verdict": "PASS",
  "resolved": true,
  "rounds": 2,
  "duration_sec": 180,
  "schema_success": true,
  "patch_apply_success": true,
  "commands_passed": true,
  "browser_tests_passed": true,
  "infra_error": false,
  "wrong_route": false,
  "search_triggered": false,
  "files_changed": [],
  "forbidden_files_touched": [],
  "final_summary": ""
}
```

---

## 12. Benchmark 汇总报告格式

```md
# OBS Code Benchmark Report

## Summary

| Benchmark | Tasks | Resolved | Rate | Avg Rounds | Avg Time | Infra Error |
|---|---:|---:|---:|---:|---:|---:|
| OBS Mini | 30 | 27 | 90% | 1.8 | 80s | 3% |
| CanItEdit | 105 | 75 | 71.4% | 1.2 | 20s | 0% |
| OBS Web | 20 | 16 | 80% | 2.1 | 120s | 5% |
| SWE-bench Lite 50 | 50 | 8 | 16% | 2.7 | 900s | 12% |

## Failure Breakdown

| Failure Type | Count | Notes |
|---|---:|---|
| PRODUCT_BUILD_ERROR | 12 | Mostly TS errors |
| RUNNER_SCRIPT_ERROR | 3 | Playwright selector issue |
| INFRA_DEPENDENCY_MISSING | 4 | Missing install permission |
| WRONG_ROUTE | 2 | Evaluator sent Runner error to Generator |

## Action Items

1. Improve Runner dev server cleanup.
2. Improve Generator patch locality.
3. Add stricter Evaluator route checks.
4. Add more frontend smoke tests.
```

---

## 13. 最终推荐

OBS Code 的 benchmark 不要只跑一个。

推荐组合是：

```text
OBS Mini Benchmark
+ CanItEdit
+ OBS Web Bench
+ Terminal-Bench
+ SWE-bench Lite
+ SWE-bench Verified
```

最重要的顺序是：

```text
先测 Harness 稳定性
再测代码编辑能力
再测浏览器和终端执行能力
最后测真实工程 issue 修复能力
```

一句话：

**OBS Code 的核心竞争力不是单次代码生成，而是 Harness 能否稳定规划、改代码、执行、验证、归因、修复和给用户清晰反馈。**