"""Zero-dependency native Windows System Tray icon using Win32 ctypes + Pillow."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from PIL import Image, ImageDraw

if sys.platform != "win32":
    class WinTrayIcon:  # type: ignore[no-redef]
        """macOS / POSIX tray & native osascript notification bridge."""

        def __init__(
            self,
            icon_path: Path,
            on_action: Callable[[str], None],
            get_flags: Callable[[], Dict[str, bool]],
        ) -> None:
            self._icon_path = icon_path
            self._on_action = on_action
            self._get_flags = get_flags

        def start(self) -> None:
            pass

        def update(
            self,
            bars: list[tuple[str, Optional[float]]],
            tooltip: str,
            mode: str = "used",
        ) -> None:
            pass

        def notify(self, title: str, message: str, warning: bool = False) -> None:
            if sys.platform != "darwin":
                return
            try:
                esc_t = title.replace("\\", "\\\\").replace('"', '\\"')
                esc_m = message.replace("\\", "\\\\").replace('"', '\\"')
                sound = ' sound name "Submarine"' if warning else ""
                script = f'display notification "{esc_m}" with title "{esc_t}"{sound}'
                subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        def stop(self) -> None:
            pass
else:
    from ctypes import wintypes

    # Module-private WinDLL handles so argtypes never collide with win11_ui / hud_app
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    WM_DESTROY = 0x0002
    WM_CLOSE = 0x0010
    WM_COMMAND = 0x0111
    WM_NULL = 0x0000
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205
    WM_CONTEXTMENU = 0x007B
    WM_APP = 0x8000
    WM_TRAYICON = WM_APP + 1
    WM_TRAY_UPDATE = WM_APP + 2
    WM_TRAY_NOTIFY = WM_APP + 3

    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002

    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_INFO = 0x00000010

    NIIF_INFO = 0x00000001
    NIIF_WARNING = 0x00000002

    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010

    MF_STRING = 0x00000000
    MF_SEPARATOR = 0x00000800
    MF_CHECKED = 0x00000008
    MF_UNCHECKED = 0x00000000

    TPM_LEFTALIGN = 0x0000
    TPM_BOTTOMALIGN = 0x0020
    TPM_RIGHTBUTTON = 0x0002
    TPM_NONOTIFY = 0x0080
    TPM_RETURNCMD = 0x0100

    CMD_TOGGLE_SHOW = 1001
    CMD_TOGGLE_TOPMOST = 1002
    CMD_TOGGLE_EXPAND = 1003
    CMD_SNAP_TASKBAR = 1004
    CMD_MANUAL_EDIT = 1005
    CMD_TOGGLE_STARTUP = 1006
    CMD_QUIT = 1099


    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]


    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]


    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("uTimeoutOrVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", GUID),
            ("hBalloonIcon", wintypes.HICON),
        ]


    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", POINT),
        ]


    # Configure 64-bit safe Win32 signatures
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT

    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM

    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND

    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL

    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None

    user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL

    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL

    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = LRESULT

    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE

    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL

    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wintypes.HMENU

    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL

    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, wintypes.HWND, wintypes.LPVOID,
    ]
    user32.TrackPopupMenu.restype = wintypes.BOOL

    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL

    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL

    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL

    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL


    def _bar_color(
        pct: Optional[float], accent: tuple[int, int, int], mode: str = "used"
    ) -> tuple[int, int, int, int]:
        if pct is None:
            return (100, 116, 139, 255)
        if mode == "used":
            if pct >= 90.0:
                return (239, 68, 68, 255)
            if pct >= 75.0:
                return (245, 158, 11, 255)
            return (accent[0], accent[1], accent[2], 255)
        if pct <= 10.0:
            return (239, 68, 68, 255)
        if pct <= 25.0:
            return (245, 158, 11, 255)
        return (accent[0], accent[1], accent[2], 255)


    PROVIDER_TRAY_ACCENTS: Dict[str, tuple[int, int, int]] = {
        "antigravity": (79, 156, 249),  # Google/Antigravity Blue
        "claude": (224, 122, 95),       # Anthropic Terracotta Coral
        "codex": (16, 185, 129),        # OpenAI Emerald Green
    }


    def render_tray_ico(
        icon_path: Path,
        bars: list[tuple[str, Optional[float]]],
        mode: str = "used",
    ) -> Path:
        """Render a crisp 64x64 gauge icon with 1, 2, or 3 bars matching active providers."""
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Rounded dark badge
        draw.rounded_rectangle([2, 2, size - 3, size - 3], radius=14, fill=(18, 22, 31, 255), outline=(58, 70, 94, 255), width=3)

        if not bars:
            bars = [("antigravity", None), ("claude", None)]

        track_x0, track_x1 = 11, size - 12
        bar_w = track_x1 - track_x0
        n = len(bars)

        if n == 1:
            slots = [(23, 41, 7)]
        elif n == 2:
            slots = [(15, 28, 5), (36, 49, 5)]
        else:
            slots = [(12, 22, 4), (27, 37, 4), (42, 52, 4)]

        for (prov, pct), (y0, y1, rad) in zip(bars[:3], slots):
            accent = PROVIDER_TRAY_ACCENTS.get(prov, (56, 189, 248))
            draw.rounded_rectangle([track_x0, y0, track_x1, y1], radius=rad, fill=(40, 48, 66, 255))
            if pct is None:
                cy = (y0 + y1) // 2
                draw.ellipse([track_x0 + 2, cy - 3, track_x0 + 8, cy + 3], fill=(accent[0], accent[1], accent[2], 190))
            elif pct > 0.0:
                fill = max(0.14, min(1.0, pct / 100.0))
                draw.rounded_rectangle(
                    [track_x0, y0, track_x0 + int(bar_w * fill), y1],
                    radius=rad,
                    fill=_bar_color(pct, accent, mode=mode),
                )
            else:
                cy = (y0 + y1) // 2
                draw.ellipse([track_x0 + 2, cy - 3, track_x0 + 8, cy + 3], fill=_bar_color(0.0, accent, mode=mode))

        icon_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(icon_path), format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
        return icon_path


    class WinTrayIcon:
        """Runs a native Win32 system tray icon on a dedicated daemon thread."""

        def __init__(
            self,
            icon_path: Path,
            on_action: Callable[[str], None],
            get_flags: Callable[[], Dict[str, bool]],
        ) -> None:
            self._icon_path = icon_path
            self._on_action = on_action
            self._get_flags = get_flags

            self._lock = threading.Lock()
            self._bars: list[tuple[str, Optional[float]]] = [("antigravity", None), ("claude", None)]
            self._mode: str = "used"
            self._tooltip: str = "AI Usage Bar"
            self._pending_notice: Optional[tuple[str, str, bool]] = None

            self._hwnd: Optional[int] = None
            self._hicon: Optional[int] = None
            self._taskbar_created_msg: int = 0
            self._wndproc_ref = WNDPROC(self._wnd_proc)
            self._ready = threading.Event()
            self._thread = threading.Thread(target=self._run_loop, name="WinTrayThread", daemon=True)

        def start(self) -> None:
            self._thread.start()
            self._ready.wait(timeout=3.0)

        def update(
            self,
            bars: list[tuple[str, Optional[float]]],
            tooltip: str,
            mode: str = "used",
        ) -> None:
            with self._lock:
                self._bars = list(bars)
                self._mode = mode
                self._tooltip = tooltip[:127]
                hwnd = self._hwnd
            if hwnd:
                user32.PostMessageW(hwnd, WM_TRAY_UPDATE, 0, 0)

        def notify(self, title: str, message: str, warning: bool = False) -> None:
            with self._lock:
                self._pending_notice = (title[:63], message[:255], warning)
                hwnd = self._hwnd
            if hwnd:
                user32.PostMessageW(hwnd, WM_TRAY_NOTIFY, 0, 0)

        def stop(self) -> None:
            hwnd = self._hwnd
            if hwnd:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            if self._thread.is_alive():
                self._thread.join(timeout=2.0)

        def _load_rendered_icon(self) -> int:
            with self._lock:
                bars = list(self._bars)
                mode = self._mode
            render_tray_ico(self._icon_path, bars, mode=mode)
            hicon = user32.LoadImageW(None, str(self._icon_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            return int(hicon) if hicon else 0

        def _make_nid(self, hicon: int, tooltip: str) -> NOTIFYICONDATAW:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = hicon
            nid.szTip = tooltip[:127]
            return nid

        def _add_or_modify_icon(self, add: bool) -> None:
            new_hicon = self._load_rendered_icon()
            with self._lock:
                tip = self._tooltip
            nid = self._make_nid(new_hicon, tip)
            shell32.Shell_NotifyIconW(NIM_ADD if add else NIM_MODIFY, ctypes.byref(nid))
            old_hicon = self._hicon
            self._hicon = new_hicon
            if old_hicon and old_hicon != new_hicon:
                user32.DestroyIcon(old_hicon)

        def _send_balloon(self) -> None:
            with self._lock:
                notice = self._pending_notice
                self._pending_notice = None
            if not notice or not self._hwnd:
                return
            title, message, warning = notice
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._hwnd
            nid.uID = 1
            nid.uFlags = NIF_INFO
            nid.szInfoTitle = title[:63]
            nid.szInfo = message[:255]
            nid.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

        def _remove_icon(self) -> None:
            if self._hwnd:
                nid = NOTIFYICONDATAW()
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = self._hwnd
                nid.uID = 1
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            if self._hicon:
                user32.DestroyIcon(self._hicon)
                self._hicon = None

        def _show_context_menu(self) -> None:
            flags = self._get_flags()
            visible = flags.get("visible", True)
            topmost = flags.get("topmost", True)
            expanded = flags.get("expanded", False)
            startup = flags.get("startup", False)

            hmenu = user32.CreatePopupMenu()
            if not hmenu:
                return
            try:
                user32.AppendMenuW(hmenu, MF_STRING, CMD_TOGGLE_SHOW, "위젯 숨기기" if visible else "위젯 보이기")
                user32.AppendMenuW(
                    hmenu,
                    MF_STRING | (MF_CHECKED if topmost else MF_UNCHECKED),
                    CMD_TOGGLE_TOPMOST,
                    "항상 최상위 고정",
                )
                user32.AppendMenuW(
                    hmenu,
                    MF_STRING | (MF_CHECKED if expanded else MF_UNCHECKED),
                    CMD_TOGGLE_EXPAND,
                    "상세 보기",
                )
                user32.AppendMenuW(hmenu, MF_STRING, CMD_SNAP_TASKBAR, "작업표시줄 위로 이동")
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                user32.AppendMenuW(hmenu, MF_STRING, CMD_MANUAL_EDIT, "잔여량 수동 입력...")
                user32.AppendMenuW(
                    hmenu,
                    MF_STRING | (MF_CHECKED if startup else MF_UNCHECKED),
                    CMD_TOGGLE_STARTUP,
                    "Windows 시작 시 자동 실행",
                )
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                user32.AppendMenuW(hmenu, MF_STRING, CMD_QUIT, "종료")

                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                user32.SetForegroundWindow(self._hwnd)
                cmd = user32.TrackPopupMenu(
                    hmenu,
                    TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                    pt.x,
                    pt.y,
                    0,
                    self._hwnd,
                    None,
                )
                user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
                if cmd:
                    self._dispatch_command(int(cmd))
            finally:
                user32.DestroyMenu(hmenu)

        def _dispatch_command(self, cmd: int) -> None:
            mapping = {
                CMD_TOGGLE_SHOW: "toggle_show",
                CMD_TOGGLE_TOPMOST: "toggle_topmost",
                CMD_TOGGLE_EXPAND: "toggle_expand",
                CMD_SNAP_TASKBAR: "snap_taskbar",
                CMD_MANUAL_EDIT: "manual_edit",
                CMD_TOGGLE_STARTUP: "toggle_startup",
                CMD_QUIT: "quit",
            }
            action = mapping.get(cmd)
            if action:
                self._on_action(action)

        def _wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == self._taskbar_created_msg and self._taskbar_created_msg != 0:
                self._add_or_modify_icon(add=True)
                return 0
            if msg == WM_TRAYICON:
                evt = lparam & 0xFFFF
                if evt == WM_LBUTTONUP:
                    self._on_action("toggle_show")
                    return 0
                if evt in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    pt = POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    user32.SetForegroundWindow(self._hwnd)
                    self._on_action(f"tray_menu:{pt.x}:{pt.y}")
                    return 0
            elif msg == WM_TRAY_UPDATE:
                self._add_or_modify_icon(add=False)
                return 0
            elif msg == WM_TRAY_NOTIFY:
                self._send_balloon()
                return 0
            elif msg == WM_CLOSE:
                self._remove_icon()
                user32.DestroyWindow(hwnd)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        def _run_loop(self) -> None:
            hinst = kernel32.GetModuleHandleW(None)
            class_name = f"AIUsageBarTray_{id(self)}"
            self._taskbar_created_msg = user32.RegisterWindowMessageW("TaskbarCreated")

            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = hinst
            wc.lpszClassName = class_name
            user32.RegisterClassW(ctypes.byref(wc))

            self._hwnd = user32.CreateWindowExW(
                0, class_name, "AIUsageBarTray", 0,
                0, 0, 0, 0,
                None, None, hinst, None,
            )
            if self._hwnd:
                self._add_or_modify_icon(add=True)
            self._ready.set()

            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            self._hwnd = None
