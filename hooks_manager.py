"""Shared official statusLine hook, shortcut, and uninstall registry management."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

if sys.platform == "win32":
    import winreg
else:
    winreg = None  # type: ignore[assignment]

from state_store import BASE_DIR, DATA_DIR, set_startup_enabled


def _to_shell_safe_path(path: Path) -> str:
    """Return a forward-slash path with NO spaces (using Windows 8.3 short path if needed)
    so no quotes are required in `cmd /c` (Go exec.Command escapes quotes as `\\\"`) or Git Bash.
    """
    raw = str(path.resolve())
    if sys.platform == "win32" and " " in raw:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = ctypes.WinDLL("kernel32").GetShortPathNameW(raw, buf, 1024)
            if n > 0 and buf.value and " " not in buf.value:
                raw = buf.value
        except Exception:
            pass
    return raw.replace("\\", "/")

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
AGY_SETTINGS = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"
UNINSTALL_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AIUsageBar"
APP_VERSION = "1.8.4"


def find_codex_cli() -> Optional[str]:
    names = ("codex.exe", "codex", "codex.cmd") if sys.platform == "win32" else ("codex",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path.home() / ".local" / "bin" / "codex",
        Path("/opt/homebrew/bin/codex"),
        Path("/usr/local/bin/codex"),
        Path.home() / ".npm-global" / "bin" / "codex",
    ]
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.exists():
        candidates.extend(sorted(nvm_dir.glob("*/bin/codex"), reverse=True))
    appdata = os.environ.get("APPDATA", "")
    local_app = os.environ.get("LOCALAPPDATA", "")
    if appdata:
        candidates.extend([
            Path(appdata) / "npm" / "codex.cmd",
            Path(appdata) / "npm" / "codex",
        ])
    if local_app:
        candidates.append(Path(local_app) / "Programs" / "codex" / "codex.exe")
    candidates.append(Path.home() / ".cargo" / "bin" / ("codex.exe" if sys.platform == "win32" else "codex"))
    vscode_ext = Path.home() / ".vscode" / "extensions"
    if vscode_ext.exists():
        ext_bin = "codex.exe" if sys.platform == "win32" else "codex"
        candidates.extend(vscode_ext.glob(f"openai.chatgpt-*/bin/*/{ext_bin}"))
        candidates.extend(vscode_ext.glob(f"openai.codex-*/bin/*/{ext_bin}"))
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def find_claude_cli() -> Optional[str]:
    names = ("claude.exe", "claude", "claude.cmd") if sys.platform == "win32" else ("claude",)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude.EXE",
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
        Path.home() / ".npm-global" / "bin" / "claude",
    ]
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.exists():
        candidates.extend(sorted(nvm_dir.glob("*/bin/claude"), reverse=True))
    appdata = os.environ.get("APPDATA", "")
    local_app = os.environ.get("LOCALAPPDATA", "")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "claude.cmd")
    if local_app:
        candidates.extend(
            (Path(local_app) / "Microsoft" / "WinGet" / "Packages").glob("Anthropic.ClaudeCode*\\claude.exe")
        )
    # Claude Desktop bundled Claude Code CLI (macOS & Windows) — newest version first
    desktop_bases = []
    if sys.platform == "darwin":
        desktop_bases.append(Path.home() / "Library" / "Application Support" / "Claude" / "claude-code")
    elif sys.platform == "win32" and appdata:
        desktop_bases.append(Path(appdata) / "Claude" / "claude-code")
    ext_bin = "claude.exe" if sys.platform == "win32" else "claude"
    bundled_hits = []
    for base in desktop_bases:
        if base.exists():
            bundled_hits.extend(base.glob(f"*/*/claude.app/Contents/MacOS/{ext_bin}"))
            bundled_hits.extend(base.glob(f"*/claude.app/Contents/MacOS/{ext_bin}"))
            bundled_hits.extend(base.glob(f"*/*/{ext_bin}"))
            bundled_hits.extend(base.glob(f"*/{ext_bin}"))
    # IDE extensions (VS Code / Cursor / Antigravity) bundled Claude Code CLI
    for ide_dir in (".vscode", ".cursor", ".antigravity"):
        ext_root = Path.home() / ide_dir / "extensions"
        if ext_root.exists():
            bundled_hits.extend(ext_root.glob(f"anthropic.claude-code-*/resources/native-binary/{ext_bin}"))
    bundled_hits = [p for p in bundled_hits if p.is_file()]
    bundled_hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    candidates.extend(bundled_hits)
    for c in candidates:
        if c.exists() and c.is_file():
            return str(c)
    return None


def find_agy_cli() -> Optional[str]:
    found = shutil.which("agy")
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "bin" / "agy",
        Path("/opt/homebrew/bin/agy"),
        Path("/usr/local/bin/agy"),
    ]
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        candidates.append(Path(local_app) / "agy" / "bin" / "agy.exe")
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def resolve_hook_executable(install_dir: Optional[Path] = None) -> Optional[Path]:
    search_roots = []
    if install_dir is not None:
        search_roots.append(install_dir)
    search_roots.extend([BASE_DIR, BASE_DIR / "build"])
    for root in search_roots:
        exe = root / "quota_hook.exe"
        if exe.exists():
            return exe.resolve()
    return None


def build_hook_command(provider: str, install_dir: Optional[Path] = None) -> str:
    """Build a command string safe across Go `exec.Command("cmd", "/c", ...)` (agy),
    Node `cmd /c` (Claude Code), PowerShell, and Git Bash.

    CRITICAL: Go's `exec.Command("cmd", "/c", cmdStr)` escapes double-quotes inside
    `cmdStr` as `\\"`, which breaks quoted executable paths! Using a forward-slash
    path with NO quotes (converting spaces via Windows 8.3 short paths when needed)
    works across cmd.exe, Git Bash, PowerShell, Go, and Node simultaneously.
    """
    flag = "--claude" if provider == "claude" else "--agy"
    if sys.platform == "win32":
        hook_exe = resolve_hook_executable(install_dir)
        if hook_exe is not None:
            exe_str = _to_shell_safe_path(hook_exe)
            if " " not in exe_str:
                return f"{exe_str} {flag}"
            return f'"{exe_str}" {flag}'
    else:
        # macOS / POSIX: use zero-dependency Python 3 hook script.
        # In frozen PyInstaller .app bundles, --add-data lives under sys._MEIPASS;
        # copy it to a stable location inside DATA_DIR so CLI hooks survive app moves/updates.
        meipass = getattr(sys, "_MEIPASS", None)
        candidates = [
            (install_dir / "macos" / "quota_hook.py") if install_dir else None,
            BASE_DIR / "macos" / "quota_hook.py",
            BASE_DIR / "quota_hook.py",
            (Path(meipass) / "macos" / "quota_hook.py") if meipass else None,
            (Path(meipass) / "quota_hook.py") if meipass else None,
            (BASE_DIR.parent / "Frameworks" / "macos" / "quota_hook.py"),
            (BASE_DIR.parent / "Resources" / "macos" / "quota_hook.py"),
            DATA_DIR / "quota_hook.py",
        ]
        found_hook: Optional[Path] = None
        for cand in candidates:
            if cand is not None and cand.exists():
                found_hook = cand.resolve()
                break
        if found_hook is not None:
            hook_target = found_hook
            if getattr(sys, "frozen", False) and hook_target != (DATA_DIR / "quota_hook.py"):
                try:
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    stable = DATA_DIR / "quota_hook.py"
                    shutil.copy2(hook_target, stable)
                    stable.chmod(0o755)
                    hook_target = stable.resolve()
                except Exception:
                    pass
            py_bin = (
                shutil.which("python3")
                or ("/usr/bin/python3" if Path("/usr/bin/python3").exists() else None)
                or ("/opt/homebrew/bin/python3" if Path("/opt/homebrew/bin/python3").exists() else None)
                or (sys.executable if not getattr(sys, "frozen", False) else "python3")
            )
            return f'"{py_bin}" "{hook_target}" {flag}'

    py_exe = _to_shell_safe_path(Path(sys.executable))
    script_name = "claude_statusline.py" if provider == "claude" else "agy_statusline.py"
    script_path = _to_shell_safe_path(BASE_DIR / "hooks" / script_name)
    if " " not in py_exe and " " not in script_path:
        return f"{py_exe} {script_path}"
    return f'"{py_exe}" "{script_path}" --ok'


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _save_json_with_backup(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(path, backup)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_managed_command(cmd: str) -> bool:
    low = cmd.lower()
    return any(tok in low for tok in ("quota_hook.exe", "quota_hook.py", "claude_statusline.py", "agy_statusline.py"))


def ensure_default_hooks_if_unset(install_dir: Optional[Path] = None) -> None:
    """Connect official statusLine hooks on first run ONLY when not already configured by another tool.
    Also refreshes stale managed paths (e.g. after upgrading or moving the app on macOS).
    """
    for settings_path, install_fn in (
        (AGY_SETTINGS, install_agy_hook),
        (CLAUDE_SETTINGS, install_claude_hook),
    ):
        try:
            data = _load_json(settings_path) if settings_path.exists() else {}
            sl = data.get("statusLine")
            if not sl:
                install_fn(install_dir)
            elif isinstance(sl, dict):
                cur_cmd = str(sl.get("command", "")).strip()
                if not cur_cmd or _is_managed_command(cur_cmd):
                    desired = build_hook_command("claude" if settings_path == CLAUDE_SETTINGS else "antigravity", install_dir)
                    if cur_cmd != desired:
                        install_fn(install_dir)
        except Exception:
            pass


def install_claude_hook(install_dir: Optional[Path] = None) -> Tuple[bool, str]:
    try:
        data = _load_json(CLAUDE_SETTINGS)
        cmd = build_hook_command("claude", install_dir)
        data["statusLine"] = {"type": "command", "command": cmd}
        _save_json_with_backup(CLAUDE_SETTINGS, data)
        return True, f"Claude Code statusLine 연결 완료: {cmd}"
    except Exception as exc:
        return False, f"Claude Code 설정 실패: {exc}"


def uninstall_claude_hook() -> Tuple[bool, str]:
    if not CLAUDE_SETTINGS.exists():
        return True, "Claude Code 설정 파일 없음"
    try:
        data = _load_json(CLAUDE_SETTINGS)
        sl = data.get("statusLine")
        if isinstance(sl, dict) and _is_managed_command(str(sl.get("command", ""))):
            data.pop("statusLine", None)
            _save_json_with_backup(CLAUDE_SETTINGS, data)
            return True, "Claude Code statusLine 연결 해제 완료"
        return True, "Claude Code statusLine은 다른 설정이 사용 중이라 유지함"
    except Exception as exc:
        return False, f"Claude Code 연결 해제 실패: {exc}"


def install_agy_hook(install_dir: Optional[Path] = None) -> Tuple[bool, str]:
    try:
        data = _load_json(AGY_SETTINGS)
        cmd = build_hook_command("antigravity", install_dir)
        data["statusLine"] = {"type": "command", "command": cmd}
        _save_json_with_backup(AGY_SETTINGS, data)
        return True, f"Antigravity CLI statusLine 연결 완료: {cmd}"
    except Exception as exc:
        return False, f"Antigravity CLI 설정 실패: {exc}"


def uninstall_agy_hook() -> Tuple[bool, str]:
    if not AGY_SETTINGS.exists():
        return True, "Antigravity CLI 설정 파일 없음"
    try:
        data = _load_json(AGY_SETTINGS)
        sl = data.get("statusLine")
        if isinstance(sl, dict) and _is_managed_command(str(sl.get("command", ""))):
            data.pop("statusLine", None)
            _save_json_with_backup(AGY_SETTINGS, data)
            return True, "Antigravity CLI statusLine 연결 해제 완료"
        return True, "Antigravity CLI statusLine은 다른 설정이 사용 중이라 유지함"
    except Exception as exc:
        return False, f"Antigravity CLI 연결 해제 실패: {exc}"


def get_hook_status() -> Dict[str, bool]:
    claude_ok = False
    try:
        if CLAUDE_SETTINGS.exists():
            sl = _load_json(CLAUDE_SETTINGS).get("statusLine", {})
            claude_ok = isinstance(sl, dict) and _is_managed_command(str(sl.get("command", "")))
    except Exception:
        pass

    agy_ok = False
    try:
        if AGY_SETTINGS.exists():
            sl = _load_json(AGY_SETTINGS).get("statusLine", {})
            agy_ok = isinstance(sl, dict) and _is_managed_command(str(sl.get("command", "")))
    except Exception:
        pass

    return {
        "claude_hook": claude_ok,
        "agy_hook": agy_ok,
        "claude_cli": find_claude_cli() is not None,
        "agy_cli": find_agy_cli() is not None,
    }


def create_windows_shortcut(
    lnk_path: Path,
    target_path: Path,
    arguments: str = "",
    working_dir: Optional[Path] = None,
    icon_path: Optional[Path] = None,
    description: str = "AI Usage Bar",
) -> None:
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    wd = str(working_dir or target_path.parent)
    ico = str(icon_path or target_path)

    def _ps_esc(s: str) -> str:
        return s.replace("'", "''")

    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('" + _ps_esc(str(lnk_path)) + "');"
        "$s.TargetPath = '" + _ps_esc(str(target_path)) + "';"
        "$s.Arguments = '" + _ps_esc(arguments) + "';"
        "$s.WorkingDirectory = '" + _ps_esc(wd) + "';"
        "$s.IconLocation = '" + _ps_esc(ico) + "';"
        "$s.Description = '" + _ps_esc(description) + "';"
        "$s.Save();"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
        creationflags=creationflags,
        capture_output=True,
    )


def desktop_shortcut_path() -> Path:
    """Resolve the real Windows Desktop folder (handles OneDrive / redirected Desktop)."""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        # CSIDL_DESKTOPDIRECTORY = 0x0010
        hr = ctypes.windll.shell32.SHGetFolderPathW(0, 0x0010, 0, 0, buf)
        if hr == 0 and buf.value:
            return Path(buf.value) / "AI Usage Bar.lnk"
    except Exception:
        pass
    return Path.home() / "Desktop" / "AI Usage Bar.lnk"


def start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "AI Usage Bar"


def register_uninstall_entry(install_dir: Path) -> None:
    if sys.platform != "win32" or winreg is None:
        return
    exe_path = install_dir / "AIUsageBar.exe"
    icon_path = install_dir / "app_icon.ico"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "AI Usage Bar")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "AI Usage Bar")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(icon_path if icon_path.exists() else exe_path))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{exe_path}" --uninstall')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def remove_uninstall_entry() -> None:
    if sys.platform != "win32" or winreg is None:
        return
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY)
    except OSError:
        pass


def stop_running_hud_processes() -> None:
    """Terminate existing AIUsageBar or hud_app.py processes cleanly before install/uninstall."""
    cur_pid = os.getpid()
    if sys.platform != "win32":
        import signal

        try:
            proc = subprocess.run(["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True, timeout=3.0)
            for ln in proc.stdout.splitlines():
                parts = ln.strip().split(None, 1)
                if len(parts) != 2:
                    continue
                try:
                    pid = int(parts[0])
                except ValueError:
                    continue
                cmd = parts[1]
                if pid == cur_pid:
                    continue
                if "hud_app.py" in cmd or "AIUsageBar.app/Contents/MacOS/AIUsageBar" in cmd:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        pass
        except Exception:
            pass
        return

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    ps = (
        f"$cur = {cur_pid}; "
        "Get-CimInstance Win32_Process | Where-Object { "
        "  $_.ProcessId -ne $cur -and ("
        "    $_.Name -ieq 'AIUsageBar.exe' -or $_.Name -ieq 'AIQuotaHUD.exe' -or "
        "    ($_.Name -ilike 'python*' -and $_.CommandLine -like '*hud_app.py*')"
        "  )"
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        creationflags=creationflags,
        capture_output=True,
    )


def perform_clean_uninstall(install_dir: Path) -> None:
    stop_running_hud_processes()
    uninstall_claude_hook()
    uninstall_agy_hook()
    try:
        set_startup_enabled(False)
    except Exception:
        pass

    if sys.platform != "win32":
        try:
            launcher = Path.home() / "Desktop" / "AI Usage Bar.command"
            if launcher.exists():
                launcher.unlink()
        except Exception:
            pass
        return

    try:
        dlnk = desktop_shortcut_path()
        if dlnk.exists():
            dlnk.unlink()
    except Exception:
        pass
    try:
        sdir = start_menu_dir()
        if sdir.exists():
            shutil.rmtree(sdir, ignore_errors=True)
    except Exception:
        pass
    remove_uninstall_entry()

    # Schedule deletion of install_dir after this process exits (only if inside LocalAppData)
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app and str(install_dir.resolve()).lower().startswith(str(Path(local_app).resolve()).lower()):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.Popen(
            ["cmd.exe", "/c", f'ping 127.0.0.1 -n 3 >nul & rmdir /s /q "{install_dir}"'],
            creationflags=creationflags,
        )
