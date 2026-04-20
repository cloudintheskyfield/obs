from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


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
        return {
            "reference_style": "Claude Code inspired request harness",
            "summary": {
                "zh": "以请求编排层、持久化层、模式路由层、Agent 工具循环层和 SSE 可观测层为核心。",
                "en": "Centered on a request harness, persistence layer, mode router, agent tool loop, and SSE observability surface.",
            },
            "flow": [
                {
                    "id": "client_ingress",
                    "lane_zh": "前端 UI",
                    "lane_en": "Client UI",
                    "title_zh": "Composer 组装 ChatStreamRequest",
                    "title_en": "Composer assembles ChatStreamRequest",
                    "module": "ui/src/App.jsx",
                    "entrypoints": ["sendMessage()"],
                    "role_zh": "把用户输入、图片、模式、权限、技能选择、工作区和模型合并成单次请求。",
                    "role_en": "Merges user text, images, mode, permission, skill selection, workspace, and model into a single request envelope.",
                    "inputs": ["message", "message_parts", "mode", "permission_mode", "enabled_skills", "workspace_path", "model"],
                    "outputs": ["POST /chat/stream", "session_id", "tool_context", "thinking_mode"],
                },
                {
                    "id": "api_ingress",
                    "lane_zh": "FastAPI",
                    "lane_en": "FastAPI",
                    "title_zh": "API 恢复线程状态并注入运行时上下文",
                    "title_en": "API restores thread state and injects runtime context",
                    "module": "src/omni_agent/api.py",
                    "entrypoints": ["chat_stream()", "_ensure_session_state_loaded()"],
                    "role_zh": "利用 SessionStore 恢复 chat_sessions 与压缩缓存，再补充日期、时区、位置、工作区、线程目录等权威运行时字段。",
                    "role_en": "Uses SessionStore to restore chat sessions and compacted cache, then injects authoritative runtime fields such as date, timezone, location, workspace, and thread runtime directory.",
                    "inputs": ["session_id", "workspace_path", "temporal_context", "session_locations"],
                    "outputs": ["chat_sessions[session_id]", "request_context", "thread_runtime_dir"],
                },
                {
                    "id": "mode_router",
                    "lane_zh": "模式路由",
                    "lane_en": "Mode Router",
                    "title_zh": "StreamingAgent 选择执行通道",
                    "title_en": "StreamingAgent selects the execution lane",
                    "module": "src/omni_agent/agents/streaming_agent.py",
                    "entrypoints": ["chat_stream()"],
                    "role_zh": "按 agent / plan / review / battle 分发请求，保持 UI、API 与执行环的边界清晰。",
                    "role_en": "Dispatches the request across agent / plan / review / battle lanes so UI, API, and execution loops stay cleanly separated.",
                    "inputs": ["mode", "permission_mode", "enabled_skills", "request_context"],
                    "outputs": ["_native_tool_stream()", "_plan_only_stream()", "_execution_engine_stream()", "_battle_stream()"],
                },
                {
                    "id": "context_harness",
                    "lane_zh": "Agent 核心",
                    "lane_en": "Agent Core",
                    "title_zh": "上下文压缩与工作 Prompt 装配",
                    "title_en": "Context compaction and working-prompt assembly",
                    "module": "src/omni_agent/agents/streaming_agent.py",
                    "entrypoints": ["_maybe_compact_conversation()", "_build_compacted_user_prompt()"],
                    "role_zh": "把长历史压缩为 historical_summary 与 recent_summary，再叠加 runtime context、skill 索引、工具指导和当前请求。",
                    "role_en": "Compacts long history into historical and recent summaries, then layers runtime context, skill index, tool guidance, and the active user request.",
                    "inputs": ["chat_sessions", "session_context_cache", "request_context"],
                    "outputs": ["working prompt", "context_state", "microcompact events"],
                },
                {
                    "id": "tool_loop",
                    "lane_zh": "LLM + Skills",
                    "lane_en": "LLM + Skills",
                    "title_zh": "原生工具循环与真实技能执行",
                    "title_en": "Native tool loop with real skill execution",
                    "module": "src/omni_agent/agents/streaming_agent.py",
                    "entrypoints": ["_native_tool_stream()", "SkillManager.execute_skill()"],
                    "role_zh": "由 VLLMClient 流式产出 token 与 tool call，随后执行真实 skill，再把结果回灌给下一轮模型。",
                    "role_en": "Streams model tokens and tool calls via VLLMClient, executes real skills, and feeds tool results back into the next model turn.",
                    "inputs": ["messages", "tools", "selected model", "workspace-bound skills"],
                    "outputs": ["thinking_delta", "task_start", "task_complete", "answer_delta"],
                },
                {
                    "id": "observability",
                    "lane_zh": "SSE / 持久化",
                    "lane_en": "SSE / Persistence",
                    "title_zh": "事件回流、落盘与后续审计",
                    "title_en": "Event replay, persistence, and later audit",
                    "module": "src/omni_agent/api.py + src/omni_agent/services/session_store.py",
                    "entrypoints": ["StreamingResponse(generate())", "persist_llm_trace()", "persist_chat_session()", "persist_context_cache()"],
                    "role_zh": "把 LLM trace、chat session、压缩缓存和 UI 会话持久化，同时把 SSE 事件实时推回 Transcript / Logs / Architecture。",
                    "role_en": "Persists LLM traces, chat sessions, compacted cache, and UI sessions while streaming SSE events back into Transcript / Logs / Architecture.",
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
                    "id": "streaming_agent",
                    "module": "omni_agent.agents.streaming_agent.StreamingAgent",
                    "role": "Mode-aware runtime loop with compaction, tool planning, execution, and SSE streaming",
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
                {"mode": "agent", "handler": "_native_tool_stream()", "purpose_zh": "真实工具调用与最终回答", "purpose_en": "Real tool calling and final answer synthesis"},
                {"mode": "plan", "handler": "_plan_only_stream()", "purpose_zh": "只生成任务图", "purpose_en": "Returns a plan/task graph without tool execution"},
                {"mode": "review", "handler": "_execution_engine_stream()", "purpose_zh": "结构化计划/执行/综合/校验", "purpose_en": "Structured planning, execution, synthesis, and verification"},
                {"mode": "battle", "handler": "_battle_stream()", "purpose_zh": "直接回答与工具增强回答对战裁决", "purpose_en": "Direct-vs-tool-assisted battle and adjudication"},
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
