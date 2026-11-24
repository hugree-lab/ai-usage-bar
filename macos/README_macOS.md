# AI Usage Bar — macOS Guide (`v1.8.5`)

## Option 1: Install from `.dmg` (Apple Silicon)

1. Download **`AIUsageBar-macOS.dmg`** from [GitHub Releases](../../releases).
2. Open the DMG and drag **`AIUsageBar.app`** into **`Applications`**.
3. Because this open-source build does not use paid Apple Notarization, macOS Gatekeeper may block the first launch. Run this once in Terminal:
   ```bash
   xattr -cr /Applications/AIUsageBar.app
   ```
4. Open **`AIUsageBar`** from Applications (official `agy` / `claude` statusLine hooks connect automatically on first launch if unset).

---

## Option 2: Quick Install from Source (Apple Silicon & Intel — No Gatekeeper Warning)

1. Double-click `macos/install_macos.command` or run it in Terminal:
   ```bash
   chmod +x macos/install_macos.command
   ./macos/install_macos.command
   ```
2. This creates a dedicated virtual environment (`~/Library/Application Support/AIUsageBar/venv`), installs `Pillow`, backs up existing CLI configs, and connects the official `Claude Code` / `agy` `statusLine` hooks (`macos/quota_hook.py`).
3. A Desktop launcher (`AI Usage Bar.command`) is created and the HUD starts automatically.

> **Note:** If Tkinter is missing on your Mac Python installation, run `brew install python python-tk` first.

## Build Standalone `.app` & `.dmg` on macOS

```bash
pip install pyinstaller pillow
python3 macos/build_macos.py
```

Output: `dist/AIUsageBar.app` and `dist/AIUsageBar-macOS.dmg`.

## macOS Shortcuts & Implementation Details
- **13 UI Design Themes (26 Dark/Light Looks):** Instant switching from right-click **UI Themes** submenu or **Settings (`⌘,`) → UI Themes** 5×3 gallery (*Modern, Liquid Glass, Silver Classic, Blue 2001, Retro 95, Paper Sky, Paper Sea, Hare & Tortoise, RPG Quest, Neo-Brutal, Thermometer, Battery Cell, Tachometer*)
- **Right-click / Two-finger click (`Control+Click`):** Native macOS context menu (Refresh, Details, UI Themes, Settings, Quit)
- **Keyboard Shortcuts:** `⌘R` Refresh · `⌘,` Settings · `⌘H` Hide (click Dock icon to restore) · `⌘Q` Quit
- **Silent Auto-Refresh:** Safe POSIX `pty.openpty()` + `subprocess.Popen` background polling for `agy`, `claude --strict-mcp-config /usage`, and `codex` (zero quota deducted)
- **Auto Dark/Light Theme:** `defaults read -g AppleInterfaceStyle`
- **Auto Language (EN/KO):** `defaults read -g AppleLanguages` (override anytime in Settings)
- **Idle Pause:** In-process `CoreGraphics` idle detection (pauses after 5 min inactivity with zero subprocess overhead)
- **Notifications:** macOS Notification Center (`osascript display notification`)
- **Launch at Login:** `~/Library/LaunchAgents/com.hugreelab.aiusagebar.plist`
- **Data Directory:** `~/Library/Application Support/AIUsageBar/`

---

## 한국어 요약 안내

### 방법 1: DMG로 설치 (Apple Silicon)
1. [GitHub Releases](../../releases)에서 **`AIUsageBar-macOS.dmg`**를 다운로드해 열고 **`AIUsageBar.app`**을 **`Applications(응용 프로그램)`** 폴더로 드래그합니다.
2. 유료 Apple 공증(Notarization)이 없는 오픈소스 빌드이므로, 최초 실행 시 보안 경고가 뜨면 터미널에서 아래 명령을 1회 실행한 뒤 다시 열어주세요:
   ```bash
   xattr -cr /Applications/AIUsageBar.app
   ```

### 방법 2: 소스에서 바로 설치 (Apple Silicon / Intel 공용 · 보안 경고 없음)
1. 저장소 폴더에서 `macos/install_macos.command`를 더블클릭하거나 터미널에서 `./macos/install_macos.command`를 실행하면 전용 가상환경 설치, `statusLine` 훅 연결, 바탕화면 실행기 생성까지 한 번에 완료됩니다.
2. macOS에 Tkinter가 없는 경우 `brew install python python-tk`를 먼저 실행해 주세요.
3. **13종 UI 디자인 테마 (다크·라이트 총 26종):** 우클릭 **UI 테마** 메뉴 또는 **설정 (`⌘,`) → UI 테마** 탭에서 클릭 한 번으로 즉시 전환할 수 있습니다.
4. **macOS 단축키:** 우클릭(두 손가락 클릭) 컨텍스트 메뉴 · `⌘R` 새로고침 · `⌘,` 설정 · `⌘H` 숨기기(Dock 아이콘 클릭 시 복원) · `⌘Q` 종료.
