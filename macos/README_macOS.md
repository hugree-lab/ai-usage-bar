# AI Usage Bar — macOS Guide (`v1.8.1`)

## Quick Install (Run Directly on macOS)

1. Double-click `macos/install_macos.command` or run it in Terminal:
   ```bash
   chmod +x macos/install_macos.command
   ./macos/install_macos.command
   ```
2. This creates a dedicated virtual environment (`~/Library/Application Support/AIUsageBar/venv`), installs `Pillow`, backs up existing CLI configs, and connects the official `Claude Code` / `agy` `statusLine` hooks (`macos/quota_hook.py`).
3. A Desktop launcher (`AI Usage Bar.command`) is created and the HUD starts automatically.

> **Note:** If Tkinter is missing on your Mac Python installation, run `brew install python-tk` first.

## Build Standalone `.app` & `.dmg` on macOS

```bash
pip install pyinstaller pillow
python3 macos/build_macos.py
```

Output: `dist/AIUsageBar.app` and `dist/AIUsageBar-macOS.dmg`.

## macOS Implementation Details
- **Silent Auto-Refresh:** POSIX `pty` background polling for `agy`, `claude --strict-mcp-config /usage`, and `codex` (zero quota deducted)
- **Auto Dark/Light Theme:** `defaults read -g AppleInterfaceStyle`
- **Auto Language (EN/KO):** `defaults read -g AppleLanguages` (override anytime in Settings)
- **Idle Pause:** `ioreg -c IOHIDSystem` idle detection (pauses after 5 min inactivity)
- **Notifications:** macOS Notification Center (`osascript display notification`)
- **Launch at Login:** `~/Library/LaunchAgents/com.hugreelab.aiusagebar.plist`
- **Data Directory:** `~/Library/Application Support/AIUsageBar/`

---

## 한국어 요약 안내

1. 압축을 푼 폴더에서 `macos/install_macos.command`를 더블클릭하거나 터미널에서 `./macos/install_macos.command`를 실행하면 전용 가상환경 설치, `statusLine` 훅 연결, 바탕화면 실행기 생성까지 한 번에 완료됩니다.
2. macOS에 Tkinter가 없는 경우 `brew install python-tk`를 먼저 실행해 주세요.
3. Mac에서 독립 `.app` / `.dmg`를 직접 빌드하려면 `pip install pyinstaller pillow && python3 macos/build_macos.py`를 실행하세요. (GitHub Releases의 자동 빌드 DMG를 바로 사용하실 수도 있습니다.)
