"""Anti-aliased Pillow visual renderers for dual concentric ring gauges
and compact-style preview graphics (used in Settings cards & hover preview tooltips).
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

STYLE_INFO: Dict[str, Tuple[str, str, str]] = {
    "dual": (
        "2줄 (주간+5h)",
        "주간 + 5시간 동시 표시",
        "주간 바와 5시간 단기 바·남은 시간을\n2줄 수직 정렬 카드로 한눈에 표시합니다.",
    ),
    "slim": (
        "1줄 슬림",
        "초슬림 높이 · 2단 바",
        "가장 작은 높이(99px)에 위(주간)/아래(5h) 2단 바 표시.\n우측 숫자를 클릭하면 5h ↔ 모델별(Ar·Fb)로 전환됩니다.",
    ),
    "ring": (
        "원형 2중 링",
        "바깥=주간 · 안쪽=5h",
        "안티앨리어싱 2중 원형 게이지로 바깥 링은 주간,\n안쪽 링은 5시간 단기 사용량을 감각적으로 표시합니다.",
    ),
}


def render_dual_ring_png(
    size: int,
    outer_pct: Optional[float],
    outer_col: str,
    inner_pct: Optional[float],
    inner_col: str,
    track_col: str,
    outer_w: int = 6,
    inner_w: int = 4,
) -> bytes:
    """Render 4x supersampled anti-aliased RGBA dual concentric ring gauge as PNG bytes."""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def _draw_ring(inset_px: int, width_px: int, pct: Optional[float], col: str) -> None:
        inset = inset_px * scale
        thick = width_px * scale
        box = [inset, inset, s - inset - 1, s - inset - 1]
        draw.arc(box, 0, 360, fill=track_col, width=thick)
        if pct is None or pct <= 0.0:
            return
        clamped = max(0.0, min(100.0, pct))
        if clamped >= 99.6:
            draw.arc(box, 0, 360, fill=col, width=thick)
            return
        sweep = max(4.0, 360.0 * (clamped / 100.0))
        start_deg = -90.0
        end_deg = start_deg + sweep
        draw.arc(box, start_deg, end_deg, fill=col, width=thick)

        cx = (box[0] + box[2]) / 2.0
        cy = (box[1] + box[3]) / 2.0
        r_mid = ((box[2] - box[0]) - (thick - 1)) / 2.0
        cap_r = (thick - 1) / 2.0
        for deg in (start_deg, end_deg):
            rad = math.radians(deg)
            px = cx + r_mid * math.cos(rad)
            py = cy + r_mid * math.sin(rad)
            draw.ellipse([px - cap_r, py - cap_r, px + cap_r, py + cap_r], fill=col)

    _draw_ring(2, outer_w, outer_pct, outer_col)
    _draw_ring(2 + outer_w + 3, inner_w, inner_pct, inner_col)

    small = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def render_style_preview_png(
    style: str,
    pal: Dict[str, str],
    width: int = 148,
    height: int = 74,
) -> bytes:
    """Render a crisp 3x supersampled miniature mockup of the chosen compact style."""
    sc = 3
    W, H = width * sc, height * sc
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    bg_main = pal["bg_main"]
    bg_card = pal["bg_card"]
    track = pal["bg_track"]
    border = pal["border"]
    txt_pri = pal["text_pri"]
    txt_mut = pal["text_muted"]
    c_agy = pal["accent_agy"]
    c_agy_5h = pal.get("accent_agy_5h", c_agy)
    c_arg = pal["accent_argon"]
    c_cld = pal["accent_claude"]
    c_cld_5h = pal.get("accent_claude_5h", c_cld)
    c_fbl = pal["accent_fable"]

    # Outer mini HUD frame
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=8 * sc, fill=bg_main, outline=border, width=sc)

    # Mini header bar (title placeholder + 3 mini dots)
    d.rounded_rectangle([8 * sc, 6 * sc, 48 * sc, 9 * sc], radius=2 * sc, fill=txt_mut)
    for idx in range(3):
        bx = W - (10 + idx * 8) * sc
        d.ellipse([bx - 2 * sc, 6 * sc, bx + 2 * sc, 10 * sc], fill=txt_mut)

    def _bar(x0: int, y0: int, x1: int, y1: int, ratio: float, col: str) -> None:
        r = max(sc, (y1 - y0) // 2)
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=track)
        fw = max(2 * r, int((x1 - x0) * ratio))
        d.rounded_rectangle([x0, y0, min(x1, x0 + fw), y1], radius=r, fill=col)

    if style == "dual":
        # 2 stacked dual-line cards
        cards = [
            (14, 38, c_agy, c_agy_5h, c_arg, 0.42, 0.25),
            (42, 66, c_cld, c_cld_5h, c_fbl, 0.22, 0.58),
        ]
        for y0, y1, c1, c5h, cmod, r1, r2 in cards:
            d.rounded_rectangle([7 * sc, y0 * sc, W - 7 * sc, y1 * sc], radius=5 * sc, fill=bg_card)
            # Row 1: dot + label + thick weekly bar + right badges
            d.ellipse([12 * sc, (y0 + 5) * sc, 16 * sc, (y0 + 9) * sc], fill=c1)
            d.rounded_rectangle([19 * sc, (y0 + 5) * sc, 31 * sc, (y0 + 9) * sc], radius=2 * sc, fill=txt_pri)
            _bar(36 * sc, (y0 + 5) * sc, 94 * sc, (y0 + 10) * sc, r1, c1)
            d.rounded_rectangle([99 * sc, (y0 + 5) * sc, 113 * sc, (y0 + 9) * sc], radius=2 * sc, fill=txt_pri)
            d.rounded_rectangle([118 * sc, (y0 + 5) * sc, 136 * sc, (y0 + 9) * sc], radius=2 * sc, fill=cmod)
            # Row 2: 5h mini label + slim 5h bar + mini countdown
            d.rounded_rectangle([19 * sc, (y0 + 15) * sc, 28 * sc, (y0 + 18) * sc], radius=sc, fill=txt_mut)
            _bar(36 * sc, (y0 + 15) * sc, 94 * sc, (y0 + 18) * sc, r2, c5h)
            d.rounded_rectangle([101 * sc, (y0 + 15) * sc, 113 * sc, (y0 + 18) * sc], radius=sc, fill=txt_mut)
            d.rounded_rectangle([120 * sc, (y0 + 15) * sc, 136 * sc, (y0 + 18) * sc], radius=sc, fill=txt_mut)

    elif style == "slim":
        # Compact centered 2 single-line cards with 2-tier stacked bar
        cards = [
            (20, 38, c_agy, c_agy_5h, 0.45, 0.28),
            (43, 61, c_cld, c_cld_5h, 0.20, 0.62),
        ]
        for y0, y1, c1, c5h, r1, r2 in cards:
            d.rounded_rectangle([7 * sc, y0 * sc, W - 7 * sc, y1 * sc], radius=5 * sc, fill=bg_card)
            d.ellipse([12 * sc, (y0 + 7) * sc, 16 * sc, (y0 + 11) * sc], fill=c1)
            d.rounded_rectangle([19 * sc, (y0 + 7) * sc, 31 * sc, (y0 + 11) * sc], radius=2 * sc, fill=txt_pri)
            # Stacked 2-tier bar (top weekly 3.5px + bottom 5h 2px)
            _bar(36 * sc, (y0 + 5) * sc, 94 * sc, (y0 + 9) * sc, r1, c1)
            _bar(36 * sc, (y0 + 11) * sc, 94 * sc, (y0 + 13) * sc, r2, c5h)
            d.rounded_rectangle([99 * sc, (y0 + 7) * sc, 113 * sc, (y0 + 11) * sc], radius=2 * sc, fill=txt_pri)
            # Clickable right badge (5h / model)
            d.rounded_rectangle([117 * sc, (y0 + 6) * sc, 136 * sc, (y0 + 12) * sc], radius=3 * sc, fill=c5h)

    else:  # "ring"
        # 2 side-by-side circular dual-ring cards
        mid = W // 2
        card_specs = [
            (7 * sc, mid - 2 * sc, c_agy, c_agy_5h, 45.0, 26.0),
            (mid + 2 * sc, W - 7 * sc, c_cld, c_cld_5h, 22.0, 62.0),
        ]
        for x0, x1, c1, c2, p1, p2 in card_specs:
            d.rounded_rectangle([x0, 14 * sc, x1, 67 * sc], radius=6 * sc, fill=bg_card)
            cx = (x0 + x1) // 2
            cy = 34 * sc

            def _ring(rad_px: int, w_px: int, pct: float, col: str) -> None:
                rad = rad_px * sc
                w = w_px * sc
                box = [cx - rad, cy - rad, cx + rad, cy + rad]
                d.arc(box, 0, 360, fill=track, width=w)
                sweep = max(8.0, 360.0 * (pct / 100.0))
                d.arc(box, -90.0, -90.0 + sweep, fill=col, width=w)

            _ring(15, 3, p1, c1)
            _ring(10, 2, p2, c2)
            # Center % placeholder
            d.rounded_rectangle([cx - 5 * sc, cy - 2 * sc, cx + 5 * sc, cy + 2 * sc], radius=sc, fill=txt_pri)
            # Short name & sub bar underneath
            d.rounded_rectangle([cx - 10 * sc, 53 * sc, cx + 10 * sc, 56 * sc], radius=sc, fill=c1)
            d.rounded_rectangle([cx - 18 * sc, 59 * sc, cx + 18 * sc, 62 * sc], radius=sc, fill=txt_mut)

    small = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def _hex_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


def render_history_chart_png(
    entries: List[Dict[str, Any]],
    provider: str,
    hours: float,
    now: float,
    pal: Dict[str, str],
    accent_hex: str,
    s5_hex: str,
    warn_pct: int = 80,
    mode: str = "used",
    width: int = 474,
    height: int = 82,
) -> bytes:
    """Render a crisp 2x anti-aliased usage trend sparkline (weekly area + 5h line)."""
    sc = 2
    W, H = width * sc, height * sc
    img = Image.new("RGBA", (W, H), _hex_rgba(pal["bg_main"], 255))
    d = ImageDraw.Draw(img, "RGBA")

    pad_l, pad_r, pad_t, pad_b = 6 * sc, 6 * sc, 7 * sc, 7 * sc
    cw = max(1, W - pad_l - pad_r)
    ch = max(1, H - pad_t - pad_b)

    # Subtle outer frame & horizontal reference lines (0%, 50%, warn%, 100%)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=6 * sc, fill=_hex_rgba(pal["bg_main"], 255), outline=_hex_rgba(pal["border"], 190), width=sc)

    def y_for_pct(val: float) -> float:
        clamped = max(0.0, min(100.0, val))
        return pad_t + ch * (1.0 - clamped / 100.0)

    # 50% subtle guide line
    y50 = y_for_pct(50.0)
    d.line([(pad_l, y50), (W - pad_r, y50)], fill=_hex_rgba(pal["border"], 130), width=sc)

    # User's custom warning line (dashed)
    if warn_pct and 0 < warn_pct < 100:
        w_line_val = float(warn_pct) if mode == "used" else float(100 - warn_pct)
        yw = y_for_pct(w_line_val)
        x = pad_l
        while x < W - pad_r:
            d.line([(x, yw), (min(W - pad_r, x + 5 * sc), yw)], fill=_hex_rgba(pal["warn"], 130), width=sc)
            x += 9 * sc

    t_start = now - hours * 3600.0
    t_span = max(60.0, hours * 3600.0)

    wk_pts: List[Tuple[float, float]] = []
    s5_pts: List[Tuple[float, float]] = []

    for e in entries:
        ts = float(e.get("ts") or 0.0)
        if ts < t_start:
            continue
        pd = e.get(provider)
        if not isinstance(pd, dict):
            continue
        x = pad_l + cw * max(0.0, min(1.0, (ts - t_start) / t_span))
        wk = pd.get("wk")
        if wk is not None:
            v = float(wk) if mode == "used" else max(0.0, 100.0 - float(wk))
            wk_pts.append((x, y_for_pct(v)))
        s5 = pd.get("s5")
        if s5 is not None:
            v5 = float(s5) if mode == "used" else max(0.0, 100.0 - float(s5))
            s5_pts.append((x, y_for_pct(v5)))

    # Soft translucent area fill + solid weekly line
    if len(wk_pts) >= 2:
        poly = [(wk_pts[0][0], pad_t + ch)] + wk_pts + [(wk_pts[-1][0], pad_t + ch)]
        d.polygon(poly, fill=_hex_rgba(accent_hex, 42))
        d.line(wk_pts, fill=_hex_rgba(accent_hex, 245), width=2 * sc)
    if wk_pts:
        lx, ly = wk_pts[-1]
        r = 3 * sc
        d.ellipse([lx - r, ly - r, lx + r, ly + r], fill=_hex_rgba(accent_hex, 255))

    # Secondary 5h line (slimmer, secondary accent)
    if len(s5_pts) >= 2:
        d.line(s5_pts, fill=_hex_rgba(s5_hex, 185), width=max(1, int(1.4 * sc)))
    if s5_pts:
        lx5, ly5 = s5_pts[-1]
        r5 = 2 * sc
        d.ellipse([lx5 - r5, ly5 - r5, lx5 + r5, ly5 + r5], fill=_hex_rgba(s5_hex, 220))

    small = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()
