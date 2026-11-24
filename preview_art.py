"""Anti-aliased Pillow visual renderers for dual concentric ring gauges
and compact-style preview graphics (used in Settings cards & hover preview tooltips).
"""

from __future__ import annotations

import io
import math
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw


def png_bytes_to_photoimage(png_bytes: bytes, master: Optional[tk.Misc] = None) -> Any:
    """Create a Tk-compatible PhotoImage from PNG bytes on both Tk 8.6+/9.0 and macOS Tk 8.5."""
    try:
        return tk.PhotoImage(data=png_bytes, master=master)
    except tk.TclError:
        from PIL import ImageTk

        img = Image.open(io.BytesIO(png_bytes))
        return ImageTk.PhotoImage(img, master=master)

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


def _hex_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


def _blend_hex(fg_hex: str, bg_hex: str, ratio: float) -> Tuple[int, int, int, int]:
    fr, fg, fb, _ = _hex_rgba(fg_hex)
    br, bg, bb, _ = _hex_rgba(bg_hex)
    r = int(round(br + (fr - br) * ratio))
    g = int(round(bg + (fg - bg) * ratio))
    b = int(round(bb + (fb - bb) * ratio))
    return (r, g, b, 255)


# 10x10 hand-crafted pixel-art RPG hero grids per AI provider
_RPG_SPRITES: Dict[str, List[str]] = {
    # Blue Star Wizard (pointy wizard hat + gold rim + cute face + cloak)
    "antigravity": [
        "....AA....",
        "...AAAA...",
        "..AAAAAA..",
        ".GGGGGGGG.",
        "..SSSSSS..",
        "..SEESES..",
        "..SSSSSS..",
        "..AAAAAA..",
        ".AAAAAAAA.",
        "..BB..BB..",
    ],
    # Orange Fox-Mage (cute ears hood + scarf + eyes + cloak)
    "claude": [
        ".AA....AA.",
        ".AAA..AAA.",
        ".AAAAAAAA.",
        ".ASSSSSSA.",
        ".ASEESESA.",
        "..SSSSSS..",
        "..GGGGGG..",
        ".AAAAAAAA.",
        "..AAAAAA..",
        "..BB..BB..",
    ],
    # Green Mecha-Bot Ranger (antenna + glowing visor + armor)
    "codex": [
        "....GG....",
        "....AA....",
        "..AAAAAA..",
        ".ABBBBBBA.",
        ".ABEEBEBA.",
        ".ABBBBBBA.",
        "..AAAAAA..",
        ".AAGGGGAA.",
        "..AAAAAA..",
        "..BB..BB..",
    ],
}

# 10x10 pixel-art White Hare / Rabbit (토끼) facing right with subtle dark outline so it pops on Light & Dark!
_HARE_GRID: List[str] = [
    "...DW.DW..",
    "...DP.DP..",
    "...DWWWW..",
    "..DWWWWED.",
    "..DWWWWWP.",
    ".WDAAAAWD.",
    ".DWWWWWWD.",
    "..DW..DW..",
    ".DW....DW.",
    "..........",
]

# 10x10 pixel-art Green Tortoise (거북이) facing right with spotted domed shell + cute lime head & legs!
_TORTOISE_GRID: List[str] = [
    "..........",
    "..........",
    "..DDDDD...",
    ".DGGKGGD..",
    "DGGKGGKGD.",
    "DGGGGGGDLL",
    "DGGGGGGDLE",
    ".DDDDDDDLL",
    ".DL..DL...",
    "..........",
]

# 8x8 retro 2001 4-pane square mosaic badge icon for the glossy blue titlebar
_RETRO01_BADGE_GRID: List[str] = [
    "........",
    ".RRR.GG.",
    ".RRR.GG.",
    ".RRR.GG.",
    "........",
    ".BBB.YY.",
    ".BBB.YY.",
    "........",
]


def _draw_pixel_grid(
    img: Image.Image,
    grid: List[str],
    cmap: Dict[str, Tuple[int, int, int, int]],
    ox: int,
    oy: int,
    px: int,
) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    for r_i, row in enumerate(grid):
        for c_i, ch in enumerate(row):
            col = cmap.get(ch)
            if col is not None:
                x0 = ox + c_i * px
                y0 = oy + r_i * px
                d.rectangle([x0, y0, x0 + px - 1, y0 + px - 1], fill=col)


def render_rpg_hero_png(
    prov: str,
    mood: str,
    accent_hex: str,
    bg_hex: str,
    dark: bool = True,
    size: int = 20,
) -> bytes:
    """Render a crisp pixel-art RPG hero sprite (reacts to ok / warn / crit usage!)."""
    img = Image.new("RGBA", (size, size), _hex_rgba(bg_hex, 255))
    grid = list(_RPG_SPRITES.get(prov, _RPG_SPRITES["antigravity"]))
    px = max(1, size // 10)
    ox = (size - 10 * px) // 2
    oy = (size - 10 * px) // 2

    skin = (255, 224, 189, 255) if prov != "codex" else (210, 232, 224, 255)
    eye = (24, 24, 32, 255) if prov != "codex" else (110, 255, 190, 255)
    if mood == "crit":
        eye = (255, 72, 72, 255)
    gold = (250, 204, 21, 255)
    boots = (58, 52, 66, 255) if dark else (45, 42, 54, 255)
    cmap = {
        "A": _hex_rgba(accent_hex, 255),
        "S": skin,
        "E": eye,
        "G": gold,
        "B": boots,
    }
    _draw_pixel_grid(img, grid, cmap, ox, oy, px)

    d = ImageDraw.Draw(img, "RGBA")
    if mood == "warn":
        # Cute cyan sweat drop on upper-right
        d.rectangle([size - 2 * px, oy + 2 * px, size - 1, oy + 4 * px - 1], fill=(56, 189, 248, 255))
    elif mood == "crit":
        # Urgent red '!' pixel marker at top-right
        d.rectangle([size - 2 * px, oy, size - 1, oy + 3 * px - 1], fill=(248, 68, 68, 255))
        d.rectangle([size - 2 * px, oy + 4 * px, size - 1, oy + 5 * px - 1], fill=(248, 68, 68, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_hare_sprite_png(
    accent_hex: str,
    mood: str = "ok",
    size: int = 20,
) -> bytes:
    """Render a crisp pixel-art sprinting White Rabbit (토끼) for Hare & Tortoise theme."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = max(1, size // 10)
    ox = (size - 10 * px) // 2
    oy = (size - 10 * px) // 2
    cmap = {
        "W": (252, 250, 246, 255),
        "P": (248, 165, 194, 255),
        "D": (52, 46, 44, 255),
        "E": (239, 68, 68, 255) if mood == "crit" else (24, 24, 30, 255),
        "A": _hex_rgba(accent_hex, 255),
    }
    _draw_pixel_grid(img, _HARE_GRID, cmap, ox, oy, px)
    d = ImageDraw.Draw(img, "RGBA")
    if mood == "warn":
        d.rectangle([ox, oy + px, ox + px - 1, oy + 3 * px - 1], fill=(56, 189, 248, 255))
    elif mood == "crit":
        d.rectangle([ox, oy, ox + px - 1, oy + 2 * px - 1], fill=(248, 68, 68, 255))
        d.rectangle([ox, oy + 3 * px, ox + px - 1, oy + 4 * px - 1], fill=(248, 68, 68, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_tortoise_sprite_png(size: int = 20) -> bytes:
    """Render a crisp pixel-art steady Green Tortoise (거북이) for Hare & Tortoise theme."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = max(1, size // 10)
    ox = (size - 10 * px) // 2
    oy = (size - 10 * px) // 2
    cmap = {
        "D": (24, 52, 30, 255),
        "G": (46, 168, 76, 255),
        "K": (26, 108, 48, 255),
        "L": (134, 224, 112, 255),
        "E": (20, 22, 26, 255),
    }
    _draw_pixel_grid(img, _TORTOISE_GRID, cmap, ox, oy, px)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_paper_plane_png(
    accent_hex: str,
    mood: str = "ok",
    dark: bool = False,
    size: int = 20,
) -> bytes:
    """Render a graceful 3x anti-aliased Storybook Watercolor folded origami Paper Airplane (종이비행기)."""
    sc = 3
    s = size * sc
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    tip = (s * 0.94, s * 0.34)
    tail_top = (s * 0.10, s * 0.24)
    crease_mid = (s * 0.32, s * 0.54)
    keel_bot = (s * 0.36, s * 0.78)
    wing_bot = (s * 0.44, s * 0.62)
    tail_low = (s * 0.20, s * 0.70)

    paper_hi = (255, 255, 255, 255) if not dark else (250, 248, 240, 255)
    paper_mid = (228, 241, 252, 255) if not dark else (210, 224, 244, 255)
    paper_sh = (168, 200, 228, 255) if not dark else (130, 158, 200, 255)
    ink = (72, 102, 132, 240) if not dark else (44, 62, 92, 240)
    if mood == "crit":
        paper_mid = (255, 222, 214, 255)

    # Lower right wing
    d.polygon([tip, crease_mid, tail_low], fill=paper_mid, outline=ink)
    # Deep folded underside keel (3D origami shadow!)
    d.polygon([tip, crease_mid, keel_bot, wing_bot], fill=paper_sh, outline=ink)
    # Main sunlit upper wing
    d.polygon([tip, tail_top, crease_mid], fill=paper_hi, outline=ink)
    # Delicate accent stripe along upper wing edge
    d.line([tail_top, tip], fill=_hex_rgba(accent_hex, 210), width=max(2, int(round(0.8 * sc))))

    small = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def render_paper_boat_png(
    accent_hex: str,
    mood: str = "ok",
    dark: bool = False,
    size: int = 20,
) -> bytes:
    """Render an adorable 3x anti-aliased Storybook Watercolor folded origami Paper Sailboat (종이돛단배)."""
    sc = 3
    s = size * sc
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    paper_hi = (255, 255, 255, 255) if not dark else (248, 246, 238, 255)
    paper_sh = (196, 224, 234, 255) if not dark else (160, 192, 212, 255)
    hull_c = (242, 249, 252, 255) if not dark else (224, 236, 246, 255)
    ink = (56, 98, 114, 240) if not dark else (38, 68, 84, 245)

    # Tiny fluttering pennant flag at mast tip
    mast_top = (s * 0.50, s * 0.14)
    d.polygon([mast_top, (s * 0.72, s * 0.21), (s * 0.50, s * 0.28)], fill=_hex_rgba(accent_hex, 245))

    # Classic triangular origami center sail (sunlit left + folded shadow right)
    d.polygon([mast_top, (s * 0.26, s * 0.62), (s * 0.50, s * 0.62)], fill=paper_hi, outline=ink)
    d.polygon([mast_top, (s * 0.50, s * 0.62), (s * 0.74, s * 0.62)], fill=paper_sh, outline=ink)

    # Folded trapezoidal origami paper hull
    hull_pts = [(s * 0.08, s * 0.60), (s * 0.92, s * 0.60), (s * 0.76, s * 0.86), (s * 0.24, s * 0.86)]
    d.polygon(hull_pts, fill=hull_c, outline=ink)
    # Center hull crease triangle
    d.polygon([(s * 0.34, s * 0.60), (s * 0.66, s * 0.60), (s * 0.50, s * 0.82)], fill=paper_sh, outline=ink)

    # Warm Storybook sea-train lantern glow on dark ocean nights (true alpha composite!)
    if dark:
        glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow, "RGBA")
        lx, ly = s * 0.78, s * 0.55
        gd.ellipse([lx - 3.6 * sc, ly - 3.6 * sc, lx + 3.6 * sc, ly + 3.6 * sc], fill=(253, 224, 120, 115))
        gd.ellipse([lx - 1.5 * sc, ly - 1.5 * sc, lx + 1.5 * sc, ly + 1.5 * sc], fill=(255, 246, 195, 255))
        img = Image.alpha_composite(img, glow)

    small = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def render_runner_sprite_png(
    accent_hex: str,
    mood: str,
    bg_hex: str,
    size: int = 20,
) -> bytes:
    """Backwards-compatible alias that renders the White Hare sprite."""
    return render_hare_sprite_png(accent_hex, mood=mood, size=size)


def render_retro01_badge_png(bg_hex: str, size: int = 16) -> bytes:
    """Render the iconic tiny 4-color Retro 2001 flag icon for the Retro 2001 titlebar."""
    img = Image.new("RGBA", (size, size), _hex_rgba(bg_hex, 255))
    px = max(1, size // 8)
    ox = (size - 8 * px) // 2
    oy = (size - 8 * px) // 2
    cmap = {
        "R": (242, 80, 34, 255),
        "G": (127, 186, 0, 255),
        "B": (0, 164, 239, 255),
        "Y": (255, 185, 0, 255),
    }
    _draw_pixel_grid(img, _RETRO01_BADGE_GRID, cmap, ox, oy, px)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_traffic_dots_png(
    bg_hex: Optional[str],
    style: str = "gel",
    dark: bool = False,
    width: int = 38,
    height: int = 16,
) -> bytes:
    """Render 3 traffic-dot window gems (Original 3D glossy gel OR Liquid Glass)."""
    sc = 3
    W, H = width * sc, height * sc
    bg_rgba = _hex_rgba(bg_hex, 255) if bg_hex else (0, 0, 0, 0)
    img = Image.new("RGBA", (W, H), bg_rgba)
    d = ImageDraw.Draw(img, "RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov, "RGBA")
    cy = H // 2
    r = int(round(4.1 * sc))
    xs = (6 * sc, 18 * sc, 30 * sc)
    if style == "gel":
        # Classic Glossy 3D glossy jewel droplets with true alpha-composited upper glass glare & bottom bounce glow!
        cols = (("#FF5F56", "#C83228"), ("#FFBD2E", "#C48A14"), ("#27C93F", "#158E27"))
        for cx, (fill_c, rim_c) in zip(xs, cols):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill_c, outline=rim_c, width=max(1, sc // 2))
            od.ellipse([cx - int(r * 0.55), cy - int(r * 0.72), cx + int(r * 0.55), cy - int(r * 0.05)], fill=(255, 255, 255, 195))
            od.ellipse([cx - int(r * 0.42), cy + int(r * 0.25), cx + int(r * 0.42), cy + int(r * 0.72)], fill=(255, 255, 255, 110))
    else:
        # Latest Liquid Glass frosted crystal droplets with bright glass rim highlight!
        cols = ("#FF6058", "#FEBC2E", "#2BC840")
        rim_col = (255, 255, 255, 185) if not dark else (220, 234, 255, 150)
        for cx, fill_c in zip(xs, cols):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_hex_rgba(fill_c, 235), outline=rim_col, width=max(1, sc // 2))
            od.arc([cx - r + sc, cy - r + sc, cx + r - sc, cy + r - sc], start=205, end=330, fill=(255, 255, 255, 215), width=max(1, sc // 2))
    img = Image.alpha_composite(img, ov)
    small = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def render_silver_metal_titlebar_png(width: int, height: int = 24, dark: bool = False) -> bytes:
    """Render authentic Brushed Metal brushed metallic aluminum titlebar (Light Silver / Dark Titanium)."""
    img = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    if not dark:
        stops = [(0.0, "#F2F4F7"), (0.12, "#E4E7EC"), (0.55, "#CDD2DA"), (0.95, "#B6BCC6"), (1.0, "#8E94A0")]
        stripe_c = (255, 255, 255, 58)
    else:
        stops = [(0.0, "#3D424C"), (0.14, "#313640"), (0.58, "#252932"), (0.94, "#1C1F26"), (1.0, "#12141A")]
        stripe_c = (255, 255, 255, 20)
    for y in range(height):
        t = y / max(1.0, float(height - 1))
        col = _hex_rgba(stops[-1][1], 255)[:3]
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                col = _blend_hex(c1, c0, (t - t0) / max(1e-6, t1 - t0))[:3]
                break
        d.line([(0, y), (width - 1, y)], fill=col)
        if y % 2 == 1 and 1 < y < height - 2:
            d.line([(0, y), (width - 1, y)], fill=stripe_c)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_retro01_titlebar_png(width: int, height: int = 26, dark: bool = False) -> bytes:
    """Render authentic multi-band glossy 3D Retro 2001 Blue (Light) or Midnight Noir (Dark) titlebar."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    d = ImageDraw.Draw(img, "RGBA")
    if not dark:
        # Retro 2001 glossy cobalt blue vertical 3D glass-tube gradient!
        stops = [
            (0.00, "#3D95FF"),
            (0.10, "#75B8FF"),
            (0.22, "#247AF8"),
            (0.42, "#0054E3"),
            (0.76, "#0047D1"),
            (0.92, "#0035B0"),
            (1.00, "#00288F"),
        ]
    else:
        # Retro 2001 midnight slate noir glossy dark glass-tube gradient!
        stops = [
            (0.00, "#5A677D"),
            (0.12, "#73829C"),
            (0.26, "#394254"),
            (0.46, "#283040"),
            (0.50, "#151924"),
            (0.86, "#1E2534"),
            (1.00, "#10131C"),
        ]
    for y in range(height):
        t = y / max(1.0, float(height - 1))
        col = _hex_rgba(stops[-1][1], 255)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                frac = (t - t0) / max(1e-6, t1 - t0)
                col = _blend_hex(c1, c0, frac)
                break
        d.line([(0, y), (width - 1, y)], fill=col)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_scenic_titlebar_png(width: int, height: int = 26, kind: str = "sky", dark: bool = False) -> bytes:
    """Render a soft Storybook Watercolor watercolor sky or coastal ocean header strip."""
    img = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    if kind == "sky":
        if not dark:
            stops = [(0.0, "#84CAF7"), (0.48, "#9ED5FA"), (0.88, "#C6E7FD"), (1.0, "#9CC8E8")]
        else:
            stops = [(0.0, "#141E36"), (0.50, "#1B2846"), (0.90, "#233459"), (1.0, "#354970")]
    else:
        if not dark:
            stops = [(0.0, "#A9E5ED"), (0.48, "#83D9E3"), (0.88, "#5EC4D1"), (1.0, "#86C2C9")]
        else:
            stops = [(0.0, "#0F202E"), (0.50, "#152D40"), (0.90, "#1C3E54"), (1.0, "#2F5066")]
    for y in range(height):
        t = y / max(1.0, float(height - 1))
        col = _hex_rgba(stops[-1][1], 255)[:3]
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                col = _blend_hex(c1, c0, (t - t0) / max(1e-6, t1 - t0))[:3]
                break
        d.line([(0, y), (width - 1, y)], fill=col)

    if kind == "sky":
        if not dark:
            # Wispy fluffy white Storybook cumulus clouds peeking along the lower horizon!
            for cx, cy, rx, ry in ((width * 0.44, height - 2, 16, 7), (width * 0.56, height - 1, 22, 8), (width * 0.64, height - 3, 12, 6)):
                d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(255, 255, 255, 185))
        else:
            # Gentle twinkling stars across the twilight sky
            for fx, fy, r in ((0.42, 0.28, 1), (0.52, 0.62, 1), (0.61, 0.24, 1.3), (0.71, 0.54, 1)):
                sx, sy = width * fx, height * fy
                d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(253, 230, 138, 225))
    else:
        # Shimmering coastal ripples (윤슬) along the lower sea edge
        glint = (253, 230, 148, 165) if dark else (255, 255, 255, 195)
        for fx, lw in ((0.42, 10), (0.52, 14), (0.63, 9), (0.70, 12)):
            sx = int(width * fx)
            d.line([(sx, height - 5), (sx + lw, height - 5)], fill=glint, width=1)
            d.line([(sx + 4, height - 3), (sx + 4 + lw // 2, height - 3)], fill=glint, width=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_scenic_emblem_png(bg_hex: Optional[str], kind: str = "sky", dark: bool = False, size: int = 16) -> bytes:
    """Render tiny Storybook Watercolor header emblem (Sun+Cloud / Crescent Moon for Sky, Sail+Wave for Sea)."""
    sc = 3
    s = size * sc
    bg_rgba = _hex_rgba(bg_hex, 255) if bg_hex else (0, 0, 0, 0)
    img = Image.new("RGBA", (s, s), bg_rgba)
    d = ImageDraw.Draw(img, "RGBA")
    if kind == "sky":
        if not dark:
            # Warm sun peeking over a fluffy white cumulus cloud
            d.ellipse([s * 0.44, s * 0.10, s * 0.88, s * 0.54], fill=(253, 200, 72, 255))
            d.ellipse([s * 0.14, s * 0.40, s * 0.58, s * 0.84], fill=(255, 255, 255, 255))
            d.ellipse([s * 0.34, s * 0.30, s * 0.78, s * 0.78], fill=(255, 255, 255, 255))
            d.ellipse([s * 0.50, s * 0.44, s * 0.90, s * 0.84], fill=(255, 255, 255, 255))
        else:
            # Pale golden crescent moon + tiny star
            d.ellipse([s * 0.16, s * 0.16, s * 0.76, s * 0.82], fill=(253, 230, 138, 255))
            d.ellipse([s * 0.34, s * 0.12, s * 0.88, s * 0.72], fill=bg_rgba)
            d.ellipse([s * 0.74, s * 0.24, s * 0.88, s * 0.38], fill=(255, 248, 210, 255))
    else:
        # Tiny white folded origami sail over sparkling ocean wave
        sail_hi = (255, 255, 255, 255)
        sail_sh = (206, 234, 244, 255)
        d.polygon([(s * 0.50, s * 0.12), (s * 0.24, s * 0.62), (s * 0.50, s * 0.62)], fill=sail_hi)
        d.polygon([(s * 0.50, s * 0.12), (s * 0.50, s * 0.62), (s * 0.76, s * 0.62)], fill=sail_sh)
        wave_c = (94, 212, 224, 255) if dark else (22, 134, 156, 255)
        d.arc([s * 0.08, s * 0.58, s * 0.54, s * 0.94], start=190, end=350, fill=wave_c, width=max(2, int(round(1.4 * sc))))
        d.arc([s * 0.44, s * 0.58, s * 0.92, s * 0.94], start=190, end=350, fill=wave_c, width=max(2, int(round(1.4 * sc))))
        if dark:
            d.ellipse([s * 0.70, s * 0.44, s * 0.86, s * 0.60], fill=(253, 224, 120, 245))
    small = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def render_dual_ring_png(
    size: int,
    outer_pct: Optional[float],
    outer_col: str,
    inner_pct: Optional[float],
    inner_col: str,
    track_col: str,
    outer_w: int = 6,
    inner_w: int = 4,
    ring_style: str = "smooth",
    outline_col: Optional[str] = None,
    highlight_col: Optional[str] = None,
) -> bytes:
    """Render 3x anti-aliased RGBA dual concentric ring gauge for all 8 distinct UI themes."""
    scale = 3
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    cx = s / 2.0
    cy = s / 2.0

    def _draw_smooth_arc(inset_px: int, width_px: int, pct: Optional[float], col: str, round_caps: bool = True) -> None:
        inset = inset_px * scale
        thick = max(scale, width_px * scale)
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
        if round_caps:
            r_mid = ((box[2] - box[0]) - (thick - 1)) / 2.0
            cap_r = (thick - 1) / 2.0
            for deg in (start_deg, end_deg):
                rad = math.radians(deg)
                px = cx + r_mid * math.cos(rad)
                py = cy + r_mid * math.sin(rad)
                draw.ellipse([px - cap_r, py - cap_r, px + cap_r, py + cap_r], fill=col)

    def _draw_segmented_arc(inset_px: int, width_px: int, pct: Optional[float], col: str, n_seg: int = 16, gap: float = 5.0) -> None:
        inset = inset_px * scale
        thick = max(scale, width_px * scale)
        box = [inset, inset, s - inset - 1, s - inset - 1]
        step = 360.0 / n_seg
        filled_n = 0 if (pct is None or pct <= 0.0) else max(1, int(round(max(0.0, min(100.0, pct)) / 100.0 * n_seg)))
        for idx in range(n_seg):
            a0 = -90.0 + idx * step + gap / 2.0
            a1 = -90.0 + (idx + 1) * step - gap / 2.0
            draw.arc(box, a0, a1, fill=col if idx < filled_n else track_col, width=thick)

    if ring_style == "rpg_orb":
        # RPG HP/MP crystal medallion: double retro gold/ink frame + bold HP outer + MP inner
        rim = outline_col or "#EAB308"
        b_rim = [scale, scale, s - scale - 1, s - scale - 1]
        draw.ellipse(b_rim, outline=rim, width=max(2, int(round(1.4 * scale))))
        _draw_segmented_arc(4, outer_w, outer_pct, outer_col, n_seg=16, gap=3.2)
        _draw_smooth_arc(4 + outer_w + 3, inner_w, inner_pct, inner_col, round_caps=False)

    elif ring_style == "track":
        # Stadium running track oval with dashed lane line, finish line at 12 o'clock & runner dot
        _draw_smooth_arc(3, outer_w + 1, outer_pct, outer_col, round_caps=False)
        # Dashed white track lane line along middle of outer track
        r_mid = (s / 2.0) - (3 + (outer_w + 1) / 2.0) * scale
        dash_col = _hex_rgba(highlight_col or "#FFFFFF", 145)
        for deg in range(0, 360, 20):
            r0 = math.radians(deg)
            r1 = math.radians(deg + 8)
            draw.line(
                [(cx + r_mid * math.cos(r0), cy + r_mid * math.sin(r0)),
                 (cx + r_mid * math.cos(r1), cy + r_mid * math.sin(r1))],
                fill=dash_col, width=max(1, int(round(0.7 * scale))),
            )
        # Checkered finish bar at 12 o'clock
        draw.rectangle([cx - scale, 2 * scale, cx + scale, (4 + outer_w) * scale], fill="#FFFFFF")
        draw.rectangle([cx - scale, 2 * scale, cx, (3 + outer_w // 2) * scale], fill="#141414")
        draw.rectangle([cx, (3 + outer_w // 2) * scale, cx + scale, (4 + outer_w) * scale], fill="#141414")
        # Runner marker dot at current angle
        if outer_pct is not None and outer_pct > 0:
            ang = math.radians(-90.0 + 360.0 * (max(0.0, min(100.0, outer_pct)) / 100.0))
            rx = cx + r_mid * math.cos(ang)
            ry = cy + r_mid * math.sin(ang)
            rr = max(3, int(round(2.6 * scale)))
            draw.ellipse([rx - rr, ry - rr, rx + rr, ry + rr], fill="#FFFFFF", outline=outer_col, width=max(2, scale))
        _draw_smooth_arc(4 + outer_w + 4, max(2, inner_w - 1), inner_pct, inner_col, round_caps=True)

    elif ring_style == "thermo_dial":
        # Round analog dial thermometer with °C scale ticks & hot-cold indicator dot
        tick_col = outline_col or track_col
        r_out = (s / 2.0) - 1.2 * scale
        for idx in range(20):
            deg = 135.0 + idx * (270.0 / 19.0)
            rad = math.radians(deg)
            is_hot = idx >= 15
            t_len = (3.4 if idx % 5 == 0 else 2.0) * scale
            x0 = cx + (r_out - t_len) * math.cos(rad)
            y0 = cy + (r_out - t_len) * math.sin(rad)
            x1 = cx + r_out * math.cos(rad)
            y1 = cy + r_out * math.sin(rad)
            draw.line([(x0, y0), (x1, y1)], fill="#EF4444" if is_hot else tick_col, width=max(1, int(round(0.9 * scale))))
        # 270-degree thermal tube arc
        inset = 5 * scale
        thick = max(scale, outer_w * scale)
        box = [inset, inset, s - inset - 1, s - inset - 1]
        draw.arc(box, 135, 405, fill=track_col, width=thick)
        if outer_pct is not None and outer_pct > 0:
            sw = max(4.0, 270.0 * (max(0.0, min(100.0, outer_pct)) / 100.0))
            draw.arc(box, 135, 135 + sw, fill=outer_col, width=thick)
            # Thermometer mercury bulb at start (135 deg)
            r_mid = ((box[2] - box[0]) - (thick - 1)) / 2.0
            bx = cx + r_mid * math.cos(math.radians(135))
            by = cy + r_mid * math.sin(math.radians(135))
            br = thick * 0.72
            draw.ellipse([bx - br, by - br, bx + br, by + br], fill=outer_col, outline=highlight_col or "#FFFFFF", width=max(1, scale // 2))
        _draw_smooth_arc(5 + outer_w + 3, max(2, inner_w - 1), inner_pct, inner_col, round_caps=True)

    elif ring_style == "battery_ring":
        # Segmented 12-cell battery ring inside metallic casing
        rim = outline_col or track_col
        b_rim = [scale, scale, s - scale - 1, s - scale - 1]
        draw.ellipse(b_rim, outline=rim, width=max(1, int(round(1.0 * scale))))
        _draw_segmented_arc(4, outer_w, outer_pct, outer_col, n_seg=12, gap=7.0)
        _draw_segmented_arc(4 + outer_w + 3, max(2, inner_w - 1), inner_pct, inner_col, n_seg=10, gap=8.0)

    elif ring_style == "speedo_dial":
        # 270-degree sports-car RPM tachometer with crimson redline (75-100%) + radial pointer
        inset = 5 * scale
        thick = max(scale, outer_w * scale)
        box = [inset, inset, s - inset - 1, s - inset - 1]
        draw.arc(box, 135, 338, fill=track_col, width=thick)
        draw.arc(box, 338, 405, fill="#991B1B", width=thick)  # Redline zone 75-100%
        r_out = (s / 2.0) - 1.2 * scale
        for idx in range(21):
            deg = 135.0 + idx * (270.0 / 20.0)
            rad = math.radians(deg)
            is_red = idx >= 15
            t_len = (3.5 if idx % 5 == 0 else 2.0) * scale
            draw.line(
                [(cx + (r_out - t_len) * math.cos(rad), cy + (r_out - t_len) * math.sin(rad)),
                 (cx + r_out * math.cos(rad), cy + r_out * math.sin(rad))],
                fill="#EF4444" if is_red else (outline_col or track_col),
                width=max(1, int(round((1.2 if idx % 5 == 0 else 0.8) * scale))),
            )
        if outer_pct is not None and outer_pct > 0:
            cl = max(0.0, min(100.0, outer_pct))
            sw = max(4.0, 270.0 * (cl / 100.0))
            draw.arc(box, 135, 135 + sw, fill=outer_col, width=thick)
            # Crisp needle tip on the dial rim
            ang = math.radians(135.0 + sw)
            r_in = r_out - (outer_w + 5) * scale
            draw.line(
                [(cx + r_in * math.cos(ang), cy + r_in * math.sin(ang)),
                 (cx + (r_out - 2 * scale) * math.cos(ang), cy + (r_out - 2 * scale) * math.sin(ang))],
                fill="#FFFFFF", width=max(2, int(round(1.3 * scale))),
            )
        # Inner secondary mini-arc (270 deg)
        in2 = (5 + outer_w + 3) * scale
        b2 = [in2, in2, s - in2 - 1, s - in2 - 1]
        tw2 = max(scale, (inner_w - 1) * scale)
        draw.arc(b2, 135, 405, fill=track_col, width=tw2)
        if inner_pct is not None and inner_pct > 0:
            sw2 = max(4.0, 270.0 * (max(0.0, min(100.0, inner_pct)) / 100.0))
            draw.arc(b2, 135, 135 + sw2, fill=inner_col, width=tw2)

    elif ring_style in ("paper_sky", "paper_sea"):
        # Soft airy Storybook Watercolor watercolor ring with cloud/wave sparkle accent!
        _draw_smooth_arc(3, outer_w, outer_pct, outer_col, round_caps=True)
        _draw_smooth_arc(3 + outer_w + 3, inner_w, inner_pct, inner_col, round_caps=True)
        if ring_style == "paper_sky":
            # Tiny fluffy white cloud puff at top-right of ring
            d_r = 2.6 * scale
            draw.ellipse([cx + 7 * scale - d_r, 3 * scale, cx + 7 * scale + d_r, 3 * scale + d_r * 1.6], fill=(255, 255, 255, 215))
            draw.ellipse([cx + 10 * scale - d_r * 0.8, 4 * scale, cx + 10 * scale + d_r * 0.8, 4 * scale + d_r * 1.3], fill=(255, 255, 255, 195))
        else:
            # Gentle moonlit/sunlit wave shimmer arc at bottom of sea ring
            b_w = [2 * scale, 2 * scale, s - 2 * scale - 1, s - 2 * scale - 1]
            draw.arc(b_w, 45, 135, fill=(255, 255, 255, 180), width=max(1, int(round(0.9 * scale))))

    elif ring_style in ("gel", "glass"):
        # Glossy gel ring OR Liquid Glass specular refractive ring
        _draw_smooth_arc(3, outer_w, outer_pct, outer_col, round_caps=True)
        _draw_smooth_arc(3 + outer_w + 3, inner_w, inner_pct, inner_col, round_caps=True)
        # Luminous specular top glass rim highlight
        b_rim = [2 * scale, 2 * scale, s - 2 * scale - 1, s - 2 * scale - 1]
        rim_rgba = (255, 255, 255, 190) if ring_style == "glass" else (255, 255, 255, 145)
        draw.arc(b_rim, -150, -30, fill=rim_rgba, width=max(1, int(round(1.0 * scale))))
        if ring_style == "gel":
            draw.ellipse([scale, scale, s - scale - 1, s - scale - 1], outline=_hex_rgba(outline_col or "#9EA4B0", 140), width=max(1, scale // 2))

    elif ring_style == "bliss_01":
        # Iconic Retro 2001 Blue/Royale glossy metallic rim + glossy segmented blocks
        rim = outline_col or "#0054E3"
        hi = highlight_col or "#7CC4FF"
        b0 = [scale, scale, s - scale - 1, s - scale - 1]
        draw.ellipse(b0, outline=rim, width=max(2, int(round(1.4 * scale))))
        draw.arc(b0, -150, -30, fill=hi, width=max(1, int(round(0.9 * scale))))
        _draw_segmented_arc(4, outer_w, outer_pct, outer_col, n_seg=14, gap=4.0)
        _draw_segmented_arc(4 + outer_w + 3, max(2, inner_w - 1), inner_pct, inner_col, n_seg=12, gap=5.0)

    elif ring_style == "retro_95":
        lo = outline_col or "#686868"
        hi = highlight_col or "#FFFFFF"
        bw = max(2, int(round(1.3 * scale)))
        b0 = [2 * scale, 2 * scale, s - 2 * scale - 1, s - 2 * scale - 1]
        draw.arc(b0, 135, 315, fill=lo, width=bw)
        draw.arc(b0, -45, 135, fill=hi, width=bw)
        _draw_segmented_arc(5, max(3, outer_w - 1), outer_pct, outer_col, n_seg=14, gap=4.5)
        _draw_segmented_arc(5 + max(3, outer_w - 1) + 3, max(2, inner_w - 1), inner_pct, inner_col, n_seg=12, gap=5.5)

    elif ring_style == "outlined":
        ink = outline_col or "#141414"
        ink_w = max(2, int(round(1.3 * scale)))
        o_inset = 3
        i_inset = 3 + outer_w + 4
        _draw_smooth_arc(o_inset, outer_w, outer_pct, outer_col, round_caps=False)
        _draw_smooth_arc(i_inset, inner_w, inner_pct, inner_col, round_caps=False)
        b_out = [o_inset * scale - ink_w // 2, o_inset * scale - ink_w // 2, s - o_inset * scale + ink_w // 2 - 1, s - o_inset * scale + ink_w // 2 - 1]
        in_e = (o_inset + outer_w) * scale
        b_in = [in_e, in_e, s - in_e - 1, s - in_e - 1]
        draw.ellipse(b_out, outline=ink, width=ink_w)
        draw.ellipse(b_in, outline=ink, width=ink_w)

    else:  # "smooth"
        _draw_smooth_arc(2, outer_w, outer_pct, outer_col, round_caps=True)
        _draw_smooth_arc(2 + outer_w + 3, inner_w, inner_pct, inner_col, round_caps=True)

    small = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def _draw_mini_bar_pil(
    d: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    ratio: float,
    col: str,
    track: str,
    border: str,
    sc: int,
    ui_theme: str,
    highlight: str = "#FFFFFF",
    is_secondary: bool = False,
) -> None:
    if ui_theme == "rpg":
        # Framed pixel HP/MP bar with bright top gleam
        bar_c = "#38BDF8" if is_secondary else "#EF4444"
        d.rectangle([x0, y0, x1, y1], fill=track, outline=border, width=max(1, sc))
        fw = max(sc * 2, int((x1 - x0 - 2 * sc) * ratio))
        fx1 = min(x1 - sc, x0 + sc + fw)
        if fx1 > x0 + sc:
            d.rectangle([x0 + sc, y0 + sc, fx1, y1 - sc], fill=bar_c)
            d.line([(x0 + sc, y0 + sc), (fx1, y0 + sc)], fill=highlight, width=max(1, sc // 2))
        return

    if ui_theme == "runner":
        # Hare & Tortoise clay track with chalk-white lane dashes + checkered finish flag + Hare & Tortoise dots!
        mid_y = (y0 + y1) // 2
        d.rectangle([x0, mid_y, x1, y1], fill=track)
        gx = x0 + 3 * sc
        while gx < x1 - 6 * sc:
            d.line([(gx, mid_y + (y1 - mid_y) // 2), (gx + 3 * sc, mid_y + (y1 - mid_y) // 2)], fill=highlight, width=max(1, sc // 2))
            gx += 7 * sc
        # Finish flag at right end
        fx = x1 - 3 * sc
        d.line([(fx, y0 - 2 * sc), (fx, y1)], fill=border, width=max(1, sc // 2))
        d.rectangle([fx, y0 - 2 * sc, x1, y0 + sc], fill="#FFFFFF")
        d.rectangle([fx, y0 - 2 * sc, fx + sc, y0 - sc], fill="#111111")
        d.rectangle([fx + sc, y0 - sc, x1, y0 + sc], fill="#111111")
        # Trail + steady green Tortoise (pace ~52%) + fast white Rabbit (usage ratio)
        rx = x0 + max(4 * sc, int((x1 - x0 - 7 * sc) * ratio))
        tx = x0 + max(4 * sc, int((x1 - x0 - 7 * sc) * 0.52))
        d.rectangle([x0, mid_y, rx, y1], fill=col)
        # Cute mini green Tortoise shell at pace
        d.ellipse([tx - 2 * sc, mid_y - sc, tx + 2 * sc, y1], fill="#2EA84C", outline="#18341E", width=1)
        # Cute mini white Rabbit with ears at usage
        d.ellipse([rx - 2 * sc, y0 - sc, rx + 2 * sc, mid_y + 2 * sc], fill="#FCF8F4", outline="#342E2C", width=1)
        d.line([(rx - sc, y0 - 3 * sc), (rx - sc, y0)], fill="#FCF8F4", width=max(1, sc // 2))
        d.line([(rx + sc, y0 - 3 * sc), (rx + sc, y0)], fill="#FCF8F4", width=max(1, sc // 2))
        return

    if ui_theme == "thermo":
        # Glass mercury thermometer: round bulb on left + graduated stem
        br = max(3 * sc, int((y1 - y0) * 0.72))
        cy = (y0 + y1) // 2
        bx = x0 + br
        sx0 = bx + br // 2
        d.rounded_rectangle([sx0, y0, x1, y1], radius=max(sc, (y1 - y0) // 2), fill=track, outline=border, width=max(1, sc // 2))
        fw = max(sc * 2, int((x1 - sx0) * ratio))
        d.rounded_rectangle([sx0, y0 + sc // 2, min(x1 - sc // 2, sx0 + fw), y1 - sc // 2], radius=max(1, (y1 - y0) // 3), fill=col)
        # Thermometer ticks
        for frac in (0.25, 0.5, 0.75):
            tx = int(sx0 + (x1 - sx0) * frac)
            d.line([(tx, y0), (tx, y0 + max(2, (y1 - y0) // 2))], fill=border, width=max(1, sc // 2))
        # Round mercury bulb
        d.ellipse([bx - br, cy - br, bx + br, cy + br], fill=col, outline=border, width=max(1, sc // 2))
        d.ellipse([bx - br // 2, cy - br // 2, bx, cy], fill=highlight)
        return

    if ui_theme == "battery":
        # Physical battery body + protruding '+' positive cap on right + glowing cells
        bx1 = x1 - 3 * sc
        d.rounded_rectangle([x0, y0 - sc, bx1, y1 + sc], radius=sc, fill=track, outline=border, width=max(1, sc // 2))
        cy = (y0 + y1) // 2
        d.rectangle([bx1, cy - 2 * sc, x1, cy + 2 * sc], fill=border)
        n_cell = 6
        gap = max(1, sc)
        ix0, ix1 = x0 + 2 * sc, bx1 - 2 * sc
        cw = max(2, (ix1 - ix0 - (n_cell - 1) * gap) // n_cell)
        filled = max(1, int(round(ratio * n_cell)))
        for idx in range(filled):
            cx0 = ix0 + idx * (cw + gap)
            d.rectangle([cx0, y0, min(ix1, cx0 + cw), y1], fill=col)
        return

    if ui_theme == "speedo":
        # Sports-car horizontal RPM tachometer with redline zone (75-100%) + needle
        rx = x0 + int((x1 - x0) * 0.75)
        d.rectangle([x0, y0, rx, y1], fill=track)
        d.rectangle([rx, y0, x1, y1], fill="#7F1D1D")
        fw = max(sc * 2, int((x1 - x0) * ratio))
        fx1 = min(x1, x0 + fw)
        d.rectangle([x0, y0, fx1, y1], fill=col)
        for frac in (0.25, 0.5, 0.75):
            tx = int(x0 + (x1 - x0) * frac)
            d.line([(tx, y0), (tx, y1)], fill="#EF4444" if frac >= 0.75 else border, width=max(1, sc // 2))
        d.rectangle([max(x0, fx1 - sc), y0 - sc, fx1 + sc // 2, y1 + sc], fill=highlight)
        return

    if ui_theme == "bliss_01":
        # Retro 2001 recessed white groove + 3-band 3D glossy cylinder lime-green blocks!
        d.rounded_rectangle([x0, y0 - sc // 2, x1, y1 + sc // 2], radius=2 * sc, fill=track, outline="#7A7A7A", width=max(1, sc // 2))
        ix0, iy0, ix1, iy1 = x0 + 2 * sc, y0, x1 - 2 * sc, y1
        bh = max(3, iy1 - iy0)
        n_blk = 7
        gap = max(2, sc)
        step = max(3, (ix1 - ix0 + gap) // n_blk)
        filled = max(1, int(round(ratio * n_blk)))
        top_c = _blend_hex("#FFFFFF", col, 0.58)
        bot_c = _blend_hex("#000000", col, 0.28)
        for idx in range(filled):
            bx0 = ix0 + idx * step
            bx1 = min(ix1, bx0 + step - gap)
            if bx1 > bx0:
                d.rectangle([bx0, iy0, bx1, iy1], fill=col)
                d.rectangle([bx0, iy0, bx1, iy0 + max(1, bh // 3)], fill=top_c)
                d.rectangle([bx0, iy1 - max(1, bh // 4), bx1, iy1], fill=bot_c)
        return

    if ui_theme == "retro_95":
        d.rectangle([x0, y0, x1, y1], fill=track)
        bw_edge = max(1, sc // 2)
        d.line([(x0, y0), (x1, y0)], fill=border, width=bw_edge)
        d.line([(x0, y0), (x0, y1)], fill=border, width=bw_edge)
        d.line([(x0, y1), (x1, y1)], fill=highlight, width=bw_edge)
        d.line([(x1, y0), (x1, y1)], fill=highlight, width=bw_edge)
        ix0, iy0, ix1, iy1 = x0 + sc, y0 + sc // 2, x1 - sc, y1 - sc // 2
        n_blk = 7
        gap = max(1, sc // 2)
        step = max(2, (ix1 - ix0 + gap) // n_blk)
        filled = max(1, int(round(ratio * n_blk)))
        for idx in range(filled):
            bx0 = ix0 + idx * step
            bx1 = min(ix1, bx0 + step - gap)
            if bx1 > bx0:
                d.rectangle([bx0, iy0, bx1, iy1], fill=col)
        return

    if ui_theme == "brutal":
        d.rectangle([x0, y0, x1, y1], fill=track, outline=border, width=max(2, int(round(0.9 * sc))))
        fw = max(sc * 2, int((x1 - x0 - sc) * ratio))
        d.rectangle([x0 + sc // 2, y0 + sc // 2, min(x1 - sc // 2, x0 + fw), y1 - sc // 2], fill=col)
        return

    if ui_theme == "paper_sky":
        # Storybook summer sky / starry night bar with meadow horizon, cumulus cloud, dotted contrail & mini plane!
        is_dk = _hex_rgba(track)[0] < 70
        d.rounded_rectangle([x0, y0 - sc, x1, y1 + sc], radius=2 * sc, fill=track, outline=border, width=max(1, sc // 2))
        # Soft green Storybook meadow strip along bottom edge
        hill_c = "#233C38" if is_dk else "#7BC47F"
        d.rectangle([x0 + sc, y1 - sc, x1 - sc, y1 + sc], fill=hill_c)
        if is_dk:
            for sx_f, sy_o in ((0.22, 0), (0.55, 1), (0.82, 0)):
                sx = x0 + int((x1 - x0) * sx_f)
                d.ellipse([sx, y0 + sy_o * sc, sx + sc, y0 + (sy_o + 1) * sc], fill="#FDE68A")
        else:
            cx_c = x0 + int((x1 - x0) * 0.78)
            d.ellipse([cx_c - 4 * sc, y0 - sc, cx_c + 2 * sc, y0 + 2 * sc], fill=(255, 255, 255, 215))
            d.ellipse([cx_c, y0, cx_c + 5 * sc, y0 + 2 * sc], fill=(255, 255, 255, 200))
        px = x0 + max(5 * sc, int((x1 - x0 - 7 * sc) * ratio))
        mid_y = (y0 + y1) // 2
        # Soft dotted wind contrail
        gx = x0 + 3 * sc
        while gx < px - 3 * sc:
            d.line([(gx, mid_y), (gx + 2 * sc, mid_y)], fill=(255, 255, 255, 215), width=max(1, sc // 2))
            gx += 5 * sc
        # Origami white paper airplane triangle
        d.polygon([(px + 3 * sc, mid_y - sc), (px - 3 * sc, mid_y - 2 * sc), (px - 2 * sc, mid_y + 2 * sc)], fill="#FFFFFF", outline=border)
        return

    if ui_theme == "paper_sea":
        # Storybook sunlit/moonlit ocean bar with layered turquoise waves, shimmer glints & mini paper boat!
        is_dk = _hex_rgba(track)[0] < 70
        d.rounded_rectangle([x0, y0 - sc, x1, y1 + sc], radius=2 * sc, fill=track, outline=border, width=max(1, sc // 2))
        mid_y = (y0 + y1) // 2
        sea_c = "#215066" if is_dk else "#4BBAC7"
        d.rectangle([x0 + sc, mid_y, x1 - sc, y1 + sc], fill=sea_c)
        # Shimmering sunlight / moonlight glints (윤슬)
        glint_c = (253, 230, 150, 180) if is_dk else (255, 255, 255, 195)
        gx = x0 + 4 * sc
        while gx < x1 - 6 * sc:
            d.line([(gx, mid_y + sc), (gx + 3 * sc, mid_y + sc)], fill=glint_c, width=max(1, sc // 2))
            gx += 8 * sc
        bx = x0 + max(5 * sc, int((x1 - x0 - 7 * sc) * ratio))
        d.rectangle([x0 + sc, mid_y, bx, y1 + sc], fill=col)
        # Tiny white folded paper sailboat
        d.polygon([(bx, y0 - sc), (bx - 2 * sc, mid_y), (bx + 2 * sc, mid_y)], fill="#FFFFFF", outline=border)
        d.polygon([(bx - 3 * sc, mid_y), (bx + 3 * sc, mid_y), (bx + 2 * sc, mid_y + 2 * sc), (bx - 2 * sc, mid_y + 2 * sc)], fill="#F2FAFC", outline=border)
        return

    if ui_theme == "silver_metal":
        # Classic glossy gel capsule with bright white top glass reflection & subtle candy sheen!
        r = max(sc, (y1 - y0) // 2)
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=track, outline=border, width=max(1, sc // 2))
        fw = max(2 * r, int((x1 - x0 - sc) * ratio))
        fx1 = min(x1 - sc // 2, x0 + fw)
        d.rounded_rectangle([x0 + sc // 2, y0 + sc // 2, fx1, y1 - sc // 2], radius=max(1, r - 1), fill=col)
        mid_y = (y0 + y1) // 2
        if fx1 > x0 + 2 * sc:
            d.rounded_rectangle([x0 + sc, y0 + sc // 2, fx1 - sc // 2, mid_y], radius=max(1, r // 2), fill=(255, 255, 255, 130))
        return

    if ui_theme == "liquid_glass":
        # Latest Liquid Glass frosted refractive capsule with crisp top specular glass streak!
        r = max(sc, (y1 - y0) // 2)
        d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=track, outline=border, width=max(1, sc // 2))
        fw = max(2 * r, int((x1 - x0) * ratio))
        fx1 = min(x1, x0 + fw)
        d.rounded_rectangle([x0, y0, fx1, y1], radius=r, fill=col)
        if fx1 > x0 + 3 * sc:
            d.line([(x0 + r, y0 + max(1, sc // 2)), (fx1 - r, y0 + max(1, sc // 2))], fill=(255, 255, 255, 195), width=max(1, sc // 2))
        return

    # Default "modern" smooth pill bar
    r = max(sc, (y1 - y0) // 2)
    d.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=track)
    fw = max(2 * r, int((x1 - x0) * ratio))
    d.rounded_rectangle([x0, y0, min(x1, x0 + fw), y1], radius=r, fill=col)


def render_ui_theme_chip_png(
    ui_theme: str,
    pal: Dict[str, str],
    width: int = 128,
    height: int = 58,
) -> bytes:
    """Fast 2x miniature gallery preview showcasing each theme's unique visual metaphor."""
    sc = 2
    W, H = width * sc, height * sc
    bg_main = pal["bg_main"]
    bg_card = pal["bg_card"]
    track = pal["bg_track"]
    border = pal["border"]
    shadow = pal.get("shadow", border)
    hi = pal.get("bevel_hi", "#FFFFFF")
    tbar = pal.get("titlebar", pal["accent_agy"])
    txt_pri = pal["text_pri"]
    c1 = pal["accent_agy"]
    c2 = pal["accent_claude"]

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    outer_r = 6 * sc if ui_theme in ("modern", "thermo", "battery", "bliss_01") else 0
    outer_w = int(round(1.5 * sc)) if ui_theme in ("brutal", "rpg") else sc
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=outer_r, fill=bg_main, outline=border, width=outer_w)

    if ui_theme == "rpg":
        # Double-lined retro RPG dialog border + two pixel heroes + HP & MP bars!
        d.rectangle([2 * sc, 2 * sc, W - 3 * sc, H - 3 * sc], outline=pal.get("bevel_hi", border), width=sc)
        for idx, (prov, y0, col, r_hp, r_mp) in enumerate((("antigravity", 7, c1, 0.78, 0.55), ("claude", 31, c2, 0.42, 0.85))):
            d.rectangle([6 * sc, y0 * sc, W - 7 * sc, (y0 + 20) * sc], fill=bg_card, outline=border, width=sc)
            hero = Image.open(io.BytesIO(render_rpg_hero_png(prov, "ok" if idx == 0 else "warn", col, bg_card, size=14 * sc))).convert("RGBA")
            img.alpha_composite(hero, (9 * sc, (y0 + 3) * sc))
            _draw_mini_bar_pil(d, 27 * sc, (y0 + 4) * sc, W - 11 * sc, (y0 + 10) * sc, r_hp, col, track, border, sc, "rpg", hi, is_secondary=False)
            _draw_mini_bar_pil(d, 27 * sc, (y0 + 12) * sc, W - 11 * sc, (y0 + 17) * sc, r_mp, col, track, border, sc, "rpg", hi, is_secondary=True)
        small = img.resize((width, height), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, format="PNG")
        return buf.getvalue()

    if ui_theme == "paper_sky":
        # Storybook Watercolor Summer Sky & Rolling Green Meadow + Gliding Origami Paper Airplanes (Dark: Starry Night!)
        is_dk = _hex_rgba(bg_main)[0] < 80
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=6 * sc, fill=bg_main, outline=border, width=sc)
        tb_img = Image.open(io.BytesIO(render_scenic_titlebar_png(W - 2 * sc, 12 * sc, kind="sky", dark=is_dk))).convert("RGBA")
        img.paste(tb_img, (sc, sc))
        emb = Image.open(io.BytesIO(render_scenic_emblem_png(None, kind="sky", dark=is_dk, size=8 * sc))).convert("RGBA")
        img.alpha_composite(emb, (4 * sc, 3 * sc))
        d.rounded_rectangle([15 * sc, 5 * sc, 48 * sc, 8 * sc], radius=sc, fill=txt_pri)
        # Soft Storybook rolling green hill along bottom of gallery chip!
        hill_c = "#1E3632" if is_dk else "#7DC482"
        hill_hi = "#284A43" if is_dk else "#9ED99B"
        d.ellipse([-12 * sc, H - 11 * sc, W * 0.65, H + 12 * sc], fill=hill_hi)
        d.ellipse([W * 0.32, H - 10 * sc, W + 16 * sc, H + 13 * sc], fill=hill_c)
        for idx, (y0, col, r_val) in enumerate(((15, c1, 0.72), (36, c2, 0.44))):
            cx0, cy0, cx1, cy1 = 6 * sc, y0 * sc, W - 7 * sc, (y0 + 18) * sc
            d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=4 * sc, fill=bg_card, outline=border, width=max(1, sc // 2))
            tx0, ty0, tx1, ty1 = cx0 + 5 * sc, cy0 + 3 * sc, cx1 - 5 * sc, cy1 - 3 * sc
            d.rounded_rectangle([tx0, ty0, tx1, ty1], radius=2 * sc, fill=track)
            d.rectangle([tx0, ty1 - 3 * sc, tx1, ty1], fill=hill_c)
            if is_dk:
                for fx_s, fy_s in ((0.2, 0.28), (0.58, 0.22), (0.85, 0.42)):
                    sx = tx0 + int((tx1 - tx0) * fx_s)
                    sy = ty0 + int((ty1 - ty0) * fy_s)
                    d.ellipse([sx, sy, sx + sc, sy + sc], fill="#FDE68A")
            else:
                cx_c = tx0 + int((tx1 - tx0) * (0.82 if idx == 0 else 0.72))
                d.ellipse([cx_c - 6 * sc, ty0 + sc, cx_c + 2 * sc, ty0 + 6 * sc], fill=(255, 255, 255, 235))
                d.ellipse([cx_c - sc, ty0 + 2 * sc, cx_c + 6 * sc, ty0 + 7 * sc], fill=(255, 255, 255, 225))
            px = tx0 + int((tx1 - tx0 - 12 * sc) * r_val)
            mid_y = (ty0 + ty1) // 2
            gx = tx0 + 3 * sc
            while gx < px:
                d.line([(gx, mid_y), (gx + 3 * sc, mid_y)], fill=(255, 255, 255, 225), width=1)
                gx += 6 * sc
            plane = Image.open(io.BytesIO(render_paper_plane_png(col, "ok", dark=is_dk, size=10 * sc))).convert("RGBA")
            img.alpha_composite(plane, (px, ty0 + sc))
        small = img.resize((width, height), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, format="PNG")
        return buf.getvalue()

    if ui_theme == "paper_sea":
        # Storybook Watercolor Watercolor Sea & Sparkling Ripples + Origami Paper Sailboats (Dark: Moonlit Sea!)
        is_dk = _hex_rgba(bg_main)[0] < 80
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=6 * sc, fill=bg_main, outline=border, width=sc)
        tb_img = Image.open(io.BytesIO(render_scenic_titlebar_png(W - 2 * sc, 12 * sc, kind="sea", dark=is_dk))).convert("RGBA")
        img.paste(tb_img, (sc, sc))
        emb = Image.open(io.BytesIO(render_scenic_emblem_png(None, kind="sea", dark=is_dk, size=8 * sc))).convert("RGBA")
        img.alpha_composite(emb, (4 * sc, 3 * sc))
        d.rounded_rectangle([15 * sc, 5 * sc, 48 * sc, 8 * sc], radius=sc, fill=txt_pri)
        # Gentle ocean horizon band at bottom of chip
        sea_band = "#183B4E" if is_dk else "#7FD0D9"
        d.rectangle([sc, H - 8 * sc, W - sc - 1, H - sc - 1], fill=sea_band)
        for idx, (y0, col, r_val) in enumerate(((15, c1, 0.66), (36, c2, 0.40))):
            cx0, cy0, cx1, cy1 = 6 * sc, y0 * sc, W - 7 * sc, (y0 + 18) * sc
            d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=4 * sc, fill=bg_card, outline=border, width=max(1, sc // 2))
            tx0, ty0, tx1, ty1 = cx0 + 5 * sc, cy0 + 3 * sc, cx1 - 5 * sc, cy1 - 3 * sc
            d.rounded_rectangle([tx0, ty0, tx1, ty1], radius=2 * sc, fill=track)
            mid_y = (ty0 + ty1) // 2 + sc
            sea_c = "#1F4F66" if is_dk else "#55C0CC"
            d.rectangle([tx0, mid_y, tx1, ty1], fill=sea_c)
            glint_c = (253, 230, 150, 200) if is_dk else (255, 255, 255, 215)
            gx = tx0 + 3 * sc
            while gx < tx1 - 6 * sc:
                d.line([(gx, mid_y + 2 * sc), (gx + 4 * sc, mid_y + 2 * sc)], fill=glint_c, width=1)
                gx += 9 * sc
            bx = tx0 + int((tx1 - tx0 - 12 * sc) * r_val)
            boat = Image.open(io.BytesIO(render_paper_boat_png(col, "ok", dark=is_dk, size=10 * sc))).convert("RGBA")
            img.alpha_composite(boat, (bx, ty0 + sc))
        small = img.resize((width, height), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, format="PNG")
        return buf.getvalue()

    if ui_theme == "runner":
        # Hare & Tortoise gallery showcase: real pixel-art Rabbit & Tortoise racing on clay tracks!
        for idx, (y0, col, r_hare, r_tort) in enumerate(((7, c1, 0.74, 0.48), (31, c2, 0.36, 0.56))):
            cx0, cy0, cx1, cy1 = 6 * sc, y0 * sc, W - 7 * sc, (y0 + 20) * sc
            d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=3 * sc, fill=bg_card, outline=border, width=max(1, sc // 2))
            tx0, ty0, tx1, ty1 = cx0 + 6 * sc, cy0 + 11 * sc, cx1 - 6 * sc, cy1 - 3 * sc
            d.rectangle([tx0, ty0, tx1, ty1], fill=track)
            gx = tx0 + 3 * sc
            while gx < tx1 - 6 * sc:
                d.line([(gx, (ty0 + ty1) // 2), (gx + 3 * sc, (ty0 + ty1) // 2)], fill=hi, width=1)
                gx += 7 * sc
            fx = tx1 - 4 * sc
            d.line([(fx, cy0 + 3 * sc), (fx, ty1)], fill=border, width=1)
            d.rectangle([fx, cy0 + 3 * sc, tx1, cy0 + 8 * sc], fill="#FFFFFF")
            d.rectangle([fx, cy0 + 3 * sc, fx + 2 * sc, cy0 + 5 * sc], fill="#111111")
            d.rectangle([fx + 2 * sc, cy0 + 5 * sc, tx1, cy0 + 8 * sc], fill="#111111")
            hx = tx0 + int((tx1 - tx0 - 12 * sc) * r_hare)
            ttx = tx0 + int((tx1 - tx0 - 12 * sc) * r_tort)
            d.rectangle([tx0, ty0, hx + 5 * sc, ty1], fill=col)
            tort = Image.open(io.BytesIO(render_tortoise_sprite_png(size=10 * sc))).convert("RGBA")
            hare = Image.open(io.BytesIO(render_hare_sprite_png(col, "warn" if r_hare > r_tort + 0.15 else "ok", size=10 * sc))).convert("RGBA")
            img.alpha_composite(tort, (ttx, cy0 + 7 * sc))
            img.alpha_composite(hare, (hx, cy0 + 3 * sc))
        small = img.resize((width, height), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, format="PNG")
        return buf.getvalue()

    if ui_theme == "silver_metal":
        # Classic Brushed Metal brushed aluminum titlebar + 3D glossy traffic-light jewels + glossy gel capsule bars!
        is_sm_dark = _hex_rgba(bg_main)[0] < 100
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=6 * sc, fill=bg_main, outline=border, width=sc)
        tb_img = Image.open(io.BytesIO(render_silver_metal_titlebar_png(W - 2 * sc, 13 * sc, dark=is_sm_dark))).convert("RGBA")
        img.paste(tb_img, (sc, sc))
        tl = Image.open(io.BytesIO(render_traffic_dots_png(None, style="gel", dark=is_sm_dark, width=22 * sc, height=9 * sc))).convert("RGBA")
        img.alpha_composite(tl, (4 * sc, 3 * sc))
        d.rectangle([32 * sc, 6 * sc, 64 * sc, 9 * sc], fill=txt_pri)
        cards = [(18, 34, c1, 0.74), (38, 54, c2, 0.48)]
    elif ui_theme == "liquid_glass":
        # Modern Liquid Glass: luminous specular rim + frosted crystal droplets + refractive glass pills!
        is_sm_dark = _hex_rgba(bg_main)[0] < 100
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=8 * sc, fill=bg_main, outline=hi, width=sc)
        d.line([(8 * sc, sc), (W - 9 * sc, sc)], fill=(255, 255, 255, 210 if not is_sm_dark else 135), width=sc)
        tl = Image.open(io.BytesIO(render_traffic_dots_png(bg_main, style="glass", dark=is_sm_dark, width=22 * sc, height=9 * sc))).convert("RGBA")
        img.alpha_composite(tl, (5 * sc, 3 * sc))
        d.rounded_rectangle([32 * sc, 6 * sc, 62 * sc, 9 * sc], radius=sc, fill=txt_pri)
        cards = [(17, 34, c1, 0.72), (38, 54, c2, 0.50)]
    elif ui_theme == "bliss_01":
        # Retro 2001 Glossy Blue (Light) / Midnight Noir (Dark): 3px blue/noir outer frame + glossy gradient titlebar + 4-color Retro 2001 4-pane badge + 3D square buttons + glossy green Retro 2001 progress blocks!
        is_r01_dark = _hex_rgba(bg_main)[0] < 100
        frame_c = pal.get("frame_border", tbar)
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=4 * sc, fill=bg_main, outline=frame_c, width=2 * sc)
        tb_h = 13 * sc
        tb_img = Image.open(io.BytesIO(render_retro01_titlebar_png(W - 4 * sc, tb_h, dark=is_r01_dark))).convert("RGBA")
        img.paste(tb_img, (2 * sc, 2 * sc))
        # Tiny 4-color Retro 2001 4-pane badge on titlebar left!
        flag = Image.open(io.BytesIO(render_retro01_badge_png(tbar, size=8 * sc))).convert("RGBA")
        img.alpha_composite(flag, (5 * sc, 4 * sc))
        d.rectangle([16 * sc, 7 * sc, 54 * sc, 10 * sc], fill="#FFFFFF")
        # Glossy blue square button + iconic glossy red X button!
        d.rounded_rectangle([W - 22 * sc, 4 * sc, W - 14 * sc, 12 * sc], radius=sc, fill="#2A74EB" if not is_r01_dark else "#354666", outline="#FFFFFF", width=1)
        d.rounded_rectangle([W - 12 * sc, 4 * sc, W - 4 * sc, 12 * sc], radius=sc, fill=pal.get("retro_close", "#E0432D"), outline="#FFFFFF", width=1)
        r01_bar_c = pal.get("retro_bar", "#2ED12E")
        cards = [(18, 34, r01_bar_c, 0.72), (38, 54, r01_bar_c if not is_r01_dark else c2, 0.48)]
    elif ui_theme == "retro_95":
        d.line([(0, 0), (W - 1, 0)], fill=hi, width=sc)
        d.line([(0, 0), (0, H - 1)], fill=hi, width=sc)
        d.line([(0, H - 1), (W - 1, H - 1)], fill=shadow, width=sc)
        d.line([(W - 1, 0), (W - 1, H - 1)], fill=shadow, width=sc)
        d.rectangle([3 * sc, 3 * sc, W - 4 * sc, 12 * sc], fill=tbar)
        d.rectangle([6 * sc, 6 * sc, 42 * sc, 9 * sc], fill="#FFFFFF")
        cards = [(16, 33, c1, 0.72), (37, 53, c2, 0.48)]
    else:
        cards = [(7, 27, c1, 0.70), (31, 51, c2, 0.46 if ui_theme != "thermo" else 0.88)]

    card_r = 6 * sc if ui_theme in ("liquid_glass", "silver_metal") else (4 * sc if ui_theme in ("modern", "thermo", "battery", "bliss_01") else 0)
    card_bw = int(round(1.5 * sc)) if ui_theme == "brutal" else max(1, sc // 2)
    sh = 2 * sc if ui_theme == "brutal" else 0

    for idx, (y0, y1, col, r_val) in enumerate(cards):
        cx0 = 7 * sc
        cy0 = y0 * sc
        cx1 = W - (7 + (2 if sh else 0)) * sc
        cy1 = (y1 - (1 if sh else 0)) * sc
        if sh:
            d.rectangle([cx0 + sh, cy0 + sh, cx1 + sh, cy1 + sh], fill=shadow)
        d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=card_r, fill=bg_card, outline=border, width=card_bw)
        if ui_theme == "liquid_glass":
            d.line([(cx0 + 4 * sc, cy0), (cx1 - 4 * sc, cy0)], fill=hi, width=1)
        if ui_theme == "retro_95":
            d.line([(cx0, cy0), (cx1, cy0)], fill=hi, width=1)
            d.line([(cx0, cy0), (cx0, cy1)], fill=hi, width=1)
            d.line([(cx0, cy1), (cx1, cy1)], fill=shadow, width=1)
            d.line([(cx1, cy0), (cx1, cy1)], fill=shadow, width=1)

        iy = (cy0 + cy1) // 2
        bar_col = "#EF4444" if (ui_theme == "thermo" and r_val > 0.8) else col
        d.rectangle([cx0 + 5 * sc, iy - 2 * sc, cx0 + 18 * sc, iy + 2 * sc], fill=txt_pri)
        bh = 6 * sc if ui_theme in ("brutal", "retro_95", "bliss_01", "battery", "thermo", "speedo") else 5 * sc
        _draw_mini_bar_pil(d, cx0 + 23 * sc, iy - bh // 2, cx1 - 6 * sc, iy + bh // 2, r_val, bar_col, track, border, sc, ui_theme, hi)

    small = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def render_style_preview_png(
    style: str,
    pal: Dict[str, str],
    width: int = 148,
    height: int = 74,
    primary_5h: bool = False,
    ui_theme: str = "modern",
) -> bytes:
    """Fast 2x miniature mockup of Dual / Slim / Ring styled for any of the 9 UI themes."""
    sc = 2
    W, H = width * sc, height * sc
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    bg_main = pal["bg_main"]
    bg_card = pal["bg_card"]
    track = pal["bg_track"]
    border = pal["border"]
    shadow = pal.get("shadow", border)
    hi = pal.get("bevel_hi", "#FFFFFF")
    tbar = pal.get("titlebar", pal["accent_agy"])
    txt_pri = pal["text_pri"]
    txt_mut = pal["text_muted"]
    c_agy = pal["accent_agy"]
    c_agy_5h = pal.get("accent_agy_5h", c_agy)
    c_arg = pal["accent_argon"]
    c_cld = pal["accent_claude"]
    c_cld_5h = pal.get("accent_claude_5h", c_cld)
    c_fbl = pal["accent_fable"]

    agy_top, agy_bot = (c_agy_5h, c_agy) if primary_5h else (c_agy, c_agy_5h)
    cld_top, cld_bot = (c_cld_5h, c_cld) if primary_5h else (c_cld, c_cld_5h)
    if ui_theme == "bliss_01" and _hex_rgba(bg_main)[0] > 120:
        r01_g = pal.get("retro_bar", "#2ED12E")
        agy_top = agy_bot = cld_top = cld_bot = r01_g

    outer_r = 7 * sc if ui_theme in ("modern", "liquid_glass", "silver_metal", "paper_sky", "paper_sea", "thermo", "battery", "bliss_01") else 0
    outer_w = int(round(1.5 * sc)) if ui_theme in ("brutal", "rpg") else sc
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=outer_r, fill=bg_main, outline=border, width=outer_w)

    if ui_theme == "silver_metal":
        is_sm_dark = _hex_rgba(bg_main)[0] < 100
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=6 * sc, fill=bg_main, outline=border, width=sc)
        tb_img = Image.open(io.BytesIO(render_silver_metal_titlebar_png(W - 2 * sc, 12 * sc, dark=is_sm_dark))).convert("RGBA")
        img.paste(tb_img, (sc, sc))
        tl = Image.open(io.BytesIO(render_traffic_dots_png(None, style="gel", dark=is_sm_dark, width=22 * sc, height=8 * sc))).convert("RGBA")
        img.alpha_composite(tl, (4 * sc, 3 * sc))
        d.rounded_rectangle([32 * sc, 6 * sc, 66 * sc, 9 * sc], radius=sc, fill=txt_pri)
    elif ui_theme == "liquid_glass":
        is_sm_dark = _hex_rgba(bg_main)[0] < 100
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=8 * sc, fill=bg_main, outline=hi, width=sc)
        d.line([(8 * sc, sc), (W - 9 * sc, sc)], fill=(255, 255, 255, 210 if not is_sm_dark else 135), width=sc)
        tl = Image.open(io.BytesIO(render_traffic_dots_png(bg_main, style="glass", dark=is_sm_dark, width=22 * sc, height=8 * sc))).convert("RGBA")
        img.alpha_composite(tl, (5 * sc, 3 * sc))
        d.rounded_rectangle([32 * sc, 6 * sc, 66 * sc, 9 * sc], radius=sc, fill=txt_pri)
    elif ui_theme == "bliss_01":
        is_r01_dark = _hex_rgba(bg_main)[0] < 100
        frame_c = pal.get("frame_border", tbar)
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=5 * sc, fill=bg_main, outline=frame_c, width=2 * sc)
        tb_img = Image.open(io.BytesIO(render_retro01_titlebar_png(W - 4 * sc, 12 * sc, dark=is_r01_dark))).convert("RGBA")
        img.paste(tb_img, (2 * sc, 2 * sc))
        flag = Image.open(io.BytesIO(render_retro01_badge_png(tbar, size=8 * sc))).convert("RGBA")
        img.alpha_composite(flag, (5 * sc, 4 * sc))
        d.rectangle([16 * sc, 6 * sc, 52 * sc, 9 * sc], fill="#FFFFFF")
        d.rounded_rectangle([W - 22 * sc, 4 * sc, W - 14 * sc, 11 * sc], radius=sc, fill="#2A74EB" if not is_r01_dark else "#354666", outline="#FFFFFF", width=1)
        d.rounded_rectangle([W - 12 * sc, 4 * sc, W - 4 * sc, 11 * sc], radius=sc, fill=pal.get("retro_close", "#E0432D"), outline="#FFFFFF", width=1)
    elif ui_theme in ("paper_sky", "paper_sea"):
        is_sc_dark = _hex_rgba(bg_main)[0] < 80
        sc_kind = "sky" if ui_theme == "paper_sky" else "sea"
        tb_img = Image.open(io.BytesIO(render_scenic_titlebar_png(W - 2 * sc, 12 * sc, kind=sc_kind, dark=is_sc_dark))).convert("RGBA")
        img.paste(tb_img, (sc, sc))
        emb = Image.open(io.BytesIO(render_scenic_emblem_png(None, kind=sc_kind, dark=is_sc_dark, size=8 * sc))).convert("RGBA")
        img.alpha_composite(emb, (4 * sc, 3 * sc))
        d.rounded_rectangle([15 * sc, 6 * sc, 54 * sc, 9 * sc], radius=sc, fill=txt_pri)
    elif ui_theme == "retro_95":
        d.rectangle([3 * sc, 3 * sc, W - 4 * sc, 11 * sc], fill=tbar)
        d.rectangle([8 * sc, 6 * sc, 48 * sc, 9 * sc], fill="#FFFFFF")
        for idx in range(3):
            bx = W - (10 + idx * 8) * sc
            d.rectangle([bx - 2 * sc, 5 * sc, bx + 2 * sc, 9 * sc], fill="#D4D0C8")
    else:
        d.rounded_rectangle([8 * sc, 6 * sc, 48 * sc, 9 * sc], radius=sc if ui_theme == "modern" else 0, fill=txt_mut)
        for idx in range(3):
            bx = W - (10 + idx * 8) * sc
            d.ellipse([bx - 2 * sc, 6 * sc, bx + 2 * sc, 10 * sc], fill=txt_mut)

    def _draw_card_box(x0: int, y0: int, x1: int, y1: int) -> None:
        card_r = 6 * sc if ui_theme in ("liquid_glass", "silver_metal", "paper_sky", "paper_sea") else (5 * sc if ui_theme in ("modern", "thermo", "battery", "bliss_01") else 0)
        card_b = int(round(1.5 * sc)) if ui_theme in ("brutal", "rpg") else max(1, sc // 2)
        if ui_theme == "brutal":
            sh = 2 * sc
            d.rectangle([x0 + sh, y0 + sh, x1 + sh, y1 + sh], fill=shadow)
        d.rounded_rectangle([x0, y0, x1, y1], radius=card_r, fill=bg_card, outline=border, width=card_b)
        if ui_theme == "liquid_glass":
            d.line([(x0 + 4 * sc, y0), (x1 - 4 * sc, y0)], fill=hi, width=1)
        if ui_theme == "retro_95":
            d.line([(x0, y0), (x1, y0)], fill=hi, width=1)
            d.line([(x0, y0), (x0, y1)], fill=hi, width=1)
            d.line([(x0, y1), (x1, y1)], fill=shadow, width=1)
            d.line([(x1, y0), (x1, y1)], fill=shadow, width=1)

    rad_lbl = sc if ui_theme == "modern" else 0

    if style == "dual":
        cards = [
            (14, 38, "antigravity", c_agy, agy_top, agy_bot, c_arg, 0.25 if primary_5h else 0.48, 0.48 if primary_5h else 0.25),
            (42, 66, "claude", c_cld, cld_top, cld_bot, c_fbl, 0.62 if primary_5h else 0.82, 0.82 if primary_5h else 0.62),
        ]
        for y0, y1, prov, c_dot, c1, c2, cmod, r1, r2 in cards:
            pad_r = 9 * sc if ui_theme == "brutal" else 7 * sc
            _draw_card_box(7 * sc, y0 * sc, W - pad_r, (y1 - (1 if ui_theme == "brutal" else 0)) * sc)
            if ui_theme == "rpg":
                hero = Image.open(io.BytesIO(render_rpg_hero_png(prov, "ok" if r1 < 0.7 else "warn", c_dot, bg_card, size=14 * sc))).convert("RGBA")
                img.alpha_composite(hero, (11 * sc, (y0 + 5) * sc))
            else:
                d.ellipse([12 * sc, (y0 + 5) * sc, 16 * sc, (y0 + 9) * sc], fill=c_dot)
                d.rounded_rectangle([19 * sc, (y0 + 5) * sc, 31 * sc, (y0 + 9) * sc], radius=rad_lbl, fill=txt_pri)
            _draw_mini_bar_pil(d, 35 * sc, (y0 + 5) * sc, 96 * sc, (y0 + 10) * sc, r1, c1, track, border, sc, ui_theme, hi, is_secondary=False)
            d.rounded_rectangle([101 * sc, (y0 + 5) * sc, 114 * sc, (y0 + 9) * sc], radius=rad_lbl, fill=txt_pri)
            d.rounded_rectangle([119 * sc, (y0 + 5) * sc, 134 * sc, (y0 + 9) * sc], radius=rad_lbl, fill=txt_mut if primary_5h else cmod)
            if ui_theme != "rpg":
                d.rounded_rectangle([19 * sc, (y0 + 15) * sc, 28 * sc, (y0 + 18) * sc], radius=rad_lbl, fill=txt_mut)
            _draw_mini_bar_pil(d, 35 * sc, (y0 + 15) * sc, 96 * sc, (y0 + 18) * sc, r2, c2, track, border, sc, ui_theme, hi, is_secondary=True)
            d.rounded_rectangle([102 * sc, (y0 + 15) * sc, 114 * sc, (y0 + 18) * sc], radius=rad_lbl, fill=txt_mut)
            d.rounded_rectangle([120 * sc, (y0 + 15) * sc, 134 * sc, (y0 + 18) * sc], radius=rad_lbl, fill=txt_mut)

    elif style == "slim":
        cards = [
            (20, 38, "antigravity", c_agy, agy_top, agy_bot, 0.28 if primary_5h else 0.50, 0.50 if primary_5h else 0.28),
            (43, 61, "claude", c_cld, cld_top, cld_bot, 0.62 if primary_5h else 0.78, 0.78 if primary_5h else 0.62),
        ]
        for y0, y1, prov, c_dot, c1, c2, r1, r2 in cards:
            pad_r = 9 * sc if ui_theme == "brutal" else 7 * sc
            _draw_card_box(7 * sc, y0 * sc, W - pad_r, (y1 - (1 if ui_theme == "brutal" else 0)) * sc)
            if ui_theme == "rpg":
                hero = Image.open(io.BytesIO(render_rpg_hero_png(prov, "ok", c_dot, bg_card, size=12 * sc))).convert("RGBA")
                img.alpha_composite(hero, (11 * sc, (y0 + 3) * sc))
            else:
                d.ellipse([12 * sc, (y0 + 7) * sc, 16 * sc, (y0 + 11) * sc], fill=c_dot)
                d.rounded_rectangle([19 * sc, (y0 + 7) * sc, 31 * sc, (y0 + 11) * sc], radius=rad_lbl, fill=txt_pri)
            _draw_mini_bar_pil(d, 35 * sc, (y0 + 5) * sc, 96 * sc, (y0 + 9) * sc, r1, c1, track, border, sc, ui_theme, hi, is_secondary=False)
            _draw_mini_bar_pil(d, 35 * sc, (y0 + 11) * sc, 96 * sc, (y0 + 14) * sc, r2, c2, track, border, sc, ui_theme, hi, is_secondary=True)
            d.rounded_rectangle([101 * sc, (y0 + 7) * sc, 114 * sc, (y0 + 11) * sc], radius=rad_lbl, fill=txt_pri)
            d.rounded_rectangle([118 * sc, (y0 + 6) * sc, 134 * sc, (y0 + 12) * sc], radius=2 * sc if ui_theme == "modern" else 0, fill=c2)

    else:  # "ring" — fast direct draw (zero nested PIL sub-renders!)
        mid = W // 2
        card_specs = [
            (7 * sc, mid - 2 * sc, c_agy, agy_top, agy_bot, 28.0 if primary_5h else 52.0, 52.0 if primary_5h else 28.0),
            (mid + 2 * sc, W - 7 * sc, c_cld, cld_top, cld_bot, 68.0 if primary_5h else 82.0, 82.0 if primary_5h else 68.0),
        ]
        for x0, x1, c_name, c1, c2, p1, p2 in card_specs:
            rx1 = x1 - (2 * sc if ui_theme == "brutal" else 0)
            _draw_card_box(x0, 14 * sc, rx1, (65 if ui_theme == "brutal" else 67) * sc)
            cx = (x0 + rx1) // 2
            cy = 34 * sc
            r1 = 14 * sc
            r2 = 9 * sc
            b1 = [cx - r1, cy - r1, cx + r1, cy + r1]
            b2 = [cx - r2, cy - r2, cx + r2, cy + r2]
            if ui_theme in ("speedo", "thermo"):
                d.arc(b1, 135, 340, fill=track, width=3 * sc)
                d.arc(b1, 340, 405, fill="#991B1B", width=3 * sc)
                d.arc(b1, 135, 135 + 270 * (p1 / 100.0), fill=c1, width=3 * sc)
                d.arc(b2, 135, 405, fill=track, width=2 * sc)
                d.arc(b2, 135, 135 + 270 * (p2 / 100.0), fill=c2, width=2 * sc)
            else:
                if ui_theme == "brutal":
                    d.ellipse([cx - r1 - sc, cy - r1 - sc, cx + r1 + sc, cy + r1 + sc], outline=border, width=sc)
                d.arc(b1, 0, 360, fill=track, width=3 * sc)
                d.arc(b1, -90, -90 + 360 * (p1 / 100.0), fill="#EF4444" if ui_theme == "rpg" else c1, width=3 * sc)
                d.arc(b2, 0, 360, fill=track, width=2 * sc)
                d.arc(b2, -90, -90 + 360 * (p2 / 100.0), fill="#38BDF8" if ui_theme == "rpg" else c2, width=2 * sc)
                if ui_theme == "runner":
                    d.rectangle([cx - sc, cy - r1 - sc, cx + sc, cy - r1 + 3 * sc], fill="#FFFFFF")
            d.rounded_rectangle([cx - 5 * sc, cy - 2 * sc, cx + 5 * sc, cy + 2 * sc], radius=rad_lbl, fill=txt_pri)
            d.rounded_rectangle([cx - 10 * sc, 53 * sc, cx + 10 * sc, 56 * sc], radius=rad_lbl, fill=c_name)
            d.rounded_rectangle([cx - 18 * sc, 59 * sc, cx + 18 * sc, 62 * sc], radius=rad_lbl, fill=txt_mut)

    small = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def render_toolbar_icon_png(
    kind: str,
    fg_hex: str,
    bg_hex: str,
    pill_bg_hex: Optional[str] = None,
    pill_border_hex: Optional[str] = None,
    width: int = 22,
    height: int = 18,
    ui_theme: str = "modern",
) -> bytes:
    """Render a crisp 4x supersampled cross-platform monochrome vector toolbar icon as PNG.

    Eliminates Windows vs macOS Apple Color Emoji discrepancies (especially 📌 ignoring fg color).
    Supported kinds: 'refresh', 'refresh_busy', 'expand', 'collapse', 'settings',
    'pin_on', 'pin_off', 'hide'.
    """
    sc = 4
    W, H = width * sc, height * sc
    base_rgba = _hex_rgba(bg_hex, 255)
    img = Image.new("RGBA", (W, H), base_rgba)
    d = ImageDraw.Draw(img, "RGBA")

    if pill_bg_hex:
        if ui_theme == "bliss_01":
            # Authentic 3D glossy Retro 2001 rounded-square titlebar button with white rim & top shine!
            x0, y0, x1, y1 = 1 * sc, 1 * sc, W - 1 * sc - 1, H - 1 * sc - 1
            pill_r = 3 * sc
            top_g = _blend_hex("#FFFFFF", pill_bg_hex, 0.52)
            bot_g = _blend_hex("#000000", pill_bg_hex, 0.28)
            d.rounded_rectangle([x0, y0, x1, y1], radius=pill_r, fill=_hex_rgba(pill_bg_hex, 255))
            # Top glossy glass reflection band
            d.rounded_rectangle([x0 + sc, y0 + sc, x1 - sc, (y0 + y1) // 2], radius=2 * sc, fill=top_g)
            # Subtle deep bottom rim shade
            d.rectangle([x0 + 2 * sc, y1 - 2 * sc, x1 - 2 * sc, y1 - sc], fill=bot_g)
            # Crisp signature Retro 2001 white button border!
            d.rounded_rectangle([x0, y0, x1, y1], radius=pill_r, outline=(255, 255, 255, 235), width=max(2, int(round(0.95 * sc))))
        else:
            if ui_theme in ("brutal", "rpg"):
                pill_r = 0
                outline = _hex_rgba(pill_border_hex, 255) if pill_border_hex else None
                pill_w = max(3, int(round(1.3 * sc)))
            elif ui_theme in ("retro_95", "speedo"):
                pill_r = 0 if ui_theme == "retro_95" else 1 * sc
                outline = _hex_rgba(pill_border_hex, 200) if pill_border_hex else None
                pill_w = max(2, int(round(0.9 * sc)))
            else:
                pill_r = 4 * sc
                outline = _hex_rgba(pill_border_hex, 125) if pill_border_hex else None
                pill_w = max(2, int(round(0.8 * sc)))
            d.rounded_rectangle(
                [1 * sc, 1 * sc, W - 1 * sc - 1, H - 1 * sc - 1],
                radius=pill_r,
                fill=_hex_rgba(pill_bg_hex, 255),
                outline=outline,
                width=pill_w if outline else 0,
            )

    fg = _hex_rgba(fg_hex, 255)
    cx, cy = W / 2.0, H / 2.0
    sw = max(2, int(round(1.55 * sc)))

    if kind == "refresh":
        rad = 4.6 * sc
        box = [cx - rad, cy - rad, cx + rad, cy + rad]
        # Clockwise arc from 4 o'clock around bottom/left/top to 1:30 o'clock (315 deg)
        d.arc(box, start=30, end=318, fill=fg, width=sw)
        # Arrowhead at 315 deg pointing clockwise (tangent = (+0.707, +0.707))
        ang = math.radians(315)
        tx = cx + rad * math.cos(ang)
        ty = cy + rad * math.sin(ang)
        tan_x, tan_y = 0.707, 0.707
        nrm_x, nrm_y = 0.707, -0.707
        tip = (tx + tan_x * 1.6 * sc, ty + tan_y * 1.6 * sc)
        b1 = (tx - tan_x * 1.9 * sc + nrm_x * 2.1 * sc, ty - tan_y * 1.9 * sc + nrm_y * 2.1 * sc)
        b2 = (tx - tan_x * 1.9 * sc - nrm_x * 2.1 * sc, ty - tan_y * 1.9 * sc - nrm_y * 2.1 * sc)
        d.polygon([tip, b1, b2], fill=fg)

    elif kind == "refresh_busy":
        r = 1.2 * sc
        for dx in (-4.2 * sc, 0.0, 4.2 * sc):
            d.ellipse([cx + dx - r, cy - r, cx + dx + r, cy + r], fill=fg)

    elif kind in ("expand", "collapse"):
        s = 3.6 * sc
        h = 2.0 * sc
        if kind == "expand":
            pts = [(cx - s, cy - h), (cx, cy + h), (cx + s, cy - h)]
        else:
            pts = [(cx - s, cy + h), (cx, cy - h), (cx + s, cy + h)]
        d.line(pts, fill=fg, width=sw, joint="curve")
        cap = sw / 2.0
        for px, py in pts:
            d.ellipse([px - cap, py - cap, px + cap, py + cap], fill=fg)

    elif kind == "settings":
        # 8-tooth crisp geometric gear
        outer_r = 5.3 * sc
        ring_r = 4.0 * sc
        inner_r = 1.9 * sc
        tooth_w = int(round(1.9 * sc))
        for deg in range(0, 360, 45):
            rad = math.radians(deg)
            x0 = cx + (ring_r - 0.5 * sc) * math.cos(rad)
            y0 = cy + (ring_r - 0.5 * sc) * math.sin(rad)
            x1 = cx + outer_r * math.cos(rad)
            y1 = cy + outer_r * math.sin(rad)
            d.line([(x0, y0), (x1, y1)], fill=fg, width=tooth_w)
            cap = tooth_w / 2.0
            d.ellipse([x1 - cap, y1 - cap, x1 + cap, y1 + cap], fill=fg)
        d.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r], fill=fg)
        hole_col = _hex_rgba(pill_bg_hex, 255) if pill_bg_hex else base_rgba
        d.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=hole_col)

    elif kind == "pin_on":
        # Upright solid pushpin ("pushed in / pinned")
        # Cap bar
        d.rounded_rectangle(
            [cx - 3.3 * sc, cy - 5.3 * sc, cx + 3.3 * sc, cy - 3.7 * sc],
            radius=0.8 * sc,
            fill=fg,
        )
        # Tapered body
        d.polygon(
            [
                (cx - 2.1 * sc, cy - 3.9 * sc),
                (cx + 2.1 * sc, cy - 3.9 * sc),
                (cx + 2.7 * sc, cy + 0.6 * sc),
                (cx - 2.7 * sc, cy + 0.6 * sc),
            ],
            fill=fg,
        )
        # Collar flange
        d.rounded_rectangle(
            [cx - 4.2 * sc, cy + 0.0 * sc, cx + 4.2 * sc, cy + 1.8 * sc],
            radius=0.9 * sc,
            fill=fg,
        )
        # Sharp needle pointing down
        d.polygon(
            [
                (cx - 0.9 * sc, cy + 1.6 * sc),
                (cx + 0.9 * sc, cy + 1.6 * sc),
                (cx, cy + 5.7 * sc),
            ],
            fill=fg,
        )

    elif kind == "pin_off":
        # 45-degree tilted hollow/outline pushpin ("unpinned / detached")
        # Draw upright on a transparent scratch canvas, then rotate 40 deg CCW
        tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp, "RGBA")
        # Outline pin shape (distinct from solid upright pin_on!)
        td.line([(cx - 3.0 * sc, cy - 4.6 * sc), (cx + 3.0 * sc, cy - 4.6 * sc)], fill=fg, width=sw)
        td.line([(cx - 1.9 * sc, cy - 4.4 * sc), (cx - 2.3 * sc, cy + 0.4 * sc)], fill=fg, width=sw)
        td.line([(cx + 1.9 * sc, cy - 4.4 * sc), (cx + 2.3 * sc, cy + 0.4 * sc)], fill=fg, width=sw)
        td.line([(cx - 3.8 * sc, cy + 0.7 * sc), (cx + 3.8 * sc, cy + 0.7 * sc)], fill=fg, width=sw)
        td.line([(cx, cy + 1.0 * sc), (cx, cy + 5.2 * sc)], fill=fg, width=max(2, int(round(1.3 * sc))))
        rotated = tmp.rotate(-42, resample=Image.BICUBIC, center=(cx, cy))
        img.alpha_composite(rotated)

    elif kind == "hide":
        if ui_theme == "bliss_01":
            r = 3.1 * sc
            sw_x = max(3, int(round(1.8 * sc)))
            d.line([(cx - r, cy - r), (cx + r, cy + r)], fill=fg, width=sw_x)
            d.line([(cx + r, cy - r), (cx - r, cy + r)], fill=fg, width=sw_x)
        else:
            x0, x1 = cx - 4.2 * sc, cx + 4.2 * sc
            d.line([(x0, cy), (x1, cy)], fill=fg, width=sw)
            cap = sw / 2.0
            d.ellipse([x0 - cap, cy - cap, x0 + cap, cy + cap], fill=fg)
            d.ellipse([x1 - cap, cy - cap, x1 + cap, cy + cap], fill=fg)

    small = img.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


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
