"""
Renders the "odds face" for the 3D cube widget.

Takes a Match (or None) and composites 1×2 odds onto a per-theme dynamic
template image. Returns raw PNG bytes ready to serve.
"""
from __future__ import annotations

import json as _json
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from ..logging_config import get_logger
from ..models import Match
from .logos import get_logo_png_bytes, render_initials_png

logger = get_logger("app.render.cube_odds_render")

_LOGOS = Path(__file__).resolve().parents[2] / "logos"
_FONT  = Path(__file__).resolve().parents[2] / "fonts" / "Jugabet-BlackItalic.ttf"

LOGO_SIZE = 70   # px — team logo size for worldcup dynamic face

# Per-theme config:
#   template    – background image path
#   boxes       – (p1_box, draw_box, p2_box) odds areas (x0,y0,x1,y1)
#   box_colors  – text fill per box: white on purple, dark on white middle
#   logo_home   – (x, y) top-left corner to paste the home logo (optional)
#   logo_away   – (x, y) top-left corner to paste the away logo (optional)
#   name_home   – (cx, y) center-x, top-y for home team name label (optional)
#   name_away   – (cx, y) center-x, top-y for away team name label (optional)
_WHITE  = (255, 255, 255, 255)
_PURPLE = (80,  20,  180, 255)

_THEME_CONFIG = {
    "ucl": {
        "template":   _LOGOS / "182481e1-5e42-4a62-bdd9-dc04c44599c7.jpg",
        "boxes":      ((32, 322, 145, 347), (152, 322, 264, 347), (272, 322, 385, 347)),
        "box_colors": (_PURPLE, _PURPLE, _PURPLE),
    },
    "worldcup": {
        "template":   _LOGOS / "19dfacf6-41c4-43b9-91c7-79c6c2a0226f.jpg",
        "boxes":      ((33, 322, 147, 348), (153, 322, 265, 348), (273, 322, 387, 348)),
        "box_colors": (_WHITE, _PURPLE, _WHITE),
        # Logos centered horizontally over the p1/p2 odds boxes (center x = 90, 330).
        # Names just below the logo, leaving ~3px gap before the odds boxes.
        "logo_home":  (55, 238),
        "logo_away":  (295, 238),
        "name_home":  (90,  310),
        "name_away":  (330, 310),
    },
}

ODDS_FONT_SIZE = 16
NAME_FONT_SIZE = 10

_font_cache: dict = {}


def _font(size: int) -> ImageFont.ImageFont:
    if size in _font_cache:
        return _font_cache[size]
    try:
        f = ImageFont.truetype(str(_FONT), size=size)
    except Exception:
        f = ImageFont.load_default()
    _font_cache[size] = f
    return f


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple:
    bb = draw.textbbox((0, 0), text, font=font)
    return int(bb[2] - bb[0]), int(bb[3] - bb[1])


def _draw_center(
    draw: ImageDraw.ImageDraw,
    box: tuple,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple = _PURPLE,
) -> None:
    x0, y0, x1, y1 = box
    tw, th = _text_size(draw, text, font)
    draw.text(
        (x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2),
        text,
        font=font,
        fill=fill,
    )


def _parse_odds(match: Match) -> tuple[str, str, str]:
    if not match.odds_json:
        return "-", "-", "-"
    try:
        o = _json.loads(match.odds_json)
        if not isinstance(o, dict):
            return "-", "-", "-"
        def f(v) -> str:
            s = str(v).strip() if v not in (None, "") else "-"
            return s or "-"
        return f(o.get("p1")), f(o.get("draw")), f(o.get("p2"))
    except Exception:
        return "-", "-", "-"


def _paste_logo(
    img: Image.Image,
    logo_bytes: Optional[bytes],
    xy: Tuple[int, int],
    logo_size: int = LOGO_SIZE,
) -> None:
    """Crop transparent padding from the source logo, scale (up or down) to
    fill logo_size preserving aspect ratio, then center it inside the
    logo_size square so rectangular flags don't appear tiny in the corner.

    PIL's `Image.thumbnail` only DOWNSCALES, so for small source logos we
    must compute the scale factor explicitly and use `resize`."""
    if not logo_bytes:
        return
    try:
        logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        # Scale to fit logo_size on the limiting axis, preserving aspect.
        scale = min(logo_size / logo.width, logo_size / logo.height)
        new_w = max(1, int(round(logo.width * scale)))
        new_h = max(1, int(round(logo.height * scale)))
        logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # Center inside a transparent logo_size×logo_size canvas.
        canvas = Image.new("RGBA", (logo_size, logo_size), (0, 0, 0, 0))
        canvas.paste(logo, ((logo_size - new_w) // 2, (logo_size - new_h) // 2), logo)
        img.paste(canvas, xy, canvas)
    except Exception:
        logger.exception("cube odds renderer: failed to paste logo")


def _draw_team_name(
    draw: ImageDraw.ImageDraw,
    name: str,
    cx: int,
    y: int,
    font: ImageFont.ImageFont,
) -> None:
    bb = draw.textbbox((0, 0), name, font=font)
    tw = bb[2] - bb[0]
    draw.text((cx - tw / 2, y), name, font=font, fill=(80, 20, 180, 255))


def render_odds_face(
    match: Optional[Match], theme_slug: str = "ucl", scale: float = 1.0
) -> bytes:
    """Composite live odds (and logos when configured) onto the theme's dynamic
    template.

    `scale` renders the whole card larger (template + logos + text + odds boxes
    all multiplied) so the animated-GIF cube can show legible odds. The live
    widget calls with scale=1.0 and is unchanged.
    """
    cfg = _THEME_CONFIG.get(theme_slug) or _THEME_CONFIG["ucl"]
    template_path: Path = cfg["template"]
    boxes: Tuple = cfg["boxes"]

    def sc(v: float) -> int:
        return int(round(v * scale))

    def sc_box(b: Tuple) -> Tuple:
        return tuple(sc(x) for x in b)

    if not template_path.exists():
        logger.error(f"cube odds renderer: template missing at {template_path}")
        img = Image.new("RGB", (sc(420), sc(380)), (20, 20, 40))
    else:
        img = Image.open(template_path).convert("RGBA")
        if scale != 1.0:
            img = img.resize((sc(img.width), sc(img.height)), Image.Resampling.LANCZOS)

    if match is None:
        out = BytesIO()
        img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

    # Team logos (worldcup only — UCL has logos baked into the template)
    if "logo_home" in cfg:
        logo_px = sc(LOGO_SIZE)
        home_name = (match.home_name or "").strip()
        away_name = (match.away_name or "").strip()
        home_bytes = get_logo_png_bytes(match.home_logo) or render_initials_png(home_name, logo_px)
        away_bytes = get_logo_png_bytes(match.away_logo) or render_initials_png(away_name, logo_px)
        lh, lw = cfg["logo_home"], cfg["logo_away"]
        _paste_logo(img, home_bytes, (sc(lh[0]), sc(lh[1])), logo_px)
        _paste_logo(img, away_bytes, (sc(lw[0]), sc(lw[1])), logo_px)

        if "name_home" in cfg:
            d_tmp = ImageDraw.Draw(img)
            fn = _font(sc(NAME_FONT_SIZE))
            cx_h, y_h = cfg["name_home"]
            cx_a, y_a = cfg["name_away"]
            _draw_team_name(d_tmp, home_name.upper(), sc(cx_h), sc(y_h), fn)
            _draw_team_name(d_tmp, away_name.upper(), sc(cx_a), sc(y_a), fn)

    d = ImageDraw.Draw(img)
    p1, dr, p2 = _parse_odds(match)
    fo = _font(sc(ODDS_FONT_SIZE))
    colors = cfg.get("box_colors", (_PURPLE, _PURPLE, _PURPLE))

    _draw_center(d, sc_box(boxes[0]), p1, fo, colors[0])
    _draw_center(d, sc_box(boxes[1]), dr, fo, colors[1])
    _draw_center(d, sc_box(boxes[2]), p2, fo, colors[2])

    out = BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
