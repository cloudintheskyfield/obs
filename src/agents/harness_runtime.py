import json
from utils.json_utils import safe_loads
import difflib
import re
import traceback
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional

from loguru import logger

from .evaluator_agent import EvaluatorAgent
from .generator_agent import GeneratorAgent
from .harness_engine import HarnessEngine
from .planner_agent import PlannerAgent
from .runner_agent import RunnerAgent
from .search_agent import SearchAgent
from services.request_lifecycle import RequestLifecycle

MODEL_CONTEXT_WINDOWS = {
    "minimax-m2": 200_000,
}

CONTEXT_MEMORY_MAX_MESSAGES = 8
CONTEXT_TEXT_LIMIT = 1200
CONTEXT_BUNDLE_MAX_TEXT_CHARS = 12_000
OUTERMOST_ROUTER_ROUTES = {"WORKFLOW", "DIRECT_ANSWER"}


def strip_provider_thinking(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", str(text or ""), flags=re.IGNORECASE).strip()


def normalize_llm_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif isinstance(item.get("text"), str):
                    parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text") or "")
        nested = content.get("content")
        if nested is not None and nested is not content:
            return normalize_llm_message_content(nested)
    return str(content) if content else ""


class HarnessRuntime:
    def __init__(
        self,
        vllm_client: Any,
        skill_manager: Any,
        request_lifecycle: Optional[RequestLifecycle] = None,
    ) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.request_lifecycle = request_lifecycle or RequestLifecycle()
        self.session_context_cache: Dict[str, Dict[str, Any]] = {}
        self.harness_engine = HarnessEngine()

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _phase(self, key: str, **overrides: Any) -> str:
        return self._sse(self.request_lifecycle.phase_payload(key, **overrides))

    def _status(self, status: str, **overrides: Any) -> str:
        return self._sse(self.request_lifecycle.status_payload(status, **overrides))

    def _agent_summary_event(
        self,
        *,
        role: str,
        payload: Mapping[str, Any],
        round_id: int,
        state: str,
    ) -> str:
        return self._sse(
            {
                "type": "agent_summary",
                "role": role,
                "round_id": round_id,
                "state": state,
                "display_summary": self.harness_engine.display_summary_for_output(role, payload),
                "payload_ref": {
                    "task_id": str(payload.get("task_id") or ""),
                    "status": str(payload.get("status") or payload.get("verdict") or ""),
                },
            }
        )

    async def _humanize_harness_decision(self, decision: Dict[str, Any], model: Optional[str] = None) -> None:
        """Use LLM to generate a user-friendly summary of what happens next."""
        if decision.get("decision") == "PASS":
            decision["humanized_next_action"] = "任务已圆满完成，所有验收标准均已通过。"
            return

        reason = decision.get("reason") or ""
        next_agent = decision.get("next_agent") or ""
        next_state = decision.get("next_state") or ""
        
        prompt = (
            f"You are a helpful project manager. Harness just made a decision about the next step in a coding task.\n"
            f"Decision: {decision.get('decision')}\n"
            f"Reason: {reason}\n"
            f"Next Agent: {next_agent}\n"
            f"Next Phase: {next_state}\n\n"
            f"Translate this technical transition into a short, friendly, single-sentence summary for the user "
            f"explaining what you (the AI) are going to do next to fulfill their request. "
            f"Speak in first person ('I will...'). Do not mention internal agent names like 'Generator' or 'Planner'. "
            f"Respond in Chinese."
        )
        
        try:
            # Quick call with low temperature
            humanized = await self.vllm_client.generate_text(prompt, model=model, temperature=0.3)
            decision["humanized_next_action"] = humanized.strip().strip('"')
        except Exception as e:
            logger.warning(f"Failed to humanize harness decision: {e}")
            decision["humanized_next_action"] = ""

    def _harness_decision_event(self, decision: Mapping[str, Any]) -> str:
        return self._sse(
            {
                "type": "harness_decision",
                "decision": self._json_safe(decision),
            }
        )

    def _tool_defs(self, enabled_skills: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        if self.skill_manager is None or not hasattr(self.skill_manager, "get_anthropic_tools"):
            return []
        try:
            tools = list(self.skill_manager.get_anthropic_tools())
        except Exception as exc:
            logger.warning(f"Could not load tool definitions: {exc}")
            return []
        if not enabled_skills:
            return tools
        enabled_set = set(enabled_skills)
        filtered: List[Dict[str, Any]] = []
        for tool in tools:
            tool_name = tool.get("name")
            resolved_skill = self.skill_manager.resolve_skill_name_for_tool(tool_name) if self.skill_manager else None
            if tool_name in enabled_set or resolved_skill in enabled_set:
                filtered.append(tool)
        return filtered

    def _workspace_path(self, request_context: Optional[Mapping[str, Any]] = None) -> Path:
        runtime_path = str((request_context or {}).get("workspace_runtime_path") or "").strip()
        if runtime_path:
            return Path(runtime_path).expanduser().resolve()
        if self.skill_manager is not None and hasattr(self.skill_manager, "get_current_workspace"):
            try:
                return Path(self.skill_manager.get_current_workspace()).expanduser().resolve()
            except Exception:
                pass
        return Path(".").resolve()

    def _get_workspace_files_if_small(self, request_context: Optional[Mapping[str, Any]] = None, max_files: int = 40) -> Optional[List[str]]:
        workspace = self._workspace_path(request_context)
        files: List[str] = []
        try:
            for path in workspace.rglob("*"):
                if not path.is_file():
                    continue
                rel = str(path.relative_to(workspace)).replace("\\", "/")
                if rel.startswith(".") or "__pycache__" in rel or "node_modules" in rel:
                    continue
                files.append(rel)
                if len(files) >= max_files:
                    return None
        except Exception:
            return None
        return files or None

    def _build_artifact_info(self, workspace: Path, plan_contract: Mapping[str, Any]) -> Dict[str, Any]:
        candidate_files = ["index.html", "src/App.tsx", "src/App.jsx", "app/page.tsx", "app/page.jsx"]
        file_path = None
        for candidate in candidate_files:
            full = workspace / candidate
            if full.exists():
                file_path = str(full)
                break
        return {
            "description": str(plan_contract.get("goal") or "Generated artifact"),
            "primary_action": "Verify core functionality",
            "file_path": file_path,
        }

    def _planner_project_summary(self, workspace: Path, existing_files: Optional[List[str]]) -> Dict[str, Any]:
        return {
            "workspace": str(workspace),
            "existing_files": list(existing_files or []),
            "entry_candidates": [
                path for path in ["index.html", "src/App.tsx", "src/App.jsx", "app/page.tsx", "app/page.jsx"]
                if (workspace / path).exists()
            ],
        }

    def _planner_constraints(self, request_context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        return {
            "sandbox_mode": self.harness_engine.DEFAULT_POLICY.get("sandbox_mode"),
            "approval_policy": str((request_context or {}).get("permission_mode") or self.harness_engine.DEFAULT_POLICY.get("approval_policy") or "ask"),
            "workspace_runtime_path": str((request_context or {}).get("workspace_runtime_path") or ""),
        }

    def _json_safe(self, payload: Any) -> Any:
        return safe_loads(json.dumps(payload, ensure_ascii=False, default=str))

    def _read_text_file(self, workspace: Path, relative_path: str, *, max_bytes: int = 262_144) -> Optional[str]:
        path = workspace / relative_path
        try:
            if not path.exists() or not path.is_file() or path.stat().st_size > max_bytes:
                return None
            return path.read_text(encoding="utf-8")
        except Exception:
            return None

    def _project_files_snapshot(self, workspace: Path, plan_contract: Mapping[str, Any]) -> Dict[str, str]:
        snapshot: Dict[str, str] = {}
        for relative_path in plan_contract.get("required_files_to_inspect", []) or []:
            rel = str(relative_path).strip()
            if not rel:
                continue
            content = self._read_text_file(workspace, rel)
            if content is not None:
                snapshot[rel] = content
        return snapshot

    def _repair_source_context(
        self,
        workspace: Path,
        plan_contract: Mapping[str, Any],
        run_report: Mapping[str, Any],
        *,
        radius: int = 8,
    ) -> List[Dict[str, Any]]:
        if not run_report:
            return []
        source_text = json.dumps(run_report, ensure_ascii=False, default=str)
        matches = re.findall(r"(https?://[^\s)\"]+?):(\d+):(\d+)", source_text)
        if not matches:
            return []

        dev_server = (
            plan_contract.get("dev_server")
            if isinstance(plan_contract.get("dev_server"), Mapping)
            else {}
        )
        fallback_path = "index.html"
        dev_url = str((dev_server or {}).get("url") or "")
        try:
            parsed_dev = urllib.parse.urlsplit(dev_url)
            if parsed_dev.path and parsed_dev.path not in {"", "/"}:
                fallback_path = parsed_dev.path.lstrip("/")
        except Exception:
            pass
        required_files = self.harness_engine.required_output_files(plan_contract)
        if required_files:
            fallback_path = required_files[0]

        contexts: List[Dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for url, line_text, column_text in matches[:8]:
            try:
                line_no = int(line_text)
                column_no = int(column_text)
            except Exception:
                continue
            parsed = urllib.parse.urlsplit(url)
            rel = urllib.parse.unquote(parsed.path or "").lstrip("/")
            if not rel:
                rel = fallback_path
            rel = rel.split("?", 1)[0].split("#", 1)[0]
            if not rel or rel.startswith(".harness/") or ".." in Path(rel).parts:
                continue
            key = (rel, line_no)
            if key in seen:
                continue
            seen.add(key)
            content = self._read_text_file(workspace, rel)
            if content is None:
                continue
            lines = content.splitlines()
            start = max(1, line_no - radius)
            end = min(len(lines), line_no + radius)
            snippet = "\n".join(
                f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1)
            )
            contexts.append(
                {
                    "path": rel,
                    "line": line_no,
                    "column": column_no,
                    "url": url,
                    "snippet": snippet,
                }
            )
        return contexts

    def _capture_allowed_text_snapshot(self, workspace: Path, plan_contract: Mapping[str, Any]) -> Dict[str, str]:
        allowed = list(plan_contract.get("allowed_files") or [])
        forbidden = list(plan_contract.get("forbidden_files") or [])
        snapshot: Dict[str, str] = {}
        try:
            for path in workspace.rglob("*"):
                if not path.is_file():
                    continue
                rel = str(path.relative_to(workspace)).replace("\\", "/")
                if not self.harness_engine.is_path_allowed(rel, allowed, forbidden, workspace):
                    continue
                content = self._read_text_file(workspace, rel)
                if content is not None:
                    snapshot[rel] = content
        except Exception:
            return snapshot
        return snapshot

    def _build_diff_patch(
        self,
        before_snapshot: Mapping[str, str],
        workspace: Path,
        patch_result: Mapping[str, Any],
    ) -> str:
        touched: List[str] = []
        for key in ("changed_files", "created_files", "deleted_files"):
            for item in patch_result.get(key, []) or []:
                rel = str(item).strip()
                if rel and rel not in touched:
                    touched.append(rel)
        chunks: List[str] = []
        for rel in touched:
            before_text = before_snapshot.get(rel, "")
            after_text = self._read_text_file(workspace, rel) or ""
            diff = list(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    after_text.splitlines(keepends=True),
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )
            if diff:
                chunks.extend(diff)
        return "".join(chunks)

    def _write_json_file(self, workspace: Path, relative_path: str, payload: Any) -> str:
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._json_safe(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return relative_path

    def _write_text_file(self, workspace: Path, relative_path: str, content: str) -> str:
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return relative_path

    def _write_harness_state(
        self,
        workspace: Path,
        *,
        task_id: str,
        round_id: int,
        state: str,
        repair_round: int,
        replan_round: int,
        search_call_count: int,
        last_completed_state: Optional[str] = None,
        last_artifact: str = "",
    ) -> str:
        return self._write_json_file(
            workspace,
            ".harness/state.json",
            {
                "task_id": task_id,
                "round_id": round_id,
                "state": state,
                "last_completed_state": last_completed_state or "",
                "last_artifact": last_artifact,
                "repair_round": repair_round,
                "replan_round": replan_round,
                "search_call_count": search_call_count,
            },
        )

    def _forward_chunk(self, raw_chunk: str) -> str:
        if not raw_chunk.startswith("data: "):
            return raw_chunk
        try:
            payload = safe_loads(raw_chunk[6:].strip())
        except Exception:
            return raw_chunk
        if isinstance(payload, dict) and payload.get("type") in {"agent_step", "task_start", "task_complete"}:
            payload["user_event"] = self.harness_engine.normalize_user_event(payload)
            return self._sse(payload)
        return raw_chunk

    def _get_context_window_tokens(self, model_name: Optional[str] = None) -> int:
        normalized = str(model_name or "").strip()
        if normalized in MODEL_CONTEXT_WINDOWS:
            return MODEL_CONTEXT_WINDOWS[normalized]
        if self.vllm_client is not None and hasattr(self.vllm_client, "config"):
            try:
                return int(getattr(self.vllm_client.config, "max_model_len", 128000) or 128000)
            except Exception:
                pass
        return 128000

    def _estimate_context_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total_chars = 0
        for msg in messages:
            total_chars += len(normalize_llm_message_content(msg.get("content")))
        return max(1, total_chars // 4) if total_chars else 0

    def _estimate_context_percent(self, messages: List[Dict[str, Any]], model_name: Optional[str] = None) -> int:
        max_tokens = max(1, self._get_context_window_tokens(model_name))
        used_tokens = self._estimate_context_tokens(messages)
        return int(min(100, round((used_tokens / max_tokens) * 100)))

    async def _summarize_context_text(self, value: Any, limit: int = CONTEXT_TEXT_LIMIT) -> str:
        text = strip_provider_thinking(normalize_llm_message_content(value))
        if len(text) <= limit:
            return text
            
        if self.vllm_client is None:
            return text[: max(0, limit - 24)].rstrip() + "\n[context truncated]"
            
        from utils.paths import identity_prompts_root
        prompt_path = identity_prompts_root() / "chunk_summarizer.prompt.md"
        sys_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "You are a concise AI context summarizer."
        
        max_context_chars = self._get_context_window_tokens() * 3
        chunk_size = max(1000, max_context_chars - 8000)
        
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        summaries = []
        model_name = getattr(self.harness_engine.config.vllm, "model", "MiniMax-M2") if hasattr(self, "harness_engine") and hasattr(self.harness_engine, "config") else "MiniMax-M2"
        
        for i, chunk in enumerate(chunks):
            prompt = f"{sys_prompt}\n\nCHUNK {i+1}/{len(chunks)}:\n{chunk}"
            try:
                summary = await self.vllm_client.generate_text(prompt, model=model_name, temperature=0.1)
                summaries.append(summary)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Summarizer failed: {e}")
                summaries.append(chunk[: max(0, limit // len(chunks) - 24)] + "\n[chunk truncated]")
                
        return "\n\n--- NEXT SUMMARY CHUNK ---\n\n".join(summaries)

    async def _summarize_chat_history(
        self,
        chat_sessions: Mapping[str, List[Dict[str, Any]]],
        session_id: str,
        *,
        max_messages: int = CONTEXT_MEMORY_MAX_MESSAGES,
    ) -> List[Dict[str, Any]]:
        messages = list(chat_sessions.get(session_id) or [])[-max_messages:]
        summary: List[Dict[str, Any]] = []
        for index, message in enumerate(messages, start=1):
            content = message.get("content")
            item: Dict[str, Any] = {
                "index": index,
                "role": str(message.get("role") or "user"),
                "content": await self._summarize_context_text(content),
            }
            if isinstance(content, list):
                item["message_parts"] = len(content)
                item["has_images"] = any(
                    isinstance(part, Mapping)
                    and str(part.get("type") or "").lower() in {"image", "image_url", "input_image"}
                    for part in content
                )
            summary.append(item)
        return summary

    async def _router_recent_dialogue(
        self,
        chat_sessions: Mapping[str, List[Dict[str, Any]]],
        session_id: str,
        *,
        max_messages: int = CONTEXT_MEMORY_MAX_MESSAGES,
        current_user_request: str = "",
    ) -> List[Dict[str, str]]:
        dialogue: List[Dict[str, str]] = []
        skipped_current_request = False
        for message in reversed(list(chat_sessions.get(session_id) or [])):
            role = str(message.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = await self._summarize_context_text(message.get("content"))
            if not content.strip():
                continue
            if (
                not skipped_current_request
                and role == "user"
                and content.strip() == str(current_user_request or "").strip()
            ):
                skipped_current_request = True
                continue
            dialogue.append({"role": role, "content": content})
            if len(dialogue) >= max_messages:
                break
        return list(reversed(dialogue))

    async def _router_memory_input(
        self,
        *,
        session_id: str,
        chat_sessions: Mapping[str, List[Dict[str, Any]]],
        user_message: str,
    ) -> Dict[str, Any]:
        memory = dict(self.session_context_cache.get(session_id) or {})
        return {
            "current_user_request": await self._summarize_context_text(user_message, 1800),
            "long_range_memory": {
                "historical_summary": await self._summarize_context_text(memory.get("historical_summary") or "", 2400),
                "recent_summary": await self._summarize_context_text(memory.get("recent_summary") or "", 1600),
                "key_memories": await self._summarize_context_text(memory.get("key_memories") or "", 1600),
            },
            "recent_dialogue": await self._router_recent_dialogue(
                chat_sessions,
                session_id,
                current_user_request=user_message,
            ),
        }

    async def _format_router_memory_input(self, payload: Mapping[str, Any]) -> str:
        memory = payload.get("long_range_memory") if isinstance(payload.get("long_range_memory"), Mapping) else {}
        recent_dialogue = payload.get("recent_dialogue") if isinstance(payload.get("recent_dialogue"), list) else []
        lines = [
            "Current user request:",
            await self._summarize_context_text(payload.get("current_user_request") or "", 1800) or "(empty)",
            "",
            "Long-range memory:",
            f"- historical_summary: {await self._summarize_context_text((memory or {}).get('historical_summary') or '', 2400) or '(none)'}",
            f"- recent_summary: {await self._summarize_context_text((memory or {}).get('recent_summary') or '', 1600) or '(none)'}",
            f"- key_memories: {await self._summarize_context_text((memory or {}).get('key_memories') or '', 1600) or '(none)'}",
            "",
            "Recent dialogue:",
        ]
        if recent_dialogue:
            for item in recent_dialogue:
                if not isinstance(item, Mapping):
                    continue
                role = str(item.get("role") or "unknown").strip() or "unknown"
                content = await self._summarize_context_text(item.get("content") or "")
                if content:
                    lines.append(f"- {role}: {content}")
        else:
            lines.append("- (none)")
        return "\n".join(lines)

    def _context_artifact_index(self, workspace: Path, *, max_items: int = 24) -> List[Dict[str, Any]]:
        harness_dir = workspace / ".harness"
        if not harness_dir.exists():
            return []
        patterns = [
            ".harness/state.json",
            ".harness/task.json",
            ".harness/session.json",
            ".harness/project_summary.json",
            ".harness/plan.json",
            ".harness/search/*/search_report.json",
            ".harness/runs/run_*/input/*_input.json",
            ".harness/runs/run_*/output/*.json",
            ".harness/runs/run_*/diff.patch",
            ".harness/runs/run_*/screenshots/*",
            ".harness/runs/run_*/logs/*",
        ]
        candidates: Dict[str, Path] = {}
        for pattern in patterns:
            try:
                for path in workspace.glob(pattern):
                    if path.is_file():
                        rel = str(path.relative_to(workspace)).replace("\\", "/")
                        candidates[rel] = path
            except Exception:
                continue
        ranked = sorted(
            candidates.items(),
            key=lambda item: item[1].stat().st_mtime if item[1].exists() else 0,
            reverse=True,
        )
        indexed: List[Dict[str, Any]] = []
        for rel, path in ranked[:max_items]:
            name = path.name
            if name.endswith("_input.json"):
                kind = "agent_input"
            elif name == "search_report.json":
                kind = "search_report"
            elif name == "run_report.json":
                kind = "run_report"
            elif name == "eval_verdict.json":
                kind = "eval_verdict"
            elif name == "patch_result.json":
                kind = "patch_result"
            elif name == "harness_decision.json":
                kind = "harness_decision"
            elif name == "diff.patch":
                kind = "diff"
            elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                kind = "screenshot"
            elif path.suffix.lower() in {".log", ".txt"}:
                kind = "log"
            else:
                kind = "harness_artifact"
            try:
                size = path.stat().st_size
                modified_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
            except Exception:
                size = 0
                modified_at = ""
            indexed.append(
                {
                    "path": rel,
                    "kind": kind,
                    "bytes": size,
                    "modified_at": modified_at,
                }
            )
        return indexed

    async def _bounded_context_bundle(self, bundle: Mapping[str, Any]) -> Dict[str, Any]:
        bounded = safe_loads(json.dumps(bundle, ensure_ascii=False, default=str))
        while len(json.dumps(bounded, ensure_ascii=False, default=str)) > CONTEXT_BUNDLE_MAX_TEXT_CHARS:
            artifacts = bounded.get("artifact_index")
            if isinstance(artifacts, list) and len(artifacts) > 8:
                del artifacts[-1]
                continue
            messages = bounded.get("recent_messages")
            if isinstance(messages, list) and messages:
                longest = max(
                    messages,
                    key=lambda item: len(str(item.get("content") or "")) if isinstance(item, Mapping) else 0,
                )
                if isinstance(longest, dict) and len(str(longest.get("content") or "")) > 320:
                    longest["content"] = await self._summarize_context_text(longest.get("content"), 320)
                    continue
            bounded["truncated"] = True
            break
        return bounded

    async def _build_context_bundle(
        self,
        *,
        session_id: str,
        chat_sessions: Mapping[str, List[Dict[str, Any]]],
        workspace: Path,
        user_message: str,
        model: Optional[str],
        request_context: Optional[Mapping[str, Any]],
        previous_failures: Optional[List[str]] = None,
        search_reports: Optional[List[Mapping[str, Any]]] = None,
        previous_verdicts: Optional[List[Mapping[str, Any]]] = None,
    ) -> Dict[str, Any]:
        memory = dict(self.session_context_cache.get(session_id) or {})
        last_plan = memory.get("last_plan_contract") if isinstance(memory.get("last_plan_contract"), Mapping) else {}
        last_verdict = memory.get("last_eval_verdict") if isinstance(memory.get("last_eval_verdict"), Mapping) else {}
        last_decision = memory.get("last_harness_decision") if isinstance(memory.get("last_harness_decision"), Mapping) else {}
        open_failures = [
            await self._summarize_context_text(item, 600)
            for item in (previous_failures or [])
            if str(item).strip()
        ]
        if last_verdict and str(last_verdict.get("verdict") or "").upper() not in {"", "PASS"}:
            root_cause = str(last_verdict.get("root_cause") or last_verdict.get("repair_instruction") or "").strip()
            if root_cause:
                open_failures.append(await self._summarize_context_text(root_cause, 600))
        bundle = {
            "schema_version": "1.0",
            "session_id": session_id,
            "workspace": str(workspace),
            "current_user_request": await self._summarize_context_text(user_message, 1800),
            "model": model or "",
            "history_policy": {
                "recent_messages_limit": CONTEXT_MEMORY_MAX_MESSAGES,
                "text_limit_per_message": CONTEXT_TEXT_LIMIT,
                "max_bundle_chars": CONTEXT_BUNDLE_MAX_TEXT_CHARS,
                "raw_logs_policy": "artifact_only",
                "agent_context_rule": (
                    "Each agent receives this bounded ContextBundle plus its role-specific contract. "
                    "Raw stdout, stderr, browser traces, and model transcripts stay in artifacts."
                ),
            },
            "recent_messages": await self._summarize_chat_history(chat_sessions, session_id),
            "working_memory": {
                "last_user_message": await self._summarize_context_text(memory.get("last_user_message") or user_message, 1800),
                "last_plan_goal": await self._summarize_context_text((last_plan or {}).get("goal") or "", 800),
                "last_decision": {
                    "decision": str((last_decision or {}).get("decision") or ""),
                    "reason": await self._summarize_context_text((last_decision or {}).get("reason") or "", 600),
                    "next_agent": str((last_decision or {}).get("next_agent") or ""),
                },
                "last_verdict": {
                    "verdict": str((last_verdict or {}).get("verdict") or ""),
                    "root_cause": await self._summarize_context_text((last_verdict or {}).get("root_cause") or "", 600),
                    "repair_instruction": await self._summarize_context_text((last_verdict or {}).get("repair_instruction") or "", 600),
                },
                "open_failures": open_failures[-6:],
            },
            "artifact_index": self._context_artifact_index(workspace),
            "search_report_count": len(list(search_reports or [])),
            "previous_verdict_count": len(list(previous_verdicts or [])),
        }
        return await self._bounded_context_bundle(bundle)

    def _persist_context_bundle(self, workspace: Path, context_bundle: Mapping[str, Any]) -> str:
        return self._write_json_file(workspace, ".harness/context/context_bundle.json", context_bundle)

    def _router_system_prompt(self) -> str:
        return self.harness_engine.load_agent_prompt("router")

    async def _normalize_router_decision(self, payload: Optional[Mapping[str, Any]], *, fallback_route: str = "WORKFLOW") -> Dict[str, Any]:
        route = str((payload or {}).get("route") or "").strip().upper()
        if route not in OUTERMOST_ROUTER_ROUTES:
            route = fallback_route if fallback_route in OUTERMOST_ROUTER_ROUTES else "WORKFLOW"

        try:
            confidence = float((payload or {}).get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        reason = str((payload or {}).get("reason") or "").strip()
        if not reason:
            reason = "Defaulted to Harness workflow." if route == "WORKFLOW" else "Pure direct answer."
        return {
            "route": route,
            "confidence": confidence,
            "reason": await self._summarize_context_text(reason, 160),
        }

    async def _update_memory_summaries(
        self,
        user_message: str,
        *,
        session_id: str = "",
        chat_sessions: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
        model: Optional[str] = None,
    ) -> None:
        """
        在每次路由前调用，自动总结历史记忆（historical_summary）、近期记忆（recent_summary）以及关键画像（key_memories）。
        它会将当前总结与最新的聊天记录发送给大模型，生成更新后的 JSON 总结并覆盖原有的缓存。
        """
        if self.vllm_client is None:
            return

        # 获取或初始化路由器的 Session ID 和完整的对话历史记录
        router_session_id = session_id or "__router__"
        router_chat_sessions = chat_sessions or {router_session_id: [{"role": "user", "content": user_message}]}
        
        # 加载用于更新记忆的大模型 System Prompt 文件
        from utils.paths import identity_prompts_root
        prompt_path = identity_prompts_root() / "memory_updater.prompt.md"
        if not prompt_path.exists():
            return
            
        system_prompt = prompt_path.read_text(encoding="utf-8")
        
        # 构建给大模型的输入内容 payload，其中包含了：
        # - current_user_request: 当前用户的请求文本
        # - long_range_memory: 之前的记忆总结（包含 historical_summary, recent_summary, key_memories）
        # - recent_dialogue: 最近几轮的对话记录（默认最多包含8条历史消息）
        payload = await self._router_memory_input(
            session_id=router_session_id,
            chat_sessions=router_chat_sessions,
            user_message=user_message,
        )
        
        # 检查是否已有历史/近期总结。如果没有，说明可能是第一次总结，或者很久前遗留的空状态。
        memory = self.session_context_cache.get(router_session_id) or {}
        has_summary = bool(memory.get("historical_summary") or memory.get("recent_summary"))
        
        if not has_summary:
            # 如果没有总结（冷启动），为了防止丢失很久以前的上下文，
            # 临时将 recent_dialogue 的最大提取条数放宽到 1000 条，把尽可能多的历史长对话塞给大模型做初始总结。
            payload["recent_dialogue"] = await self._router_recent_dialogue(
                router_chat_sessions,
                router_session_id,
                max_messages=1000,
                current_user_request=user_message,
            )
        
        # 构造发给大模型的最终消息列表
        # 这里使用了 _format_router_memory_input 把 JSON payload 转换成了排版良好的 Markdown 文本
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": await self._format_router_memory_input(payload)},
        ]
        
        raw_content = ""
        try:
            # 异步请求大模型，不使用任何外部 Tools，仅执行总结任务
            stream = await self.vllm_client.chat_completion(
                messages=messages,
                tools=None,
                temperature=0.0,
                max_tokens=800,
                stream=True,
                model=model,
            )
            async for chunk in stream:
                if isinstance(chunk, dict) and "__obs_phase" in chunk:
                    continue
                if "choices" not in chunk or not chunk["choices"]:
                    continue
                raw_content += chunk["choices"][0].get("delta", {}).get("content") or ""
                
            parsed: Optional[Dict[str, Any]] = None
            try:
                # 尝试直接把大模型返回的文本（并过滤掉 provider 的 thinking 标签）解析为 JSON
                obj = safe_loads(strip_provider_thinking(raw_content))
                if isinstance(obj, dict):
                    parsed = obj
            except Exception:
                # 如果直接解析失败（例如大模型在 JSON 外面包裹了 markdown 代码块或者额外文字），尝试用正则提取花括号中的内容再解析
                start = raw_content.find("{")
                end = raw_content.rfind("}")
                if start >= 0 and end > start:
                    try:
                        obj = safe_loads(strip_provider_thinking(raw_content[start:end + 1]))
                        if isinstance(obj, dict):
                            parsed = obj
                    except Exception:
                        pass
                        
            # 解析成功后，将更新后的各部分总结写回到 session_context_cache 缓存中
            if parsed:
                if "historical_summary" in parsed:
                    self.session_context_cache.setdefault(session_id, {})["historical_summary"] = parsed["historical_summary"]
                if "recent_summary" in parsed:
                    self.session_context_cache.setdefault(session_id, {})["recent_summary"] = parsed["recent_summary"]
                if "key_memories" in parsed:
                    self.session_context_cache.setdefault(session_id, {})["key_memories"] = parsed["key_memories"]
                    
        except Exception as exc:
            logger.warning(f"Memory Updater failed: {exc}")

    async def _classify_intent_with_llm(
        self,
        user_message: str,
        *,
        session_id: str = "",
        chat_sessions: Optional[Mapping[str, List[Dict[str, Any]]]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = (user_message or "").strip()
        if not text:
            return await self._normalize_router_decision(
                {"route": "DIRECT_ANSWER", "confidence": 1.0, "reason": "Empty request can be answered directly."},
                fallback_route="DIRECT_ANSWER",
            )
        if self.vllm_client is None:
            logger.warning("Outermost Router has no LLM client; defaulting to WORKFLOW for non-empty request.")
            return await self._normalize_router_decision(
                {"route": "WORKFLOW", "confidence": 0.0, "reason": "No router model available."},
                fallback_route="WORKFLOW",
            )

        router_session_id = session_id or "__router__"
        router_chat_sessions = chat_sessions or {router_session_id: [{"role": "user", "content": text}]}
        payload = await self._router_memory_input(
            session_id=router_session_id,
            chat_sessions=router_chat_sessions,
            user_message=text,
        )
        messages = [
            {"role": "system", "content": self._router_system_prompt()},
            {"role": "user", "content": await self._format_router_memory_input(payload)},
        ]
        raw_content = ""
        try:
            stream = await self.vllm_client.chat_completion(
                messages=messages,
                tools=None,
                temperature=0.0,
                max_tokens=400,
                stream=True,
                model=model,
            )
            async for chunk in stream:
                if isinstance(chunk, dict) and "__obs_phase" in chunk:
                    continue
                if "choices" not in chunk or not chunk["choices"]:
                    continue
                raw_content += chunk["choices"][0].get("delta", {}).get("content") or ""
        except Exception as exc:
            logger.warning(f"Outermost Router LLM classification failed: {exc}")
            return await self._normalize_router_decision(
                {"route": "WORKFLOW", "confidence": 0.0, "reason": "Router model call failed."},
                fallback_route="WORKFLOW",
            )

        parsed: Optional[Dict[str, Any]] = None
        try:
            obj = safe_loads(strip_provider_thinking(raw_content))
            if isinstance(obj, dict):
                parsed = obj
        except Exception:
            start = raw_content.find("{")
            end = raw_content.rfind("}")
            if start >= 0 and end > start:
                try:
                    obj = safe_loads(strip_provider_thinking(raw_content[start:end + 1]))
                    if isinstance(obj, dict):
                        parsed = obj
                except Exception:
                    parsed = None

        decision = await self._normalize_router_decision(parsed, fallback_route="WORKFLOW")
        if not parsed or str((parsed or {}).get("route") or "").strip().upper() not in OUTERMOST_ROUTER_ROUTES:
            logger.warning(f"Outermost Router returned invalid decision {parsed!r}; defaulting to WORKFLOW.")
        return decision

    def _final_answer(
        self,
        plan_contract: Mapping[str, Any],
        patch_result: Optional[Mapping[str, Any]],
        run_report: Optional[Mapping[str, Any]],
        verdict: Mapping[str, Any],
        workspace: Optional[Path] = None,
    ) -> str:
        verdict_name = str(verdict.get("verdict") or "")
        summary = (verdict.get("display_summary") or {}).get("summary") or verdict.get("root_cause") or ""
        lines: List[str] = []
        if verdict_name == "PASS":
            lines.append("## 完成情况")
            lines.append(f"- **结果**：{summary or '任务已通过验收。'}")
            
            changed_files = set()
            if patch_result:
                for item in patch_result.get("changed_files", []) or []:
                    changed_files.add(str(item))
                    
            if workspace and workspace.exists():
                allowed_files = plan_contract.get("allowed_files") or []
                for pattern in allowed_files:
                    path = str(pattern).strip()
                    # Only check concrete file paths explicitly designated by the Planner LLM
                    if not path or any(token in path for token in ("*", "?", "[")):
                        continue
                    p = workspace / path
                    if p.is_file() and p.stat().st_size > 0:
                        changed_files.add(path)
                                    
            if changed_files:
                links = []
                for f in sorted(list(changed_files))[:15]:
                    links.append(f"[{f}](/preview/local-file?path={urllib.parse.quote(f)})")
                lines.append("- **相关文件**：" + "、".join(links))
                
            if run_report:
                lines.append(f"- **验证状态**：{run_report.get('status') or 'UNKNOWN'}")
        else:
            lines.append("## 任务暂未完成")
            lines.append(f"- **当前结论**：{verdict_name or 'UNKNOWN'}")
            if summary:
                lines.append(f"- **原因**：{summary}")
            next_agent = str(verdict.get("next_agent") or "None")
            if next_agent and next_agent != "None":
                lines.append(f"- **下一步**：交由 {next_agent} 继续处理")
        goal = str(plan_contract.get("goal") or "").strip()
        if goal:
            lines.insert(0, f"# {goal}")
        return "\n".join(lines)

    def _append_assistant_message(self, chat_sessions: Dict[str, List[Dict[str, Any]]], session_id: str, content: str) -> None:
        if not content.strip():
            return
        chat_sessions.setdefault(session_id, []).append({"role": "assistant", "content": content})

    def _build_planner_input(
        self,
        *,
        user_message: str,
        workspace: Path,
        existing_files: Optional[List[str]],
        request_context: Optional[Mapping[str, Any]],
        previous_failures: Optional[List[str]] = None,
        search_reports: Optional[List[Mapping[str, Any]]] = None,
        context_bundle: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        project_summary = self._planner_project_summary(workspace, existing_files)
        return {
            "task_context": {
                "user_request": user_message,
                "workspace": str(workspace),
                "project_summary": project_summary,
                "constraints": self._planner_constraints(request_context),
                "search_reports": list(search_reports or []),
                "context_bundle": dict(context_bundle or {}),
            },
            "previous_failures": list(previous_failures or []),
        }

    def _build_search_input(
        self,
        *,
        plan_contract: Mapping[str, Any],
        round_id: int,
        search_call_count: int,
        triggered_by: str,
        reason: str,
        user_message: str,
        run_report: Optional[Mapping[str, Any]] = None,
        eval_verdict: Optional[Mapping[str, Any]] = None,
        context_bundle: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        external = dict((plan_contract.get("external_research") or {}))
        report = dict(run_report or {})
        verdict = dict(eval_verdict or {})
        questions = verdict.get("search_questions") or []
        research_questions = []
        if isinstance(questions, list):
            for index, item in enumerate(questions, start=1):
                question = str(item).strip()
                if question:
                    research_questions.append({"id": f"Q{index}", "question": question, "priority": "high"})
        if not research_questions:
            research_questions = [{
                "id": "Q1",
                "question": str(reason or plan_contract.get("goal") or user_message).strip(),
                "priority": "high",
            }]
        return {
            "schema_version": "1.0",
            "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
            "round_id": round_id,
            "search_id": f"search_{search_call_count:03d}",
            "triggered_by": triggered_by,
            "reason": str(reason or user_message),
            "research_questions": research_questions,
            "queries": list(external.get("queries") or verdict.get("search_questions") or [str(plan_contract.get("goal") or user_message)]),
            "allowed_domains": list(external.get("allowed_domains") or []),
            "blocked_domains": [],
            "max_results": int(external.get("max_results", 5) or 5),
            "max_pages_to_scrape": int(external.get("max_pages_to_scrape", 3) or 3),
            "freshness": str(external.get("freshness") or "stable"),
            "source_preference": ["official_docs", "github_repo", "github_issues", "stackoverflow", "blog"],
            "context": {
                "run_report_status": str(report.get("status") or ""),
                "error_summary": str(report.get("summary") or ""),
                "root_cause": str(verdict.get("root_cause") or ""),
                "current_assumption": str(reason or ""),
                "context_bundle": dict(context_bundle or {}),
            },
            "permissions": {
                "allow_web_search": True,
                "allow_scrape": True,
                "allow_login": False,
                "allow_download": False,
                "allow_execute_remote_code": False,
            },
        }

    def _build_generator_input(
        self,
        *,
        workspace: Path,
        plan_contract: Mapping[str, Any],
        search_reports: List[Dict[str, Any]],
        last_run_report: Mapping[str, Any],
        eval_verdict: Mapping[str, Any],
        round_id: int,
        context_bundle: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "schema_version": "1.0",
            "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
            "round_id": round_id,
            "mode": "repair" if round_id > 1 else "initial",
            "workspace": str(workspace),
            "plan_contract": dict(plan_contract),
            "project_files_snapshot": self._project_files_snapshot(workspace, plan_contract),
            "harness_constraints": {
                "allowed_write_paths": list(plan_contract.get("allowed_files") or []),
                "forbidden_write_paths": list(plan_contract.get("forbidden_files") or []),
                "package_json_policy": dict(plan_contract.get("package_json_policy") or {}),
                "allow_new_dependencies": bool(
                    ((plan_contract.get("package_json_policy") or {}).get("allow_add_dependencies")) or False
                ),
            },
            "search_reports": list(search_reports or []),
            "run_report": dict(last_run_report or {}),
            "eval_verdict": dict(eval_verdict or {}),
            "context_bundle": dict(context_bundle or {}),
            "repair_source_context": self._repair_source_context(
                workspace, plan_contract, last_run_report
            ),
        }

    def _build_runner_input(
        self,
        *,
        workspace: Path,
        plan_contract: Mapping[str, Any],
        patch_result: Mapping[str, Any],
        search_reports: List[Dict[str, Any]],
        artifact_info: Mapping[str, Any],
        round_id: int,
        context_bundle: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        run_dir = f".harness/runs/run_{round_id:03d}"
        return {
            "schema_version": "1.0",
            "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
            "round_id": round_id,
            "execution_mode": "harness_controlled",
            "workspace": str(workspace),
            "run_dir": run_dir,
            "plan_contract": dict(plan_contract),
            "patch_result": dict(patch_result),
            "test_commands": list(plan_contract.get("test_commands") or []),
            "dev_server": dict(plan_contract.get("dev_server") or {}),
            "smoke_tests": list(plan_contract.get("smoke_tests") or []),
            "runner_limits": {
                "max_command_retries": 0,
                "max_dev_server_retries": 2,
                "max_smoke_test_steps": 10,
                "overall_timeout_sec": int((self.harness_engine.get_budgets(str(workspace)).get("timeouts") or {}).get("runner_sec", 300)),
                "command_timeout_sec": int((self.harness_engine.get_budgets(str(workspace)).get("timeouts") or {}).get("command_default_sec", 120)),
                "dev_server_timeout_sec": int((self.harness_engine.get_budgets(str(workspace)).get("timeouts") or {}).get("dev_server_sec", 60)),
                "browser_test_timeout_sec": int((self.harness_engine.get_budgets(str(workspace)).get("timeouts") or {}).get("browser_test_sec", 60)),
            },
            "permissions": dict((self.harness_engine.get_policy(str(workspace)).get("agent_permissions") or {}).get("Runner") or {}),
            "search_reports": list(search_reports or []),
            "artifact_info": dict(artifact_info or {}),
            "context_bundle": dict(context_bundle or {}),
        }

    def _build_evaluator_input(
        self,
        *,
        plan_contract: Mapping[str, Any],
        patch_result: Mapping[str, Any],
        run_report: Mapping[str, Any],
        search_reports: List[Dict[str, Any]],
        previous_verdicts: List[Dict[str, Any]],
        round_id: int,
        diff_path: str,
        context_bundle: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        artifacts = run_report.get("artifacts") if isinstance(run_report.get("artifacts"), Mapping) else {}
        return {
            "schema_version": "1.0",
            "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
            "round_id": round_id,
            "plan_contract": dict(plan_contract),
            "patch_result": dict(patch_result),
            "run_report": dict(run_report),
            "search_reports": list(search_reports or []),
            "git_diff_summary": {
                "changed_files": list(patch_result.get("changed_files") or []),
                "created_files": list(patch_result.get("created_files") or []),
                "deleted_files": list(patch_result.get("deleted_files") or []),
                "diff_path": diff_path,
            },
            "screenshots": list(artifacts.get("screenshots") or []),
            "previous_eval_verdicts": list(previous_verdicts or []),
            "context_bundle": dict(context_bundle or {}),
        }

    async def _planner_only_stream(
        self,
        *,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        user_message: str,
        request_context: Optional[Mapping[str, Any]],
        enabled_skills: Optional[List[str]],
        model: Optional[str],
    ) -> AsyncGenerator[str, None]:
        _ = enabled_skills
        planner = PlannerAgent(self.vllm_client)
        workspace = self._workspace_path(request_context)
        existing_files = self._get_workspace_files_if_small(request_context)
        context_bundle = await self._build_context_bundle(
            session_id=session_id,
            chat_sessions=chat_sessions,
            workspace=workspace,
            user_message=user_message,
            model=model,
            request_context=request_context,
            previous_failures=[],
            search_reports=[],
            previous_verdicts=[],
        )
        planner_input = self._build_planner_input(
            user_message=user_message,
            workspace=workspace,
            existing_files=existing_files,
            request_context=request_context,
            previous_failures=[],
            search_reports=[],
            context_bundle=context_bundle,
        )
        self.harness_engine.validate_agent_input("Planner", planner_input)
        async for chunk in planner.plan(
            session_id=session_id,
            user_message=user_message,
            model=model,
            existing_files=existing_files,
            project_summary=planner_input["task_context"]["project_summary"],
            previous_failures=planner_input["previous_failures"],
            constraints=planner_input["task_context"]["constraints"],
            search_reports=planner_input["task_context"]["search_reports"],
            recent_messages=(context_bundle or {}).get("recent_messages"),
        ):
            yield self._forward_chunk(chunk)
        plan_contract = planner.last_plan_contract
        plan_id = str(uuid.uuid4())
        tasks = [
            {
                "task_id": f"T{index}",
                "description": str(item.get("title") or item.get("description") or f"步骤 {index}"),
                "owner": "Planner" if index == 1 else ("Evaluator" if index >= len(planner.last_tasks) else "Generator"),
                "dependencies": [f"T{index - 1}"] if index > 1 else [],
            }
            for index, item in enumerate(plan_contract.get("implementation_steps") or [], start=1)
            if isinstance(item, Mapping)
        ]
        yield self._sse(
            {
                "type": "plan",
                "plan_id": plan_id,
                "harness_strategy": "planner_only",
                "awaiting_approval": False,
                "plan": {
                    "goal": plan_contract.get("goal") or user_message,
                    "roles": ["Planner", "Search", "Generator", "Runner", "Evaluator"],
                    "steps": tasks,
                    "acceptance_checks": plan_contract.get("acceptance_criteria") or [],
                },
                "plan_graph": {
                    "tasks": tasks,
                    "edges": [
                        {"from": f"T{index}", "to": f"T{index + 1}"}
                        for index in range(1, len(tasks))
                    ],
                },
                "session_id": session_id,
            }
        )
        final_text = self._final_answer(plan_contract, None, None, {"verdict": "PASS", "display_summary": {"summary": "PlanContract 已生成。"}}, workspace)
        self._append_assistant_message(chat_sessions, session_id, final_text)
        yield self._sse({"type": "answer_delta", "delta": final_text, "session_id": session_id})
        yield self._sse({"done": True, "session_id": session_id})

    async def _direct_answer_stream(
        self,
        *,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        user_message: str,
        model: Optional[str],
        route: Optional[str] = "DIRECT_ANSWER",
        extra_context: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream a direct LLM answer without invoking the 5-agent pipeline."""
        import json
        from utils.json_utils import safe_loads
        if route:
            yield self._sse({"type": "route", "route": route, "session_id": session_id})
        yield self._status("answering", session_id=session_id)

        from utils.paths import identity_prompts_root
        prompt_path = identity_prompts_root() / "direct_answer.prompt.md"
        sys_prompt_content = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else "You are a helpful AI assistant."

        if extra_context:
            sys_prompt_content += (
                "\n\nUse the following bounded SearchReport as evidence. "
                "Answer the user's question directly, cite source titles/URLs when present, "
                "and do not invent facts outside the report.\n\n"
                f"{extra_context}"
            )

        payload = await self._router_memory_input(
            session_id=session_id,
            chat_sessions=chat_sessions,
            user_message=user_message,
        )
        user_content = await self._format_router_memory_input(payload)

        messages = [
            {"role": "system", "content": sys_prompt_content},
            {"role": "user", "content": user_content},
        ]
        
        direct_answer_tools = [
            {
                "type": "function",
                "function": {
                    "name": "run_search_agent",
                    "description": "Run the dedicated Search Agent to deeply research a topic. The Search Agent will use browsers and search engines to compile a comprehensive report.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query or topic to research"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

        max_iterations = 4
        for iteration in range(max_iterations):
            accumulated = ""
            in_think = False
            buf = ""
            assistant_message = {"role": "assistant", "content": ""}
            tool_calls = []
            
            try:
                stream = await self.vllm_client.chat_completion(messages=messages, tools=direct_answer_tools, model=model, stream=True)
                async for chunk in stream:
                    if isinstance(chunk, dict) and chunk.get("__obs_phase"):
                        yield self._sse({"type": "phase", "transient": True, "content": "正在重试...", "session_id": session_id})
                        continue
                        
                    try:
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                            
                        delta = choices[0].get("delta") or {}
                        piece = str(delta.get("content") or "")
                        
                        if piece:
                            assistant_message["content"] += piece
                            accumulated += piece
                            buf += piece
                            
                            while True:
                                if not in_think:
                                    start_pos = buf.find("<think>")
                                    if start_pos != -1:
                                        if start_pos > 0:
                                            yield self._sse({"type": "answer_delta", "delta": buf[:start_pos], "session_id": session_id})
                                        in_think = True
                                        buf = buf[start_pos+7:]
                                    else:
                                        safe_len = max(0, len(buf) - 6)
                                        if safe_len > 0:
                                            yield self._sse({"type": "answer_delta", "delta": buf[:safe_len], "session_id": session_id})
                                            buf = buf[safe_len:]
                                        break
                                else:
                                    end_pos = buf.find("</think>")
                                    if end_pos != -1:
                                        if end_pos > 0:
                                            yield self._sse({"type": "agent_thinking", "delta": buf[:end_pos], "session_id": session_id})
                                        in_think = False
                                        buf = buf[end_pos+8:]
                                    else:
                                        safe_len = max(0, len(buf) - 7)
                                        if safe_len > 0:
                                            yield self._sse({"type": "agent_thinking", "delta": buf[:safe_len], "session_id": session_id})
                                            buf = buf[safe_len:]
                                        break
                                        
                        # Parse tool calls
                        if "tool_calls" in delta and delta["tool_calls"]:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", len(tool_calls))
                                while len(tool_calls) <= idx:
                                    tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                                if tc.get("id"):
                                    tool_calls[idx]["id"] = tc["id"]
                                if "function" in tc:
                                    if tc["function"].get("name"):
                                        tool_calls[idx]["function"]["name"] += tc["function"]["name"]
                                    if tc["function"].get("arguments"):
                                        tool_calls[idx]["function"]["arguments"] += tc["function"]["arguments"]
                                        
                    except Exception:
                        pass
                
                # Flush buf
                if buf:
                    if in_think:
                        yield self._sse({"type": "agent_thinking", "delta": buf, "session_id": session_id})
                    else:
                        yield self._sse({"type": "answer_delta", "delta": buf, "session_id": session_id})
                        
            except Exception as exc:
                logger.warning(f"Direct answer stream error: {exc}")
                fallback = "暂时无法回答，请稍后重试。"
                yield self._sse({"type": "answer_delta", "delta": fallback, "session_id": session_id})
                return
                
            if not tool_calls:
                # Normal response finished
                break
                
            # Process tool calls
            assistant_message["tool_calls"] = tool_calls
            messages.append(dict(assistant_message))
            
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    raw_args = tc["function"]["arguments"]
                    tool_args = safe_loads(raw_args) if raw_args else {}
                except Exception:
                    tool_args = {}
                    
                if tool_name == "run_search_agent":
                    query = tool_args.get("query", user_message)
                    
                    search_agent = self.harness_engine.get_agent("Search")
                    search_input = {
                        "task_id": f"direct_answer_{session_id}",
                        "round_id": iteration + 1,
                        "search_id": f"search_{iteration}",
                        "planner_summary": "Direct answering agent requested a web search.",
                        "research_questions": [query]
                    }
                    
                    # Yield search stream to frontend
                    async for search_chunk in search_agent.search(
                        session_id=session_id,
                        search_input=search_input,
                        tools=self.harness_engine.active_tools(),
                        model=model,
                    ):
                        yield search_chunk
                        
                    report = search_agent.last_search_report
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", "unknown"),
                        "name": tool_name,
                        "content": json.dumps(report, ensure_ascii=False)
                    })
                else:
                    # Unknown tool
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", "unknown"),
                        "name": tool_name,
                        "content": "Error: Unknown tool."
                    })

        accumulated = strip_provider_thinking(accumulated)
        if accumulated.strip():
            self._append_assistant_message(chat_sessions, session_id, accumulated)
        yield self._sse({"done": True, "session_id": session_id})

    async def chat_stream(
        self,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        *,
        permission_mode: str = "ask",
        permission_confirmed: bool = False,
        context: str = "",
        tool_context: str = "workspace",
        enabled_skills: Optional[List[str]] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        try:
            _ = permission_mode
            _ = permission_confirmed
            _ = context
            _ = tool_context
            user_message = normalize_llm_message_content(chat_sessions.get(session_id, [])[-1].get("content") if chat_sessions.get(session_id) else "")
            strategy = self.harness_engine.default_strategy()
            selected_model = str((request_context or {}).get("model") or "").strip() or None
            workspace = self._workspace_path(request_context)
            if self.skill_manager is not None and hasattr(self.skill_manager, "set_workspace"):
                self.skill_manager.set_workspace(str(workspace))
            tools = self._tool_defs(enabled_skills)
            self.session_context_cache.setdefault(session_id, {})["last_user_message"] = user_message
            self.session_context_cache[session_id]["workspace"] = str(workspace)

            yield self._status("loading_context", session_id=session_id)  # 向前端 UI 推送一个“加载状态”的动画提示

            # Intent Router: for default strategy, skip the 5-agent pipeline
            # for simple conversational queries that don't require code changes.
            if strategy in ("agent", "default", "", None):
                yield self._status("routing", session_id=session_id)
                await self._update_memory_summaries(
                    user_message,
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                    model=selected_model,
                )
                router_decision = await self._classify_intent_with_llm(
                    user_message,
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                    model=selected_model,
                )
                intent = str(router_decision.get("route") or "WORKFLOW").strip().upper()
                if intent == "DIRECT_ANSWER":
                    async for chunk in self._direct_answer_stream(
                        session_id=session_id,
                        chat_sessions=chat_sessions,
                        user_message=user_message,
                        model=selected_model,
                        route="DIRECT_ANSWER",
                    ):
                        yield chunk
                    return
                yield self._sse({"type": "route", "route": "WORKFLOW", "router_decision": router_decision, "session_id": session_id})
                yield self._status("planning", session_id=session_id)

            existing_files = self._get_workspace_files_if_small(request_context)
            self.harness_engine.create_scaffold(workspace)  # 始化工作区（Workspace），为 Harness 的 5-Agent 工作流搭建必要的脚手架目录和默认配置
            budgets = self.harness_engine.get_budgets(str(workspace))
            provisional_task_id = f"task_{session_id.replace('-', '')[:12] or 'runtime'}"
            planner = PlannerAgent(self.vllm_client)
            context_bundle = await self._build_context_bundle(
                session_id=session_id,
                chat_sessions=chat_sessions,
                workspace=workspace,
                user_message=user_message,
                model=selected_model,
                request_context=request_context,
                previous_failures=[],
                search_reports=[],
                previous_verdicts=[],
            )
            self._persist_context_bundle(workspace, context_bundle)
            planner_input = self._build_planner_input(
                user_message=user_message,
                workspace=workspace,
                existing_files=existing_files,
                request_context=request_context,
                previous_failures=[],
                search_reports=[],
                context_bundle=context_bundle,
            )
            self._write_json_file(
                workspace,
                ".harness/task.json",
                {
                    "task_id": provisional_task_id,
                    "session_id": session_id,
                    "user_request": user_message,
                    "workspace": str(workspace),
                    "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "harness_strategy": strategy,
                    "permission_policy": permission_mode,
                    "sandbox_mode": self.harness_engine.DEFAULT_POLICY.get("sandbox_mode"),
                },
            )
            self._write_json_file(
                workspace,
                ".harness/session.json",
                {
                    "session_id": session_id,
                    "workspace": str(workspace),
                    "harness_strategy": strategy,
                    "model": selected_model or "",
                },
            )
            self._write_json_file(
                workspace,
                ".harness/project_summary.json",
                planner_input["task_context"]["project_summary"],
            )
            self._write_harness_state(
                workspace,
                task_id=provisional_task_id,
                round_id=1,
                state="PLAN",
                repair_round=0,
                replan_round=0,
                search_call_count=0,
            )
            self._write_json_file(workspace, ".harness/runs/run_001/input/planner_input.json", planner_input)
            self.harness_engine.validate_agent_input("Planner", planner_input)
            async for chunk in planner.plan(
                session_id=session_id,
                user_message=user_message,
                model=selected_model,
                existing_files=existing_files,
                project_summary=planner_input["task_context"]["project_summary"],
                previous_failures=planner_input["previous_failures"],
                constraints=planner_input["task_context"]["constraints"],
                search_reports=planner_input["task_context"]["search_reports"],
                recent_messages=(context_bundle or {}).get("recent_messages"),
            ):
                yield self._forward_chunk(chunk)
            plan_contract = planner.last_plan_contract
            if not plan_contract.get("task_id"):
                plan_contract["task_id"] = provisional_task_id
            
            round_str = f"{round_id:03d}" if 'round_id' in locals() else "001"
            run_out_path = f".harness/runs/run_{round_id:03d}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
            
            self._write_text_file(workspace, f".harness/plans/plan_{round_str}.md", planner.last_plan_markdown)
            self._write_json_file(workspace, f".harness/plans/plan_{round_str}.contract.json", plan_contract)
            self._write_json_file(workspace, f".harness/plans/plan_{round_str}.compiler_report.json", planner.last_compiler_report)
            
            if not planner.last_compiler_report.get("ok", True):
                yield self._sse(
                    {
                        "type": "harness_decision",
                        "decision": {
                            "decision": "PLAN_COMPILER_ERROR",
                            "reason": "Planner failed to produce valid markdown plan",
                            "next_agent": "",
                            "next_state": "TERMINAL_ERROR"
                        }
                    }
                )
                return
            
            self.harness_engine.validate_schema(plan_contract, "PlanContract")
            self._write_json_file(workspace, ".harness/plan.json", plan_contract)
            self._write_json_file(workspace, run_out_path, plan_contract)
            
            # Emit todo_list and create initial plan.md
            todo_items = [
                str(item.get("title") or item.get("description") or f"步骤 {idx}")
                for idx, item in enumerate(plan_contract.get("implementation_steps") or [], start=1)
                if isinstance(item, Mapping)
            ]
            
            if todo_items:
                yield self._sse({"type": "todo_list", "items": todo_items, "session_id": session_id})
                
                plan_md_content = "# Implementation Plan\n\n"
                for item in todo_items:
                    plan_md_content += f"- [ ] {item}\n"
                active_task_id = str(plan_contract.get("task_id") or provisional_task_id)
                self._write_text_file(workspace, f"plan_{active_task_id}.md", plan_md_content)
            yield self._agent_summary_event(
                role="Planner",
                payload={
                    "task_id": plan_contract.get("task_id") or provisional_task_id,
                    "summary": plan_contract.get("implementation_strategy") or plan_contract.get("goal") or "",
                    "display_summary": {
                        "title": "计划已生成",
                        "status": "success",
                        "summary": str(plan_contract.get("goal") or ""),
                        "highlights": [str(item.get("title") or "") for item in (plan_contract.get("implementation_steps") or [])[:3] if isinstance(item, Mapping)],
                        "user_visible": True,
                    },
                },
                round_id=1,
                state="PLAN",
            )
            self._write_harness_state(
                workspace,
                task_id=str(plan_contract.get("task_id") or provisional_task_id),
                round_id=1,
                state="VALIDATE_PLAN",
                repair_round=0,
                replan_round=0,
                search_call_count=0,
                last_completed_state="PLAN",
                last_artifact=".harness/plan.json",
            )

            round_id = 1
            repair_round = 0
            replan_round = 0
            search_call_count = 0
            previous_verdicts: List[Dict[str, Any]] = []
            search_reports: List[Dict[str, Any]] = []
            last_patch_result: Dict[str, Any] = {}
            last_run_report: Dict[str, Any] = {}
            final_verdict: Dict[str, Any] = {}
            last_diff_path = ""
            skip_generator = False
            completed_task_indices = set()

            while True:
                if self.harness_engine.should_search(user_request=user_message, plan=plan_contract) and not search_reports:
                    search_call_count += 1
                    context_bundle = await self._build_context_bundle(
                        session_id=session_id,
                        chat_sessions=chat_sessions,
                        workspace=workspace,
                        user_message=user_message,
                        model=selected_model,
                        request_context=request_context,
                        previous_failures=[],
                        search_reports=search_reports,
                        previous_verdicts=previous_verdicts,
                    )
                    self._persist_context_bundle(workspace, context_bundle)
                    search_input = self._build_search_input(
                        plan_contract=plan_contract,
                        round_id=round_id,
                        search_call_count=search_call_count,
                        triggered_by="Planner",
                        reason=str(((plan_contract.get("external_research") or {}).get("reason") or user_message)),
                        user_message=user_message,
                        context_bundle=context_bundle,
                    )
                    search_dir = f".harness/search/{search_input['search_id']}"
                    self._write_harness_state(
                        workspace,
                        task_id=str(plan_contract.get("task_id") or provisional_task_id),
                        round_id=round_id,
                        state="SEARCH",
                        repair_round=repair_round,
                        replan_round=replan_round,
                        search_call_count=search_call_count,
                        last_completed_state="VALIDATE_PLAN",
                    )
                    self._write_json_file(workspace, f"{search_dir}/search_request.json", search_input)
                    self.harness_engine.validate_agent_input("Search", search_input)
                    search_agent = SearchAgent(self.vllm_client, self.skill_manager)
                    async for chunk in search_agent.search(
                        session_id=session_id,
                        search_input=search_input,
                        tools=tools,
                        model=selected_model,
                    ):
                        yield self._forward_chunk(chunk)
                    search_report = search_agent.last_search_report
                    self.harness_engine.validate_schema(search_report, "SearchReport")
                    search_reports.append(search_report)
                    self._write_json_file(workspace, f"{search_dir}/search_report.json", search_report)
                    self._write_json_file(workspace, f"{search_dir}/sources.json", search_report.get("sources") or [])
                    self._write_json_file(workspace, f"{search_dir}/citations.json", search_report.get("key_findings") or [])
                    yield self._agent_summary_event(
                        role="Search",
                        payload=search_report,
                        round_id=round_id,
                        state="SEARCH",
                    )

                    if self.harness_engine.route_after_search(search_report, plan=plan_contract) == "REPLAN":
                        if replan_round >= int(budgets.get("max_replan_rounds", 1)):
                            final_verdict = {
                                "schema_version": "1.0",
                                "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
                                "round_id": round_id,
                                "verdict": "FAIL_HARD",
                                "score": 0.0,
                                "passed_criteria": [],
                                "failed_criteria": list(plan_contract.get("acceptance_criteria") or []),
                                "evidence": [str(search_report.get("status") or "FAILED")],
                                "root_cause": str(search_report.get("query_summary") or search_report.get("status") or "Search failed."),
                                "repair_instruction": "",
                                "needs_search": False,
                                "search_questions": [],
                                "next_agent": "None",
                                "confidence": 0.7,
                                "stop_reason": "Search failed or lacked evidence and no replan budget remained.",
                            }
                            final_verdict["display_summary"] = self.harness_engine.display_summary_for_output("Evaluator", final_verdict)
                            self._write_harness_state(
                                workspace,
                                task_id=str(plan_contract.get("task_id") or provisional_task_id),
                                round_id=round_id,
                                state="FAIL_HARD",
                                repair_round=repair_round,
                                replan_round=replan_round,
                                search_call_count=search_call_count,
                                last_completed_state="SEARCH",
                                last_artifact=f"{search_dir}/search_report.json",
                            )
                            break
                        replan_round += 1
                        round_id += 1
                        replan_reason = str(search_report.get("query_summary") or search_report.get("status") or "Search evidence was insufficient.")
                        context_bundle = await self._build_context_bundle(
                            session_id=session_id,
                            chat_sessions=chat_sessions,
                            workspace=workspace,
                            user_message=user_message,
                            model=selected_model,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
                            previous_verdicts=previous_verdicts,
                        )
                        self._persist_context_bundle(workspace, context_bundle)
                        planner = PlannerAgent(self.vllm_client)
                        planner_input = self._build_planner_input(
                            user_message="\n\n".join(part for part in [user_message, "[Search Failure]", replan_reason] if part),
                            workspace=workspace,
                            existing_files=existing_files,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
                            context_bundle=context_bundle,
                        )
                        self._write_harness_state(
                            workspace,
                            task_id=str(plan_contract.get("task_id") or provisional_task_id),
                            round_id=round_id,
                            state="REPLAN",
                            repair_round=repair_round,
                            replan_round=replan_round,
                            search_call_count=search_call_count,
                            last_completed_state="SEARCH",
                            last_artifact=f"{search_dir}/search_report.json",
                        )
                        self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/input/planner_input.json", planner_input)
                        self.harness_engine.validate_agent_input("Planner", planner_input)
                        async for chunk in planner.plan(
                            session_id=session_id,
                            user_message=planner_input["task_context"]["user_request"],
                            model=selected_model,
                            existing_files=existing_files,
                            project_summary=planner_input["task_context"]["project_summary"],
                            previous_failures=planner_input["previous_failures"],
                            constraints=planner_input["task_context"]["constraints"],
                            search_reports=planner_input["task_context"]["search_reports"],
                            recent_messages=(context_bundle or {}).get("recent_messages"),
                        ):
                            yield self._forward_chunk(chunk)
                        plan_contract = planner.last_plan_contract
                        if not plan_contract.get("task_id"):
                            plan_contract["task_id"] = provisional_task_id
                        
                        round_str = f"{round_id:03d}" if 'round_id' in locals() else "001"
                        run_out_path = f".harness/runs/run_{round_id:03d}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
                        
                        self._write_text_file(workspace, f".harness/plans/plan_{round_str}.md", planner.last_plan_markdown)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.contract.json", plan_contract)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.compiler_report.json", planner.last_compiler_report)
                        
                        if not planner.last_compiler_report.get("ok", True):
                            yield self._sse(
                                {
                                    "type": "harness_decision",
                                    "decision": {
                                        "decision": "PLAN_COMPILER_ERROR",
                                        "reason": "Planner failed to produce valid markdown plan",
                                        "next_agent": "",
                                        "next_state": "TERMINAL_ERROR"
                                    }
                                }
                            )
                            return
                        
                        self.harness_engine.validate_schema(plan_contract, "PlanContract")
                        self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                        self._write_json_file(workspace, run_out_path, plan_contract)
                        continue

                if not skip_generator:
                    before_patch_snapshot = self._capture_allowed_text_snapshot(workspace, plan_contract)
                    generator = GeneratorAgent(self.vllm_client, self.skill_manager)
                    context_bundle = await self._build_context_bundle(
                        session_id=session_id,
                        chat_sessions=chat_sessions,
                        workspace=workspace,
                        user_message=user_message,
                        model=selected_model,
                        request_context=request_context,
                        previous_failures=[],
                        search_reports=search_reports,
                        previous_verdicts=previous_verdicts,
                    )
                    self._persist_context_bundle(workspace, context_bundle)
                    generator_input = self._build_generator_input(
                        workspace=workspace,
                        plan_contract=plan_contract,
                        search_reports=search_reports,
                        last_run_report=last_run_report,
                        eval_verdict=previous_verdicts[-1] if previous_verdicts else {},
                        round_id=round_id,
                        context_bundle=context_bundle,
                    )
                    self._write_harness_state(
                        workspace,
                        task_id=str(plan_contract.get("task_id") or provisional_task_id),
                        round_id=round_id,
                        state="GENERATE",
                        repair_round=repair_round,
                        replan_round=replan_round,
                        search_call_count=search_call_count,
                        last_completed_state="SEARCH" if search_reports else "VALIDATE_PLAN",
                    )
                    run_root = f".harness/runs/run_{round_id:03d}"
                    self._write_json_file(workspace, f"{run_root}/input/generator_input.json", generator_input)
                    self.harness_engine.validate_agent_input("Generator", generator_input)
                    async for chunk in generator.generate(
                        session_id=session_id,
                        generator_input=generator_input,
                        tools=tools,
                        model=selected_model,
                    ):
                        yield self._forward_chunk(chunk)
                    last_patch_result = generator.last_patch_result
                    self.harness_engine.validate_schema(last_patch_result, "PatchResult")
                    self.harness_engine.validate_patch_policy(last_patch_result, plan_contract, workspace=workspace)
                    patch_application = await self.harness_engine.apply_patch_envelope(
                        last_patch_result.get("patch_envelope") or {},
                        plan_contract,
                        workspace=workspace,
                        vllm_client=self.vllm_client,
                        model=selected_model,
                    )
                    if any(patch_application.values()):
                        last_patch_result["changed_files"] = list(
                            dict.fromkeys(
                                [str(item) for item in last_patch_result.get("changed_files", []) or []]
                                + list(patch_application.get("changed_files") or [])
                            )
                        )
                        last_patch_result["created_files"] = list(
                            dict.fromkeys(
                                [str(item) for item in last_patch_result.get("created_files", []) or []]
                                + list(patch_application.get("created_files") or [])
                            )
                        )
                        last_patch_result["deleted_files"] = list(
                            dict.fromkeys(
                                [str(item) for item in last_patch_result.get("deleted_files", []) or []]
                                + list(patch_application.get("deleted_files") or [])
                            )
                        )
                        last_patch_result["display_summary"] = self.harness_engine.display_summary_for_output(
                            "Generator",
                            last_patch_result,
                        )
                    self._write_json_file(workspace, f"{run_root}/output/patch_result.json", last_patch_result)
                    self.session_context_cache[session_id]["last_plan_contract"] = plan_contract
                    self.session_context_cache[session_id]["last_patch_result"] = last_patch_result
                    yield self._agent_summary_event(
                        role="Generator",
                        payload=last_patch_result,
                        round_id=round_id,
                        state="GENERATE",
                    )
                    last_diff_path = self._write_text_file(
                        workspace,
                        f"{run_root}/diff.patch",
                        self._build_diff_patch(before_patch_snapshot, workspace, last_patch_result),
                    )
                    self._write_harness_state(
                        workspace,
                        task_id=str(plan_contract.get("task_id") or provisional_task_id),
                        round_id=round_id,
                        state="APPLY_PATCH",
                        repair_round=repair_round,
                        replan_round=replan_round,
                        search_call_count=search_call_count,
                        last_completed_state="GENERATE",
                        last_artifact=f"{run_root}/output/patch_result.json",
                    )

                    if (
                        self.harness_engine.patch_result_is_empty(last_patch_result)
                        and self.harness_engine.plan_requires_file_output(plan_contract)
                    ):
                        final_verdict = self.harness_engine.empty_patch_verdict(
                            plan_contract,
                            last_patch_result,
                            round_id=round_id,
                        )
                        self._write_json_file(workspace, f"{run_root}/output/eval_verdict.json", final_verdict)
                        yield self._agent_summary_event(
                            role="Evaluator",
                            payload=final_verdict,
                            round_id=round_id,
                            state="EVALUATE",
                        )
                        repeated_root_cause = self.harness_engine.same_error_repeated(
                            previous_verdicts,
                            final_verdict,
                            max_same_error_repeats=int(budgets.get("max_same_error_repeats", 2)),
                        )
                        previous_verdicts.append(final_verdict)
                        decision = self.harness_engine.build_harness_decision(
                            final_verdict,
                            repair_round=repair_round,
                            replan_round=replan_round,
                            search_call_count=search_call_count,
                            same_error_repeated=repeated_root_cause,
                            budgets=budgets,
                        )
                        self._write_json_file(workspace, f"{run_root}/output/harness_decision.json", decision)
                        yield self._harness_decision_event(decision)
                        self.session_context_cache[session_id].update(
                            {
                                "last_plan_contract": plan_contract,
                                "last_patch_result": last_patch_result,
                                "last_run_report": last_run_report,
                                "last_eval_verdict": final_verdict,
                                "last_harness_decision": decision,
                            }
                        )
                        context_bundle = await self._build_context_bundle(
                            session_id=session_id,
                            chat_sessions=chat_sessions,
                            workspace=workspace,
                            user_message=user_message,
                            model=selected_model,
                            request_context=request_context,
                            previous_failures=[str(final_verdict.get("root_cause") or "")],
                            search_reports=search_reports,
                            previous_verdicts=previous_verdicts,
                        )
                        self._persist_context_bundle(workspace, context_bundle)
                        if decision["decision"] == "CALL_GENERATOR":
                            repair_round += 1
                            round_id += 1
                            continue
                        if decision["decision"] == "CALL_PLANNER":
                            replan_round += 1
                            round_id += 1
                            replan_reason = str(final_verdict.get("root_cause") or final_verdict.get("repair_instruction") or "")
                            context_bundle = await self._build_context_bundle(
                                session_id=session_id,
                                chat_sessions=chat_sessions,
                                workspace=workspace,
                                user_message=user_message,
                                model=selected_model,
                                request_context=request_context,
                                previous_failures=[replan_reason] if replan_reason else [],
                                search_reports=search_reports,
                                previous_verdicts=previous_verdicts,
                            )
                            self._persist_context_bundle(workspace, context_bundle)
                            planner = PlannerAgent(self.vllm_client)
                            planner_input = self._build_planner_input(
                                user_message="\n\n".join(part for part in [user_message, "[Empty Generator Patch]", replan_reason] if part),
                                workspace=workspace,
                                existing_files=existing_files,
                                request_context=request_context,
                                previous_failures=[replan_reason] if replan_reason else [],
                                search_reports=search_reports,
                                context_bundle=context_bundle,
                            )
                            self._write_harness_state(
                                workspace,
                                task_id=str(plan_contract.get("task_id") or provisional_task_id),
                                round_id=round_id,
                                state="REPLAN",
                                repair_round=repair_round,
                                replan_round=replan_round,
                                search_call_count=search_call_count,
                                last_completed_state="APPLY_PATCH",
                                last_artifact=f"{run_root}/output/harness_decision.json",
                            )
                            self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/input/planner_input.json", planner_input)
                            self.harness_engine.validate_agent_input("Planner", planner_input)
                            async for chunk in planner.plan(
                                session_id=session_id,
                                user_message=planner_input["task_context"]["user_request"],
                                model=selected_model,
                                existing_files=existing_files,
                                project_summary=planner_input["task_context"]["project_summary"],
                                previous_failures=planner_input["previous_failures"],
                                constraints=planner_input["task_context"]["constraints"],
                                search_reports=planner_input["task_context"]["search_reports"],
                                recent_messages=(context_bundle or {}).get("recent_messages"),
                            ):
                                yield self._forward_chunk(chunk)
                            plan_contract = planner.last_plan_contract
                            if not plan_contract.get("task_id"):
                                plan_contract["task_id"] = provisional_task_id
                            
                            round_str = f"{round_id:03d}" if 'round_id' in locals() else "001"
                            run_out_path = f".harness/runs/run_{round_id:03d}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
                            
                            self._write_text_file(workspace, f".harness/plans/plan_{round_str}.md", planner.last_plan_markdown)
                            self._write_json_file(workspace, f".harness/plans/plan_{round_str}.contract.json", plan_contract)
                            self._write_json_file(workspace, f".harness/plans/plan_{round_str}.compiler_report.json", planner.last_compiler_report)
                            
                            if not planner.last_compiler_report.get("ok", True):
                                yield self._sse(
                                    {
                                        "type": "harness_decision",
                                        "decision": {
                                            "decision": "PLAN_COMPILER_ERROR",
                                            "reason": "Planner failed to produce valid markdown plan",
                                            "next_agent": "",
                                            "next_state": "TERMINAL_ERROR"
                                        }
                                    }
                                )
                                return
                            
                            self.harness_engine.validate_schema(plan_contract, "PlanContract")
                            self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                            self._write_json_file(workspace, run_out_path, plan_contract)
                            continue
                        self._write_harness_state(
                            workspace,
                            task_id=str(plan_contract.get("task_id") or provisional_task_id),
                            round_id=round_id,
                            state="FAIL_HARD",
                            repair_round=repair_round,
                            replan_round=replan_round,
                            search_call_count=search_call_count,
                            last_completed_state="APPLY_PATCH",
                            last_artifact=f"{run_root}/output/harness_decision.json",
                        )
                        break

                    if bool(last_patch_result.get("needs_replan")):
                        if replan_round >= int(budgets.get("max_replan_rounds", 1)):
                            final_verdict = {
                                "schema_version": "1.0",
                                "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
                                "round_id": round_id,
                                "verdict": "FAIL_HARD",
                                "score": 0.0,
                                "passed_criteria": [],
                                "failed_criteria": list(plan_contract.get("acceptance_criteria") or []),
                                "evidence": [str(last_patch_result.get("summary") or "Generator requested replan.")],
                                "root_cause": str(last_patch_result.get("replan_reason") or last_patch_result.get("summary") or "Generator requested replan."),
                                "repair_instruction": "",
                                "needs_search": False,
                                "search_questions": [],
                                "next_agent": "None",
                                "confidence": 0.75,
                                "stop_reason": "Generator requested replan but no replan budget remained.",
                            }
                            final_verdict["display_summary"] = self.harness_engine.display_summary_for_output("Evaluator", final_verdict)
                            self._write_harness_state(
                                workspace,
                                task_id=str(plan_contract.get("task_id") or provisional_task_id),
                                round_id=round_id,
                                state="FAIL_HARD",
                                repair_round=repair_round,
                                replan_round=replan_round,
                                search_call_count=search_call_count,
                                last_completed_state="GENERATE",
                                last_artifact=f"{run_root}/output/patch_result.json",
                            )
                            break
                        replan_round += 1
                        round_id += 1
                        replan_reason = str(last_patch_result.get("replan_reason") or last_patch_result.get("summary") or "Generator requested replan.")
                        context_bundle = await self._build_context_bundle(
                            session_id=session_id,
                            chat_sessions=chat_sessions,
                            workspace=workspace,
                            user_message=user_message,
                            model=selected_model,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
                            previous_verdicts=previous_verdicts,
                        )
                        self._persist_context_bundle(workspace, context_bundle)
                        planner = PlannerAgent(self.vllm_client)
                        planner_input = self._build_planner_input(
                            user_message="\n\n".join(part for part in [user_message, "[Generator Replan]", replan_reason] if part),
                            workspace=workspace,
                            existing_files=existing_files,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
                            context_bundle=context_bundle,
                        )
                        self._write_harness_state(
                            workspace,
                            task_id=str(plan_contract.get("task_id") or provisional_task_id),
                            round_id=round_id,
                            state="REPLAN",
                            repair_round=repair_round,
                            replan_round=replan_round,
                            search_call_count=search_call_count,
                            last_completed_state="GENERATE",
                            last_artifact=f"{run_root}/output/patch_result.json",
                        )
                        self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/input/planner_input.json", planner_input)
                        self.harness_engine.validate_agent_input("Planner", planner_input)
                        async for chunk in planner.plan(
                            session_id=session_id,
                            user_message=planner_input["task_context"]["user_request"],
                            model=selected_model,
                            existing_files=existing_files,
                            project_summary=planner_input["task_context"]["project_summary"],
                            previous_failures=planner_input["previous_failures"],
                            constraints=planner_input["task_context"]["constraints"],
                            search_reports=planner_input["task_context"]["search_reports"],
                            recent_messages=(context_bundle or {}).get("recent_messages"),
                        ):
                            yield self._forward_chunk(chunk)
                        plan_contract = planner.last_plan_contract
                        if not plan_contract.get("task_id"):
                            plan_contract["task_id"] = provisional_task_id
                        
                        round_str = f"{round_id:03d}" if 'round_id' in locals() else "001"
                        run_out_path = f".harness/runs/run_{round_id:03d}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
                        
                        self._write_text_file(workspace, f".harness/plans/plan_{round_str}.md", planner.last_plan_markdown)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.contract.json", plan_contract)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.compiler_report.json", planner.last_compiler_report)
                        
                        if not planner.last_compiler_report.get("ok", True):
                            yield self._sse(
                                {
                                    "type": "harness_decision",
                                    "decision": {
                                        "decision": "PLAN_COMPILER_ERROR",
                                        "reason": "Planner failed to produce valid markdown plan",
                                        "next_agent": "",
                                        "next_state": "TERMINAL_ERROR"
                                    }
                                }
                            )
                            return
                        
                        self.harness_engine.validate_schema(plan_contract, "PlanContract")
                        self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                        self._write_json_file(workspace, run_out_path, plan_contract)
                        continue
                skip_generator = False

                artifact_info = self._build_artifact_info(workspace, plan_contract)
                runner = RunnerAgent(self.vllm_client, self.skill_manager)
                context_bundle = await self._build_context_bundle(
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                    workspace=workspace,
                    user_message=user_message,
                    model=selected_model,
                    request_context=request_context,
                    previous_failures=[],
                    search_reports=search_reports,
                    previous_verdicts=previous_verdicts,
                )
                self._persist_context_bundle(workspace, context_bundle)
                runner_input = self._build_runner_input(
                    workspace=workspace,
                    plan_contract=plan_contract,
                    patch_result=last_patch_result,
                    search_reports=search_reports,
                    artifact_info=artifact_info,
                    round_id=round_id,
                    context_bundle=context_bundle,
                )
                run_root = f".harness/runs/run_{round_id:03d}"
                self._write_harness_state(
                    workspace,
                    task_id=str(plan_contract.get("task_id") or provisional_task_id),
                    round_id=round_id,
                    state="RUN",
                    repair_round=repair_round,
                    replan_round=replan_round,
                    search_call_count=search_call_count,
                    last_completed_state="APPLY_PATCH" if last_patch_result else "SEARCH",
                    last_artifact=last_diff_path,
                )
                self._write_json_file(workspace, f"{run_root}/input/runner_input.json", runner_input)
                self.harness_engine.validate_agent_input("Runner", runner_input)
                async for chunk in runner.run(
                    session_id=session_id,
                    runner_input=runner_input,
                    tools=tools,
                    model=selected_model,
                ):
                    yield self._forward_chunk(chunk)
                last_run_report = runner.last_run_report
                self.harness_engine.validate_schema(last_run_report, "RunReport")
                self._write_json_file(workspace, f"{run_root}/output/run_report.json", last_run_report)
                self.session_context_cache[session_id]["last_run_report"] = last_run_report
                yield self._agent_summary_event(
                    role="Runner",
                    payload=last_run_report,
                    round_id=round_id,
                    state="RUN",
                )

                evaluator = EvaluatorAgent(self.vllm_client)
                context_bundle = await self._build_context_bundle(
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                    workspace=workspace,
                    user_message=user_message,
                    model=selected_model,
                    request_context=request_context,
                    previous_failures=[],
                    search_reports=search_reports,
                    previous_verdicts=previous_verdicts,
                )
                self._persist_context_bundle(workspace, context_bundle)
                evaluation_input = self._build_evaluator_input(
                    plan_contract=plan_contract,
                    patch_result=last_patch_result,
                    run_report=last_run_report,
                    search_reports=search_reports,
                    previous_verdicts=previous_verdicts,
                    round_id=round_id,
                    diff_path=last_diff_path,
                    context_bundle=context_bundle,
                )
                self._write_harness_state(
                    workspace,
                    task_id=str(plan_contract.get("task_id") or provisional_task_id),
                    round_id=round_id,
                    state="EVALUATE",
                    repair_round=repair_round,
                    replan_round=replan_round,
                    search_call_count=search_call_count,
                    last_completed_state="RUN",
                    last_artifact=f"{run_root}/output/run_report.json",
                )
                self._write_json_file(workspace, f"{run_root}/input/evaluator_input.json", evaluation_input)
                self.harness_engine.validate_agent_input("Evaluator", evaluation_input)
                async for chunk in evaluator.evaluate(
                    session_id=session_id,
                    evaluation_input=evaluation_input,
                    model=selected_model,
                    workspace=workspace,
                ):
                    yield self._forward_chunk(chunk)
                final_verdict = evaluator.last_verdict
                self.harness_engine.validate_schema(final_verdict, "EvalVerdict")
                self._write_json_file(workspace, f"{run_root}/output/eval_verdict.json", final_verdict)
                self.session_context_cache[session_id]["last_eval_verdict"] = final_verdict
                yield self._agent_summary_event(
                    role="Evaluator",
                    payload=final_verdict,
                    round_id=round_id,
                    state="EVALUATE",
                )
                
                # Update task progress
                passed_criteria = final_verdict.get("passed_criteria") or []
                acceptance_criteria = plan_contract.get("acceptance_criteria") or []
                for idx, item in enumerate(plan_contract.get("implementation_steps") or []):
                    if idx in completed_task_indices:
                        continue
                    success_criteria = acceptance_criteria[idx] if idx < len(acceptance_criteria) else "完成该实施步骤并保持契约范围一致"
                    if final_verdict.get("verdict") == "PASS" or success_criteria in passed_criteria:
                        completed_task_indices.add(idx)
                        yield self._sse({"type": "todo_done", "index": idx, "session_id": session_id})
                
                if todo_items:
                    plan_md_content = "# Implementation Plan\n\n"
                    for idx, item in enumerate(todo_items):
                        mark = "x" if idx in completed_task_indices else " "
                        plan_md_content += f"- [{mark}] {item}\n"
                    active_task_id = str(plan_contract.get("task_id") or provisional_task_id)
                    self._write_text_file(workspace, f"plan_{active_task_id}.md", plan_md_content)

                repeated_root_cause = self.harness_engine.same_error_repeated(
                    previous_verdicts,
                    final_verdict,
                    max_same_error_repeats=int(budgets.get("max_same_error_repeats", 2)),
                )
                previous_verdicts.append(final_verdict)

                decision = self.harness_engine.build_harness_decision(
                    final_verdict,
                    repair_round=repair_round,
                    replan_round=replan_round,
                    search_call_count=search_call_count,
                    same_error_repeated=repeated_root_cause,
                    budgets=budgets,
                )
                await self._humanize_harness_decision(decision, model=selected_model)
                self._write_json_file(workspace, f"{run_root}/output/harness_decision.json", decision)
                yield self._harness_decision_event(decision)
                self.session_context_cache[session_id].update(
                    {
                        "last_plan_contract": plan_contract,
                        "last_patch_result": last_patch_result,
                        "last_run_report": last_run_report,
                        "last_eval_verdict": final_verdict,
                        "last_harness_decision": decision,
                    }
                )
                context_bundle = await self._build_context_bundle(
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                    workspace=workspace,
                    user_message=user_message,
                    model=selected_model,
                    request_context=request_context,
                    previous_failures=[str(final_verdict.get("root_cause") or "")],
                    search_reports=search_reports,
                    previous_verdicts=previous_verdicts,
                )
                self._persist_context_bundle(workspace, context_bundle)

                if decision["decision"] == "PASS":
                    self._write_harness_state(
                        workspace,
                        task_id=str(plan_contract.get("task_id") or provisional_task_id),
                        round_id=round_id,
                        state="PASS",
                        repair_round=repair_round,
                        replan_round=replan_round,
                        search_call_count=search_call_count,
                        last_completed_state="EVALUATE",
                        last_artifact=f"{run_root}/output/harness_decision.json",
                    )
                    break
                if decision["decision"] == "CALL_SEARCH":
                    if search_call_count >= int(budgets.get("max_search_calls_per_task", 2)):
                        final_verdict = {
                            "schema_version": "1.0",
                            "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
                            "round_id": round_id,
                            "verdict": "FAIL_HARD",
                            "score": 0.0,
                            "passed_criteria": [],
                            "failed_criteria": list(plan_contract.get("acceptance_criteria") or []),
                            "evidence": [str(final_verdict.get("root_cause") or "Search budget exceeded.")],
                            "root_cause": str(final_verdict.get("root_cause") or "Search budget exceeded."),
                            "repair_instruction": "",
                            "needs_search": False,
                            "search_questions": [],
                            "next_agent": "None",
                            "confidence": 0.7,
                            "stop_reason": "Search was requested but search budget was exhausted.",
                        }
                        final_verdict["display_summary"] = self.harness_engine.display_summary_for_output("Evaluator", final_verdict)
                        self._write_harness_state(
                            workspace,
                            task_id=str(plan_contract.get("task_id") or provisional_task_id),
                            round_id=round_id,
                            state="FAIL_HARD",
                            repair_round=repair_round,
                            replan_round=replan_round,
                            search_call_count=search_call_count,
                            last_completed_state="EVALUATE",
                            last_artifact=f"{run_root}/output/harness_decision.json",
                        )
                        break
                    search_call_count += 1
                    context_bundle = await self._build_context_bundle(
                        session_id=session_id,
                        chat_sessions=chat_sessions,
                        workspace=workspace,
                        user_message=user_message,
                        model=selected_model,
                        request_context=request_context,
                        previous_failures=[str(final_verdict.get("root_cause") or "")],
                        search_reports=search_reports,
                        previous_verdicts=previous_verdicts,
                    )
                    self._persist_context_bundle(workspace, context_bundle)
                    search_input = self._build_search_input(
                        plan_contract=plan_contract,
                        round_id=round_id,
                        search_call_count=search_call_count,
                        triggered_by="Evaluator",
                        reason=str(final_verdict.get("root_cause") or "Evaluator requested external research."),
                        user_message=user_message,
                        run_report=last_run_report,
                        eval_verdict=final_verdict,
                        context_bundle=context_bundle,
                    )
                    search_dir = f".harness/search/{search_input['search_id']}"
                    self._write_harness_state(
                        workspace,
                        task_id=str(plan_contract.get("task_id") or provisional_task_id),
                        round_id=round_id,
                        state="SEARCH",
                        repair_round=repair_round,
                        replan_round=replan_round,
                        search_call_count=search_call_count,
                        last_completed_state="EVALUATE",
                        last_artifact=f"{run_root}/output/harness_decision.json",
                    )
                    self._write_json_file(workspace, f"{search_dir}/search_request.json", search_input)
                    self.harness_engine.validate_agent_input("Search", search_input)
                    search_agent = SearchAgent(self.vllm_client, self.skill_manager)
                    async for chunk in search_agent.search(
                        session_id=session_id,
                        search_input=search_input,
                        tools=tools,
                        model=selected_model,
                    ):
                        yield self._forward_chunk(chunk)
                    search_report = search_agent.last_search_report
                    self.harness_engine.validate_schema(search_report, "SearchReport")
                    search_reports.append(search_report)
                    self._write_json_file(workspace, f"{search_dir}/search_report.json", search_report)
                    self._write_json_file(workspace, f"{search_dir}/sources.json", search_report.get("sources") or [])
                    self._write_json_file(workspace, f"{search_dir}/citations.json", search_report.get("key_findings") or [])
                    yield self._agent_summary_event(
                        role="Search",
                        payload=search_report,
                        round_id=round_id,
                        state="SEARCH",
                    )
                    round_id += 1
                    next_state_after_search = self.harness_engine.route_after_search(
                        search_report,
                        plan=plan_contract,
                        verdict=final_verdict,
                    )
                    if next_state_after_search == "REPLAN":
                        if replan_round >= int(budgets.get("max_replan_rounds", 1)):
                            final_verdict = {
                                "schema_version": "1.0",
                                "task_id": str(plan_contract.get("task_id") or "task_runtime_001"),
                                "round_id": round_id,
                                "verdict": "FAIL_HARD",
                                "score": 0.0,
                                "passed_criteria": [],
                                "failed_criteria": list(plan_contract.get("acceptance_criteria") or []),
                                "evidence": [str(search_report.get("status") or "FAILED")],
                                "root_cause": str(search_report.get("query_summary") or search_report.get("status") or "Search failed after evaluation."),
                                "repair_instruction": "",
                                "needs_search": False,
                                "search_questions": [],
                                "next_agent": "None",
                                "confidence": 0.7,
                                "stop_reason": "Search after evaluation failed and no replan budget remained.",
                            }
                            final_verdict["display_summary"] = self.harness_engine.display_summary_for_output("Evaluator", final_verdict)
                            self._write_harness_state(
                                workspace,
                                task_id=str(plan_contract.get("task_id") or provisional_task_id),
                                round_id=round_id,
                                state="FAIL_HARD",
                                repair_round=repair_round,
                                replan_round=replan_round,
                                search_call_count=search_call_count,
                                last_completed_state="SEARCH",
                                last_artifact=f"{search_dir}/search_report.json",
                            )
                            break
                        replan_round += 1
                        replan_reason = str(search_report.get("query_summary") or search_report.get("status") or "Search evidence was insufficient.")
                        context_bundle = await self._build_context_bundle(
                            session_id=session_id,
                            chat_sessions=chat_sessions,
                            workspace=workspace,
                            user_message=user_message,
                            model=selected_model,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
                            previous_verdicts=previous_verdicts,
                        )
                        self._persist_context_bundle(workspace, context_bundle)
                        planner = PlannerAgent(self.vllm_client)
                        planner_input = self._build_planner_input(
                            user_message="\n\n".join(part for part in [user_message, "[Evaluator Search]", replan_reason] if part),
                            workspace=workspace,
                            existing_files=existing_files,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
                            context_bundle=context_bundle,
                        )
                        self._write_harness_state(
                            workspace,
                            task_id=str(plan_contract.get("task_id") or provisional_task_id),
                            round_id=round_id,
                            state="REPLAN",
                            repair_round=repair_round,
                            replan_round=replan_round,
                            search_call_count=search_call_count,
                            last_completed_state="SEARCH",
                            last_artifact=f"{search_dir}/search_report.json",
                        )
                        self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/input/planner_input.json", planner_input)
                        self.harness_engine.validate_agent_input("Planner", planner_input)
                        async for chunk in planner.plan(
                            session_id=session_id,
                            user_message=planner_input["task_context"]["user_request"],
                            model=selected_model,
                            existing_files=existing_files,
                            project_summary=planner_input["task_context"]["project_summary"],
                            previous_failures=planner_input["previous_failures"],
                            constraints=planner_input["task_context"]["constraints"],
                            search_reports=planner_input["task_context"]["search_reports"],
                            recent_messages=(context_bundle or {}).get("recent_messages"),
                        ):
                            yield self._forward_chunk(chunk)
                        plan_contract = planner.last_plan_contract
                        if not plan_contract.get("task_id"):
                            plan_contract["task_id"] = provisional_task_id
                        
                        round_str = f"{round_id:03d}" if 'round_id' in locals() else "001"
                        run_out_path = f".harness/runs/run_{round_id:03d}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
                        
                        self._write_text_file(workspace, f".harness/plans/plan_{round_str}.md", planner.last_plan_markdown)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.contract.json", plan_contract)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.compiler_report.json", planner.last_compiler_report)
                        
                        if not planner.last_compiler_report.get("ok", True):
                            yield self._sse(
                                {
                                    "type": "harness_decision",
                                    "decision": {
                                        "decision": "PLAN_COMPILER_ERROR",
                                        "reason": "Planner failed to produce valid markdown plan",
                                        "next_agent": "",
                                        "next_state": "TERMINAL_ERROR"
                                    }
                                }
                            )
                            return
                        
                        self.harness_engine.validate_schema(plan_contract, "PlanContract")
                        self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                        self._write_json_file(workspace, run_out_path, plan_contract)
                    elif next_state_after_search == "RUN":
                        skip_generator = True
                    continue
                if decision["decision"] == "CALL_GENERATOR" and repair_round < int(budgets.get("max_repair_rounds", 3)):
                    repair_round += 1
                    round_id += 1
                    continue
                if decision["decision"] == "CALL_PLANNER" and replan_round < int(budgets.get("max_replan_rounds", 1)):
                    replan_round += 1
                    round_id += 1
                    replan_reason = str(final_verdict.get("root_cause") or final_verdict.get("repair_instruction") or "")
                    context_bundle = await self._build_context_bundle(
                        session_id=session_id,
                        chat_sessions=chat_sessions,
                        workspace=workspace,
                        user_message=user_message,
                        model=selected_model,
                        request_context=request_context,
                        previous_failures=[replan_reason] if replan_reason else [],
                        search_reports=search_reports,
                        previous_verdicts=previous_verdicts,
                    )
                    self._persist_context_bundle(workspace, context_bundle)
                    planner = PlannerAgent(self.vllm_client)
                    planner_input = self._build_planner_input(
                        user_message="\n\n".join(part for part in [user_message, "[Previous EvalVerdict]", replan_reason] if part),
                        workspace=workspace,
                        existing_files=existing_files,
                        request_context=request_context,
                        previous_failures=[replan_reason] if replan_reason else [],
                        search_reports=search_reports,
                        context_bundle=context_bundle,
                    )
                    self._write_harness_state(
                        workspace,
                        task_id=str(plan_contract.get("task_id") or provisional_task_id),
                        round_id=round_id,
                        state="REPLAN",
                        repair_round=repair_round,
                        replan_round=replan_round,
                        search_call_count=search_call_count,
                        last_completed_state="EVALUATE",
                        last_artifact=f"{run_root}/output/harness_decision.json",
                    )
                    self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/input/planner_input.json", planner_input)
                    self.harness_engine.validate_agent_input("Planner", planner_input)
                    async for chunk in planner.plan(
                        session_id=session_id,
                        user_message=planner_input["task_context"]["user_request"],
                        model=selected_model,
                        existing_files=existing_files,
                        project_summary=planner_input["task_context"]["project_summary"],
                        previous_failures=planner_input["previous_failures"],
                        constraints=planner_input["task_context"]["constraints"],
                        search_reports=planner_input["task_context"]["search_reports"],
                        recent_messages=(context_bundle or {}).get("recent_messages"),
                    ):
                        yield self._forward_chunk(chunk)
                    plan_contract = planner.last_plan_contract
                    if not plan_contract.get("task_id"):
                        plan_contract["task_id"] = provisional_task_id
                    
                    round_str = f"{round_id:03d}" if 'round_id' in locals() else "001"
                    run_out_path = f".harness/runs/run_{round_id:03d}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
                    
                    self._write_text_file(workspace, f".harness/plans/plan_{round_str}.md", planner.last_plan_markdown)
                    self._write_json_file(workspace, f".harness/plans/plan_{round_str}.contract.json", plan_contract)
                    self._write_json_file(workspace, f".harness/plans/plan_{round_str}.compiler_report.json", planner.last_compiler_report)
                    
                    if not planner.last_compiler_report.get("ok", True):
                        yield self._sse(
                            {
                                "type": "harness_decision",
                                "decision": {
                                    "decision": "PLAN_COMPILER_ERROR",
                                    "reason": "Planner failed to produce valid markdown plan",
                                    "next_agent": "",
                                    "next_state": "TERMINAL_ERROR"
                                }
                            }
                        )
                        return
                    
                    self.harness_engine.validate_schema(plan_contract, "PlanContract")
                    self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                    self._write_json_file(workspace, run_out_path, plan_contract)
                    continue
                self._write_harness_state(
                    workspace,
                    task_id=str(plan_contract.get("task_id") or provisional_task_id),
                    round_id=round_id,
                    state="FAIL_HARD",
                    repair_round=repair_round,
                    replan_round=replan_round,
                    search_call_count=search_call_count,
                    last_completed_state="EVALUATE",
                    last_artifact=f"{run_root}/output/harness_decision.json",
                )
                break

            final_answer = self._final_answer(plan_contract, last_patch_result, last_run_report, final_verdict, workspace)
            self._append_assistant_message(chat_sessions, session_id, final_answer)
            yield self._sse({"type": "answer_delta", "delta": final_answer, "session_id": session_id})
            yield self._sse({"done": True, "session_id": session_id})
        except Exception as exc:
            logger.exception("HarnessRuntime error")
            error_text = str(exc).strip() or repr(exc)
            error_type = type(exc).__name__
            tb = traceback.format_exc()
            last_line = tb.strip().rsplit("\n", 1)[-1].strip() if tb else error_text
            combined = error_text if not last_line or last_line == error_text else f"{error_text}\n↳ {last_line}"
            yield self._sse(
                {
                    "error": combined,
                    "error_type": error_type,
                    "error_detail": last_line,
                    "done": True,
                    "session_id": session_id,
                }
            )
