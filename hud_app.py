"""AI Usage Bar — Always-on-top Windows floating bar + System Tray monitor
for Antigravity (일반 주간 / Argon 주간 / 5시간), Claude (일반 주간 / Fable 주간 / 5시간),
and optional Codex (주간 7일 / 5시간).
Supports 3 compact styles (2줄 주간+5h, 1줄 슬림 2단바, 원형 2중 링), custom AI ordering,
Windows 11 Dark/Light auto theme, multi-monitor, hover reset tooltips, and threshold alerts.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.messagebox as messagebox
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if sys.platform == "win32":
    from ctypes import wintypes

BASE_DIR_LOCAL = Path(__file__).resolve().parent
if str(BASE_DIR_LOCAL) not in sys.path:
    sys.path.insert(0, str(BASE_DIR_LOCAL))

from background_refresher import read_latest_codex_session_limits, refresh_all_silent
from hooks_manager import (
    ensure_default_hooks_if_unset,
    install_agy_hook,
    install_claude_hook,
    perform_clean_uninstall,
)
from hotkey_manager import GlobalHotkeyManager
from i18n import resolve_lang, tr
from preview_art import png_bytes_to_photoimage, render_dual_ring_png, render_style_preview_png
from settings_dialog import SettingsDialog
from state_store import (
    ALL_PROVIDERS,
    BASE_DIR,
    COMPACT_STYLES,
    DATA_DIR,
    SESSION_5H_WINDOW_SEC,
    STATE_PATH,
    WEEKLY_WINDOW_SEC,
    append_history_snapshot,
    cleanup_stale_temp_files,
    compute_pace,
    format_countdown,
    format_relative_age,
    format_reset_datetime,
    get_effective_bucket,
    is_startup_enabled,
    load_config,
    load_state,
    normalize_enabled_providers,
    normalize_provider_order,
    save_config,
    set_startup_enabled,
    update_provider_state,
)
from win11_ui import (
    FluentMenuItem,
    FluentPopupMenu,
    FluentTooltip,
    apply_win11_dwm,
    get_hwnd,
    get_idle_seconds,
    get_monitor_work_area_for_point,
    get_primary_work_area,
    is_windows_dark_mode,
    ui_font,
)
from win_tray import WinTrayIcon

# Module-private WinDLL handles so argtypes never collide across modules
if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL

    _kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:
    _user32 = None
    _kernel32 = None

# Win32 constants
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
ERROR_ALREADY_EXISTS = 183

# Fixed compact width so the HUD never stretches horizontally
HUD_WIDTH = 338 if sys.platform == "darwin" else 310
DETAIL_BAR_WIDTH = HUD_WIDTH - 38
IDLE_PAUSE_SEC = 300.0  # Pause background polling after 5 min of keyboard/mouse inactivity
REFRESH_INTERVALS = (60, 180, 300, 600)
THEME_CYCLE = ("auto", "dark", "light")

STYLE_LABELS: Dict[str, str] = {
    "dual": "2줄",
    "slim": "슬림",
    "ring": "원형",
}

STYLE_MENU_LABELS: Dict[str, str] = {
    "dual": "2줄 (주간+5h)",
    "slim": "1줄 슬림 (2단 바)",
    "ring": "원형 2중 링",
}

# Dual Windows 11 Fluent palettes with distinct brand signature colors per provider & 5h sub-tone
PALETTES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg_main": "#12151C",
        "bg_card": "#1A1F2B",
        "bg_track": "#252C3D",
        "bg_btn": "#222938",
        "bg_btn_hover": "#2F394F",
        "border": "#2B3347",
        "text_pri": "#F1F5F9",
        "text_sec": "#94A3B8",
        "text_muted": "#64748B",
        # Antigravity (Google/Gemini Blue + Sky Cyan 5h + Argon Violet)
        "accent_agy": "#4F9CF9",
        "accent_agy_5h": "#38BDF8",
        "accent_argon": "#A78BFA",
        # Claude (Anthropic Terracotta Coral + Soft Peach 5h + Fable Rose Pink)
        "accent_claude": "#E07A5F",
        "accent_claude_5h": "#F2A679",
        "accent_fable": "#F472B6",
        # Codex (OpenAI Emerald Green + Mint Teal 5h)
        "accent_codex": "#10B981",
        "accent_codex_5h": "#2DD4BF",
        # Semantic status colors (75%+ warn amber, 90%+ critical crimson red)
        "good": "#34D399",
        "warn": "#F59E0B",
        "low": "#EF4444",
        "expired": "#818CF8",
    },
    "light": {
        "bg_main": "#F3F5F9",
        "bg_card": "#FFFFFF",
        "bg_track": "#E2E8F0",
        "bg_btn": "#E6ECF5",
        "bg_btn_hover": "#D6E0EE",
        "border": "#CBD5E1",
        "text_pri": "#0F172A",
        "text_sec": "#475569",
        "text_muted": "#64748B",
        # Antigravity
        "accent_agy": "#2563EB",
        "accent_agy_5h": "#0284C7",
        "accent_argon": "#7C3AED",
        # Claude
        "accent_claude": "#C96442",
        "accent_claude_5h": "#D97745",
        "accent_fable": "#DB2777",
        # Codex
        "accent_codex": "#059669",
        "accent_codex_5h": "#0D9488",
        # Semantic status colors
        "good": "#059669",
        "warn": "#D97706",
        "low": "#DC2626",
        "expired": "#4F46E5",
    },
}

# (full_name, short_name, primary_weekly_accent_key, short_5h_accent_key)
PROVIDER_META: Dict[str, Tuple[str, str, str, str]] = {
    "antigravity": ("Antigravity", "AGY", "accent_agy", "accent_agy_5h"),
    "claude": ("Claude", "CLD", "accent_claude", "accent_claude_5h"),
    "codex": ("Codex", "CDX", "accent_codex", "accent_codex_5h"),
}


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.WinDLL("user32").SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.WinDLL("user32").SetProcessDPIAware()
            except Exception:
                pass


def acquire_single_instance_mutex() -> Optional[Any]:
    if sys.platform != "win32":
        try:
            import fcntl

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            f = open(DATA_DIR / ".instance.lock", "w", encoding="utf-8")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except Exception:
            return None
    handle = _kernel32.CreateMutexW(None, False, "Local\\AIUsageBar_SingleInstance_v1")
    if not handle:
        return None
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return int(handle)


def set_topmost_noactivate(hwnd: int, topmost: bool) -> None:
    if sys.platform != "win32" or not hwnd or _user32 is None:
        return
    z = wintypes.HWND(HWND_TOPMOST if topmost else HWND_NOTOPMOST)
    _user32.SetWindowPos(
        wintypes.HWND(hwnd), z, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def quota_color(
    pct: Optional[float],
    accent: str,
    expired: bool = False,
    mode: str = "used",
    pal: Optional[Dict[str, str]] = None,
) -> str:
    """Keep each provider's brand signature color until 75% (amber warn) / 90% (red alert)."""
    p = pal or PALETTES["dark"]
    if pct is None:
        return p["text_muted"]
    if expired:
        return p["expired"]
    if mode == "used":
        if pct >= 90.0:
            return p["low"]
        if pct >= 75.0:
            return p["warn"]
        return accent
    if pct <= 10.0:
        return p["low"]
    if pct <= 25.0:
        return p["warn"]
    return accent


def bucket_display_pct(bucket: Dict[str, Any], mode: str) -> Optional[float]:
    if bucket.get("remaining_pct") is None:
        return None
    if mode == "used":
        if bucket.get("used_pct") is not None:
            return float(bucket["used_pct"])
        return round(max(0.0, min(100.0, 100.0 - float(bucket["remaining_pct"]))), 1)
    return float(bucket["remaining_pct"])


def is_warn_level(pct: float, mode: str) -> bool:
    return (pct >= 75.0) if mode == "used" else (pct <= 25.0)


def is_crit_level(pct: float, mode: str) -> bool:
    return (pct >= 90.0) if mode == "used" else (pct <= 10.0)


def format_pct_compact(pct: float, mode: str) -> str:
    if is_crit_level(pct, mode) and pct < 99.5:
        return f"⚠{pct:.0f}%"
    return f"{pct:.0f}%"


def format_pct_detail(pct: float, mode: str) -> str:
    if is_crit_level(pct, mode):
        return f"⚠{pct:.1f}%"
    return f"{pct:.1f}%"


def truncate_text(text: str, max_len: int = 38) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _rounded_rect(canvas: tk.Canvas, x0: int, y0: int, x1: int, y1: int, r: int, **kwargs: Any) -> None:
    if x1 - x0 <= 2 * r:
        canvas.create_oval(x0, y0, x1, y1, **kwargs)
        return
    canvas.create_oval(x0, y0, x0 + 2 * r, y1, **kwargs)
    canvas.create_oval(x1 - 2 * r, y0, x1, y1, **kwargs)
    canvas.create_rectangle(x0 + r, y0, x1 - r, y1, **kwargs)


def draw_rounded_bar(
    canvas: tk.Canvas,
    pct: Optional[float],
    fill_color: str,
    width: int,
    height: int = 5,
    track_color: str = "#252C3D",
    pace_marker_pct: Optional[float] = None,
    marker_color: Optional[str] = None,
) -> None:
    canvas.delete("all")
    w = width
    h = height
    r = max(1, h // 2)
    _rounded_rect(canvas, 0, 0, w, h, r, fill=track_color, outline="")
    if pct is not None:
        clamped = max(0.0, min(100.0, pct))
        fill_w = int(round(w * (clamped / 100.0)))
        if clamped > 0 and fill_w < h:
            fill_w = h
        if fill_w > 0:
            _rounded_rect(canvas, 0, 0, min(w, fill_w), h, r, fill=fill_color, outline="")
    if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
        mx = max(1, min(w - 2, int(round(w * (pace_marker_pct / 100.0)))))
        canvas.create_rectangle(mx, 0, mx + 1, h, fill=marker_color, outline="")


def draw_stacked_dual_bar(
    canvas: tk.Canvas,
    top_pct: Optional[float],
    top_color: str,
    bot_pct: Optional[float],
    bot_color: str,
    width: int,
    track_color: str = "#252C3D",
    top_pace_pct: Optional[float] = None,
    bot_pace_pct: Optional[float] = None,
    marker_color: Optional[str] = None,
) -> None:
    """Draw a sleek 8px dual-bar gauge: top 4px (weekly) + 2px gap + bottom 2px (5h)."""
    canvas.delete("all")
    w = width
    # Top 4px track & fill (weekly)
    _rounded_rect(canvas, 0, 0, w, 4, 2, fill=track_color, outline="")
    if top_pct is not None:
        c1 = max(0.0, min(100.0, top_pct))
        fw1 = int(round(w * (c1 / 100.0)))
        if c1 > 0 and fw1 < 4:
            fw1 = 4
        if fw1 > 0:
            _rounded_rect(canvas, 0, 0, min(w, fw1), 4, 2, fill=top_color, outline="")
    if top_pace_pct is not None and marker_color and 2.0 <= top_pace_pct <= 98.0:
        mx1 = max(1, min(w - 2, int(round(w * (top_pace_pct / 100.0)))))
        canvas.create_rectangle(mx1, 0, mx1 + 1, 4, fill=marker_color, outline="")

    # Bottom 2px track & fill (5h)
    _rounded_rect(canvas, 0, 6, w, 8, 1, fill=track_color, outline="")
    if bot_pct is not None:
        c2 = max(0.0, min(100.0, bot_pct))
        fw2 = int(round(w * (c2 / 100.0)))
        if c2 > 0 and fw2 < 3:
            fw2 = 3
        if fw2 > 0:
            _rounded_rect(canvas, 0, 6, min(w, fw2), 8, 1, fill=bot_color, outline="")
    if bot_pace_pct is not None and marker_color and 2.0 <= bot_pace_pct <= 98.0:
        mx2 = max(1, min(w - 2, int(round(w * (bot_pace_pct / 100.0)))))
        canvas.create_rectangle(mx2, 6, mx2 + 1, 8, fill=marker_color, outline="")


def resolve_agy_buckets(pdata: Dict[str, Any], now: float) -> Dict[str, Any]:
    """Split Antigravity quotas cleanly into 일반 주간, Argon 주간, 5시간 단기, and 3P summary."""
    all_b = pdata.get("all_buckets") if isinstance(pdata.get("all_buckets"), dict) else {}

    raw_gen = None
    raw_argon = pdata.get("weekly_argon") if isinstance(pdata.get("weekly_argon"), dict) else None
    raw_5h = pdata.get("session_5h") if isinstance(pdata.get("session_5h"), dict) else None
    raw_3p_wk = None

    for k, v in all_b.items():
        if not isinstance(v, dict):
            continue
        lk = k.lower()
        if "argon" in lk and raw_argon is None:
            raw_argon = v
        elif lk == "gemini-weekly" or ("gemini" in lk and "week" in lk and "argon" not in lk):
            raw_gen = v
        elif lk == "gemini-5h" or ("gemini" in lk and "5h" in lk):
            raw_5h = v
        elif lk.startswith("3p") and "week" in lk:
            raw_3p_wk = v

    if raw_gen is None and isinstance(pdata.get("weekly"), dict):
        bid = str(pdata["weekly"].get("bucket_id") or "").lower()
        if "argon" not in bid:
            raw_gen = pdata["weekly"]

    return {
        "weekly_gen": get_effective_bucket(raw_gen, now),
        "weekly_argon": get_effective_bucket(raw_argon, now),
        "session_5h": get_effective_bucket(raw_5h, now),
        "third_party_wk": get_effective_bucket(raw_3p_wk, now),
    }


def resolve_claude_buckets(pdata: Dict[str, Any], now: float) -> Dict[str, Any]:
    """Split Claude quotas cleanly into 일반 주간, Fable 주간, and 5시간 단기."""
    raw_gen = pdata.get("weekly") if isinstance(pdata.get("weekly"), dict) else None
    raw_fable = pdata.get("weekly_fable") if isinstance(pdata.get("weekly_fable"), dict) else None
    raw_5h = pdata.get("session_5h") if isinstance(pdata.get("session_5h"), dict) else None

    extra = pdata.get("extra_buckets") if isinstance(pdata.get("extra_buckets"), dict) else {}
    if raw_fable is None:
        for k, v in extra.items():
            if "fable" in k.lower() and isinstance(v, dict):
                raw_fable = v
                break

    return {
        "weekly_gen": get_effective_bucket(raw_gen, now),
        "weekly_fable": get_effective_bucket(raw_fable, now),
        "session_5h": get_effective_bucket(raw_5h, now),
    }


def collect_notify_snapshot(
    state: Dict[str, Any], now: float, lang: str = "ko"
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Extract comparable per-bucket usage/reset snapshots for threshold & reset notifications."""
    snap: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def _put(prov: str, slot: str, label: str, bucket: Dict[str, Any]) -> None:
        used = bucket_display_pct(bucket, "used")
        if used is None:
            return
        snap[(prov, slot)] = {
            "label": label,
            "used_pct": used,
            "resets_at": bucket.get("resets_at"),
            "expired": bool(bucket.get("expired")),
        }

    agy = state.get("antigravity") if isinstance(state.get("antigravity"), dict) else {}
    ab = resolve_agy_buckets(agy, now)
    _put("antigravity", "weekly_gen", f"Antigravity {tr(lang, 'weekly_gen')}", ab["weekly_gen"])
    _put("antigravity", "weekly_argon", f"Antigravity {tr(lang, 'weekly_argon')}", ab["weekly_argon"])
    _put("antigravity", "session_5h", f"Antigravity {tr(lang, 'session_5h')}", ab["session_5h"])

    cld = state.get("claude") if isinstance(state.get("claude"), dict) else {}
    cb = resolve_claude_buckets(cld, now)
    _put("claude", "weekly_gen", f"Claude {tr(lang, 'weekly_gen')}", cb["weekly_gen"])
    _put("claude", "weekly_fable", f"Claude {tr(lang, 'weekly_fable')}", cb["weekly_fable"])
    _put("claude", "session_5h", f"Claude {tr(lang, 'session_5h')}", cb["session_5h"])

    cdx = state.get("codex") if isinstance(state.get("codex"), dict) else {}
    _put("codex", "weekly", f"Codex {tr(lang, 'weekly_7d')}", get_effective_bucket(cdx.get("weekly"), now))
    _put("codex", "session_5h", f"Codex {tr(lang, 'session_5h')}", get_effective_bucket(cdx.get("session_5h"), now))

    return snap


def _cycle_key(resets_at: Optional[float]) -> int:
    if resets_at is None:
        return 0
    return int(round(float(resets_at) / 300.0))


class QuotaHUDApp:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.state = load_state()
        self._last_mtime: float = self._get_state_mtime()
        self._last_tray_sig: Optional[tuple] = None
        self._action_queue: queue.Queue[str] = queue.Queue()
        self._hwnd: int = 0
        self._drag_origin: Optional[tuple[int, int, int, int]] = None
        self._refreshing: bool = False
        self._paused_for_idle: bool = False
        self._last_auto_refresh: float = 0.0
        self._codex_poll_counter: int = 0
        self._theme_poll_counter: int = 0
        self._last_applied_dark: bool = self._is_dark_theme()
        self._ring_photo_cache: Dict[str, Tuple[tuple, tk.PhotoImage]] = {}
        self._style_preview_cache: Dict[Tuple[str, bool], tk.PhotoImage] = {}
        self._settings_dlg: Optional[SettingsDialog] = None

        # Per-provider last silent refresh result for onboarding/diagnostic hints
        self._last_refresh_status: Dict[str, Tuple[bool, str]] = {}
        self._pending_refresh_results: Optional[Dict[str, Tuple[bool, str]]] = None

        # Notification state seeded from initial state so startup never fires stale alerts
        self._notified_milestones: set[tuple] = set()
        self._prev_notify_snap: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._seed_notification_state(time.time())

        pal = self._pal()

        self.root = tk.Tk()
        self.root.title("AI Usage Bar")
        self.root.configure(bg=pal["bg_main"])
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.cfg["topmost"]))
        self.root.attributes("-alpha", float(self.cfg["opacity"]))

        if sys.platform != "win32":
            # Never start permanently hidden when there is no Windows tray icon
            self.cfg["visible"] = True
            ensure_default_hooks_if_unset()

        self._font_title = ui_font("ui", 9, "bold")
        self._font_label = ui_font("ui", 8)
        self._font_pct = ui_font("num", 9, "bold")
        self._font_pct_sm = ui_font("num", 8, "bold")
        self._font_small = ui_font("ui", 8)
        self._font_mono = ui_font("num", 8)

        # Outer container locked strictly to HUD_WIDTH
        self._outer = tk.Frame(self.root, bg=pal["bg_main"], padx=9, pady=7, width=HUD_WIDTH)
        self._outer.pack(fill="both", expand=True)

        self._build_compact_section()
        self._build_detail_section()
        self._build_context_menu()
        self._setup_macos_integration()
        self._bind_tooltips()

        self._apply_visibility_layout(resize_window=False)
        if self.cfg["expanded"]:
            self._detail_frame.pack(fill="x", pady=(6, 0))
            self._btn_expand.configure(text="▴")
        else:
            self._btn_expand.configure(text="▾")

        self._update_pin_visual()
        self._refresh_provider_chips()
        self._refresh_style_chips()
        self._bind_drag(self._outer)
        self._bind_drag(self._compact_frame)
        self._bind_drag(self._rows_container)
        self._bind_drag(self._ring_container)

        self.root.update_idletasks()
        self._hwnd = get_hwnd(self.root)
        apply_win11_dwm(
            self._hwnd,
            border_hex=pal["border"],
            dark_titlebar=self._last_applied_dark,
            toolwindow=True,
        )
        self._position_initial()

        if self.cfg.get("visible", True):
            self.root.deiconify()
            self.root.lift()
            if self._hwnd:
                set_topmost_noactivate(self._hwnd, bool(self.cfg["topmost"]))
        else:
            self.root.withdraw()

        self.tray = WinTrayIcon(
            icon_path=DATA_DIR / "tray_icon.ico",
            on_action=self._enqueue_tray_action,
            get_flags=self._get_tray_flags,
        )
        self.tray.start()

        self.hotkey_mgr = GlobalHotkeyManager(on_trigger=lambda: self._enqueue_tray_action("toggle_show"))
        self.hotkey_mgr.start(
            bool(self.cfg.get("hotkey_enabled", True)),
            str(self.cfg.get("hotkey") or "Ctrl+Alt+Q"),
            lang=self._lang(),
        )
        append_history_snapshot(self.state)

        self._refresh_ui(force_tray=True)
        self.root.after(100, self._process_actions)
        self.root.after(1000, self._tick)
        self.root.after(2500, self._topmost_guard)
        self.root.after(2000, self._auto_refresh_tick)

    # ------------------------------------------------------------------ Config Helpers
    def _lang(self) -> str:
        return resolve_lang(str(self.cfg.get("language") or "auto"))

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self._lang(), key, **kwargs)

    def _apply_language(self) -> None:
        """Update all visible HUD texts & tray immediately after a language switch."""
        FluentTooltip.hide_active()
        self._pv_lbl.configure(text=self._t("lbl_providers"))
        self._st_lbl.configure(text=self._t("lbl_compact"))
        self._btn_snap.configure(text=self._t("btn_snap"))
        self._btn_settings_pill.configure(text=self._t("btn_settings_all"))

        self._agy_slots["weekly_gen"]["lbl"].configure(text=self._t("weekly_gen"))
        self._agy_slots["weekly_argon"]["lbl"].configure(text=self._t("weekly_argon"))
        self._agy_slots["session_5h"]["lbl"].configure(text=self._t("session_5h"))
        self._cld_slots["weekly_gen"]["lbl"].configure(text=self._t("weekly_gen"))
        self._cld_slots["weekly_fable"]["lbl"].configure(text=self._t("weekly_fable"))
        self._cld_slots["session_5h"]["lbl"].configure(text=self._t("session_5h"))
        self._cdx_slots["weekly"]["lbl"].configure(text=self._t("weekly_7d"))
        self._cdx_slots["session_5h"]["lbl"].configure(text=self._t("session_5h"))

        self._refresh_style_chips()
        self._refresh_mode_btn()
        self._refresh_ui(force_tray=True)

    def _theme_mode(self) -> str:
        t = str(self.cfg.get("theme") or "auto").lower()
        return t if t in THEME_CYCLE else "auto"

    def _is_dark_theme(self) -> bool:
        mode = self._theme_mode()
        if mode == "dark":
            return True
        if mode == "light":
            return False
        return is_windows_dark_mode(system_surface=False)

    def _pal(self) -> Dict[str, str]:
        return PALETTES["dark" if self._is_dark_theme() else "light"]

    def _compact_style(self) -> str:
        s = str(self.cfg.get("compact_style") or "dual").lower()
        return s if s in COMPACT_STYLES else "dual"

    def _slim_sub_metric(self) -> str:
        return "model" if str(self.cfg.get("slim_sub_metric") or "5h").lower() == "model" else "5h"

    def _provider_order(self) -> list[str]:
        return normalize_provider_order(self.cfg.get("provider_order"))

    def _enabled_providers(self) -> list[str]:
        return normalize_enabled_providers(self.cfg.get("enabled_providers"), self._provider_order())

    def _cycle_theme(self) -> None:
        cur = self._theme_mode()
        idx = (THEME_CYCLE.index(cur) + 1) % len(THEME_CYCLE)
        self.cfg["theme"] = THEME_CYCLE[idx]
        save_config(self.cfg)
        self._apply_theme()

    def _set_compact_style(self, style: str) -> None:
        if style not in COMPACT_STYLES:
            return
        FluentTooltip.hide_active()
        self.cfg["compact_style"] = style
        save_config(self.cfg)
        self._refresh_style_chips()
        self._apply_visibility_layout(resize_window=True)
        self._refresh_ui(force_tray=False)

    def _cycle_compact_style(self) -> None:
        cur = self._compact_style()
        nxt = COMPACT_STYLES[(COMPACT_STYLES.index(cur) + 1) % len(COMPACT_STYLES)]
        self._set_compact_style(nxt)

    def _toggle_slim_sub_metric(self) -> None:
        FluentTooltip.hide_active()
        self.cfg["slim_sub_metric"] = "model" if self._slim_sub_metric() == "5h" else "5h"
        save_config(self.cfg)
        self._refresh_ui(force_tray=False)

    def _move_provider(self, prov: str, delta: int) -> None:
        """Move provider up (-1) or down (+1) among enabled providers (preserving full order)."""
        order = self._provider_order()
        enabled = self._enabled_providers()
        if prov not in enabled or len(enabled) <= 1:
            return
        e_idx = enabled.index(prov)
        target_e_idx = e_idx + delta
        if not (0 <= target_e_idx < len(enabled)):
            return
        other = enabled[target_e_idx]
        i1, i2 = order.index(prov), order.index(other)
        order[i1], order[i2] = order[i2], order[i1]
        self.cfg["provider_order"] = order
        self.cfg["enabled_providers"] = normalize_enabled_providers(self.cfg.get("enabled_providers"), order)
        save_config(self.cfg)
        self._refresh_provider_chips()
        self._apply_visibility_layout(resize_window=False)
        self._refresh_ui(force_tray=True)

    def _rotate_provider_order(self) -> None:
        """Rotate order of currently enabled providers (instant swap for 2 AIs, cycle for 3)."""
        enabled = self._enabled_providers()
        if len(enabled) <= 1:
            return
        order = self._provider_order()
        rotated = enabled[1:] + enabled[:1]
        positions = [order.index(p) for p in enabled]
        for pos, prov in zip(positions, rotated):
            order[pos] = prov
        self.cfg["provider_order"] = order
        self.cfg["enabled_providers"] = normalize_enabled_providers(self.cfg.get("enabled_providers"), order)
        save_config(self.cfg)
        self._refresh_provider_chips()
        self._apply_visibility_layout(resize_window=False)
        self._refresh_ui(force_tray=True)

    def _open_settings(self, tab: str = "display") -> None:
        FluentTooltip.hide_active()
        if self._settings_dlg is not None and not self._settings_dlg._closed:
            self._settings_dlg.show_tab(tab)
            return
        self._settings_dlg = SettingsDialog(self, initial_tab=tab)

    def _update_hotkey(self, enabled: bool, spec: str) -> Tuple[bool, str]:
        ok, msg = self.hotkey_mgr.update(enabled, spec, lang=self._lang())
        if ok or not enabled:
            self.cfg["hotkey_enabled"] = bool(enabled)
            if spec:
                self.cfg["hotkey"] = spec
            save_config(self.cfg)
        return ok, msg

    def _test_notification(self) -> None:
        if hasattr(self, "tray"):
            self.tray.notify(
                self._t("noti_test_title"),
                self._t("noti_test_body"),
                warning=False,
            )

    def _reseed_notifications(self) -> None:
        self._notified_milestones.clear()
        self._seed_notification_state(time.time())

    def _get_style_preview_photo(self, style: str) -> Any:
        dark = self._is_dark_theme()
        key = (style, dark)
        cached = self._style_preview_cache.get(key)
        if cached is not None:
            return cached
        png = render_style_preview_png(style, self._pal(), width=164, height=82)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._style_preview_cache[key] = photo
        return photo

    # ------------------------------------------------------------------ Live Theme Switch
    def _apply_theme(self) -> None:
        FluentTooltip.hide_active()
        dark = self._is_dark_theme()
        self._last_applied_dark = dark
        pal = PALETTES["dark" if dark else "light"]
        self._ring_photo_cache.clear()
        self._style_preview_cache.clear()

        self.root.configure(bg=pal["bg_main"])
        for w in (
            self._outer, self._compact_frame, self._hdr, self._btn_bar,
            self._rows_container, self._ring_container, self._detail_frame,
            self._cards_container, self._ctrl, self._pv_row, self._st_row,
            self._act_row,
        ):
            w.configure(bg=pal["bg_main"])

        self._lbl_title.configure(bg=pal["bg_main"], fg=pal["text_sec"])
        self._detail_sep.configure(bg=pal["border"])
        self._pv_lbl.configure(bg=pal["bg_main"], fg=pal["text_muted"])
        self._st_lbl.configure(bg=pal["bg_main"], fg=pal["text_muted"])

        for b in (
            self._btn_refresh, self._btn_expand, self._btn_settings,
            self._btn_pin, self._btn_hide,
        ):
            self._restore_btn_style(b)

        for prov, row in self._rows.items():
            accent = pal[PROVIDER_META[prov][2]]
            row["frame"].configure(bg=pal["bg_card"])
            row["dot"].configure(bg=pal["bg_card"])
            row["dot"].itemconfig(row["dot_id"], fill=accent)
            row["name"].configure(bg=pal["bg_card"], fg=pal["text_pri"])
            row["bar"].configure(bg=pal["bg_card"])
            row["pct"].configure(bg=pal["bg_card"])
            row["sub"].configure(bg=pal["bg_card"])
            row["lbl_5h"].configure(bg=pal["bg_card"], fg=pal["text_muted"])
            row["bar_5h"].configure(bg=pal["bg_card"])
            row["pct_5h"].configure(bg=pal["bg_card"])
            row["sub_5h"].configure(bg=pal["bg_card"])

        for prov, rc in self._ring_cards.items():
            accent = pal[PROVIDER_META[prov][2]]
            rc["frame"].configure(bg=pal["bg_card"])
            rc["canvas"].configure(bg=pal["bg_card"])
            rc["name"].configure(bg=pal["bg_card"], fg=accent)
            rc["sub"].configure(bg=pal["bg_card"], fg=pal["text_sec"])

        for prov, cinfo in self._card_refs.items():
            accent = pal[PROVIDER_META[prov][2]]
            cinfo["card"].configure(bg=pal["bg_card"])
            cinfo["top"].configure(bg=pal["bg_card"])
            cinfo["title"].configure(bg=pal["bg_card"], fg=accent)
            cinfo["btn_up"].configure(bg=pal["bg_card"], fg=pal["text_muted"])
            cinfo["btn_dn"].configure(bg=pal["bg_card"], fg=pal["text_muted"])
            cinfo["meta"].configure(bg=pal["bg_card"], fg=pal["text_muted"])
            cinfo["footer"].configure(bg=pal["bg_card"], fg=pal["text_muted"])
            for slot in cinfo["slots"].values():
                slot["hdr"].configure(bg=pal["bg_card"])
                slot["lbl"].configure(bg=pal["bg_card"], fg=pal["text_sec"])
                slot["pct"].configure(bg=pal["bg_card"])
                slot["sub"].configure(bg=pal["bg_card"])
                slot["bar"].configure(bg=pal["bg_card"])

        for b in self._pill_btns:
            b.configure(bg=pal["bg_btn"], fg=pal["text_sec"])

        self._refresh_provider_chips()
        self._refresh_style_chips()
        self._refresh_mode_btn()

        if self._hwnd:
            apply_win11_dwm(
                self._hwnd,
                border_hex=pal["border"],
                dark_titlebar=dark,
                toolwindow=True,
            )
        self._refresh_ui(force_tray=False)
        if self._settings_dlg is not None and not self._settings_dlg._closed:
            self._settings_dlg.refresh_theme()

    # ------------------------------------------------------------------ UI Build
    def _build_compact_section(self) -> None:
        pal = self._pal()
        self._compact_frame = tk.Frame(self._outer, bg=pal["bg_main"])
        self._compact_frame.pack(fill="x")

        self._hdr = tk.Frame(self._compact_frame, bg=pal["bg_main"])
        self._hdr.pack(fill="x", pady=(0, 4))
        self._bind_drag(self._hdr)

        self._lbl_title = tk.Label(
            self._hdr, text=self._t("hud_title_used"), bg=pal["bg_main"], fg=pal["text_sec"],
            font=ui_font("ui", 8, "bold"),
        )
        self._lbl_title.pack(side="left")
        self._bind_drag(self._lbl_title)
        self._lbl_title.bind("<Double-Button-1>", lambda _e: self._snap_to_taskbar())

        self._btn_bar = tk.Frame(self._hdr, bg=pal["bg_main"])
        self._btn_bar.pack(side="right")

        self._btn_refresh = self._make_icon_btn(self._btn_bar, "↻", self._trigger_refresh)
        self._btn_expand = self._make_icon_btn(self._btn_bar, "▾", self._toggle_expand)
        self._btn_settings = self._make_icon_btn(self._btn_bar, "⚙", lambda: self._open_settings("display"))
        self._btn_pin = self._make_icon_btn(self._btn_bar, "📌", self._toggle_topmost)
        self._btn_hide = self._make_icon_btn(self._btn_bar, "—", self._hide_to_tray)

        for b in (
            self._btn_refresh, self._btn_expand, self._btn_settings,
            self._btn_pin, self._btn_hide,
        ):
            b.pack(side="left", padx=(2, 0))

        # Container A: Row-based compact view ("dual" 2-line and "slim" 1-line)
        self._rows_container = tk.Frame(self._compact_frame, bg=pal["bg_main"])
        self._rows: Dict[str, Dict[str, Any]] = {}
        for prov in ALL_PROVIDERS:
            _full, short, accent_key, _inner = PROVIDER_META[prov]
            self._rows[prov] = self._make_compact_row(self._rows_container, prov, short, accent_key)

        # Container B: Circular ring compact view ("ring")
        self._ring_container = tk.Frame(self._compact_frame, bg=pal["bg_main"])
        self._ring_cards: Dict[str, Dict[str, Any]] = {}
        for prov in ALL_PROVIDERS:
            _full, short, accent_key, inner_key = PROVIDER_META[prov]
            self._ring_cards[prov] = self._make_ring_card(
                self._ring_container, prov, short, accent_key, inner_key
            )

    def _make_icon_btn(
        self, parent: tk.Widget, text: str, cmd, font: Optional[Tuple[Any, ...]] = None
    ) -> tk.Label:
        pal = self._pal()
        lbl = tk.Label(
            parent,
            text=text,
            bg=pal["bg_main"],
            fg=pal["text_sec"],
            font=font or ui_font("sym", 9),
            padx=3,
            pady=0,
            cursor="hand2",
        )
        lbl.bind("<Button-1>", lambda _e: cmd())
        lbl.bind("<Enter>", lambda _e, w=lbl: w.configure(bg=self._pal()["bg_btn_hover"], fg=self._pal()["text_pri"]))
        lbl.bind("<Leave>", lambda _e, w=lbl: self._restore_btn_style(w))
        return lbl

    def _restore_btn_style(self, lbl: tk.Label) -> None:
        pal = self._pal()
        if lbl is getattr(self, "_btn_pin", None):
            self._update_pin_visual()
        elif lbl is getattr(self, "_btn_refresh", None) and self._refreshing:
            lbl.configure(bg=pal["bg_main"], fg=pal["accent_agy"])
        else:
            lbl.configure(bg=pal["bg_main"], fg=pal["text_sec"])

    def _make_compact_row(
        self, parent: tk.Widget, prov: str, short_name: str, accent_key: str
    ) -> Dict[str, Any]:
        """Grid-aligned compact row supporting both 'dual' (2-line weekly+5h) and 'slim' (1-line)."""
        pal = self._pal()
        accent = pal[accent_key]
        row = tk.Frame(parent, bg=pal["bg_card"], padx=8, pady=4)
        row.grid_columnconfigure(2, weight=1)
        self._bind_drag(row)

        # Row 0: Weekly
        dot = tk.Canvas(row, width=7, height=7, bg=pal["bg_card"], highlightthickness=0)
        dot_id = dot.create_oval(0, 0, 6, 6, fill=accent, outline="")
        dot.grid(row=0, column=0, padx=(0, 5), sticky="w")
        self._bind_drag(dot)

        name_lbl = tk.Label(
            row, text=short_name, bg=pal["bg_card"], fg=pal["text_pri"],
            font=ui_font("num", 9, "bold"), width=4, anchor="w",
        )
        name_lbl.grid(row=0, column=1, sticky="w")
        self._bind_drag(name_lbl)

        bar = tk.Canvas(row, width=102, height=6, bg=pal["bg_card"], highlightthickness=0)
        bar.grid(row=0, column=2, padx=(3, 6), sticky="w")
        self._bind_drag(bar)

        pct_lbl = tk.Label(
            row, text="--%", bg=pal["bg_card"], fg=pal["text_muted"],
            font=self._font_pct, width=5, anchor="e",
        )
        pct_lbl.grid(row=0, column=3, sticky="e")
        self._bind_drag(pct_lbl)

        sub_lbl = tk.Label(
            row, text=self._t("waiting"), bg=pal["bg_card"], fg=pal["text_muted"],
            font=self._font_small, width=8, anchor="e",
        )
        sub_lbl.grid(row=0, column=4, padx=(4, 0), sticky="e")

        def on_sub_press(event: tk.Event) -> Optional[str]:
            if self._compact_style() == "slim":
                self._toggle_slim_sub_metric()
                return "break"
            self._on_drag_start(event)
            return None

        sub_lbl.bind("<ButtonPress-1>", on_sub_press)
        sub_lbl.bind("<B1-Motion>", self._on_drag_move)
        sub_lbl.bind("<ButtonRelease-1>", self._on_drag_end)

        # Row 1: 5-hour short-term (visible in 'dual' mode, hidden in 'slim' mode)
        lbl_5h = tk.Label(
            row, text="5h", bg=pal["bg_card"], fg=pal["text_muted"],
            font=ui_font("num", 8), width=4, anchor="w",
        )
        lbl_5h.grid(row=1, column=1, pady=(1, 0), sticky="w")
        self._bind_drag(lbl_5h)

        bar_5h = tk.Canvas(row, width=102, height=3, bg=pal["bg_card"], highlightthickness=0)
        bar_5h.grid(row=1, column=2, padx=(3, 6), pady=(1, 0), sticky="w")
        self._bind_drag(bar_5h)

        pct_5h = tk.Label(
            row, text="--%", bg=pal["bg_card"], fg=pal["text_muted"],
            font=self._font_pct_sm, width=5, anchor="e",
        )
        pct_5h.grid(row=1, column=3, pady=(1, 0), sticky="e")
        self._bind_drag(pct_5h)

        sub_5h = tk.Label(
            row, text="", bg=pal["bg_card"], fg=pal["text_muted"],
            font=self._font_mono, width=8, anchor="e",
        )
        sub_5h.grid(row=1, column=4, padx=(4, 0), pady=(1, 0), sticky="e")
        self._bind_drag(sub_5h)

        row1_widgets = [lbl_5h, bar_5h, pct_5h, sub_5h]
        all_widgets = [row, dot, name_lbl, bar, pct_lbl, sub_lbl] + row1_widgets
        for w in all_widgets:
            if w is not sub_lbl:
                w.bind("<Double-Button-1>", lambda _e: self._toggle_expand())

        return {
            "prov": prov,
            "frame": row,
            "dot": dot,
            "dot_id": dot_id,
            "name": name_lbl,
            "bar": bar,
            "pct": pct_lbl,
            "sub": sub_lbl,
            "lbl_5h": lbl_5h,
            "bar_5h": bar_5h,
            "pct_5h": pct_5h,
            "sub_5h": sub_5h,
            "row1_widgets": row1_widgets,
            "accent_key": accent_key,
            "widgets": all_widgets,
        }

    def _make_ring_card(
        self, parent: tk.Widget, prov: str, short_name: str, accent_key: str, inner_key: str
    ) -> Dict[str, Any]:
        pal = self._pal()
        card = tk.Frame(parent, bg=pal["bg_card"], padx=4, pady=6)
        self._bind_drag(card)

        canvas = tk.Canvas(card, width=70, height=70, bg=pal["bg_card"], highlightthickness=0)
        canvas.pack(pady=(0, 3))
        self._bind_drag(canvas)

        name_lbl = tk.Label(
            card, text=short_name, bg=pal["bg_card"], fg=pal[accent_key],
            font=ui_font("num", 9, "bold"),
        )
        name_lbl.pack()
        self._bind_drag(name_lbl)

        sub_lbl = tk.Label(
            card, text=self._t("waiting"), bg=pal["bg_card"], fg=pal["text_sec"],
            font=ui_font("ui", 7), justify="center",
        )
        sub_lbl.pack(pady=(1, 0))
        self._bind_drag(sub_lbl)

        widgets = [card, canvas, name_lbl, sub_lbl]
        for w in widgets:
            w.bind("<Double-Button-1>", lambda _e: self._toggle_expand())

        return {
            "prov": prov,
            "frame": card,
            "canvas": canvas,
            "name": name_lbl,
            "sub": sub_lbl,
            "accent_key": accent_key,
            "inner_key": inner_key,
            "widgets": widgets,
            "photo": None,
        }

    def _make_metric_slot(self, parent: tk.Widget, label_text: str, accent_key: str, top_pad: int = 3) -> Dict[str, Any]:
        pal = self._pal()
        hdr = tk.Frame(parent, bg=pal["bg_card"])
        hdr.pack(fill="x", pady=(top_pad, 1))

        lbl = tk.Label(hdr, text=label_text, bg=pal["bg_card"], fg=pal["text_sec"], font=self._font_label)
        lbl.pack(side="left")
        pct_lbl = tk.Label(hdr, text="--%", bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_pct, width=6, anchor="e")
        pct_lbl.pack(side="right")
        sub_lbl = tk.Label(hdr, text="", bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_mono, anchor="e")
        sub_lbl.pack(side="right", padx=(4, 4))

        bar = tk.Canvas(parent, width=DETAIL_BAR_WIDTH, height=4, bg=pal["bg_card"], highlightthickness=0)
        bar.pack(fill="x")

        return {
            "hdr": hdr,
            "lbl": lbl,
            "accent_key": accent_key,
            "pct": pct_lbl,
            "sub": sub_lbl,
            "bar": bar,
        }

    def _make_order_arrow(self, parent: tk.Widget, text: str, prov: str, delta: int) -> tk.Label:
        pal = self._pal()
        btn = tk.Label(
            parent, text=text, bg=pal["bg_card"], fg=pal["text_muted"],
            font=ui_font("sym", 7), padx=2, pady=0, cursor="hand2",
        )
        btn.bind("<Button-1>", lambda _e, p=prov, d=delta: self._move_provider(p, d))
        btn.bind("<Enter>", lambda _e, w=btn: w.configure(fg=self._pal()["text_pri"]))
        btn.bind("<Leave>", lambda _e, w=btn: w.configure(fg=self._pal()["text_muted"]))
        return btn

    def _build_detail_section(self) -> None:
        pal = self._pal()
        self._detail_frame = tk.Frame(self._outer, bg=pal["bg_main"])

        self._detail_sep = tk.Frame(self._detail_frame, bg=pal["border"], height=1)
        self._detail_sep.pack(fill="x", pady=(0, 5))

        self._cards_container = tk.Frame(self._detail_frame, bg=pal["bg_main"])
        self._cards_container.pack(fill="x")
        self._detail_cards: Dict[str, tk.Frame] = {}
        self._card_refs: Dict[str, Dict[str, Any]] = {}

        # Antigravity compact detail card
        agy_card = tk.Frame(self._cards_container, bg=pal["bg_card"], padx=9, pady=5)
        self._detail_cards["antigravity"] = agy_card
        agy_top = tk.Frame(agy_card, bg=pal["bg_card"])
        agy_top.pack(fill="x")
        agy_title = tk.Label(agy_top, text="Antigravity", bg=pal["bg_card"], fg=pal["accent_agy"], font=self._font_title)
        agy_title.pack(side="left")
        agy_up = self._make_order_arrow(agy_top, "▲", "antigravity", -1)
        agy_dn = self._make_order_arrow(agy_top, "▼", "antigravity", 1)
        agy_up.pack(side="left", padx=(4, 0))
        agy_dn.pack(side="left")
        self._agy_meta = tk.Label(agy_top, text=self._t("waiting_conn"), bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_small)
        self._agy_meta.pack(side="right")

        self._agy_slots = {
            "weekly_gen": self._make_metric_slot(agy_card, self._t("weekly_gen"), "accent_agy", top_pad=3),
            "weekly_argon": self._make_metric_slot(agy_card, self._t("weekly_argon"), "accent_argon", top_pad=3),
            "session_5h": self._make_metric_slot(agy_card, self._t("session_5h"), "accent_agy_5h", top_pad=3),
        }
        self._agy_footer = tk.Label(agy_card, text="", bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_small, anchor="w")
        self._agy_footer.pack(fill="x", pady=(3, 0))
        self._card_refs["antigravity"] = {
            "card": agy_card, "top": agy_top, "title": agy_title,
            "btn_up": agy_up, "btn_dn": agy_dn,
            "meta": self._agy_meta, "footer": self._agy_footer, "slots": self._agy_slots,
        }

        # Claude compact detail card
        cld_card = tk.Frame(self._cards_container, bg=pal["bg_card"], padx=9, pady=5)
        self._detail_cards["claude"] = cld_card
        cld_top = tk.Frame(cld_card, bg=pal["bg_card"])
        cld_top.pack(fill="x")
        cld_title = tk.Label(cld_top, text="Claude", bg=pal["bg_card"], fg=pal["accent_claude"], font=self._font_title)
        cld_title.pack(side="left")
        cld_up = self._make_order_arrow(cld_top, "▲", "claude", -1)
        cld_dn = self._make_order_arrow(cld_top, "▼", "claude", 1)
        cld_up.pack(side="left", padx=(4, 0))
        cld_dn.pack(side="left")
        self._cld_meta = tk.Label(cld_top, text=self._t("waiting_conn"), bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_small)
        self._cld_meta.pack(side="right")

        self._cld_slots = {
            "weekly_gen": self._make_metric_slot(cld_card, self._t("weekly_gen"), "accent_claude", top_pad=3),
            "weekly_fable": self._make_metric_slot(cld_card, self._t("weekly_fable"), "accent_fable", top_pad=3),
            "session_5h": self._make_metric_slot(cld_card, self._t("session_5h"), "accent_claude_5h", top_pad=3),
        }
        self._cld_footer = tk.Label(cld_card, text="", bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_small, anchor="w")
        self._cld_footer.pack(fill="x", pady=(3, 0))
        self._card_refs["claude"] = {
            "card": cld_card, "top": cld_top, "title": cld_title,
            "btn_up": cld_up, "btn_dn": cld_dn,
            "meta": self._cld_meta, "footer": self._cld_footer, "slots": self._cld_slots,
        }

        # Codex compact detail card
        cdx_card = tk.Frame(self._cards_container, bg=pal["bg_card"], padx=9, pady=5)
        self._detail_cards["codex"] = cdx_card
        cdx_top = tk.Frame(cdx_card, bg=pal["bg_card"])
        cdx_top.pack(fill="x")
        cdx_title = tk.Label(cdx_top, text="Codex", bg=pal["bg_card"], fg=pal["accent_codex"], font=self._font_title)
        cdx_title.pack(side="left")
        cdx_up = self._make_order_arrow(cdx_top, "▲", "codex", -1)
        cdx_dn = self._make_order_arrow(cdx_top, "▼", "codex", 1)
        cdx_up.pack(side="left", padx=(4, 0))
        cdx_dn.pack(side="left")
        self._cdx_meta = tk.Label(cdx_top, text=self._t("waiting_conn"), bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_small)
        self._cdx_meta.pack(side="right")

        self._cdx_slots = {
            "weekly": self._make_metric_slot(cdx_card, self._t("weekly_7d"), "accent_codex", top_pad=3),
            "session_5h": self._make_metric_slot(cdx_card, self._t("session_5h"), "accent_codex_5h", top_pad=3),
        }
        self._cdx_footer = tk.Label(cdx_card, text="", bg=pal["bg_card"], fg=pal["text_muted"], font=self._font_small, anchor="w")
        self._cdx_footer.pack(fill="x", pady=(3, 0))
        self._card_refs["codex"] = {
            "card": cdx_card, "top": cdx_top, "title": cdx_title,
            "btn_up": cdx_up, "btn_dn": cdx_dn,
            "meta": self._cdx_meta, "footer": self._cdx_footer, "slots": self._cdx_slots,
        }

        # Compact bottom controls (AI selector chips + compact style chips + buttons)
        self._ctrl = tk.Frame(self._detail_frame, bg=pal["bg_main"])
        self._ctrl.pack(fill="x", pady=(1, 0))

        self._pv_row = tk.Frame(self._ctrl, bg=pal["bg_main"])
        self._pv_row.pack(fill="x", pady=(0, 3))
        self._pv_lbl = tk.Label(self._pv_row, text=self._t("lbl_providers"), bg=pal["bg_main"], fg=pal["text_muted"], font=self._font_small)
        self._pv_lbl.pack(side="left")
        self._provider_chips: Dict[str, tk.Label] = {}
        for prov in ALL_PROVIDERS:
            _full, short, _acc, _in = PROVIDER_META[prov]
            chip = tk.Label(
                self._pv_row, text=short, bg=pal["bg_btn"], fg=pal["text_muted"],
                font=self._font_small, padx=7, pady=1, cursor="hand2",
            )
            chip.bind("<Button-1>", lambda _e, p=prov: self._toggle_provider(p))
            self._provider_chips[prov] = chip

        self._st_row = tk.Frame(self._ctrl, bg=pal["bg_main"])
        self._st_row.pack(fill="x", pady=(0, 4))
        self._st_lbl = tk.Label(self._st_row, text=self._t("lbl_compact"), bg=pal["bg_main"], fg=pal["text_muted"], font=self._font_small)
        self._st_lbl.pack(side="left")
        self._style_chips: Dict[str, tk.Label] = {}
        for st in reversed(COMPACT_STYLES):
            chip = tk.Label(
                self._st_row, text=self._t(f"style_{st}"), bg=pal["bg_btn"], fg=pal["text_muted"],
                font=self._font_small, padx=7, pady=1, cursor="hand2",
            )
            chip.bind("<Button-1>", lambda _e, s=st: self._set_compact_style(s))
            chip.pack(side="right", padx=(4, 0))
            self._style_chips[st] = chip

        self._act_row = tk.Frame(self._ctrl, bg=pal["bg_main"])
        self._act_row.pack(fill="x")
        self._pill_btns: List[tk.Label] = []
        self._btn_mode = self._make_pill_btn(self._act_row, "", self._toggle_display_mode)
        self._btn_mode.pack(side="left", padx=(0, 4))
        self._btn_snap = self._make_pill_btn(self._act_row, self._t("btn_snap"), self._snap_to_taskbar)
        self._btn_snap.pack(side="left", padx=(0, 4))
        self._btn_settings_pill = self._make_pill_btn(self._act_row, self._t("btn_settings_all"), lambda: self._open_settings("display"))
        self._btn_settings_pill.pack(side="right")
        self._refresh_mode_btn()

    def _make_pill_btn(self, parent: tk.Widget, text: str, cmd) -> tk.Label:
        pal = self._pal()
        btn = tk.Label(
            parent,
            text=text,
            bg=pal["bg_btn"],
            fg=pal["text_sec"],
            font=self._font_small,
            padx=8,
            pady=3,
            cursor="hand2",
        )
        btn.bind("<Button-1>", lambda _e: cmd())
        btn.bind("<Enter>", lambda _e, w=btn: w.configure(bg=self._pal()["bg_btn_hover"], fg=self._pal()["text_pri"]))
        btn.bind("<Leave>", lambda _e, w=btn: self._restore_pill_style(w))
        self._pill_btns.append(btn)
        return btn

    def _restore_pill_style(self, btn: tk.Label) -> None:
        pal = self._pal()
        btn.configure(bg=pal["bg_btn"])
        if btn is getattr(self, "_btn_mode", None):
            self._refresh_mode_btn()
        else:
            btn.configure(fg=pal["text_sec"])

    # ------------------------------------------------------------------ Hover Tooltips
    def _bind_tooltips(self) -> None:
        FluentTooltip.bind(
            self._lbl_title,
            lambda: self._t("tip_title"),
            self._is_dark_theme,
            delay_ms=420,
        )
        FluentTooltip.bind(
            self._btn_refresh,
            lambda: self._t("tip_refresh_busy") if self._refreshing else self._t("tip_refresh"),
            self._is_dark_theme,
            delay_ms=300,
        )
        FluentTooltip.bind(
            self._btn_expand,
            lambda: self._t("tip_collapse") if self.cfg.get("expanded", False) else self._t("tip_expand"),
            self._is_dark_theme,
            delay_ms=300,
        )
        FluentTooltip.bind(
            self._btn_settings,
            lambda: self._t("tip_settings"),
            self._is_dark_theme,
            delay_ms=300,
        )
        FluentTooltip.bind(
            self._btn_pin,
            lambda: self._t("tip_pin_on") if self.cfg.get("topmost", True) else self._t("tip_pin_off"),
            self._is_dark_theme,
            delay_ms=300,
        )
        FluentTooltip.bind(
            self._btn_hide,
            lambda: self._t("tip_hide_macos" if sys.platform == "darwin" else "tip_hide"),
            self._is_dark_theme,
            delay_ms=300,
        )

        # Visual hover preview tooltips on the detail-view compact style chips
        for st, chip in self._style_chips.items():
            FluentTooltip.bind(
                chip,
                lambda s=st: f"{self._t(f'style_{s}_title')}\n{self._t(f'style_{s}_desc')}",
                self._is_dark_theme,
                delay_ms=180,
                image_provider=lambda s=st: self._get_style_preview_photo(s),
            )

        # Compact AI rows AND ring cards hover tooltips (remaining days/hours & reset times)
        for prov in ALL_PROVIDERS:
            row = self._rows[prov]
            FluentTooltip.bind(
                row["widgets"],
                lambda p=prov: self._build_compact_row_tooltip(p),
                self._is_dark_theme,
                delay_ms=260,
                anchor_widget=row["frame"],
            )
            rc = self._ring_cards[prov]
            FluentTooltip.bind(
                rc["widgets"],
                lambda p=prov: self._build_compact_row_tooltip(p),
                self._is_dark_theme,
                delay_ms=260,
                anchor_widget=rc["frame"],
            )
            cinfo = self._card_refs[prov]
            FluentTooltip.bind(cinfo["btn_up"], lambda: self._t("tip_move_up"), self._is_dark_theme, delay_ms=350)
            FluentTooltip.bind(cinfo["btn_dn"], lambda: self._t("tip_move_dn"), self._is_dark_theme, delay_ms=350)

    def _format_tooltip_bucket_line(
        self,
        label: str,
        bucket: Dict[str, Any],
        mode: str,
        now: float,
    ) -> str:
        val = bucket_display_pct(bucket, mode)
        if val is None:
            return f"• {label}: --"
        if bucket["expired"]:
            return f"• {label}: {self._t('reset_tooltip')}"
        cd = format_countdown(bucket["resets_at"], compact=False, now=now, lang=self._lang())
        dt = format_reset_datetime(bucket["resets_at"])
        if cd and dt != "-":
            return f"• {label}: {val:.1f}%  ({cd} · {dt})"
        if cd:
            return f"• {label}: {val:.1f}%  ({cd})"
        return f"• {label}: {val:.1f}%"

    def _build_compact_row_tooltip(self, prov: str) -> str:
        # Suppress redundant row hover when detail cards are already expanded right below
        if self.cfg.get("expanded", False):
            return ""

        now = time.time()
        lang = self._lang()
        mode = self._display_mode()
        mode_lbl = self._t("mode_used_word") if mode == "used" else self._t("mode_rem_word")
        full_name = PROVIDER_META[prov][0]
        pdata = self.state.get(prov) if isinstance(self.state.get(prov), dict) else {}

        lines = [f"{full_name}  ·  {self._t('mode_basis', mode=mode_lbl)}"]
        has_any = False

        wk_for_pace: Optional[Dict[str, Any]] = None
        if prov == "antigravity":
            b = resolve_agy_buckets(pdata, now)
            wk_for_pace = b["weekly_gen"] if b["weekly_gen"]["remaining_pct"] is not None else b["weekly_argon"]
            for lbl, key, optional in (
                (self._t("weekly_gen"), "weekly_gen", False),
                (self._t("weekly_argon"), "weekly_argon", True),
                (self._t("session_5h"), "session_5h", False),
                (self._t("third_party_wk"), "third_party_wk", True),
            ):
                bkt = b[key]
                if bkt["remaining_pct"] is not None:
                    has_any = True
                    lines.append(self._format_tooltip_bucket_line(lbl, bkt, mode, now))
                elif not optional:
                    lines.append(f"• {lbl}: {self._t('waiting')}")
        elif prov == "claude":
            b = resolve_claude_buckets(pdata, now)
            wk_for_pace = b["weekly_gen"]
            for lbl, key, optional in (
                (self._t("weekly_gen"), "weekly_gen", False),
                (self._t("weekly_fable"), "weekly_fable", True),
                (self._t("session_5h"), "session_5h", False),
            ):
                bkt = b[key]
                if bkt["remaining_pct"] is not None:
                    has_any = True
                    lines.append(self._format_tooltip_bucket_line(lbl, bkt, mode, now))
                elif not optional:
                    lines.append(f"• {lbl}: {self._t('waiting')}")
        else:  # codex
            wk = get_effective_bucket(pdata.get("weekly"), now)
            s5 = get_effective_bucket(pdata.get("session_5h"), now)
            wk_for_pace = wk
            for lbl, bkt in ((self._t("weekly_7d"), wk), (self._t("session_5h"), s5)):
                if bkt["remaining_pct"] is not None:
                    has_any = True
                    lines.append(self._format_tooltip_bucket_line(lbl, bkt, mode, now))
                else:
                    lines.append(f"• {lbl}: {self._t('waiting')}")

        if wk_for_pace is not None and not wk_for_pace.get("expired"):
            pace = compute_pace(
                bucket_display_pct(wk_for_pace, "used"),
                wk_for_pace.get("resets_at"),
                WEEKLY_WINDOW_SEC,
                now=now,
                mode=mode,
                lang=lang,
            )
            if pace is not None:
                lines.append(self._t("tip_pace", label=pace["label"]))

        status = self._last_refresh_status.get(prov)
        if status and not status[0] and status[1]:
            lines.append(f"⚠ {status[1]}")
        q_ts = pdata.get("quota_updated_at") or pdata.get("updated_at")
        if q_ts:
            age = format_relative_age(q_ts, now, lang=lang)
            if self._compact_style() == "slim":
                lines.append(self._t("tip_updated_slim", age=age))
            else:
                lines.append(self._t("tip_updated_dbl", age=age))
        elif not (status and not status[0]):
            lines.append(self._t("tip_click_refresh"))

        return "\n".join(lines)

    # ------------------------------------------------------------------ Fluent Context Menu & macOS Integration
    def _build_context_menu(self) -> None:
        self.root.bind("<Button-3>", self._show_context_menu)
        if sys.platform == "darwin":
            # macOS Aqua Tk maps secondary / two-finger click to Button-2 (and Ctrl+Click)
            self.root.bind("<Button-2>", self._show_context_menu)
            self.root.bind("<Control-Button-1>", self._show_context_menu)

    def _setup_macos_integration(self) -> None:
        if sys.platform != "darwin":
            return
        try:
            self.root.createcommand("tk::mac::ReopenApplication", self._show_from_tray)
            self.root.createcommand("tk::mac::ShowPreferences", lambda: self._open_settings("display"))
            self.root.createcommand("tk::mac::Quit", self._quit)
        except Exception:
            pass
        try:
            menubar = tk.Menu(self.root)
            app_menu = tk.Menu(menubar, name="apple", tearoff=0)
            app_menu.add_command(label=self._t("menu_show"), command=self._show_from_tray)
            app_menu.add_command(label=self._t("menu_refresh"), accelerator="Command-R", command=self._trigger_refresh)
            app_menu.add_separator()
            app_menu.add_command(label=self._t("menu_settings"), accelerator="Command-,", command=lambda: self._open_settings("display"))
            menubar.add_cascade(menu=app_menu)

            win_menu = tk.Menu(menubar, tearoff=0)
            win_menu.add_command(label=self._t("menu_show"), command=self._show_from_tray)
            win_menu.add_command(label=self._t("menu_hide"), accelerator="Command-H", command=self._hide_to_tray)
            win_menu.add_command(label=self._t("menu_details"), command=self._toggle_expand)
            win_menu.add_command(label=self._t("menu_topmost"), command=self._toggle_topmost)
            win_menu.add_command(label=self._t("menu_snap"), command=lambda: (self._show_from_tray(), self._snap_to_taskbar()))
            menubar.add_cascade(label="AI Usage Bar", menu=win_menu)
            self.root.configure(menu=menubar)
        except Exception:
            pass
        self.root.bind_all("<Command-r>", lambda _e: self._trigger_refresh())
        self.root.bind_all("<Command-R>", lambda _e: self._trigger_refresh())
        self.root.bind_all("<Command-comma>", lambda _e: self._open_settings("display"))
        self.root.bind_all("<Command-h>", lambda _e: self._hide_to_tray())
        self.root.bind_all("<Command-H>", lambda _e: self._hide_to_tray())
        self.root.bind_all("<Command-q>", lambda _e: self._quit())
        self.root.bind_all("<Command-Q>", lambda _e: self._quit())

    def _refresh_interval_sec(self) -> int:
        try:
            v = int(self.cfg.get("refresh_interval_sec", 180))
        except (TypeError, ValueError):
            v = 180
        return max(60, v)

    def _cycle_refresh_interval(self) -> None:
        cur = self._refresh_interval_sec()
        nxt = REFRESH_INTERVALS[0]
        for iv in REFRESH_INTERVALS:
            if iv > cur:
                nxt = iv
                break
        self.cfg["refresh_interval_sec"] = nxt
        save_config(self.cfg)

    def _toggle_notifications(self) -> None:
        self.cfg["notifications"] = not bool(self.cfg.get("notifications", True))
        save_config(self.cfg)

    def _open_fluent_menu(self, x: int, y: int, system_surface: bool = False) -> None:
        FluentTooltip.hide_active()
        visible = bool(self.cfg.get("visible", True))
        topmost = bool(self.cfg.get("topmost", True))
        expanded = bool(self.cfg.get("expanded", False))

        items: List[FluentMenuItem] = [
            FluentMenuItem(
                label=self._t("menu_refresh"),
                icon="↻",
                command=self._trigger_refresh,
            ),
            FluentMenuItem(
                label=self._t("menu_details"),
                checked=expanded,
                command=self._toggle_expand,
            ),
            FluentMenuItem(
                label=self._t("menu_topmost"),
                checked=topmost,
                command=self._toggle_topmost,
            ),
            FluentMenuItem(
                label=self._t("menu_snap"),
                icon="↙",
                command=lambda: (self._show_from_tray(), self._snap_to_taskbar()),
            ),
            FluentMenuItem(
                label=self._t("menu_hide") if visible else self._t("menu_show"),
                icon="—" if visible else "◫",
                command=self._hide_to_tray if visible else self._show_from_tray,
            ),
            FluentMenuItem(separator=True),
            FluentMenuItem(
                label=self._t("menu_trends"),
                icon="◔",
                command=lambda: self._open_settings("trends"),
            ),
            FluentMenuItem(
                label=self._t("menu_settings"),
                icon="⚙",
                command=lambda: self._open_settings("display"),
            ),
            FluentMenuItem(separator=True),
            FluentMenuItem(
                label=self._t("menu_quit"),
                icon="✕",
                danger=True,
                command=self._quit,
            ),
        ]

        force_dark = None if system_surface else self._is_dark_theme()
        FluentPopupMenu(self.root, items, x, y, system_surface=system_surface, force_dark=force_dark)

    def _show_context_menu(self, event: tk.Event) -> None:
        self._open_fluent_menu(event.x_root, event.y_root, system_surface=False)

    # ------------------------------------------------------------------ Drag & Multi-Monitor Positioning
    def _bind_drag(self, widget: tk.Widget) -> None:
        widget.bind("<ButtonPress-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_move)
        widget.bind("<ButtonRelease-1>", self._on_drag_end)

    def _on_drag_start(self, event: tk.Event) -> None:
        FluentTooltip.hide_active()
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _on_drag_move(self, event: tk.Event) -> None:
        if not self._drag_origin:
            return
        ox, oy, wx, wy = self._drag_origin
        nx = wx + (event.x_root - ox)
        ny = wy + (event.y_root - oy)
        h = self.root.winfo_height()
        self.root.geometry(f"{HUD_WIDTH}x{h}+{nx}+{ny}")

    def _on_drag_end(self, _event: tk.Event) -> None:
        if not self._drag_origin:
            return
        self._drag_origin = None
        self.cfg["x"] = self.root.winfo_x()
        self.cfg["y"] = self.root.winfo_y()
        save_config(self.cfg)

    def _position_initial(self) -> None:
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()

        x = self.cfg.get("x")
        y = self.cfg.get("y")
        if x is None or y is None:
            self._snap_to_taskbar(save=False, use_primary=True)
            return

        ix, iy = int(x), int(y)
        wl, wt, wr, wb = get_monitor_work_area_for_point(ix + HUD_WIDTH // 2, iy + h // 2)
        ix = max(wl, min(ix, wr - HUD_WIDTH))
        iy = max(wt, min(iy, wb - h))
        self.root.geometry(f"{HUD_WIDTH}x{h}+{ix}+{iy}")

    def _snap_to_taskbar(self, save: bool = True, use_primary: bool = False) -> None:
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        if use_primary:
            _wl, _wt, wr, wb = get_primary_work_area()
        else:
            cx = self.root.winfo_x() + HUD_WIDTH // 2
            cy = self.root.winfo_y() + max(h, self.root.winfo_height()) // 2
            _wl, _wt, wr, wb = get_monitor_work_area_for_point(cx, cy)
        x = wr - HUD_WIDTH - 12
        y = wb - h - 8
        self.root.geometry(f"{HUD_WIDTH}x{h}+{x}+{y}")
        if save:
            self.cfg["x"] = x
            self.cfg["y"] = y
            save_config(self.cfg)

    # ------------------------------------------------------------------ Actions
    def _enqueue_tray_action(self, action: str) -> None:
        self._action_queue.put(action)

    def _get_tray_flags(self) -> Dict[str, bool]:
        return {
            "visible": bool(self.cfg.get("visible", True)),
            "topmost": bool(self.cfg.get("topmost", True)),
            "expanded": bool(self.cfg.get("expanded", False)),
            "startup": is_startup_enabled(),
        }

    def _process_actions(self) -> None:
        try:
            while True:
                action = self._action_queue.get_nowait()
                if action.startswith("tray_menu:"):
                    parts = action.split(":")
                    if len(parts) == 3:
                        self._open_fluent_menu(int(parts[1]), int(parts[2]), system_surface=True)
                elif action == "toggle_show":
                    if self.cfg.get("visible", True):
                        self._hide_to_tray()
                    else:
                        self._show_from_tray()
                elif action == "toggle_topmost":
                    self._toggle_topmost()
                elif action == "toggle_expand":
                    self._toggle_expand()
                elif action == "snap_taskbar":
                    self._show_from_tray()
                    self._snap_to_taskbar()
                elif action == "toggle_startup":
                    self._toggle_startup()
                elif action == "refresh_done":
                    self._refreshing = False
                    if self._pending_refresh_results is not None:
                        self._last_refresh_status.update(self._pending_refresh_results)
                        self._pending_refresh_results = None
                    self._btn_refresh.configure(text="↻", fg=self._pal()["text_sec"])
                    self._last_mtime = self._get_state_mtime()
                    self.state = load_state()
                    now_ts = time.time()
                    append_history_snapshot(self.state, now_ts)
                    self._check_notifications(now_ts)
                    self._refresh_ui(force_tray=True)
                elif action == "quit":
                    self._quit()
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._process_actions)

    def _hide_to_tray(self) -> None:
        FluentTooltip.hide_active()
        self.cfg["visible"] = False
        if sys.platform == "win32":
            save_config(self.cfg)
        self.root.withdraw()

    def _show_from_tray(self) -> None:
        self.cfg["visible"] = True
        save_config(self.cfg)
        self.root.deiconify()
        self.root.lift()
        if self._hwnd:
            set_topmost_noactivate(self._hwnd, bool(self.cfg["topmost"]))

    def _toggle_topmost(self) -> None:
        self.cfg["topmost"] = not bool(self.cfg.get("topmost", True))
        save_config(self.cfg)
        self.root.attributes("-topmost", self.cfg["topmost"])
        if self._hwnd:
            set_topmost_noactivate(self._hwnd, self.cfg["topmost"])
        self._update_pin_visual()

    def _update_pin_visual(self) -> None:
        pal = self._pal()
        if self.cfg.get("topmost", True):
            self._btn_pin.configure(bg=pal["bg_main"], fg=pal["accent_agy"])
        else:
            self._btn_pin.configure(bg=pal["bg_main"], fg=pal["text_muted"])

    def _toggle_expand(self) -> None:
        FluentTooltip.hide_active()
        old_x = self.root.winfo_x()
        old_y = self.root.winfo_y()
        old_h = self.root.winfo_height()
        old_bottom = old_y + old_h
        wl, wt, wr, wb = get_monitor_work_area_for_point(old_x + HUD_WIDTH // 2, old_y + old_h // 2)
        near_bottom = (wb - old_bottom) < 160

        expanded = not bool(self.cfg.get("expanded", False))
        self.cfg["expanded"] = expanded
        if expanded:
            self._detail_frame.pack(fill="x", pady=(6, 0))
            self._btn_expand.configure(text="▴")
        else:
            self._detail_frame.pack_forget()
            self._btn_expand.configure(text="▾")

        self.root.update_idletasks()
        new_h = self.root.winfo_reqheight()
        new_x = max(wl, min(old_x, wr - HUD_WIDTH))
        new_y = max(wt, old_bottom - new_h) if near_bottom else old_y
        if new_y + new_h > wb:
            new_y = max(wt, wb - new_h - 8)
        self.root.geometry(f"{HUD_WIDTH}x{new_h}+{new_x}+{new_y}")
        self.cfg["x"] = new_x
        self.cfg["y"] = new_y
        save_config(self.cfg)
        self._refresh_ui(force_tray=False)

    def _on_opacity_change(self, val: str) -> None:
        op = round(float(val), 2)
        self.cfg["opacity"] = op
        self.root.attributes("-alpha", op)
        save_config(self.cfg)

    def _toggle_startup(self) -> None:
        try:
            set_startup_enabled(not is_startup_enabled())
        except Exception:
            pass

    def _toggle_provider(self, prov: str) -> None:
        cur = self._enabled_providers()
        order = self._provider_order()
        if prov in cur:
            if len(cur) <= 1:
                return  # Always keep at least one AI visible
            nxt = [p for p in cur if p != prov]
        else:
            nxt = [p for p in order if p in set(cur) | {prov}]
        self.cfg["enabled_providers"] = nxt
        save_config(self.cfg)
        self._refresh_provider_chips()
        self._apply_visibility_layout(resize_window=True)
        self._refresh_ui(force_tray=True)
        if prov in nxt and not (self.state.get(prov) or {}).get("updated_at"):
            self._trigger_refresh()

    def _refresh_provider_chips(self) -> None:
        pal = self._pal()
        order = self._provider_order()
        enabled = set(self._enabled_providers())
        for chip in self._provider_chips.values():
            chip.pack_forget()
        # Pack in reversed order with side="right" so left-to-right matches custom provider_order
        for prov in reversed(order):
            chip = self._provider_chips[prov]
            _full, short, accent_key, _in = PROVIDER_META[prov]
            if prov in enabled:
                chip.configure(text=f"{short} ✓", bg=pal["bg_btn_hover"], fg=pal[accent_key])
            else:
                chip.configure(text=short, bg=pal["bg_btn"], fg=pal["text_muted"])
            chip.pack(side="right", padx=(4, 0))

    def _refresh_style_chips(self) -> None:
        pal = self._pal()
        cur = self._compact_style()
        for st, chip in self._style_chips.items():
            lbl = self._t(f"style_{st}")
            if st == cur:
                chip.configure(text=f"{lbl} ✓", bg=pal["bg_btn_hover"], fg=pal["accent_agy"])
            else:
                chip.configure(text=lbl, bg=pal["bg_btn"], fg=pal["text_muted"])

    def _apply_visibility_layout(self, resize_window: bool = True) -> None:
        enabled = self._enabled_providers()
        style = self._compact_style()
        old_x = self.root.winfo_x()
        old_y = self.root.winfo_y()
        old_h = self.root.winfo_height()
        old_bottom = old_y + old_h
        wl, wt, wr, wb = get_monitor_work_area_for_point(old_x + HUD_WIDTH // 2, old_y + old_h // 2)
        near_bottom = resize_window and (wb - old_bottom) < 160

        # Hide all compact & detail widgets before re-packing in custom order
        self._rows_container.pack_forget()
        self._ring_container.pack_forget()
        for prov in ALL_PROVIDERS:
            self._rows[prov]["frame"].pack_forget()
            self._ring_cards[prov]["frame"].grid_forget()
            self._detail_cards[prov].pack_forget()

        if style == "ring":
            self._ring_container.pack(fill="x")
            for c in range(3):
                self._ring_container.grid_columnconfigure(c, weight=0, uniform="")
            for idx, prov in enumerate(enabled):
                self._ring_container.grid_columnconfigure(idx, weight=1, uniform="ring_card")
                pad_r = 5 if idx < len(enabled) - 1 else 0
                self._ring_cards[prov]["frame"].grid(row=0, column=idx, sticky="nsew", padx=(0, pad_r))
        else:
            self._rows_container.pack(fill="x")
            is_dual = style == "dual"
            for idx, prov in enumerate(enabled):
                row = self._rows[prov]
                if is_dual:
                    row["bar"].configure(height=6)
                    row["sub"].configure(cursor="")
                    for w in row["row1_widgets"]:
                        w.grid()
                else:
                    row["bar"].configure(height=8)
                    row["sub"].configure(cursor="hand2")
                    for w in row["row1_widgets"]:
                        w.grid_remove()
                pad_b = 4 if idx < len(enabled) - 1 else 0
                row["frame"].pack(fill="x", pady=(0, pad_b))

        # Detail cards always in custom provider order; toggle ▲/▼ visibility when >= 2 AIs
        multi = len(enabled) >= 2
        for idx, prov in enumerate(enabled):
            self._detail_cards[prov].pack(fill="x", pady=(0, 4))
            cinfo = self._card_refs[prov]
            cinfo["btn_up"].pack_forget()
            cinfo["btn_dn"].pack_forget()
            if multi:
                if idx > 0:
                    cinfo["btn_up"].pack(side="left", padx=(4, 0))
                if idx < len(enabled) - 1:
                    cinfo["btn_dn"].pack(side="left", padx=(2 if idx > 0 else 4, 0))

        if resize_window:
            self.root.update_idletasks()
            new_h = self.root.winfo_reqheight()
            new_x = max(wl, min(old_x, wr - HUD_WIDTH))
            new_y = max(wt, old_bottom - new_h) if near_bottom else old_y
            if new_y + new_h > wb:
                new_y = max(wt, wb - new_h - 8)
            self.root.geometry(f"{HUD_WIDTH}x{new_h}+{new_x}+{new_y}")
            self.cfg["x"] = new_x
            self.cfg["y"] = new_y
            save_config(self.cfg)

    def _display_mode(self) -> str:
        m = str(self.cfg.get("display_mode") or "used").lower()
        return "remaining" if m == "remaining" else "used"

    def _toggle_display_mode(self) -> None:
        self.cfg["display_mode"] = "remaining" if self._display_mode() == "used" else "used"
        save_config(self.cfg)
        self._refresh_mode_btn()
        self._refresh_ui(force_tray=True)

    def _refresh_mode_btn(self) -> None:
        pal = self._pal()
        is_used = self._display_mode() == "used"
        self._btn_mode.configure(
            text=self._t("btn_mode_used") if is_used else self._t("btn_mode_rem"),
            fg=pal["accent_claude"] if is_used else pal["accent_agy"],
        )

    def _toggle_auto_refresh(self) -> None:
        self.cfg["auto_refresh"] = not bool(self.cfg.get("auto_refresh", True))
        save_config(self.cfg)
        if self.cfg["auto_refresh"]:
            self._trigger_refresh()

    def _trigger_refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self._paused_for_idle = False
        self._last_auto_refresh = time.time()
        self._btn_refresh.configure(text="…", fg=self._pal()["accent_agy"])
        targets = self._enabled_providers()
        lang = self._lang()

        def _worker() -> None:
            results: Dict[str, Tuple[bool, str]] = {}
            try:
                results = refresh_all_silent(targets, lang=lang)
            except Exception:
                pass
            finally:
                self._pending_refresh_results = results
                self._action_queue.put("refresh_done")

        threading.Thread(target=_worker, name="QuotaRefreshThread", daemon=True).start()

    def _auto_refresh_tick(self) -> None:
        interval = self._refresh_interval_sec()
        if self.cfg.get("auto_refresh", True) and not self._refreshing:
            idle_sec = get_idle_seconds()
            if idle_sec >= IDLE_PAUSE_SEC:
                self._paused_for_idle = True
            else:
                if self._paused_for_idle:
                    self._paused_for_idle = False
                    if time.time() - self._last_auto_refresh >= 60:
                        self._trigger_refresh()
                elif time.time() - self._last_auto_refresh >= interval:
                    self._trigger_refresh()
        self.root.after(15000, self._auto_refresh_tick)

    def _reconnect_hooks(self) -> Tuple[bool, bool]:
        ok1, _m1 = install_claude_hook()
        ok2, _m2 = install_agy_hook()
        return ok1, ok2

    def _quit(self) -> None:
        FluentTooltip.hide_active()
        if self._settings_dlg is not None and not self._settings_dlg._closed:
            self._settings_dlg.close()
        try:
            self.hotkey_mgr.stop()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        self.root.destroy()

    # ------------------------------------------------------------------ Threshold & Reset Notifications
    def _seed_notification_state(self, now: float) -> None:
        snap = collect_notify_snapshot(self.state, now, lang=self._lang())
        self._prev_notify_snap = snap
        warn_pct = int(self.cfg.get("notify_warn_pct", 80))
        crit_pct = int(self.cfg.get("notify_crit_pct", 95))
        for (prov, slot), info in snap.items():
            ck = _cycle_key(info.get("resets_at"))
            used = float(info["used_pct"])
            if info.get("expired"):
                self._notified_milestones.add((prov, slot, ck, "reset"))
            else:
                if warn_pct > 0 and used >= warn_pct:
                    self._notified_milestones.add((prov, slot, ck, ("warn", warn_pct)))
                if crit_pct > 0 and used >= crit_pct:
                    self._notified_milestones.add((prov, slot, ck, ("crit", crit_pct)))

    def _check_notifications(self, now: float) -> None:
        lang = self._lang()
        cur_snap = collect_notify_snapshot(self.state, now, lang=lang)
        enabled = set(self._enabled_providers())
        noti_on = bool(self.cfg.get("notifications", True))
        warn_pct = int(self.cfg.get("notify_warn_pct", 80))
        crit_pct = int(self.cfg.get("notify_crit_pct", 95))
        on_reset = bool(self.cfg.get("notify_on_reset", True))
        include_5h = bool(self.cfg.get("notify_include_5h", True))

        if len(self._notified_milestones) > 250:
            self._notified_milestones.clear()

        if noti_on and hasattr(self, "tray"):
            for key, cur in cur_snap.items():
                prov, slot = key
                if prov not in enabled:
                    continue
                if slot == "session_5h" and not include_5h:
                    continue
                prev = self._prev_notify_snap.get(key)
                label = cur["label"]
                used = float(cur["used_pct"])
                exp = bool(cur["expired"])
                ck = _cycle_key(cur.get("resets_at"))
                prev_used = float(prev["used_pct"]) if prev else 0.0
                prev_exp = bool(prev["expired"]) if prev else False
                prev_resets = prev.get("resets_at") if prev else None
                prev_ck = _cycle_key(prev_resets)

                if on_reset and prev is not None and prev_used >= 20.0:
                    if not prev_exp and exp:
                        mk = (prov, slot, prev_ck, "reset")
                        if mk not in self._notified_milestones:
                            self._notified_milestones.add(mk)
                            self.tray.notify(
                                self._t("noti_reset_title", label=label),
                                self._t("noti_reset_body"),
                                warning=False,
                            )
                    elif (
                        not exp
                        and used <= 5.0
                        and cur.get("resets_at") is not None
                        and prev_resets is not None
                        and float(cur["resets_at"]) > float(prev_resets) + 600.0
                    ):
                        mk_old = (prov, slot, prev_ck, "reset")
                        mk_new = (prov, slot, ck, "reset_new")
                        if mk_old not in self._notified_milestones and mk_new not in self._notified_milestones:
                            self._notified_milestones.add(mk_new)
                            self.tray.notify(
                                self._t("noti_reset_title", label=label),
                                self._t("noti_reset_new_body"),
                                warning=False,
                            )

                if not exp:
                    cd = format_countdown(cur.get("resets_at"), compact=False, now=now, lang=lang)
                    cd_hint = self._t("noti_until_reset", cd=cd) if cd else ""
                    if crit_pct > 0 and used >= crit_pct:
                        mk_c = (prov, slot, ck, ("crit", crit_pct))
                        if mk_c not in self._notified_milestones and (prev is None or prev_used < crit_pct):
                            if warn_pct > 0:
                                self._notified_milestones.add((prov, slot, ck, ("warn", warn_pct)))
                            self._notified_milestones.add(mk_c)
                            body = self._t("noti_crit_body", th=crit_pct)
                            self.tray.notify(
                                self._t("noti_crit_title", label=label, pct=used),
                                f"{body} · {cd_hint}".strip(" ·"),
                                warning=True,
                            )
                    elif warn_pct > 0 and used >= warn_pct:
                        mk_w = (prov, slot, ck, ("warn", warn_pct))
                        if mk_w not in self._notified_milestones and (prev is None or prev_used < warn_pct):
                            self._notified_milestones.add(mk_w)
                            body = self._t("noti_warn_body", th=warn_pct, rem=max(0.0, 100.0 - used))
                            self.tray.notify(
                                self._t("noti_warn_title", label=label, pct=used),
                                f"{body} · {cd_hint}".strip(" ·"),
                                warning=True,
                            )

        self._prev_notify_snap = cur_snap

    # ------------------------------------------------------------------ Data & Refresh Loop
    def _get_state_mtime(self) -> float:
        try:
            return STATE_PATH.stat().st_mtime
        except OSError:
            return 0.0

    def _tick(self) -> None:
        now = time.time()

        self._theme_poll_counter += 1
        if self._theme_poll_counter >= 5:
            self._theme_poll_counter = 0
            if self._theme_mode() == "auto" and self._is_dark_theme() != self._last_applied_dark:
                self._apply_theme()

        self._codex_poll_counter += 1
        if self._codex_poll_counter >= 5 and "codex" in self._enabled_providers():
            self._codex_poll_counter = 0
            try:
                latest_cdx = read_latest_codex_session_limits()
                cur_cdx = self.state.get("codex") if isinstance(self.state.get("codex"), dict) else {}
                cur_ts = float(cur_cdx.get("updated_at") or 0.0)
                if latest_cdx and float(latest_cdx.get("updated_at") or 0.0) > cur_ts:
                    update_provider_state("codex", latest_cdx)
            except Exception:
                pass

        mtime = self._get_state_mtime()
        changed = mtime != self._last_mtime
        if changed:
            self._last_mtime = mtime
            self.state = load_state()
            append_history_snapshot(self.state, now)

        self._check_notifications(now)
        self._refresh_ui(force_tray=changed)
        self.root.after(1000, self._tick)

    def _topmost_guard(self) -> None:
        if (
            self.cfg.get("visible", True)
            and self.cfg.get("topmost", True)
            and FluentPopupMenu._active is None
            and FluentTooltip._active_win is None
            and (self._settings_dlg is None or self._settings_dlg._closed)
            and self._hwnd
        ):
            set_topmost_noactivate(self._hwnd, True)
        self.root.after(2500, self._topmost_guard)

    def _pace_marker_for(self, bucket: Dict[str, Any], window_sec: float, now: float, mode: str) -> Optional[float]:
        if not self.cfg.get("show_pace_marker", True) or bucket.get("expired"):
            return None
        used = bucket_display_pct(bucket, "used")
        pace = compute_pace(used, bucket.get("resets_at"), window_sec, now=now, mode=mode, lang=self._lang())
        return pace["marker_pct"] if pace else None

    def _update_metric_slot(
        self,
        slot: Dict[str, Any],
        bucket: Dict[str, Any],
        now: float,
        mode: str,
        empty_hint: Optional[str] = None,
        window_sec: float = WEEKLY_WINDOW_SEC,
    ) -> None:
        pal = self._pal()
        lang = self._lang()
        accent = pal[slot["accent_key"]]
        val = bucket_display_pct(bucket, mode)
        exp = bucket["expired"]
        col = quota_color(val, accent, exp, mode=mode, pal=pal)
        if val is None:
            slot["pct"].configure(text="--%", fg=pal["text_muted"])
            slot["sub"].configure(text=empty_hint if empty_hint is not None else self._t("waiting"), fg=pal["text_muted"])
            draw_rounded_bar(slot["bar"], None, col, width=DETAIL_BAR_WIDTH, height=4, track_color=pal["bg_track"])
            return

        slot["pct"].configure(text=self._t("reset_short") if exp else format_pct_detail(val, mode), fg=col)
        cd = format_countdown(bucket["resets_at"], compact=True, now=now, lang=lang)
        dt = format_reset_datetime(bucket["resets_at"])
        if exp:
            sub = self._t("reset_done")
        elif cd and dt != "-":
            sub = f"{cd} ({dt})"
        elif cd:
            sub = cd
        else:
            sub = ""
        slot["sub"].configure(text=sub, fg=pal["expired"] if exp else pal["text_muted"])
        bar_val = (0.0 if mode == "used" else 100.0) if exp else val
        marker_pct = self._pace_marker_for(bucket, window_sec, now, mode)
        draw_rounded_bar(
            slot["bar"], bar_val, col, width=DETAIL_BAR_WIDTH, height=4,
            track_color=pal["bg_track"], pace_marker_pct=marker_pct, marker_color=pal["text_pri"],
        )

    def _update_compact_provider_views(
        self,
        prov: str,
        primary_bkt: Dict[str, Any],
        s5_bkt: Dict[str, Any],
        model_badge: Optional[Tuple[str, float, bool, str]],
        empty_sub: str,
        now: float,
        mode: str,
        n_enabled: int,
    ) -> Tuple[Optional[float], str]:
        """Update both row view (dual/slim) and ring view for one provider; return tray tuple."""
        pal = self._pal()
        lang = self._lang()
        is_used = mode == "used"
        style = self._compact_style()
        slim_metric = self._slim_sub_metric()
        _full, _short, accent_key, inner_key = PROVIDER_META[prov]
        accent = pal[accent_key]
        inner_accent = pal[inner_key]
        reset_word = self._t("reset_short")

        p_wk = bucket_display_pct(primary_bkt, mode)
        exp_wk = bool(primary_bkt["expired"])
        col_wk = quota_color(p_wk, accent, exp_wk, mode=mode, pal=pal)
        disp_wk = None if p_wk is None else ((0.0 if is_used else 100.0) if exp_wk else p_wk)

        p_5h = bucket_display_pct(s5_bkt, mode)
        exp_5h = bool(s5_bkt["expired"])
        col_5h = quota_color(p_5h, inner_accent, exp_5h, mode=mode, pal=pal)
        disp_5h = None if p_5h is None else ((0.0 if is_used else 100.0) if exp_5h else p_5h)

        wk_marker = self._pace_marker_for(primary_bkt, WEEKLY_WINDOW_SEC, now, mode)
        s5_marker = self._pace_marker_for(s5_bkt, SESSION_5H_WINDOW_SEC, now, mode)
        m_col = pal["text_pri"]

        # ---------------- Row view ("dual" & "slim") ----------------
        row = self._rows[prov]
        if p_wk is None:
            row["pct"].configure(text="--%", fg=pal["text_muted"])
            row["sub"].configure(text=empty_sub, fg=pal["text_muted"])
            if style == "slim":
                draw_stacked_dual_bar(
                    row["bar"], None, col_wk, disp_5h, col_5h, width=102,
                    track_color=pal["bg_track"], top_pace_pct=None, bot_pace_pct=s5_marker, marker_color=m_col,
                )
            else:
                draw_rounded_bar(row["bar"], None, col_wk, width=102, height=6, track_color=pal["bg_track"])
            tray_info: Tuple[Optional[float], str] = (None, empty_sub)
        else:
            row["pct"].configure(
                text=reset_word if exp_wk else format_pct_compact(p_wk, mode),
                fg=col_wk if exp_wk or is_warn_level(p_wk, mode) else pal["text_pri"],
            )

            # Decide right-hand badge text for top row
            if style == "slim" and slim_metric == "5h" and p_5h is not None:
                sub_txt = f"5h {reset_word}" if exp_5h else f"5h {format_pct_compact(p_5h, mode)}"
                sub_col = col_5h if exp_5h or is_warn_level(p_5h, mode) else pal["text_sec"]
            elif model_badge is not None:
                b_prefix, b_val, b_exp, b_acc = model_badge
                sub_txt = f"{b_prefix} {reset_word}" if b_exp else f"{b_prefix} {format_pct_compact(b_val, mode)}"
                sub_col = quota_color(b_val, b_acc, b_exp, mode=mode, pal=pal)
            elif p_5h is not None and style == "slim":
                sub_txt = f"5h {reset_word}" if exp_5h else f"5h {format_pct_compact(p_5h, mode)}"
                sub_col = col_5h if exp_5h or is_warn_level(p_5h, mode) else pal["text_sec"]
            else:
                cd_wk = format_countdown(primary_bkt["resets_at"], compact=True, now=now, lang=lang)
                sub_txt = cd_wk or self._t("days_7")
                sub_col = pal["expired"] if exp_wk else pal["text_sec"]

            row["sub"].configure(text=sub_txt, fg=sub_col)

            if style == "slim":
                draw_stacked_dual_bar(
                    row["bar"], disp_wk, col_wk, disp_5h, col_5h, width=102,
                    track_color=pal["bg_track"], top_pace_pct=wk_marker, bot_pace_pct=s5_marker, marker_color=m_col,
                )
            else:
                draw_rounded_bar(
                    row["bar"], disp_wk, col_wk, width=102, height=6,
                    track_color=pal["bg_track"], pace_marker_pct=wk_marker, marker_color=m_col,
                )

            # Tray tooltip summary
            parts = [f"{self._t('tray_wk_prefix')} {p_wk:.0f}%"]
            if p_5h is not None:
                parts.append(f"5h {p_5h:.0f}%")
            if model_badge is not None:
                parts.append(f"{model_badge[0]} {model_badge[1]:.0f}%")
            tray_info = (disp_wk, " · ".join(parts))

        # Dual mode row 1 (5-hour dedicated line)
        if style == "dual":
            if p_5h is None:
                row["pct_5h"].configure(text="--%", fg=pal["text_muted"])
                row["sub_5h"].configure(text="", fg=pal["text_muted"])
                draw_rounded_bar(row["bar_5h"], None, col_5h, width=102, height=3, track_color=pal["bg_track"])
            else:
                row["pct_5h"].configure(
                    text=reset_word if exp_5h else format_pct_compact(p_5h, mode),
                    fg=col_5h if exp_5h or is_warn_level(p_5h, mode) else pal["text_sec"],
                )
                cd_5h = format_countdown(s5_bkt["resets_at"], compact=True, now=now, lang=lang)
                row["sub_5h"].configure(
                    text=self._t("reset_done_short") if exp_5h else (cd_5h or "5h"),
                    fg=pal["expired"] if exp_5h else pal["text_muted"],
                )
                draw_rounded_bar(
                    row["bar_5h"], disp_5h, col_5h, width=102, height=3,
                    track_color=pal["bg_track"], pace_marker_pct=s5_marker, marker_color=m_col,
                )

        # ---------------- Ring view ("ring") ----------------
        if style == "ring":
            rc = self._ring_cards[prov]
            if n_enabled == 1:
                r_size, ow, iw, c_font = 84, 7, 4, ui_font("num", 12, "bold")
            elif n_enabled == 2:
                r_size, ow, iw, c_font = 70, 6, 4, ui_font("num", 10, "bold")
            else:
                r_size, ow, iw, c_font = 60, 5, 3, ui_font("num", 9, "bold")

            cv = rc["canvas"]
            if int(cv.cget("width")) != r_size:
                cv.configure(width=r_size, height=r_size)

            cache_key = (
                r_size,
                ow,
                iw,
                pal["bg_track"],
                None if disp_wk is None else round(disp_wk, 1),
                col_wk,
                None if disp_5h is None else round(disp_5h, 1),
                col_5h,
            )
            cached = self._ring_photo_cache.get(prov)
            if cached is not None and cached[0] == cache_key:
                photo = cached[1]
            else:
                png = render_dual_ring_png(
                    size=r_size,
                    outer_pct=disp_wk,
                    outer_col=col_wk,
                    inner_pct=disp_5h,
                    inner_col=col_5h,
                    track_col=pal["bg_track"],
                    outer_w=ow,
                    inner_w=iw,
                )
                photo = png_bytes_to_photoimage(png, master=self.root)
                self._ring_photo_cache[prov] = (cache_key, photo)

            rc["photo"] = photo
            cv.delete("all")
            cv.create_image(r_size // 2, r_size // 2, image=photo)
            if p_wk is None:
                center_txt = "--%"
                center_col = pal["text_muted"]
            elif exp_wk:
                center_txt = reset_word
                center_col = pal["expired"]
            else:
                center_txt = format_pct_compact(p_wk, mode)
                center_col = col_wk if is_warn_level(p_wk, mode) else pal["text_pri"]
            cv.create_text(r_size // 2, r_size // 2, text=center_txt, fill=center_col, font=c_font)

            # Ring card bottom sub-text
            if p_wk is None and p_5h is None:
                ring_sub = empty_sub
            else:
                s5_str = (f"5h {reset_word}" if exp_5h else f"5h {p_5h:.0f}%") if p_5h is not None else "5h --"
                if model_badge is not None:
                    mb_str = f"{model_badge[0]} {model_badge[1]:.0f}%"
                    ring_sub = f"{s5_str}\n{mb_str}" if n_enabled >= 3 else f"{s5_str} · {mb_str}"
                else:
                    cd_s5 = format_countdown(s5_bkt["resets_at"], compact=True, now=now, lang=lang) if p_5h is not None else ""
                    if cd_s5 and not exp_5h:
                        ring_sub = f"{s5_str}\n{cd_s5}" if n_enabled >= 3 else f"{s5_str} · {cd_s5}"
                    else:
                        ring_sub = s5_str
            rc["sub"].configure(text=ring_sub, fg=pal["text_sec"] if p_wk is not None else pal["text_muted"])

        return tray_info

    def _diagnostic_hint(self, prov: str, fallback: str) -> str:
        st = self._last_refresh_status.get(prov)
        if st and not st[0] and st[1]:
            return st[1]
        return fallback

    def _refresh_ui(self, force_tray: bool = False) -> None:
        now = time.time()
        pal = self._pal()
        lang = self._lang()
        mode = self._display_mode()
        is_used = mode == "used"
        enabled = self._enabled_providers()
        n_enabled = len(enabled)
        self._lbl_title.configure(text=self._t("hud_title_used") if is_used else self._t("hud_title_rem"))

        # ---------------- Antigravity ----------------
        agy_data = self.state.get("antigravity") if isinstance(self.state.get("antigravity"), dict) else {}
        agy_b = resolve_agy_buckets(agy_data, now)
        agy_wk = agy_b["weekly_gen"]
        agy_ar = agy_b["weekly_argon"]
        agy_5h = agy_b["session_5h"]
        agy_3p = agy_b["third_party_wk"]

        primary_a = agy_wk if agy_wk["remaining_pct"] is not None else agy_ar
        p_a = bucket_display_pct(primary_a, mode)
        ar_val = bucket_display_pct(agy_ar, mode)
        agy_badge = (
            ("Ar", ar_val, bool(agy_ar["expired"]), pal["accent_argon"])
            if (ar_val is not None and agy_wk["remaining_pct"] is not None)
            else None
        )
        tray_agy = self._update_compact_provider_views(
            "antigravity", primary_a, agy_5h, agy_badge, self._t("waiting"), now, mode, n_enabled
        )

        agy_age = format_relative_age(agy_data.get("updated_at"), now, lang=lang)
        self._agy_meta.configure(
            text=f"{self._t('src_agy')} · {agy_age}" if agy_data.get("updated_at") else self._t("waiting_conn")
        )
        self._update_metric_slot(self._agy_slots["weekly_gen"], agy_wk, now, mode, empty_hint=self._t("waiting"), window_sec=WEEKLY_WINDOW_SEC)
        self._update_metric_slot(self._agy_slots["weekly_argon"], agy_ar, now, mode, empty_hint=self._t("none_avail"), window_sec=WEEKLY_WINDOW_SEC)
        self._update_metric_slot(self._agy_slots["session_5h"], agy_5h, now, mode, empty_hint=self._t("waiting"), window_sec=SESSION_5H_WINDOW_SEC)

        agy_foot_parts = []
        if agy_data.get("model"):
            agy_foot_parts.append(str(agy_data["model"]))
        p_3p = bucket_display_pct(agy_3p, mode)
        if p_3p is not None:
            agy_foot_parts.append(f"3P {p_3p:.0f}%")
        agy_pace = compute_pace(bucket_display_pct(primary_a, "used"), primary_a.get("resets_at"), WEEKLY_WINDOW_SEC, now=now, mode=mode, lang=lang)
        if agy_pace and not primary_a["expired"]:
            agy_foot_parts.append(agy_pace["short"])
        if p_a is None:
            agy_foot_parts = [self._diagnostic_hint("antigravity", self._t("hint_agy"))]
        elif not agy_foot_parts:
            agy_foot_parts.append(self._t("hint_agy"))
        self._agy_footer.configure(text=truncate_text(" · ".join(agy_foot_parts), 40))

        # ---------------- Claude ----------------
        cld_data = self.state.get("claude") if isinstance(self.state.get("claude"), dict) else {}
        cld_b = resolve_claude_buckets(cld_data, now)
        cld_wk = cld_b["weekly_gen"]
        cld_fb = cld_b["weekly_fable"]
        cld_5h = cld_b["session_5h"]

        p_c = bucket_display_pct(cld_wk, mode)
        fb_val = bucket_display_pct(cld_fb, mode)
        cld_badge = (
            ("Fb", fb_val, bool(cld_fb["expired"]), pal["accent_fable"])
            if fb_val is not None
            else None
        )
        cld_empty = self._t("waiting_resp") if cld_data.get("updated_at") else self._t("waiting")
        tray_cld = self._update_compact_provider_views(
            "claude", cld_wk, cld_5h, cld_badge, cld_empty, now, mode, n_enabled
        )

        cld_qts = cld_data.get("quota_updated_at") or cld_data.get("updated_at")
        cld_age = format_relative_age(cld_qts, now, lang=lang)
        cld_src = self._t("src_cld_auto") if cld_data.get("source") == "claude_usage_auto" else self._t("src_cld_hook")
        self._cld_meta.configure(
            text=f"{cld_src} · {cld_age}" if cld_qts else self._t("waiting_conn")
        )
        self._update_metric_slot(
            self._cld_slots["weekly_gen"], cld_wk, now, mode,
            empty_hint=self._t("after_first_chat") if cld_data.get("updated_at") else self._t("waiting"),
            window_sec=WEEKLY_WINDOW_SEC,
        )
        self._update_metric_slot(
            self._cld_slots["weekly_fable"], cld_fb, now, mode,
            empty_hint=self._t("cli_unavailable") if p_c is not None else self._t("waiting"),
            window_sec=WEEKLY_WINDOW_SEC,
        )
        self._update_metric_slot(
            self._cld_slots["session_5h"], cld_5h, now, mode,
            empty_hint=self._t("waiting"), window_sec=SESSION_5H_WINDOW_SEC,
        )

        cld_status = self._last_refresh_status.get("claude")
        cld_err = bool(cld_status and not cld_status[0] and cld_status[1])
        cld_foot_parts = []
        if cld_err:
            cld_foot_parts.append(f"⚠ {cld_status[1]}")
        elif p_c is None:
            cld_foot_parts.append(self._diagnostic_hint("claude", self._t("hint_cld")))
        else:
            if cld_data.get("model"):
                m = str(cld_data["model"])
                if cld_data.get("context_used_pct") is not None:
                    m += f" · Ctx {cld_data['context_used_pct']:.0f}%"
                cld_foot_parts.append(m)
            cld_pace = compute_pace(bucket_display_pct(cld_wk, "used"), cld_wk.get("resets_at"), WEEKLY_WINDOW_SEC, now=now, mode=mode, lang=lang)
            if cld_pace and not cld_wk["expired"]:
                cld_foot_parts.append(cld_pace["short"])
            if not cld_foot_parts:
                cld_foot_parts.append(self._t("hint_cld_sync"))
        self._cld_footer.configure(
            text=truncate_text(" · ".join(cld_foot_parts), 42),
            fg=pal["warn"] if cld_err else pal["text_muted"],
        )

        # ---------------- Codex ----------------
        cdx_data = self.state.get("codex") if isinstance(self.state.get("codex"), dict) else {}
        cdx_wk = get_effective_bucket(cdx_data.get("weekly"), now)
        cdx_5h = get_effective_bucket(cdx_data.get("session_5h"), now)

        primary_x = cdx_wk if cdx_wk["remaining_pct"] is not None else cdx_5h
        p_x = bucket_display_pct(primary_x, mode)
        tray_cdx = self._update_compact_provider_views(
            "codex", primary_x, cdx_5h, None, self._t("waiting"), now, mode, n_enabled
        )

        cdx_age = format_relative_age(cdx_data.get("updated_at"), now, lang=lang)
        cdx_src = self._t("src_cdx_log") if cdx_data.get("source") == "codex_session_log" else self._t("src_cdx_auto")
        self._cdx_meta.configure(
            text=f"{cdx_src} · {cdx_age}" if cdx_data.get("updated_at") else self._t("waiting_conn")
        )
        self._update_metric_slot(self._cdx_slots["weekly"], cdx_wk, now, mode, empty_hint=self._t("waiting"), window_sec=WEEKLY_WINDOW_SEC)
        self._update_metric_slot(self._cdx_slots["session_5h"], cdx_5h, now, mode, empty_hint=self._t("waiting"), window_sec=SESSION_5H_WINDOW_SEC)

        cdx_foot_parts = []
        if p_x is None:
            cdx_foot_parts.append(self._diagnostic_hint("codex", self._t("hint_cdx")))
        else:
            if cdx_data.get("plan_tier"):
                cdx_foot_parts.append(str(cdx_data["plan_tier"]))
            cdx_pace = compute_pace(bucket_display_pct(cdx_wk, "used"), cdx_wk.get("resets_at"), WEEKLY_WINDOW_SEC, now=now, mode=mode, lang=lang)
            if cdx_pace and not cdx_wk["expired"]:
                cdx_foot_parts.append(cdx_pace["short"])
            if not cdx_foot_parts:
                cdx_foot_parts.append(self._t("hint_cdx"))
        self._cdx_footer.configure(text=truncate_text(" · ".join(cdx_foot_parts), 40))

        # Tray icon & tooltip (strictly follows enabled providers in custom order!)
        tray_map = {
            "antigravity": ("AGY", tray_agy),
            "claude": ("Claude", tray_cld),
            "codex": ("Codex", tray_cdx),
        }
        tray_bars: list[tuple[str, Optional[float]]] = []
        mode_word = self._t("mode_used_word") if is_used else self._t("mode_rem_word")
        tip_lines = [f"AI Usage Bar ({mode_word})"]
        for prov in enabled:
            lbl, (bar_val, tip_val) = tray_map[prov]
            tray_bars.append((prov, bar_val))
            tip_lines.append(f"{lbl}: {tip_val}")

        tooltip = "\n".join(tip_lines)
        sig = (
            mode,
            lang,
            tuple((p, None if v is None else round(v)) for p, v in tray_bars),
            tooltip,
        )
        if force_tray or sig != self._last_tray_sig:
            self._last_tray_sig = sig
            self.tray.update(tray_bars, tooltip, mode=mode)

    def run(self) -> None:
        self.root.mainloop()


def run_uninstall_ui() -> int:
    enable_dpi_awareness()
    cfg = load_config()
    lang = resolve_lang(str(cfg.get("language") or "auto"))
    root = tk.Tk()
    root.withdraw()
    ans = messagebox.askyesno(
        tr(lang, "uninst_title"),
        tr(lang, "uninst_confirm"),
    )
    if ans:
        perform_clean_uninstall(BASE_DIR)
        messagebox.showinfo(tr(lang, "uninst_title"), tr(lang, "uninst_done"))
    root.destroy()
    return 0


def main() -> int:
    if "--uninstall" in sys.argv:
        return run_uninstall_ui()

    enable_dpi_awareness()
    mutex = acquire_single_instance_mutex()
    if mutex is None:
        return 0
    cleanup_stale_temp_files()
    try:
        app = QuotaHUDApp()
        app.run()
    except Exception:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / "hud_error.log").write_text(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}]\n{traceback.format_exc()}\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        raise
    finally:
        try:
            if sys.platform == "win32" and _kernel32 is not None:
                _kernel32.CloseHandle(mutex)
            elif hasattr(mutex, "close"):
                mutex.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
