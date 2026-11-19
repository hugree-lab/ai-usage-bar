"""Zero-dependency Windows global hotkey manager using Win32 RegisterHotKey.

Runs a tiny dedicated Win32 message-loop thread so user-customizable shortcuts
(e.g., Ctrl+Alt+Q, Ctrl+Shift+A, Alt+F9) toggle the HUD from anywhere on Windows,
including fullscreen apps. Gracefully degrades to no-op on non-Windows platforms.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from typing import Callable, Optional, Tuple

from i18n import tr

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP = 0x8000
WM_UPDATE_HOTKEY = WM_APP + 21
HOTKEY_ID = 1

_VK_MAP = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): ord(str(d)) for d in range(0, 10)},
    **{f"F{i}": 0x70 + (i - 1) for i in range(1, 13)},
    "SPACE": 0x20,
    "TAB": 0x09,
    "HOME": 0x24,
    "END": 0x23,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
}

_MOD_ORDER = ("Ctrl", "Alt", "Shift", "Win")
_MOD_BITS = {
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "ALT": MOD_ALT,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN,
    "SUPER": MOD_WIN,
}


def parse_hotkey(spec: str) -> Optional[Tuple[int, int, str]]:
    """Parse 'Ctrl+Alt+Q' into (win32_mods, vk_code, normalized_label) or None if invalid."""
    if not spec or not isinstance(spec, str):
        return None
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if len(parts) < 2:
        return None

    mods = 0
    mod_names = set()
    key_name: Optional[str] = None
    for part in parts:
        up = part.upper()
        if up in _MOD_BITS:
            mods |= _MOD_BITS[up]
            if up in ("CTRL", "CONTROL"):
                mod_names.add("Ctrl")
            elif up == "ALT":
                mod_names.add("Alt")
            elif up == "SHIFT":
                mod_names.add("Shift")
            else:
                mod_names.add("Win")
        elif key_name is None and up in _VK_MAP:
            key_name = up
        else:
            return None

    if mods == 0 or key_name is None:
        return None

    # Require Ctrl or Alt (or F-key with Shift) so typing normal capital letters isn't hijacked
    if mods == MOD_SHIFT and not key_name.startswith("F"):
        return None

    pretty_key = key_name if len(key_name) <= 3 else key_name.title()
    ordered_mods = [m for m in _MOD_ORDER if m in mod_names]
    normalized = "+".join(ordered_mods + [pretty_key])
    return mods, _VK_MAP[key_name], normalized


def format_tk_key_event(state: int, keysym: str) -> Optional[str]:
    """Convert a Tk <KeyPress> event (state, keysym) into a normalized hotkey string."""
    if not keysym:
        return None
    up = keysym.upper()
    if up in ("CONTROL_L", "CONTROL_R", "ALT_L", "ALT_R", "SHIFT_L", "SHIFT_R", "WIN_L", "WIN_R", "SUPER_L", "SUPER_R"):
        return None

    # Tk Windows modifier masks: Shift=0x1, Control=0x4, Alt=0x20000 (or 0x8)
    mods = []
    if state & 0x0004:
        mods.append("Ctrl")
    if state & (0x20000 | 0x0008):
        mods.append("Alt")
    if state & 0x0001:
        mods.append("Shift")

    if not mods:
        return None

    key_alias = {
        "PRIOR": "PAGEUP",
        "NEXT": "PAGEDOWN",
    }.get(up, up)
    if key_alias not in _VK_MAP:
        return None

    candidate = "+".join(mods + [key_alias])
    parsed = parse_hotkey(candidate)
    return parsed[2] if parsed else None


if sys.platform == "win32":
    from ctypes import wintypes

    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    _k32.GetCurrentThreadId.argtypes = []
    _k32.GetCurrentThreadId.restype = wintypes.DWORD

    _u32.PeekMessageW.argtypes = [
        ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT
    ]
    _u32.PeekMessageW.restype = wintypes.BOOL

    _u32.GetMessageW.argtypes = [
        ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT
    ]
    _u32.GetMessageW.restype = wintypes.BOOL

    _u32.PostThreadMessageW.argtypes = [
        wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    _u32.PostThreadMessageW.restype = wintypes.BOOL

    _u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _u32.RegisterHotKey.restype = wintypes.BOOL

    _u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.UnregisterHotKey.restype = wintypes.BOOL


class GlobalHotkeyManager:
    """Manages one customizable global toggle hotkey on Windows."""

    def __init__(self, on_trigger: Callable[[], None]) -> None:
        self._on_trigger = on_trigger
        self._tid: int = 0
        self._ready = threading.Event()
        self._update_done = threading.Event()
        self._lock = threading.Lock()
        self._pending_spec: Optional[Tuple[bool, str, str]] = None
        self._last_result: Tuple[bool, str] = (True, "")
        self._registered: bool = False
        self._thread: Optional[threading.Thread] = None

    def start(self, enabled: bool, spec: str, lang: str = "ko") -> Tuple[bool, str]:
        if sys.platform != "win32":
            return True, tr(lang, "hk_macos_note")
        if self._thread is not None and self._thread.is_alive():
            return self.update(enabled, spec, lang=lang)
        self._thread = threading.Thread(target=self._run, name="GlobalHotkeyThread", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self.update(enabled, spec, lang=lang)

    def update(self, enabled: bool, spec: str, lang: str = "ko") -> Tuple[bool, str]:
        if sys.platform != "win32":
            return True, ""
        if not self._tid:
            return False, tr(lang, "hk_init_err")
        with self._lock:
            self._pending_spec = (enabled, spec, lang)
            self._update_done.clear()
            _u32.PostThreadMessageW(self._tid, WM_UPDATE_HOTKEY, 0, 0)
        self._update_done.wait(timeout=1.5)
        return self._last_result

    def stop(self) -> None:
        if sys.platform != "win32":
            return
        if self._tid:
            try:
                _u32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self._tid = 0

    def _apply_on_thread(self, enabled: bool, spec: str, lang: str = "ko") -> Tuple[bool, str]:
        if self._registered:
            _u32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False
        if not enabled:
            return True, tr(lang, "hk_disabled")
        parsed = parse_hotkey(spec)
        if not parsed:
            return False, tr(lang, "hk_invalid")
        mods, vk, norm = parsed
        ok = bool(_u32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk))
        if not ok:
            return False, tr(lang, "hk_in_use", norm=norm)
        self._registered = True
        return True, tr(lang, "hk_registered", norm=norm)

    def _run(self) -> None:
        self._tid = int(_k32.GetCurrentThreadId())
        # Force creation of Win32 message queue before signaling ready
        msg = _MSG()
        _u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._ready.set()

        while _u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                try:
                    self._on_trigger()
                except Exception:
                    pass
            elif msg.message == WM_UPDATE_HOTKEY:
                pending = self._pending_spec
                if pending is not None:
                    self._last_result = self._apply_on_thread(pending[0], pending[1], pending[2])
                self._update_done.set()

        if self._registered:
            _u32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False
