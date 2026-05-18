from __future__ import annotations

import json
from pathlib import Path

from services.session_store import SessionStore, SessionStorePaths


def build_store(tmp_path: Path) -> SessionStore:
    return SessionStore(
        SessionStorePaths(
            llm_trace_dir=tmp_path / "llm_traces",
            session_store_dir=tmp_path / "chat_sessions",
            context_cache_dir=tmp_path / "context_cache",
            thread_workspace_dir=tmp_path / "thread_workspaces",
            workspace_state_file=tmp_path / "workspace_state.json",
            ui_sessions_dir=tmp_path / "ui_sessions",
            published_projects_dir=tmp_path / "published_projects",
        )
    )


def test_session_store_persists_core_artifacts(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    session_id = "team/demo:thread"

    store.persist_llm_trace(session_id, {
        "phase": "tool_planning",
        "direction": "request",
        "payload": {"messages": 1},
    })
    traces = store.load_llm_traces(session_id)
    assert len(traces) == 1
    assert traces[0]["phase"] == "tool_planning"

    messages = [{"role": "user", "content": "hello"}]
    store.persist_chat_session(session_id, messages)
    assert store.load_chat_session(session_id) == messages

    cache = {"historical_summary": "A", "recent_summary": "B"}
    store.persist_context_cache(session_id, cache)
    assert store.load_context_cache(session_id) == cache


def test_session_store_handles_ui_and_workspace_state(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    session_id = "ui-session"
    ui_payload = {"id": session_id, "title": "Thread"}

    store.save_ui_session(session_id, ui_payload)
    assert store.load_ui_session(session_id) == ui_payload
    assert store.list_ui_sessions()[0]["id"] == session_id

    workspace_payload = {"path": "/tmp/demo", "runtime_path": "/runtime/demo"}
    store.persist_workspace_state(workspace_payload)
    assert store.load_workspace_state() == workspace_payload

    runtime_dir = Path(store.thread_runtime_dir("thread-1"))
    assert runtime_dir.exists()
    assert runtime_dir.is_dir()

    store.delete_ui_session(session_id)
    assert store.load_ui_session(session_id) is None


def test_session_store_lists_chat_sessions_when_ui_snapshot_is_missing(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    session_id = "session-from-chat"
    messages = [
        {"role": "user", "content": "生成一个小游戏"},
        {"role": "assistant", "content": "已经完成。"},
    ]

    store.persist_chat_session(session_id, messages)
    sessions = store.list_ui_sessions()
    restored = next(item for item in sessions if item["id"] == session_id)

    assert restored["restoredFromChatSession"] is True
    assert restored["title"] == "生成一个小游戏"
    assert [entry["kind"] for entry in restored["transcript"]] == ["user", "assistant"]
    assert store.load_ui_session(session_id)["transcript"][0]["content"] == "生成一个小游戏"


def test_session_store_prefers_saved_ui_snapshot_over_chat_fallback(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    session_id = "session-with-ui"

    store.persist_chat_session(session_id, [{"role": "user", "content": "old"}])
    store.save_ui_session(session_id, {"id": session_id, "title": "Saved UI", "transcript": []})

    sessions = [item for item in store.list_ui_sessions() if item["id"] == session_id]
    assert len(sessions) == 1
    assert sessions[0]["title"] == "Saved UI"
    assert store.load_ui_session(session_id)["title"] == "Saved UI"


def test_session_store_handles_published_projects(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    payload = {"id": "project-demo", "title": "Zombie Rush", "published_at": "2026-05-07T18:00:00+08:00"}

    store.save_published_project(payload["id"], payload)
    assert store.load_published_project(payload["id"]) == payload
    assert store.list_published_projects()[0]["id"] == payload["id"]

    store.delete_published_project(payload["id"])
    assert store.load_published_project(payload["id"]) is None
