#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
UI_ROOT = REPO_ROOT / "ui"
RUN_DIR = REPO_ROOT / ".run"
FRONTEND_LOG = RUN_DIR / "pycharm-frontend.log"
FRONTEND_PID = RUN_DIR / "pycharm-frontend.pid"


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port(host: str, port: int, timeout_sec: float) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def _run_npm_install_if_needed() -> None:
    if (UI_ROOT / "node_modules").exists():
        return
    print("[pycharm] ui/node_modules not found; running npm install once...")
    subprocess.run(["npm", "install"], cwd=UI_ROOT, check=True)


def _start_frontend(host: str, port: int, install: bool) -> Optional[subprocess.Popen]:
    if _port_open("127.0.0.1", port):
        print(f"[pycharm] frontend already running on http://localhost:{port}/static/")
        return None

    if install:
        _run_npm_install_if_needed()

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log_file = FRONTEND_LOG.open("ab", buffering=0)
    env = os.environ.copy()
    env.setdefault("BROWSER", "none")
    command = ["npm", "run", "dev", "--", "--host", host, "--port", str(port)]
    process = subprocess.Popen(
        command,
        cwd=UI_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    FRONTEND_PID.write_text(str(process.pid), encoding="utf-8")
    print(f"[pycharm] frontend PID {process.pid}; log: {FRONTEND_LOG}")
    if _wait_for_port("127.0.0.1", port, timeout_sec=20):
        print(f"[pycharm] frontend ready: http://localhost:{port}/static/")
    else:
        print(f"[pycharm] frontend not ready yet; check {FRONTEND_LOG}")
    return process


def _stop_frontend(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
    try:
        FRONTEND_PID.unlink(missing_ok=True)
    except OSError:
        pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "PyCharm-friendly dev launcher: start the Vite frontend, then run "
            "the FastAPI backend in this Python process so breakpoints work."
        )
    )
    parser.add_argument("--backend-host", default=os.getenv("OBS_BACKEND_HOST", "0.0.0.0"))
    parser.add_argument("--backend-port", type=int, default=int(os.getenv("OBS_BACKEND_PORT", "8213")))
    parser.add_argument("--frontend-host", default=os.getenv("OBS_FRONTEND_HOST", "0.0.0.0"))
    parser.add_argument("--frontend-port", type=int, default=int(os.getenv("OBS_FRONTEND_PORT", "5173")))
    parser.add_argument(
        "--no-frontend",
        action="store_true",
        help="Only run the backend; useful when the Vite server is managed elsewhere.",
    )
    parser.add_argument(
        "--no-npm-install",
        action="store_true",
        help="Do not run npm install automatically when ui/node_modules is missing.",
    )
    parser.add_argument("--log-level", default=os.getenv("OBS_UVICORN_LOG_LEVEL", "info"))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    os.chdir(REPO_ROOT)
    os.environ.setdefault("OBS_PUBLIC_HOST", "localhost")
    os.environ.setdefault("OBS_PUBLIC_PORT", str(args.backend_port))

    if _port_open("127.0.0.1", args.backend_port):
        raise SystemExit(
            f"Backend port {args.backend_port} is already in use. "
            "Run ./run.sh stop or stop the existing PyCharm process first."
        )

    frontend_process = None
    if not args.no_frontend:
        frontend_process = _start_frontend(
            host=args.frontend_host,
            port=args.frontend_port,
            install=not args.no_npm_install,
        )
        atexit.register(_stop_frontend, frontend_process)

    import uvicorn
    from api import app

    print(f"[pycharm] backend ready to debug on http://localhost:{args.backend_port}")
    print("[pycharm] uvicorn reload is disabled so PyCharm breakpoints stay attached.")
    uvicorn.run(
        app,
        host=args.backend_host,
        port=args.backend_port,
        reload=False,
        log_level=args.log_level,
        access_log=True,
    )


if __name__ == "__main__":
    main()
