import json
import difflib
import traceback
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
        execution_engine: Any = None,
        plan_agent: Any = None,
        request_lifecycle: Optional[RequestLifecycle] = None,
    ) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.execution_engine = execution_engine
        self.plan_agent = plan_agent
        self.request_lifecycle = request_lifecycle or RequestLifecycle()
        self.session_context_cache: Dict[str, Dict[str, Any]] = {}
        self.harness_engine = HarnessEngine()

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _phase(self, key: str, **overrides: Any) -> str:
        return self._sse(self.request_lifecycle.phase_payload(key, **overrides))

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
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))

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
            payload = json.loads(raw_chunk[6:].strip())
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

    def _final_answer(
        self,
        plan_contract: Mapping[str, Any],
        patch_result: Optional[Mapping[str, Any]],
        run_report: Optional[Mapping[str, Any]],
        verdict: Mapping[str, Any],
    ) -> str:
        verdict_name = str(verdict.get("verdict") or "")
        summary = (verdict.get("display_summary") or {}).get("summary") or verdict.get("root_cause") or ""
        lines: List[str] = []
        if verdict_name == "PASS":
            lines.append("## 完成情况")
            lines.append(f"- **结果**：{summary or '任务已通过验收。'}")
            if patch_result:
                changed_files = [str(item) for item in patch_result.get("changed_files", []) or []]
                if changed_files:
                    lines.append("- **修改文件**：" + "、".join(changed_files[:8]))
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
    ) -> Dict[str, Any]:
        return {
            "task_context": {
                "user_request": user_message,
                "workspace": str(workspace),
                "project_summary": self._planner_project_summary(workspace, existing_files),
                "constraints": self._planner_constraints(request_context),
                "search_reports": list(search_reports or []),
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
                "overall_timeout_sec": int((self.harness_engine.DEFAULT_BUDGETS.get("timeouts") or {}).get("runner_sec", 300)),
                "command_timeout_sec": int((self.harness_engine.DEFAULT_BUDGETS.get("timeouts") or {}).get("command_default_sec", 120)),
                "dev_server_timeout_sec": int((self.harness_engine.DEFAULT_BUDGETS.get("timeouts") or {}).get("dev_server_sec", 60)),
                "browser_test_timeout_sec": int((self.harness_engine.DEFAULT_BUDGETS.get("timeouts") or {}).get("browser_test_sec", 60)),
            },
            "permissions": dict((self.harness_engine.default_policy(str(workspace)).get("agent_permissions") or {}).get("Runner") or {}),
            "search_reports": list(search_reports or []),
            "artifact_info": dict(artifact_info or {}),
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
        planner_input = self._build_planner_input(
            user_message=user_message,
            workspace=workspace,
            existing_files=existing_files,
            request_context=request_context,
            previous_failures=[],
            search_reports=[],
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
                "task_graph": {
                    "tasks": tasks,
                    "edges": [
                        {"from": f"T{index}", "to": f"T{index + 1}"}
                        for index in range(1, len(tasks))
                    ],
                },
                "session_id": session_id,
            }
        )
        final_text = self._final_answer(plan_contract, None, None, {"verdict": "PASS", "display_summary": {"summary": "PlanContract 已生成。"}})
        self._append_assistant_message(chat_sessions, session_id, final_text)
        yield self._sse({"type": "answer_delta", "delta": final_text, "session_id": session_id})
        yield self._sse({"done": True, "session_id": session_id})

    async def chat_stream(
        self,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        *,
        mode: str = "agent",
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
            strategy = self.harness_engine.strategy_for_mode(mode)
            selected_model = str((request_context or {}).get("model") or "").strip() or None
            workspace = self._workspace_path(request_context)
            if self.skill_manager is not None and hasattr(self.skill_manager, "set_workspace"):
                self.skill_manager.set_workspace(str(workspace))
            tools = self._tool_defs(enabled_skills)
            self.session_context_cache.setdefault(session_id, {})["last_user_message"] = user_message
            self.session_context_cache[session_id]["workspace"] = str(workspace)

            if strategy == "create":
                yield self._phase("create", session_id=session_id)
            else:
                yield self._phase("prep_context", session_id=session_id)

            if strategy == "planner_only":
                async for chunk in self._planner_only_stream(
                    session_id=session_id,
                    chat_sessions=chat_sessions,
                    user_message=user_message,
                    request_context=request_context,
                    enabled_skills=enabled_skills,
                    model=selected_model,
                ):
                    yield chunk
                return

            budgets = self.harness_engine.default_budgets()
            existing_files = self._get_workspace_files_if_small(request_context)
            self.harness_engine.create_scaffold(workspace)
            provisional_task_id = f"task_{session_id.replace('-', '')[:12] or 'runtime'}"
            planner = PlannerAgent(self.vllm_client)
            planner_input = self._build_planner_input(
                user_message=user_message,
                workspace=workspace,
                existing_files=existing_files,
                request_context=request_context,
                previous_failures=[],
                search_reports=[],
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
                    "mode": strategy,
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
                    "mode": strategy,
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
            ):
                yield self._forward_chunk(chunk)
            plan_contract = planner.last_plan_contract
            if not plan_contract.get("task_id"):
                plan_contract["task_id"] = provisional_task_id
            self.harness_engine.validate_schema(plan_contract, "PlanContract")
            self._write_json_file(workspace, ".harness/plan.json", plan_contract)
            self._write_json_file(workspace, ".harness/runs/run_001/output/plan_contract.json", plan_contract)
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

            while True:
                if self.harness_engine.should_search(user_request=user_message, plan=plan_contract) and not search_reports:
                    search_call_count += 1
                    search_input = self._build_search_input(
                        plan_contract=plan_contract,
                        round_id=round_id,
                        search_call_count=search_call_count,
                        triggered_by="Planner",
                        reason=str(((plan_contract.get("external_research") or {}).get("reason") or user_message)),
                        user_message=user_message,
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
                        planner = PlannerAgent(self.vllm_client)
                        planner_input = self._build_planner_input(
                            user_message="\n\n".join(part for part in [user_message, "[Search Failure]", replan_reason] if part),
                            workspace=workspace,
                            existing_files=existing_files,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
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
                        ):
                            yield self._forward_chunk(chunk)
                        plan_contract = planner.last_plan_contract
                        if not plan_contract.get("task_id"):
                            plan_contract["task_id"] = provisional_task_id
                        self.harness_engine.validate_schema(plan_contract, "PlanContract")
                        self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                        self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/output/plan_contract.json", plan_contract)
                        continue

                if not skip_generator:
                    before_patch_snapshot = self._capture_allowed_text_snapshot(workspace, plan_contract)
                    generator = GeneratorAgent(self.vllm_client, self.skill_manager)
                    generator_input = self._build_generator_input(
                        workspace=workspace,
                        plan_contract=plan_contract,
                        search_reports=search_reports,
                        last_run_report=last_run_report,
                        eval_verdict=previous_verdicts[-1] if previous_verdicts else {},
                        round_id=round_id,
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
                    self.harness_engine.validate_patch_envelope(
                        last_patch_result.get("patch_envelope") or {},
                        plan_contract,
                        workspace=workspace,
                    )
                    self._write_json_file(workspace, f"{run_root}/output/patch_result.json", last_patch_result)
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
                        if decision["decision"] == "CALL_GENERATOR":
                            repair_round += 1
                            round_id += 1
                            continue
                        if decision["decision"] == "CALL_PLANNER":
                            replan_round += 1
                            round_id += 1
                            replan_reason = str(final_verdict.get("root_cause") or final_verdict.get("repair_instruction") or "")
                            planner = PlannerAgent(self.vllm_client)
                            planner_input = self._build_planner_input(
                                user_message="\n\n".join(part for part in [user_message, "[Empty Generator Patch]", replan_reason] if part),
                                workspace=workspace,
                                existing_files=existing_files,
                                request_context=request_context,
                                previous_failures=[replan_reason] if replan_reason else [],
                                search_reports=search_reports,
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
                            ):
                                yield self._forward_chunk(chunk)
                            plan_contract = planner.last_plan_contract
                            if not plan_contract.get("task_id"):
                                plan_contract["task_id"] = provisional_task_id
                            self.harness_engine.validate_schema(plan_contract, "PlanContract")
                            self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                            self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/output/plan_contract.json", plan_contract)
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
                        planner = PlannerAgent(self.vllm_client)
                        planner_input = self._build_planner_input(
                            user_message="\n\n".join(part for part in [user_message, "[Generator Replan]", replan_reason] if part),
                            workspace=workspace,
                            existing_files=existing_files,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
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
                        ):
                            yield self._forward_chunk(chunk)
                        plan_contract = planner.last_plan_contract
                        if not plan_contract.get("task_id"):
                            plan_contract["task_id"] = provisional_task_id
                        self.harness_engine.validate_schema(plan_contract, "PlanContract")
                        self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                        self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/output/plan_contract.json", plan_contract)
                        continue
                skip_generator = False

                artifact_info = self._build_artifact_info(workspace, plan_contract)
                runner = RunnerAgent(self.vllm_client, self.skill_manager)
                runner_input = self._build_runner_input(
                    workspace=workspace,
                    plan_contract=plan_contract,
                    patch_result=last_patch_result,
                    search_reports=search_reports,
                    artifact_info=artifact_info,
                    round_id=round_id,
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
                yield self._agent_summary_event(
                    role="Runner",
                    payload=last_run_report,
                    round_id=round_id,
                    state="RUN",
                )

                evaluator = EvaluatorAgent(self.vllm_client)
                evaluation_input = self._build_evaluator_input(
                    plan_contract=plan_contract,
                    patch_result=last_patch_result,
                    run_report=last_run_report,
                    search_reports=search_reports,
                    previous_verdicts=previous_verdicts,
                    round_id=round_id,
                    diff_path=last_diff_path,
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
                ):
                    yield self._forward_chunk(chunk)
                final_verdict = evaluator.last_verdict
                self.harness_engine.validate_schema(final_verdict, "EvalVerdict")
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
                    search_input = self._build_search_input(
                        plan_contract=plan_contract,
                        round_id=round_id,
                        search_call_count=search_call_count,
                        triggered_by="Evaluator",
                        reason=str(final_verdict.get("root_cause") or "Evaluator requested external research."),
                        user_message=user_message,
                        run_report=last_run_report,
                        eval_verdict=final_verdict,
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
                        planner = PlannerAgent(self.vllm_client)
                        planner_input = self._build_planner_input(
                            user_message="\n\n".join(part for part in [user_message, "[Evaluator Search]", replan_reason] if part),
                            workspace=workspace,
                            existing_files=existing_files,
                            request_context=request_context,
                            previous_failures=[replan_reason],
                            search_reports=search_reports,
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
                        ):
                            yield self._forward_chunk(chunk)
                        plan_contract = planner.last_plan_contract
                        if not plan_contract.get("task_id"):
                            plan_contract["task_id"] = provisional_task_id
                        self.harness_engine.validate_schema(plan_contract, "PlanContract")
                        self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                        self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/output/plan_contract.json", plan_contract)
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
                    planner = PlannerAgent(self.vllm_client)
                    planner_input = self._build_planner_input(
                        user_message="\n\n".join(part for part in [user_message, "[Previous EvalVerdict]", replan_reason] if part),
                        workspace=workspace,
                        existing_files=existing_files,
                        request_context=request_context,
                        previous_failures=[replan_reason] if replan_reason else [],
                        search_reports=search_reports,
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
                    ):
                        yield self._forward_chunk(chunk)
                    plan_contract = planner.last_plan_contract
                    if not plan_contract.get("task_id"):
                        plan_contract["task_id"] = provisional_task_id
                    self.harness_engine.validate_schema(plan_contract, "PlanContract")
                    self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                    self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/output/plan_contract.json", plan_contract)
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

            final_answer = self._final_answer(plan_contract, last_patch_result, last_run_report, final_verdict)
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
