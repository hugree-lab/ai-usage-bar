"""Windows 11 Fluent theme helpers, multi-monitor geometry, Idle detection,
native-styled Dark/Light Context Menu, and non-activating Hover Tooltip.
"""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
import time
import tkinter as tk
from typing import Any, Callable, List, Optional, Tuple, Union


def ui_font(role: str, size: int, weight: str = "") -> Tuple[Any, ...]:
    """Return a platform-appropriate Tk font tuple with equivalent visual sizing on Windows & macOS."""
    if sys.platform == "darwin":
        family_map = {
            "ui": "Apple SD Gothic Neo",
            "num": "Helvetica Neue",
            "sym": "Apple SD Gothic Neo",
            "mono": "Menlo",
        }
        fam = family_map.get(role, "Apple SD Gothic Neo")
        scaled = max(9, int(round(size * 1.28)))
        return (fam, scaled, weight) if weight else (fam, scaled)
    family_map = {
        "ui": "Malgun Gothic",
        "num": "Segoe UI",
        "sym": "Segoe UI Symbol",
        "mono": "Consolas",
    }
    fam = family_map.get(role, "Malgun Gothic")
    return (fam, size, weight) if weight else (fam, size)

if sys.platform == "win32":
    import winreg
    from ctypes import wintypes

    # Module-private WinDLL handles so argtypes never collide with win_tray / hud_app
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
else:
    winreg = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]
    user32 = None
    kernel32 = None
    dwmapi = None

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SPI_GETWORKAREA = 0x0030
MONITOR_DEFAULTTONEAREST = 2

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02

if sys.platform == "win32":
    _RECT = wintypes.RECT
    _POINT = wintypes.POINT

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    # Explicit 64-bit safe Win32 signatures
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    user32.MonitorFromPoint.argtypes = [_POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
    user32.GetLastInputInfo.restype = wintypes.BOOL
    kernel32.GetTickCount.argtypes = []
    kernel32.GetTickCount.restype = wintypes.DWORD


_MACOS_DARK_CACHE: Tuple[float, bool] = (0.0, True)


def is_windows_dark_mode(system_surface: bool = False) -> bool:
    """Detect OS Dark/Light theme (Windows Personalize registry or cached macOS AppleInterfaceStyle)."""
    global _MACOS_DARK_CACHE
    if sys.platform == "darwin":
        now = time.monotonic()
        if now - _MACOS_DARK_CACHE[0] < 5.0:
            return _MACOS_DARK_CACHE[1]
        try:
            proc = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=1.5,
            )
            dark = proc.returncode == 0 and "dark" in proc.stdout.lower()
        except Exception:
            dark = _MACOS_DARK_CACHE[1]
        _MACOS_DARK_CACHE = (now, dark)
        return dark
    if sys.platform != "win32" or winreg is None:
        return True
    val_name = "SystemUsesLightTheme" if system_surface else "AppsUseLightTheme"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, val_name)
            return int(val) == 0
    except OSError:
        return True


_MACOS_CG_LIB: Any = None


def get_idle_seconds() -> float:
    """Return seconds elapsed since the last mouse or keyboard input."""
    global _MACOS_CG_LIB
    if sys.platform == "darwin":
        try:
            if _MACOS_CG_LIB is None:
                cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
                cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
                cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
                _MACOS_CG_LIB = cg
            # kCGEventSourceStateCombinedSessionState = 0, kCGAnyInputEventType = ~0
            sec = float(_MACOS_CG_LIB.CGEventSourceSecondsSinceLastEventType(0, 0xFFFFFFFF))
            return max(0.0, sec)
        except Exception:
            return 0.0
    if sys.platform != "win32" or user32 is None or kernel32 is None:
        return 0.0
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    now_tick = int(kernel32.GetTickCount())
    elapsed_ms = (now_tick - int(lii.dwTime)) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def get_primary_work_area() -> Tuple[int, int, int, int]:
    if sys.platform == "win32" and user32 is not None:
        rect = _RECT()
        if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    if sys.platform == "darwin":
        try:
            root = tk._default_root  # type: ignore[attr-defined]
            if root is not None:
                return 0, 28, int(root.winfo_screenwidth()), int(root.winfo_screenheight()) - 64
        except Exception:
            pass
    return 0, 0, 1920, 1032


def get_monitor_work_area_for_point(x: int, y: int) -> Tuple[int, int, int, int]:
    """Return (left, top, right, bottom) work area of the monitor nearest to (x, y)."""
    if sys.platform == "win32" and user32 is not None:
        try:
            hmon = user32.MonitorFromPoint(_POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
            if hmon:
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(_MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    w = mi.rcWork
                    return w.left, w.top, w.right, w.bottom
        except Exception:
            pass
    wl, wt, wr, wb = get_primary_work_area()
    if sys.platform == "darwin" and not (wl <= x <= wr and 0 <= y <= wb + 80):
        # Preserve position when user placed HUD on a secondary macOS display
        return min(wl, x - 400), min(wt, y - 300), max(wr, x + 500), max(wb, y + 500)
    return wl, wt, wr, wb


def _hex_to_colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def get_hwnd(win: tk.Misc) -> int:
    if sys.platform != "win32" or user32 is None:
        return 0
    hwnd = user32.GetParent(win.winfo_id())
    return int(hwnd) if hwnd else int(win.winfo_id())


def apply_win11_dwm(
    hwnd: int,
    rounded: int = DWMWCP_ROUND,
    border_hex: Optional[str] = None,
    dark_titlebar: Optional[bool] = None,
    toolwindow: bool = False,
    noactivate: bool = False,
) -> None:
    if sys.platform != "win32" or not hwnd or user32 is None or dwmapi is None:
        return
    if toolwindow or noactivate:
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_ssize_t
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_long.restype = ctypes.c_ssize_t
        ex = get_long(hwnd, GWL_EXSTYLE)
        if toolwindow:
            ex = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if noactivate:
            ex = ex | WS_EX_NOACTIVATE
        set_long(hwnd, GWL_EXSTYLE, ex)

    try:
        if dark_titlebar is not None:
            val = ctypes.c_int(1 if dark_titlebar else 0)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_USE_IMMERSIVE_DARK_MODE),
                ctypes.byref(val),
                ctypes.sizeof(val),
            )
        if rounded:
            corner = ctypes.c_int(rounded)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_WINDOW_CORNER_PREFERENCE),
                ctypes.byref(corner),
                ctypes.sizeof(corner),
            )
        if border_hex:
            border = ctypes.c_int(_hex_to_colorref(border_hex))
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_BORDER_COLOR),
                ctypes.byref(border),
                ctypes.sizeof(border),
            )
    except Exception:
        pass


def _win11_menu_palette(dark: bool) -> dict:
    if dark:
        return {
            "bg": "#2B2B2B",
            "hover": "#383838",
            "border": "#444444",
            "sep": "#3E3E3E",
            "fg": "#F5F5F5",
            "fg_muted": "#A6A6A6",
            "accent": "#60CDFF",
            "danger": "#FF99A4",
            "danger_hover": "#44272B",
        }
    return {
        "bg": "#F9F9F9",
        "hover": "#EAEAEA",
        "border": "#D6D6D6",
        "sep": "#E3E3E3",
        "fg": "#1A1A1A",
        "fg_muted": "#616161",
        "accent": "#0067C0",
        "danger": "#C42B1C",
        "danger_hover": "#FDE7E9",
    }


class FluentMenuItem:
    def __init__(
        self,
        label: str = "",
        command: Optional[Callable[[], None]] = None,
        checked: Optional[bool] = None,
        icon: str = "",
        danger: bool = False,
        separator: bool = False,
    ) -> None:
        self.label = label
        self.command = command
        self.checked = checked
        self.icon = icon
        self.danger = danger
        self.separator = separator


class FluentPopupMenu:
    """Windows 11 Fluent Dark/Light context menu with DWM rounded corners & multi-monitor clamping."""

    _active: Optional["FluentPopupMenu"] = None

    def __init__(
        self,
        master: tk.Misc,
        items: List[FluentMenuItem],
        x: int,
        y: int,
        system_surface: bool = False,
        force_dark: Optional[bool] = None,
    ) -> None:
        if FluentPopupMenu._active is not None:
            FluentPopupMenu._active.close()
        FluentTooltip.hide_active()

        self._master = master
        self._closed = False
        self._mouse_was_down = True
        self._native_menu: Optional[tk.Menu] = None
        self._native_vars: List[tk.BooleanVar] = []

        if sys.platform == "darwin":
            # Use native macOS Cocoa popup menu for reliable dark/light theme & outside-click dismissal
            menu = tk.Menu(master, tearoff=0)
            self._native_menu = menu
            for item in items:
                if item.separator:
                    menu.add_separator()
                    continue

                def _invoke(cmd=item.command) -> None:
                    self.close()
                    if cmd:
                        self._master.after(10, cmd)

                if item.checked is not None:
                    var = tk.BooleanVar(master=master, value=bool(item.checked))
                    self._native_vars.append(var)
                    menu.add_checkbutton(label=item.label, variable=var, command=_invoke)
                else:
                    menu.add_command(label=item.label, command=_invoke)

            FluentPopupMenu._active = self
            try:
                menu.tk_popup(int(x), int(y))
            finally:
                try:
                    menu.grab_release()
                except Exception:
                    pass
                if FluentPopupMenu._active is self:
                    FluentPopupMenu._active = None
            return

        dark = is_windows_dark_mode(system_surface=system_surface) if force_dark is None else force_dark
        pal = _win11_menu_palette(dark)
        self._pal = pal

        win = tk.Toplevel(master)
        self._win = win
        win.overrideredirect(True)
        win.configure(bg=pal["bg"])
        win.attributes("-topmost", True)

        container = tk.Frame(win, bg=pal["bg"], padx=5, pady=5)
        container.pack(fill="both", expand=True)

        font_item = ui_font("ui", 9)
        font_icon = ui_font("sym", 9)

        for item in items:
            if item.separator:
                tk.Frame(container, bg=pal["sep"], height=1).pack(fill="x", padx=6, pady=3)
                continue

            row = tk.Frame(container, bg=pal["bg"], padx=8, pady=4, cursor="hand2")
            row.pack(fill="x", pady=1)

            if item.checked is not None:
                glyph = "✓" if item.checked else ""
                glyph_fg = pal["accent"] if item.checked else pal["bg"]
            else:
                glyph = item.icon
                glyph_fg = pal["danger"] if item.danger else pal["fg_muted"]

            lbl_g = tk.Label(
                row, text=glyph, bg=pal["bg"], fg=glyph_fg,
                font=font_icon, width=2, anchor="center",
            )
            lbl_g.pack(side="left", padx=(0, 6))

            fg_norm = pal["danger"] if item.danger else pal["fg"]
            lbl_t = tk.Label(
                row, text=item.label, bg=pal["bg"], fg=fg_norm,
                font=font_item, anchor="w", padx=2,
            )
            lbl_t.pack(side="left", fill="x", expand=True, padx=(0, 12))

            hover_bg = pal["danger_hover"] if item.danger else pal["hover"]

            def make_handlers(r=row, g=lbl_g, t=lbl_t, hbg=hover_bg, cmd=item.command):
                def on_enter(_e):
                    r.configure(bg=hbg)
                    g.configure(bg=hbg)
                    t.configure(bg=hbg)

                def on_leave(_e):
                    r.configure(bg=pal["bg"])
                    g.configure(bg=pal["bg"])
                    t.configure(bg=pal["bg"])

                def on_click(_e):
                    self.close()
                    if cmd:
                        self._master.after(10, cmd)

                return on_enter, on_leave, on_click

            ent, lve, clk = make_handlers()
            for w in (row, lbl_g, lbl_t):
                w.bind("<Enter>", ent)
                w.bind("<Leave>", lve)
                w.bind("<ButtonRelease-1>", clk)

        # Multi-monitor work area clamping around the clicked point (x, y)
        win.update_idletasks()
        w = max(218, win.winfo_reqwidth())
        h = win.winfo_reqheight()
        wl, wt, wr, wb = get_monitor_work_area_for_point(x, y)

        px = x if (x + w <= wr - 4) else max(wl + 4, x - w)
        py = y if (y + h <= wb - 4) else max(wt + 4, y - h)
        if y > wb:
            py = max(wt + 4, wb - h - 6)
        win.geometry(f"{w}x{h}+{px}+{py}")
        win.update_idletasks()

        self._hwnd = get_hwnd(win)
        if sys.platform == "win32" and user32 is not None and self._hwnd:
            apply_win11_dwm(
                self._hwnd,
                rounded=DWMWCP_ROUND,
                border_hex=pal["border"],
                dark_titlebar=dark,
                toolwindow=True,
            )
            user32.SetWindowPos(
                wintypes.HWND(self._hwnd),
                wintypes.HWND(HWND_TOPMOST),
                px, py, w, h,
                SWP_FRAMECHANGED,
            )
            win.geometry(f"{w}x{h}+{px}+{py}")
            try:
                user32.SetForegroundWindow(wintypes.HWND(self._hwnd))
            except Exception:
                pass
        try:
            win.focus_force()
        except Exception:
            pass

        win.bind("<Escape>", lambda _e: self.close())
        win.bind("<FocusOut>", lambda _e: self._on_focus_out())

        FluentPopupMenu._active = self
        if sys.platform == "win32":
            self._win.after(60, self._poll_outside_click)

    def _on_focus_out(self) -> None:
        if self._closed:
            return
        self._win.after(30, self._check_focus)

    def _check_focus(self) -> None:
        if self._closed:
            return
        if sys.platform != "win32" or user32 is None:
            try:
                if self._win.focus_displayof() is None:
                    self.close()
            except Exception:
                self.close()
            return
        try:
            fg = int(user32.GetForegroundWindow())
            if fg != self._hwnd:
                self.close()
        except Exception:
            pass

    def _poll_outside_click(self) -> None:
        if self._closed:
            return
        try:
            ldown = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            rdown = bool(user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)
            any_down = ldown or rdown
            if self._mouse_was_down:
                if not any_down:
                    self._mouse_was_down = False
            elif any_down:
                pt = _POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                rx0 = self._win.winfo_rootx()
                ry0 = self._win.winfo_rooty()
                rx1 = rx0 + self._win.winfo_width()
                ry1 = ry0 + self._win.winfo_height()
                if not (rx0 <= pt.x <= rx1 and ry0 <= pt.y <= ry1):
                    self.close()
                    return
        except Exception:
            return
        if not self._closed:
            self._win.after(45, self._poll_outside_click)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if FluentPopupMenu._active is self:
            FluentPopupMenu._active = None
        if getattr(self, "_native_menu", None) is not None:
            try:
                self._native_menu.unpost()
                self._native_menu.destroy()
            except Exception:
                pass
            self._native_menu = None
            return
        try:
            self._win.destroy()
        except Exception:
            pass


class FluentTooltip:
    """Non-activating Windows 11 Fluent hover tooltip for buttons & compact AI rows."""

    _active_win: Optional[tk.Toplevel] = None
    _active_anchor: Optional[tk.Widget] = None
    _pending_after: Optional[tuple[tk.Misc, str]] = None
    _pending_anchor: Optional[tk.Widget] = None

    @classmethod
    def hide_active(cls) -> None:
        if cls._pending_after is not None:
            owner, after_id = cls._pending_after
            cls._pending_after = None
            cls._pending_anchor = None
            try:
                owner.after_cancel(after_id)
            except Exception:
                pass
        if cls._active_win is not None:
            w = cls._active_win
            cls._active_win = None
            cls._active_anchor = None
            try:
                w.destroy()
            except Exception:
                pass

    @classmethod
    def _widget_screen_rect(cls, widget: tk.Widget) -> Tuple[int, int, int, int]:
        if sys.platform == "win32" and user32 is not None:
            rc = _RECT()
            try:
                wid = widget.winfo_id()
                if wid and user32.GetWindowRect(wintypes.HWND(wid), ctypes.byref(rc)):
                    if rc.right > rc.left and rc.bottom > rc.top:
                        return int(rc.left), int(rc.top), int(rc.right), int(rc.bottom)
            except Exception:
                pass
        ax0 = widget.winfo_rootx()
        ay0 = widget.winfo_rooty()
        return ax0, ay0, ax0 + widget.winfo_width(), ay0 + widget.winfo_height()

    @classmethod
    def _cursor_inside(cls, anchor: tk.Widget) -> bool:
        try:
            if not anchor.winfo_exists() or not anchor.winfo_viewable():
                return False
            if sys.platform == "win32" and user32 is not None:
                pt = _POINT()
                if user32.GetCursorPos(ctypes.byref(pt)):
                    cx, cy = int(pt.x), int(pt.y)
                else:
                    cx, cy = anchor.winfo_pointerxy()
            else:
                cx, cy = anchor.winfo_pointerxy()
            ax0, ay0, ax1, ay1 = cls._widget_screen_rect(anchor)
            return ax0 <= cx <= ax1 and ay0 <= cy <= ay1
        except Exception:
            return False

    @classmethod
    def bind(
        cls,
        widgets: Union[tk.Widget, List[tk.Widget]],
        text_provider: Union[str, Callable[[], str]],
        is_dark_fn: Callable[[], bool],
        delay_ms: int = 320,
        anchor_widget: Optional[tk.Widget] = None,
        image_provider: Optional[Callable[[], Optional[tk.PhotoImage]]] = None,
    ) -> None:
        wlist = widgets if isinstance(widgets, (list, tuple)) else [widgets]
        anchor = anchor_widget or wlist[0]

        def on_enter(_e: tk.Event) -> None:
            if FluentPopupMenu._active is not None:
                return
            # Avoid flickering when crossing between child labels of the same compact row
            if cls._active_win is not None and cls._active_anchor is anchor:
                return
            if cls._pending_after is not None and cls._pending_anchor is anchor:
                return
            cls.hide_active()
            aid = anchor.after(delay_ms, show)
            cls._pending_after = (anchor, aid)
            cls._pending_anchor = anchor

        def on_leave(_e: tk.Event) -> None:
            # Delay briefly so crossing child widgets inside the same row does not cancel/flicker
            anchor.after(65, check_still_inside)

        def check_still_inside() -> None:
            if cls._cursor_inside(anchor):
                return
            if cls._active_anchor is anchor or cls._pending_anchor is anchor:
                cls.hide_active()

        def show() -> None:
            cls._pending_after = None
            cls._pending_anchor = None
            if FluentPopupMenu._active is not None:
                return
            if not cls._cursor_inside(anchor):
                return
            try:
                txt = text_provider() if callable(text_provider) else text_provider
            except Exception:
                return
            img = None
            if image_provider is not None:
                try:
                    img = image_provider()
                except Exception:
                    img = None
            if (not txt or not txt.strip()) and img is None:
                return

            cls.hide_active()
            dark = is_dark_fn()
            pal = _win11_menu_palette(dark)

            tip = tk.Toplevel(anchor)
            cls._active_win = tip
            cls._active_anchor = anchor
            if sys.platform == "darwin":
                # On macOS Tk 9.0, overrideredirect(True) forces a Toplevel to layer=0,
                # which gets buried/clipped behind the pinned floating HUD (layer=19).
                # Native MacWindowStyle "help noActivates" keeps the tooltip borderless
                # at floating tooltip level (layer=19) directly above the pinned HUD.
                tip.withdraw()
                try:
                    tip.tk.call("::tk::unsupported::MacWindowStyle", "style", tip._w, "help", "noActivates")
                except Exception:
                    tip.overrideredirect(True)
                tip.configure(bg=pal["bg"])
                body = tk.Frame(
                    tip,
                    bg=pal["bg"],
                    highlightbackground=pal["border"],
                    highlightthickness=1,
                    padx=10,
                    pady=7,
                )
            else:
                tip.overrideredirect(True)
                tip.configure(bg=pal["bg"])
                tip.attributes("-topmost", True)
                body = tk.Frame(tip, bg=pal["bg"], padx=10, pady=7)
            body.pack()
            tip.bind("<ButtonPress-1>", lambda _e: cls.hide_active(), add="+")

            if img is not None:
                tip._img_ref = img  # type: ignore[attr-defined]
                tk.Label(body, image=img, bg=pal["bg"], bd=0).pack(pady=(0, 5 if txt else 0))

            if txt and txt.strip():
                lines = txt.strip().splitlines()
                if len(lines) >= 2:
                    tk.Label(
                        body,
                        text=lines[0],
                        bg=pal["bg"],
                        fg=pal["accent"],
                        font=ui_font("ui", 8, "bold"),
                        justify="left",
                        anchor="w",
                    ).pack(fill="x", pady=(0, 3))
                    tk.Label(
                        body,
                        text="\n".join(lines[1:]),
                        bg=pal["bg"],
                        fg=pal["fg"],
                        font=ui_font("ui", 8),
                        justify="left",
                        anchor="w",
                    ).pack(fill="x")
                else:
                    tk.Label(
                        body,
                        text=lines[0],
                        bg=pal["bg"],
                        fg=pal["fg"],
                        font=ui_font("ui", 8),
                        justify="left",
                        anchor="w",
                    ).pack()

            tip.update_idletasks()
            tw = tip.winfo_reqwidth()
            th = tip.winfo_reqheight()

            ax, ay, ax1, ay1 = cls._widget_screen_rect(anchor)
            aw = max(1, ax1 - ax)
            ah = max(1, ay1 - ay)
            wl, wt, wr, wb = get_monitor_work_area_for_point(ax + aw // 2, ay + ah // 2)

            px = max(wl + 6, min(ax, wr - tw - 6))
            # Prefer above the row/button; fall back to below if near top edge
            py = ay - th - 6
            if py < wt + 6:
                py = min(wb - th - 6, ay + ah + 6)

            tip.geometry(f"{tw}x{th}{px:+d}{py:+d}")
            if sys.platform == "darwin":
                tip.deiconify()
                tip.update_idletasks()
                tip.geometry(f"{tw}x{th}{px:+d}{py:+d}")
                try:
                    top_owner = anchor.winfo_toplevel()
                    tip.lift(top_owner)
                except Exception:
                    try:
                        tip.lift()
                    except Exception:
                        pass
            else:
                tip.update_idletasks()
            if sys.platform == "win32" and user32 is not None:
                hwnd = get_hwnd(tip)
                apply_win11_dwm(
                    hwnd,
                    rounded=DWMWCP_ROUNDSMALL,
                    border_hex=pal["border"],
                    dark_titlebar=dark,
                    toolwindow=True,
                    noactivate=True,
                )
                user32.SetWindowPos(
                    wintypes.HWND(hwnd),
                    wintypes.HWND(HWND_TOPMOST),
                    px, py, tw, th,
                    SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
                )

        for w in wlist:
            w.bind("<Enter>", on_enter, add="+")
            w.bind("<Leave>", on_leave, add="+")
            w.bind("<ButtonPress-1>", lambda _e: cls.hide_active(), add="+")
            w.bind("<ButtonPress-2>", lambda _e: cls.hide_active(), add="+")
            w.bind("<ButtonPress-3>", lambda _e: cls.hide_active(), add="+")
            if sys.platform == "darwin":
                w.bind("<Control-ButtonPress-1>", lambda _e: cls.hide_active(), add="+")
