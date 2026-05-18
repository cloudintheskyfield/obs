from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class SessionStorePaths:
    llm_trace_dir: Path
    session_store_dir: Path
    context_cache_dir: Path
    thread_workspace_dir: Path
    workspace_state_file: Path
    ui_sessions_dir: Path
    published_projects_dir: Path


class SessionStore:
    """Persistent storage for chat history, compacted memory, traces, and UI state.

    This mirrors Claude Code's separation between the request loop and the
    persistence layer: API and agents operate on in-memory state, while
    SessionStore handles durable JSON/JSONL artifacts on disk.
    """

    def __init__(self, paths: SessionStorePaths):
        self.paths = paths
        self.paths.llm_trace_dir.mkdir(parents=True, exist_ok=True)
        self.paths.session_store_dir.mkdir(parents=True, exist_ok=True)
        self.paths.context_cache_dir.mkdir(parents=True, exist_ok=True)
        self.paths.thread_workspace_dir.mkdir(parents=True, exist_ok=True)
        self.paths.ui_sessions_dir.mkdir(parents=True, exist_ok=True)
        self.paths.published_projects_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config: Any) -> "SessionStore":
        base_dir = (
            Path(config.log.file_path).parent
            if getattr(config.log, "file_path", None)
            else Path(config.work_dir).parent / "logs"
        )
        return cls(
            SessionStorePaths(
                llm_trace_dir=base_dir / "llm_traces",
                session_store_dir=base_dir / "chat_sessions",
                context_cache_dir=base_dir / "context_cache",
                thread_workspace_dir=base_dir / "thread_workspaces",
                workspace_state_file=base_dir / "workspace_state.json",
                ui_sessions_dir=base_dir / "ui_sessions",
                published_projects_dir=base_dir / "published_projects",
            )
        )

    @staticmethod
    def sanitize_session_id(session_id: str, max_len: int = 120) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", session_id)[:max_len]

    def llm_trace_file(self, session_id: str) -> Path:
        return self.paths.llm_trace_dir / f"{self.sanitize_session_id(session_id)}.jsonl"

    def chat_session_file(self, session_id: str) -> Path:
        return self.paths.session_store_dir / f"{self.sanitize_session_id(session_id)}.json"

    def context_cache_file(self, session_id: str) -> Path:
        return self.paths.context_cache_dir / f"{self.sanitize_session_id(session_id)}.json"

    def ui_session_file(self, session_id: str) -> Path:
        return self.paths.ui_sessions_dir / f"{self.sanitize_session_id(session_id, max_len=80)}.json"

    def published_project_file(self, project_id: str) -> Path:
        return self.paths.published_projects_dir / f"{self.sanitize_session_id(project_id, max_len=80)}.json"

    def thread_runtime_dir(self, session_id: str) -> str:
        path = self.paths.thread_workspace_dir / self.sanitize_session_id(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def persist_llm_trace(self, session_id: str, payload: Dict[str, Any]) -> None:
        record = {
            "session_id": session_id,
            "timestamp": payload.get("timestamp") or datetime.now().astimezone().isoformat(timespec="seconds"),
            "phase": payload.get("phase"),
            "direction": payload.get("direction"),
            "payload": payload.get("payload"),
            "type": "llm_log",
        }
        with self.llm_trace_file(session_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_llm_traces(self, session_id: str) -> List[Dict[str, Any]]:
        trace_file = self.llm_trace_file(session_id)
        if not trace_file.exists():
            return []
        records: List[Dict[str, Any]] = []
        with trace_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def load_chat_session(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        session_file = self.chat_session_file(session_id)
        if not session_file.exists():
            return None
        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
            messages = payload.get("messages")
            if isinstance(messages, list):
                return messages
        except Exception as exc:
            logger.warning(f"Failed to load chat session {session_id}: {exc}")
        return None

    def list_chat_sessions(self) -> List[Dict[str, Any]]:
        sessions: List[Dict[str, Any]] = []
        for file_path in sorted(
            self.paths.session_store_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            messages = payload.get("messages")
            if not isinstance(messages, list):
                continue
            session_id = str(payload.get("session_id") or file_path.stem)
            sessions.append(
                {
                    "session_id": session_id,
                    "updated_at": str(payload.get("updated_at") or ""),
                    "messages": messages,
                }
            )
        return sessions

    def persist_chat_session(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        payload = {
            "session_id": session_id,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "messages": messages,
        }
        self.chat_session_file(session_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_context_cache(self, session_id: str) -> Optional[Dict[str, Any]]:
        cache_file = self.context_cache_file(session_id)
        if not cache_file.exists():
            return None
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            cache = payload.get("cache")
            if isinstance(cache, dict):
                return cache
        except Exception as exc:
            logger.warning(f"Failed to load context cache {session_id}: {exc}")
        return None

    def persist_context_cache(self, session_id: str, cache: Optional[Dict[str, Any]]) -> None:
        if cache is None:
            return
        payload = {
            "session_id": session_id,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "cache": cache,
        }
        self.context_cache_file(session_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def ensure_session_state_loaded(
        self,
        session_id: str,
        chat_sessions: Dict[str, List[Dict[str, Any]]],
        cache_store: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        if session_id not in chat_sessions:
            chat_sessions[session_id] = self.load_chat_session(session_id) or []

        if cache_store is not None and session_id not in cache_store:
            cache_store[session_id] = self.load_context_cache(session_id) or {}

    @staticmethod
    def _message_to_transcript_entry(message: Dict[str, Any], index: int) -> Dict[str, Any]:
        role = str(message.get("role") or "assistant")
        kind = "user" if role == "user" else "assistant"
        return {
            "id": f"persisted_{index}_{kind}",
            "kind": kind,
            "content": str(message.get("content") or ""),
            "timestamp": message.get("timestamp") or "",
            "message_parts": message.get("message_parts") or [],
            "streaming": False,
        }

    @staticmethod
    def _fallback_title_from_messages(messages: List[Dict[str, Any]], session_id: str) -> str:
        for message in messages:
            if str(message.get("role") or "") != "user":
                continue
            content = str(message.get("content") or "").strip()
            if content:
                return content.replace("\n", " ")[:24]
        return session_id

    def _ui_session_from_chat_payload(self, chat_payload: Dict[str, Any]) -> Dict[str, Any]:
        session_id = str(chat_payload.get("session_id") or "")
        messages = chat_payload.get("messages") if isinstance(chat_payload.get("messages"), list) else []
        updated_at = str(chat_payload.get("updated_at") or datetime.now().astimezone().isoformat(timespec="seconds"))
        return {
            "id": session_id,
            "title": self._fallback_title_from_messages(messages, session_id),
            "transcript": [
                self._message_to_transcript_entry(message, index)
                for index, message in enumerate(messages)
                if isinstance(message, dict)
            ],
            "logs": self.load_llm_traces(session_id)[-400:],
            "tasks": {},
            "workspacePath": str(self.paths.thread_workspace_dir / self.sanitize_session_id(session_id)),
            "selectedModel": "",
            "createdAt": updated_at,
            "updatedAt": updated_at,
            "restoredFromChatSession": True,
        }

    def list_ui_sessions(self) -> List[Dict[str, Any]]:
        sessions: List[Dict[str, Any]] = []
        seen_ids = set()
        for file_path in sorted(
            self.paths.ui_sessions_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                payload = json.loads(file_path.read_text(encoding="utf-8"))
                session_id = str(payload.get("id") or file_path.stem)
                seen_ids.add(session_id)
                sessions.append(payload)
            except Exception:
                continue
        for chat_payload in self.list_chat_sessions():
            session_id = str(chat_payload.get("session_id") or "")
            if not session_id or session_id in seen_ids:
                continue
            sessions.append(self._ui_session_from_chat_payload(chat_payload))
        return sessions

    def load_ui_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        session_file = self.ui_session_file(session_id)
        if session_file.exists():
            return json.loads(session_file.read_text(encoding="utf-8"))
        messages = self.load_chat_session(session_id)
        if messages is None:
            return None
        chat_file = self.chat_session_file(session_id)
        updated_at = ""
        try:
            payload = json.loads(chat_file.read_text(encoding="utf-8"))
            updated_at = str(payload.get("updated_at") or "")
        except Exception:
            pass
        return self._ui_session_from_chat_payload(
            {
                "session_id": session_id,
                "updated_at": updated_at,
                "messages": messages,
            }
        )

    def save_ui_session(self, session_id: str, payload: Dict[str, Any]) -> None:
        self.ui_session_file(session_id).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def delete_ui_session(self, session_id: str) -> None:
        session_file = self.ui_session_file(session_id)
        if session_file.exists():
            session_file.unlink()

    def list_published_projects(self) -> List[Dict[str, Any]]:
        projects: List[Dict[str, Any]] = []
        for file_path in sorted(
            self.paths.published_projects_dir.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                projects.append(json.loads(file_path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return projects

    def load_published_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        project_file = self.published_project_file(project_id)
        if not project_file.exists():
            return None
        return json.loads(project_file.read_text(encoding="utf-8"))

    def save_published_project(self, project_id: str, payload: Dict[str, Any]) -> None:
        self.published_project_file(project_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete_published_project(self, project_id: str) -> None:
        project_file = self.published_project_file(project_id)
        if project_file.exists():
            project_file.unlink()

    def persist_workspace_state(self, payload: Dict[str, Any]) -> None:
        self.paths.workspace_state_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_workspace_state(self) -> Optional[Dict[str, Any]]:
        if not self.paths.workspace_state_file.exists():
            return None
        try:
            return json.loads(self.paths.workspace_state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Failed to load workspace state: {exc}")
            return None
