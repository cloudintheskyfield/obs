from __future__ import annotations

from omni_agent import desktop_app


def test_desktop_data_dir_uses_platform_specific_defaults(monkeypatch) -> None:
    monkeypatch.setattr(desktop_app, "_platform_id", lambda: "win32")
    monkeypatch.setattr(desktop_app, "_platform_name", lambda: "nt")
    monkeypatch.setenv("APPDATA", r"C:\Users\tester\AppData\Roaming")

    data_dir = desktop_app._desktop_data_dir()

    assert str(data_dir).replace("\\", "/").endswith("AppData/Roaming/OBS Code")


def test_desktop_shell_falls_back_to_browser_when_webview_missing(monkeypatch) -> None:
    shell = desktop_app.OBSDesktopShell()
    opened = []

    monkeypatch.setattr(shell.backend, "ensure_running", lambda: None)
    monkeypatch.setattr(shell, "_load_webview", lambda: None)
    monkeypatch.setattr(desktop_app.webbrowser, "open", lambda url: opened.append(url))

    shell.run()

    assert opened == [desktop_app.APP_URL]


def test_desktop_shell_uses_webview_with_local_runtime_url(monkeypatch) -> None:
    monkeypatch.delenv("OBS_DESKTOP_GUI", raising=False)
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
    assert started["gui"] == shell.gui_backend
    assert started["http_server"] is False
    assert started["storage_path"] == str(desktop_app.APP_DIR)


def test_desktop_shell_prefers_explicit_target_url(monkeypatch) -> None:
    monkeypatch.setenv("OBS_DESKTOP_TARGET_URL", "http://10.25.35.73:8000")
    shell = desktop_app.OBSDesktopShell()

    assert shell.target_url == "http://10.25.35.73:8000"


def test_desktop_shell_mirrors_running_local_web_app(monkeypatch) -> None:
    monkeypatch.delenv("OBS_DESKTOP_TARGET_URL", raising=False)
    monkeypatch.setenv("OBS_DESKTOP_MIRROR_WEB", "1")
    monkeypatch.setattr(desktop_app, "_healthcheck", lambda url, timeout=1.5: url == desktop_app.LOCAL_WEB_URL)
    shell = desktop_app.OBSDesktopShell()
    ensured = []

    events = type("Events", (), {"closed": type("ClosedEvent", (), {"__iadd__": lambda self, callback: self})()})()
    created = {}

    class FakeWebview:
        def create_window(self, title, url, **kwargs):
            created.update({"title": title, "url": url, **kwargs})
            return type("Window", (), {"events": events})()

        def start(self, **kwargs):
            return None

    monkeypatch.setattr(shell.backend, "ensure_running", lambda: ensured.append(True))
    monkeypatch.setattr(shell, "_load_webview", lambda: FakeWebview())

    shell.run()

    assert shell.target_url == desktop_app.LOCAL_WEB_URL
    assert ensured == []
    assert created["url"] == desktop_app.LOCAL_WEB_URL


def test_desktop_shell_prefers_explicit_gui_backend(monkeypatch) -> None:
    monkeypatch.setenv("OBS_DESKTOP_GUI", "qt")
    shell = desktop_app.OBSDesktopShell()

    assert shell.gui_backend == "qt"


def test_desktop_shell_defaults_to_windows_gui_backend(monkeypatch) -> None:
    monkeypatch.delenv("OBS_DESKTOP_GUI", raising=False)
    monkeypatch.setattr(desktop_app, "_platform_id", lambda: "win32")
    monkeypatch.setattr(desktop_app, "_platform_name", lambda: "nt")

    shell = desktop_app.OBSDesktopShell()

    assert shell.gui_backend == "edgechromium"
