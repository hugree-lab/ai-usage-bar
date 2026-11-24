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
from preview_art import (
    png_bytes_to_photoimage,
    render_dual_ring_png,
    render_scenic_emblem_png,
    render_scenic_titlebar_png,
    render_hare_sprite_png,
    render_silver_metal_titlebar_png,
    render_traffic_dots_png,
    render_paper_boat_png,
    render_paper_plane_png,
    render_rpg_hero_png,
    render_runner_sprite_png,
    render_style_preview_png,
    render_toolbar_icon_png,
    render_tortoise_sprite_png,
    render_retro01_badge_png,
    render_retro01_titlebar_png,
)
from settings_dialog import SettingsDialog
from state_store import (
    ALL_PROVIDERS,
    BASE_DIR,
    COMPACT_STYLES,
    DATA_DIR,
    PRIMARY_METRICS,
    SESSION_5H_WINDOW_SEC,
    STATE_PATH,
    UI_THEMES,
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
HUD_WIDTH = 352 if sys.platform == "darwin" else 322
DETAIL_BAR_WIDTH = HUD_WIDTH - 48
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

# Structural geometry & chrome spec for each of the 11 distinct UI Design Themes
UI_THEME_SPECS: Dict[str, Dict[str, Any]] = {
    "modern": {
        "bar_style": "pill",
        "ring_style": "smooth",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "flat",
        "indicator": "dot",
        "mono_ui": False,
        "title_prefix": "",
        "name_brackets": False,
        "titlebar": False,
        "pri_bar_h": 6,
        "sec_bar_h": 3,
        "sec_urg_h": 5,
    },
    "liquid_glass": {
        "bar_style": "glass",
        "ring_style": "glass",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "glass_rim",
        "indicator": "capsule",
        "mono_ui": False,
        "title_prefix": "",
        "name_brackets": False,
        "titlebar": False,
        "dot_chrome": "glass",
        "pri_bar_h": 8,
        "sec_bar_h": 4,
        "sec_urg_h": 6,
    },
    "silver_metal": {
        "bar_style": "gel",
        "ring_style": "gel",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "glass_rim",
        "indicator": "capsule",
        "mono_ui": False,
        "title_prefix": "",
        "name_brackets": False,
        "titlebar": True,
        "dot_chrome": "gel",
        "pri_bar_h": 10,
        "sec_bar_h": 6,
        "sec_urg_h": 8,
    },
    "bliss_01": {
        "bar_style": "bliss_01",
        "ring_style": "bliss_01",
        "border_w": 1,
        "outer_border_w": 3,
        "shadow": False,
        "hairline_list": False,
        "chrome": "r01_gloss",
        "indicator": "dot",
        "mono_ui": False,
        "title_prefix": "",
        "name_brackets": False,
        "titlebar": True,
        "pri_bar_h": 11,
        "sec_bar_h": 7,
        "sec_urg_h": 9,
    },
    "retro_95": {
        "bar_style": "retro_95",
        "ring_style": "retro_95",
        "border_w": 0,
        "outer_border_w": 2,
        "shadow": False,
        "hairline_list": False,
        "chrome": "bevel3d",
        "indicator": "bevel_sq",
        "mono_ui": False,
        "title_prefix": "",
        "name_brackets": False,
        "titlebar": True,
        "pri_bar_h": 10,
        "sec_bar_h": 6,
        "sec_urg_h": 8,
    },
    "brutal": {
        "bar_style": "brutal",
        "ring_style": "outlined",
        "border_w": 2,
        "outer_border_w": 2,
        "shadow": True,
        "hairline_list": False,
        "chrome": "flat",
        "indicator": "sq_out",
        "mono_ui": False,
        "title_prefix": "",
        "name_brackets": False,
        "titlebar": False,
        "pri_bar_h": 9,
        "sec_bar_h": 5,
        "sec_urg_h": 7,
    },
    "paper_sky": {
        "bar_style": "paper_sky",
        "ring_style": "paper_sky",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "glass_rim",
        "indicator": "meadow_leaf",
        "mono_ui": False,
        "title_prefix": "SKY · ",
        "name_brackets": False,
        "titlebar": True,
        "pri_bar_h": 20,
        "sec_bar_h": 10,
        "sec_urg_h": 12,
    },
    "paper_sea": {
        "bar_style": "paper_sea",
        "ring_style": "paper_sea",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "glass_rim",
        "indicator": "sea_drop",
        "mono_ui": False,
        "title_prefix": "SEA · ",
        "name_brackets": False,
        "titlebar": True,
        "pri_bar_h": 20,
        "sec_bar_h": 10,
        "sec_urg_h": 12,
    },
    "rpg": {
        "bar_style": "rpg",
        "ring_style": "rpg_orb",
        "border_w": 2,
        "outer_border_w": 2,
        "shadow": False,
        "hairline_list": False,
        "chrome": "rpg_box",
        "indicator": "rpg_hero",
        "mono_ui": True,
        "title_prefix": "QUEST · ",
        "name_brackets": False,
        "titlebar": False,
        "pri_bar_h": 9,
        "sec_bar_h": 6,
        "sec_urg_h": 8,
    },
    "runner": {
        "bar_style": "runner",
        "ring_style": "track",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "flat",
        "indicator": "dot",
        "mono_ui": False,
        "title_prefix": "RACE · ",
        "name_brackets": False,
        "titlebar": False,
        "pri_bar_h": 20,
        "sec_bar_h": 10,
        "sec_urg_h": 12,
    },
    "thermo": {
        "bar_style": "thermo",
        "ring_style": "thermo_dial",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "glass_rim",
        "indicator": "capsule",
        "mono_ui": False,
        "title_prefix": "TEMP · ",
        "name_brackets": False,
        "titlebar": False,
        "pri_bar_h": 14,
        "sec_bar_h": 8,
        "sec_urg_h": 10,
    },
    "battery": {
        "bar_style": "battery",
        "ring_style": "battery_ring",
        "border_w": 1,
        "outer_border_w": 1,
        "shadow": False,
        "hairline_list": False,
        "chrome": "cyber_top",
        "indicator": "vbar",
        "mono_ui": True,
        "title_prefix": "PWR · ",
        "name_brackets": False,
        "titlebar": False,
        "pri_bar_h": 12,
        "sec_bar_h": 7,
        "sec_urg_h": 9,
    },
    "speedo": {
        "bar_style": "speedo",
        "ring_style": "speedo_dial",
        "border_w": 1,
        "outer_border_w": 2,
        "shadow": False,
        "hairline_list": False,
        "chrome": "cyber_top",
        "indicator": "diamond",
        "mono_ui": True,
        "title_prefix": "RPM · ",
        "name_brackets": False,
        "titlebar": False,
        "pri_bar_h": 10,
        "sec_bar_h": 6,
        "sec_urg_h": 8,
    },
}

# 9 distinct UI Design Themes — each with bold, unmistakable Dark AND Light palettes (18 looks total)
THEME_PALETTES: Dict[str, Dict[str, Dict[str, str]]] = {
    "modern": {
        "dark": {
            "bg_main": "#141417",
            "bg_card": "#1C1C21",
            "bg_track": "#2A2A32",
            "bg_btn": "#25252C",
            "bg_btn_hover": "#32323C",
            "border": "#2E2E37",
            "shadow": "#09090B",
            "bevel_hi": "#484856",
            "text_pri": "#F4F4F6",
            "text_sec": "#A1A1AA",
            "text_muted": "#71717A",
            "accent_agy": "#6CA6F8",
            "accent_agy_5h": "#5CC8E6",
            "accent_argon": "#B497FA",
            "accent_claude": "#E0876A",
            "accent_claude_5h": "#EDA985",
            "accent_fable": "#EC7EB4",
            "accent_codex": "#46C296",
            "accent_codex_5h": "#52D1BE",
            "good": "#4ADE80",
            "warn": "#F59E0B",
            "low": "#F87171",
            "expired": "#93A3F8",
            "pin_pill": "#1E2E47",
            "pin_pill_hover": "#273E61",
        },
        "light": {
            "bg_main": "#F3F3F5",
            "bg_card": "#FFFFFF",
            "bg_track": "#E4E4E9",
            "bg_btn": "#E8E8EE",
            "bg_btn_hover": "#DCDCE4",
            "border": "#D4D4DC",
            "shadow": "#C5C5CF",
            "bevel_hi": "#FFFFFF",
            "text_pri": "#18181B",
            "text_sec": "#52525B",
            "text_muted": "#71717A",
            "accent_agy": "#2563EB",
            "accent_agy_5h": "#0284C7",
            "accent_argon": "#7C3AED",
            "accent_claude": "#C96442",
            "accent_claude_5h": "#D97745",
            "accent_fable": "#DB2777",
            "accent_codex": "#059669",
            "accent_codex_5h": "#0D9488",
            "good": "#059669",
            "warn": "#D97706",
            "low": "#DC2626",
            "expired": "#4F46E5",
            "pin_pill": "#DCEAFE",
            "pin_pill_hover": "#C7DFFD",
        },
    },
    "paper_sky": {
        "dark": {
            # Storybook Watercolor Starry Night Sky & Firefly Meadow (calm twilight indigo, zero eye strain!)
            "bg_main": "#131926",
            "bg_card": "#1B2336",
            "bg_track": "#141D33",
            "bg_btn": "#242F47",
            "bg_btn_hover": "#2F3E5C",
            "border": "#3F547A",
            "shadow": "#090D16",
            "bevel_hi": "#7D9BC9",
            "titlebar": "#1B2846",
            "text_pri": "#F4F7FC",
            "text_sec": "#AFC1DE",
            "text_muted": "#7A8FB0",
            "accent_agy": "#7CC6FE",
            "accent_agy_5h": "#67E8F9",
            "accent_argon": "#C4B5FD",
            "accent_claude": "#F4A261",
            "accent_claude_5h": "#FDE68A",
            "accent_fable": "#F9A8D4",
            "accent_codex": "#6AD4A5",
            "accent_codex_5h": "#86EFAC",
            "good": "#6AD4A5",
            "warn": "#F5B841",
            "low": "#F47272",
            "expired": "#A5B4FC",
            "pin_pill": "#1E3454",
            "pin_pill_hover": "#284670",
        },
        "light": {
            # Storybook Watercolor Summer Watercolor Sky, Fluffy Clouds & Sunlit Green Meadow!
            "bg_main": "#DCEEFB",
            "bg_card": "#F7FBFF",
            "bg_track": "#C9E6FA",
            "bg_btn": "#D2E8F8",
            "bg_btn_hover": "#BEDEF5",
            "border": "#9CC8E8",
            "shadow": "#86B5D8",
            "bevel_hi": "#FFFFFF",
            "titlebar": "#9ED5FA",
            "text_pri": "#163047",
            "text_sec": "#426380",
            "text_muted": "#7291AD",
            "accent_agy": "#2B8AE0",
            "accent_agy_5h": "#1AA6D4",
            "accent_argon": "#7C63D6",
            "accent_claude": "#EA7B4F",
            "accent_claude_5h": "#E5A032",
            "accent_fable": "#D95F96",
            "accent_codex": "#3EA86B",
            "accent_codex_5h": "#249E89",
            "good": "#3EA86B",
            "warn": "#D98A1C",
            "low": "#DC4848",
            "expired": "#5A67D8",
            "pin_pill": "#C2E3FC",
            "pin_pill_hover": "#A8D7FA",
        },
    },
    "paper_sea": {
        "dark": {
            # Storybook Watercolor Moonlit Night Sea & Warm Sea-Train Lanterns!
            "bg_main": "#111A22",
            "bg_card": "#182430",
            "bg_track": "#132330",
            "bg_btn": "#203140",
            "bg_btn_hover": "#2B4154",
            "border": "#3A5B70",
            "shadow": "#080E14",
            "bevel_hi": "#6C9BB3",
            "titlebar": "#152D40",
            "text_pri": "#F0F8FA",
            "text_sec": "#A4C4D4",
            "text_muted": "#6E91A3",
            "accent_agy": "#56CFE1",
            "accent_agy_5h": "#72EFDD",
            "accent_argon": "#B8A9F8",
            "accent_claude": "#F4A261",
            "accent_claude_5h": "#FDE68A",
            "accent_fable": "#F490B8",
            "accent_codex": "#5EEAD4",
            "accent_codex_5h": "#80ED99",
            "good": "#5EEAD4",
            "warn": "#F5B841",
            "low": "#F47272",
            "expired": "#93C5FD",
            "pin_pill": "#19394A",
            "pin_pill_hover": "#224D63",
        },
        "light": {
            # Storybook Watercolor Clear Turquoise Ocean, Sunlit Ripples & Coastal Breeze!
            "bg_main": "#DFF1F2",
            "bg_card": "#F6FCFC",
            "bg_track": "#CDE9ED",
            "bg_btn": "#D3ECEE",
            "bg_btn_hover": "#BEE2E6",
            "border": "#94CBD1",
            "shadow": "#7BB4BC",
            "bevel_hi": "#FFFFFF",
            "titlebar": "#83D9E3",
            "text_pri": "#12323B",
            "text_sec": "#3E6670",
            "text_muted": "#6E95A0",
            "accent_agy": "#1796AD",
            "accent_agy_5h": "#24B0B8",
            "accent_argon": "#7C63D6",
            "accent_claude": "#E87A54",
            "accent_claude_5h": "#E59D32",
            "accent_fable": "#D65C94",
            "accent_codex": "#2BA67D",
            "accent_codex_5h": "#1D9E96",
            "good": "#2BA67D",
            "warn": "#D98A1C",
            "low": "#DC4848",
            "expired": "#4E6CE0",
            "pin_pill": "#BFE8EC",
            "pin_pill_hover": "#A3DFE6",
        },
    },
    "rpg": {
        "dark": {
            # Cozy Velvet Midnight JRPG Menu (soft royal navy-slate + antique gold double border!)
            "bg_main": "#161C2C",
            "bg_card": "#1F283E",
            "bg_track": "#111624",
            "bg_btn": "#293552",
            "bg_btn_hover": "#364569",
            "border": "#C9AE6E",
            "shadow": "#0A0E18",
            "bevel_hi": "#53658F",
            "rpg_hp": "#E85555",
            "rpg_mp": "#4DA8FF",
            "text_pri": "#F5F2EA",
            "text_sec": "#BAC5DE",
            "text_muted": "#8392B3",
            "accent_agy": "#60A5FA",
            "accent_agy_5h": "#38BDF8",
            "accent_argon": "#B794F4",
            "accent_claude": "#F09058",
            "accent_claude_5h": "#EAB354",
            "accent_fable": "#E879A8",
            "accent_codex": "#4ADE80",
            "accent_codex_5h": "#34D399",
            "good": "#4ADE80",
            "warn": "#EAB308",
            "low": "#F05656",
            "expired": "#93A3F8",
            "pin_pill": "#2A3656",
            "pin_pill_hover": "#374770",
        },
        "light": {
            # Crisp Fantasy Kingdom Storybook Ivory + Royal Sapphire & Gold RPG Trim (no dusty beige!)
            "bg_main": "#EEF2F7",
            "bg_card": "#FDFEFE",
            "bg_track": "#DDE5F0",
            "bg_btn": "#E2E8F2",
            "bg_btn_hover": "#D2DCEB",
            "border": "#3D5A99",
            "shadow": "#2B4070",
            "bevel_hi": "#D4A94E",
            "rpg_hp": "#DC2626",
            "rpg_mp": "#0284C7",
            "text_pri": "#192338",
            "text_sec": "#445473",
            "text_muted": "#7282A1",
            "accent_agy": "#2563EB",
            "accent_agy_5h": "#0284C7",
            "accent_argon": "#7C3AED",
            "accent_claude": "#D9531E",
            "accent_claude_5h": "#D97706",
            "accent_fable": "#C0267D",
            "accent_codex": "#15803D",
            "accent_codex_5h": "#0D9488",
            "good": "#15803D",
            "warn": "#B45309",
            "low": "#C81E1E",
            "expired": "#4F46E5",
            "pin_pill": "#DCE6F7",
            "pin_pill_hover": "#C4D6F2",
        },
    },
    "runner": {
        "dark": {
            # Nike Run Club / Night Asphalt + Authentic Clay Running Track (zero green terminal!)
            "bg_main": "#151618",
            "bg_card": "#1E2024",
            "bg_track": "#4D2C24",
            "bg_btn": "#272A30",
            "bg_btn_hover": "#333740",
            "border": "#363A42",
            "shadow": "#090A0C",
            "bevel_hi": "#D6BDB4",
            "text_pri": "#F4F5F7",
            "text_sec": "#A6ABB6",
            "text_muted": "#747A86",
            "accent_agy": "#38BDF8",
            "accent_agy_5h": "#2DD4BF",
            "accent_argon": "#B794F4",
            "accent_claude": "#FF7A45",
            "accent_claude_5h": "#FBB040",
            "accent_fable": "#F472B6",
            "accent_codex": "#4ADE80",
            "accent_codex_5h": "#6EE7B7",
            "good": "#4ADE80",
            "warn": "#F59E0B",
            "low": "#F87171",
            "expired": "#93A3F8",
            "pin_pill": "#263344",
            "pin_pill_hover": "#314259",
        },
        "light": {
            # Daylight Olympic Clay Running Track!
            "bg_main": "#F3E9E0",
            "bg_card": "#FFFDF9",
            "bg_track": "#DFC0A8",
            "bg_btn": "#EBDCD0",
            "bg_btn_hover": "#DFCCB9",
            "border": "#CFAF95",
            "shadow": "#B59378",
            "bevel_hi": "#FFFFFF",
            "text_pri": "#261810",
            "text_sec": "#634736",
            "text_muted": "#947460",
            "accent_agy": "#2563EB",
            "accent_agy_5h": "#0891B2",
            "accent_argon": "#7C3AED",
            "accent_claude": "#D9481E",
            "accent_claude_5h": "#EA8A1A",
            "accent_fable": "#DB2777",
            "accent_codex": "#15803D",
            "accent_codex_5h": "#0D9488",
            "good": "#15803D",
            "warn": "#C26D0A",
            "low": "#DC2626",
            "expired": "#4F46E5",
            "pin_pill": "#FBDAC4",
            "pin_pill_hover": "#F5C5A6",
        },
    },
    "thermo": {
        "dark": {
            # Calm Dark Frosted Glass Laboratory Instrument!
            "bg_main": "#12161C",
            "bg_card": "#1A2029",
            "bg_track": "#27313F",
            "bg_btn": "#222A36",
            "bg_btn_hover": "#2D3848",
            "border": "#364559",
            "shadow": "#080A0E",
            "bevel_hi": "#6C84A0",
            "text_pri": "#EEF4FA",
            "text_sec": "#9DB0C4",
            "text_muted": "#6B7F94",
            "accent_agy": "#38BDF8",
            "accent_agy_5h": "#22D3EE",
            "accent_argon": "#A78BFA",
            "accent_claude": "#F59E0B",
            "accent_claude_5h": "#FBBF24",
            "accent_fable": "#F472B6",
            "accent_codex": "#2DD4BF",
            "accent_codex_5h": "#5EEAD4",
            "good": "#34D399",
            "warn": "#F59E0B",
            "low": "#EF4444",
            "expired": "#818CF8",
            "pin_pill": "#1B334B",
            "pin_pill_hover": "#244463",
        },
        "light": {
            # Frosted Ice-Lab Clinical Thermometer!
            "bg_main": "#E5F0F8",
            "bg_card": "#FAFDFF",
            "bg_track": "#D4E5F2",
            "bg_btn": "#DCEAF5",
            "bg_btn_hover": "#CBE0F0",
            "border": "#96BDD9",
            "shadow": "#84ABC7",
            "bevel_hi": "#FFFFFF",
            "text_pri": "#0E2233",
            "text_sec": "#385670",
            "text_muted": "#6685A1",
            "accent_agy": "#0284C7",
            "accent_agy_5h": "#0891B2",
            "accent_argon": "#6D28D9",
            "accent_claude": "#EA580C",
            "accent_claude_5h": "#D97706",
            "accent_fable": "#DB2777",
            "accent_codex": "#0D9488",
            "accent_codex_5h": "#059669",
            "good": "#059669",
            "warn": "#D97706",
            "low": "#DC2626",
            "expired": "#4F46E5",
            "pin_pill": "#CBE8FA",
            "pin_pill_hover": "#B2DCF7",
        },
    },
    "battery": {
        "dark": {
            # Matte Anodized Gunmetal Power Cell Pack!
            "bg_main": "#151719",
            "bg_card": "#1E2125",
            "bg_track": "#2B3036",
            "bg_btn": "#262A30",
            "bg_btn_hover": "#333941",
            "border": "#48515B",
            "shadow": "#090A0B",
            "bevel_hi": "#4ADE80",
            "text_pri": "#F2F4F6",
            "text_sec": "#A6B0BA",
            "text_muted": "#737D87",
            "accent_agy": "#38BDF8",
            "accent_agy_5h": "#22D3EE",
            "accent_argon": "#B794F4",
            "accent_claude": "#F59E0B",
            "accent_claude_5h": "#FBBF24",
            "accent_fable": "#F472B6",
            "accent_codex": "#4ADE80",
            "accent_codex_5h": "#86EFAC",
            "good": "#4ADE80",
            "warn": "#F59E0B",
            "low": "#F87171",
            "expired": "#818CF8",
            "pin_pill": "#1E3829",
            "pin_pill_hover": "#284B37",
        },
        "light": {
            # Brushed Silver-Mint Energy Pack!
            "bg_main": "#E4EFE9",
            "bg_card": "#F7FCF9",
            "bg_track": "#D4E4DC",
            "bg_btn": "#DCEAE2",
            "bg_btn_hover": "#CBE0D4",
            "border": "#8EB39E",
            "shadow": "#7A9E8A",
            "bevel_hi": "#16A34A",
            "text_pri": "#10241A",
            "text_sec": "#385947",
            "text_muted": "#658775",
            "accent_agy": "#0284C7",
            "accent_agy_5h": "#0891B2",
            "accent_argon": "#7C3AED",
            "accent_claude": "#D97706",
            "accent_claude_5h": "#EA580C",
            "accent_fable": "#DB2777",
            "accent_codex": "#16A34A",
            "accent_codex_5h": "#0D9488",
            "good": "#16A34A",
            "warn": "#CA8A04",
            "low": "#DC2626",
            "expired": "#4F46E5",
            "pin_pill": "#C9F0D8",
            "pin_pill_hover": "#B0E6C5",
        },
    },
    "speedo": {
        "dark": {
            # Matte Carbon Sports-Car Cockpit Tachometer!
            "bg_main": "#131316",
            "bg_card": "#1C1C21",
            "bg_track": "#2C2C33",
            "bg_btn": "#26262D",
            "bg_btn_hover": "#34343D",
            "border": "#3E3E48",
            "shadow": "#08080A",
            "bevel_hi": "#F4F4F7",
            "text_pri": "#F5F5F7",
            "text_sec": "#A8A8B3",
            "text_muted": "#747480",
            "accent_agy": "#38BDF8",
            "accent_agy_5h": "#22D3EE",
            "accent_argon": "#B794F4",
            "accent_claude": "#FF5C35",
            "accent_claude_5h": "#F59E0B",
            "accent_fable": "#F472B6",
            "accent_codex": "#34D399",
            "accent_codex_5h": "#5EEAD4",
            "good": "#34D399",
            "warn": "#F59E0B",
            "low": "#EF4444",
            "expired": "#818CF8",
            "pin_pill": "#3B1E22",
            "pin_pill_hover": "#52282E",
        },
        "light": {
            # Classic White-Face Sports GT Instrument Dial!
            "bg_main": "#EBE8E4",
            "bg_card": "#FFFFFF",
            "bg_track": "#DDD8D2",
            "bg_btn": "#E2DDD7",
            "bg_btn_hover": "#D4CEC6",
            "border": "#9E948E",
            "shadow": "#8A807A",
            "bevel_hi": "#141414",
            "text_pri": "#1A1414",
            "text_sec": "#524644",
            "text_muted": "#827573",
            "accent_agy": "#1D4ED8",
            "accent_agy_5h": "#0284C7",
            "accent_argon": "#7C3AED",
            "accent_claude": "#E03A1E",
            "accent_claude_5h": "#D97706",
            "accent_fable": "#DB2777",
            "accent_codex": "#059669",
            "accent_codex_5h": "#0D9488",
            "good": "#059669",
            "warn": "#D97706",
            "low": "#DC2626",
            "expired": "#4F46E5",
            "pin_pill": "#FAD7D4",
            "pin_pill_hover": "#F5BEB9",
        },
    },
    "liquid_glass": {
        "dark": {
            # Modern Liquid Glass (Midnight Frosted Crystal + Specular Top Rim!)
            "bg_main": "#141823",
            "bg_card": "#1D2332",
            "bg_track": "#2A3247",
            "bg_btn": "#242B3D",
            "bg_btn_hover": "#313B54",
            "border": "#394663",
            "shadow": "#090C12",
            "bevel_hi": "#7F96C2",
            "text_pri": "#F5F8FF",
            "text_sec": "#A9B6D1",
            "text_muted": "#7281A0",
            "accent_agy": "#5AC8FA",
            "accent_agy_5h": "#64D2FF",
            "accent_argon": "#BF5AF2",
            "accent_claude": "#FF8A65",
            "accent_claude_5h": "#FFAB73",
            "accent_fable": "#FF6B9D",
            "accent_codex": "#30D158",
            "accent_codex_5h": "#5EEAD4",
            "good": "#30D158",
            "warn": "#FFD60A",
            "low": "#FF453A",
            "expired": "#8E9BFF",
            "pin_pill": "#1E3552",
            "pin_pill_hover": "#28476E",
        },
        "light": {
            # Modern Liquid Glass (Daylight Crystal Mist + Pure White Specular Rim!)
            "bg_main": "#E7EEF8",
            "bg_card": "#F8FBFF",
            "bg_track": "#D8E4F3",
            "bg_btn": "#E1EAF6",
            "bg_btn_hover": "#D2E0F2",
            "border": "#C4D3E8",
            "shadow": "#B5C6DC",
            "bevel_hi": "#FFFFFF",
            "text_pri": "#101828",
            "text_sec": "#475467",
            "text_muted": "#7A89A0",
            "accent_agy": "#007AFF",
            "accent_agy_5h": "#32ADE6",
            "accent_argon": "#AF52DE",
            "accent_claude": "#FF5E3A",
            "accent_claude_5h": "#FF9500",
            "accent_fable": "#FF2D55",
            "accent_codex": "#28CD41",
            "accent_codex_5h": "#00C7BE",
            "good": "#28CD41",
            "warn": "#FF9500",
            "low": "#FF3B30",
            "expired": "#5856D6",
            "pin_pill": "#D6EAFF",
            "pin_pill_hover": "#C0DFFF",
        },
    },
    "silver_metal": {
        "dark": {
            # Dark Brushed Titanium Metal + Glossy Gel!
            "bg_main": "#1C1E23",
            "bg_card": "#262930",
            "bg_track": "#17191E",
            "bg_btn": "#30343D",
            "bg_btn_hover": "#3D424E",
            "border": "#424854",
            "shadow": "#0D0E12",
            "bevel_hi": "#687080",
            "titlebar": "#2A2E37",
            "text_pri": "#F2F4F8",
            "text_sec": "#B6BCC8",
            "text_muted": "#828896",
            "accent_agy": "#3CA1FF",
            "accent_agy_5h": "#56CCF2",
            "accent_argon": "#B983FF",
            "accent_claude": "#F28B50",
            "accent_claude_5h": "#F5B041",
            "accent_fable": "#F472B6",
            "accent_codex": "#45D17B",
            "accent_codex_5h": "#5EEAD4",
            "good": "#45D17B",
            "warn": "#F5B041",
            "low": "#FF5F56",
            "expired": "#93A3F8",
            "pin_pill": "#233C5C",
            "pin_pill_hover": "#2E4F78",
        },
        "light": {
            # Classic Brushed Metal Brushed Aluminum Silver + Glossy Glossy Gel Blue!
            "bg_main": "#E2E5EA",
            "bg_card": "#F8FAFC",
            "bg_track": "#D6DCE4",
            "bg_btn": "#DADEE5",
            "bg_btn_hover": "#CBD0DA",
            "border": "#AEB5C2",
            "shadow": "#8F96A3",
            "bevel_hi": "#FFFFFF",
            "titlebar": "#D4D8DF",
            "text_pri": "#1D2026",
            "text_sec": "#4E5460",
            "text_muted": "#7A818F",
            "accent_agy": "#1B84F0",
            "accent_agy_5h": "#1AA6E8",
            "accent_argon": "#7C4DFF",
            "accent_claude": "#E06832",
            "accent_claude_5h": "#E89128",
            "accent_fable": "#D63384",
            "accent_codex": "#27B858",
            "accent_codex_5h": "#17A2B8",
            "good": "#27B858",
            "warn": "#D9820B",
            "low": "#E03E36",
            "expired": "#4E5BF2",
            "pin_pill": "#CFE4FC",
            "pin_pill_hover": "#B8D6FA",
        },
    },
    "bliss_01": {
        "dark": {
            # Retro 2001 midnight slate noir Dark Gloss!
            "bg_main": "#212328",
            "bg_card": "#2B2E35",
            "bg_track": "#161922",
            "bg_btn": "#343842",
            "bg_btn_hover": "#424754",
            "border": "#484F5E",
            "frame_border": "#263042",
            "shadow": "#101114",
            "bevel_hi": "#5E7FB5",
            "titlebar": "#1E2636",
            "xp_btn": "#323D52",
            "xp_btn_hover": "#43526E",
            "xp_pin_on": "#2F9635",
            "xp_pin_hover": "#3CB544",
            "retro_close": "#D94432",
            "xp_close_hover": "#F05946",
            "retro_bar": "#3FD146",
            "text_pri": "#F2F4F8",
            "text_sec": "#B8C0D0",
            "text_muted": "#848E9F",
            "accent_agy": "#4DA3FF",
            "accent_agy_5h": "#38BDF8",
            "accent_argon": "#B794F4",
            "accent_claude": "#E87A24",
            "accent_claude_5h": "#F5A53B",
            "accent_fable": "#F472B6",
            "accent_codex": "#3FD146",
            "accent_codex_5h": "#5EEAD4",
            "good": "#3FD146",
            "warn": "#F59E0B",
            "low": "#F05246",
            "expired": "#93A3F8",
            "pin_pill": "#2D4C85",
            "pin_pill_hover": "#3960A6",
        },
        "light": {
            # Retro 2001 Glossy Blue (3px Blue Frame + Glossy Blue Bar + Red X + Lime Green Blocks)!
            "bg_main": "#ECE9D8",
            "bg_card": "#FFFFFF",
            "bg_track": "#FFFFFF",
            "bg_btn": "#E2DEC9",
            "bg_btn_hover": "#D5D0B6",
            "border": "#C5C2B4",
            "frame_border": "#0054E3",
            "shadow": "#8C897C",
            "bevel_hi": "#6BB0FF",
            "titlebar": "#0054E3",
            "xp_btn": "#266CEB",
            "xp_btn_hover": "#3D85FF",
            "xp_pin_on": "#35A82B",
            "xp_pin_hover": "#46C43B",
            "retro_close": "#E0432D",
            "xp_close_hover": "#F25A44",
            "retro_bar": "#2ED12E",
            "text_pri": "#141414",
            "text_sec": "#3E434D",
            "text_muted": "#6B7280",
            "accent_agy": "#0054E3",
            "accent_agy_5h": "#1D78EA",
            "accent_argon": "#6D46C7",
            "accent_claude": "#E56A1E",
            "accent_claude_5h": "#E89219",
            "accent_fable": "#CC3377",
            "accent_codex": "#2ED12E",
            "accent_codex_5h": "#1BA866",
            "good": "#2ED12E",
            "warn": "#D97706",
            "low": "#D62828",
            "expired": "#3B5BDB",
            "pin_pill": "#2D77F0",
            "pin_pill_hover": "#478BF5",
        },
    },
    "retro_95": {
        "dark": {
            # NeXTSTEP / SGI Dark Workstation 3D Bevels!
            "bg_main": "#25272D",
            "bg_card": "#31343C",
            "bg_track": "#1B1D22",
            "bg_btn": "#3A3E48",
            "bg_btn_hover": "#484D59",
            "border": "#14161A",
            "shadow": "#111317",
            "bevel_hi": "#565B69",
            "titlebar": "#1E3A68",
            "text_pri": "#EEF0F6",
            "text_sec": "#B6BCCB",
            "text_muted": "#838A9C",
            "accent_agy": "#5AA9FF",
            "accent_agy_5h": "#4FD1C5",
            "accent_argon": "#B794F4",
            "accent_claude": "#FF875B",
            "accent_claude_5h": "#F6AD55",
            "accent_fable": "#F687B3",
            "accent_codex": "#48BB78",
            "accent_codex_5h": "#68D391",
            "good": "#48BB78",
            "warn": "#ECC94B",
            "low": "#FC8181",
            "expired": "#90CDF4",
            "pin_pill": "#2A508E",
            "pin_pill_hover": "#3563AD",
        },
        "light": {
            # Classic Classic 1995 Silver 3D Raised Bevels!
            "bg_main": "#C0C0C0",
            "bg_card": "#D4D0C8",
            "bg_track": "#FFFFFF",
            "bg_btn": "#D4D0C8",
            "bg_btn_hover": "#E2DFD7",
            "border": "#6B6B6B",
            "shadow": "#585858",
            "bevel_hi": "#FFFFFF",
            "titlebar": "#0A246A",
            "text_pri": "#000000",
            "text_sec": "#2E2E2E",
            "text_muted": "#595959",
            "accent_agy": "#000080",
            "accent_agy_5h": "#006699",
            "accent_argon": "#660099",
            "accent_claude": "#B83B1D",
            "accent_claude_5h": "#CC6600",
            "accent_fable": "#A61C58",
            "accent_codex": "#007A5E",
            "accent_codex_5h": "#008080",
            "good": "#007A3D",
            "warn": "#B86E00",
            "low": "#C80000",
            "expired": "#000080",
            "pin_pill": "#3A5EA8",
            "pin_pill_hover": "#4B72C2",
        },
    },
    "brutal": {
        "dark": {
            # Editorial Dark Neo-Brutal (Matte Charcoal + Crisp Off-White 2px Ink Borders + Hard Black Shadows)!
            "bg_main": "#19191D",
            "bg_card": "#232329",
            "bg_track": "#121215",
            "bg_btn": "#2E2E36",
            "bg_btn_hover": "#3B3B45",
            "border": "#E5E1D6",
            "shadow": "#070709",
            "bevel_hi": "#E5E1D6",
            "text_pri": "#F7F5EE",
            "text_sec": "#BDBAB0",
            "text_muted": "#85827A",
            "accent_agy": "#52B8FF",
            "accent_agy_5h": "#4FD1C5",
            "accent_argon": "#C49BFF",
            "accent_claude": "#FF7252",
            "accent_claude_5h": "#F5A623",
            "accent_fable": "#F472B6",
            "accent_codex": "#45D994",
            "accent_codex_5h": "#7CEBB5",
            "good": "#45D994",
            "warn": "#F5C242",
            "low": "#F55B64",
            "expired": "#9BA8FF",
            "pin_pill": "#2A3647",
            "pin_pill_hover": "#36465C",
        },
        "light": {
            # Comic Paper Neo-Brutal (Warm Cream + Jet-Black 2px Borders + Hard Offset Shadows)!
            "bg_main": "#F5F0E4",
            "bg_card": "#FFFFFF",
            "bg_track": "#EAE4D6",
            "bg_btn": "#ECE6D8",
            "bg_btn_hover": "#DFD7C5",
            "border": "#141414",
            "shadow": "#141414",
            "bevel_hi": "#141414",
            "text_pri": "#111111",
            "text_sec": "#383836",
            "text_muted": "#66645E",
            "accent_agy": "#2563EB",
            "accent_agy_5h": "#0891B2",
            "accent_argon": "#7C3AED",
            "accent_claude": "#F04E23",
            "accent_claude_5h": "#EA8A1A",
            "accent_fable": "#DB2777",
            "accent_codex": "#109856",
            "accent_codex_5h": "#0D9488",
            "good": "#109856",
            "warn": "#D97706",
            "low": "#DC2626",
            "expired": "#4F46E5",
            "pin_pill": "#FFE36E",
            "pin_pill_hover": "#FFD633",
        },
    },
}

# Backwards-compatible default alias
PALETTES: Dict[str, Dict[str, str]] = THEME_PALETTES["modern"]

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
        return f"⚠\uFE0E{pct:.0f}%"
    return f"{pct:.0f}%"


def format_pct_detail(pct: float, mode: str) -> str:
    if is_crit_level(pct, mode):
        return f"⚠\uFE0E{pct:.1f}%"
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


def _mix_hex(c1: str, c2: str, ratio: float) -> str:
    h1, h2 = c1.lstrip("#"), c2.lstrip("#")
    r1, g1, b1 = int(h1[0:2], 16), int(h1[2:4], 16), int(h1[4:6], 16)
    r2, g2, b2 = int(h2[0:2], 16), int(h2[2:4], 16), int(h2[4:6], 16)
    r = int(round(r1 + (r2 - r1) * ratio))
    g = int(round(g1 + (g2 - g1) * ratio))
    b = int(round(b1 + (b2 - b1) * ratio))
    return f"#{r:02x}{g:02x}{b:02x}"


def draw_rounded_bar(
    canvas: tk.Canvas,
    pct: Optional[float],
    fill_color: str,
    width: int,
    height: int = 5,
    track_color: str = "#252C3D",
    pace_marker_pct: Optional[float] = None,
    marker_color: Optional[str] = None,
    bar_style: str = "pill",
    border_color: str = "#2E2E37",
    highlight_color: str = "#FFFFFF",
    runner_photo: Optional[Any] = None,
    tortoise_photo: Optional[Any] = None,
    is_secondary: bool = False,
) -> None:
    sig = (
        None if pct is None else round(pct, 1),
        fill_color,
        width,
        height,
        track_color,
        None if pace_marker_pct is None else round(pace_marker_pct, 1),
        marker_color,
        bar_style,
        border_color,
        highlight_color,
        id(runner_photo) if runner_photo is not None else 0,
        id(tortoise_photo) if tortoise_photo is not None else 0,
        is_secondary,
    )
    if getattr(canvas, "_last_bar_sig", None) == sig:
        return
    canvas._last_bar_sig = sig  # type: ignore[attr-defined]
    canvas.delete("all")
    w = width
    h = height

    if bar_style == "rpg":
        # Classic RPG framed HP (red/crimson) & MP (sky-blue) game gauge with bright top shine
        bar_c = fill_color
        canvas.create_rectangle(0, 0, w - 1, h - 1, fill=track_color, outline=border_color, width=1)
        if pct is not None and pct > 0.0:
            clamped = max(0.0, min(100.0, pct))
            fw = max(3, int(round((w - 2) * (clamped / 100.0))))
            fx1 = min(w - 1, 1 + fw)
            canvas.create_rectangle(1, 1, fx1, h - 1, fill=bar_c, outline="")
            if h >= 5 and fx1 > 3:
                canvas.create_line(2, 2, fx1 - 1, 2, fill=highlight_color, width=1)
        # Pixel divider notches at 25/50/75%
        for frac in (0.25, 0.5, 0.75):
            tx = int(round(w * frac))
            canvas.create_line(tx, 1, tx, h - 1, fill=border_color, width=1)
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(2, min(w - 3, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 1, mx + 2, h - 1, fill=marker_color, outline="")
        return

    if bar_style == "paper_sky":
        # Storybook Watercolor Summer Sky & Rolling Green Meadow (Dark: Starry Night!) + Gliding Paper Airplane!
        is_dk = int(track_color.lstrip("#")[0:2], 16) < 70
        _rounded_rect(canvas, 0, 0, w, h, 3, fill=track_color, outline="")
        # Soft 2-band watercolor sky gradient at top
        sky_top = "#0F182D" if is_dk else "#9ED4FA"
        if h >= 12:
            canvas.create_rectangle(0, 0, w, max(4, h // 2 - 1), fill=sky_top, outline="")
        # Soft rolling green meadow hill along bottom edge + tiny wildflowers / fireflies
        hill_c = "#213834" if is_dk else "#7DC482"
        hill_hi = "#2B4A44" if is_dk else "#9ED99C"
        if h >= 14:
            canvas.create_oval(-14, h - 6, int(w * 0.62), h + 10, fill=hill_hi, outline="")
            canvas.create_oval(int(w * 0.35), h - 5, w + 14, h + 10, fill=hill_c, outline="")
            for fx, fc in ((0.16, "#FEF08A" if is_dk else "#FFFFFF"), (0.48, "#FDE68A"), (0.82, "#FEF08A" if is_dk else "#FFFBEB")):
                wx = int(round(w * fx))
                canvas.create_oval(wx, h - 4, wx + 2, h - 2, fill=fc, outline="")
        else:
            canvas.create_rectangle(0, h - 2, w, h, fill=hill_c, outline="")
        if is_dk:
            # Twinkling golden stars & pale crescent moon
            for frac, sy in ((0.18, 3), (0.46, 2), (0.74, 4), (0.90, 3)):
                sx = int(round(w * frac))
                canvas.create_oval(sx, sy, sx + 2, sy + 2, fill="#FDE68A", outline="")
        else:
            # Fluffy white cumulus cloud puffs drifting across the summer sky
            for frac, cy_c in ((0.30, 3), (0.78, 2)):
                cx_c = int(round(w * frac))
                canvas.create_oval(cx_c - 6, cy_c, cx_c + 2, cy_c + 6, fill="#FFFFFF", outline="")
                canvas.create_oval(cx_c - 1, cy_c + 1, cx_c + 6, cy_c + 6, fill="#FFFFFF", outline="")
        # Pace marker: warm golden sun (Light) or glowing star (Dark)
        if pace_marker_pct is not None and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(4, min(w - 5, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_oval(mx - 2, 2, mx + 3, 7, fill="#FBBF24" if not is_dk else "#FDE68A", outline="")
        # Dotted white contrail + graceful folded paper airplane!
        if pct is not None:
            clamped = max(0.0, min(100.0, pct))
            px = max(10, min(w - 10, int(round((w - 20) * (clamped / 100.0))) + 10))
            cy = max(5, h // 2 - 1)
            for gx in range(3, max(4, px - 6), 6):
                canvas.create_line(gx, cy + 1, min(px - 6, gx + 3), cy + 1, fill="#FFFFFF" if not is_dk else "#B8D0F0", width=1)
            if runner_photo is not None and h >= 15:
                canvas._runner_ref = runner_photo  # type: ignore[attr-defined]
                canvas.create_image(px, cy, image=runner_photo)
            else:
                canvas.create_polygon([px + 4, cy, px - 3, cy - 3, px - 2, cy + 2], fill="#FFFFFF", outline=border_color)
        return

    if bar_style == "paper_sea":
        # Storybook Watercolor Sunlit/Moonlit Watercolor Ocean + Scalloped Waves + Sparkling Ripples (윤슬) + Origami Paper Sailboat!
        is_dk = int(track_color.lstrip("#")[0:2], 16) < 70
        _rounded_rect(canvas, 0, 0, w, h, 3, fill=track_color, outline="")
        water_y = max(4, h // 2 + 1)
        sea_back = "#1A4256" if is_dk else "#69CBD4"
        sea_front = "#23556D" if is_dk else "#4BBAC7"
        canvas.create_rectangle(0, water_y - 1, w, h, fill=sea_back, outline="")
        if h >= 14:
            # Gentle scalloped watercolor wave crests along the horizon
            for wx in range(-4, w + 8, 14):
                canvas.create_oval(wx, water_y - 3, wx + 14, water_y + 4, fill=sea_back, outline="")
        canvas.create_rectangle(0, water_y + 2, w, h, fill=sea_front, outline="")
        # Shimmering sunlight / moonlight glints (윤슬)
        glint_c = "#FDE68A" if is_dk else "#FFFFFF"
        for gx in range(5, w - 6, 12):
            canvas.create_line(gx, water_y + 3, gx + 4, water_y + 3, fill=glint_c, width=1)
        if is_dk and h >= 14:
            # Tiny pale moon in the night ocean sky
            canvas.create_oval(w - 14, 2, w - 8, 8, fill="#FEF3C7", outline="")
        # Pace marker: tiny floating buoy on the waves
        if pace_marker_pct is not None and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(4, min(w - 5, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_line(mx, max(2, water_y - 4), mx, water_y + 2, fill="#F97316" if not is_dk else "#FDE68A", width=2)
        if pct is not None:
            clamped = max(0.0, min(100.0, pct))
            bx = max(10, min(w - 10, int(round((w - 20) * (clamped / 100.0))) + 10))
            # Soft colored sea wake behind the paper boat
            canvas.create_rectangle(0, water_y + 1, bx, h, fill=fill_color, outline="")
            for gx in range(4, max(5, bx - 6), 9):
                canvas.create_line(gx, water_y + 3, min(bx - 4, gx + 4), water_y + 3, fill="#FFFFFF", width=1)
            if runner_photo is not None and h >= 15:
                canvas._runner_ref = runner_photo  # type: ignore[attr-defined]
                canvas.create_image(bx, max(8, water_y - 2), image=runner_photo)
            else:
                canvas.create_polygon([bx, max(1, water_y - 5), bx - 3, water_y, bx + 3, water_y], fill="#FFFFFF", outline=border_color)
                canvas.create_polygon([bx - 4, water_y, bx + 4, water_y, bx + 2, water_y + 2, bx - 2, water_y + 2], fill="#F2FAFC", outline=border_color)
        return

    if bar_style == "runner":
        # Hare & Tortoise (토끼와 거북이) Olympic clay track race!
        # Hare = your actual usage %; Tortoise = steady recommended time pace %!
        track_h = max(5, min(8, h // 2))
        ty0 = h - track_h
        canvas.create_rectangle(0, ty0, w, h, fill=track_color, outline="")
        mid_t = ty0 + track_h // 2
        for gx in range(4, w - 10, 9):
            canvas.create_line(gx, mid_t, gx + 4, mid_t, fill=highlight_color, width=1)
        # Checkered finish flag at right end
        fx = w - 8
        canvas.create_line(fx, 1, fx, h, fill=border_color, width=1)
        canvas.create_rectangle(fx + 1, 1, w - 1, 7, fill="#FFFFFF", outline="")
        canvas.create_rectangle(fx + 1, 1, fx + 4, 4, fill="#141414", outline="")
        canvas.create_rectangle(fx + 4, 4, w - 1, 7, fill="#141414", outline="")

        usable_w = max(12, w - 20)
        # Usage trail up to Hare position
        if pct is not None:
            clamped = max(0.0, min(100.0, pct))
            hx = max(9, min(w - 12, int(round(usable_w * (clamped / 100.0))) + 9))
            canvas.create_rectangle(0, ty0, hx, h, fill=fill_color, outline="")
        else:
            hx = None

        # Draw Tortoise (거북이) at pace_marker_pct (or starting line if pace unavailable)
        pace_v = max(0.0, min(100.0, pace_marker_pct)) if pace_marker_pct is not None else 6.0
        tx = max(9, min(w - 13, int(round(usable_w * (pace_v / 100.0))) + 9))
        if tortoise_photo is not None and h >= 16:
            canvas._tortoise_ref = tortoise_photo  # type: ignore[attr-defined]
            canvas.create_image(tx, h - 8, image=tortoise_photo)
        elif pace_marker_pct is not None:
            canvas.create_oval(tx - 3, max(1, ty0 - 2), tx + 3, min(h - 1, ty0 + 4), fill="#2EA84C", outline="#18341E", width=1)

        # Draw Hare (토끼) at actual usage % slightly higher mid-leap so both are visible even neck-and-neck!
        if hx is not None:
            if runner_photo is not None and h >= 16:
                canvas._runner_ref = runner_photo  # type: ignore[attr-defined]
                canvas.create_image(hx, max(9, h // 2 - 1), image=runner_photo)
            else:
                # Cute mini white bunny with tiny ears on slim/secondary rows
                by = max(2, ty0 - 2)
                canvas.create_line(hx - 1, max(0, by - 3), hx - 1, by, fill="#FCF8F4", width=1)
                canvas.create_line(hx + 1, max(0, by - 3), hx + 1, by, fill="#FCF8F4", width=1)
                canvas.create_oval(hx - 3, by - 1, hx + 3, min(h - 1, by + 5), fill="#FCF8F4", outline="#342E2C", width=1)
        return

    if bar_style == "thermo":
        # Real horizontal glass mercury thermometer: round bulb on left + graduated tick stem + heat bubbles!
        cy = h // 2
        bulb_r = max(3, min(6, (h - 1) // 2))
        bx = bulb_r + 1
        stem_h = max(4, int(round(bulb_r * 1.15)))
        sy0 = cy - stem_h // 2
        sy1 = sy0 + stem_h
        sx0 = bx + bulb_r - 2
        # Thermal liquid color: cool blue -> warm amber -> boiling red
        liq_col = fill_color
        if pct is not None:
            if pct >= 85.0:
                liq_col = "#EF4444"
            elif pct >= 65.0:
                liq_col = "#F59E0B"
        # Glass tube outline & track
        _rounded_rect(canvas, sx0, sy0, w - 1, sy1, max(1, stem_h // 2), fill=track_color, outline=border_color)
        if pct is not None and pct > 0.0:
            clamped = max(0.0, min(100.0, pct))
            fw = max(4, int(round((w - sx0 - 2) * (clamped / 100.0))))
            fx1 = min(w - 2, sx0 + fw)
            _rounded_rect(canvas, sx0, sy0 + 1, fx1, sy1 - 1, max(1, (stem_h - 2) // 2), fill=liq_col, outline="")
            # Tiny boiling heat bubbles inside red liquid when hot!
            if clamped >= 85.0 and fx1 > sx0 + 16:
                for offset in (6, 13):
                    canvas.create_oval(fx1 - offset, cy - 1, fx1 - offset + 2, cy + 1, fill="#FFFFFF", outline="")
        # Thermometer °C ticks along top of stem
        for frac in (0.2, 0.4, 0.6, 0.8):
            tx = int(round(sx0 + (w - sx0 - 2) * frac))
            canvas.create_line(tx, sy0, tx, sy0 + max(2, stem_h // 2), fill=border_color, width=1)
        # Round glass mercury bulb on left with specular gleam
        canvas.create_oval(bx - bulb_r, cy - bulb_r, bx + bulb_r, cy + bulb_r, fill=liq_col, outline=border_color, width=1)
        if bulb_r >= 4:
            canvas.create_oval(bx - bulb_r + 2, cy - bulb_r + 2, bx - 1, cy - 1, fill=highlight_color, outline="")
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(sx0 + 2, min(w - 3, int(round(sx0 + (w - sx0 - 2) * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, sy0 - 1, mx + 1, sy1 + 1, fill=marker_color, outline="")
        return

    if bar_style == "battery":
        # Physical battery housing + protruding '+' metal cap on right + glowing cells
        bx1 = w - 5
        canvas.create_rectangle(0, 0, bx1, h - 1, fill=track_color, outline=border_color, width=1)
        # Protruding positive '+' cap
        cap_h = max(4, h // 2)
        cy0 = (h - cap_h) // 2
        canvas.create_rectangle(bx1 + 1, cy0, w - 1, cy0 + cap_h, fill=border_color, outline="")
        ix0, iy0, ix1, iy1 = 2, 2, bx1 - 2, max(3, h - 2)
        n_cell = 10 if w >= 180 else 8
        gap = 2
        step = (ix1 - ix0 + gap) / float(n_cell)
        filled_n = 0 if (pct is None or pct <= 0.0) else max(1, int(round(max(0.0, min(100.0, pct)) / 100.0 * n_cell)))
        for idx in range(filled_n):
            cx0 = ix0 + int(round(idx * step))
            cx1 = min(ix1, ix0 + int(round((idx + 1) * step)) - gap)
            if cx1 > cx0:
                canvas.create_rectangle(cx0, iy0, cx1, iy1, fill=fill_color, outline="")
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(2, min(bx1 - 2, int(round(bx1 * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 1, mx + 1, h - 1, fill=marker_color, outline="")
        return

    if bar_style == "speedo":
        # Sports-car horizontal RPM tachometer with crimson redline zone (75-100%) + needle
        rx = int(round(w * 0.75))
        canvas.create_rectangle(0, 1, rx, h - 1, fill=track_color, outline="")
        canvas.create_rectangle(rx, 1, w, h - 1, fill="#7F1D1D", outline="")
        if pct is not None and pct > 0.0:
            clamped = max(0.0, min(100.0, pct))
            fw = max(3, int(round(w * (clamped / 100.0))))
            fx1 = min(w, fw)
            canvas.create_rectangle(0, 1, fx1, h - 1, fill=fill_color, outline="")
            # Bright vertical racing needle at current value
            canvas.create_rectangle(max(0, fx1 - 2), 0, min(w, fx1 + 1), h, fill=highlight_color, outline="")
        for frac in (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875):
            tx = int(round(w * frac))
            canvas.create_line(tx, 1, tx, h - 1, fill="#EF4444" if frac >= 0.75 else border_color, width=1)
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(1, min(w - 2, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 0, mx + 1, h, fill=marker_color, outline="")
        return

    if bar_style == "bliss_01":
        # Retro 2001 recessed white/dark groove + 3-band 3D glossy cylinder segmented blocks!
        canvas.create_rectangle(0, 0, w - 1, h - 1, fill=track_color, outline="")
        canvas.create_line(0, 0, w - 1, 0, fill="#7A7A7A", width=1)
        canvas.create_line(0, 0, 0, h - 1, fill="#7A7A7A", width=1)
        canvas.create_line(0, h - 1, w - 1, h - 1, fill=border_color, width=1)
        canvas.create_line(w - 1, 0, w - 1, h - 1, fill=border_color, width=1)
        ix0, iy0, ix1, iy1 = 2, 2, w - 2, max(4, h - 2)
        bh = max(3, iy1 - iy0)
        blk_w = 7 if w >= 180 else 6
        gap = 2
        n_blk = max(6, (ix1 - ix0 + gap) // (blk_w + gap))
        step = (ix1 - ix0 + gap) / float(n_blk)
        filled_n = 0 if (pct is None or pct <= 0.0) else max(1, int(round(max(0.0, min(100.0, pct)) / 100.0 * n_blk)))
        top_g = _mix_hex(fill_color, "#FFFFFF", 0.56)
        bot_g = _mix_hex(fill_color, "#000000", 0.26)
        for idx in range(filled_n):
            bx0 = ix0 + int(round(idx * step))
            bx1 = min(ix1, ix0 + int(round((idx + 1) * step)) - gap)
            if bx1 > bx0:
                canvas.create_rectangle(bx0, iy0, bx1, iy1, fill=fill_color, outline="")
                if bh >= 4:
                    canvas.create_rectangle(bx0, iy0, bx1, iy0 + max(1, bh // 3), fill=top_g, outline="")
                    canvas.create_rectangle(bx0, iy1 - max(1, bh // 4), bx1, iy1, fill=bot_g, outline="")
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(2, min(w - 3, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 1, mx + 1, h - 1, fill=marker_color, outline="")
        return

    if bar_style == "gel":
        # Classic Brushed Metal "lickable" glossy gel capsule with glossy top reflection + subtle candy sheen!
        r = max(2, h // 2)
        _rounded_rect(canvas, 0, 0, w, h, r, fill=track_color, outline=border_color)
        if pct is not None and pct > 0.0:
            clamped = max(0.0, min(100.0, pct))
            fw = max(h, int(round((w - 2) * (clamped / 100.0))))
            fx1 = min(w - 1, 1 + fw)
            _rounded_rect(canvas, 1, 1, fx1, h - 1, max(1, r - 1), fill=fill_color, outline="")
            # Signature glossy candy diagonal sheen stripes + glossy top glass band!
            sheen = _mix_hex(fill_color, "#FFFFFF", 0.48)
            glow = _mix_hex(fill_color, "#FFFFFF", 0.25)
            mid_y = max(2, h // 2)
            if fx1 > 4:
                canvas.create_rectangle(max(2, r), 1, max(3, fx1 - max(1, r // 2)), mid_y, fill=sheen, outline="")
                for sx in range(r, fx1 - 3, 10):
                    canvas.create_line(sx, h - 2, min(fx1 - 1, sx + 4), 2, fill=glow, width=2)
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(2, min(w - 3, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 1, mx + 1, h - 1, fill=marker_color, outline="")
        return

    if bar_style == "glass":
        # Modern Liquid Glass refractive frosted pill with crisp top specular streak!
        r = max(2, h // 2)
        _rounded_rect(canvas, 0, 0, w, h, r, fill=track_color, outline=border_color)
        if pct is not None and pct > 0.0:
            clamped = max(0.0, min(100.0, pct))
            fw = max(h, int(round(w * (clamped / 100.0))))
            fx1 = min(w, fw)
            _rounded_rect(canvas, 0, 0, fx1, h, r, fill=fill_color, outline="")
            if fx1 > r * 2 + 2:
                spec_c = _mix_hex(fill_color, "#FFFFFF", 0.65)
                canvas.create_line(r, 1, fx1 - r, 1, fill=spec_c, width=1)
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(1, min(w - 2, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 0, mx + 1, h, fill=marker_color, outline="")
        return

    if bar_style == "retro_95":
        # Classic Y2K 3D sunken groove + chunky segmented blocks
        canvas.create_rectangle(0, 0, w - 1, h - 1, fill=track_color, outline="")
        canvas.create_line(0, 0, w - 1, 0, fill=border_color, width=1)
        canvas.create_line(0, 0, 0, h - 1, fill=border_color, width=1)
        canvas.create_line(0, h - 1, w - 1, h - 1, fill=highlight_color, width=1)
        canvas.create_line(w - 1, 0, w - 1, h - 1, fill=highlight_color, width=1)
        ix0, iy0, ix1, iy1 = 2, 2, w - 2, max(3, h - 2)
        blk_w = 6 if w >= 180 else 5
        gap = 2
        n_blk = max(6, (ix1 - ix0 + gap) // (blk_w + gap))
        step = (ix1 - ix0 + gap) / float(n_blk)
        filled_n = 0 if (pct is None or pct <= 0.0) else max(1, int(round(max(0.0, min(100.0, pct)) / 100.0 * n_blk)))
        for idx in range(filled_n):
            bx0 = ix0 + int(round(idx * step))
            bx1 = min(ix1, ix0 + int(round((idx + 1) * step)) - gap)
            if bx1 > bx0:
                canvas.create_rectangle(bx0, iy0, bx1, iy1, fill=fill_color, outline="")
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(2, min(w - 3, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 1, mx + 1, h - 1, fill=marker_color, outline="")
        return

    if bar_style == "brutal":
        # Neo-Brutalist chunky ink-outlined rectangular bar
        canvas.create_rectangle(0, 0, w - 1, h - 1, fill=track_color, outline=border_color, width=1)
        if pct is not None:
            clamped = max(0.0, min(100.0, pct))
            inner_w = max(1, w - 2)
            fill_w = int(round(inner_w * (clamped / 100.0)))
            if clamped > 0 and fill_w < 3:
                fill_w = 3
            if fill_w > 0:
                fx1 = min(w - 1, 1 + fill_w)
                canvas.create_rectangle(1, 1, fx1, h - 1, fill=fill_color, outline="")
                if fx1 < w - 2:
                    canvas.create_line(fx1, 1, fx1, h - 1, fill=border_color, width=1)
        if pace_marker_pct is not None and marker_color and 2.0 <= pace_marker_pct <= 98.0:
            mx = max(2, min(w - 3, int(round(w * (pace_marker_pct / 100.0)))))
            canvas.create_rectangle(mx, 1, mx + 2, h - 1, fill=marker_color, outline="")
        return

    # Default "pill": smooth rounded bar
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
    bot_urgent: bool = False,
    bar_style: str = "pill",
    border_color: str = "#2E2E37",
    highlight_color: str = "#FFFFFF",
) -> None:
    """Draw a sleek dual-bar gauge tailored to any of the 9 UI design themes (cached)."""
    sig = (
        "dual_stack",
        None if top_pct is None else round(top_pct, 1),
        top_color,
        None if bot_pct is None else round(bot_pct, 1),
        bot_color,
        width,
        track_color,
        None if top_pace_pct is None else round(top_pace_pct, 1),
        None if bot_pace_pct is None else round(bot_pace_pct, 1),
        marker_color,
        bot_urgent,
        bar_style,
        border_color,
        highlight_color,
    )
    if getattr(canvas, "_last_bar_sig", None) == sig:
        return
    canvas._last_bar_sig = sig  # type: ignore[attr-defined]
    canvas.delete("all")
    w = width

    def _draw_band(y0: int, y1: int, pct: Optional[float], col: str, pace_pct: Optional[float], rounded: bool) -> None:
        bh = max(2, y1 - y0)
        if bar_style in ("retro_95", "bliss_01"):
            canvas.create_rectangle(0, y0, w - 1, y1, fill=track_color, outline=border_color if bar_style == "bliss_01" else "")
            if bar_style == "retro_95":
                canvas.create_line(0, y0, w - 1, y0, fill=border_color, width=1)
                canvas.create_line(0, y1, w - 1, y1, fill=highlight_color, width=1)
            n_blk = 14
            gap = 2
            step = (w - 2 + gap) / float(n_blk)
            filled_n = 0 if (pct is None or pct <= 0.0) else max(1, int(round(max(0.0, min(100.0, pct)) / 100.0 * n_blk)))
            for idx in range(filled_n):
                bx0 = 1 + int(round(idx * step))
                bx1 = min(w - 1, 1 + int(round((idx + 1) * step)) - gap)
                if bx1 > bx0:
                    canvas.create_rectangle(bx0, y0 + 1, bx1, max(y0 + 2, y1), fill=col, outline="")
        elif bar_style == "battery":
            bx1 = w - 3
            canvas.create_rectangle(0, y0, bx1, y1, fill=track_color, outline=border_color, width=1)
            canvas.create_rectangle(bx1 + 1, y0 + 1, w - 1, max(y0 + 2, y1 - 1), fill=border_color, outline="")
            n_c = 10
            gap = 2
            step = (bx1 - 2 + gap) / float(n_c)
            filled_n = 0 if (pct is None or pct <= 0.0) else max(1, int(round(max(0.0, min(100.0, pct)) / 100.0 * n_c)))
            for idx in range(filled_n):
                cx0 = 1 + int(round(idx * step))
                cx1 = min(bx1 - 1, 1 + int(round((idx + 1) * step)) - gap)
                if cx1 > cx0:
                    canvas.create_rectangle(cx0, y0 + 1, cx1, max(y0 + 2, y1), fill=col, outline="")
        elif bar_style == "speedo":
            rx = int(round(w * 0.75))
            canvas.create_rectangle(0, y0, rx, y1, fill=track_color, outline="")
            canvas.create_rectangle(rx, y0, w, y1, fill="#7F1D1D", outline="")
            if pct is not None and pct > 0.0:
                fw = max(3, int(round(w * (max(0.0, min(100.0, pct)) / 100.0))))
                canvas.create_rectangle(0, y0, min(w, fw), y1, fill=col, outline="")
        elif bar_style in ("brutal", "rpg"):
            canvas.create_rectangle(0, y0, w - 1, y1, fill=track_color, outline=border_color, width=1)
            if pct is not None and pct > 0.0:
                fw = max(3, int(round((w - 2) * (max(0.0, min(100.0, pct)) / 100.0))))
                canvas.create_rectangle(1, y0 + 1, min(w - 1, 1 + fw), y1, fill=col, outline="")
        else:
            r = max(1, bh // 2) if rounded else 1
            _rounded_rect(canvas, 0, y0, w, y1, r, fill=track_color, outline="")
            if pct is not None and pct > 0.0:
                fw = max(bh, int(round(w * (max(0.0, min(100.0, pct)) / 100.0))))
                _rounded_rect(canvas, 0, y0, min(w, fw), y1, r, fill=col, outline="")
            if bar_style == "runner":
                if pace_pct is not None:
                    tx = max(3, min(w - 4, int(round(w * (max(0.0, min(100.0, pace_pct)) / 100.0)))))
                    canvas.create_oval(tx - 2, y0, tx + 2, y1, fill="#2EA84C", outline="#18341E", width=1)
                if pct is not None:
                    rx = max(3, min(w - 4, int(round(w * (max(0.0, min(100.0, pct)) / 100.0)))))
                    canvas.create_oval(rx - 2, y0, rx + 2, y1, fill="#FCF8F4", outline="#342E2C", width=1)
            elif bar_style == "paper_sky" and pct is not None:
                px = max(4, min(w - 4, int(round(w * (max(0.0, min(100.0, pct)) / 100.0)))))
                ym = (y0 + y1) // 2
                canvas.create_polygon([px + 3, ym, px - 2, y0, px - 2, y1], fill="#FFFFFF", outline=border_color)
            elif bar_style == "paper_sea" and pct is not None:
                bx = max(4, min(w - 4, int(round(w * (max(0.0, min(100.0, pct)) / 100.0)))))
                canvas.create_polygon([bx, y0, bx - 3, y1, bx + 3, y1], fill="#FFFFFF", outline=border_color)
            elif bar_style in ("gel", "glass") and pct is not None and pct > 0.0:
                fw = max(bh, int(round(w * (max(0.0, min(100.0, pct)) / 100.0))))
                if fw > 6:
                    canvas.create_line(2, y0 + 1, min(w - 2, fw - 2), y0 + 1, fill=_mix_hex(col, "#FFFFFF", 0.55), width=1)
            elif bar_style == "thermo":
                canvas.create_oval(0, y0, bh + 1, y1, fill=col, outline=border_color, width=1)
        if pace_pct is not None and marker_color and 2.0 <= pace_pct <= 98.0:
            mx = max(1, min(w - 2, int(round(w * (pace_pct / 100.0)))))
            canvas.create_rectangle(mx, y0, mx + 1, y1, fill=marker_color, outline="")

    if bar_style in ("brutal", "retro_95", "bliss_01", "rpg", "battery"):
        _draw_band(0, 4, top_pct, top_color, top_pace_pct, rounded=False)
        _draw_band(5 if bot_urgent else 6, 9, bot_pct, bot_color, bot_pace_pct, rounded=False)
    else:
        _draw_band(0, 4, top_pct, top_color, top_pace_pct, rounded=True)
        _draw_band(5 if bot_urgent else 6, 8, bot_pct, bot_color, bot_pace_pct, rounded=False)


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
        self._style_preview_cache: Dict[tuple, Any] = {}
        self._theme_card_cache: Dict[tuple, Any] = {}
        self._icon_photo_cache: Dict[tuple, Any] = {}
        self._sprite_photo_cache: Dict[tuple, Any] = {}
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

        m_adj = -1 if sys.platform == "darwin" else 0
        self._font_title_sans = ui_font("ui", 9, "bold")
        self._font_title_mono = ui_font("mono", 9 + m_adj, "bold")
        self._font_hdr_sans = ui_font("ui", 8, "bold")
        self._font_hdr_mono = ui_font("mono", 8 + m_adj, "bold")
        self._font_name_sans = ui_font("num", 9, "bold")
        self._font_name_mono = ui_font("mono", 9 + m_adj, "bold")
        self._font_label_sans = ui_font("ui", 8)
        self._font_label_mono = ui_font("mono", 8 + m_adj)
        self._font_label_bold_sans = ui_font("ui", 8, "bold")
        self._font_label_bold_mono = ui_font("mono", 8 + m_adj, "bold")
        self._font_pct_sans = ui_font("num", 9, "bold")
        self._font_pct_mono = ui_font("mono", 9 + m_adj, "bold")
        self._font_pct_sm_sans = ui_font("num", 8, "bold")
        self._font_pct_sm_mono = ui_font("mono", 8 + m_adj, "bold")
        self._font_small_sans = ui_font("ui", 8)
        self._font_small_mono = ui_font("mono", 8 + m_adj)
        self._font_small_bold_sans = ui_font("ui", 8, "bold")
        self._font_small_bold_mono = ui_font("mono", 8 + m_adj, "bold")
        self._font_mono_num = ui_font("num", 8)
        self._font_mono_code = ui_font("mono", 8 + m_adj)
        self._font_mono_num_bold = ui_font("num", 8, "bold")
        self._font_mono_code_bold = ui_font("mono", 8 + m_adj, "bold")
        self._font_ring_sub_sans = ui_font("ui", 7)
        self._font_ring_sub_mono = ui_font("mono", 7)
        self._font_ring_sub_bold_sans = ui_font("ui", 7, "bold")
        self._font_ring_sub_bold_mono = ui_font("mono", 7, "bold")
        self._sync_theme_fonts()

        spec = self._theme_spec()
        # Outer container (omit width= so Tk 9.0 ConfigureFrame never resets reqheight to 1 on .configure()!)
        self._outer = tk.Frame(
            self.root,
            bg=pal["bg_main"],
            padx=0,
            pady=0,
            highlightbackground=pal.get("frame_border", pal["border"]),
            highlightthickness=0 if sys.platform == "win32" else spec["outer_border_w"],
        )
        self._outer.pack(fill="both", expand=True)

        self._build_compact_section()
        self._build_detail_section()
        self._build_context_menu()
        self._setup_macos_integration()
        self._bind_tooltips()

        self._apply_visibility_layout(resize_window=False)
        if self.cfg["expanded"]:
            self._detail_frame.pack(fill="x", pady=(6, 0))
        self._render_icon_btn(self._btn_expand)

        self._update_pin_visual()
        self._refresh_provider_chips()
        self._refresh_style_chips()
        self._bind_drag(self._outer)
        self._bind_drag(self._compact_frame)
        self._bind_drag(self._body_wrap)
        self._bind_drag(self._rows_container)
        self._bind_drag(self._ring_container)

        self.root.update_idletasks()
        self._hwnd = get_hwnd(self.root)
        apply_win11_dwm(
            self._hwnd,
            border_hex=pal.get("frame_border", pal["border"]),
            dark_titlebar=self._last_applied_dark,
            toolwindow=True,
        )
        self._position_initial()

        if self.cfg.get("visible", True):
            self.root.deiconify()
            self.root.lift()
            self._sync_topmost()
            # macOS Tk 9.0 ignores pre-map -topmost on overrideredirect windows; re-sync post-map!
            if sys.platform == "darwin":
                self.root.after(90, self._sync_topmost)
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

    def _ui_theme(self) -> str:
        ut = str(self.cfg.get("ui_theme") or "modern").lower()
        return ut if ut in THEME_PALETTES else "modern"

    def _color_theme(self) -> str:
        """Backwards-compatible alias for _ui_theme()."""
        return self._ui_theme()

    def _theme_spec(self) -> Dict[str, Any]:
        return UI_THEME_SPECS[self._ui_theme()]

    def _is_dark_theme(self) -> bool:
        mode = self._theme_mode()
        if mode == "dark":
            return True
        if mode == "light":
            return False
        return is_windows_dark_mode(system_surface=False)

    def _pal(self) -> Dict[str, str]:
        ut = self._ui_theme()
        return THEME_PALETTES[ut]["dark" if self._is_dark_theme() else "light"]

    def _sync_theme_fonts(self) -> None:
        mono = bool(self._theme_spec().get("mono_ui", False))
        self._font_title = self._font_title_mono if mono else self._font_title_sans
        self._font_hdr = self._font_hdr_mono if mono else self._font_hdr_sans
        self._font_name = self._font_name_mono if mono else self._font_name_sans
        self._font_label = self._font_label_mono if mono else self._font_label_sans
        self._font_label_bold = self._font_label_bold_mono if mono else self._font_label_bold_sans
        self._font_pct = self._font_pct_mono if mono else self._font_pct_sans
        self._font_pct_sm = self._font_pct_sm_mono if mono else self._font_pct_sm_sans
        self._font_small = self._font_small_mono if mono else self._font_small_sans
        self._font_small_bold = self._font_small_bold_mono if mono else self._font_small_bold_sans
        self._font_mono = self._font_mono_code if mono else self._font_mono_num
        self._font_mono_bold = self._font_mono_code_bold if mono else self._font_mono_num_bold
        self._font_ring_sub = self._font_ring_sub_mono if mono else self._font_ring_sub_sans
        self._font_ring_sub_bold = self._font_ring_sub_bold_mono if mono else self._font_ring_sub_bold_sans

    def _primary_metric(self) -> str:
        pm = str(self.cfg.get("primary_metric") or "weekly").lower()
        return pm if pm in PRIMARY_METRICS else "weekly"

    def _emphasize_urgent(self) -> bool:
        return bool(self.cfg.get("emphasize_urgent", True))

    def _set_primary_metric(self, metric: str) -> None:
        if metric not in PRIMARY_METRICS:
            return
        FluentTooltip.hide_active()
        self.cfg["primary_metric"] = metric
        save_config(self.cfg)
        self._ring_photo_cache.clear()
        self._refresh_pri_pill()
        self._apply_visibility_layout(resize_window=False)
        self._refresh_ui(force_tray=True)
        if self._settings_dlg is not None and not self._settings_dlg._closed:
            self._settings_dlg.refresh_theme()

    def _toggle_primary_metric(self) -> None:
        self._set_primary_metric("5h" if self._primary_metric() == "weekly" else "weekly")

    def _set_ui_theme(self, ut: str) -> None:
        if ut not in THEME_PALETTES:
            return
        self.cfg["ui_theme"] = ut
        save_config(self.cfg)
        self._apply_theme()

    def _set_color_theme(self, ct: str) -> None:
        self._set_ui_theme(ct)

    def _refresh_pri_pill(self) -> None:
        if not hasattr(self, "_btn_pri_pill"):
            return
        pal = self._pal()
        ut = self._ui_theme()
        spec = self._theme_spec()
        is_5h = self._primary_metric() == "5h"
        base_tag = "5h" if is_5h else "7d"
        if ut == "rpg":
            txt = f"[{base_tag.upper()}]"
            bd_w = 1
            bg = pal["pin_pill"] if is_5h else pal["bg_btn"]
        elif ut in ("battery", "speedo"):
            txt = base_tag.upper()
            bd_w = 1
            bg = pal["pin_pill"] if is_5h else pal["bg_btn"]
        elif ut == "brutal":
            txt = base_tag.upper()
            bd_w = 1
            bg = pal["pin_pill"] if is_5h else pal["bg_card"]
        elif ut in ("retro_95", "bliss_01"):
            txt = base_tag.upper()
            bd_w = 1
            bg = pal["bg_card"]
        else:
            txt = base_tag
            bd_w = 0
            bg = pal["pin_pill"] if is_5h else pal["bg_btn"]

        if ut in ("retro_95", "bliss_01"):
            fg = pal["accent_agy"] if is_5h else pal["text_pri"]
        else:
            fg = pal["accent_agy"] if is_5h else (pal["text_pri"] if ut == "brutal" else pal["text_sec"])

        bd_col = pal.get("bevel_hi", pal["border"]) if ut in ("retro_95", "bliss_01") else pal["border"]
        if hasattr(self, "_pri_pill_wrap"):
            self._pri_pill_wrap.configure(
                bg=bd_col if bd_w > 0 else (pal.get("titlebar", pal["accent_agy"]) if spec.get("titlebar") else pal["bg_main"]),
                padx=bd_w,
                pady=bd_w,
            )
        # Never set highlightthickness > 0 on tk.Label (macOS Cocoa Tk 9.0 Retina renders a half-size rect!)
        self._btn_pri_pill.configure(
            text=txt,
            bg=bg,
            fg=fg,
            font=ui_font("mono" if spec["mono_ui"] else "num", 7, "bold"),
            highlightthickness=0,
        )

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

    def _get_style_preview_photo(self, style: str, width: int = 156, height: int = 74) -> Any:
        dark = self._is_dark_theme()
        pri_5h = self._primary_metric() == "5h"
        ut = self._ui_theme()
        key = (style, ut, dark, pri_5h, width, height)
        cached = self._style_preview_cache.get(key)
        if cached is not None:
            return cached
        png = render_style_preview_png(style, self._pal(), width=width, height=height, primary_5h=pri_5h, ui_theme=ut)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._style_preview_cache[key] = photo
        return photo

    def _get_theme_card_photo(self, ut: str, mode_key: str, width: int = 152, height: int = 58) -> Any:
        from preview_art import render_ui_theme_chip_png

        key = (ut, mode_key, width, height)
        cached = self._theme_card_cache.get(key)
        if cached is not None:
            return cached
        t_pal = THEME_PALETTES[ut][mode_key]
        png = render_ui_theme_chip_png(ut, t_pal, width=width, height=height)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._theme_card_cache[key] = photo
        return photo

    def _sync_topmost(self) -> None:
        want = bool(self.cfg.get("topmost", True))
        try:
            self.root.attributes("-topmost", want)
        except Exception:
            pass
        if self._hwnd:
            set_topmost_noactivate(self._hwnd, want)

    def _get_rpg_hero_photo(self, prov: str, mood: str, accent: str, bg: str) -> Any:
        dark = self._is_dark_theme()
        key = ("rpg_hero", prov, mood, accent, bg, dark)
        cached = self._sprite_photo_cache.get(key)
        if cached is not None:
            return cached
        png = render_rpg_hero_png(prov, mood, accent, bg, dark=dark, size=20)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._sprite_photo_cache[key] = photo
        return photo

    def _get_hare_photo(self, accent: str, mood: str) -> Any:
        key = ("hare", accent, mood)
        cached = self._sprite_photo_cache.get(key)
        if cached is not None:
            return cached
        png = render_hare_sprite_png(accent, mood=mood, size=20)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._sprite_photo_cache[key] = photo
        return photo

    def _get_tortoise_photo(self) -> Any:
        key = ("tortoise", 20)
        cached = self._sprite_photo_cache.get(key)
        if cached is not None:
            return cached
        png = render_tortoise_sprite_png(size=20)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._sprite_photo_cache[key] = photo
        return photo

    def _get_paper_plane_photo(self, accent: str, mood: str) -> Any:
        dark = self._is_dark_theme()
        key = ("paper_plane", accent, mood, dark)
        cached = self._sprite_photo_cache.get(key)
        if cached is not None:
            return cached
        png = render_paper_plane_png(accent, mood=mood, dark=dark, size=20)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._sprite_photo_cache[key] = photo
        return photo

    def _get_paper_boat_photo(self, accent: str, mood: str) -> Any:
        dark = self._is_dark_theme()
        key = ("paper_boat", accent, mood, dark)
        cached = self._sprite_photo_cache.get(key)
        if cached is not None:
            return cached
        png = render_paper_boat_png(accent, mood=mood, dark=dark, size=20)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._sprite_photo_cache[key] = photo
        return photo

    def _get_hdr_bg_photo(self, ut: str, dark: bool) -> Any:
        key = ("hdr_bg", ut, dark, HUD_WIDTH)
        cached = self._icon_photo_cache.get(key)
        if cached is not None:
            return cached
        if ut == "bliss_01":
            png = render_retro01_titlebar_png(HUD_WIDTH, height=28, dark=dark)
        elif ut == "paper_sky":
            png = render_scenic_titlebar_png(HUD_WIDTH, height=26, kind="sky", dark=dark)
        elif ut == "paper_sea":
            png = render_scenic_titlebar_png(HUD_WIDTH, height=26, kind="sea", dark=dark)
        else:
            png = render_silver_metal_titlebar_png(HUD_WIDTH, height=26, dark=dark)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._icon_photo_cache[key] = photo
        return photo

    def _get_hdr_leading_photo(self, ut: str, bg_hex: str, dark: bool) -> Any:
        key = ("hdr_lead", ut, bg_hex, dark)
        cached = self._icon_photo_cache.get(key)
        if cached is not None:
            return cached
        if ut == "bliss_01":
            png = render_retro01_badge_png(bg_hex, size=16)
        elif ut == "paper_sky":
            png = render_scenic_emblem_png(bg_hex, kind="sky", dark=dark, size=16)
        elif ut == "paper_sea":
            png = render_scenic_emblem_png(bg_hex, kind="sea", dark=dark, size=16)
        elif ut == "silver_metal":
            png = render_traffic_dots_png(bg_hex, style="gel", dark=dark, width=38, height=16)
        else:
            png = render_traffic_dots_png(bg_hex, style="glass", dark=dark, width=38, height=16)
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._icon_photo_cache[key] = photo
        return photo

    def _make_card_shell(
        self,
        parent: tk.Widget,
        padx: int,
        pady: int,
        with_sep: bool = False,
        accent_key: str = "accent_agy",
    ) -> Tuple[Dict[str, Any], tk.Frame]:
        """Create a multi-chrome card shell supporting all 10 UI design themes.

        Supports: Brutal 3px hard shadow, Retro 95 3D raised bevel, Liquid Glass top specular rim,
        Cyber HUD glowing top strip, Notebook 4px left colored spine, and Minimal hairline dividers.
        """
        pal = self._pal()
        spec = self._theme_spec()
        shell = tk.Frame(parent, bg=pal["bg_main"])
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(1, weight=1)

        bevel_t = tk.Frame(shell, bg=pal.get("bevel_hi", pal["border"]), height=1)
        bevel_l = tk.Frame(shell, bg=pal.get("bevel_hi", pal["border"]), width=1)
        bevel_t.grid(row=0, column=0, columnspan=2, sticky="ew")
        bevel_l.grid(row=1, column=0, sticky="ns")
        bevel_t.grid_remove()
        bevel_l.grid_remove()

        card = tk.Frame(
            shell,
            bg=pal["bg_card"],
            highlightbackground=pal["border"],
            highlightthickness=spec["border_w"],
            padx=padx,
            pady=pady,
        )
        card.grid(row=1, column=1, sticky="nsew")

        sh_r = tk.Frame(shell, bg=pal["shadow"], width=3)
        sh_b = tk.Frame(shell, bg=pal["shadow"], height=3)
        sh_c = tk.Frame(shell, bg=pal["shadow"], width=3, height=3)
        sh_r.grid(row=1, column=2, sticky="ns", pady=(3, 0))
        sh_b.grid(row=2, column=1, sticky="ew", padx=(3, 0))
        sh_c.grid(row=2, column=2, sticky="nsew")
        sh_r.grid_remove()
        sh_b.grid_remove()
        sh_c.grid_remove()

        sep = None
        if with_sep:
            sep = tk.Frame(shell, bg=pal["border"], height=1)
            sep.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(3, 0))
            sep.grid_remove()

        shell_info = {
            "shell": shell,
            "card": card,
            "bevel_t": bevel_t,
            "bevel_l": bevel_l,
            "sh_r": sh_r,
            "sh_b": sh_b,
            "sh_c": sh_c,
            "sep": sep,
            "show_sep": False,
            "accent_key": accent_key,
        }
        self._style_card_shell(shell_info)
        return shell_info, card

    def _style_card_shell(
        self,
        shell_info: Dict[str, Any],
        show_sep: Optional[bool] = None,
        border_override: Optional[str] = None,
    ) -> None:
        pal = self._pal()
        spec = self._theme_spec()
        chrome = spec.get("chrome", "flat")
        if show_sep is not None:
            shell_info["show_sep"] = show_sep
        shell_info["shell"].configure(bg=pal["bg_main"])
        card_bg = pal["bg_main"] if spec["hairline_list"] else pal["bg_card"]
        bd_col = border_override or pal["border"]
        bd_w = spec["border_w"]
        if border_override and spec["hairline_list"]:
            bd_w = 0
        elif border_override and chrome == "bevel3d":
            bd_w = 1
        shell_info["card"].configure(
            bg=card_bg,
            highlightbackground=bd_col,
            highlightthickness=bd_w,
        )

        bt = shell_info["bevel_t"]
        bl = shell_info["bevel_l"]
        sr = shell_info["sh_r"]
        sb = shell_info["sh_b"]
        sc = shell_info["sh_c"]

        if spec["shadow"]:
            sh_col = pal["shadow"]
            bt.grid_remove()
            bl.grid_remove()
            sr.configure(bg=sh_col, width=3)
            sb.configure(bg=sh_col, height=3)
            sc.configure(bg=sh_col, width=3, height=3)
            sr.grid(row=1, column=2, sticky="ns", pady=(3, 0))
            sb.grid(row=2, column=1, sticky="ew", padx=(3, 0))
            sc.grid(row=2, column=2, sticky="nsew")
        elif chrome == "bevel3d":
            hi = pal.get("bevel_hi", "#FFFFFF")
            lo = pal["shadow"]
            bt.configure(bg=hi, height=1)
            bl.configure(bg=hi, width=1)
            sr.configure(bg=lo, width=2)
            sb.configure(bg=lo, height=2)
            sc.configure(bg=lo, width=2, height=2)
            bt.grid(row=0, column=0, columnspan=2, sticky="ew")
            bl.grid(row=1, column=0, sticky="ns")
            sr.grid(row=0, column=2, rowspan=2, sticky="ns", pady=0)
            sb.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0)
            sc.grid(row=2, column=2, sticky="nsew")
        elif chrome == "rpg_box":
            hi = border_override or pal.get("bevel_hi", pal["border"])
            bt.configure(bg=hi, height=1)
            bl.configure(bg=hi, width=1)
            sr.configure(bg=hi, width=1)
            sb.configure(bg=hi, height=1)
            sc.configure(bg=hi, width=1, height=1)
            bt.grid(row=0, column=0, columnspan=2, sticky="ew")
            bl.grid(row=1, column=0, sticky="ns")
            sr.grid(row=0, column=2, rowspan=2, sticky="ns", pady=0)
            sb.grid(row=2, column=0, columnspan=2, sticky="ew", padx=0)
            sc.grid(row=2, column=2, sticky="nsew")
        elif chrome in ("glass_rim", "r01_gloss"):
            bt.configure(bg=pal.get("bevel_hi", "#FFFFFF"), height=1)
            bt.grid(row=0, column=1, columnspan=1, sticky="ew")
            bl.grid_remove()
            sr.grid_remove()
            sb.grid_remove()
            sc.grid_remove()
        elif chrome == "cyber_top":
            acc = border_override or pal[shell_info.get("accent_key", "accent_agy")]
            bt.configure(bg=acc, height=2)
            bt.grid(row=0, column=1, columnspan=1, sticky="ew")
            bl.grid_remove()
            sr.grid_remove()
            sb.grid_remove()
            sc.grid_remove()
        elif chrome == "spine":
            acc = border_override or pal[shell_info.get("accent_key", "accent_agy")]
            bl.configure(bg=acc, width=4)
            bl.grid(row=1, column=0, sticky="ns")
            bt.grid_remove()
            sr.grid_remove()
            sb.grid_remove()
            sc.grid_remove()
        else:
            bt.grid_remove()
            bl.grid_remove()
            sr.grid_remove()
            sb.grid_remove()
            sc.grid_remove()

        sep = shell_info.get("sep")
        if sep is not None:
            if spec["hairline_list"] and shell_info.get("show_sep"):
                sep.configure(bg=pal["border"])
                sep.grid()
            else:
                sep.grid_remove()

    def _draw_provider_indicator(
        self,
        canvas: tk.Canvas,
        accent: str,
        prov: str = "antigravity",
        mood: str = "ok",
    ) -> None:
        pal = self._pal()
        spec = self._theme_spec()
        kind = spec["indicator"]
        bg = pal["bg_main"] if spec["hairline_list"] else pal["bg_card"]
        sig = (kind, accent, prov, mood, bg, pal["border"], pal.get("bevel_hi", "#FFFFFF"), pal["shadow"], self._is_dark_theme())
        if getattr(canvas, "_last_ind_sig", None) == sig:
            return
        canvas._last_ind_sig = sig  # type: ignore[attr-defined]
        canvas.configure(bg=bg)
        canvas.delete("all")
        if kind == "none":
            canvas.grid_remove()
            return
        if kind == "rpg_hero":
            canvas.configure(width=20, height=20)
            canvas.grid(row=0, column=0, rowspan=2, padx=(0, 5), sticky="w")
            photo = self._get_rpg_hero_photo(prov, mood, accent, bg)
            canvas._hero_ref = photo  # type: ignore[attr-defined]
            canvas.create_image(10, 10, image=photo)
            return
        canvas.configure(width=10, height=12)
        canvas.grid(row=0, column=0, rowspan=1, padx=(0, 4), sticky="w")
        if kind == "vbar":
            canvas.create_rectangle(3, 0, 6, 12, fill=accent, outline="")
        elif kind == "tick":
            canvas.create_rectangle(4, 0, 6, 12, fill=accent, outline="")
        elif kind == "sq":
            canvas.create_rectangle(2, 3, 8, 9, fill=accent, outline="")
        elif kind == "sq_out":
            canvas.create_rectangle(1, 2, 9, 10, fill=accent, outline=pal["border"], width=1)
        elif kind == "dots4":
            for dx in (1, 6):
                for dy in (2, 7):
                    canvas.create_oval(dx, dy, dx + 3, dy + 3, fill=accent, outline="")
        elif kind == "bevel_sq":
            canvas.create_rectangle(1, 2, 9, 10, fill=accent, outline="")
            canvas.create_line(1, 2, 9, 2, fill=pal.get("bevel_hi", "#FFFFFF"), width=1)
            canvas.create_line(1, 2, 1, 10, fill=pal.get("bevel_hi", "#FFFFFF"), width=1)
            canvas.create_line(1, 10, 9, 10, fill=pal["shadow"], width=1)
            canvas.create_line(9, 2, 9, 10, fill=pal["shadow"], width=1)
        elif kind == "diamond":
            canvas.create_polygon([5, 1, 9, 6, 5, 11, 1, 6], fill=accent, outline="")
        elif kind == "capsule":
            canvas.create_oval(2, 1, 8, 5, fill=accent, outline="")
            canvas.create_oval(2, 7, 8, 11, fill=accent, outline="")
            canvas.create_rectangle(2, 3, 8, 9, fill=accent, outline="")
            canvas.create_oval(4, 2, 6, 4, fill=pal.get("bevel_hi", "#FFFFFF"), outline="")
        elif kind == "meadow_leaf":
            # Soft Storybook Watercolor meadow sprout leaf
            canvas.create_oval(1, 2, 7, 8, fill=accent, outline="")
            canvas.create_oval(4, 4, 9, 9, fill=_mix_hex(accent, "#7DC482", 0.35), outline="")
            canvas.create_line(2, 10, 5, 6, fill=pal.get("good", "#3EA86B"), width=1)
        elif kind == "sea_drop":
            # Delicate coastal water droplet with specular glint
            canvas.create_polygon([5, 1, 8, 6, 5, 10, 2, 6], fill=accent, outline="")
            canvas.create_oval(2, 5, 8, 10, fill=accent, outline="")
            canvas.create_oval(4, 6, 5, 7, fill="#FFFFFF", outline="")
        else:  # "dot"
            canvas.create_oval(1, 2, 8, 9, fill=accent, outline="")

    def _hdr_colors(self) -> Tuple[str, str, bool]:
        pal = self._pal()
        ut = self._ui_theme()
        spec = self._theme_spec()
        dark = self._is_dark_theme()
        use_tbar = bool(spec.get("titlebar"))
        hdr_bg = pal.get("titlebar", pal["accent_agy"]) if use_tbar else pal["bg_main"]
        if ut in ("silver_metal", "paper_sky", "paper_sea"):
            hdr_fg = pal["text_pri"]
        elif use_tbar:
            hdr_fg = "#FFFFFF"
        elif ut == "rpg":
            hdr_fg = pal["border"]
        elif ut == "brutal" and dark:
            hdr_fg = pal["border"]
        else:
            hdr_fg = pal["text_sec"]
        return hdr_bg, hdr_fg, use_tbar

    def _apply_header_chrome(self) -> None:
        pal = self._pal()
        ut = self._ui_theme()
        dark = self._is_dark_theme()
        hdr_bg, hdr_fg, use_tbar = self._hdr_colors()

        # Flush edge-to-edge titlebar for OS & Storybook scenic themes; padded header for others!
        if use_tbar:
            self._hdr_wrap.pack_configure(padx=0, pady=0)
            self._body_wrap.pack_configure(padx=8, pady=(5, 7))
        else:
            self._hdr_wrap.pack_configure(padx=9, pady=(7, 4))
            self._body_wrap.pack_configure(padx=9, pady=(0, 7))

        self._hdr_gloss.pack_forget()
        if ut in ("bliss_01", "silver_metal", "paper_sky", "paper_sea"):
            bg_photo = self._get_hdr_bg_photo(ut, dark)
            self._hdr_bg_lbl._photo_ref = bg_photo  # type: ignore[attr-defined]
            self._hdr_bg_lbl.configure(image=bg_photo, bg=hdr_bg)
            self._hdr_bg_lbl.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            self._hdr_bg_lbl.lower()
            self._hdr.configure(bg=hdr_bg, padx=6, pady=4 if ut == "bliss_01" else 3)
        else:
            self._hdr_bg_lbl.place_forget()
            self._hdr.configure(bg=hdr_bg, padx=5 if use_tbar else 0, pady=3 if use_tbar else 0)

        if ut in ("bliss_01", "silver_metal", "liquid_glass", "paper_sky", "paper_sea"):
            lead_photo = self._get_hdr_leading_photo(ut, hdr_bg, dark)
            self._hdr_leading_lbl._photo_ref = lead_photo  # type: ignore[attr-defined]
            self._hdr_leading_lbl.configure(image=lead_photo, bg=hdr_bg)
            self._hdr_leading_lbl.pack(side="left", padx=(0, 5), before=self._lbl_title)
        else:
            self._hdr_leading_lbl.pack_forget()

        self._btn_bar.configure(bg=hdr_bg)
        self._lbl_title.configure(bg=hdr_bg, fg=hdr_fg, font=self._font_hdr)

    # ------------------------------------------------------------------ Live Theme Switch
    def _apply_theme(self) -> None:
        FluentTooltip.hide_active()
        dark = self._is_dark_theme()
        self._last_applied_dark = dark
        pal = self._pal()
        ut = self._ui_theme()
        spec = self._theme_spec()
        self._sync_theme_fonts()

        card_bg = pal["bg_main"] if spec["hairline_list"] else pal["bg_card"]

        self.root.configure(bg=pal["bg_main"])
        self._outer.configure(
            highlightbackground=pal.get("frame_border", pal["border"]),
            highlightthickness=0 if sys.platform == "win32" else spec["outer_border_w"],
        )
        for w in (
            self._outer, self._compact_frame, self._hdr_wrap, self._body_wrap, self._compact_body,
            self._rows_container, self._ring_container, self._detail_frame,
            self._cards_container, self._ctrl, self._pv_row, self._st_row,
            self._act_row,
        ):
            w.configure(bg=pal["bg_main"])

        self._apply_header_chrome()
        self._refresh_pri_pill()
        self._detail_sep.configure(bg=pal["border"])
        self._pv_lbl.configure(bg=pal["bg_main"], fg=pal["text_muted"], font=self._font_small)
        self._st_lbl.configure(bg=pal["bg_main"], fg=pal["text_muted"], font=self._font_small)

        for b in (
            self._btn_refresh, self._btn_expand, self._btn_settings,
            self._btn_pin, self._btn_hide,
        ):
            self._restore_btn_style(b)

        use_brackets = bool(spec["name_brackets"])
        for prov, row in self._rows.items():
            _full, short, accent_key, _inner = PROVIDER_META[prov]
            accent = pal[accent_key]
            self._style_card_shell(row["shell"])
            self._draw_provider_indicator(row["dot"], accent, prov=prov, mood="ok")
            row["name"].configure(
                text=f"[{short}]" if use_brackets else short,
                width=5 if use_brackets else 4,
                bg=card_bg,
                fg=pal["text_pri"],
                font=self._font_name,
            )
            row["bar"].configure(bg=card_bg)
            row["pct"].configure(bg=card_bg, font=self._font_pct)
            row["sub"].configure(bg=card_bg, font=self._font_small)
            row["lbl_5h"].configure(bg=card_bg, fg=pal["text_muted"], font=self._font_mono)
            row["bar_5h"].configure(bg=card_bg)
            row["pct_5h"].configure(bg=card_bg, font=self._font_pct_sm)
            row["sub_5h"].configure(bg=card_bg, font=self._font_mono)

        for prov, rc in self._ring_cards.items():
            _full, short, accent_key, _inner = PROVIDER_META[prov]
            accent = pal[accent_key]
            self._style_card_shell(rc["shell"])
            rc["canvas"].configure(bg=card_bg)
            rc["name"].configure(
                text=f"[{short}]" if use_brackets else short,
                bg=card_bg,
                fg=accent,
                font=self._font_name,
            )
            rc["sub"].configure(bg=card_bg, fg=pal["text_sec"], font=self._font_ring_sub)

        for prov, cinfo in self._card_refs.items():
            accent = pal[PROVIDER_META[prov][2]]
            self._style_card_shell(cinfo["shell"])
            cinfo["top"].configure(bg=card_bg)
            cinfo["title"].configure(bg=card_bg, fg=accent, font=self._font_title)
            cinfo["btn_up"].configure(bg=card_bg, fg=pal["text_muted"])
            cinfo["btn_dn"].configure(bg=card_bg, fg=pal["text_muted"])
            cinfo["meta"].configure(bg=card_bg, fg=pal["text_muted"], font=self._font_small)
            cinfo["footer"].configure(bg=card_bg, fg=pal["text_muted"], font=self._font_small)
            for slot in cinfo["slots"].values():
                slot["wrap"].configure(bg=card_bg)
                slot["hdr"].configure(bg=card_bg)
                slot["lbl"].configure(bg=card_bg, fg=pal["text_sec"], font=self._font_label)
                slot["pct"].configure(bg=card_bg, font=self._font_pct)
                slot["sub"].configure(bg=card_bg, font=self._font_mono)
                slot["bar"].configure(bg=card_bg)

        for b in self._pill_btns:
            b.configure(
                bg=pal["bg_btn"],
                fg=pal["text_sec"],
                font=self._font_small,
                highlightthickness=0,
            )

        self._refresh_provider_chips()
        self._refresh_style_chips()
        self._refresh_mode_btn()
        self._apply_visibility_layout(resize_window=True)

        if self._hwnd:
            apply_win11_dwm(
                self._hwnd,
                border_hex=pal.get("frame_border", pal["border"]),
                dark_titlebar=dark,
                toolwindow=True,
            )
        self._refresh_ui(force_tray=False)
        if self._settings_dlg is not None and not self._settings_dlg._closed:
            self._settings_dlg.refresh_theme()

    # ------------------------------------------------------------------ UI Build
    def _build_compact_section(self) -> None:
        pal = self._pal()
        hdr_bg, hdr_fg, use_tbar = self._hdr_colors()

        self._compact_frame = tk.Frame(self._outer, bg=pal["bg_main"])
        self._compact_frame.pack(fill="x")

        self._hdr_wrap = tk.Frame(self._compact_frame, bg=pal["bg_main"])
        self._hdr_wrap.pack(fill="x", padx=0 if use_tbar else 9, pady=0 if use_tbar else (7, 4))

        self._hdr_gloss = tk.Frame(self._hdr_wrap, bg=pal.get("bevel_hi", "#6BB0FF"), height=2)

        self._hdr = tk.Frame(self._hdr_wrap, bg=hdr_bg, padx=6 if use_tbar else 0, pady=3 if use_tbar else 0)
        self._hdr.pack(fill="x")
        self._hdr_bg_lbl = tk.Label(self._hdr, bg=hdr_bg, bd=0, highlightthickness=0)
        self._bind_drag(self._hdr)
        self._bind_drag(self._hdr_bg_lbl)
        self._bind_drag(self._hdr_gloss)

        self._hdr_leading_lbl = tk.Label(self._hdr, bg=hdr_bg, bd=0, highlightthickness=0)
        self._bind_drag(self._hdr_leading_lbl)

        self._lbl_title = tk.Label(
            self._hdr, text=self._t("hud_title_used"), bg=hdr_bg, fg=hdr_fg,
            font=self._font_hdr,
        )
        self._lbl_title.pack(side="left")
        self._bind_drag(self._lbl_title)
        self._lbl_title.bind("<Double-Button-1>", lambda _e: self._snap_to_taskbar())

        self._pri_pill_wrap = tk.Frame(self._hdr, bg=hdr_bg, bd=0, highlightthickness=0)
        self._pri_pill_wrap.pack(side="left", padx=(5, 0))
        self._btn_pri_pill = tk.Label(
            self._pri_pill_wrap,
            text="5h" if self._primary_metric() == "5h" else "7d",
            bg=pal["bg_btn"],
            fg=pal["text_sec"],
            font=ui_font("num", 7, "bold"),
            padx=5,
            pady=0,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self._btn_pri_pill.pack()
        self._btn_pri_pill.bind("<Button-1>", lambda _e: self._toggle_primary_metric())
        self._btn_pri_pill.bind(
            "<Enter>",
            lambda _e: self._btn_pri_pill.configure(bg=self._pal()["bg_btn_hover"], fg=self._pal()["text_pri"]),
        )
        self._btn_pri_pill.bind("<Leave>", lambda _e: self._refresh_pri_pill())
        self._refresh_pri_pill()

        self._btn_bar = tk.Frame(self._hdr, bg=hdr_bg)
        self._btn_bar.pack(side="right")

        self._btn_refresh = self._make_icon_btn(self._btn_bar, "refresh", self._trigger_refresh)
        self._btn_expand = self._make_icon_btn(self._btn_bar, "expand", self._toggle_expand)
        self._btn_settings = self._make_icon_btn(self._btn_bar, "settings", lambda: self._open_settings("display"))
        self._btn_pin = self._make_icon_btn(self._btn_bar, "pin_on", self._toggle_topmost)
        self._btn_hide = self._make_icon_btn(self._btn_bar, "hide", self._hide_to_tray)

        for b in (
            self._btn_refresh, self._btn_expand, self._btn_settings,
            self._btn_pin, self._btn_hide,
        ):
            b.pack(side="left", padx=(2, 0))

        # Body wrapper holds compact body (rows/rings) ABOVE detail section with theme-appropriate padding
        self._body_wrap = tk.Frame(self._outer, bg=pal["bg_main"])
        self._body_wrap.pack(fill="x", padx=8 if use_tbar else 9, pady=(5, 7) if use_tbar else (0, 7))
        self._compact_body = tk.Frame(self._body_wrap, bg=pal["bg_main"])
        self._compact_body.pack(fill="x")
        self._bind_drag(self._compact_body)
        self._apply_header_chrome()

        # Container A: Row-based compact view ("dual" 2-line and "slim" 1-line)
        self._rows_container = tk.Frame(self._compact_body, bg=pal["bg_main"])
        self._rows: Dict[str, Dict[str, Any]] = {}
        for prov in ALL_PROVIDERS:
            _full, short, accent_key, _inner = PROVIDER_META[prov]
            self._rows[prov] = self._make_compact_row(self._rows_container, prov, short, accent_key)

        # Container B: Circular ring compact view ("ring")
        self._ring_container = tk.Frame(self._compact_body, bg=pal["bg_main"])
        self._ring_cards: Dict[str, Dict[str, Any]] = {}
        for prov in ALL_PROVIDERS:
            _full, short, accent_key, inner_key = PROVIDER_META[prov]
            self._ring_cards[prov] = self._make_ring_card(
                self._ring_container, prov, short, accent_key, inner_key
            )

    def _get_toolbar_icon(self, kind: str, hovered: bool = False) -> Any:
        dark = self._is_dark_theme()
        ut = self._ui_theme()
        spec = self._theme_spec()
        pal = self._pal()
        key = (kind, hovered, ut, dark)
        cached = self._icon_photo_cache.get(key)
        if cached is not None:
            return cached

        use_tbar = bool(spec.get("titlebar"))
        bg = pal.get("titlebar", pal["accent_agy"]) if use_tbar else pal["bg_main"]
        pill_bg: Optional[str] = None
        pill_border: Optional[str] = None
        if ut == "bliss_01":
            # Retro 2001 glossy 3D white-bordered titlebar buttons (Blue / Start-Green Pin / Red X)!
            fg = "#FFFFFF"
            pill_border = "#FFFFFF"
            if kind == "hide":
                pill_bg = pal.get("xp_close_hover", "#F25A44") if hovered else pal.get("retro_close", "#E0432D")
            elif kind == "pin_on":
                pill_bg = pal.get("xp_pin_hover", "#46C43B") if hovered else pal.get("xp_pin_on", "#35A82B")
            else:
                pill_bg = pal.get("xp_btn_hover", "#3D85FF") if hovered else pal.get("xp_btn", "#266CEB")
        elif ut == "silver_metal":
            if kind == "pin_on":
                fg = pal["accent_agy"]
                pill_bg = pal["pin_pill_hover"] if hovered else pal["pin_pill"]
                pill_border = pal["accent_agy"]
            elif kind == "pin_off":
                fg = pal["text_pri"] if hovered else pal["text_muted"]
                pill_bg = pal["bg_btn_hover"] if hovered else None
            else:
                fg = pal["text_pri"] if hovered else pal["text_sec"]
                pill_bg = pal["bg_btn_hover"] if hovered else None
        elif use_tbar:
            if kind == "pin_on":
                fg = "#FFFFFF"
                pill_bg = pal.get("pin_pill_hover", "#4B72C2") if hovered else pal.get("pin_pill", "#3A5EA8")
                pill_border = "#FFFFFF"
            elif kind == "pin_off":
                fg = "#FFFFFF" if hovered else "#CBD5E1"
                pill_bg = pal.get("pin_pill", "#3A5EA8") if hovered else None
            else:
                fg = "#FFFFFF"
                pill_bg = pal.get("pin_pill", "#3A5EA8") if hovered else None
        elif kind == "pin_on":
            if ut == "brutal":
                fg = pal["border"] if dark else pal["text_pri"]
                pill_border = pal["border"]
            else:
                fg = pal["accent_agy"]
                pill_border = pal["border"] if ut == "rpg" else pal["accent_agy"]
            pill_bg = pal.get("pin_pill_hover", pal["bg_btn_hover"]) if hovered else pal.get("pin_pill", pal["bg_btn"])
        elif kind == "pin_off":
            fg = pal["text_pri"] if hovered else pal["text_muted"]
            pill_bg = pal["bg_btn_hover"] if hovered else None
        elif kind == "refresh_busy":
            fg = pal["accent_agy"]
            pill_bg = pal["bg_btn_hover"] if hovered else None
        else:
            fg = pal["text_pri"] if hovered else pal["text_sec"]
            pill_bg = pal["bg_btn_hover"] if hovered else None

        png = render_toolbar_icon_png(
            kind, fg, bg, pill_bg_hex=pill_bg, pill_border_hex=pill_border, width=22, height=18, ui_theme=ut
        )
        photo = png_bytes_to_photoimage(png, master=self.root)
        self._icon_photo_cache[key] = photo
        return photo

    def _render_icon_btn(self, lbl: tk.Label) -> None:
        pal = self._pal()
        spec = self._theme_spec()
        bg = pal.get("titlebar", pal["accent_agy"]) if spec.get("titlebar") else pal["bg_main"]
        if lbl is getattr(self, "_btn_pin", None):
            kind = "pin_on" if self.cfg.get("topmost", True) else "pin_off"
        elif lbl is getattr(self, "_btn_expand", None):
            kind = "collapse" if self.cfg.get("expanded", False) else "expand"
        elif lbl is getattr(self, "_btn_refresh", None):
            kind = "refresh_busy" if self._refreshing else "refresh"
        else:
            kind = str(getattr(lbl, "_icon_kind", "refresh"))
        hovered = bool(getattr(lbl, "_hovered", False))
        photo = self._get_toolbar_icon(kind, hovered=hovered)
        lbl._photo_ref = photo  # type: ignore[attr-defined]
        lbl.configure(bg=bg, image=photo)

    def _make_icon_btn(self, parent: tk.Widget, icon_kind: str, cmd) -> tk.Label:
        pal = self._pal()
        lbl = tk.Label(
            parent,
            bg=pal["bg_main"],
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            cursor="hand2",
        )
        lbl._icon_kind = icon_kind  # type: ignore[attr-defined]
        lbl._hovered = False  # type: ignore[attr-defined]
        self._render_icon_btn(lbl)

        def _on_enter(_e: tk.Event, w: tk.Label = lbl) -> None:
            w._hovered = True  # type: ignore[attr-defined]
            self._render_icon_btn(w)

        def _on_leave(_e: tk.Event, w: tk.Label = lbl) -> None:
            w._hovered = False  # type: ignore[attr-defined]
            self._render_icon_btn(w)

        lbl.bind("<Button-1>", lambda _e: cmd())
        lbl.bind("<Enter>", _on_enter)
        lbl.bind("<Leave>", _on_leave)
        return lbl

    def _restore_btn_style(self, lbl: tk.Label) -> None:
        self._render_icon_btn(lbl)

    def _make_compact_row(
        self, parent: tk.Widget, prov: str, short_name: str, accent_key: str
    ) -> Dict[str, Any]:
        """Grid-aligned compact row supporting both 'dual' (2-line weekly+5h) and 'slim' (1-line)."""
        pal = self._pal()
        spec = self._theme_spec()
        card_bg = pal["bg_main"] if spec["hairline_list"] else pal["bg_card"]
        accent = pal[accent_key]
        shell_info, row = self._make_card_shell(parent, padx=8, pady=4, with_sep=True, accent_key=accent_key)
        row.grid_columnconfigure(2, weight=1)
        self._bind_drag(shell_info["shell"])
        self._bind_drag(row)

        # Row 0: Primary metric
        dot = tk.Canvas(row, width=10, height=12, bg=card_bg, highlightthickness=0)
        dot.grid(row=0, column=0, padx=(0, 4), sticky="w")
        self._draw_provider_indicator(dot, accent, prov=prov, mood="ok")
        self._bind_drag(dot)

        use_brackets = bool(spec["name_brackets"])
        name_lbl = tk.Label(
            row,
            text=f"[{short_name}]" if use_brackets else short_name,
            bg=card_bg,
            fg=pal["text_pri"],
            font=self._font_name,
            width=5 if use_brackets else 4,
            anchor="w",
        )
        name_lbl.grid(row=0, column=1, sticky="w")
        self._bind_drag(name_lbl)

        bar = tk.Canvas(row, width=102, height=spec["pri_bar_h"], bg=card_bg, highlightthickness=0)
        bar.grid(row=0, column=2, padx=(3, 6), sticky="w")
        self._bind_drag(bar)

        pct_lbl = tk.Label(
            row, text="--%", bg=card_bg, fg=pal["text_muted"],
            font=self._font_pct, width=5, anchor="e",
        )
        pct_lbl.grid(row=0, column=3, sticky="e")
        self._bind_drag(pct_lbl)

        sub_lbl = tk.Label(
            row, text=self._t("waiting"), bg=card_bg, fg=pal["text_muted"],
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

        # Row 1: Secondary metric (visible in 'dual' mode, hidden in 'slim' mode)
        lbl_5h = tk.Label(
            row, text="5h", bg=card_bg, fg=pal["text_muted"],
            font=self._font_mono, width=4, anchor="w",
        )
        lbl_5h.grid(row=1, column=1, pady=(1, 0), sticky="w")
        self._bind_drag(lbl_5h)

        bar_5h = tk.Canvas(row, width=102, height=spec["sec_bar_h"], bg=card_bg, highlightthickness=0)
        bar_5h.grid(row=1, column=2, padx=(3, 6), pady=(1, 0), sticky="w")
        self._bind_drag(bar_5h)

        pct_5h = tk.Label(
            row, text="--%", bg=card_bg, fg=pal["text_muted"],
            font=self._font_pct_sm, width=5, anchor="e",
        )
        pct_5h.grid(row=1, column=3, pady=(1, 0), sticky="e")
        self._bind_drag(pct_5h)

        sub_5h = tk.Label(
            row, text="", bg=card_bg, fg=pal["text_muted"],
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
            "shell": shell_info,
            "frame": row,
            "dot": dot,
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
        spec = self._theme_spec()
        card_bg = pal["bg_main"] if spec["hairline_list"] else pal["bg_card"]
        shell_info, card = self._make_card_shell(parent, padx=4, pady=6, with_sep=False, accent_key=accent_key)
        self._bind_drag(shell_info["shell"])
        self._bind_drag(card)

        canvas = tk.Canvas(card, width=70, height=70, bg=card_bg, highlightthickness=0)
        canvas.pack(pady=(0, 3))
        self._bind_drag(canvas)

        use_brackets = bool(spec["name_brackets"])
        name_lbl = tk.Label(
            card,
            text=f"[{short_name}]" if use_brackets else short_name,
            bg=card_bg,
            fg=pal[accent_key],
            font=self._font_name,
        )
        name_lbl.pack()
        self._bind_drag(name_lbl)

        sub_lbl = tk.Label(
            card, text=self._t("waiting"), bg=card_bg, fg=pal["text_sec"],
            font=self._font_ring_sub, justify="center",
        )
        sub_lbl.pack(pady=(1, 0))
        self._bind_drag(sub_lbl)

        widgets = [card, canvas, name_lbl, sub_lbl]
        for w in widgets:
            w.bind("<Double-Button-1>", lambda _e: self._toggle_expand())

        return {
            "prov": prov,
            "shell": shell_info,
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
        spec = self._theme_spec()
        card_bg = pal["bg_main"] if spec["hairline_list"] else pal["bg_card"]
        wrap = tk.Frame(parent, bg=card_bg)
        wrap.pack(fill="x", pady=(top_pad, 0))

        hdr = tk.Frame(wrap, bg=card_bg)
        hdr.pack(fill="x", pady=(0, 1))

        lbl = tk.Label(hdr, text=label_text, bg=card_bg, fg=pal["text_sec"], font=self._font_label)
        lbl.pack(side="left")
        pct_lbl = tk.Label(hdr, text="--%", bg=card_bg, fg=pal["text_muted"], font=self._font_pct, width=6, anchor="e")
        pct_lbl.pack(side="right")
        sub_lbl = tk.Label(hdr, text="", bg=card_bg, fg=pal["text_muted"], font=self._font_mono, anchor="e")
        sub_lbl.pack(side="right", padx=(4, 4))

        bar = tk.Canvas(wrap, width=DETAIL_BAR_WIDTH, height=6, bg=card_bg, highlightthickness=0)
        bar.pack(fill="x")

        return {
            "wrap": wrap,
            "hdr": hdr,
            "lbl": lbl,
            "accent_key": accent_key,
            "pct": pct_lbl,
            "sub": sub_lbl,
            "bar": bar,
            "top_pad": top_pad,
        }

    def _make_order_arrow(self, parent: tk.Widget, text: str, prov: str, delta: int) -> tk.Label:
        pal = self._pal()
        card_bg = pal["bg_main"] if self._theme_spec()["hairline_list"] else pal["bg_card"]
        btn = tk.Label(
            parent, text=text, bg=card_bg, fg=pal["text_muted"],
            font=ui_font("sym", 7), padx=2, pady=0, cursor="hand2",
        )
        btn.bind("<Button-1>", lambda _e, p=prov, d=delta: self._move_provider(p, d))
        btn.bind("<Enter>", lambda _e, w=btn: w.configure(fg=self._pal()["text_pri"]))
        btn.bind("<Leave>", lambda _e, w=btn: w.configure(fg=self._pal()["text_muted"]))
        return btn

    def _build_detail_section(self) -> None:
        pal = self._pal()
        card_bg = pal["bg_main"] if self._theme_spec()["hairline_list"] else pal["bg_card"]
        self._detail_frame = tk.Frame(self._body_wrap, bg=pal["bg_main"])

        self._detail_sep = tk.Frame(self._detail_frame, bg=pal["border"], height=1)
        self._detail_sep.pack(fill="x", pady=(0, 5))

        self._cards_container = tk.Frame(self._detail_frame, bg=pal["bg_main"])
        self._cards_container.pack(fill="x")
        self._detail_cards: Dict[str, tk.Frame] = {}
        self._card_refs: Dict[str, Dict[str, Any]] = {}

        # Antigravity compact detail card
        agy_shell, agy_card = self._make_card_shell(self._cards_container, padx=9, pady=5, with_sep=True, accent_key="accent_agy")
        self._detail_cards["antigravity"] = agy_shell["shell"]
        agy_top = tk.Frame(agy_card, bg=card_bg)
        agy_top.pack(fill="x")
        agy_title = tk.Label(agy_top, text="Antigravity", bg=card_bg, fg=pal["accent_agy"], font=self._font_title)
        agy_title.pack(side="left")
        agy_up = self._make_order_arrow(agy_top, "▲", "antigravity", -1)
        agy_dn = self._make_order_arrow(agy_top, "▼", "antigravity", 1)
        agy_up.pack(side="left", padx=(4, 0))
        agy_dn.pack(side="left")
        self._agy_meta = tk.Label(agy_top, text=self._t("waiting_conn"), bg=card_bg, fg=pal["text_muted"], font=self._font_small)
        self._agy_meta.pack(side="right")

        self._agy_slots = {
            "weekly_gen": self._make_metric_slot(agy_card, self._t("weekly_gen"), "accent_agy", top_pad=3),
            "weekly_argon": self._make_metric_slot(agy_card, self._t("weekly_argon"), "accent_argon", top_pad=3),
            "session_5h": self._make_metric_slot(agy_card, self._t("session_5h"), "accent_agy_5h", top_pad=3),
        }
        self._agy_footer = tk.Label(agy_card, text="", bg=card_bg, fg=pal["text_muted"], font=self._font_small, anchor="w")
        self._agy_footer.pack(fill="x", pady=(3, 0))
        self._card_refs["antigravity"] = {
            "shell": agy_shell, "card": agy_card, "top": agy_top, "title": agy_title,
            "btn_up": agy_up, "btn_dn": agy_dn,
            "meta": self._agy_meta, "footer": self._agy_footer, "slots": self._agy_slots,
        }

        # Claude compact detail card
        cld_shell, cld_card = self._make_card_shell(self._cards_container, padx=9, pady=5, with_sep=True, accent_key="accent_claude")
        self._detail_cards["claude"] = cld_shell["shell"]
        cld_top = tk.Frame(cld_card, bg=card_bg)
        cld_top.pack(fill="x")
        cld_title = tk.Label(cld_top, text="Claude", bg=card_bg, fg=pal["accent_claude"], font=self._font_title)
        cld_title.pack(side="left")
        cld_up = self._make_order_arrow(cld_top, "▲", "claude", -1)
        cld_dn = self._make_order_arrow(cld_top, "▼", "claude", 1)
        cld_up.pack(side="left", padx=(4, 0))
        cld_dn.pack(side="left")
        self._cld_meta = tk.Label(cld_top, text=self._t("waiting_conn"), bg=card_bg, fg=pal["text_muted"], font=self._font_small)
        self._cld_meta.pack(side="right")

        self._cld_slots = {
            "weekly_gen": self._make_metric_slot(cld_card, self._t("weekly_gen"), "accent_claude", top_pad=3),
            "weekly_fable": self._make_metric_slot(cld_card, self._t("weekly_fable"), "accent_fable", top_pad=3),
            "session_5h": self._make_metric_slot(cld_card, self._t("session_5h"), "accent_claude_5h", top_pad=3),
        }
        self._cld_footer = tk.Label(cld_card, text="", bg=card_bg, fg=pal["text_muted"], font=self._font_small, anchor="w")
        self._cld_footer.pack(fill="x", pady=(3, 0))
        self._card_refs["claude"] = {
            "shell": cld_shell, "card": cld_card, "top": cld_top, "title": cld_title,
            "btn_up": cld_up, "btn_dn": cld_dn,
            "meta": self._cld_meta, "footer": self._cld_footer, "slots": self._cld_slots,
        }

        # Codex compact detail card
        cdx_shell, cdx_card = self._make_card_shell(self._cards_container, padx=9, pady=5, with_sep=True, accent_key="accent_codex")
        self._detail_cards["codex"] = cdx_shell["shell"]
        cdx_top = tk.Frame(cdx_card, bg=card_bg)
        cdx_top.pack(fill="x")
        cdx_title = tk.Label(cdx_top, text="Codex", bg=card_bg, fg=pal["accent_codex"], font=self._font_title)
        cdx_title.pack(side="left")
        cdx_up = self._make_order_arrow(cdx_top, "▲", "codex", -1)
        cdx_dn = self._make_order_arrow(cdx_top, "▼", "codex", 1)
        cdx_up.pack(side="left", padx=(4, 0))
        cdx_dn.pack(side="left")
        self._cdx_meta = tk.Label(cdx_top, text=self._t("waiting_conn"), bg=card_bg, fg=pal["text_muted"], font=self._font_small)
        self._cdx_meta.pack(side="right")

        self._cdx_slots = {
            "weekly": self._make_metric_slot(cdx_card, self._t("weekly_7d"), "accent_codex", top_pad=3),
            "session_5h": self._make_metric_slot(cdx_card, self._t("session_5h"), "accent_codex_5h", top_pad=3),
        }
        self._cdx_footer = tk.Label(cdx_card, text="", bg=card_bg, fg=pal["text_muted"], font=self._font_small, anchor="w")
        self._cdx_footer.pack(fill="x", pady=(3, 0))
        self._card_refs["codex"] = {
            "shell": cdx_shell, "card": cdx_card, "top": cdx_top, "title": cdx_title,
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
            self._btn_pri_pill,
            lambda: self._t("tip_pri_toggle"),
            self._is_dark_theme,
            delay_ms=300,
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
            lines.append(f"⚠\uFE0E {status[1]}")
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
                label=self._t("menu_primary_5h"),
                checked=(self._primary_metric() == "5h"),
                command=self._toggle_primary_metric,
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
                label=self._t("menu_themes"),
                icon="◈",
                command=lambda: self._open_settings("themes"),
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
                    self._render_icon_btn(self._btn_refresh)
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
        # Allow a second launch (e.g. clicking AIUsageBar.app again) to wake/focus this instance
        show_trig = DATA_DIR / ".show_trigger"
        if show_trig.exists():
            try:
                show_trig.unlink()
            except OSError:
                pass
            self._show_from_tray()
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
        self._render_icon_btn(self._btn_pin)

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
        else:
            self._detail_frame.pack_forget()
        self._render_icon_btn(self._btn_expand)

        self.root.update_idletasks()
        new_h = self._measure_hud_height()
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

    def _reorder_detail_slots(self) -> None:
        """Order detail-card metric slots so the chosen primary metric (7d or 5h) sits on top."""
        is_5h = self._primary_metric() == "5h"
        slot_orders = {
            "antigravity": ("session_5h", "weekly_gen", "weekly_argon") if is_5h else ("weekly_gen", "weekly_argon", "session_5h"),
            "claude": ("session_5h", "weekly_gen", "weekly_fable") if is_5h else ("weekly_gen", "weekly_fable", "session_5h"),
            "codex": ("session_5h", "weekly") if is_5h else ("weekly", "session_5h"),
        }
        for prov, order_keys in slot_orders.items():
            cinfo = self._card_refs[prov]
            slots = cinfo["slots"]
            cinfo["footer"].pack_forget()
            for slot in slots.values():
                slot["wrap"].pack_forget()
            for key in order_keys:
                slot = slots[key]
                slot["wrap"].pack(fill="x", pady=(slot.get("top_pad", 3), 0))
            cinfo["footer"].pack(fill="x", pady=(3, 0))

    def _measure_hud_height(self) -> int:
        """Safely compute true required HUD height (guards against Tk 9.0 transient 1px reqheight)."""
        self.root.update_idletasks()
        h = max(self.root.winfo_reqheight(), self._outer.winfo_reqheight())
        if h < 60:
            self._outer.update_idletasks()
            self.root.update_idletasks()
            hdr_h = self._compact_frame.winfo_reqheight()
            body_h = self._body_wrap.winfo_reqheight()
            h = max(self.root.winfo_reqheight(), self._outer.winfo_reqheight(), hdr_h + body_h + 12)
        return max(80, h)

    def _apply_visibility_layout(self, resize_window: bool = True) -> None:
        enabled = self._enabled_providers()
        style = self._compact_style()
        spec = self._theme_spec()
        ut = self._ui_theme()
        cur_h = self.root.winfo_height()
        if cur_h < 60:
            old_x = int(self.cfg.get("x") or 0)
            old_y = int(self.cfg.get("y") or 0)
            old_h = self._measure_hud_height()
        else:
            old_x = self.root.winfo_x()
            old_y = self.root.winfo_y()
            old_h = cur_h
        old_bottom = old_y + old_h
        wl, wt, wr, wb = get_monitor_work_area_for_point(old_x + HUD_WIDTH // 2, old_y + old_h // 2)
        near_bottom = resize_window and cur_h >= 60 and (wb - old_bottom) < 160

        layout_sig = (tuple(enabled), style, ut, self._primary_metric(), bool(self.cfg.get("expanded", False)))
        if getattr(self, "_last_layout_sig", None) == layout_sig:
            # Structural geometry unchanged (e.g. Dark <-> Light switch): restyle shells in-place, zero churn!
            for idx, prov in enumerate(enabled):
                has_next = idx < len(enabled) - 1
                if style == "ring":
                    self._style_card_shell(self._ring_cards[prov]["shell"], show_sep=False)
                else:
                    self._style_card_shell(self._rows[prov]["shell"], show_sep=has_next)
                self._style_card_shell(self._card_refs[prov]["shell"], show_sep=has_next)
            return
        self._last_layout_sig = layout_sig

        # Hide all compact & detail widgets before re-packing in custom order
        self._rows_container.pack_forget()
        self._ring_container.pack_forget()
        for prov in ALL_PROVIDERS:
            self._rows[prov]["shell"]["shell"].pack_forget()
            self._ring_cards[prov]["shell"]["shell"].grid_forget()
            self._detail_cards[prov].pack_forget()

        if style == "ring":
            self._ring_container.pack(fill="x")
            for c in range(3):
                self._ring_container.grid_columnconfigure(c, weight=0, uniform="")
            for idx, prov in enumerate(enabled):
                self._ring_container.grid_columnconfigure(idx, weight=1, uniform="ring_card")
                pad_r = 5 if idx < len(enabled) - 1 else 0
                self._style_card_shell(self._ring_cards[prov]["shell"], show_sep=False)
                self._ring_cards[prov]["shell"]["shell"].grid(row=0, column=idx, sticky="nsew", padx=(0, pad_r))
        else:
            self._rows_container.pack(fill="x")
            is_dual = style == "dual"
            slim_h = 10 if spec["bar_style"] in ("brutal", "retro_95", "bliss_01", "rpg", "battery") else 8
            for idx, prov in enumerate(enabled):
                row = self._rows[prov]
                if is_dual:
                    row["bar"].configure(height=spec["pri_bar_h"])
                    row["sub"].configure(cursor="")
                    for w in row["row1_widgets"]:
                        w.grid()
                else:
                    row["bar"].configure(height=slim_h)
                    row["sub"].configure(cursor="hand2")
                    for w in row["row1_widgets"]:
                        w.grid_remove()
                has_next = idx < len(enabled) - 1
                self._style_card_shell(row["shell"], show_sep=has_next)
                pad_b = (2 if spec["hairline_list"] else (5 if spec["shadow"] else 4)) if has_next else 0
                row["shell"]["shell"].pack(fill="x", pady=(0, pad_b))

        # Detail cards always in custom provider order; toggle ▲/▼ visibility when >= 2 AIs
        self._reorder_detail_slots()
        multi = len(enabled) >= 2
        for idx, prov in enumerate(enabled):
            has_next = idx < len(enabled) - 1
            cinfo = self._card_refs[prov]
            self._style_card_shell(cinfo["shell"], show_sep=has_next)
            pad_b = 3 if spec["hairline_list"] else (5 if spec["shadow"] else 4)
            self._detail_cards[prov].pack(fill="x", pady=(0, pad_b))
            cinfo["btn_up"].pack_forget()
            cinfo["btn_dn"].pack_forget()
            if multi:
                if idx > 0:
                    cinfo["btn_up"].pack(side="left", padx=(4, 0))
                if idx < len(enabled) - 1:
                    cinfo["btn_dn"].pack(side="left", padx=(2 if idx > 0 else 4, 0))

        if resize_window:
            new_h = self._measure_hud_height()
            new_x = max(wl, min(old_x, wr - HUD_WIDTH))
            new_y = max(wt, old_bottom - new_h) if near_bottom else old_y
            if new_y + new_h > wb:
                new_y = max(wt, wb - new_h - 8)
            new_geom = f"{HUD_WIDTH}x{new_h}+{new_x}+{new_y}"
            if (new_h != cur_h) or (new_x != old_x) or (new_y != old_y):
                self.root.geometry(new_geom)
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
        self._render_icon_btn(self._btn_refresh)
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
    ) -> bool:
        """Update one detail metric slot; return True if critical-level urgent emphasis is active."""
        pal = self._pal()
        spec = self._theme_spec()
        ut = self._ui_theme()
        bar_style = spec["bar_style"]
        lang = self._lang()
        emph = self._emphasize_urgent()
        accent = pal[slot["accent_key"]]
        if ut == "bliss_01" and not self._is_dark_theme():
            accent = pal.get("retro_bar", "#2ED12E")
        val = bucket_display_pct(bucket, mode)
        exp = bucket["expired"]
        col = quota_color(val, accent, exp, mode=mode, pal=pal)
        if bar_style in ("runner", "paper_sky", "paper_sea"):
            norm_h, urg_h = 18, 19
        elif bar_style == "thermo":
            norm_h, urg_h = 11, 13
        elif bar_style == "battery":
            norm_h, urg_h = 10, 11
        elif bar_style in ("retro_95", "bliss_01", "speedo", "rpg", "gel"):
            norm_h, urg_h = 9, 10
        elif bar_style in ("brutal", "glass"):
            norm_h, urg_h = 8, 9
        else:
            norm_h, urg_h = 5, 6
        hi_col = pal.get("bevel_hi", "#FFFFFF")
        if val is None:
            slot["lbl"].configure(fg=pal["text_sec"], font=self._font_label)
            slot["pct"].configure(text="--%", fg=pal["text_muted"])
            slot["sub"].configure(text=empty_hint if empty_hint is not None else self._t("waiting"), fg=pal["text_muted"])
            if int(slot["bar"].cget("height")) != norm_h:
                slot["bar"].configure(height=norm_h)
            draw_rounded_bar(
                slot["bar"], None, col, width=DETAIL_BAR_WIDTH, height=norm_h,
                track_color=pal["bg_track"], bar_style=bar_style, border_color=pal["border"], highlight_color=hi_col,
                tortoise_photo=self._get_tortoise_photo() if bar_style == "runner" else None,
            )
            return False

        urgent = emph and not exp and is_warn_level(val, mode)
        crit = emph and not exp and is_crit_level(val, mode)

        slot["lbl"].configure(
            fg=col if urgent else pal["text_sec"],
            font=self._font_label_bold if urgent else self._font_label,
        )
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
        sub_fg = pal["expired"] if exp else (col if crit else (pal["text_pri"] if urgent else pal["text_muted"]))
        slot["sub"].configure(text=sub, fg=sub_fg)
        bar_val = (0.0 if mode == "used" else 100.0) if exp else val
        marker_pct = self._pace_marker_for(bucket, window_sec, now, mode)
        bh = urg_h if urgent else norm_h
        if int(slot["bar"].cget("height")) != bh:
            slot["bar"].configure(height=bh)
        r_photo = None
        t_photo = None
        if bar_style == "runner":
            ahead = marker_pct is not None and ((bar_val - marker_pct >= 15.0) if mode == "used" else (marker_pct - bar_val >= 15.0))
            r_mood = "crit" if crit else ("warn" if (urgent or ahead) else "ok")
            r_photo = self._get_hare_photo(col, r_mood)
            t_photo = self._get_tortoise_photo()
        elif bar_style == "paper_sky":
            r_photo = self._get_paper_plane_photo(col, "crit" if crit else ("warn" if urgent else "ok"))
        elif bar_style == "paper_sea":
            r_photo = self._get_paper_boat_photo(col, "crit" if crit else ("warn" if urgent else "ok"))
        draw_rounded_bar(
            slot["bar"], bar_val, col, width=DETAIL_BAR_WIDTH, height=bh,
            track_color=pal["bg_track"], pace_marker_pct=marker_pct, marker_color=pal["text_pri"],
            bar_style=bar_style, border_color=pal["border"], highlight_color=hi_col,
            runner_photo=r_photo, tortoise_photo=t_photo,
        )
        return crit

    def _update_compact_provider_views(
        self,
        prov: str,
        wk_bkt: Dict[str, Any],
        s5_bkt: Dict[str, Any],
        model_badge: Optional[Tuple[str, float, bool, str]],
        empty_sub: str,
        now: float,
        mode: str,
        n_enabled: int,
    ) -> Tuple[Optional[float], str]:
        """Update both row view (dual/slim) and ring view for one provider; return tray tuple."""
        pal = self._pal()
        spec = self._theme_spec()
        bar_style = spec["bar_style"]
        ring_style = spec["ring_style"]
        pri_h = spec["pri_bar_h"]
        sec_h = spec["sec_bar_h"]
        sec_urg_h = spec["sec_urg_h"]
        lang = self._lang()
        is_used = mode == "used"
        is_5h_pri = self._primary_metric() == "5h"
        emph = self._emphasize_urgent()
        style = self._compact_style()
        slim_metric = self._slim_sub_metric()
        _full, _short, accent_key, inner_key = PROVIDER_META[prov]
        accent = pal[accent_key]
        inner_accent = pal[inner_key]
        reset_word = self._t("reset_short")

        if is_5h_pri:
            top_bkt, bot_bkt = s5_bkt, wk_bkt
            top_win, bot_win = SESSION_5H_WINDOW_SEC, WEEKLY_WINDOW_SEC
            top_acc, bot_acc = inner_accent, accent
            top_tag, bot_tag = "5h", "7d"
            top_fallback, bot_fallback = "5h", self._t("days_7")
        else:
            top_bkt, bot_bkt = wk_bkt, s5_bkt
            top_win, bot_win = WEEKLY_WINDOW_SEC, SESSION_5H_WINDOW_SEC
            top_acc, bot_acc = accent, inner_accent
            top_tag, bot_tag = self._t("tray_wk_prefix"), "5h"
            top_fallback, bot_fallback = self._t("days_7"), "5h"

        p_top = bucket_display_pct(top_bkt, mode)
        exp_top = bool(top_bkt["expired"])
        col_top = quota_color(p_top, top_acc, exp_top, mode=mode, pal=pal)
        disp_top = None if p_top is None else ((0.0 if is_used else 100.0) if exp_top else p_top)

        p_bot = bucket_display_pct(bot_bkt, mode)
        exp_bot = bool(bot_bkt["expired"])
        col_bot = quota_color(p_bot, bot_acc, exp_bot, mode=mode, pal=pal)
        disp_bot = None if p_bot is None else ((0.0 if is_used else 100.0) if exp_bot else p_bot)

        top_marker = self._pace_marker_for(top_bkt, top_win, now, mode)
        bot_marker = self._pace_marker_for(bot_bkt, bot_win, now, mode)
        m_col = pal["text_pri"]

        top_crit = emph and p_top is not None and not exp_top and is_crit_level(p_top, mode)
        top_warn = p_top is not None and not exp_top and is_warn_level(p_top, mode)
        bot_urgent = emph and p_bot is not None and not exp_bot and is_warn_level(p_bot, mode)
        bot_crit = emph and p_bot is not None and not exp_bot and is_crit_level(p_bot, mode)
        border_override = pal["low"] if (top_crit or bot_crit) else None

        ut = self._ui_theme()
        mood = "crit" if (top_crit or bot_crit) else ("warn" if (top_warn or bot_urgent) else "ok")

        # Theme-specific signature bar colors: RPG HP/MP, Retro 2001 Lime Green!
        if ut == "rpg":
            bar_col_top = quota_color(p_top, pal.get("rpg_hp", "#EF4444"), exp_top, mode=mode, pal=pal)
            bar_col_bot = quota_color(p_bot, pal.get("rpg_mp", "#38BDF8"), exp_bot, mode=mode, pal=pal)
            sec_row_tag = "MP"
        elif ut == "bliss_01" and not self._is_dark_theme():
            r01_g = pal.get("retro_bar", "#2ED12E")
            bar_col_top = quota_color(p_top, r01_g, exp_top, mode=mode, pal=pal)
            bar_col_bot = quota_color(p_bot, r01_g, exp_bot, mode=mode, pal=pal)
            sec_row_tag = bot_tag
        else:
            bar_col_top = col_top
            bar_col_bot = col_bot
            sec_row_tag = bot_tag

        # ---------------- Row view ("dual" & "slim") ----------------
        row = self._rows[prov]
        hi_col = pal.get("bevel_hi", "#FFFFFF")
        self._style_card_shell(row["shell"], border_override=border_override)
        if spec["indicator"] == "rpg_hero":
            self._draw_provider_indicator(row["dot"], accent, prov=prov, mood=mood)
        r_photo = None
        t_photo = None
        if bar_style == "runner" and style == "dual":
            ahead = (
                disp_top is not None
                and top_marker is not None
                and ((disp_top - top_marker >= 15.0) if is_used else (top_marker - disp_top >= 15.0))
            )
            hare_mood = "crit" if top_crit else ("warn" if (top_warn or ahead) else "ok")
            r_photo = self._get_hare_photo(bar_col_top, hare_mood)
            t_photo = self._get_tortoise_photo()
        elif bar_style == "paper_sky" and style == "dual":
            r_photo = self._get_paper_plane_photo(bar_col_top, "crit" if top_crit else "ok")
        elif bar_style == "paper_sea" and style == "dual":
            r_photo = self._get_paper_boat_photo(bar_col_top, "crit" if top_crit else "ok")
        if p_top is None:
            row["pct"].configure(text="--%", fg=pal["text_muted"])
            row["sub"].configure(text=empty_sub, fg=pal["text_muted"], font=self._font_small)
            if style == "slim":
                draw_stacked_dual_bar(
                    row["bar"], None, bar_col_top, disp_bot, bar_col_bot, width=102,
                    track_color=pal["bg_track"], top_pace_pct=None, bot_pace_pct=bot_marker,
                    marker_color=m_col, bot_urgent=bot_urgent, bar_style=bar_style,
                    border_color=pal["border"], highlight_color=hi_col,
                )
            else:
                draw_rounded_bar(
                    row["bar"], None, bar_col_top, width=102, height=pri_h,
                    track_color=pal["bg_track"], bar_style=bar_style,
                    border_color=pal["border"], highlight_color=hi_col,
                    tortoise_photo=t_photo,
                )
            tray_info: Tuple[Optional[float], str] = (None, empty_sub)
        else:
            row["pct"].configure(
                text=reset_word if exp_top else format_pct_compact(p_top, mode),
                fg=col_top if exp_top or is_warn_level(p_top, mode) else pal["text_pri"],
            )

            # Decide right-hand badge text for top row
            sub_font = self._font_small
            if style == "slim":
                if (slim_metric == "5h" or bot_crit) and p_bot is not None:
                    sub_txt = f"{sec_row_tag} {reset_word}" if exp_bot else f"{sec_row_tag} {format_pct_compact(p_bot, mode)}"
                    sub_col = col_bot if exp_bot or is_warn_level(p_bot, mode) else pal["text_sec"]
                    if bot_urgent:
                        sub_font = self._font_small_bold
                elif model_badge is not None:
                    b_prefix, b_val, b_exp, b_acc = model_badge
                    sub_txt = f"{b_prefix} {reset_word}" if b_exp else f"{b_prefix} {format_pct_compact(b_val, mode)}"
                    sub_col = quota_color(b_val, b_acc, b_exp, mode=mode, pal=pal)
                elif p_bot is not None:
                    sub_txt = f"{sec_row_tag} {reset_word}" if exp_bot else f"{sec_row_tag} {format_pct_compact(p_bot, mode)}"
                    sub_col = col_bot if exp_bot or is_warn_level(p_bot, mode) else pal["text_sec"]
                    if bot_urgent:
                        sub_font = self._font_small_bold
                else:
                    cd_top = format_countdown(top_bkt["resets_at"], compact=True, now=now, lang=lang)
                    sub_txt = self._t("reset_done_short") if exp_top else (cd_top or top_fallback)
                    sub_col = pal["expired"] if exp_top else pal["text_sec"]
            else:
                if (not is_5h_pri) and model_badge is not None:
                    b_prefix, b_val, b_exp, b_acc = model_badge
                    sub_txt = f"{b_prefix} {reset_word}" if b_exp else f"{b_prefix} {format_pct_compact(b_val, mode)}"
                    sub_col = quota_color(b_val, b_acc, b_exp, mode=mode, pal=pal)
                else:
                    cd_top = format_countdown(top_bkt["resets_at"], compact=True, now=now, lang=lang)
                    sub_txt = self._t("reset_done_short") if exp_top else (cd_top or top_fallback)
                    sub_col = pal["expired"] if exp_top else pal["text_sec"]

            row["sub"].configure(text=sub_txt, fg=sub_col, font=sub_font)

            if style == "slim":
                draw_stacked_dual_bar(
                    row["bar"], disp_top, bar_col_top, disp_bot, bar_col_bot, width=102,
                    track_color=pal["bg_track"], top_pace_pct=top_marker, bot_pace_pct=bot_marker,
                    marker_color=m_col, bot_urgent=bot_urgent, bar_style=bar_style,
                    border_color=pal["border"], highlight_color=hi_col,
                )
            else:
                draw_rounded_bar(
                    row["bar"], disp_top, bar_col_top, width=102, height=pri_h,
                    track_color=pal["bg_track"], pace_marker_pct=top_marker, marker_color=m_col,
                    bar_style=bar_style, border_color=pal["border"], highlight_color=hi_col,
                    runner_photo=r_photo, tortoise_photo=t_photo,
                )

            # Tray tooltip summary (follows active primary metric first)
            parts = [f"{top_tag} {p_top:.0f}%"]
            if p_bot is not None:
                parts.append(f"{bot_tag} {p_bot:.0f}%")
            if model_badge is not None:
                parts.append(f"{model_badge[0]} {model_badge[1]:.0f}%")
            tray_info = (disp_top, " · ".join(parts))

        # Dual mode row 1 (secondary metric line — auto-emphasized when urgent)
        if style == "dual":
            row["lbl_5h"].configure(
                text=sec_row_tag,
                fg=bar_col_bot if (bot_urgent or ut == "rpg") else pal["text_muted"],
                font=self._font_mono_bold if (bot_urgent or ut == "rpg") else self._font_mono,
            )
            b_h = sec_urg_h if bot_urgent else sec_h
            if int(row["bar_5h"].cget("height")) != b_h:
                row["bar_5h"].configure(height=b_h)
            if p_bot is None:
                row["pct_5h"].configure(text="--%", fg=pal["text_muted"], font=self._font_pct_sm)
                row["sub_5h"].configure(text="", fg=pal["text_muted"])
                draw_rounded_bar(
                    row["bar_5h"], None, bar_col_bot, width=102, height=sec_h,
                    track_color=pal["bg_track"], bar_style=bar_style,
                    border_color=pal["border"], highlight_color=hi_col, is_secondary=True,
                )
            else:
                row["pct_5h"].configure(
                    text=reset_word if exp_bot else format_pct_compact(p_bot, mode),
                    fg=col_bot if exp_bot or is_warn_level(p_bot, mode) else pal["text_sec"],
                    font=self._font_pct if bot_crit else self._font_pct_sm,
                )
                cd_bot = format_countdown(bot_bkt["resets_at"], compact=True, now=now, lang=lang)
                sub_bot_col = (
                    pal["expired"] if exp_bot
                    else (col_bot if bot_crit else (pal["text_pri"] if bot_urgent else pal["text_muted"]))
                )
                row["sub_5h"].configure(
                    text=self._t("reset_done_short") if exp_bot else (cd_bot or bot_fallback),
                    fg=sub_bot_col,
                )
                draw_rounded_bar(
                    row["bar_5h"], disp_bot, bar_col_bot, width=102, height=b_h,
                    track_color=pal["bg_track"], pace_marker_pct=bot_marker, marker_color=m_col,
                    bar_style=bar_style, border_color=pal["border"], highlight_color=hi_col, is_secondary=True,
                )

        # ---------------- Ring view ("ring") ----------------
        if style == "ring":
            rc = self._ring_cards[prov]
            self._style_card_shell(rc["shell"], border_override=border_override)
            c_fam = "mono" if spec["mono_ui"] else "num"
            if n_enabled == 1:
                r_size, ow, iw, c_font = 84, 7, 4, ui_font(c_fam, 12, "bold")
            elif n_enabled == 2:
                r_size, ow, iw, c_font = 70, 6, 4, ui_font(c_fam, 10, "bold")
            else:
                r_size, ow, iw, c_font = 60, 5, 3, ui_font(c_fam, 9, "bold")
            eff_iw = iw + (1 if bot_urgent else 0)

            cv = rc["canvas"]
            if int(cv.cget("width")) != r_size:
                cv.configure(width=r_size, height=r_size)

            cache_key = (
                r_size,
                ow,
                eff_iw,
                ring_style,
                pal["border"],
                hi_col,
                pal["bg_track"],
                None if disp_top is None else round(disp_top, 1),
                bar_col_top,
                None if disp_bot is None else round(disp_bot, 1),
                bar_col_bot,
            )
            cached = self._ring_photo_cache.get(prov)
            if cached is not None and cached[0] == cache_key:
                photo = cached[1]
            else:
                png = render_dual_ring_png(
                    size=r_size,
                    outer_pct=disp_top,
                    outer_col=bar_col_top,
                    inner_pct=disp_bot,
                    inner_col=bar_col_bot,
                    track_col=pal["bg_track"],
                    outer_w=ow,
                    inner_w=eff_iw,
                    ring_style=ring_style,
                    outline_col=pal["border"],
                    highlight_col=hi_col,
                )
                photo = png_bytes_to_photoimage(png, master=self.root)
                self._ring_photo_cache[prov] = (cache_key, photo)

            rc["photo"] = photo
            cv.delete("all")
            cv.create_image(r_size // 2, r_size // 2, image=photo)
            if p_top is None:
                center_txt = "--%"
                center_col = pal["text_muted"]
            elif exp_top:
                center_txt = reset_word
                center_col = pal["expired"]
            else:
                center_txt = format_pct_compact(p_top, mode)
                center_col = col_top if is_warn_level(p_top, mode) else pal["text_pri"]
            cv.create_text(r_size // 2, r_size // 2, text=center_txt, fill=center_col, font=c_font)

            # Ring card bottom sub-text
            if p_top is None and p_bot is None:
                ring_sub = empty_sub
            else:
                bot_str = (
                    f"{sec_row_tag} {reset_word}" if exp_bot else f"{sec_row_tag} {p_bot:.0f}%"
                ) if p_bot is not None else f"{sec_row_tag} --"
                if model_badge is not None:
                    mb_str = f"{model_badge[0]} {model_badge[1]:.0f}%"
                    ring_sub = f"{bot_str}\n{mb_str}" if n_enabled >= 3 else f"{bot_str} · {mb_str}"
                else:
                    cd_bot = format_countdown(bot_bkt["resets_at"], compact=True, now=now, lang=lang) if p_bot is not None else ""
                    if cd_bot and not exp_bot:
                        ring_sub = f"{bot_str}\n{cd_bot}" if n_enabled >= 3 else f"{bot_str} · {cd_bot}"
                    else:
                        ring_sub = bot_str
            rc["sub"].configure(
                text=ring_sub,
                fg=(col_bot if bot_urgent else (pal["text_sec"] if p_top is not None else pal["text_muted"])),
                font=self._font_ring_sub_bold if bot_urgent else self._font_ring_sub,
            )

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
        is_5h_pri = self._primary_metric() == "5h"
        enabled = self._enabled_providers()
        n_enabled = len(enabled)
        if is_5h_pri:
            title_key = "hud_title_5h_used" if is_used else "hud_title_5h_rem"
        else:
            title_key = "hud_title_used" if is_used else "hud_title_rem"
        prefix = str(self._theme_spec().get("title_prefix") or "")
        self._lbl_title.configure(text=f"{prefix}{self._t(title_key)}")

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
        agy_crit = any((
            self._update_metric_slot(self._agy_slots["weekly_gen"], agy_wk, now, mode, empty_hint=self._t("waiting"), window_sec=WEEKLY_WINDOW_SEC),
            self._update_metric_slot(self._agy_slots["weekly_argon"], agy_ar, now, mode, empty_hint=self._t("none_avail"), window_sec=WEEKLY_WINDOW_SEC),
            self._update_metric_slot(self._agy_slots["session_5h"], agy_5h, now, mode, empty_hint=self._t("waiting"), window_sec=SESSION_5H_WINDOW_SEC),
        ))
        self._style_card_shell(self._card_refs["antigravity"]["shell"], border_override=pal["low"] if agy_crit else None)

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
        cld_crit = any((
            self._update_metric_slot(
                self._cld_slots["weekly_gen"], cld_wk, now, mode,
                empty_hint=self._t("after_first_chat") if cld_data.get("updated_at") else self._t("waiting"),
                window_sec=WEEKLY_WINDOW_SEC,
            ),
            self._update_metric_slot(
                self._cld_slots["weekly_fable"], cld_fb, now, mode,
                empty_hint=self._t("cli_unavailable") if p_c is not None else self._t("waiting"),
                window_sec=WEEKLY_WINDOW_SEC,
            ),
            self._update_metric_slot(
                self._cld_slots["session_5h"], cld_5h, now, mode,
                empty_hint=self._t("waiting"), window_sec=SESSION_5H_WINDOW_SEC,
            ),
        ))
        self._style_card_shell(self._card_refs["claude"]["shell"], border_override=pal["low"] if cld_crit else None)

        cld_status = self._last_refresh_status.get("claude")
        cld_err = bool(cld_status and not cld_status[0] and cld_status[1])
        cld_foot_parts = []
        if cld_err:
            cld_foot_parts.append(f"⚠\uFE0E {cld_status[1]}")
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

        primary_x = cdx_wk if (is_5h_pri or cdx_wk["remaining_pct"] is not None) else cdx_5h
        p_x = bucket_display_pct(cdx_wk if cdx_wk["remaining_pct"] is not None else cdx_5h, mode)
        tray_cdx = self._update_compact_provider_views(
            "codex", primary_x, cdx_5h, None, self._t("waiting"), now, mode, n_enabled
        )

        cdx_age = format_relative_age(cdx_data.get("updated_at"), now, lang=lang)
        cdx_src = self._t("src_cdx_log") if cdx_data.get("source") == "codex_session_log" else self._t("src_cdx_auto")
        self._cdx_meta.configure(
            text=f"{cdx_src} · {cdx_age}" if cdx_data.get("updated_at") else self._t("waiting_conn")
        )
        cdx_crit = any((
            self._update_metric_slot(self._cdx_slots["weekly"], cdx_wk, now, mode, empty_hint=self._t("waiting"), window_sec=WEEKLY_WINDOW_SEC),
            self._update_metric_slot(self._cdx_slots["session_5h"], cdx_5h, now, mode, empty_hint=self._t("waiting"), window_sec=SESSION_5H_WINDOW_SEC),
        ))
        self._style_card_shell(self._card_refs["codex"]["shell"], border_override=pal["low"] if cdx_crit else None)

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
            is_5h_pri,
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
        # Signal the already-running instance to surface itself
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / ".show_trigger").write_text("show", encoding="utf-8")
        except OSError:
            pass
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
