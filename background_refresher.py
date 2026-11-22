"""Silent zero-deduction background quota refresher using official agy & claude CLIs
inside a hidden Windows ConPTY (or POSIX pty on macOS).

- Antigravity: starts official `agy` headlessly until the statusLine hook updates
  `quota_state.json` (~0.7s, 0 prompts, zero quota deducted).
- Claude: starts official `claude --strict-mcp-config` inside an already-trusted workspace
  (read-only lookup from ~/.claude.json, never modifying trust), sends `/usage`, emulates
  the minimal VT100 screen grid to capture Current session, Current week (all models),
  and Current week (Fable) with zero quota deducted.
"""

from __future__ import annotations

import atexit
import ctypes
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from hooks_manager import find_agy_cli, find_claude_cli, find_codex_cli
from i18n import tr
from state_store import DATA_DIR, STATE_PATH, clamp_pct, load_state, parse_timestamp, update_provider_state

if sys.platform == "win32":
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
else:
    kernel32 = None
    _user32 = None

PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
STARTF_USESHOWWINDOW = 0x00000001
STARTF_USESTDHANDLES = 0x00000100
SW_HIDE = 0
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
DESKTOP_ALL_ACCESS = 0x000F01FF
HIDDEN_DESKTOP_NAME = "AIUsageBar_HiddenDesk"


if sys.platform == "win32":
    class _COORD(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _STARTUPINFOW),
            ("lpAttributeList", wintypes.LPVOID),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    # Configure 64-bit safe Win32 signatures
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SECURITY_ATTRIBUTES),
        wintypes.DWORD,
    ]
    kernel32.CreatePipe.restype = wintypes.BOOL

    kernel32.CreatePseudoConsole.argtypes = [
        _COORD, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
    ]
    kernel32.CreatePseudoConsole.restype = ctypes.c_long

    kernel32.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
    kernel32.ClosePseudoConsole.restype = None

    kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL

    kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t,
        wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID,
    ]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL

    kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    kernel32.DeleteProcThreadAttributeList.restype = None

    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
        wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOEXW), ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL

    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL

    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID
    ]
    kernel32.ReadFile.restype = wintypes.BOOL

    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID
    ]
    kernel32.WriteFile.restype = wintypes.BOOL

    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL

    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD

    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL

    _user32.CreateDesktopW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    ]
    _user32.CreateDesktopW.restype = wintypes.HANDLE

    _user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    _user32.CloseDesktop.restype = wintypes.BOOL


_hidden_desk_lock = threading.Lock()
_hidden_desk_handle: Optional[int] = None


def _ensure_hidden_desktop() -> Optional[str]:
    """Create/keep an invisible Win32 Desktop so child & grandchild console processes
    (cmd.exe, conhost.exe, git.exe, reg.exe, bash.exe) can NEVER flash on the user's screen.
    """
    global _hidden_desk_handle
    if sys.platform != "win32" or _user32 is None:
        return None
    with _hidden_desk_lock:
        if _hidden_desk_handle:
            return HIDDEN_DESKTOP_NAME
        try:
            h = _user32.CreateDesktopW(HIDDEN_DESKTOP_NAME, None, None, 0, DESKTOP_ALL_ACCESS, None)
            if h:
                _hidden_desk_handle = int(h)
                return HIDDEN_DESKTOP_NAME
        except Exception:
            pass
    return None


def _close_hidden_desktop() -> None:
    global _hidden_desk_handle
    if sys.platform != "win32" or _user32 is None:
        return
    with _hidden_desk_lock:
        if _hidden_desk_handle:
            try:
                _user32.CloseDesktop(wintypes.HANDLE(_hidden_desk_handle))
            except Exception:
                pass
            _hidden_desk_handle = None


atexit.register(_close_hidden_desktop)


def _run_hidden_capture(cmd_line: str, cwd: Optional[str] = None, timeout: float = 5.0) -> Tuple[int, str]:
    """Run a short CLI command on the isolated hidden Win32 Desktop and capture stdout."""
    if sys.platform != "win32" or kernel32 is None:
        proc = subprocess.run(
            shlex.split(cmd_line),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or ""

    out_r, out_w = wintypes.HANDLE(), wintypes.HANDLE()
    sa = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
    if not kernel32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), ctypes.byref(sa), 0):
        return -1, ""
    # Prevent child from inheriting the read end so EOF arrives cleanly on exit
    kernel32.SetHandleInformation(out_r, 0x00000001, 0)

    si = _STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOW)
    si.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
    si.StartupInfo.wShowWindow = SW_HIDE
    si.StartupInfo.hStdOutput = out_w
    si.StartupInfo.hStdError = out_w
    hidden_desk = _ensure_hidden_desktop()
    if hidden_desk:
        si.StartupInfo.lpDesktop = hidden_desk

    pi = _PROCESS_INFORMATION()
    hjob = kernel32.CreateJobObjectW(None, None)
    if hjob:
        jinfo = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        jinfo.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            hjob, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(jinfo), ctypes.sizeof(jinfo)
        ):
            kernel32.CloseHandle(hjob)
            hjob = None

    cmd_buf = ctypes.create_unicode_buffer(cmd_line)
    ok = kernel32.CreateProcessW(
        None, cmd_buf, None, None, True,
        CREATE_NO_WINDOW | CREATE_SUSPENDED,
        None, cwd, ctypes.byref(si), ctypes.byref(pi),
    )
    kernel32.CloseHandle(out_w)
    if not ok:
        if hjob:
            kernel32.CloseHandle(hjob)
        kernel32.CloseHandle(out_r)
        return -1, ""

    if hjob:
        if not kernel32.AssignProcessToJobObject(hjob, pi.hProcess):
            kernel32.CloseHandle(hjob)
            hjob = None
    kernel32.ResumeThread(pi.hThread)

    chunks: List[bytes] = []
    deadline = time.time() + timeout
    exit_code = -1
    try:
        while time.time() < deadline:
            avail = wintypes.DWORD(0)
            while kernel32.PeekNamedPipe(out_r, None, 0, None, ctypes.byref(avail), None) and avail.value > 0:
                buf = ctypes.create_string_buffer(min(avail.value, 65536))
                read = wintypes.DWORD(0)
                if not kernel32.ReadFile(out_r, buf, len(buf), ctypes.byref(read), None) or read.value == 0:
                    break
                chunks.append(buf.raw[: read.value])
            ec = wintypes.DWORD(0)
            if kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(ec)) and ec.value != 259:
                exit_code = int(ec.value)
                # Drain any remaining buffered stdout
                while kernel32.PeekNamedPipe(out_r, None, 0, None, ctypes.byref(avail), None) and avail.value > 0:
                    buf = ctypes.create_string_buffer(min(avail.value, 65536))
                    read = wintypes.DWORD(0)
                    if not kernel32.ReadFile(out_r, buf, len(buf), ctypes.byref(read), None) or read.value == 0:
                        break
                    chunks.append(buf.raw[: read.value])
                break
            time.sleep(0.03)
    finally:
        if hjob:
            kernel32.TerminateJobObject(hjob, 0)
            kernel32.CloseHandle(hjob)
        kernel32.TerminateProcess(pi.hProcess, 0)
        kernel32.WaitForSingleObject(pi.hProcess, 400)
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(out_r)

    return exit_code, b"".join(chunks).decode("utf-8", errors="replace")


# Minimal VT100 screen grid so Ink TUI cursor-positioned diff redraws merge cleanly
class _VTScreen:
    def __init__(self, cols: int = 120, rows: int = 45) -> None:
        self.cols = cols
        self.rows = rows
        self.grid: List[List[str]] = [[" "] * cols for _ in range(rows)]
        self.r = 0
        self.c = 0
        self._buf = ""

    def feed(self, text: str) -> None:
        s = self._buf + text
        self._buf = ""
        i = 0
        n = len(s)
        while i < n:
            ch = s[i]
            if ch == "\x1b":
                if i + 1 >= n:
                    self._buf = s[i:]
                    return
                nxt = s[i + 1]
                if nxt == "[":
                    # CSI sequence: \x1b[ params final
                    j = i + 2
                    while j < n and not ("@" <= s[j] <= "~"):
                        j += 1
                    if j >= n:
                        self._buf = s[i:]
                        return
                    params = s[i + 2 : j]
                    cmd = s[j]
                    self._handle_csi(params, cmd)
                    i = j + 1
                    continue
                elif nxt == "]":
                    # OSC sequence terminated by BEL (\x07) or ST (\x1b\\)
                    end_bel = s.find("\x07", i + 2)
                    end_st = s.find("\x1b\\", i + 2)
                    if end_bel == -1 and end_st == -1:
                        self._buf = s[i:]
                        return
                    if end_bel != -1 and (end_st == -1 or end_bel < end_st):
                        i = end_bel + 1
                    else:
                        i = end_st + 2
                    continue
                else:
                    i += 2
                    continue
            elif ch == "\r":
                self.c = 0
            elif ch == "\n":
                self.r = min(self.rows - 1, self.r + 1)
            elif ch == "\b":
                self.c = max(0, self.c - 1)
            elif ch >= " ":
                if 0 <= self.r < self.rows and 0 <= self.c < self.cols:
                    self.grid[self.r][self.c] = ch
                self.c = min(self.cols - 1, self.c + 1)
            i += 1

    def _parse_nums(self, params: str) -> List[int]:
        clean = params.lstrip("?>=!")
        if not clean:
            return []
        out = []
        for part in clean.split(";"):
            try:
                out.append(int(part) if part else 0)
            except ValueError:
                out.append(0)
        return out

    def _handle_csi(self, params: str, cmd: str) -> None:
        if params.startswith("?"):
            return
        nums = self._parse_nums(params)
        if cmd in ("H", "f"):
            row = (nums[0] if len(nums) >= 1 and nums[0] > 0 else 1) - 1
            col = (nums[1] if len(nums) >= 2 and nums[1] > 0 else 1) - 1
            self.r = max(0, min(self.rows - 1, row))
            self.c = max(0, min(self.cols - 1, col))
        elif cmd == "A":
            self.r = max(0, self.r - (nums[0] if nums and nums[0] > 0 else 1))
        elif cmd == "B":
            self.r = min(self.rows - 1, self.r + (nums[0] if nums and nums[0] > 0 else 1))
        elif cmd == "C":
            self.c = min(self.cols - 1, self.c + (nums[0] if nums and nums[0] > 0 else 1))
        elif cmd == "D":
            self.c = max(0, self.c - (nums[0] if nums and nums[0] > 0 else 1))
        elif cmd == "G":
            col = (nums[0] if nums and nums[0] > 0 else 1) - 1
            self.c = max(0, min(self.cols - 1, col))
        elif cmd == "J":
            mode = nums[0] if nums else 0
            if mode == 2:
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
            elif mode == 0:
                for c in range(self.c, self.cols):
                    self.grid[self.r][c] = " "
                for r in range(self.r + 1, self.rows):
                    self.grid[r] = [" "] * self.cols
        elif cmd == "K":
            mode = nums[0] if nums else 0
            if mode == 0:
                for c in range(self.c, self.cols):
                    self.grid[self.r][c] = " "
            elif mode == 1:
                for c in range(0, self.c + 1):
                    self.grid[self.r][c] = " "
            elif mode == 2:
                self.grid[self.r] = [" "] * self.cols

    def text(self) -> str:
        return "\n".join("".join(row).rstrip() for row in self.grid)


def _spawn_posix_pty(
    cmd_line: str,
    cwd: str,
    cols: int,
    rows: int,
    timeout: float,
    on_tick: Callable[[_VTScreen, float, Callable[[bytes], None]], bool],
) -> _VTScreen:
    """POSIX (macOS / Linux) pseudo-terminal runner using stdlib pty + select."""
    import fcntl
    import pty
    import select
    import signal
    import struct
    import termios

    argv = shlex.split(cmd_line)
    pid, master_fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(cwd)
            os.environ.setdefault("TERM", "xterm-256color")
            os.execvp(argv[0], argv)
        except Exception:
            os._exit(127)

    try:
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass

    def send_bytes(data: bytes) -> None:
        try:
            os.write(master_fd, data)
        except OSError:
            pass

    screen = _VTScreen(cols=cols, rows=rows)
    start = time.time()
    try:
        while time.time() - start < timeout:
            rlist, _, _ = select.select([master_fd], [], [], 0.08)
            if rlist:
                try:
                    raw_chunk = os.read(master_fd, 65536)
                except OSError:
                    break
                if not raw_chunk:
                    break
                if b"\x1b[6n" in raw_chunk:
                    send_bytes(b"\x1b[1;1R")
                screen.feed(raw_chunk.decode("utf-8", errors="replace"))
            if on_tick(screen, time.time() - start, send_bytes):
                break
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                break
    finally:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except Exception:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass

    return screen


def _spawn_conpty(
    cmd_line: str,
    cwd: str,
    cols: int,
    rows: int,
    timeout: float,
    on_tick: Callable[[_VTScreen, float, Callable[[bytes], None]], bool],
) -> _VTScreen:
    """Run a CLI inside a hidden PTY (Windows ConPTY or macOS/POSIX pty)."""
    if sys.platform != "win32":
        return _spawn_posix_pty(cmd_line, cwd, cols, rows, timeout, on_tick)
    in_r, in_w = wintypes.HANDLE(), wintypes.HANDLE()
    out_r, out_w = wintypes.HANDLE(), wintypes.HANDLE()
    sa = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
    if not kernel32.CreatePipe(ctypes.byref(in_r), ctypes.byref(in_w), ctypes.byref(sa), 0):
        raise OSError("CreatePipe(in) failed")
    if not kernel32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), ctypes.byref(sa), 0):
        kernel32.CloseHandle(in_r)
        kernel32.CloseHandle(in_w)
        raise OSError("CreatePipe(out) failed")

    hpc = wintypes.HANDLE()
    hr = kernel32.CreatePseudoConsole(_COORD(cols, rows), in_r, out_w, 0, ctypes.byref(hpc))
    kernel32.CloseHandle(in_r)
    kernel32.CloseHandle(out_w)
    if hr != 0:
        kernel32.CloseHandle(in_w)
        kernel32.CloseHandle(out_r)
        raise OSError(f"CreatePseudoConsole failed: {hr}")

    attr_size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
    attr_buf = ctypes.create_string_buffer(attr_size.value)
    kernel32.InitializeProcThreadAttributeList(attr_buf, 1, 0, ctypes.byref(attr_size))
    kernel32.UpdateProcThreadAttribute(
        attr_buf, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
        hpc.value, ctypes.sizeof(wintypes.HANDLE), None, None,
    )

    si = _STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
    # CRITICAL on Windows 11 GUI apps:
    # 1. Assign an isolated invisible Win32 Desktop (`lpDesktop`) so ALL child AND grandchild
    #    console processes (cmd.exe, conhost.exe, git.exe, reg.exe, bash.exe, node.exe) are
    #    kernel-isolated from the user's interactive Desktop and can NEVER flash on screen.
    # 2. Also set STARTF_USESHOWWINDOW + SW_HIDE as a secondary fallback.
    hidden_desk = _ensure_hidden_desktop()
    if hidden_desk:
        si.StartupInfo.lpDesktop = hidden_desk
    si.StartupInfo.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
    si.StartupInfo.wShowWindow = SW_HIDE
    si.lpAttributeList = ctypes.addressof(attr_buf)
    pi = _PROCESS_INFORMATION()

    hjob = kernel32.CreateJobObjectW(None, None)
    if hjob:
        jinfo = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        jinfo.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            hjob, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(jinfo), ctypes.sizeof(jinfo)
        ):
            kernel32.CloseHandle(hjob)
            hjob = None

    cmd_buf = ctypes.create_unicode_buffer(cmd_line)
    ok = kernel32.CreateProcessW(
        None, cmd_buf, None, None, False,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED,
        None, cwd, ctypes.byref(si), ctypes.byref(pi),
    )
    if not ok:
        if hjob:
            kernel32.CloseHandle(hjob)
        kernel32.ClosePseudoConsole(hpc)
        kernel32.DeleteProcThreadAttributeList(attr_buf)
        kernel32.CloseHandle(in_w)
        kernel32.CloseHandle(out_r)
        raise OSError(f"CreateProcessW failed: {ctypes.GetLastError()}")

    if hjob:
        # Nested jobs are supported on Win8+; ignore failure gracefully and still resume
        if not kernel32.AssignProcessToJobObject(hjob, pi.hProcess):
            kernel32.CloseHandle(hjob)
            hjob = None
    kernel32.ResumeThread(pi.hThread)

    def send_bytes(data: bytes) -> None:
        written = wintypes.DWORD(0)
        kernel32.WriteFile(in_w, data, len(data), ctypes.byref(written), None)

    screen = _VTScreen(cols=cols, rows=rows)
    start = time.time()
    try:
        while time.time() - start < timeout:
            avail = wintypes.DWORD(0)
            while kernel32.PeekNamedPipe(out_r, None, 0, None, ctypes.byref(avail), None) and avail.value > 0:
                buf = ctypes.create_string_buffer(min(avail.value, 65536))
                read = wintypes.DWORD(0)
                if not kernel32.ReadFile(out_r, buf, len(buf), ctypes.byref(read), None) or read.value == 0:
                    break
                raw_chunk = buf.raw[: read.value]
                if b"\x1b[6n" in raw_chunk:
                    send_bytes(b"\x1b[1;1R")
                screen.feed(raw_chunk.decode("utf-8", errors="replace"))

            if on_tick(screen, time.time() - start, send_bytes):
                break

            ec = wintypes.DWORD(0)
            if kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(ec)) and ec.value != 259:
                break
            time.sleep(0.08)
    finally:
        if hjob:
            kernel32.TerminateJobObject(hjob, 0)
            kernel32.CloseHandle(hjob)
        kernel32.TerminateProcess(pi.hProcess, 0)
        kernel32.WaitForSingleObject(pi.hProcess, 600)
        kernel32.ClosePseudoConsole(hpc)
        kernel32.DeleteProcThreadAttributeList(attr_buf)
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(in_w)
        kernel32.CloseHandle(out_r)

    return screen


# ------------------------------------------------------------------ Antigravity silent refresh
def _snapshot_agy_logs() -> tuple[Path, set[str]]:
    log_dir = Path.home() / ".gemini" / "antigravity-cli" / "log"
    if not log_dir.exists():
        return log_dir, set()
    try:
        return log_dir, {p.name for p in log_dir.glob("cli-*.log")}
    except OSError:
        return log_dir, set()


def _cleanup_new_agy_logs(log_dir: Path, before_names: set[str]) -> None:
    if not log_dir.exists():
        return
    try:
        new_files = [p for p in log_dir.glob("cli-*.log") if p.name not in before_names]
    except OSError:
        return
    for p in new_files:
        for _ in range(3):
            try:
                p.unlink(missing_ok=True)
                break
            except OSError:
                time.sleep(0.08)


def refresh_antigravity_silent(timeout: float = 12.0, lang: str = "ko") -> Tuple[bool, str]:
    agy_exe = find_agy_cli()
    if not agy_exe:
        return False, tr(lang, "ref_agy_missing")

    prev_state = load_state()
    prev_agy = prev_state.get("antigravity") or {}
    prev_qts = float(prev_agy.get("quota_updated_at") or prev_agy.get("updated_at") or 0.0)
    flags: Dict[str, Any] = {
        "sent_usage": False,
        "first_update_at": None,
        "seen_ts": prev_qts,
    }

    def _on_tick(_scr: _VTScreen, elapsed: float, send: Callable[[bytes], None]) -> bool:
        cur = load_state()
        cur_agy = cur.get("antigravity") or {}
        cur_qts = float(cur_agy.get("quota_updated_at") or 0.0)

        # Wait until agy completes login & server quota reload (quota_updated_at only bumps
        # when real quota buckets are received, never on the empty pre-login startup tick)
        if cur_qts > flags["seen_ts"]:
            flags["seen_ts"] = cur_qts
            if flags["first_update_at"] is None:
                flags["first_update_at"] = elapsed

        # If agy hasn't pushed fresh quota after 3.5s, trigger `/usage` explicitly
        if not flags["sent_usage"] and flags["first_update_at"] is None and elapsed >= 3.5:
            flags["sent_usage"] = True
            send(b"/usage\r")

        # Give 1.0s settle window after first quota update in case a second fresh fetch lands
        if flags["first_update_at"] is not None and (elapsed - flags["first_update_at"]) >= 1.0:
            return True
        return False

    log_dir, logs_before = _snapshot_agy_logs()
    scr: Optional[_VTScreen] = None
    try:
        scr = _spawn_conpty(f'"{agy_exe}"', str(Path.home()), 100, 30, timeout, _on_tick)
    except Exception as exc:
        return False, tr(lang, "ref_agy_err", exc=exc)
    finally:
        _cleanup_new_agy_logs(log_dir, logs_before)

    after = load_state()
    after_agy = after.get("antigravity") or {}
    after_qts = float(after_agy.get("quota_updated_at") or 0.0)
    if after_qts > prev_qts or flags["seen_ts"] > prev_qts:
        return True, tr(lang, "ref_agy_ok")

    if scr is not None:
        low = scr.text().lower()
        if "sign in" in low or "login" in low or "authenticate" in low:
            return False, tr(lang, "ref_agy_login")
    return False, tr(lang, "ref_agy_timeout")


# ------------------------------------------------------------------ Claude /usage silent refresh
def _find_trusted_claude_cwd() -> Optional[str]:
    """Read-only lookup of a directory already trusted by the user in ~/.claude.json."""
    cfg_path = Path.home() / ".claude.json"
    if not cfg_path.exists():
        return None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return None

    # Claude Code v2.1+ stores normalized forward-slash paths; prefer normal user dirs over Windows system dirs
    fwd_candidates: List[str] = []
    other_candidates: List[str] = []
    sys_fallback: List[str] = []
    for k, v in projects.items():
        if not isinstance(v, dict) or not v.get("hasTrustDialogAccepted"):
            continue
        p = Path(k)
        if not p.exists() or not p.is_dir():
            continue
        low_p = str(p).lower().replace("/", "\\")
        if low_p.startswith(("c:\\windows", "c:\\program files")):
            sys_fallback.append(str(p))
        elif "/" in k:
            fwd_candidates.append(str(p))
        else:
            other_candidates.append(str(p))

    if fwd_candidates:
        return fwd_candidates[0]
    if other_candidates:
        return other_candidates[0]
    if sys_fallback:
        return sys_fallback[0]
    return None


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_claude_reset_string(text: str, now_dt: Optional[datetime] = None) -> Optional[float]:
    """Parse strings like 'Resets 7:10pm (Asia/Seoul)' or 'Resets Nov 19, 3am (Asia/Seoul)'."""
    if now_dt is None:
        now_dt = datetime.now()
    s = text.strip()

    # Format 1: "Nov 19, 3am" or "Nov 19, 3:30pm"
    m = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        s,
        re.IGNORECASE,
    )
    if m:
        mon = _MONTHS[m.group(1)[:3].lower()]
        day = int(m.group(2))
        hr = int(m.group(3))
        mn = int(m.group(4) or 0)
        ampm = m.group(5).lower()
        if ampm == "pm" and hr != 12:
            hr += 12
        elif ampm == "am" and hr == 12:
            hr = 0
        year = now_dt.year
        try:
            dt = datetime(year, mon, day, hr, mn)
        except ValueError:
            return None
        # Handle Dec -> Jan year rollover
        if (dt - now_dt).total_seconds() < -30 * 86400:
            try:
                dt = datetime(year + 1, mon, day, hr, mn)
            except ValueError:
                return None
        return dt.timestamp()

    # Format 2: "7:10pm" or "3am" (today or tomorrow)
    m2 = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", s, re.IGNORECASE)
    if m2:
        hr = int(m2.group(1))
        mn = int(m2.group(2) or 0)
        ampm = m2.group(3).lower()
        if ampm == "pm" and hr != 12:
            hr += 12
        elif ampm == "am" and hr == 12:
            hr = 0
        dt = now_dt.replace(hour=hr, minute=mn, second=0, microsecond=0)
        if dt <= now_dt:
            dt += timedelta(days=1)
        return dt.timestamp()

    return None


def parse_claude_usage_screen(screen_text: str, now: Optional[float] = None) -> Dict[str, Any]:
    """Extract session_5h, weekly, and weekly_fable buckets from Claude `/usage` TUI text."""
    if now is None:
        now = time.time()
    now_dt = datetime.fromtimestamp(now)

    lines = [ln.strip() for ln in screen_text.splitlines() if ln.strip()]
    result: Dict[str, Any] = {}
    current_section: Optional[str] = None

    for ln in lines:
        low = ln.lower()
        if "current session" in low:
            current_section = "session_5h"
            result.setdefault(current_section, {})
            continue
        if "current week" in low and "all models" in low:
            current_section = "weekly"
            result.setdefault(current_section, {})
            continue
        if "current week" in low and "fable" in low:
            current_section = "weekly_fable"
            result.setdefault(current_section, {})
            continue
        if "current week" in low and ("sonnet" in low or "opus" in low):
            current_section = None
            continue
        if "usage credits" in low or "what's contributing" in low:
            current_section = None
            continue

        if current_section is None:
            continue

        m_pct = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*used", ln, re.IGNORECASE)
        if m_pct:
            used = clamp_pct(float(m_pct.group(1)))
            if used is not None:
                result[current_section]["used_pct"] = used
                result[current_section]["remaining_pct"] = clamp_pct(100.0 - used)
            continue

        if "reset" in low:
            ts = parse_claude_reset_string(ln, now_dt=now_dt)
            if ts is not None:
                result[current_section]["resets_at"] = ts

    # Keep only valid buckets that have remaining_pct
    cleaned: Dict[str, Any] = {}
    for k, v in result.items():
        if isinstance(v, dict) and v.get("remaining_pct") is not None:
            v.setdefault("resets_at", None)
            cleaned[k] = v
    return cleaned


def _ensure_claude_probe_settings() -> Optional[Path]:
    """Write a minimal settings override file disabling user hooks, plugins, and statusLine
    during silent `/usage` polling so background refreshes stay lightweight and never fire hooks.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe_path = DATA_DIR / ".claude_probe_settings.json"
        payload = json.dumps(
            {
                "disableAllHooks": True,
                "enabledPlugins": {},
                "statusLine": {"type": "command", "command": ""},
            },
            separators=(",", ":"),
        )
        if not probe_path.exists() or probe_path.read_text(encoding="utf-8", errors="ignore") != payload:
            probe_path.write_text(payload, encoding="utf-8")
        return probe_path
    except Exception:
        return None


def _check_claude_auth_status(claude_exe: str) -> Optional[bool]:
    """Fast 0.2s zero-ConPTY check via official `claude auth status` on hidden desktop.

    Returns:
      False -> definitively logged out or non-subscription API key only (skip ConPTY)
      True  -> logged in
      None  -> indeterminate (older CLI without `auth status`, fall through to /usage)
    """
    try:
        _rc, raw_out = _run_hidden_capture(f'"{claude_exe}" auth status', timeout=5.0)
        raw = (raw_out or "").strip()
        if raw.startswith("{"):
            info = json.loads(raw)
            if isinstance(info, dict) and "loggedIn" in info:
                if not info.get("loggedIn"):
                    return False
                if str(info.get("authMethod") or "").lower() in ("apikey", "api_key", "none"):
                    return False
                return True
    except Exception:
        pass
    return None


def refresh_claude_silent(timeout: float = 13.0, lang: str = "ko") -> Tuple[bool, str]:
    claude_exe = find_claude_cli()
    if not claude_exe:
        return False, tr(lang, "ref_cld_missing")

    # Fast zero-ConPTY auth check: avoids wasting 13s or spawning ConPTY when logged out
    if _check_claude_auth_status(claude_exe) is False:
        return False, tr(lang, "ref_cld_login")

    cwd = _find_trusted_claude_cwd()
    if not cwd:
        return False, tr(lang, "ref_cld_trust")

    def _run_usage_probe(cmd_line: str) -> _VTScreen:
        state_flags: Dict[str, Any] = {
            "ready_at": None,
            "sent_cmd": False,
            "sent_enter1": False,
            "sent_enter2": False,
            "saw_refreshing": False,
            "finished_at": None,
        }

        def _on_tick(scr: _VTScreen, elapsed: float, send: Callable[[bytes], None]) -> bool:
            txt = scr.text()
            low = txt.lower()
            if "unknown option" in low or "folder isn't trusted" in low or "quick safety check" in low:
                return True
            if "api usage billing" in low or "not logged in" in low:
                return True

            if state_flags["ready_at"] is None:
                if "❯" in txt or "claude code" in low or elapsed >= 4.0:
                    state_flags["ready_at"] = elapsed

            ra = state_flags["ready_at"]
            if ra is not None:
                since = elapsed - ra
                if not state_flags["sent_cmd"] and since >= 0.7:
                    state_flags["sent_cmd"] = True
                    send(b"/usage")
                if state_flags["sent_cmd"] and not state_flags["sent_enter1"] and since >= 1.3:
                    state_flags["sent_enter1"] = True
                    send(b"\r")
                if state_flags["sent_enter1"] and not state_flags["sent_enter2"] and since >= 2.0:
                    state_flags["sent_enter2"] = True
                    send(b"\r")

                if state_flags["sent_enter1"]:
                    if "estimated cost:" in low and "current week" not in low:
                        return True
                    if "refreshing usage" in low:
                        state_flags["saw_refreshing"] = True
                    has_data = ("current session" in low and "current week" in low and "% used" in low)
                    still_refreshing = "refreshing usage" in low
                    if has_data and not still_refreshing and (state_flags["saw_refreshing"] or since >= 5.2):
                        if state_flags["finished_at"] is None:
                            state_flags["finished_at"] = elapsed
                        elif elapsed - state_flags["finished_at"] >= 0.6:
                            return True
            return False

        return _spawn_conpty(cmd_line, cwd, 120, 45, timeout, _on_tick)

    probe_cfg = _ensure_claude_probe_settings()
    if probe_cfg is not None:
        primary_cmd = (
            f'"{claude_exe}" --strict-mcp-config --setting-sources "" '
            f'--settings "{probe_cfg}"'
        )
    else:
        primary_cmd = f'"{claude_exe}" --strict-mcp-config'

    try:
        scr = _run_usage_probe(primary_cmd)
        # Backwards-compatible fallback for older Claude Code versions without new flags
        low_out = scr.text().lower()
        if "unknown option" in low_out or "only works with" in low_out:
            scr = _run_usage_probe(f'"{claude_exe}" --strict-mcp-config')
    except Exception as exc:
        return False, tr(lang, "ref_cld_err", exc=exc)

    now = time.time()
    screen_text = scr.text()
    parsed = parse_claude_usage_screen(screen_text, now=now)
    if not parsed:
        low = screen_text.lower()
        if "folder isn't trusted" in low or "quick safety check" in low:
            return False, tr(lang, "ref_cld_trust_once")
        if any(
            k in low
            for k in (
                "api usage billing",
                "estimated cost:",
                "not logged in",
                "credit balance",
                "sign in",
                "api key",
                "login method",
            )
        ):
            return False, tr(lang, "ref_cld_login")
        return False, tr(lang, "ref_cld_timeout")

    patch: Dict[str, Any] = {
        "source": "claude_usage_auto",
        "updated_at": now,
        "quota_updated_at": now,
    }
    patch.update(parsed)
    update_provider_state("claude", patch)
    return True, tr(lang, "ref_cld_ok")


# ------------------------------------------------------------------ Codex silent refresh
def _parse_codex_window(obj: Any, now: float) -> Optional[Tuple[int, Dict[str, Any]]]:
    if not isinstance(obj, dict):
        return None
    used_raw = obj.get("usedPercent")
    if used_raw is None:
        used_raw = obj.get("used_percent")
    used = clamp_pct(used_raw)
    if used is None:
        return None
    rem = clamp_pct(100.0 - used)

    win_raw = obj.get("windowDurationMins")
    if win_raw is None:
        win_raw = obj.get("window_minutes")
    try:
        win_mins = int(win_raw) if win_raw is not None else 0
    except (TypeError, ValueError):
        win_mins = 0

    resets_at = parse_timestamp(
        obj.get("resetsAt") if obj.get("resetsAt") is not None else obj.get("resets_at"),
        fallback_in_seconds=obj.get("resetsInSeconds") or obj.get("resets_in_seconds"),
        now=now,
    )
    return win_mins, {
        "used_pct": used,
        "remaining_pct": rem,
        "resets_at": resets_at,
    }


def parse_codex_rate_limits(rl: Any, now: Optional[float] = None) -> Dict[str, Any]:
    """Parse Codex `rateLimits` (app-server or rollout JSONL schema) into weekly & session_5h."""
    if now is None:
        now = time.time()
    if not isinstance(rl, dict):
        return {}

    out: Dict[str, Any] = {}
    plan = rl.get("planType") or rl.get("plan_type")
    if plan:
        out["plan_tier"] = str(plan)

    for key in ("primary", "secondary"):
        parsed = _parse_codex_window(rl.get(key), now)
        if parsed is None:
            continue
        win_mins, bucket = parsed
        if win_mins >= 1440:
            out["weekly"] = bucket
        elif win_mins > 0:
            out["session_5h"] = bucket
        elif key == "secondary":
            out["weekly"] = bucket
        else:
            out["session_5h"] = bucket

    return out


def read_latest_codex_session_limits(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Read the newest non-empty `rate_limits` entry from ~/.codex/sessions/**/*.jsonl."""
    if now is None:
        now = time.time()
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        return None

    files = sorted(
        sessions_dir.rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in files[:5]:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for raw_line in reversed(lines):
            if "rate_limits" not in raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            rl = (obj.get("payload") or {}).get("rate_limits") if isinstance(obj.get("payload"), dict) else None
            if rl is None:
                rl = obj.get("rate_limits")
            parsed = parse_codex_rate_limits(rl, now=now)
            if parsed.get("weekly") or parsed.get("session_5h"):
                parsed["source"] = "codex_session_log"
                parsed["updated_at"] = path.stat().st_mtime
                return parsed
    return None


def _query_codex_app_server(codex_exe: str, timeout: float = 6.5) -> Optional[Dict[str, Any]]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    if codex_exe.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd.exe", "/c", codex_exe, "app-server"]
    else:
        cmd = [codex_exe, "app-server"]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        startupinfo=startupinfo,
    )
    line_q: queue.Queue[Optional[str]] = queue.Queue()

    def _reader() -> None:
        try:
            assert proc.stdout is not None
            for ln in proc.stdout:
                line_q.put(ln)
        except Exception:
            pass
        finally:
            line_q.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    try:
        assert proc.stdin is not None
        reqs = [
            {"method": "initialize", "id": 1, "params": {"clientInfo": {"name": "AIUsageBar", "version": "1.8.2"}}},
            {"method": "initialized", "params": {}},
            {"method": "account/rateLimits/read", "id": 2, "params": {}},
        ]
        for r in reqs:
            proc.stdin.write(json.dumps(r) + "\n")
        proc.stdin.flush()

        deadline = time.time() + timeout
        while time.time() < deadline:
            rem = max(0.05, deadline - time.time())
            try:
                ln = line_q.get(timeout=min(0.25, rem))
            except queue.Empty:
                continue
            if ln is None:
                break
            ln = ln.strip()
            if not ln:
                continue
            try:
                msg = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == 2 and isinstance(msg.get("result"), dict):
                res = msg["result"]
                rl = res.get("rateLimits")
                if not isinstance(rl, dict) and isinstance(res.get("rateLimitsByLimitId"), dict):
                    by_id = res["rateLimitsByLimitId"]
                    rl = by_id.get("codex") or (next(iter(by_id.values())) if by_id else None)
                now = time.time()
                parsed = parse_codex_rate_limits(rl, now=now)
                if parsed.get("weekly") or parsed.get("session_5h"):
                    parsed["source"] = "codex_app_server"
                    parsed["updated_at"] = now
                    return parsed
                return None
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=1.5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return None


def refresh_codex_silent(timeout: float = 7.0, lang: str = "ko") -> Tuple[bool, str]:
    now = time.time()
    codex_exe = find_codex_cli()
    if codex_exe:
        try:
            live = _query_codex_app_server(codex_exe, timeout=timeout)
            if live:
                update_provider_state("codex", live)
                return True, tr(lang, "ref_cdx_ok")
        except Exception:
            pass

    fallback = read_latest_codex_session_limits(now=now)
    if fallback:
        update_provider_state("codex", fallback)
        return True, tr(lang, "ref_cdx_log_ok")

    return False, tr(lang, "ref_cdx_missing")


def refresh_all_silent(enabled_providers: Optional[List[str]] = None, lang: str = "ko") -> Dict[str, Tuple[bool, str]]:
    targets = set(enabled_providers or ["antigravity", "claude"])
    results: Dict[str, Tuple[bool, str]] = {}
    if "antigravity" in targets:
        results["antigravity"] = refresh_antigravity_silent(lang=lang)
    if "claude" in targets:
        results["claude"] = refresh_claude_silent(lang=lang)
    if "codex" in targets:
        results["codex"] = refresh_codex_silent(lang=lang)
    return results
