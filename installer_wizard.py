"""AI Usage Bar — Standalone Bilingual (EN/KO) Windows Setup Wizard."""

from __future__ import annotations

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
import zipfile
from pathlib import Path
from typing import Optional

BASE_SCRIPT_DIR = Path(__file__).resolve().parent
if str(BASE_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_SCRIPT_DIR))

from hooks_manager import (
    APP_VERSION,
    create_windows_shortcut,
    desktop_shortcut_path,
    find_agy_cli,
    find_claude_cli,
    find_codex_cli,
    install_agy_hook,
    install_claude_hook,
    register_uninstall_entry,
    start_menu_dir,
    stop_running_hud_processes,
)
from i18n import detect_os_language, tr
from state_store import load_config, normalize_enabled_providers, save_config, set_startup_enabled
from win11_ui import apply_win11_dwm, get_hwnd

# Dark slate theme matching AI Usage Bar
BG_MAIN = "#11151D"
BG_PANEL = "#181E2A"
BG_CARD = "#1E2534"
BG_INPUT = "#252D3F"
BORDER = "#2C364B"

TEXT_PRI = "#F1F5F9"
TEXT_SEC = "#94A3B8"
TEXT_MUTED = "#64748B"

ACCENT = "#4F9CF9"
ACCENT_HOVER = "#7DD3FC"
ACCENT_CLAUDE = "#E07A5F"
GOOD = "#34D399"
WARN = "#F59E0B"
ERR = "#EF4444"


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.WinDLL("user32").SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except Exception:
            pass


def resource_path(rel_name: str) -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / rel_name
    for cand in (BASE_SCRIPT_DIR / "build" / rel_name, BASE_SCRIPT_DIR / "assets" / rel_name, BASE_SCRIPT_DIR / rel_name):
        if cand.exists():
            return cand
    return BASE_SCRIPT_DIR / rel_name


def default_install_dir() -> Path:
    local_app = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local_app) / "AIUsageBar"


class SetupWizardApp:
    def __init__(self) -> None:
        self.lang = detect_os_language()
        self._lang_overridden = False

        self.root = tk.Tk()
        self.root.title(self._t("wiz_title", ver=APP_VERSION))
        self.root.configure(bg=BG_MAIN)
        self.root.resizable(False, False)

        ico = resource_path("app_icon.ico")
        if ico.exists():
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass

        self.step = 0
        self.installing = False
        self.install_succeeded = False
        self._log_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        # Detect environment
        self.claude_path = find_claude_cli()
        self.agy_path = find_agy_cli()
        self.codex_path = find_codex_cli()

        # User options (persisted cleanly across language switches)
        self.var_install_dir = tk.StringVar(value=str(default_install_dir()))
        self.var_show_agy = tk.BooleanVar(value=True)
        self.var_show_claude = tk.BooleanVar(value=True)
        self.var_show_codex = tk.BooleanVar(value=(self.codex_path is not None))
        self.var_hook_claude = tk.BooleanVar(value=True)
        self.var_hook_agy = tk.BooleanVar(value=True)
        self.var_install_agy_cli = tk.BooleanVar(value=(self.agy_path is None))
        self.var_startup = tk.BooleanVar(value=True)
        self.var_desktop_shortcut = tk.BooleanVar(value=True)
        self.var_start_menu = tk.BooleanVar(value=True)
        self.var_launch_after = tk.BooleanVar(value=True)

        self._f_h1 = ("Malgun Gothic", 13, "bold")
        self._f_h2 = ("Malgun Gothic", 10, "bold")
        self._f_body = ("Malgun Gothic", 9)
        self._f_small = ("Malgun Gothic", 8)
        self._f_mono = ("Consolas", 8)

        self._fixed_w = 640
        self._fixed_h = 560

        self.root.withdraw()
        self._measure_and_center()
        self._build_layout()
        self._show_step(0)
        self.root.deiconify()
        apply_win11_dwm(get_hwnd(self.root), dark_titlebar=True)
        self.root.after(100, self._poll_queue)

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self.lang, key, **kwargs)

    def _set_lang(self, new_lang: str) -> None:
        if self.installing or new_lang == self.lang or new_lang not in ("ko", "en"):
            return
        self.lang = new_lang
        self._lang_overridden = True
        cur_step = self.step
        self._build_layout()
        self._show_step(cur_step)

    def _measure_and_center(self) -> None:
        """Measure max dimensions across all pages in BOTH KO and EN once, then lock size."""
        saved_lang = self.lang
        max_w = 640
        max_h = 550
        try:
            for probe_lang in ("ko", "en"):
                self.lang = probe_lang
                self._build_layout()
                for page in self._pages:
                    for p in self._pages:
                        p.pack_forget()
                    page.pack(fill="both", expand=True)
                    self.root.update_idletasks()
                    max_w = max(max_w, self.root.winfo_reqwidth() + 24)
                    max_h = max(max_h, self.root.winfo_reqheight() + 20)
        finally:
            self.lang = saved_lang

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self._fixed_w = min(max_w, sw - 60)
        self._fixed_h = min(max_h, sh - 80)
        x = max(20, (sw - self._fixed_w) // 2)
        y = max(20, (sh - self._fixed_h) // 2)
        self.root.minsize(self._fixed_w, self._fixed_h)
        self.root.maxsize(self._fixed_w, self._fixed_h)
        self.root.geometry(f"{self._fixed_w}x{self._fixed_h}+{x}+{y}")

    def _build_layout(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

        self.root.title(self._t("wiz_title", ver=APP_VERSION))

        # Top header banner
        header = tk.Frame(self.root, bg=BG_PANEL, padx=22, pady=13)
        header.pack(fill="x")

        title_row = tk.Frame(header, bg=BG_PANEL)
        title_row.pack(fill="x")
        tk.Label(
            title_row, text="AI Usage Bar", bg=BG_PANEL, fg=ACCENT, font=("Segoe UI", 13, "bold")
        ).pack(side="left")
        tk.Label(
            title_row, text=self._t("wiz_header_sub", ver=APP_VERSION), bg=BG_PANEL, fg=TEXT_PRI, font=("Malgun Gothic", 11, "bold")
        ).pack(side="left")

        # Bilingual language toggle pill in header right
        lang_box = tk.Frame(title_row, bg=BG_MAIN, padx=2, pady=2)
        lang_box.pack(side="right")
        for lcode, llbl in (("ko", "한국어"), ("en", "EN")):
            active = self.lang == lcode
            btn_l = tk.Label(
                lang_box,
                text=llbl,
                bg=BG_CARD if active else BG_MAIN,
                fg=ACCENT if active else TEXT_MUTED,
                font=self._f_small,
                padx=8,
                pady=2,
                cursor="hand2",
            )
            btn_l.pack(side="left", padx=1)
            btn_l.bind("<Button-1>", lambda _e, lc=lcode: self._set_lang(lc))

        # Stepper bar
        step_row = tk.Frame(header, bg=BG_PANEL)
        step_row.pack(fill="x", pady=(8, 0))
        self._step_labels = []
        for skey in ("wiz_step1", "wiz_step2", "wiz_step3", "wiz_step4"):
            lbl = tk.Label(step_row, text=self._t(skey), bg=BG_PANEL, fg=TEXT_MUTED, font=self._f_small, padx=8, pady=2)
            lbl.pack(side="left", padx=(0, 8))
            self._step_labels.append(lbl)

        tk.Frame(self.root, bg=BORDER, height=1).pack(side="top", fill="x")

        # Bottom navigation bar packed BEFORE content so it is NEVER pushed off-screen
        footer = tk.Frame(self.root, bg=BG_PANEL, padx=20, pady=12)
        footer.pack(side="bottom", fill="x")
        tk.Frame(self.root, bg=BORDER, height=1).pack(side="bottom", fill="x")

        self._btn_cancel = tk.Button(
            footer, text=self._t("wiz_cancel"), command=self._on_cancel,
            bg=BG_CARD, fg=TEXT_SEC, activebackground=BG_INPUT, activeforeground=TEXT_PRI,
            relief="flat", font=self._f_body, padx=14, pady=5, cursor="hand2"
        )
        self._btn_cancel.pack(side="left")

        self._btn_next = tk.Button(
            footer, text=self._t("wiz_next"), command=self._on_next,
            bg=ACCENT, fg="#0B1120", activebackground=ACCENT_HOVER, activeforeground="#0B1120",
            relief="flat", font=self._f_h2, padx=18, pady=5, cursor="hand2"
        )
        self._btn_next.pack(side="right")

        self._btn_back = tk.Button(
            footer, text=self._t("wiz_back"), command=self._on_back,
            bg=BG_CARD, fg=TEXT_SEC, activebackground=BG_INPUT, activeforeground=TEXT_PRI,
            relief="flat", font=self._f_body, padx=14, pady=5, cursor="hand2"
        )
        self._btn_back.pack(side="right", padx=(0, 8))

        # Content container fills remaining middle area
        self._content = tk.Frame(self.root, bg=BG_MAIN, padx=22, pady=15)
        self._content.pack(side="top", fill="both", expand=True)

        self._pages = [
            self._build_page_welcome(),
            self._build_page_options(),
            self._build_page_progress(),
            self._build_page_finish(),
        ]

    # ------------------------------------------------------------------ Pages
    def _build_page_welcome(self) -> tk.Frame:
        p = tk.Frame(self._content, bg=BG_MAIN)
        tk.Label(
            p, text=self._t("wiz_welcome_h1"),
            bg=BG_MAIN, fg=TEXT_PRI, font=self._f_h1, anchor="w"
        ).pack(fill="x", pady=(0, 8))

        tk.Label(
            p,
            text=self._t("wiz_welcome_sub"),
            bg=BG_MAIN, fg=TEXT_SEC, font=self._f_body, justify="left", anchor="w"
        ).pack(fill="x", pady=(0, 12))

        card = tk.Frame(p, bg=BG_CARD, padx=14, pady=11)
        card.pack(fill="x", pady=(0, 10))

        for tk_key, dk_key in (
            ("wiz_f1_t", "wiz_f1_d"),
            ("wiz_f2_t", "wiz_f2_d"),
            ("wiz_f3_t", "wiz_f3_d"),
            ("wiz_f4_t", "wiz_f4_d"),
        ):
            tk.Label(card, text=self._t(tk_key), bg=BG_CARD, fg=TEXT_PRI, font=self._f_h2, anchor="w").pack(fill="x")
            tk.Label(card, text="  " + self._t(dk_key), bg=BG_CARD, fg=TEXT_SEC, font=self._f_small, anchor="w").pack(fill="x", pady=(0, 6))

        tk.Label(
            p,
            text=self._t("wiz_welcome_foot"),
            bg=BG_MAIN, fg=TEXT_MUTED, font=self._f_small, anchor="w"
        ).pack(fill="x", pady=(4, 0))
        return p

    def _build_page_options(self) -> tk.Frame:
        p = tk.Frame(self._content, bg=BG_MAIN)

        # Environment detection box
        env_card = tk.Frame(p, bg=BG_CARD, padx=12, pady=9)
        env_card.pack(fill="x", pady=(0, 9))
        tk.Label(env_card, text=self._t("wiz_env_title"), bg=BG_CARD, fg=TEXT_PRI, font=self._f_h2, anchor="w").pack(fill="x", pady=(0, 4))

        for name, path, miss_key, miss_col in (
            ("Claude Code (claude)", self.claude_path, "wiz_not_found_claude", WARN),
            ("Antigravity CLI (agy)", self.agy_path, "wiz_not_found_agy", WARN),
            ("OpenAI Codex (codex)", self.codex_path, "wiz_not_found_codex", TEXT_MUTED),
        ):
            r = tk.Frame(env_card, bg=BG_CARD)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=name, bg=BG_CARD, fg=TEXT_SEC, font=self._f_small, width=22, anchor="w").pack(side="left")
            tk.Label(
                r,
                text=self._t("wiz_detected") if path else self._t(miss_key),
                bg=BG_CARD,
                fg=GOOD if path else miss_col,
                font=self._f_small,
            ).pack(side="left")

        # Provider display selector
        show_card = tk.Frame(p, bg=BG_CARD, padx=12, pady=7)
        show_card.pack(fill="x", pady=(0, 8))
        show_row = tk.Frame(show_card, bg=BG_CARD)
        show_row.pack(fill="x")
        tk.Label(show_row, text=self._t("wiz_show_ai"), bg=BG_CARD, fg=TEXT_PRI, font=self._f_h2).pack(side="left", padx=(0, 10))
        for txt, var in (("Antigravity", self.var_show_agy), ("Claude", self.var_show_claude), ("Codex", self.var_show_codex)):
            tk.Checkbutton(
                show_row, text=txt, variable=var,
                bg=BG_CARD, fg=TEXT_PRI, selectcolor=BG_INPUT,
                activebackground=BG_CARD, activeforeground=TEXT_PRI,
                font=self._f_small, cursor="hand2"
            ).pack(side="left", padx=(0, 10))

        # Checkboxes
        opt_card = tk.Frame(p, bg=BG_CARD, padx=12, pady=8)
        opt_card.pack(fill="x", pady=(0, 9))
        tk.Label(opt_card, text=self._t("wiz_opt_title"), bg=BG_CARD, fg=TEXT_PRI, font=self._f_h2, anchor="w").pack(fill="x", pady=(0, 4))

        def add_chk(text: str, var: tk.BooleanVar) -> None:
            tk.Checkbutton(
                opt_card, text=text, variable=var,
                bg=BG_CARD, fg=TEXT_PRI, selectcolor=BG_INPUT,
                activebackground=BG_CARD, activeforeground=TEXT_PRI,
                font=self._f_small, anchor="w", cursor="hand2"
            ).pack(fill="x", pady=1)

        add_chk(self._t("wiz_opt_claude"), self.var_hook_claude)
        add_chk(self._t("wiz_opt_agy"), self.var_hook_agy)
        add_chk(
            self._t("wiz_opt_agy_inst_done" if self.agy_path else "wiz_opt_agy_inst_rec"),
            self.var_install_agy_cli,
        )
        add_chk(self._t("wiz_opt_startup"), self.var_startup)
        add_chk(self._t("wiz_opt_desktop"), self.var_desktop_shortcut)
        add_chk(self._t("wiz_opt_startmenu"), self.var_start_menu)

        # Install folder
        dir_row = tk.Frame(p, bg=BG_MAIN)
        dir_row.pack(fill="x")
        tk.Label(dir_row, text=self._t("wiz_install_dir"), bg=BG_MAIN, fg=TEXT_SEC, font=self._f_small).pack(side="left", padx=(0, 8))
        tk.Entry(
            dir_row, textvariable=self.var_install_dir,
            bg=BG_INPUT, fg=TEXT_PRI, insertbackground=TEXT_PRI,
            relief="flat", font=self._f_small
        ).pack(side="left", fill="x", expand=True, ipady=4)
        tk.Button(
            dir_row, text=self._t("wiz_browse"), command=self._browse_dir,
            bg=BG_CARD, fg=TEXT_SEC, activebackground=BG_INPUT, activeforeground=TEXT_PRI,
            relief="flat", font=self._f_small, padx=10, pady=3, cursor="hand2"
        ).pack(side="left", padx=(6, 0))
        return p

    def _build_page_progress(self) -> tk.Frame:
        p = tk.Frame(self._content, bg=BG_MAIN)
        self._prog_title = tk.Label(
            p, text=self._t("wiz_prog_prep"), bg=BG_MAIN, fg=TEXT_PRI, font=self._f_h2, anchor="w"
        )
        self._prog_title.pack(fill="x", pady=(0, 8))

        self._prog_canvas = tk.Canvas(p, height=12, bg=BG_INPUT, highlightthickness=0)
        self._prog_canvas.pack(fill="x", pady=(0, 10))
        self._prog_pct = 0.0

        self._log_box = tk.Text(
            p, bg=BG_PANEL, fg=TEXT_SEC, font=self._f_mono,
            relief="flat", bd=0, padx=10, pady=8, height=13, state="disabled"
        )
        self._log_box.pack(fill="both", expand=True)
        return p

    def _build_page_finish(self) -> tk.Frame:
        p = tk.Frame(self._content, bg=BG_MAIN)
        self._fin_title = tk.Label(
            p, text=self._t("wiz_fin_title"), bg=BG_MAIN, fg=GOOD, font=self._f_h1, anchor="w"
        )
        self._fin_title.pack(fill="x", pady=(4, 10))

        self._fin_summary = tk.Label(
            p, text="", bg=BG_MAIN, fg=TEXT_SEC, font=self._f_body, justify="left", anchor="w"
        )
        self._fin_summary.pack(fill="x", pady=(0, 14))

        tip_card = tk.Frame(p, bg=BG_CARD, padx=14, pady=12)
        tip_card.pack(fill="x", pady=(0, 14))
        tk.Label(tip_card, text=self._t("wiz_fin_tip_title"), bg=BG_CARD, fg=ACCENT, font=self._f_h2, anchor="w").pack(fill="x", pady=(0, 6))
        tk.Label(
            tip_card,
            text=self._t("wiz_fin_tip_body"),
            bg=BG_CARD, fg=TEXT_PRI, font=self._f_small, justify="left", anchor="w"
        ).pack(fill="x")

        tk.Checkbutton(
            p, text=self._t("wiz_launch_after"), variable=self.var_launch_after,
            bg=BG_MAIN, fg=TEXT_PRI, selectcolor=BG_INPUT,
            activebackground=BG_MAIN, activeforeground=TEXT_PRI,
            font=self._f_h2, anchor="w", cursor="hand2"
        ).pack(fill="x")
        return p

    # ------------------------------------------------------------------ Navigation
    def _show_step(self, idx: int) -> None:
        self.step = idx
        for i, page in enumerate(self._pages):
            if i == idx:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()

        for i, lbl in enumerate(self._step_labels):
            if i == idx:
                lbl.configure(bg=BG_CARD, fg=ACCENT)
            elif i < idx:
                lbl.configure(bg=BG_PANEL, fg=GOOD)
            else:
                lbl.configure(bg=BG_PANEL, fg=TEXT_MUTED)

        if idx == 0:
            self._btn_back.configure(state="disabled")
            self._btn_next.configure(text=self._t("wiz_next"), state="normal")
            self._btn_cancel.configure(state="normal")
        elif idx == 1:
            self._btn_back.configure(state="normal")
            self._btn_next.configure(text=self._t("wiz_start"), state="normal")
            self._btn_cancel.configure(state="normal")
        elif idx == 2:
            self._btn_back.configure(state="disabled")
            self._btn_next.configure(text=self._t("wiz_installing"), state="disabled")
            self._btn_cancel.configure(state="disabled")
            self._start_install_thread()
        elif idx == 3:
            self._btn_back.configure(state="disabled")
            self._btn_next.configure(text=self._t("wiz_done"), state="normal")
            self._btn_cancel.configure(state="disabled")

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_install_dir.get(), title=self._t("wiz_browse_title"))
        if chosen:
            self.var_install_dir.set(chosen)

    def _on_back(self) -> None:
        if self.step > 0 and not self.installing:
            self._show_step(self.step - 1)

    def _on_next(self) -> None:
        if self.step == 0:
            self._show_step(1)
        elif self.step == 1:
            self._show_step(2)
        elif self.step == 2 and not self.installing:
            self._btn_back.configure(state="disabled")
            self._btn_cancel.configure(state="disabled")
            self._btn_next.configure(text=self._t("wiz_installing"), state="disabled")
            self._start_install_thread()
        elif self.step == 3:
            if self.install_succeeded and self.var_launch_after.get():
                self._launch_installed_app()
            self.root.destroy()

    def _on_cancel(self) -> None:
        if self.installing:
            return
        self.root.destroy()

    # ------------------------------------------------------------------ Install Worker
    def _set_progress(self, pct: float, title: Optional[str] = None) -> None:
        self._prog_pct = max(0.0, min(100.0, pct))
        if title is not None:
            self._prog_title.configure(text=title)
        self._prog_canvas.delete("all")
        w = max(self._prog_canvas.winfo_width(), 540)
        fill_w = int(w * (self._prog_pct / 100.0))
        if fill_w > 0:
            self._prog_canvas.create_rectangle(0, 0, fill_w, 12, fill=ACCENT, outline="")

    def _append_log(self, msg: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert(tk.END, msg + "\n")
        self._log_box.see(tk.END)
        self._log_box.configure(state="disabled")

    def _emit(self, kind: str, data: object) -> None:
        self._log_queue.put((kind, data))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, data = self._log_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(data))
                elif kind == "prog":
                    pct, title = data  # type: ignore[misc]
                    self._set_progress(pct, title)
                elif kind == "done":
                    ok, summary = data  # type: ignore[misc]
                    self.installing = False
                    self.install_succeeded = bool(ok)
                    if ok:
                        self._fin_title.configure(text=self._t("wiz_fin_title"), fg=GOOD)
                        self._fin_summary.configure(text=str(summary))
                        self._show_step(3)
                    else:
                        self._prog_title.configure(text=self._t("wiz_err_hdr"), fg=ERR)
                        self._btn_back.configure(state="normal")
                        self._btn_cancel.configure(state="normal")
                        self._btn_next.configure(text=self._t("wiz_retry"), state="normal")
                        messagebox.showerror(self._t("wiz_err_title"), str(summary))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _start_install_thread(self) -> None:
        self.installing = True
        self._set_progress(5, self._t("wiz_prog_start"))
        t = threading.Thread(target=self._run_install, daemon=True)
        t.start()

    def _run_install(self) -> None:
        t = self._t
        try:
            install_dir = Path(self.var_install_dir.get().strip() or str(default_install_dir())).resolve()
            payload_zip = resource_path("payload.zip")
            if not payload_zip.exists():
                raise FileNotFoundError(t("wiz_err_no_payload", path=payload_zip))

            self._emit("prog", (12, t("wiz_step_stop")))
            self._emit("log", t("wiz_log_stop"))
            stop_running_hud_processes()

            self._emit("prog", (28, t("wiz_step_extract")))
            self._emit("log", t("wiz_log_dir", dir=install_dir))
            install_dir.mkdir(parents=True, exist_ok=True)

            # Remove old _internal directory cleanly before extracting new version
            old_internal = install_dir / "_internal"
            if old_internal.exists():
                shutil.rmtree(old_internal, ignore_errors=True)

            with zipfile.ZipFile(payload_zip, "r") as zf:
                members = zf.infolist()
                total = max(1, len(members))
                for idx, m in enumerate(members, start=1):
                    zf.extract(m, install_dir)
                    if idx % 20 == 0 or idx == total:
                        self._emit("prog", (28 + (idx / total) * 32, t("wiz_prog_extract", cur=idx, tot=total)))
            self._emit("log", t("wiz_log_extract_ok"))

            # Optional agy CLI installation
            if self.var_install_agy_cli.get():
                self._emit("prog", (66, t("wiz_step_agy")))
                self._emit("log", t("wiz_log_agy_run"))
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                proc = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        "irm https://antigravity.google/cli/install.ps1 | iex",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                    timeout=120,
                )
                if proc.returncode == 0:
                    self._emit("log", t("wiz_log_agy_ok"))
                else:
                    self._emit("log", t("wiz_log_agy_note", msg=(proc.stderr or proc.stdout).strip()[:200]))
            else:
                self._emit("log", t("wiz_log_agy_skip"))

            # Configure official statusLine hooks
            self._emit("prog", (78, t("wiz_step_hooks")))
            self._emit("log", t("wiz_log_hooks"))
            if self.var_hook_claude.get():
                ok, msg = install_claude_hook(install_dir)
                self._emit("log", ("      [OK] " if ok else "      [WARN] ") + msg)
            if self.var_hook_agy.get():
                ok, msg = install_agy_hook(install_dir)
                self._emit("log", ("      [OK] " if ok else "      [WARN] ") + msg)

            # Save chosen AI providers and language preference into config.json
            chosen = []
            if self.var_show_agy.get():
                chosen.append("antigravity")
            if self.var_show_claude.get():
                chosen.append("claude")
            if self.var_show_codex.get():
                chosen.append("codex")
            cfg = load_config()
            cfg["enabled_providers"] = normalize_enabled_providers(chosen)
            cfg["language"] = self.lang if self._lang_overridden else "auto"
            save_config(cfg)

            # Startup, shortcuts, uninstall registration
            self._emit("prog", (90, t("wiz_step_shortcuts")))
            self._emit("log", t("wiz_log_shortcuts"))
            exe_path = install_dir / "AIUsageBar.exe"
            icon_path = install_dir / "app_icon.ico"

            set_startup_enabled(bool(self.var_startup.get()), target_exe=exe_path)
            self._emit("log", t("wiz_log_startup", state="ON" if self.var_startup.get() else "OFF"))

            if self.var_desktop_shortcut.get():
                create_windows_shortcut(
                    desktop_shortcut_path(), exe_path, icon_path=icon_path, description="AI Usage Bar"
                )
                self._emit("log", t("wiz_log_desktop"))

            if self.var_start_menu.get():
                sdir = start_menu_dir()
                create_windows_shortcut(
                    sdir / "AI Usage Bar.lnk", exe_path, icon_path=icon_path, description="AI Usage Bar"
                )
                create_windows_shortcut(
                    sdir / t("wiz_uninst_lnk"),
                    exe_path,
                    arguments="--uninstall",
                    icon_path=icon_path,
                    description=t("wiz_uninst_desc"),
                )
                register_uninstall_entry(install_dir)
                self._emit("log", t("wiz_log_startmenu"))

            self._emit("prog", (100, t("wiz_step_done")))
            self._emit("log", t("wiz_log_done"))
            summary = t("wiz_summary", dir=install_dir, exe=exe_path.name)
            self._emit("done", (True, summary))
        except Exception as exc:
            self._emit("log", t("wiz_log_err", exc=exc))
            self._emit("done", (False, str(exc)))

    def _launch_installed_app(self) -> None:
        install_dir = Path(self.var_install_dir.get().strip() or str(default_install_dir())).resolve()
        exe_path = install_dir / "AIUsageBar.exe"
        if exe_path.exists():
            flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
            )
            subprocess.Popen([str(exe_path)], cwd=str(install_dir), creationflags=flags)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    enable_dpi_awareness()
    app = SetupWizardApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
