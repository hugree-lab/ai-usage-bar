#!/usr/bin/env bash
# AI Usage Bar v1.8.4 — macOS 1-Click Installer (Apple Silicon & Intel)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_HOME="$HOME/Library/Application Support/AIUsageBar"
APP_DIR="$APP_HOME/app"
VENV_DIR="$APP_HOME/venv"
LAUNCH_LOG="$APP_HOME/hud_launch.log"

if [ -w "/Applications" ]; then
  APP_BUNDLE="/Applications/AIUsageBar.app"
else
  mkdir -p "$HOME/Applications"
  APP_BUNDLE="$HOME/Applications/AIUsageBar.app"
fi

echo "============================================"
echo "  AI Usage Bar v1.8.4 — macOS Installer"
echo "============================================"

# Prefer a modern Python 3 with Tk >= 8.6 (Homebrew, python.org, or uv) before system Python 3.9 (Tk 8.5)
select_python() {
  local candidates=(
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.12"
    "/usr/local/bin/python3.11"
    "/usr/local/bin/python3"
  )
  for p in "$HOME/.local/share/uv/python"/cpython-3.*/bin/python3*; do
    [ -x "$p" ] && candidates+=("$p")
  done
  for p in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3; do
    [ -x "$p" ] && candidates+=("$p")
  done
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi

  local fallback=""
  for py in "${candidates[@]}"; do
    [ -x "$py" ] || continue
    local tk_ver
    tk_ver=$("$py" -c "import tkinter; print(tkinter.TkVersion)" 2>/dev/null || true)
    [ -n "$tk_ver" ] || continue
    if "$py" -c "import tkinter; raise SystemExit(0 if tkinter.TkVersion >= 8.6 else 1)" 2>/dev/null; then
      echo "$py"
      return 0
    fi
    if [ -z "$fallback" ]; then
      fallback="$py"
    fi
  done

  if [ -n "$fallback" ]; then
    echo "$fallback"
    return 0
  fi
  return 1
}

PY_BIN="$(select_python || true)"
if [ -z "$PY_BIN" ]; then
  echo "[Error] Python 3 with Tkinter not found. Install via Homebrew: brew install python python-tk"
  exit 1
fi
PY_INFO=$("$PY_BIN" -c "import sys, tkinter; print(f'Python {sys.version.split()[0]} / Tk {tkinter.TkVersion}')")
echo "Using: $PY_BIN ($PY_INFO)"

# Stop any previously running AI Usage Bar instance so upgrades start cleanly
pkill -f "$APP_DIR/hud_app.py" >/dev/null 2>&1 || true
pkill -f "AIUsageBar.app/Contents/MacOS/AIUsageBar" >/dev/null 2>&1 || true
sleep 0.4

echo "[1/5] Copying app files to: $APP_DIR"
mkdir -p "$APP_DIR/macos"
for f in hud_app.py settings_dialog.py preview_art.py state_store.py i18n.py win11_ui.py win_tray.py hooks_manager.py background_refresher.py hotkey_manager.py setup_hooks.py; do
  if [ -f "$SRC_ROOT/$f" ]; then
    cp "$SRC_ROOT/$f" "$APP_DIR/$f"
  fi
done
cp "$SCRIPT_DIR/quota_hook.py" "$APP_DIR/macos/quota_hook.py"
chmod +x "$APP_DIR/macos/quota_hook.py"

echo "[2/5] Preparing virtual environment and Pillow..."
NEED_VENV=0
if [ ! -x "$VENV_DIR/bin/python" ]; then
  NEED_VENV=1
else
  VENV_TK_OK=$("$VENV_DIR/bin/python" -c "import tkinter; print(1 if tkinter.TkVersion >= 8.6 else 0)" 2>/dev/null || echo 0)
  SEL_TK_OK=$("$PY_BIN" -c "import tkinter; print(1 if tkinter.TkVersion >= 8.6 else 0)" 2>/dev/null || echo 0)
  if [ "$VENV_TK_OK" = "0" ] && [ "$SEL_TK_OK" = "1" ]; then
    echo "  Upgrading virtual environment from Tk 8.5 to $PY_INFO..."
    rm -rf "$VENV_DIR"
    NEED_VENV=1
  fi
fi

if [ "$NEED_VENV" = "1" ]; then
  "$PY_BIN" -m venv "$VENV_DIR"
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

echo "[4/5] Installing native macOS app bundle: $APP_BUNDLE"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"

"$VENV_DIR/bin/python" - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$SCRIPT_DIR")
from build_macos import generate_macos_icns
generate_macos_icns(Path("$APP_BUNDLE/Contents/Resources/AppIcon.icns"))
PY

cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>AI Usage Bar</string>
    <key>CFBundleDisplayName</key><string>AI Usage Bar</string>
    <key>CFBundleIdentifier</key><string>com.hugreelab.aiusagebar</string>
    <key>CFBundleVersion</key><string>1.8.4</string>
    <key>CFBundleShortVersionString</key><string>1.8.4</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>AIUsageBar</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

cat > "$APP_BUNDLE/Contents/MacOS/AIUsageBar" <<EOF
#!/usr/bin/env bash
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec "$VENV_DIR/bin/python" "$APP_DIR/hud_app.py" >"$LAUNCH_LOG" 2>&1
EOF
chmod +x "$APP_BUNDLE/Contents/MacOS/AIUsageBar"
xattr -cr "$APP_BUNDLE" >/dev/null 2>&1 || true

# Clean up legacy Desktop .command launcher if present
rm -f "$HOME/Desktop/AI Usage Bar.command" >/dev/null 2>&1 || true

echo "[5/5] Launching AI Usage Bar via LaunchServices..."
open -a "$APP_BUNDLE"
sleep 1.2
if pgrep -f "$APP_DIR/hud_app.py" >/dev/null 2>&1; then
  HUD_PID=$(pgrep -f "$APP_DIR/hud_app.py" | head -n 1)
  echo ""
  echo "Installation complete! AI Usage Bar is running (PID $HUD_PID)."
  echo "Installed app: $APP_BUNDLE (open anytime from Applications or Spotlight)."
  echo "(Enable Launch at Login in Settings ⚙ -> Alerts & Key.)"
else
  echo ""
  echo "[Warning] AI Usage Bar did not stay running. Log output ($LAUNCH_LOG):"
  cat "$LAUNCH_LOG" 2>/dev/null || true
  exit 1
fi
