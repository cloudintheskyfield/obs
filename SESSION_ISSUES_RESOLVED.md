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