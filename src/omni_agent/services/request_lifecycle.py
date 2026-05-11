from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ..agents.harness_engine import HarnessEngine


@dataclass(frozen=True)
class LifecyclePhase:
    key: str
    default_content: str
    transient: bool = True


class RequestLifecycle:
    """Structured request phases for the harness/runtime layer.

    Inspired by Claude Code's explicit execution states: request ingress,
    session restore, context preparation, route selection, prompt assembly,
    model wait, tool execution, and final persistence.
    """

    PHASES: Dict[str, LifecyclePhase] = {
        "prep_context": LifecyclePhase("prep_context", "Loading session context"),
        "prep_route": LifecyclePhase("prep_route", "Selecting execution path"),
        "prep_prompt": LifecyclePhase("prep_prompt", "Assembling prompt"),
        "prep_model": LifecyclePhase("prep_model", "Waiting for model response"),
        "fast_path": LifecyclePhase("fast_path", "Running direct tool path"),
        "create": LifecyclePhase("create", "Scaffolding runnable application", transient=False),
        "battle": LifecyclePhase("battle", "Running battle contenders", transient=False),
        "compression_start": LifecyclePhase("compression_start", "Compressing conversation context", transient=False),
        "compression_complete": LifecyclePhase("compression_complete", "Context compression complete", transient=False),
    }

    def phase_payload(self, key: str, **overrides: Any) -> Dict[str, Any]:
        phase = self.PHASES.get(key, LifecyclePhase(key, key.replace("_", " ").title()))
        payload_type = overrides.pop("type", None)
        if payload_type is None:
            payload_type = phase.key if phase.key.startswith("compression_") else "phase"
        payload = {
            "type": payload_type,
            "phase": phase.key,
            "content": overrides.pop("content", phase.default_content),
            "transient": overrides.pop("transient", phase.transient),
        }
        payload.update(overrides)
        return payload

    def architecture_signature(self) -> Dict[str, Any]:
        harness = HarnessEngine().architecture_signature()
        return {
            "reference_style": "OBS agent + model + harness",
            "summary": {
                "zh": "统一 OBS Agent 内部由 Planner / Search / Generator / Runner / Evaluator 五个职责包组成，由 Harness 统一管理上下文、工具、编排、状态、评估、恢复。",
                "en": "A unified OBS Agent is internally composed of Planner / Search / Generator / Runner / Evaluator role packages, with the Harness managing context, tools, orchestration, state, evaluation, and recovery.",
            },
            "harness": harness,
            "flow": [
                {
                    "id": "client_ingress",
                    "lane_zh": "前端 UI",
                    "lane_en": "Client UI",
                    "title_zh": "Composer 组装 ChatStreamRequest",
                    "title_en": "Composer assembles ChatStreamRequest",
                    "module": "ui/src/App.jsx",
                    "entrypoints": ["sendMessage()"],
                    "role_zh": "把用户输入、图片、权限、技能选择和模型合并成单次请求；每个 thread 默认使用自己的隔离工作区。",
                    "role_en": "Merges user text, images, permission, skill selection, and model into a single request envelope; each thread defaults to its own isolated workspace.",
                    "inputs": ["message", "message_parts", "permission_mode", "enabled_skills", "model", "session workspace"],
                    "outputs": ["POST /chat/stream", "session_id", "tool_context", "harness strategy"],
                },
                {
                    "id": "api_ingress",
                    "lane_zh": "FastAPI",
                    "lane_en": "FastAPI",
                    "title_zh": "API 恢复线程状态并注入运行时上下文",
                    "title_en": "API restores thread state and injects runtime context",
                    "module": "src/omni_agent/api.py",
                    "entrypoints": ["chat_stream()", "_ensure_session_state_loaded()"],
                    "role_zh": "利用 SessionStore 恢复 chat_sessions 与压缩缓存，再注入日期、时区、位置、thread workspace 和线程目录等权威运行时字段。",
                    "role_en": "Uses SessionStore to restore chat sessions and compacted cache, then injects date, timezone, location, thread workspace, and runtime directory.",
                    "inputs": ["session_id", "workspace_path", "temporal_context", "session_locations"],
                    "outputs": ["chat_sessions[session_id]", "request_context", "thread_runtime_dir"],
                },
                {
                    "id": "planner",
                    "lane_zh": "Planner",
                    "lane_en": "Planner",
                    "title_zh": "模糊需求转完整规格与验收标准",
                    "title_en": "Ambiguous request to specification and acceptance criteria",
                    "module": "src/omni_agent/agents/harness_runtime.py + planner_agent.py + harness_engine.py",
                    "entrypoints": ["HarnessRuntime.chat_stream()", "PlannerAgent.plan()"],
                    "role_zh": "理解目标、判断缺失信息、选择最小工具集合，产出规格、假设、任务图和 Evaluator checklist。",
                    "role_en": "Understands target, judges missing information, chooses the minimum tool set, and produces spec, assumptions, task graph, and evaluator checklist.",
                    "inputs": ["current request", "relevant memory", "runtime context", "available tools"],
                    "outputs": ["spec", "assumptions", "task list", "acceptance checklist"],
                },
                {
                    "id": "context_harness",
                    "lane_zh": "上下文 Harness",
                    "lane_en": "Context Harness",
                    "title_zh": "相关上下文裁剪与工作 Prompt 装配",
                    "title_en": "Relevant context selection and working-prompt assembly",
                    "module": "src/omni_agent/agents/harness_runtime.py",
                    "entrypoints": ["chat_stream()", "_append_assistant_message()"],
                    "role_zh": "把长历史压缩为 historical_summary 与 recent_summary，再叠加 runtime context、skill 索引、工具指导和当前请求。",
                    "role_en": "Compacts long history into historical and recent summaries, then layers runtime context, skill index, tool guidance, and the active user request.",
                    "inputs": ["chat_sessions", "session_context_cache", "request_context"],
                    "outputs": ["working prompt", "context_state", "microcompact events"],
                },
                {
                    "id": "search",
                    "lane_zh": "Search",
                    "lane_en": "Search",
                    "title_zh": "按 Search Gate 执行外部资料确认",
                    "title_en": "External research through the Search Gate",
                    "module": "src/omni_agent/agents/harness_engine.py",
                    "entrypoints": ["HarnessEngine.should_search()", "SearchReport"],
                    "role_zh": "只在用户明确要求、计划需要外部资料、或第三方 API 用法不确定时检索，并把资料先交回 Harness。",
                    "role_en": "Searches only for explicit lookup requests, planned external research, or uncertain third-party API usage, then returns evidence to Harness.",
                    "inputs": ["SearchRequest", "budget", "allowed_domains"],
                    "outputs": ["SearchReport", "sources", "citations"],
                },
                {
                    "id": "generator",
                    "lane_zh": "Generator",
                    "lane_en": "Generator",
                    "title_zh": "按规格实现代码与运行入口",
                    "title_en": "Implementation against the specification",
                    "module": "src/omni_agent/agents/generator_agent.py + harness_runtime.py",
                    "entrypoints": ["GeneratorAgent.generate()", "HarnessRuntime.chat_stream()"],
                    "role_zh": "在当前 thread workspace 内创建/修改真实文件，并由 Harness 归并为 PatchResult，不直接执行验证。",
                    "role_en": "Creates/edits real files inside the current thread workspace, then lets the Harness synthesize PatchResult without running verification directly.",
                    "inputs": ["PlanContract", "scoped files", "repair instruction", "workspace-bound skills"],
                    "outputs": ["workspace mutations", "PatchResult", "PatchEnvelope"],
                },
                {
                    "id": "runner",
                    "lane_zh": "Runner",
                    "lane_en": "Runner",
                    "title_zh": "执行命令、页面冒烟测试与证据采集",
                    "title_en": "Command execution, browser smoke tests, and evidence collection",
                    "module": "src/omni_agent/agents/runner_agent.py + harness_runtime.py",
                    "entrypoints": ["RunnerAgent.run()", "desktop-commander", "Skill Management = python runtime", "playwright-e2e", "web-testing-playwright-e2e", "e2e", "computer-use"],
                    "role_zh": "只运行 Harness 指定的命令和浏览器检查，把 stdout/stderr、截图、控制台和错误分类写入 RunReport。",
                    "role_en": "Runs only Harness-provided commands and browser checks, then records stdout/stderr, screenshots, console output, and classified errors in RunReport.",
                    "inputs": ["PlanContract", "PatchResult", "SearchReport optional", "artifact_info"],
                    "outputs": ["RunReport", "logs", "screenshots", "browser_console"],
                },
                {
                    "id": "evaluator",
                    "lane_zh": "Evaluator",
                    "lane_en": "Evaluator",
                    "title_zh": "基于证据的一次性验收判断",
                    "title_en": "Single-pass evidence-based judgement",
                    "module": "src/omni_agent/agents/evaluator_agent.py + harness_engine.py",
                    "entrypoints": ["EvaluatorAgent.evaluate()", "HarnessEngine.build_harness_decision()"],
                    "role_zh": "只读取 PlanContract、PatchResult、RunReport 和既有证据，输出一次性 EvalVerdict，不直接执行工具。",
                    "role_en": "Reads PlanContract, PatchResult, RunReport, and existing evidence only, then emits one EvalVerdict without running tools.",
                    "inputs": ["PlanContract", "PatchResult", "RunReport", "screenshots", "previous verdicts"],
                    "outputs": ["EvalVerdict", "display_summary", "next_agent hint"],
                },
                {
                    "id": "observability",
                    "lane_zh": "SSE / 持久化",
                    "lane_en": "SSE / Persistence",
                    "title_zh": "事件回流、落盘与后续审计",
                    "title_en": "Event replay, persistence, and later audit",
                    "module": "src/omni_agent/api.py + src/omni_agent/services/session_store.py",
                    "entrypoints": ["StreamingResponse(generate())", "persist_llm_trace()", "persist_chat_session()", "persist_context_cache()"],
                    "role_zh": "把 LLM trace、chat session、压缩缓存、Evaluator 证据和 UI 会话持久化，同时通过 SSE 实时回报关键节点。",
                    "role_en": "Persists LLM traces, chat sessions, compacted cache, evaluator evidence, and UI sessions while reporting checkpoints via SSE.",
                    "inputs": ["llm_log", "chat history", "compacted cache", "ui session snapshot"],
                    "outputs": ["logs/llm_traces", "chat_sessions", "context_cache", "ui_sessions"],
                },
            ],
            "layers": [
                {
                    "id": "session_store",
                    "module": "omni_agent.services.session_store.SessionStore",
                    "role": "Durable history, compacted memory cache, traces, workspace state, and UI session persistence",
                },
                {
                    "id": "request_lifecycle",
                    "module": "omni_agent.services.request_lifecycle.RequestLifecycle",
                    "role": "Structured execution phases for request preparation, routing, prompt assembly, model wait, and completion",
                },
                {
                    "id": "harness_engine",
                    "module": "omni_agent.agents.harness_engine.HarnessEngine",
                    "role": "Planner/Search/Generator/Runner/Evaluator contract, state machine, search gate, policy, evidence handling, and recovery rules",
                },
                {
                    "id": "harness_runtime",
                    "module": "omni_agent.agents.harness_runtime.HarnessRuntime",
                    "role": "Unified five-agent Harness runtime with orchestration, streaming, context accounting, and SSE delivery",
                },
            ],
            "stores": [
                {
                    "name": "chat_sessions",
                    "detail_zh": "线程级对话事实源。先写入用户消息，完成后回写 assistant 消息。",
                    "detail_en": "Canonical per-thread conversation source. User turns are written first, then assistant turns are appended on completion.",
                },
                {
                    "name": "context_cache",
                    "detail_zh": "压缩后的上下文缓存，保存 historical_summary、recent_summary 及签名。",
                    "detail_en": "Compacted context cache holding historical_summary, recent_summary, and reuse signatures.",
                },
                {
                    "name": "llm_traces",
                    "detail_zh": "请求/响应与规划日志的持久化面，供 Logs 与调试回放使用。",
                    "detail_en": "Persisted request/response and planning trace surface used by Logs and debugging replay.",
                },
                {
                    "name": "ui_sessions",
                    "detail_zh": "前端线程快照，用于恢复 transcript、tasks 和抽屉状态。",
                    "detail_en": "Frontend thread snapshots used to restore transcript, tasks, and drawer state.",
                },
            ],
            "mode_routes": [
                {"mode": "agent", "handler": "Unified Harness", "purpose_zh": "默认 Planner -> Search Gate -> Generator -> Runner -> Evaluator 闭环", "purpose_en": "Default Planner -> Search Gate -> Generator -> Runner -> Evaluator loop"},
                {"mode": "create", "handler": "Unified Harness / create strategy", "purpose_zh": "同一个 Agent 的可运行产物策略，不再是独立 Agent", "purpose_en": "Runnable-deliverable strategy inside the same Agent, no longer a separate agent"},
                {"mode": "plan", "handler": "Unified Harness / planner-only strategy", "purpose_zh": "Planner 只输出规格与任务图", "purpose_en": "Planner-only spec and task graph"},
                {"mode": "review", "handler": "Unified Harness / evaluator-heavy strategy", "purpose_zh": "Evaluator 加权的审查与验证", "purpose_en": "Evaluator-heavy review and verification"},
                {"mode": "battle", "handler": "Unified Harness / comparison strategy", "purpose_zh": "同一 Harness 内的候选比较与裁决", "purpose_en": "Candidate comparison and judgement inside the same Harness"},
            ],
            "prompt_sections": [
                "workspace_context",
                "runtime_context",
                "historical_summary",
                "recent_summary",
                "skill_index",
                "skill_instructions",
                "tool_guidance",
                "current_user_request",
            ],
            "phase_catalog": self.phase_catalog(),
        }

    def phase_catalog(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": phase.key,
                "content": phase.default_content,
                "transient": phase.transient,
                "event_type": phase.key if phase.key.startswith("compression_") else "phase",
            }
            for phase in self.PHASES.values()
        ]
