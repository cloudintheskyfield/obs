#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

set -a
[[ -f "$ROOT_DIR/.env" ]] && source "$ROOT_DIR/.env"
set +a

export PYTHONPATH="$ROOT_DIR/src"
export SKILLS_DIR="${SKILLS_DIR:-$ROOT_DIR/.claude/skills}"

python -m omni_agent.main desktop
