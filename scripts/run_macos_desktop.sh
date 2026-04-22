#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

set -a
[[ -f "$ROOT_DIR/.env" ]] && source "$ROOT_DIR/.env"
set +a

export PYTHONPATH="$ROOT_DIR/src"
export SKILLS_DIR="${SKILLS_DIR:-$ROOT_DIR/.claude/skills}"
export OBS_DESKTOP_MIRROR_WEB="${OBS_DESKTOP_MIRROR_WEB:-1}"
export OBS_DESKTOP_GUI="${OBS_DESKTOP_GUI:-cocoa}"

if [[ -z "${OBS_DESKTOP_TARGET_URL:-}" && -n "${OBS_WEB_URL:-}" ]]; then
  export OBS_DESKTOP_TARGET_URL="$OBS_WEB_URL"
fi

if [[ -z "${OBS_DESKTOP_TARGET_URL:-}" ]]; then
  if python - <<'PY' >/dev/null 2>&1
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1.5) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
  then
    export OBS_DESKTOP_TARGET_URL="http://127.0.0.1:8000"
  fi
fi

if [[ -z "${OBS_DESKTOP_TARGET_URL:-}" ]]; then
  if [[ ! -d "$ROOT_DIR/ui/node_modules" ]]; then
    npm --prefix "$ROOT_DIR/ui" install
  fi
  npm --prefix "$ROOT_DIR/ui" run build
fi

python -m omni_agent.main desktop
