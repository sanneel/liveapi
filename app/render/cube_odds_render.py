"""
Renders the "odds face" for the 3D cube widget.

Takes a Match (or None) and composites team names + 1×2 odds onto the
shared media-cub-template.png the same way cube_render_server.py did.
Returns raw PNG bytes ready to serve.
"""
from __future__ import annotations

import json as _json
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from ..logging_config import get_logger
from ..models import Match

logger = get_logger("app.render.cube_odds_render")

_TEMPLATE = Path(__file__).resolve().parents[2] / "logos" / "media-cub-template.png"
_FONT     = Path(__file__).resolve().parents[2] / "fonts" / "Jugabet-BlackItalic.ttf"

# Pixel boxes on the 420×380 template (x0, y0, x1, y1)
NAME_HOME_BOX = (40,  290, 180, 335)
NAME_AWAY_BOX = (250, 290, 370, 335)
ODD_P1_BOX    = (39,  322, 140, 370)
ODD_DRAW_BOX  = (158, 322, 261, 370)
ODD_P2_BOX    = (277, 322, 373, 370)

BASE_TEAM_FONT = 16
MIN_TEAM_FONT  = 10
ODDS_FONT_SIZE = 22

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


def _fit_font(draw: ImageDraw.ImageDraw, t1: str, t2: str) -> ImageFont.ImageFont:
    mw1 = max(10, (NAME_HOME_BOX[2] - NAME_HOME_BOX[0]) - 8)
    mw2 = max(10, (NAME_AWAY_BOX[2] - NAME_AWAY_BOX[0]) - 8)
    size = BASE_TEAM_FONT
    while size >= MIN_TEAM_FONT:
        f = _font(size)
        w1, _ = _text_size(draw, t1, f)
        w2, _ = _text_size(draw, t2, f)
        if w1 <= mw1 and w2 <= mw2:
            return f
        size -= 1
    return _font(MIN_TEAM_FONT)


def _draw_center(draw: ImageDraw.ImageDraw, box: tuple, text: str, font) -> None:
    x0, y0, x1, y1 = box
    tw, th = _text_size(draw, text, font)
    draw.text(
        (x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2),
        text,
        font=font,
        fill=(255, 255, 255, 255),
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


def render_odds_face(match: Optional[Match]) -> bytes:
    """Composite team names + odds onto media-cub-template. Returns PNG bytes."""
    if not _TEMPLATE.exists():
        logger.error(f"cube odds renderer: template missing at {_TEMPLATE}")
        img = Image.new("RGB", (420, 380), (20, 20, 40))
    else:
        img = Image.open(_TEMPLATE).convert("RGBA")

    if match is None:
        out = BytesIO()
        img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

    d    = ImageDraw.Draw(img)
    home = (match.home_name or "-").strip()
    away = (match.away_name or "-").strip()
    p1, dr, p2 = _parse_odds(match)

    ft = _fit_font(d, home, away)
    fo = _font(ODDS_FONT_SIZE)

    _draw_center(d, NAME_HOME_BOX, home, ft)
    _draw_center(d, NAME_AWAY_BOX, away, ft)
    _draw_center(d, ODD_P1_BOX,    p1,   fo)
    _draw_center(d, ODD_DRAW_BOX,  dr,   fo)
    _draw_center(d, ODD_P2_BOX,    p2,   fo)

    out = BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
