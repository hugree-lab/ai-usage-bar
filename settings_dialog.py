"""Windows 11 Fluent 4-Tab Settings, Trends & Help Dialog for AI Usage Bar (EN/KO).

Tabs:
1. display: Visual style preview cards, Drag-and-Drop AI ordering, display mode, pace tick, theme, language, opacity
2. alerts : Custom warn/critical % thresholds, scope, reset alerts, test button, custom global hotkey recorder, refresh & startup
3. trends : 24h / 7d anti-aliased usage trend charts + live pace forecast per AI
4. help   : Visual legend, pace guide, shortcuts, zero-deduction auto-refresh & login guide
"""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hooks_manager import APP_VERSION
from hotkey_manager import format_tk_key_event
from preview_art import png_bytes_to_photoimage, render_history_chart_png, render_style_preview_png
from state_store import (
    BASE_DIR,
    COMPACT_STYLES,
    DATA_DIR,
    WEEKLY_WINDOW_SEC,
    compute_pace,
    format_relative_age,
    get_effective_bucket,
    is_startup_enabled,
    load_history_entries,
    normalize_enabled_providers,
    save_config,
)
from win11_ui import apply_win11_dwm, get_hwnd, get_monitor_work_area_for_point, ui_font

if TYPE_CHECKING:
    from hud_app import QuotaHUDApp

VALID_TABS = ("display", "alerts", "trends", "help")
TAB_KEYS = (
    ("display", "tab_display"),
    ("alerts", "tab_alerts"),
    ("trends", "tab_trends"),
    ("help", "tab_help"),
)


class SettingsDialog:
    """Single-instance fixed-size Windows 11 Fluent Settings, Trends & Help window."""

    def __init__(self, app: "QuotaHUDApp", initial_tab: str = "display") -> None:
        self.app = app
        self.active_tab = initial_tab if initial_tab in VALID_TABS else "display"
        self.trend_hours: float = 24.0
        self._closed = False
        self._recording_hotkey = False
        self._hotkey_status_msg: str = ""
        self._hotkey_status_ok: bool = True
        self._preview_photos: Dict[str, tk.PhotoImage] = {}
        self._trend_photos: Dict[str, tk.PhotoImage] = {}
        self._order_rows: Dict[str, Dict[str, Any]] = {}
        self._drag_prov: Optional[str] = None

        self.win = tk.Toplevel(app.root)
        self.win.title(self.app._t("set_win_title", ver=APP_VERSION))
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<KeyPress>", self._on_win_keypress)

        ico = self._find_icon()
        if ico:
            try:
                self.win.iconbitmap(str(ico))
            except Exception:
                pass

        self._f_h2 = ui_font("ui", 9, "bold")
        self._f_body = ui_font("ui", 8)
        self._f_small = ui_font("ui", 8)
        self._f_mono = ui_font("num", 8)
        self._f_kbd = ui_font("mono", 9, "bold")
        self._fixed_w: int = 618
        self._fixed_h: int = 656

        self.win.withdraw()
        self._measure_fixed_size()
        self._rebuild_contents()
        self._position_near_hud()
        self.win.deiconify()
        self._apply_dwm()

    def _measure_fixed_size(self) -> None:
        """Measure max dimensions across all 4 tabs in both KO & EN ONCE and lock size."""
        saved_tab = self.active_tab
        saved_lang = self.app.cfg.get("language", "auto")
        max_w = 618
        max_h = 648
        try:
            for probe_lang in ("ko", "en"):
                self.app.cfg["language"] = probe_lang
                for tab in VALID_TABS:
                    self.active_tab = tab
                    self._rebuild_contents(preserve_pos=False)
                    self.win.update_idletasks()
                    extra_h = 34 if tab == "display" else 20
                    max_w = max(max_w, self.win.winfo_reqwidth() + 10)
                    max_h = max(max_h, self.win.winfo_reqheight() + extra_h)
        finally:
            self.app.cfg["language"] = saved_lang
            self.active_tab = saved_tab

        hx = self.app.root.winfo_x() + 155
        hy = self.app.root.winfo_y() + 60
        wl, wt, wr, wb = get_monitor_work_area_for_point(hx, hy)
        self._fixed_w = min(max_w, wr - wl - 32)
        self._fixed_h = min(max_h, wb - wt - 32)
        self.win.minsize(self._fixed_w, self._fixed_h)
        self.win.maxsize(self._fixed_w, self._fixed_h)

    def _find_icon(self) -> Optional[Path]:
        for cand in (BASE_DIR / "app_icon.ico", BASE_DIR / "assets" / "app_icon.ico"):
            if cand.exists():
                return cand
        return None

    def _apply_dwm(self) -> None:
        pal = self.app._pal()
        dark = self.app._is_dark_theme()
        self.win.update_idletasks()
        apply_win11_dwm(
            get_hwnd(self.win),
            border_hex=pal["border"],
            dark_titlebar=dark,
        )

    def _position_near_hud(self) -> None:
        self.win.update_idletasks()
        w, h = self._fixed_w, self._fixed_h

        hx = self.app.root.winfo_x() + 155
        hy = self.app.root.winfo_y() + 60
        wl, wt, wr, wb = get_monitor_work_area_for_point(hx, hy)

        px = wl + max(16, (wr - wl - w) // 2)
        py = wt + max(16, (wb - wt - h) // 2)
        self.win.geometry(f"{w}x{h}+{px}+{py}")

    def show_tab(self, tab: str) -> None:
        if self._closed:
            return
        self._recording_hotkey = False
        self.active_tab = tab if tab in VALID_TABS else "display"
        self._rebuild_contents(preserve_pos=True)
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def refresh_theme(self) -> None:
        if self._closed:
            return
        self._rebuild_contents(preserve_pos=True)
        self._apply_dwm()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._recording_hotkey = False
        if getattr(self.app, "_settings_dlg", None) is self:
            self.app._settings_dlg = None
        try:
            self.win.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------ Global Key Handler
    def _on_win_keypress(self, event: tk.Event) -> Optional[str]:
        t = self.app._t
        if self._recording_hotkey:
            if event.keysym == "Escape":
                self._recording_hotkey = False
                self._hotkey_status_msg = t("hk_cancelled")
                self._hotkey_status_ok = True
                self._rebuild_contents(preserve_pos=True)
                return "break"
            formatted = format_tk_key_event(int(event.state), str(event.keysym))
            if formatted:
                self._recording_hotkey = False
                ok, msg = self.app._update_hotkey(True, formatted)
                self._hotkey_status_ok = ok
                self._hotkey_status_msg = msg
                self._rebuild_contents(preserve_pos=True)
                return "break"
            return "break"

        if event.keysym == "Escape":
            self.close()
            return "break"
        return None

    # ------------------------------------------------------------------ Chrome & Tabs
    def _rebuild_contents(self, preserve_pos: bool = False) -> None:
        t = self.app._t
        for child in self.win.winfo_children():
            child.destroy()

        pal = self.app._pal()
        self.win.title(t("set_win_title", ver=APP_VERSION))
        self.win.configure(bg=pal["bg_main"])
        self._preview_photos.clear()
        self._trend_photos.clear()
        self._order_rows.clear()

        # Top header with segmented 4-tab bar
        top = tk.Frame(self.win, bg=pal["bg_card"], padx=16, pady=10)
        top.pack(fill="x")

        tk.Label(
            top, text="AI Usage Bar", bg=pal["bg_card"], fg=pal["accent_agy"],
            font=ui_font("num", 11, "bold"),
        ).pack(side="left")
        tk.Label(
            top, text=f" v{APP_VERSION}", bg=pal["bg_card"], fg=pal["text_muted"],
            font=self._f_mono,
        ).pack(side="left", padx=(2, 10))

        tab_box = tk.Frame(top, bg=pal["bg_main"], padx=3, pady=3)
        tab_box.pack(side="right")

        for tid, tkey in TAB_KEYS:
            active = self.active_tab == tid
            lbl = tk.Label(
                tab_box,
                text=t(tkey),
                bg=pal["bg_btn_hover"] if active else pal["bg_main"],
                fg=pal["accent_agy"] if active else pal["text_sec"],
                font=self._f_h2 if active else self._f_body,
                padx=10,
                pady=4,
                cursor="hand2",
            )
            lbl.pack(side="left", padx=1)
            lbl.bind("<Button-1>", lambda _e, tab_id=tid: self.show_tab(tab_id))

        tk.Frame(self.win, bg=pal["border"], height=1).pack(fill="x")

        # Footer packed BEFORE body so it is never pushed off-screen
        footer = tk.Frame(self.win, bg=pal["bg_card"], padx=16, pady=9)
        footer.pack(side="bottom", fill="x")
        tk.Frame(self.win, bg=pal["border"], height=1).pack(side="bottom", fill="x")

        self._make_btn(footer, t("btn_open_data"), self._open_data_dir).pack(side="left")
        self._make_btn(footer, t("btn_close"), self.close, primary=True).pack(side="right")

        body = tk.Frame(self.win, bg=pal["bg_main"], padx=16, pady=11)
        body.pack(fill="both", expand=True)

        if self.active_tab == "display":
            self._build_display_tab(body, pal)
        elif self.active_tab == "alerts":
            self._build_alerts_tab(body, pal)
        elif self.active_tab == "trends":
            self._build_trends_tab(body, pal)
        else:
            self._build_help_tab(body, pal)

        self.win.update_idletasks()

    def _make_btn(self, parent: tk.Widget, text: str, cmd, primary: bool = False) -> tk.Label:
        pal = self.app._pal()
        bg = pal["accent_agy"] if primary else pal["bg_btn"]
        fg = "#0B1120" if primary else pal["text_pri"]
        hover_bg = pal["accent_agy"] if primary else pal["bg_btn_hover"]
        btn = tk.Label(
            parent, text=text, bg=bg, fg=fg,
            font=self._f_h2 if primary else self._f_body,
            padx=12, pady=4, cursor="hand2",
        )
        btn.bind("<Button-1>", lambda _e: cmd())
        if not primary:
            btn.bind("<Enter>", lambda _e, w=btn, hb=hover_bg: w.configure(bg=hb))
            btn.bind("<Leave>", lambda _e, w=btn, nb=bg: w.configure(bg=nb))
        return btn

    def _make_seg_chip(
        self, parent: tk.Widget, text: str, active: bool, cmd, accent: Optional[str] = None, padx: int = 8
    ) -> tk.Label:
        pal = self.app._pal()
        acc = accent or pal["accent_agy"]
        lbl = tk.Label(
            parent,
            text=f"{text} ✓" if active else text,
            bg=pal["bg_btn_hover"] if active else pal["bg_btn"],
            fg=acc if active else pal["text_sec"],
            font=self._f_h2 if active else self._f_small,
            padx=padx,
            pady=3,
            cursor="hand2",
        )
        lbl.bind("<Button-1>", lambda _e: cmd())
        return lbl

    # ------------------------------------------------------------------ Tab 1: Display & Order
    def _build_display_tab(self, body: tk.Frame, pal: Dict[str, str]) -> None:
        t = self.app._t

        # Card 1: Compact Style Visual Preview Cards
        sec1 = tk.Frame(body, bg=pal["bg_card"], padx=12, pady=9)
        sec1.pack(fill="x", pady=(0, 8))

        s1_hdr = tk.Frame(sec1, bg=pal["bg_card"])
        s1_hdr.pack(fill="x", pady=(0, 6))
        tk.Label(s1_hdr, text=t("sec_style_title"), bg=pal["bg_card"], fg=pal["text_pri"], font=self._f_h2).pack(side="left")
        tk.Label(s1_hdr, text=t("sec_style_hint"), bg=pal["bg_card"], fg=pal["text_muted"], font=self._f_small).pack(side="right")

        cards_grid = tk.Frame(sec1, bg=pal["bg_card"])
        cards_grid.pack(fill="x")
        cur_style = self.app._compact_style()

        self._style_desc_lbl = tk.Label(
            sec1,
            text=t(f"style_{cur_style}_desc").replace("\n", " "),
            bg=pal["bg_card"],
            fg=pal["text_sec"],
            font=self._f_small,
            anchor="w",
        )

        for col_idx, st in enumerate(COMPACT_STYLES):
            cards_grid.grid_columnconfigure(col_idx, weight=1, uniform="style_prev")
            selected = st == cur_style
            title = t(f"style_{st}_title")
            sub = t(f"style_{st}_sub")
            desc = t(f"style_{st}_desc")

            outer_card = tk.Frame(
                cards_grid,
                bg=pal["bg_main"],
                highlightbackground=pal["accent_agy"] if selected else pal["border"],
                highlightthickness=2 if selected else 1,
                padx=6,
                pady=5,
                cursor="hand2",
            )
            pad_r = 6 if col_idx < len(COMPACT_STYLES) - 1 else 0
            outer_card.grid(row=0, column=col_idx, sticky="nsew", padx=(0, pad_r))

            png = render_style_preview_png(st, pal, width=146, height=68)
            photo = png_bytes_to_photoimage(png, master=self.win)
            self._preview_photos[st] = photo

            img_lbl = tk.Label(outer_card, image=photo, bg=pal["bg_main"], bd=0, cursor="hand2")
            img_lbl.pack(pady=(0, 3))

            t_lbl = tk.Label(
                outer_card,
                text=f"{title} ✓" if selected else title,
                bg=pal["bg_main"],
                fg=pal["accent_agy"] if selected else pal["text_pri"],
                font=self._f_h2,
                cursor="hand2",
            )
            t_lbl.pack()

            s_lbl = tk.Label(
                outer_card,
                text=sub,
                bg=pal["bg_main"],
                fg=pal["text_muted"],
                font=ui_font("ui", 7),
                cursor="hand2",
            )
            s_lbl.pack()

            def _bind_card(style_key: str, desc_txt: str, widgets: List[tk.Widget], card_f: tk.Frame) -> None:
                def on_click(_e: tk.Event) -> None:
                    self.app._set_compact_style(style_key)
                    self._rebuild_contents(preserve_pos=True)

                def on_enter(_e: tk.Event) -> None:
                    self._style_desc_lbl.configure(text=desc_txt.replace("\n", " "))
                    if self.app._compact_style() != style_key:
                        card_f.configure(highlightbackground=pal["text_muted"])

                def on_leave(_e: tk.Event) -> None:
                    cur = self.app._compact_style()
                    self._style_desc_lbl.configure(text=self.app._t(f"style_{cur}_desc").replace("\n", " "))
                    card_f.configure(highlightbackground=pal["accent_agy"] if cur == style_key else pal["border"])

                for w in widgets:
                    w.bind("<Button-1>", on_click)
                    w.bind("<Enter>", on_enter)
                    w.bind("<Leave>", on_leave)

            _bind_card(st, desc, [outer_card, img_lbl, t_lbl, s_lbl], outer_card)

        self._style_desc_lbl.pack(fill="x", pady=(5, 0))

        if cur_style == "slim":
            slim_row = tk.Frame(sec1, bg=pal["bg_card"])
            slim_row.pack(fill="x", pady=(5, 0))
            tk.Label(
                slim_row, text=t("lbl_slim_sub"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_small
            ).pack(side="left")
            cur_sm = self.app._slim_sub_metric()
            for mk, mkey in (("model", "opt_slim_model"), ("5h", "opt_slim_5h")):
                def _set_sm(val: str = mk) -> None:
                    self.app.cfg["slim_sub_metric"] = val
                    save_config(self.app.cfg)
                    self.app._refresh_ui(force_tray=False)
                    self._rebuild_contents(preserve_pos=True)

                self._make_seg_chip(slim_row, t(mkey), cur_sm == mk, _set_sm).pack(side="right", padx=(4, 0))

        # Card 2: AI Providers & Drag-and-Drop Custom Ordering
        sec2 = tk.Frame(body, bg=pal["bg_card"], padx=12, pady=8)
        sec2.pack(fill="x", pady=(0, 8))

        s2_hdr = tk.Frame(sec2, bg=pal["bg_card"])
        s2_hdr.pack(fill="x", pady=(0, 5))
        tk.Label(s2_hdr, text=t("sec_order_title"), bg=pal["bg_card"], fg=pal["text_pri"], font=self._f_h2).pack(side="left")
        tk.Label(s2_hdr, text=t("sec_order_hint"), bg=pal["bg_card"], fg=pal["text_muted"], font=self._f_small).pack(side="right")

        self._order_list_frame = tk.Frame(sec2, bg=pal["bg_card"])
        self._order_list_frame.pack(fill="x")

        from hud_app import PROVIDER_META
        order = self.app._provider_order()
        enabled_set = set(self.app._enabled_providers())

        for prov in order:
            full_name, short, accent_key, _in = PROVIDER_META[prov]
            is_on = prov in enabled_set
            row = tk.Frame(
                self._order_list_frame,
                bg=pal["bg_main"],
                highlightbackground=pal["border"],
                highlightthickness=1,
                padx=8,
                pady=4,
                cursor="fleur",
            )

            handle = tk.Label(
                row, text="⠿", bg=pal["bg_main"], fg=pal["text_muted"],
                font=ui_font("sym", 10), padx=2, cursor="fleur",
            )
            handle.pack(side="left", padx=(0, 4))

            rank_lbl = tk.Label(
                row, text="1", bg=pal["bg_btn"], fg=pal["text_sec"],
                font=ui_font("num", 8, "bold"), width=2, anchor="center", cursor="fleur",
            )
            rank_lbl.pack(side="left", padx=(0, 7))

            dot = tk.Canvas(row, width=8, height=8, bg=pal["bg_main"], highlightthickness=0, cursor="fleur")
            dot.create_oval(0, 0, 7, 7, fill=pal[accent_key] if is_on else pal["text_muted"], outline="")
            dot.pack(side="left", padx=(0, 7))

            name_lbl = tk.Label(
                row,
                text=f"{full_name} ({short})",
                bg=pal["bg_main"],
                fg=pal["text_pri"] if is_on else pal["text_muted"],
                font=self._f_h2 if is_on else self._f_body,
                cursor="fleur",
            )
            name_lbl.pack(side="left")

            btn_dn = tk.Label(
                row, text="▼", bg=pal["bg_btn"], fg=pal["text_pri"],
                font=ui_font("sym", 8), padx=6, pady=1, cursor="hand2",
            )
            btn_dn.pack(side="right", padx=(3, 0))
            btn_dn.bind("<Button-1>", lambda _e, p=prov: self._step_provider_order(p, 1))

            btn_up = tk.Label(
                row, text="▲", bg=pal["bg_btn"], fg=pal["text_pri"],
                font=ui_font("sym", 8), padx=6, pady=1, cursor="hand2",
            )
            btn_up.pack(side="right", padx=(8, 0))
            btn_up.bind("<Button-1>", lambda _e, p=prov: self._step_provider_order(p, -1))

            def _toggle_p(p: str = prov) -> None:
                self.app._toggle_provider(p)
                self._rebuild_contents(preserve_pos=True)

            self._make_seg_chip(
                row, t("chip_shown") if is_on else t("chip_hidden"), is_on, _toggle_p, accent=pal[accent_key]
            ).pack(side="right")

            for dw in (row, handle, rank_lbl, dot, name_lbl):
                dw.bind("<ButtonPress-1>", lambda e, p=prov: self._on_order_drag_start(p, e))
                dw.bind("<B1-Motion>", self._on_order_drag_motion)
                dw.bind("<ButtonRelease-1>", self._on_order_drag_end)

            self._order_rows[prov] = {
                "frame": row,
                "handle": handle,
                "rank": rank_lbl,
                "dot": dot,
                "name": name_lbl,
                "btn_up": btn_up,
                "btn_dn": btn_dn,
                "bg_widgets": [row, handle, dot, name_lbl],
            }

        self._layout_order_rows()

        # Card 3: Display Mode, Pace Tick, Theme & Language, Opacity
        sec3 = tk.Frame(body, bg=pal["bg_card"], padx=12, pady=8)
        sec3.pack(fill="x")

        # Row 1: Display mode
        r_mode = tk.Frame(sec3, bg=pal["bg_card"])
        r_mode.pack(fill="x", pady=(0, 5))
        tk.Label(r_mode, text=t("lbl_mode"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left")

        is_used = self.app._display_mode() == "used"
        for mval, mkey, macc in (("remaining", "chip_rem_pct", pal["accent_agy"]), ("used", "chip_used_pct", pal["accent_claude"])):
            def _set_dm(v: str = mval) -> None:
                if self.app._display_mode() != v:
                    self.app._toggle_display_mode()
                    self._rebuild_contents(preserve_pos=True)

            self._make_seg_chip(r_mode, t(mkey), (is_used == (mval == "used")), _set_dm, accent=macc).pack(side="right", padx=(4, 0))

        # Row 2: Dedicated clearly-visible Pace Tick toggle
        r_pace = tk.Frame(sec3, bg=pal["bg_card"])
        r_pace.pack(fill="x", pady=(0, 5))
        tk.Label(r_pace, text=t("lbl_pace_row"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left")
        pace_on = bool(self.app.cfg.get("show_pace_marker", True))

        def _toggle_pace() -> None:
            self.app.cfg["show_pace_marker"] = not pace_on
            save_config(self.app.cfg)
            self.app._refresh_ui(force_tray=False)
            self._rebuild_contents(preserve_pos=True)

        self._make_seg_chip(
            r_pace, t("chip_on") if pace_on else t("chip_off"), pace_on, _toggle_pace, accent=pal["good"]
        ).pack(side="right")

        # Row 3: Theme (left) + Language (right)
        r_tl = tk.Frame(sec3, bg=pal["bg_card"])
        r_tl.pack(fill="x", pady=(0, 5))

        tk.Label(r_tl, text=t("lbl_theme"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left", padx=(0, 6))
        cur_th = self.app._theme_mode()
        for tval, tkey in (("auto", "theme_auto"), ("dark", "theme_dark"), ("light", "theme_light")):
            def _set_th(v: str = tval) -> None:
                self.app.cfg["theme"] = v
                save_config(self.app.cfg)
                self.app._apply_theme()
                self.refresh_theme()

            self._make_seg_chip(r_tl, t(tkey), cur_th == tval, _set_th, padx=6).pack(side="left", padx=(0, 3))

        cur_lang_pref = str(self.app.cfg.get("language") or "auto").lower()
        for lval, llbl in (("en", "EN"), ("ko", "한국어"), ("auto", t("lang_auto"))):
            def _set_lang(v: str = lval) -> None:
                self.app.cfg["language"] = v
                save_config(self.app.cfg)
                self.app._apply_language()
                self._rebuild_contents(preserve_pos=True)

            self._make_seg_chip(r_tl, llbl, cur_lang_pref == lval, _set_lang, padx=6).pack(side="right", padx=(3, 0))
        tk.Label(r_tl, text=t("lbl_lang"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="right", padx=(8, 4))

        # Row 4: Opacity
        r_op = tk.Frame(sec3, bg=pal["bg_card"])
        r_op.pack(fill="x")
        tk.Label(r_op, text=t("lbl_opacity"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left")
        op_lbl = tk.Label(
            r_op,
            text=f"{int(round(float(self.app.cfg['opacity']) * 100))}%",
            bg=pal["bg_card"], fg=pal["text_pri"], font=self._f_mono, width=5, anchor="e",
        )
        op_lbl.pack(side="right")

        op_var = tk.DoubleVar(value=float(self.app.cfg["opacity"]))

        def _on_op(val: str) -> None:
            self.app._on_opacity_change(val)
            op_lbl.configure(text=f"{int(round(float(val) * 100))}%")

        tk.Scale(
            r_op, from_=0.55, to=1.0, resolution=0.05, orient="horizontal", showvalue=False,
            variable=op_var, command=_on_op, bg=pal["bg_card"], fg=pal["text_pri"],
            troughcolor=pal["bg_track"], highlightthickness=0, bd=0, sliderrelief="flat",
            activebackground=pal["accent_agy"], length=210, width=11,
        ).pack(side="right", padx=(6, 4))

    # ------------------------------------------------------------------ Tab 2: Alerts, Hotkey & System
    def _build_alerts_tab(self, body: tk.Frame, pal: Dict[str, str]) -> None:
        t = self.app._t

        # Card 1: Custom Alert Thresholds
        c1 = tk.Frame(body, bg=pal["bg_card"], padx=13, pady=10)
        c1.pack(fill="x", pady=(0, 9))

        c1_hdr = tk.Frame(c1, bg=pal["bg_card"])
        c1_hdr.pack(fill="x", pady=(0, 7))
        tk.Label(c1_hdr, text=t("sec_alert_title"), bg=pal["bg_card"], fg=pal["text_pri"], font=self._f_h2).pack(side="left")

        noti_on = bool(self.app.cfg.get("notifications", True))

        def _toggle_noti() -> None:
            self.app._toggle_notifications()
            self._rebuild_contents(preserve_pos=True)

        self._make_btn(c1_hdr, t("btn_alert_test"), self.app._test_notification).pack(side="right", padx=(6, 0))
        self._make_seg_chip(
            c1_hdr, t("chip_alert_on") if noti_on else t("chip_alert_off"), noti_on, _toggle_noti, accent=pal["good"]
        ).pack(side="right")

        # Warning threshold selector
        r_warn = tk.Frame(c1, bg=pal["bg_card"])
        r_warn.pack(fill="x", pady=(0, 5))
        tk.Label(r_warn, text=t("lbl_warn_th"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left")
        cur_w = int(self.app.cfg.get("notify_warn_pct", 80))
        for val in (90, 85, 80, 75, 70, 60, 0):
            lbl = t("opt_off") if val == 0 else f"{val}%"

            def _set_w(v: int = val) -> None:
                self.app.cfg["notify_warn_pct"] = v
                save_config(self.app.cfg)
                self.app._reseed_notifications()
                self._rebuild_contents(preserve_pos=True)

            self._make_seg_chip(r_warn, lbl, cur_w == val, _set_w, accent=pal["warn"], padx=7).pack(side="right", padx=(3, 0))

        # Critical threshold selector
        r_crit = tk.Frame(c1, bg=pal["bg_card"])
        r_crit.pack(fill="x", pady=(0, 6))
        tk.Label(r_crit, text=t("lbl_crit_th"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left")
        cur_c = int(self.app.cfg.get("notify_crit_pct", 95))
        for val in (98, 95, 90, 85, 0):
            lbl = t("opt_off") if val == 0 else f"{val}%"

            def _set_c(v: int = val) -> None:
                self.app.cfg["notify_crit_pct"] = v
                save_config(self.app.cfg)
                self.app._reseed_notifications()
                self._rebuild_contents(preserve_pos=True)

            self._make_seg_chip(r_crit, lbl, cur_c == val, _set_c, accent=pal["low"], padx=7).pack(side="right", padx=(3, 0))

        # Scope & Reset completion
        r_scope = tk.Frame(c1, bg=pal["bg_card"])
        r_scope.pack(fill="x")
        tk.Label(r_scope, text=t("lbl_alert_scope"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left")

        on_reset = bool(self.app.cfg.get("notify_on_reset", True))
        inc_5h = bool(self.app.cfg.get("notify_include_5h", True))

        def _toggle_reset_n() -> None:
            self.app.cfg["notify_on_reset"] = not on_reset
            save_config(self.app.cfg)
            self._rebuild_contents(preserve_pos=True)

        def _set_5h(val: bool) -> None:
            self.app.cfg["notify_include_5h"] = val
            save_config(self.app.cfg)
            self._rebuild_contents(preserve_pos=True)

        self._make_seg_chip(r_scope, t("chip_on_reset"), on_reset, _toggle_reset_n, accent=pal["expired"]).pack(side="right", padx=(6, 0))
        self._make_seg_chip(r_scope, t("chip_scope_all"), inc_5h, lambda: _set_5h(True)).pack(side="right", padx=(3, 0))
        self._make_seg_chip(r_scope, t("chip_scope_wk"), not inc_5h, lambda: _set_5h(False)).pack(side="right")

        # Card 2: Custom Global Hotkey
        c2 = tk.Frame(body, bg=pal["bg_card"], padx=13, pady=10)
        c2.pack(fill="x", pady=(0, 9))

        c2_hdr = tk.Frame(c2, bg=pal["bg_card"])
        c2_hdr.pack(fill="x", pady=(0, 6))
        tk.Label(c2_hdr, text=t("sec_hotkey_title"), bg=pal["bg_card"], fg=pal["text_pri"], font=self._f_h2).pack(side="left")

        hk_on = bool(self.app.cfg.get("hotkey_enabled", True))
        hk_spec = str(self.app.cfg.get("hotkey") or "Ctrl+Alt+Q")

        def _toggle_hk() -> None:
            ok, msg = self.app._update_hotkey(not hk_on, hk_spec)
            self._hotkey_status_ok = ok
            self._hotkey_status_msg = msg
            self._rebuild_contents(preserve_pos=True)

        self._make_seg_chip(
            c2_hdr, t("chip_on") if hk_on else t("chip_off"), hk_on, _toggle_hk, accent=pal["good"]
        ).pack(side="right")

        hk_row = tk.Frame(c2, bg=pal["bg_card"])
        hk_row.pack(fill="x")

        if self._recording_hotkey:
            badge_txt = t("hk_recording")
            badge_bg = pal["bg_btn_hover"]
            badge_fg = pal["accent_agy"]
            border_c = pal["accent_agy"]
        else:
            badge_txt = hk_spec
            badge_bg = pal["bg_main"]
            badge_fg = pal["text_pri"] if hk_on else pal["text_muted"]
            border_c = pal["border"]

        badge_box = tk.Frame(hk_row, bg=badge_bg, highlightbackground=border_c, highlightthickness=1, padx=10, pady=4)
        badge_box.pack(side="left")
        tk.Label(badge_box, text=badge_txt, bg=badge_bg, fg=badge_fg, font=self._f_kbd).pack()

        def _reset_hk() -> None:
            self._recording_hotkey = False
            ok, msg = self.app._update_hotkey(True, "Ctrl+Alt+Q")
            self._hotkey_status_ok = ok
            self._hotkey_status_msg = msg
            self._rebuild_contents(preserve_pos=True)

        def _start_record() -> None:
            self._recording_hotkey = not self._recording_hotkey
            self._hotkey_status_msg = t("hk_hint") if self._recording_hotkey else ""
            self._hotkey_status_ok = True
            self._rebuild_contents(preserve_pos=True)
            self.win.focus_force()

        self._make_btn(hk_row, t("btn_hk_default"), _reset_hk).pack(side="right", padx=(4, 0))
        self._make_btn(
            hk_row,
            t("btn_hk_cancel") if self._recording_hotkey else t("btn_hk_change"),
            _start_record,
            primary=self._recording_hotkey,
        ).pack(side="right")

        status_note = self._hotkey_status_msg or (t("hk_macos_note") if sys.platform == "darwin" else "")
        if status_note:
            tk.Label(
                c2,
                text=status_note,
                bg=pal["bg_card"],
                fg=pal["text_sec"] if (sys.platform == "darwin" and not self._hotkey_status_msg) else (pal["good"] if self._hotkey_status_ok else pal["low"]),
                font=self._f_small,
                anchor="w",
            ).pack(fill="x", pady=(5, 0))

        # Card 3: Auto-Refresh & System
        c3 = tk.Frame(body, bg=pal["bg_card"], padx=13, pady=10)
        c3.pack(fill="x")

        r_iv = tk.Frame(c3, bg=pal["bg_card"])
        r_iv.pack(fill="x", pady=(0, 6))
        tk.Label(r_iv, text=t("lbl_refresh_iv"), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body).pack(side="left")
        cur_iv = self.app._refresh_interval_sec()
        for sec_v, mins in ((600, 10), (300, 5), (180, 3), (60, 1)):
            def _set_iv(v: int = sec_v) -> None:
                self.app.cfg["refresh_interval_sec"] = v
                save_config(self.app.cfg)
                self._rebuild_contents(preserve_pos=True)

            self._make_seg_chip(r_iv, t("min_fmt", m=mins), cur_iv == sec_v, _set_iv, padx=7).pack(side="right", padx=(3, 0))

        r_sys = tk.Frame(c3, bg=pal["bg_card"])
        r_sys.pack(fill="x")

        def _toggle_ar() -> None:
            self.app._toggle_auto_refresh()
            self._rebuild_contents(preserve_pos=True)

        def _toggle_st() -> None:
            self.app._toggle_startup()
            self._rebuild_contents(preserve_pos=True)

        self._make_seg_chip(
            r_sys, t("chip_auto_refresh"), bool(self.app.cfg.get("auto_refresh", True)), _toggle_ar, accent=pal["good"]
        ).pack(side="left", padx=(0, 6))
        self._make_seg_chip(
            r_sys, t("chip_startup"), is_startup_enabled(), _toggle_st, accent=pal["good"]
        ).pack(side="left")

        rec_btn = self._make_btn(r_sys, t("btn_reconnect"), lambda: self._run_reconnect(rec_btn))
        rec_btn.pack(side="right")

    def _run_reconnect(self, btn: tk.Label) -> None:
        self.app._reconnect_hooks()
        pal = self.app._pal()
        t = self.app._t
        btn.configure(text=t("btn_reconnected"), fg=pal["good"])
        self.win.after(2200, lambda: (not self._closed) and btn.configure(text=t("btn_reconnect"), fg=pal["text_pri"]))

    # ------------------------------------------------------------------ Tab 3: Usage Trends & Pace
    def _build_trends_tab(self, body: tk.Frame, pal: Dict[str, str]) -> None:
        from hud_app import PROVIDER_META, bucket_display_pct, resolve_agy_buckets, resolve_claude_buckets

        t = self.app._t
        lang = self.app._lang()
        now = time.time()
        mode = self.app._display_mode()
        entries = load_history_entries(hours=self.trend_hours, now=now)
        warn_pct = int(self.app.cfg.get("notify_warn_pct", 80))

        # Top period filter bar + subtle legend
        bar = tk.Frame(body, bg=pal["bg_main"])
        bar.pack(fill="x", pady=(0, 8))

        tk.Label(
            bar,
            text=t("trends_legend"),
            bg=pal["bg_main"], fg=pal["text_muted"], font=self._f_small,
        ).pack(side="left")

        for hrs, hkey in ((168.0, "period_7d"), (24.0, "period_24h")):
            def _set_h(v: float = hrs) -> None:
                self.trend_hours = v
                self._rebuild_contents(preserve_pos=True)

            self._make_seg_chip(bar, t(hkey), abs(self.trend_hours - hrs) < 0.1, _set_h).pack(side="right", padx=(4, 0))

        enabled = self.app._enabled_providers()
        chart_h = 74 if len(enabled) <= 2 else 56

        for idx, prov in enumerate(enabled):
            full_name, _short, accent_key, inner_key = PROVIDER_META[prov]
            pdata = self.app.state.get(prov) if isinstance(self.app.state.get(prov), dict) else {}

            if prov == "antigravity":
                ab = resolve_agy_buckets(pdata, now)
                wk_bkt = ab["weekly_gen"] if ab["weekly_gen"]["remaining_pct"] is not None else ab["weekly_argon"]
            elif prov == "claude":
                cb = resolve_claude_buckets(pdata, now)
                wk_bkt = cb["weekly_gen"]
            else:
                wk_bkt = get_effective_bucket(pdata.get("weekly"), now)

            used_wk = bucket_display_pct(wk_bkt, "used")
            disp_wk = bucket_display_pct(wk_bkt, mode)
            pace = compute_pace(used_wk, wk_bkt.get("resets_at"), WEEKLY_WINDOW_SEC, now=now, mode=mode, lang=lang)

            card = tk.Frame(body, bg=pal["bg_card"], padx=12, pady=8)
            card.pack(fill="x", pady=(0, 8 if idx < len(enabled) - 1 else 0))

            hdr = tk.Frame(card, bg=pal["bg_card"])
            hdr.pack(fill="x", pady=(0, 5))

            tk.Label(hdr, text=full_name, bg=pal["bg_card"], fg=pal[accent_key], font=self._f_h2).pack(side="left")
            if disp_wk is not None:
                tk.Label(
                    hdr,
                    text=f"  {disp_wk:.1f}%",
                    bg=pal["bg_card"], fg=pal["text_pri"], font=ui_font("num", 9, "bold"),
                ).pack(side="left")

            if pace is not None:
                p_col = {
                    "fast": pal["low"],
                    "warn": pal["warn"],
                    "relaxed": pal["good"],
                    "steady": pal["text_sec"],
                }[pace["status"]]
                tk.Label(hdr, text=f"● {pace['label']}", bg=pal["bg_card"], fg=p_col, font=self._f_small).pack(side="right")
            else:
                tk.Label(hdr, text=t("pace_waiting"), bg=pal["bg_card"], fg=pal["text_muted"], font=self._f_small).pack(side="right")

            png = render_history_chart_png(
                entries=entries,
                provider=prov,
                hours=self.trend_hours,
                now=now,
                pal=pal,
                accent_hex=pal[accent_key],
                s5_hex=pal[inner_key],
                warn_pct=warn_pct,
                mode=mode,
                width=492,
                height=chart_h,
            )
            photo = png_bytes_to_photoimage(png, master=self.win)
            self._trend_photos[prov] = photo
            tk.Label(card, image=photo, bg=pal["bg_card"], bd=0).pack(fill="x")

            n_pts = sum(1 for e in entries if isinstance(e.get(prov), dict))
            age = format_relative_age(pdata.get("updated_at"), now, lang=lang)
            foot_txt = t("trends_points", n=n_pts, age=age) if n_pts >= 2 else t("trends_collecting")
            tk.Label(card, text=foot_txt, bg=pal["bg_card"], fg=pal["text_muted"], font=ui_font("ui", 7), anchor="w").pack(fill="x", pady=(4, 0))

    # ------------------------------------------------------------------ Tab 4: Help Guide
    def _build_help_tab(self, body: tk.Frame, pal: Dict[str, str]) -> None:
        t = self.app._t

        c1 = tk.Frame(body, bg=pal["bg_card"], padx=13, pady=9)
        c1.pack(fill="x", pady=(0, 8))
        tk.Label(c1, text=t("help_c1_title"), bg=pal["bg_card"], fg=pal["accent_agy"], font=self._f_h2, anchor="w").pack(fill="x", pady=(0, 5))

        for k_key, v_key in (
            ("help_l1_k", "help_l1_v"),
            ("help_l2_k", "help_l2_v"),
            ("help_l3_k", "help_l3_v"),
            ("help_l4_k", "help_l4_v"),
        ):
            r = tk.Frame(c1, bg=pal["bg_card"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text=t(k_key), bg=pal["bg_card"], fg=pal["text_pri"], font=self._f_h2, width=21, anchor="w").pack(side="left")
            tk.Label(r, text=t(v_key), bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body, anchor="w").pack(side="left")

        col_row = tk.Frame(c1, bg=pal["bg_main"], padx=9, pady=5)
        col_row.pack(fill="x", pady=(6, 0))
        for col_hex, lkey in (
            (pal["accent_agy"], "legend_ok"),
            (pal["warn"], "legend_warn"),
            (pal["low"], "legend_crit"),
            (pal["expired"], "legend_reset"),
        ):
            dot = tk.Canvas(col_row, width=8, height=8, bg=pal["bg_main"], highlightthickness=0)
            dot.create_oval(0, 0, 7, 7, fill=col_hex, outline="")
            dot.pack(side="left", padx=(0, 4))
            tk.Label(col_row, text=t(lkey), bg=pal["bg_main"], fg=pal["text_sec"], font=self._f_small).pack(side="left", padx=(0, 14))

        c2 = tk.Frame(body, bg=pal["bg_card"], padx=13, pady=9)
        c2.pack(fill="x", pady=(0, 8))
        tk.Label(c2, text=t("help_c2_title"), bg=pal["bg_card"], fg=pal["accent_agy"], font=self._f_h2, anchor="w").pack(fill="x", pady=(0, 5))

        hk_spec = str(self.app.cfg.get("hotkey") or "Ctrl+Alt+Q")
        for k_txt, v_txt in (
            (t("help_s1_k"), t("help_s1_v")),
            (t("help_s2_k"), t("help_s2_v")),
            (t("help_s3_k"), t("help_s3_v")),
            (t("help_s4_k"), t("help_s4_v")),
            (t("help_s5_k", hk=hk_spec), t("help_s5_v")),
        ):
            r = tk.Frame(c2, bg=pal["bg_card"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text=k_txt, bg=pal["bg_card"], fg=pal["text_pri"], font=self._f_h2, width=21, anchor="w").pack(side="left")
            tk.Label(r, text=v_txt, bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body, anchor="w").pack(side="left")

        c3 = tk.Frame(body, bg=pal["bg_card"], padx=13, pady=9)
        c3.pack(fill="x")
        tk.Label(c3, text=t("help_c3_title"), bg=pal["bg_card"], fg=pal["accent_agy"], font=self._f_h2, anchor="w").pack(fill="x", pady=(0, 4))
        tk.Label(
            c3,
            text=t("help_c3_body"),
            bg=pal["bg_card"], fg=pal["text_sec"], font=self._f_body,
            justify="left", anchor="w", wraplength=545,
        ).pack(fill="x")

    # ------------------------------------------------------------------ Drag-and-Drop Order Helpers
    def _layout_order_rows(self) -> None:
        pal = self.app._pal()
        order = self.app._provider_order()
        for info in self._order_rows.values():
            info["frame"].pack_forget()

        for idx, prov in enumerate(order):
            info = self._order_rows[prov]
            info["rank"].configure(text=str(idx + 1))
            can_up = idx > 0
            can_dn = idx < len(order) - 1
            info["btn_up"].configure(
                fg=pal["text_pri"] if can_up else pal["bg_btn"],
                cursor="hand2" if can_up else "",
            )
            info["btn_dn"].configure(
                fg=pal["text_pri"] if can_dn else pal["bg_btn"],
                cursor="hand2" if can_dn else "",
            )
            info["frame"].pack(fill="x", pady=(0, 4 if can_dn else 0))

    def _apply_new_provider_order(self, new_order: List[str], save: bool = True) -> None:
        self.app.cfg["provider_order"] = list(new_order)
        self.app.cfg["enabled_providers"] = normalize_enabled_providers(
            self.app.cfg.get("enabled_providers"), new_order
        )
        if save:
            save_config(self.app.cfg)
        self._layout_order_rows()
        self.app._refresh_provider_chips()
        self.app._apply_visibility_layout(resize_window=False)
        self.app._refresh_ui(force_tray=True)

    def _step_provider_order(self, prov: str, delta: int) -> None:
        order = self.app._provider_order()
        if prov not in order:
            return
        i = order.index(prov)
        j = i + delta
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            self._apply_new_provider_order(order, save=True)

    def _on_order_drag_start(self, prov: str, _event: tk.Event) -> None:
        self._drag_prov = prov
        pal = self.app._pal()
        info = self._order_rows.get(prov)
        if not info:
            return
        info["frame"].configure(highlightbackground=pal["accent_agy"], highlightthickness=2)
        for w in info["bg_widgets"]:
            w.configure(bg=pal["bg_btn"])
        info["rank"].configure(bg=pal["accent_agy"], fg="#0B1120")

    def _on_order_drag_motion(self, event: tk.Event) -> None:
        prov = self._drag_prov
        if not prov:
            return
        order = self.app._provider_order()
        if prov not in order:
            return
        cur_idx = order.index(prov)
        y = event.y_root

        if cur_idx > 0:
            prev_rf = self._order_rows[order[cur_idx - 1]]["frame"]
            if y < prev_rf.winfo_rooty() + prev_rf.winfo_height() // 2:
                order[cur_idx], order[cur_idx - 1] = order[cur_idx - 1], order[cur_idx]
                self._apply_new_provider_order(order, save=False)
                self._order_list_frame.update_idletasks()
                return
        if cur_idx < len(order) - 1:
            next_rf = self._order_rows[order[cur_idx + 1]]["frame"]
            if y > next_rf.winfo_rooty() + next_rf.winfo_height() // 2:
                order[cur_idx], order[cur_idx + 1] = order[cur_idx + 1], order[cur_idx]
                self._apply_new_provider_order(order, save=False)
                self._order_list_frame.update_idletasks()
                return

    def _on_order_drag_end(self, _event: tk.Event) -> None:
        prov = self._drag_prov
        if not prov:
            return
        self._drag_prov = None
        pal = self.app._pal()
        info = self._order_rows.get(prov)
        if info:
            info["frame"].configure(highlightbackground=pal["border"], highlightthickness=1)
            for w in info["bg_widgets"]:
                w.configure(bg=pal["bg_main"])
            info["rank"].configure(bg=pal["bg_btn"], fg=pal["text_sec"])
        save_config(self.app.cfg)

    def _open_data_dir(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(DATA_DIR))
            else:
                import subprocess

                subprocess.Popen(["open", str(DATA_DIR)])
        except Exception:
            pass
