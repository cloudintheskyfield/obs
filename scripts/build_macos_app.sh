#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="OBS Code"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
DMG_DIR="$ROOT_DIR/dist-dmg"
VERSION_TAG="$(date +%Y%m%d-%H%M%S)"
ICONSET_DIR="$BUILD_DIR/icon.iconset"
ICON_PNG_DIR="$BUILD_DIR/icon-preview"
ICON_PNG="$ICON_PNG_DIR/obs-code-app-icon.png"
ICON_ICNS="$BUILD_DIR/obs-code-logo.icns"

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

if ! python - <<'PY' >/dev/null 2>&1
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("webview") else 1)
PY
then
  echo "Missing desktop dependency: pywebview. Install it with 'python -m pip install pywebview==6.2.1' first."
  exit 1
fi

rm -rf "$BUILD_DIR" "$DIST_DIR" "$DMG_DIR"
mkdir -p "$DMG_DIR"

if [[ ! -d "$ROOT_DIR/ui/node_modules" ]]; then
  npm --prefix "$ROOT_DIR/ui" install
fi
npm --prefix "$ROOT_DIR/ui" run build

mkdir -p "$ICON_PNG_DIR"
python "$ROOT_DIR/scripts/generate_desktop_icons.py" --png "$ICON_PNG"

rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"
sips -z 16 16 "$ICON_PNG" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32 "$ICON_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ICON_PNG" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64 "$ICON_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ICON_PNG" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256 "$ICON_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ICON_PNG" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512 "$ICON_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ICON_PNG" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
cp "$ICON_PNG" "$ICONSET_DIR/icon_512x512@2x.png"
iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"

python -m PyInstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --icon "$ICON_ICNS" \
  --paths "$ROOT_DIR/src" \
  --paths "$ROOT_DIR/.claude/skills" \
  --hidden-import omni_agent.api \
  --hidden-import skill_manager \
  --hidden-import skill_loader \
  --hidden-import base_skill \
  --hidden-import webview \
  --hidden-import objc \
  --hidden-import AppKit \
  --hidden-import Foundation \
  --hidden-import WebKit \
  --hidden-import PyObjCTools \
  --hidden-import PyObjCTools.AppHelper \
  --hidden-import webview.platforms.cocoa \
  --collect-all webview \
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
