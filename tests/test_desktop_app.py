from __future__ import annotations

from omni_agent import desktop_app


def test_desktop_shell_falls_back_to_browser_when_webview_missing(monkeypatch) -> None:
    shell = desktop_app.OBSDesktopShell()
    opened = []

    monkeypatch.setattr(shell.backend, "ensure_running", lambda: None)
    monkeypatch.setattr(shell, "_load_webview", lambda: None)
    monkeypatch.setattr(desktop_app.webbrowser, "open", lambda url: opened.append(url))

    shell.run()

    assert opened == [desktop_app.APP_URL]


def test_desktop_shell_uses_webview_with_local_runtime_url(monkeypatch) -> None:
    shell = desktop_app.OBSDesktopShell()
    events = type("Events", (), {"closed": type("ClosedEvent", (), {"__iadd__": lambda self, callback: self})()})()
    created = {}
    started = {}

    class FakeWebview:
        def create_window(self, title, url, **kwargs):
            created.update({"title": title, "url": url, **kwargs})
            return type("Window", (), {"events": events})()

        def start(self, **kwargs):
            started.update(kwargs)

    monkeypatch.setattr(shell.backend, "ensure_running", lambda: None)
    monkeypatch.setattr(shell, "_load_webview", lambda: FakeWebview())

    shell.run()

    assert created["title"] == desktop_app.APP_NAME
    assert created["url"] == desktop_app.APP_URL
    assert created["min_size"] == desktop_app.WINDOW_MIN_SIZE
    assert started["gui"] == "cocoa"
    assert started["http_server"] is False
    assert started["storage_path"] == str(desktop_app.APP_DIR)

