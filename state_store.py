"""Shared atomic state & config storage for AI Usage Bar."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

if sys.platform == "win32":
    from ctypes import wintypes

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def _resolve_data_dir() -> Path:
    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            return Path(local_app) / "AIUsageBar"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AIUsageBar"
    return Path.home() / ".ai-usage-bar"


DATA_DIR = _resolve_data_dir()
STATE_PATH = DATA_DIR / "quota_state.json"
CONFIG_PATH = DATA_DIR / "config.json"
HISTORY_PATH = DATA_DIR / "quota_history.jsonl"

WEEKLY_WINDOW_SEC = 7.0 * 86400.0
SESSION_5H_WINDOW_SEC = 5.0 * 3600.0

ALL_PROVIDERS = ("antigravity", "claude", "codex")
COMPACT_STYLES = ("dual", "slim", "ring")

DEFAULT_CONFIG: Dict[str, Any] = {
    "x": None,
    "y": None,
    "topmost": True,
    "expanded": False,
    "opacity": 0.94,
    "visible": True,
    "auto_refresh": True,
    "refresh_interval_sec": 180,
    "display_mode": "used",  # "used" (사용량 %, default) or "remaining" (남은량 %)
    "enabled_providers": ["antigravity", "claude"],
    "provider_order": ["antigravity", "claude", "codex"],
    "compact_style": "dual",  # "dual" (2줄 주간+5h), "slim" (1줄 2단바), "ring" (원형 링)
    "slim_sub_metric": "5h",  # "5h" or "model" (for slim mode right indicator)
    "show_pace_marker": True,  # Show time-elapsed pace tick '|' on progress bars
    "notifications": True,
    "notify_warn_pct": 80,  # 0 = off, or 60..90
    "notify_crit_pct": 95,  # 0 = off, or 85..98
    "notify_on_reset": True,
    "notify_include_5h": True,
    "hotkey_enabled": True,
    "hotkey": "Ctrl+Alt+Q",
    "theme": "auto",  # "auto" (OS), "dark", "light"
    "language": "auto",  # "auto" (OS), "ko", "en"
}


def cleanup_stale_temp_files(max_age_sec: float = 60.0) -> None:
    """Remove leftover *.tmp files (and opt-out debug log) from DATA_DIR."""
    if not DATA_DIR.exists():
        return
    now = time.time()
    for p in DATA_DIR.glob("*.tmp"):
        try:
            if now - p.stat().st_mtime >= max_age_sec:
                p.unlink()
        except OSError:
            pass
    if os.environ.get("AIUSAGEBAR_DEBUG") != "1":
        dbg = DATA_DIR / "hook_debug.json"
        if dbg.exists():
            try:
                dbg.unlink()
            except OSError:
                pass


def normalize_provider_order(val: Any) -> list[str]:
    out: list[str] = []
    if isinstance(val, (list, tuple)):
        for p in val:
            if p in ALL_PROVIDERS and p not in out:
                out.append(p)
    for p in ALL_PROVIDERS:
        if p not in out:
            out.append(p)
    return out


def normalize_enabled_providers(val: Any, order: Optional[list[str]] = None) -> list[str]:
    ord_list = normalize_provider_order(order)
    if not isinstance(val, (list, tuple)):
        default_set = {"antigravity", "claude"}
        return [p for p in ord_list if p in default_set]
    val_set = set(val)
    chosen = [p for p in ord_list if p in val_set]
    return chosen if chosen else [ord_list[0]]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def parse_timestamp(value: Any, fallback_in_seconds: Any = None, now: Optional[float] = None) -> Optional[float]:
    """Parse Unix epoch (s/ms), ISO-8601 string, or relative seconds into UTC epoch seconds."""
    if now is None:
        now = time.time()

    if value is not None and value != "":
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 0:
                return ts
        elif isinstance(value, str):
            raw = value.strip()
            if raw:
                try:
                    num = float(raw)
                    if num > 1e12:
                        num /= 1000.0
                    if num > 0:
                        return num
                except ValueError:
                    pass
                try:
                    iso = raw
                    if iso.endswith("Z"):
                        iso = iso[:-1] + "+00:00"
                    dt = datetime.fromisoformat(iso)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except ValueError:
                    pass

    if fallback_in_seconds is not None:
        try:
            sec = float(fallback_in_seconds)
            if sec >= 0:
                return now + sec
        except (TypeError, ValueError):
            pass

    return None


def clamp_pct(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, v)), 1)


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    for _ in range(5):
        try:
            text = path.read_text(encoding="utf-8-sig")
            if not text.strip():
                return json.loads(json.dumps(default))
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            return json.loads(json.dumps(default))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.02)
    return json.loads(json.dumps(default))


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(str(tmp_path), str(path))
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.025)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_state() -> Dict[str, Any]:
    return _read_json(STATE_PATH, {"claude": {}, "antigravity": {}, "codex": {}})


def save_state(state: Dict[str, Any]) -> None:
    _write_json_atomic(STATE_PATH, state)


@contextlib.contextmanager
def _state_file_lock(timeout_ms: int = 800) -> Iterator[None]:
    """Cross-process lock (Win32 named mutex on Windows, fcntl flock on macOS/POSIX)."""
    if sys.platform == "win32":
        k32 = None
        handle = None
        acquired = False
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            k32.CreateMutexW.restype = wintypes.HANDLE
            k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k32.WaitForSingleObject.restype = wintypes.DWORD
            k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            k32.ReleaseMutex.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle.restype = wintypes.BOOL

            handle = k32.CreateMutexW(None, False, "Local\\AIUsageBar_StateLock")
            if handle:
                res = k32.WaitForSingleObject(handle, timeout_ms)
                acquired = res in (0, 0x80)
        except Exception:
            pass
        try:
            yield
        finally:
            if handle and k32 is not None:
                try:
                    if acquired:
                        k32.ReleaseMutex(handle)
                    k32.CloseHandle(handle)
                except Exception:
                    pass
        return

    # POSIX (macOS / Linux) file lock
    lock_file = None
    try:
        import fcntl

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        lock_file = open(DATA_DIR / ".state.lock", "w", encoding="utf-8")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    except Exception:
        pass
    try:
        yield
    finally:
        if lock_file is not None:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except Exception:
                pass


def update_provider_state(provider: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge new provider quota snapshot while preserving previous known limits if omitted."""
    with _state_file_lock():
        state = load_state()
        prev = state.get(provider)
        if not isinstance(prev, dict):
            prev = {}

        merged = dict(prev)
        for k, v in patch.items():
            if k in ("weekly", "weekly_argon", "weekly_fable", "session_5h") and isinstance(v, dict):
                if v.get("remaining_pct") is None and isinstance(prev.get(k), dict):
                    continue
                merged[k] = v
            elif v is not None:
                merged[k] = v

        state[provider] = merged
        save_state(state)
        return state


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    loaded = _read_json(CONFIG_PATH, {})
    for k in DEFAULT_CONFIG:
        if k in loaded:
            cfg[k] = loaded[k]
    cfg["provider_order"] = normalize_provider_order(cfg.get("provider_order"))
    cfg["enabled_providers"] = normalize_enabled_providers(cfg.get("enabled_providers"), cfg["provider_order"])
    if cfg.get("compact_style") not in COMPACT_STYLES:
        cfg["compact_style"] = "dual"
    if cfg.get("slim_sub_metric") not in ("5h", "model"):
        cfg["slim_sub_metric"] = "5h"
    try:
        w_pct = int(cfg.get("notify_warn_pct", 80))
        cfg["notify_warn_pct"] = 0 if w_pct <= 0 else max(10, min(99, w_pct))
    except (TypeError, ValueError):
        cfg["notify_warn_pct"] = 80
    try:
        c_pct = int(cfg.get("notify_crit_pct", 95))
        cfg["notify_crit_pct"] = 0 if c_pct <= 0 else max(10, min(99, c_pct))
    except (TypeError, ValueError):
        cfg["notify_crit_pct"] = 95
    if not isinstance(cfg.get("hotkey"), str) or not cfg["hotkey"].strip():
        cfg["hotkey"] = "Ctrl+Alt+Q"
    if str(cfg.get("language") or "auto").lower() not in ("auto", "ko", "en"):
        cfg["language"] = "auto"
    else:
        cfg["language"] = str(cfg.get("language") or "auto").lower()
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    _write_json_atomic(CONFIG_PATH, cfg)


def format_countdown(
    resets_at: Optional[float],
    compact: bool = False,
    now: Optional[float] = None,
    lang: str = "ko",
) -> str:
    if resets_at is None:
        return ""
    if now is None:
        now = time.time()
    is_en = lang != "ko"
    diff = int(resets_at - now)
    if diff <= 0:
        if is_en:
            return "Reset" if compact else "Reset (pending)"
        return "리셋됨" if compact else "초기화됨 (갱신 대기)"
    days, rem = divmod(diff, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if compact:
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{max(1, mins)}m"
    if is_en:
        if days > 0:
            return f"{days}d {hours}h left"
        if hours > 0:
            return f"{hours}h {mins}m left"
        return f"{max(1, mins)}m left"
    if days > 0:
        return f"{days}일 {hours}시간 남음"
    if hours > 0:
        return f"{hours}시간 {mins}분 남음"
    return f"{max(1, mins)}분 남음"


def format_reset_datetime(resets_at: Optional[float]) -> str:
    if resets_at is None:
        return "-"
    try:
        dt = datetime.fromtimestamp(resets_at)
        return dt.strftime("%m/%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "-"


def format_relative_age(updated_at: Optional[float], now: Optional[float] = None, lang: str = "ko") -> str:
    is_en = lang != "ko"
    if not updated_at:
        return "No data" if is_en else "기록 없음"
    if now is None:
        now = time.time()
    diff = int(now - updated_at)
    if diff < 60:
        return "just now" if is_en else "방금 전"
    if diff < 3600:
        return f"{diff // 60}m ago" if is_en else f"{diff // 60}분 전"
    if diff < 86400:
        return f"{diff // 3600}h ago" if is_en else f"{diff // 3600}시간 전"
    return f"{diff // 86400}d ago" if is_en else f"{diff // 86400}일 전"


def get_effective_bucket(bucket: Optional[Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    if not isinstance(bucket, dict) or bucket.get("remaining_pct") is None:
        return {"remaining_pct": None, "used_pct": None, "resets_at": None, "expired": False}
    if now is None:
        now = time.time()
    resets_at = bucket.get("resets_at")
    expired = bool(resets_at is not None and now >= float(resets_at))
    return {
        "remaining_pct": clamp_pct(bucket.get("remaining_pct")),
        "used_pct": clamp_pct(bucket.get("used_pct")),
        "resets_at": resets_at,
        "expired": expired,
        "bucket_id": bucket.get("bucket_id"),
    }


def _format_duration(sec: float, lang: str = "ko") -> str:
    s = max(60, int(sec))
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if lang != "ko":
        if days > 0:
            return f"{days}d {hours}h" if hours > 0 else f"{days}d"
        if hours > 0:
            return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"
        return f"{max(1, mins)}m"
    if days > 0:
        return f"{days}일 {hours}시간" if hours > 0 else f"{days}일"
    if hours > 0:
        return f"{hours}시간 {mins}분" if mins > 0 else f"{hours}시간"
    return f"{max(1, mins)}분"


def compute_pace(
    used_pct: Optional[float],
    resets_at: Optional[float],
    window_sec: float = WEEKLY_WINDOW_SEC,
    now: Optional[float] = None,
    mode: str = "used",
    lang: str = "ko",
) -> Optional[Dict[str, Any]]:
    """Compute time-elapsed pace marker & burn-rate forecast from (used_pct, resets_at)."""
    if used_pct is None or resets_at is None or window_sec <= 0:
        return None
    if now is None:
        now = time.time()
    rem_sec = float(resets_at) - now
    if rem_sec <= 0 or rem_sec > window_sec * 1.15:
        return None

    elapsed_sec = max(0.0, window_sec - rem_sec)
    elapsed_pct = max(0.0, min(100.0, (elapsed_sec / window_sec) * 100.0))
    marker_pct = elapsed_pct if mode == "used" else max(0.0, min(100.0, 100.0 - elapsed_pct))
    diff = float(used_pct) - elapsed_pct  # >0 means burning faster than steady pace
    is_en = lang != "ko"

    min_elapsed = 1800.0 if window_sec >= 86400.0 else 300.0
    early_sec: Optional[float] = None
    if elapsed_sec >= min_elapsed and used_pct > 0.5:
        rate = float(used_pct) / elapsed_sec
        if rate > 0:
            sec_to_full = max(0.0, 100.0 - float(used_pct)) / rate
            if sec_to_full < rem_sec:
                early_sec = rem_sec - sec_to_full

    if diff >= 15.0 and used_pct >= 15.0:
        status = "fast"
        if early_sec is not None and early_sec >= 1800.0:
            dur = _format_duration(early_sec, lang)
            label = f"Fast (est. empty {dur} early)" if is_en else f"빠름 (리셋 {dur} 전 소진 예상)"
            short = f"Fast (-{dur})" if is_en else f"빠름 (-{dur})"
        else:
            label = (
                f"Fast ({used_pct:.0f}% at {elapsed_pct:.0f}% elapsed)"
                if is_en
                else f"빠름 (경과 {elapsed_pct:.0f}% 대비 {used_pct:.0f}%)"
            )
            short = "Fast pace" if is_en else "페이스 빠름"
    elif diff >= 6.0 and used_pct >= 10.0:
        status = "warn"
        label = (
            f"Slightly fast ({used_pct:.0f}% at {elapsed_pct:.0f}% elapsed)"
            if is_en
            else f"다소 빠름 (경과 {elapsed_pct:.0f}% 대비 {used_pct:.0f}%)"
        )
        short = "Slightly fast" if is_en else "다소 빠름"
    elif diff <= -10.0:
        status = "relaxed"
        label = (
            f"Relaxed ({used_pct:.0f}% at {elapsed_pct:.0f}% elapsed)"
            if is_en
            else f"여유 (경과 {elapsed_pct:.0f}% 대비 {used_pct:.0f}%)"
        )
        short = "Relaxed pace" if is_en else "페이스 여유"
    else:
        status = "steady"
        label = (
            f"On track ({used_pct:.0f}% at {elapsed_pct:.0f}% elapsed)"
            if is_en
            else f"적정 (경과 {elapsed_pct:.0f}% 대비 {used_pct:.0f}%)"
        )
        short = "On track" if is_en else "페이스 적정"

    return {
        "elapsed_pct": round(elapsed_pct, 1),
        "marker_pct": round(marker_pct, 1),
        "diff": round(diff, 1),
        "status": status,
        "label": label,
        "short": short,
        "early_sec": early_sec,
    }


def _extract_used_pct(bucket: Any) -> Optional[float]:
    if not isinstance(bucket, dict):
        return None
    if bucket.get("used_pct") is not None:
        return clamp_pct(bucket.get("used_pct"))
    if bucket.get("remaining_pct") is not None:
        rem = clamp_pct(bucket.get("remaining_pct"))
        return clamp_pct(100.0 - rem) if rem is not None else None
    return None


def append_history_snapshot(state: Dict[str, Any], now: Optional[float] = None, min_interval_sec: float = 150.0) -> None:
    """Append a compact usage history point to quota_history.jsonl (auto-pruned to 8 days)."""
    if now is None:
        now = time.time()
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Extract concise normalized used_pct snapshot
        snap: Dict[str, Any] = {"ts": round(now, 1)}

        agy = state.get("antigravity") if isinstance(state.get("antigravity"), dict) else {}
        ab = agy.get("all_buckets") if isinstance(agy.get("all_buckets"), dict) else {}
        agy_wk = _extract_used_pct(ab.get("gemini-weekly") or agy.get("weekly"))
        agy_ar = _extract_used_pct(agy.get("weekly_argon") or ab.get("gemini-argon-wtu-weekly"))
        agy_5h = _extract_used_pct(ab.get("gemini-5h") or agy.get("session_5h"))
        if any(v is not None for v in (agy_wk, agy_ar, agy_5h)):
            snap["antigravity"] = {"wk": agy_wk, "ar": agy_ar, "s5": agy_5h}

        cld = state.get("claude") if isinstance(state.get("claude"), dict) else {}
        cld_wk = _extract_used_pct(cld.get("weekly"))
        cld_fb = _extract_used_pct(cld.get("weekly_fable"))
        cld_5h = _extract_used_pct(cld.get("session_5h"))
        if any(v is not None for v in (cld_wk, cld_fb, cld_5h)):
            snap["claude"] = {"wk": cld_wk, "fb": cld_fb, "s5": cld_5h}

        cdx = state.get("codex") if isinstance(state.get("codex"), dict) else {}
        cdx_wk = _extract_used_pct(cdx.get("weekly"))
        cdx_5h = _extract_used_pct(cdx.get("session_5h"))
        if any(v is not None for v in (cdx_wk, cdx_5h)):
            snap["codex"] = {"wk": cdx_wk, "s5": cdx_5h}

        if len(snap) <= 1:
            return

        # Skip if last recorded point is too recent and identical
        if HISTORY_PATH.exists():
            try:
                lines = HISTORY_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
                if lines:
                    last = json.loads(lines[-1])
                    last_ts = float(last.get("ts") or 0.0)
                    same_vals = {k: v for k, v in last.items() if k != "ts"} == {k: v for k, v in snap.items() if k != "ts"}
                    if (now - last_ts) < min_interval_sec and same_vals:
                        return
                # Auto-prune if history exceeds 4000 lines (~8 days)
                if len(lines) > 4000:
                    cutoff = now - 8.0 * 86400.0
                    kept = []
                    for ln in lines[-3500:]:
                        try:
                            o = json.loads(ln)
                            if float(o.get("ts") or 0.0) >= cutoff:
                                kept.append(ln)
                        except Exception:
                            pass
                    kept.append(json.dumps(snap, separators=(",", ":")))
                    HISTORY_PATH.write_text("\n".join(kept) + "\n", encoding="utf-8")
                    return
            except Exception:
                pass

        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, separators=(",", ":")) + "\n")
    except Exception:
        pass


def load_history_entries(hours: float = 24.0, now: Optional[float] = None) -> List[Dict[str, Any]]:
    if now is None:
        now = time.time()
    if not HISTORY_PATH.exists():
        return []
    cutoff = now - hours * 3600.0
    out: List[Dict[str, Any]] = []
    try:
        for ln in HISTORY_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not ln.strip():
                continue
            try:
                obj = json.loads(ln)
                if isinstance(obj, dict) and float(obj.get("ts") or 0.0) >= cutoff:
                    out.append(obj)
            except Exception:
                continue
    except OSError:
        return []
    return out


def startup_vbs_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "AIUsageBar.vbs"


def _macos_launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.hugreelab.aiusagebar.plist"


def is_startup_enabled() -> bool:
    if sys.platform == "darwin":
        return _macos_launch_agent_path().exists()
    return startup_vbs_path().exists()


def set_startup_enabled(enabled: bool, target_exe: Optional[Path] = None) -> bool:
    if sys.platform == "darwin":
        from xml.sax.saxutils import escape as _xml_esc

        plist = _macos_launch_agent_path()
        if not enabled:
            if plist.exists():
                plist.unlink()
            return False
        plist.parent.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            exe_path = Path(target_exe) if target_exe is not None else Path(sys.executable)
            prog_args = [str(exe_path.resolve())]
            work_dir = str(exe_path.resolve().parent)
        else:
            run_script = Path(target_exe) if target_exe is not None else (BASE_DIR / "hud_app.py")
            # Preserve venv symlink path (do NOT .resolve() sys.executable, or venv site-packages are lost!)
            prog_args = [os.path.abspath(sys.executable), str(run_script.resolve())]
            work_dir = str(run_script.resolve().parent)
        args_xml = "\n".join(f"        <string>{_xml_esc(a)}</string>" for a in prog_args)
        default_path = f"{Path.home() / '.local' / 'bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        plist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.hugreelab.aiusagebar</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key><string>{_xml_esc(work_dir)}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>{_xml_esc(default_path)}</string>
    </dict>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
"""
        plist.write_text(plist_xml, encoding="utf-8")
        return True

    target = startup_vbs_path()
    if not enabled:
        if target.exists():
            target.unlink()
        return False

    if target_exe is None:
        exe_candidate = BASE_DIR / "AIUsageBar.exe"
        if exe_candidate.exists():
            target_exe = exe_candidate
        else:
            target_exe = BASE_DIR / "start_hud.vbs"

    target.parent.mkdir(parents=True, exist_ok=True)
    vbs_content = (
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run """{target_exe}""", 0, False\r\n'
    )
    target.write_text(vbs_content, encoding="utf-8")
    return True
