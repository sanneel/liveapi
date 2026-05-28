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

logger = get_logger("app.render.cube_odds_render")

_LOGOS = Path(__file__).resolve().parents[2] / "logos"
_FONT  = Path(__file__).resolve().parents[2] / "fonts" / "Jugabet-BlackItalic.ttf"

# Per-theme config: template image + odds box coordinates (x0,y0,x1,y1)
_THEME_CONFIG = {
    "ucl": {
        "template": _LOGOS / "182481e1-5e42-4a62-bdd9-dc04c44599c7.jpg",
        "boxes": ((32, 322, 145, 347), (152, 322, 264, 347), (272, 322, 385, 347)),
    },
    "worldcup": {
        "template": _LOGOS / "19dfacf6-41c4-43b9-91c7-79c6c2a0226f.jpg",
        "boxes": ((33, 322, 147, 348), (153, 322, 265, 348), (273, 322, 387, 348)),
    },
}

ODDS_FONT_SIZE = 16

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


def _draw_center(draw: ImageDraw.ImageDraw, box: tuple, text: str, font) -> None:
    x0, y0, x1, y1 = box
    tw, th = _text_size(draw, text, font)
    draw.text(
        (x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2),
        text,
        font=font,
        fill=(80, 20, 180, 255),
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


def render_odds_face(match: Optional[Match], theme_slug: str = "ucl") -> bytes:
    """Composite live odds onto the theme's dynamic template. Returns PNG bytes."""
    cfg = _THEME_CONFIG.get(theme_slug) or _THEME_CONFIG["ucl"]
    template_path: Path = cfg["template"]
    boxes: Tuple = cfg["boxes"]

    if not template_path.exists():
        logger.error(f"cube odds renderer: template missing at {template_path}")
        img = Image.new("RGB", (420, 380), (20, 20, 40))
    else:
        img = Image.open(template_path).convert("RGBA")

    if match is None:
        out = BytesIO()
        img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

    d = ImageDraw.Draw(img)
    p1, dr, p2 = _parse_odds(match)
    fo = _font(ODDS_FONT_SIZE)

    _draw_center(d, boxes[0], p1, fo)
    _draw_center(d, boxes[1], dr, fo)
    _draw_center(d, boxes[2], p2, fo)

    out = BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
