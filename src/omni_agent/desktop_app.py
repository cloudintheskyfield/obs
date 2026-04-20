"""Native macOS desktop shell that reuses the web UI.

The desktop app intentionally serves the same FastAPI + frontend bundle used by
the browser version so the DMG experience matches the web experience.
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests
import uvicorn

from omni_agent.utils.paths import app_root, claude_skills_root


APP_NAME = "OBS Code"
APP_HOST = os.getenv("OBS_DESKTOP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("OBS_DESKTOP_PORT", "8765"))
APP_URL = f"http://{APP_HOST}:{APP_PORT}"
APP_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
WINDOW_MIN_SIZE = (1180, 760)
WINDOW_SIZE = (1540, 980)
WINDOW_BG = "#161616"


class BackendServer:
    def __init__(self) -> None:
        self.server: Optional[uvicorn.Server] = None
        self.thread: Optional[threading.Thread] = None

    def ensure_running(self) -> None:
        if self._is_healthy():
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
                return
            time.sleep(0.35)
        raise RuntimeError(f"Desktop backend failed to start on {APP_URL}")

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

    def _is_healthy(self) -> bool:
        try:
            response = requests.get(f"{APP_URL}/health", timeout=1.5)
            return response.ok
        except requests.RequestException:
            return False


class OBSDesktopShell:
    def __init__(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.backend = BackendServer()

    def run(self) -> None:
        self.backend.ensure_running()
        webview = self._load_webview()
        if webview is None:
            webbrowser.open(APP_URL)
            return

        window = webview.create_window(
            APP_NAME,
            APP_URL,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=WINDOW_MIN_SIZE,
            background_color=WINDOW_BG,
            text_select=True,
            confirm_close=False,
        )
        window.events.closed += self._on_window_closed
        webview.start(
            gui="cocoa",
            debug=False,
            http_server=False,
            private_mode=False,
            storage_path=str(APP_DIR),
        )

    def _load_webview(self):
        try:
            import webview  # type: ignore

            return webview
        except Exception:
            return None

    def _on_window_closed(self, *_args, **_kwargs) -> None:
        self.backend.stop()


def run_desktop_app() -> None:
    OBSDesktopShell().run()
