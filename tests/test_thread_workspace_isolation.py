from pathlib import Path
import asyncio
import json
from urllib.parse import quote

from omni_agent import api
from omni_agent.services.session_store import SessionStore, SessionStorePaths


def _store(tmp_path: Path) -> SessionStore:
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


def test_request_without_workspace_uses_thread_private_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api, "session_store", _store(tmp_path))

    first = api._resolve_request_workspace("thread-a", "")
    second = api._resolve_request_workspace("thread-b", None)

    assert first["runtime_path"] != second["runtime_path"]
    assert first["runtime_path"].endswith("thread_workspaces/thread-a")
    assert second["runtime_path"].endswith("thread_workspaces/thread-b")
    assert Path(first["runtime_path"]).is_dir()
    assert Path(second["runtime_path"]).is_dir()


def test_explicit_workspace_overrides_thread_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api, "session_store", _store(tmp_path))
    explicit = tmp_path / "custom-workspace"

    resolved = api._resolve_request_workspace("thread-a", str(explicit))

    assert resolved["runtime_path"] == str(explicit.resolve())
    assert explicit.is_dir()


def test_non_git_workspace_changes_reports_html_preview_files(tmp_path) -> None:
    workspace = tmp_path / "thread-workspace"
    workspace.mkdir()
    html_file = workspace / "index.html"
    html_file.write_text("<!doctype html><title>Preview</title>", encoding="utf-8")

    response = asyncio.run(api.workspace_changes(str(workspace)))
    payload = json.loads(response.body)

    assert payload["success"] is True
    assert payload["is_git"] is False
    assert payload["files"] == []
    assert payload["preview_files"][0]["path"] == "index.html"
    assert payload["preview_files"][0]["absolute_path"] == str(html_file.resolve())


def test_local_preview_rewrites_relative_html_assets(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api, "_current_workspace_runtime", lambda: str(tmp_path))
    html_file = tmp_path / "index.html"
    css_file = tmp_path / "style.css"
    js_file = tmp_path / "game.js"
    html_file.write_text(
        '<!doctype html><link rel="stylesheet" href="style.css">'
        '<script src="./game.js"></script>',
        encoding="utf-8",
    )
    css_file.write_text("body{color:white}", encoding="utf-8")
    js_file.write_text("window.started=false", encoding="utf-8")

    response = asyncio.run(api.serve_local_preview_file(str(html_file)))
    body = response.body.decode("utf-8")

    assert f"/preview/local-file?path={quote(str(css_file.resolve()), safe='')}" in body
    assert f"/preview/local-file?path={quote(str(js_file.resolve()), safe='')}" in body


def test_local_preview_rewrites_relative_css_urls(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api, "_current_workspace_runtime", lambda: str(tmp_path))
    css_file = tmp_path / "style.css"
    image_file = tmp_path / "roof.png"
    css_file.write_text(".hero{background:url('./roof.png')}", encoding="utf-8")
    image_file.write_bytes(b"png")

    response = asyncio.run(api.serve_local_preview_file(str(css_file)))
    body = response.body.decode("utf-8")

    assert f"url('/preview/local-file?path={quote(str(image_file.resolve()), safe='')}')" in body
