#!/usr/bin/env bash
# AI Usage Bar v1.8.2 — macOS 1-Click Installer (Apple Silicon & Intel)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_HOME="$HOME/Library/Application Support/AIUsageBar"
APP_DIR="$APP_HOME/app"
VENV_DIR="$APP_HOME/venv"

echo "============================================"
echo "  AI Usage Bar v1.8.2 — macOS Installer"
echo "============================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[Error] python3 not found. Install via Homebrew: brew install python python-tk"
  exit 1
fi

echo "[1/5] Copying app files to: $APP_DIR"
mkdir -p "$APP_DIR/macos"
for f in hud_app.py settings_dialog.py preview_art.py state_store.py i18n.py win11_ui.py win_tray.py hooks_manager.py background_refresher.py hotkey_manager.py; do
  if [ -f "$SRC_ROOT/$f" ]; then
    cp "$SRC_ROOT/$f" "$APP_DIR/$f"
  fi
done
cp "$SCRIPT_DIR/quota_hook.py" "$APP_DIR/macos/quota_hook.py"
chmod +x "$APP_DIR/macos/quota_hook.py"

echo "[2/5] Preparing virtual environment and Pillow..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --quiet --upgrade pip pillow

echo "[3/5] Connecting official Claude Code / agy statusLine hooks..."
"$VENV_DIR/bin/python" - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$APP_DIR")
from hooks_manager import install_claude_hook, install_agy_hook
for name, fn in (("Claude", install_claude_hook), ("Antigravity", install_agy_hook)):
    ok, msg = fn(Path("$APP_DIR"))
    print(f"  [{name}] {'OK' if ok else 'Note'}: {msg}")
PY

echo "[4/5] Creating Desktop launcher..."
LAUNCHER="$HOME/Desktop/AI Usage Bar.command"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
nohup "$VENV_DIR/bin/python" "$APP_DIR/hud_app.py" >/dev/null 2>&1 &
EOF
chmod +x "$LAUNCHER"

echo "[5/5] Launching AI Usage Bar..."
nohup "$VENV_DIR/bin/python" "$APP_DIR/hud_app.py" >/dev/null 2>&1 &
echo ""
echo "Installation complete! Launch anytime via Desktop 'AI Usage Bar.command'."
echo "(Enable Launch at Login in Settings ⚙ -> Alerts & Key.)"
