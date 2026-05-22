"""
Themed cube PNG renderer.

Generates a 600×600 branded PNG for one football match (or whatever sport
the theme is scoped to). Composes a procedural background gradient + theme
badge + match summary so themed cubes can ship without each theme needing
its own pre-baked template asset. If a theme later provides a real branded
template image, the renderer composites match data on top of THAT instead.

This is deliberately PIL-only — no Playwright, no Skia, no Chromium. The
cube renders in well under 100ms even cold, and is cached upstream by
png_cache so repeat hits cost nothing.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from ..logging_config import get_logger
from ..models import Match
from ..services.cube_themes import CubeTheme

logger = get_logger("app.render.cube_render")

# Canvas size for the themed cube. Square so the asset works for OG/social,
# email headers, and ad banners without re-cropping.
CUBE_W = 600
CUBE_H = 600

# Brand font shared with the other renderers (legacy cube_render_server.py
# also uses this exact file).
_FONT_PATH = (
    Path(__file__).resolve().parents[2] / "fonts" / "Jugabet-BlackItalic.ttf"
)

_font_cache: Dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    f = _font_cache.get(size)
    if f is not None:
        return f
    try:
        f = ImageFont.truetype(str(_FONT_PATH), size=size)
    except Exception:
        # Headless box without the brand font — fall back to PIL default so
        # the cube still renders rather than crashing the route.
        logger.warning(f"cube renderer: brand font missing at {_FONT_PATH}, using default")
        f = ImageFont.load_default()
    _font_cache[size] = f
    return f


# ── Background ──────────────────────────────────────────────────────────
def _vertical_gradient(
    size: Tuple[int, int],
    top: Tuple[int, int, int],
    bottom: Tuple[int, int, int],
) -> Image.Image:
    """Linear top-to-bottom RGB gradient. PIL has no built-in for this."""
    w, h = size
    img = Image.new("RGB", size, top)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _load_template(theme: CubeTheme) -> Image.Image:
    """Either composite onto a theme-provided template image, or build a
    procedural gradient background sized CUBE_W × CUBE_H."""
    if theme.template_image_path:
        path = Path(__file__).resolve().parents[2] / theme.template_image_path
        if path.exists():
            try:
                im = Image.open(path).convert("RGBA")
                if im.size != (CUBE_W, CUBE_H):
                    im = im.resize((CUBE_W, CUBE_H), Image.LANCZOS)
                return im
            except Exception:
                logger.exception(
                    f"cube renderer: failed to load template {path}; falling back to gradient"
                )
    grad = _vertical_gradient((CUBE_W, CUBE_H), theme.bg_top, theme.bg_bottom)
    return grad.convert("RGBA")


# ── Drawing helpers ─────────────────────────────────────────────────────
def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])


def _center(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    tw, th = _text_size(draw, text, font)
    draw.text(
        (x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2),
        text,
        font=font,
        fill=fill + (255,),
    )


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_w: int,
    start: int = 56,
    floor: int = 22,
) -> ImageFont.FreeTypeFont:
    size = start
    while size > floor:
        f = _font(size)
        w, _ = _text_size(draw, text, f)
        if w <= max_w:
            return f
        size -= 2
    return _font(floor)


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    radius: int,
    fill: Tuple[int, int, int],
    outline: Optional[Tuple[int, int, int]] = None,
    width: int = 0,
) -> None:
    fill_rgba = fill + (255,)
    outline_rgba = (outline + (255,)) if outline else None
    draw.rounded_rectangle(box, radius=radius, fill=fill_rgba, outline=outline_rgba, width=width)


# ── Field extraction (Match → display strings) ──────────────────────────
def _odds_strings(match: Match) -> Tuple[str, str, str]:
    """Return (p1, draw, p2) odds strings — '-' for missing values."""
    import json as _json
    raw = match.odds_json
    if not raw:
        return "-", "-", "-"
    try:
        odds = _json.loads(raw)
    except Exception:
        return "-", "-", "-"
    if not isinstance(odds, dict):
        return "-", "-", "-"

    def f(v: Any) -> str:
        if v is None:
            return "-"
        s = str(v).strip()
        return s if s else "-"
    return f(odds.get("p1")), f(odds.get("draw")), f(odds.get("p2"))


def _time_label(match: Match) -> str:
    if match.status and match.status.lower() == "live":
        if match.home_score is not None and match.away_score is not None:
            return f"LIVE  {match.home_score} - {match.away_score}"
        return "LIVE"
    return (match.time_raw or "").strip() or "—"


# ── Main render ─────────────────────────────────────────────────────────
def render_cube_png(theme: CubeTheme, match: Optional[Match]) -> bytes:
    """Compose the themed cube PNG. `match=None` renders the placeholder
    (theme branding only, no event) so the endpoint always returns a valid
    image even when zero in-scope matches exist."""
    base = _load_template(theme)
    draw = ImageDraw.Draw(base, "RGBA")

    # Top badge plaque — accent-colored pill with theme.badge_text
    badge_text = theme.badge_text.upper()
    badge_font = _font(34)
    bw, bh = _text_size(draw, badge_text, badge_font)
    pad_x, pad_y = 28, 12
    badge_box = (
        (CUBE_W - bw) // 2 - pad_x,
        40,
        (CUBE_W + bw) // 2 + pad_x,
        40 + bh + pad_y * 2,
    )
    _rounded_rect(draw, badge_box, radius=28, fill=theme.accent)
    _center(draw, badge_box, badge_text, badge_font, fill=(20, 20, 20))

    # Subtitle (small, under badge)
    sub_font = _font(20)
    sw, sh = _text_size(draw, theme.subtitle, sub_font)
    draw.text(
        ((CUBE_W - sw) // 2, badge_box[3] + 14),
        theme.subtitle,
        font=sub_font,
        fill=theme.text_muted + (255,),
    )

    if match is None:
        # Placeholder: clean theme branding + "No matches" line.
        msg = "Awaiting in-scope matches"
        f = _font(28)
        mw, _ = _text_size(draw, msg, f)
        draw.text(
            ((CUBE_W - mw) // 2, CUBE_H // 2),
            msg,
            font=f,
            fill=theme.text_muted + (255,),
        )
        return _encode(base)

    # ── Event block (center) ──
    home_name = (match.home_name or "?").strip()
    away_name = (match.away_name or "?").strip()

    # "VS" plaque between teams
    vs_text = "VS"
    vs_font = _font(54)
    vw, vh = _text_size(draw, vs_text, vs_font)
    vs_y = 270
    draw.text(
        ((CUBE_W - vw) // 2, vs_y),
        vs_text,
        font=vs_font,
        fill=theme.accent + (255,),
    )

    # Team names — auto-fit width
    max_team_w = CUBE_W - 80
    home_font = _fit_font(draw, home_name, max_team_w)
    away_font = _fit_font(draw, away_name, max_team_w)
    hw, hh = _text_size(draw, home_name, home_font)
    aw, ah = _text_size(draw, away_name, away_font)
    draw.text(
        ((CUBE_W - hw) // 2, vs_y - hh - 28),
        home_name,
        font=home_font,
        fill=theme.text_primary + (255,),
    )
    draw.text(
        ((CUBE_W - aw) // 2, vs_y + vh + 28),
        away_name,
        font=away_font,
        fill=theme.text_primary + (255,),
    )

    # Time / status strip
    time_label = _time_label(match)
    tf = _font(22)
    tw, th = _text_size(draw, time_label, tf)
    draw.text(
        ((CUBE_W - tw) // 2, vs_y + vh + 28 + ah + 18),
        time_label,
        font=tf,
        fill=theme.text_muted + (255,),
    )

    # ── Odds row at the bottom ──
    p1, dr, p2 = _odds_strings(match)
    odds_y = CUBE_H - 110
    slot_w = (CUBE_W - 80) // 3
    margin = 20
    for i, (label, val) in enumerate([("1", p1), ("X", dr), ("2", p2)]):
        x0 = 40 + i * (slot_w + 10)
        box = (x0, odds_y, x0 + slot_w, odds_y + 80)
        _rounded_rect(
            draw,
            box,
            radius=14,
            fill=(0, 0, 0),
            outline=theme.accent,
            width=2,
        )
        label_font = _font(18)
        val_font = _font(36)
        # Label top-left of slot
        draw.text((x0 + 12, odds_y + 8), label, font=label_font, fill=theme.text_muted + (255,))
        # Value centered
        vw_, vh_ = _text_size(draw, val, val_font)
        draw.text(
            (x0 + (slot_w - vw_) // 2, odds_y + (80 - vh_) // 2 + 4),
            val,
            font=val_font,
            fill=theme.text_primary + (255,),
        )
    return _encode(base)


def _encode(img: Image.Image) -> bytes:
    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
