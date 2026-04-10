#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="OBS Code"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
DMG_DIR="$ROOT_DIR/dist-dmg"
VERSION_TAG="$(date +%Y%m%d-%H%M%S)"

cd "$ROOT_DIR"

set -a
[[ -f "$ROOT_DIR/.env" ]] && source "$ROOT_DIR/.env"
set +a

export PYTHONPATH="$ROOT_DIR/src"
export SKILLS_DIR="${SKILLS_DIR:-$ROOT_DIR/.claude/skills}"

ENV_DATA_ARGS=()
if [[ -f "$ROOT_DIR/.env" ]]; then
  ENV_DATA_ARGS+=(--add-data "$ROOT_DIR/.env:.")
fi

rm -rf "$BUILD_DIR" "$DIST_DIR" "$DMG_DIR"
mkdir -p "$DMG_DIR"

python -m PyInstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --paths "$ROOT_DIR/src" \
  --paths "$ROOT_DIR/.claude/skills" \
  --hidden-import omni_agent.api \
  --hidden-import skill_manager \
  --hidden-import skill_loader \
  --hidden-import base_skill \
  --exclude-module matplotlib \
  --exclude-module IPython \
  --exclude-module jupyter_client \
  --exclude-module jupyter_core \
  --exclude-module ipykernel \
  --exclude-module pandas \
  --exclude-module scipy \
  "${ENV_DATA_ARGS[@]}" \
  --add-data "$ROOT_DIR/.claude/skills:.claude/skills" \
  --add-data "$ROOT_DIR/frontend:frontend" \
  --add-data "$ROOT_DIR/skills:skills" \
  "$ROOT_DIR/src/omni_agent/desktop_app.py"

APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "App bundle was not created"
  exit 1
fi

STAGE_DIR="$DMG_DIR/$APP_NAME"
mkdir -p "$STAGE_DIR"
cp -R "$APP_BUNDLE" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"

DMG_PATH="$ROOT_DIR/dist/${APP_NAME// /-}-$VERSION_TAG.dmg"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH" >/dev/null

echo "APP_BUNDLE=$APP_BUNDLE"
echo "DMG_PATH=$DMG_PATH"
