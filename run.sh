#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_DIR="$SCRIPT_DIR/.run"
BACKEND_PID="$PID_DIR/backend.pid"
FRONTEND_PID="$PID_DIR/frontend.pid"
BACKEND_LOG="$PID_DIR/backend.log"
FRONTEND_LOG="$PID_DIR/frontend.log"

start_detached() {
    local cwd="$1"
    local log_file="$2"
    local pid_file="$3"
    shift 3

    START_CWD="$cwd" START_LOG="$log_file" START_PID_FILE="$pid_file" python3 - "$@" <<'PY'
import os
import subprocess
import sys

cwd = os.environ["START_CWD"]
log_file = os.environ["START_LOG"]
pid_file = os.environ["START_PID_FILE"]

log = open(log_file, "ab", buffering=0)
process = subprocess.Popen(
    sys.argv[1:],
    cwd=cwd,
    stdin=subprocess.DEVNULL,
    stdout=log,
    stderr=subprocess.STDOUT,
    start_new_session=True,
)

with open(pid_file, "w", encoding="utf-8") as handle:
    handle.write(str(process.pid))
PY
}

start() {
    mkdir -p "$PID_DIR"

    echo "Starting backend..."
    start_detached "$SCRIPT_DIR" "$BACKEND_LOG" "$BACKEND_PID" env PYTHONPATH="$SCRIPT_DIR/src" uv run uvicorn api:app --host 0.0.0.0 --port 8213
    echo "  Backend PID: $(cat "$BACKEND_PID")  (log: $BACKEND_LOG)"

    echo "Starting frontend..."
    start_detached "$SCRIPT_DIR/ui" "$FRONTEND_LOG" "$FRONTEND_PID" npm run dev -- --host 0.0.0.0
    echo "  Frontend PID: $(cat "$FRONTEND_PID")  (log: $FRONTEND_LOG)"

    echo ""
    echo "Waiting for services..."
    sleep 5

    if curl -sf http://localhost:8213/health > /dev/null 2>&1; then
        echo "  Backend:  http://localhost:8213  ✓"
    else
        echo "  Backend:  http://localhost:8213  ✗ (check $BACKEND_LOG)"
    fi

    if curl -sf http://localhost:5173/static/ > /dev/null 2>&1; then
        echo "  Frontend: http://localhost:5173/static/  ✓"
    else
        echo "  Frontend: http://localhost:5173/static/  ✗ (check $FRONTEND_LOG)"
    fi
}

stop() {
    kill_stale_port() {
        local name="$1"
        local port="$2"
        local pids
        pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
        if [ -z "$pids" ]; then
            return 0
        fi

        kill $pids 2>/dev/null || true
        sleep 1

        local remaining
        remaining=$(lsof -ti tcp:"$port" 2>/dev/null || true)
        if [ -n "$remaining" ]; then
            kill -9 $remaining 2>/dev/null || true
        fi

        echo "  Killed stale $name on :$port (PID $(echo "$pids" | tr '\n' ' ' | sed 's/ *$//'))"
    }

    kill_group() {
        local name="$1"
        local pidfile="$2"
        if [ -f "$pidfile" ]; then
            local pid
            pid=$(cat "$pidfile")
            # kill the entire process group (negative PID)
            if kill -0 "$pid" 2>/dev/null; then
                kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null
                echo "  $name (PGID $pid) stopped"
            else
                echo "  $name (PID $pid) was not running"
            fi
            rm -f "$pidfile"
        else
            echo "  $name: no pid file found"
        fi
    }

    kill_group "Backend"  "$BACKEND_PID"
    kill_group "Frontend" "$FRONTEND_PID"

    # fallback: kill by port in case pid files are stale or only child
    # processes survived the process-group stop.
    kill_stale_port "backend" 8213
    kill_stale_port "frontend" 5173

    return 0
}

case "${1:-}" in
    start) start ;;
    stop)  stop  ;;
    restart) stop; sleep 2; start ;;
    *)
        echo "Usage: $0 {start|stop|restart}"
        exit 1
        ;;
esac
