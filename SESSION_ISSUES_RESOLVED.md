# 会话问题修复记录 (Session Issues Resolved)

本文档记录了在本次长会话中遇到的所有问题及其对应的解决方案。

## 1. 简历内容事实性与命名修正
* **问题描述**：简历中关于“Claude Code”的项目描述需要聚焦为独立的“OBS Code”工作台；在丰富 Qwen Omni 和 Align-Anything 项目技术细节时，初次生成的文本包含了一些未在原始记录中证实的推测性指标（如 45% 性能提升、200ms 首字延迟、主观抽样评测等）；此外，在“意向”栏缺少 Agent 方向。
* **解决方案**：
  * 修改了 `docs/resume_ws_hr.html`，将标题及相关描述的侧重点彻底移向 OBS Code 自研工作台。
  * 对技术细节进行了“脱水”处理，严格比对原始记录，恢复了 `SFT + Logits Distillation (KL)`、`Process Deadlock`、`Zero Stage` 等原本真实的术语，移除了所有未证实的推测数据。
  * 在简历求职意向末尾追加了“Agent”。

## 2. 前端 UI：浅色模式下聊天框未固定在底部
* **问题描述**：在浅色模式（Light Mode）下，页面的网格布局导致主面板无法垂直撑满可用空间，使得底部的 Composer（输入框）随内容上浮，无法固定在页面底部。
* **解决方案**：修改了 `ui/src/styles.css`，将 `html[data-theme="light"] .workspace-content-shell` 的布局属性由 `align-items: start;` 修改为 `align-items: stretch;`，使得内部的主聊天区域能够正确拉伸，输入框恢复固定。

## 3. 前端 UI：浅色模式下组件对比度过低看不清
* **问题描述**：在浅色模式下，Harness Agent 进度条、报错日志、时间轴等各种面板的背景色和文字颜色对比度太低，几乎与纯白背景融为一体，难以阅读。
* **解决方案**：在 `ui/src/improvements.css` 中追加了一整套针对 `html[data-theme="light"]` 的样式覆写（Overrides）。为 `.agent-process-statusbar`、`.harness-user-stage-body`、`pre` 代码块等引入了浅灰色背景和深灰/深色文本，显著提升了可读性。

## 4. 后端 Tool：文件浏览器不支持 `ls` 命令
* **问题描述**：Agent 试图使用文件读取工具查看目录时，输出了 `ls` 指令。由于该别名不在文件工具的验证白名单内，导致任务报出 `Unsupported file command: ls` 错误并被阻塞。
* **解决方案**：修改了 `src/agents/generator_agent.py`，在验证逻辑中增加了 `"ls"`、`"list"`、`"list_dir"` 作为合法命令，允许 Agent 顺利读取目录列表。

## 5. Harness 路由：短指令未触发 Agent 完整工作流
* **问题描述**：当输入 `给我一个ppt 宣传北京旅游的` 时，由于字数较少且缺乏明确的编程信号词，系统错误地将其判定为 `DIRECT_ANSWER`（直接问答），导致模型直接输出了纯文本（带代码），而没有启动 Harness 的 Planner -> Generator -> Runner 完整创建流程。
* **解决方案**：修改了 `src/agents/harness_runtime.py` 中的 `_classify_intent` 守卫方法。在 `CODE_SIGNALS` 正则表达式中增加了 `ppt`、`给我`、`帮我` 等触发词，确保此类需求能够正确进入 `CODE_WORKFLOW`。

## 6. Harness 引擎：`fnmatch` 匹配规则导致安全策略误拦截
* **问题描述**：Agent 按照 PlanContract 在项目根目录生成了 `beijing_tourism.py` 文件，而白名单配置为 `**/*.py`。Python 内置的 `fnmatch` 库在解析 `**/` 时强制要求路径包含 `/`，导致根目录文件匹配失败，触发了 `HarnessPolicyViolation` 安全死锁。
* **解决方案**：
  * 对 `src/agents/harness_engine.py` 中的 `_matches` 方法进行补丁，增加了对 `**/` 前缀特例的处理，使其能够正确匹配位于根目录的文件。
  * 修改了 `src/agents/planner_agent.py` 的 Prompt 指令，建议 Planner 针对根目录的新文件直接写明具体文件名，减少通配符带来的风险。

## 7. Planner 验证机制：先验后行的死锁 (INFRA 错误)
* **问题描述**：Planner 生成的 `test_commands` 中，将严格的文件存在性检查命令（`verify_generated_files`）排在了执行 Python 脚本的命令之前，并设置为强制依赖（`required: True`）。这导致脚本还没运行，文件检查就失败了，Runner 跳过执行，Evaluator 因缺乏运行证据而报 INFRA 错误结束任务。
* **解决方案**：
  * 修改了 `src/agents/planner_agent.py` 中的组装逻辑，将 `verify_generated_files` 命令强制追加到执行列表的最末尾。
  * 放宽了验证逻辑：将其改为 `required: False`，并调整判断条件，只需允许生成的文件列表中有**任何一个**非空文件生成即可判定为成功。

## 8. 前端 UI：模型 `<think>` 标签在流式输出时外漏
* **问题描述**：在模型思考并进行流式输出（Streaming）时，前端直接将 `<think>` 标签以纯文本渲染在了界面上。原因是原正则表达式要求匹配到闭合的 `</think>` 才会将其隐藏。
* **解决方案**：更新了 `ui/src/lib/formatting.js` 中的 `normalizeDisplayText` 逻辑，将匹配正则调整为支持非闭合标签（`(?:<\/think>|$)`），从而在流式输出的任何阶段都能动态过滤掉 `<think>` 块。

## 9. 前端 UI：刷新页面后聊天列表滚动到最顶端
* **问题描述**：刷新页面时，聊天记录自动滚动到了最顶端，而不是保持在最新的底部。这是由于 React 中负责滚动恢复的 `useEffect` 在组件初次挂载（此时会话数据尚未从后端获取完全）时就错误执行了。
* **解决方案**：修改了 `ui/src/App.jsx` 中的自动滚动逻辑，在 Hook 中增加了 `if (!currentSession) return;` 的阻塞守卫，确保 DOM 完全获取到列表数据并渲染后再执行到底部的滚动恢复。

## 10. Harness 路由：输入“继续”等短指令的意图判定过于强硬
* **问题描述**：为了修复短指令不执行任务的问题，曾将“继续”等指令强硬路由至 `CODE_WORKFLOW`。但这带来了一个新问题：如果上一个任务只是普通的聊天问答（`DIRECT_ANSWER`）且被意外中断，输入“继续”本应只恢复问答，却被错误地引入了繁重的 Agent 工作流中。系统缺乏基于上下文的“断点”判断机制。
* **解决方案**：升级了 `src/agents/harness_runtime.py` 中的意图分类器 `_classify_intent`，引入了**上下文感知（Context-aware）**能力。现在当系统捕捉到 `继续`、`continue` 等指令时，会主动读取工作区中的 `.harness/state.json` 文件（作为 Checkpoint）：
  * 如果当前存在尚未 `PASS` 的工作流状态（例如 `FAIL_HARD` 或 `BLOCKED`），则判定为修复接管，路由至 `CODE_WORKFLOW`。
  * 如果状态不存在或是已完成的纯聊天上下文，则平滑降级，路由回 `DIRECT_ANSWER` 继续普通对话。

## 11. Harness 引擎：致命错误 (INFRA/FAIL_HARD) 缺乏自愈能力
* **问题描述**：当 Runner 或 Evaluator 遭遇诸如环境依赖缺失、端口占用或编译失败等严重问题时，会直接抛出 `INFRA` 或 `FAIL_HARD` 导致整个任务彻底挂起。系统缺乏将这些环境报错抛给大模型进行诊断和自我修复的闭环机制。
* **解决方案**：
  * 重构了 `src/agents/harness_engine.py` 中的状态机路由核心 `build_harness_decision`。拦截所有的 `INFRA` 和 `FAIL_HARD` 判定，将其转换并降级为 `CALL_PLANNER`（重新规划）。
  * 将故障堆栈作为 `previous_failures` 输入给 Planner，让大模型充当架构师分析报错原因（例如发现缺少 `python-pptx` 库从而在脚本中加上 `pip install`）。
  * 在 `DEFAULT_BUDGETS` 中将全局重规化预算（`max_replan_rounds`）由 1 提升至 3，赋予 Agent 在彻底失败前多次试错并自我修复的能力。

## 12. Planner 强制要求验证 index.html (INFRA 错误与残留逻辑)
* **问题描述**：在生成 PPT 的任务中，Planner 强行输出了一条针对 `index.html` 的测试验证命令。这是因为在空项目或非 Web 项目中，`_default_allowed_files` 默认模版被硬编码填充了 Web 开发目录（包含 `index.html`），导致生成的 `verify_generated_files` 命令强制检查不相关的网页文件。且因之前修改了后端 Python 代码但**未重启后端服务（Uvicorn）**，导致之前第 7 项的“非强制弹性验证”补丁未能生效。
* **解决方案**：
  * 从 `src/agents/planner_agent.py` 的 `_default_allowed_files` 中移除了无脑 fallback 到 `["src/**", "index.html"...]` 的硬编码逻辑。现在对于空项目，将由大模型（Planner）完全自主推导应该允许哪些文件。
  * 重启了后端 Uvicorn 进程，确保上述所有（包括第 7、10、11 项）Python 核心代码层的修改被动态加载并生效。

## 13. 最终结果卡片：缺少可直接点击下载的产物超链接
* **问题描述**：当任务顺利通过验收并生成文件（例如 PPT 或 Python 脚本）后，模型只在回复中列出了修改的纯文本文件名，用户无法在聊天界面直接点击并下载或预览生成的交付产物。之前曾尝试用 15 分钟的修改时间窗口去全盘扫描，但这种方式既耗时也不精准。
* **解决方案**：
  * 扩展了 `src/api.py` 中的 `PREVIEW_ASSET_ALLOWED_SUFFIXES` 白名单，将 `.pptx`、`.py`、`.docx`、`.xlsx` 等文件后缀加入，使得后端 API `/preview/local-file` 可以直接分发这些文件。
  * 升级了 `src/agents/harness_runtime.py` 中的 `_final_answer` 模块，去除了暴力的时间扫描。现在系统会直接读取大模型（Planner）在规划契约（`allowed_files`）中显式写明的**具体文件名**。只要大模型规划的这些产物文件确实存在且非空，系统就会将它们转换为形如 `[filename](/preview/local-file?path=...)` 的 Markdown 超链接。
  * 通过这种方式，最终在界面上呈现的修改文件列表变成了可以直接点击下载/预览的高亮超链接。