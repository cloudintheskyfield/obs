"""Native desktop shell that reuses the web UI.

The desktop app intentionally serves the same FastAPI + frontend bundle used by
the browser version so the packaged desktop experience matches the web
experience on macOS and Windows.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional
import traceback

import requests
import uvicorn

from omni_agent.utils.paths import app_root, claude_skills_root


APP_NAME = "OBS Code"
APP_HOST = os.getenv("OBS_DESKTOP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("OBS_DESKTOP_PORT", "8765"))
APP_URL = f"http://{APP_HOST}:{APP_PORT}"
LOCAL_WEB_URL = os.getenv("OBS_WEB_URL", "http://127.0.0.1:8000")
WINDOW_MIN_SIZE = (1180, 760)
WINDOW_SIZE = (1540, 980)
WINDOW_BG = "#161616"


def _platform_name() -> str:
    return os.name


def _platform_id() -> str:
    return sys.platform


def _desktop_data_dir() -> Path:
    if _platform_id() == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if _platform_name() == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    xdg_config = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / APP_NAME.lower().replace(" ", "-")


APP_DIR = _desktop_data_dir()
DESKTOP_LOG_FILE = APP_DIR / "desktop.log"


def _desktop_log(message: str) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    if not DESKTOP_LOG_FILE.exists():
        DESKTOP_LOG_FILE.write_text("", encoding="utf-8")
    with DESKTOP_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def _resolve_gui_backend() -> str:
    explicit_gui = os.getenv("OBS_DESKTOP_GUI", "").strip().lower()
    if explicit_gui in {"qt", "gtk", "cocoa", "winforms", "edgechromium", "mshtml"}:
        return explicit_gui
    if _platform_id() == "darwin":
        return "cocoa"
    if _platform_name() == "nt":
        return "edgechromium"
    return "qt"


def _healthcheck(url: str, timeout: float = 1.5) -> bool:
    health_url = f"{url.rstrip('/')}/health"
    try:
        response = requests.get(health_url, timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


class BackendServer:
    def __init__(self) -> None:
        self.server: Optional[uvicorn.Server] = None
        self.thread: Optional[threading.Thread] = None

    def ensure_running(self) -> None:
        if self._is_healthy():
            _desktop_log(f"Backend already healthy at {APP_URL}")
            return

        os.environ.setdefault("PYTHONPATH", str(app_root() / "src"))
        os.environ.setdefault("SKILLS_DIR", str(claude_skills_root()))

        from omni_agent.api import app

        config = uvicorn.Config(
            app,
            host=APP_HOST,
            port=APP_PORT,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

        deadline = time.time() + 45
        while time.time() < deadline:
            if self._is_healthy():
                _desktop_log(f"Embedded backend started at {APP_URL}")
                return
            time.sleep(0.35)
        _desktop_log(f"Embedded backend failed to become healthy at {APP_URL}")
        raise RuntimeError(f"Desktop backend failed to start on {APP_URL}")

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

    def _is_healthy(self) -> bool:
        return _healthcheck(APP_URL)


class OBSDesktopShell:
    def __init__(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.backend = BackendServer()
        self.target_url = self._resolve_target_url()
        self.gui_backend = _resolve_gui_backend()

    def run(self) -> None:
        _desktop_log(f"Launching desktop shell target={self.target_url} gui={self.gui_backend} frozen={getattr(sys, 'frozen', False)}")
        if self.target_url == APP_URL:
            self.backend.ensure_running()
        webview = self._load_webview()
        if webview is None:
            _desktop_log(f"pywebview unavailable, opening browser at {self.target_url}")
            webbrowser.open(self.target_url)
            return

        window = webview.create_window(
            APP_NAME,
            self.target_url,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=WINDOW_MIN_SIZE,
            background_color=WINDOW_BG,
            text_select=True,
            confirm_close=False,
        )
        window.events.closed += self._on_window_closed
        start_kwargs = {
            "gui": self.gui_backend,
            "debug": False,
            "http_server": False,
            "private_mode": False,
            "storage_path": str(APP_DIR),
        }
        try:
            webview.start(**start_kwargs)
            _desktop_log(f"pywebview exited normally using gui={start_kwargs['gui']}")
        except Exception as exc:
            _desktop_log(f"pywebview.start failed with gui={start_kwargs['gui']}: {exc}\n{traceback.format_exc()}")
            if _platform_name() == "nt":
                fallback_gui = "winforms" if self.gui_backend != "winforms" else "qt"
            else:
                fallback_gui = "qt" if self.gui_backend != "qt" else None
            if fallback_gui is None:
                _desktop_log(f"No GUI fallback available, opening browser at {self.target_url}")
                webbrowser.open(self.target_url)
                return
            start_kwargs["gui"] = fallback_gui
            try:
                webview.start(**start_kwargs)
                _desktop_log(f"pywebview exited normally using fallback gui={start_kwargs['gui']}")
            except Exception as fallback_exc:
                _desktop_log(f"pywebview fallback start failed with gui={start_kwargs['gui']}: {fallback_exc}\n{traceback.format_exc()}")
                _desktop_log(f"Opening browser fallback at {self.target_url}")
                webbrowser.open(self.target_url)

    def _load_webview(self):
        try:
            import webview  # type: ignore

            _desktop_log("Imported pywebview successfully")
            return webview
        except Exception as exc:
            _desktop_log(f"Failed to import pywebview: {exc}\n{traceback.format_exc()}")
            return None

    def _resolve_target_url(self) -> str:
        explicit_target = os.getenv("OBS_DESKTOP_TARGET_URL", "").strip()
        if explicit_target:
            _desktop_log(f"Using explicit desktop target URL: {explicit_target}")
            return explicit_target

        mirror_web = os.getenv("OBS_DESKTOP_MIRROR_WEB", "1").strip().lower()
        if mirror_web not in {"0", "false", "no"} and _healthcheck(LOCAL_WEB_URL):
            _desktop_log(f"Mirroring running web app at {LOCAL_WEB_URL}")
            return LOCAL_WEB_URL

        _desktop_log(f"Falling back to embedded desktop backend at {APP_URL}")
        return APP_URL

    def _on_window_closed(self, *_args, **_kwargs) -> None:
        self.backend.stop()


def run_desktop_app() -> None:
    OBSDesktopShell().run()


if __name__ == "__main__":
    run_desktop_app()
