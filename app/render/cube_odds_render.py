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

LOGO_SIZE = 66   # px — team logo size for worldcup dynamic face

# Per-theme config:
#   template    – background image path
#   boxes       – (p1_box, draw_box, p2_box) odds areas (x0,y0,x1,y1)
#   box_colors  – text fill per box: white on purple, dark on white middle
#   logo_home   – (x, y) top-left corner to paste the home logo (optional)
#   logo_away   – (x, y) top-left corner to paste the away logo (optional)
#   name_home   – (cx, y) center-x, top-y for home team name label (optional)
#   name_away   – (cx, y) center-x, top-y for away team name label (optional)
#   info_pos    – (cx, top-y) center for the kickoff time / live-status label (optional)
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
        # Enlarged white card drawn in code (see `_render_big_panel`): the panel
        # grows up over the lower ball/trophy and all elements scale up. The
        # baked panel/VS/pills in the template are covered by the redrawn ones.
        "big_panel": True,
    },
}

ODDS_FONT_SIZE = 21
NAME_FONT_SIZE = 15
INFO_FONT_SIZE = 14

# ── Enlarged "big panel" layout (worldcup) ────────────────────────────────
# The dynamic white card grows UP over the lower hero image (matching the
# blue-box request) so the matchup + odds stay legible once the face is
# shrunk and colour-reduced onto the spinning-cube GIF. Everything inside is
# drawn in code: flat shapes compress far better in GIF than the photographic
# ball/trophy they cover, so the file shrinks *and* the text gets bigger.
_BRAND_PURPLE = (119, 43, 253, 255)  # sampled from the template's odds pills
_LIME = (183, 222, 19, 255)          # sampled from the template's frame
_PANEL_BG = (247, 248, 253, 255)     # the panel's near-white inner fill

PANEL_TOP_Y = 150          # white panel starts here (was ~220); covers lower hero
PANEL_BADGE_R = 40         # radius of the circular team-logo badge
# Center column reserved for "VS" + kickoff/status. Team names + badges live in
# the left/right columns OUTSIDE this band so long names can never overlap the
# centered text (the bug with "ARABIA SAUDITA" running into "HOY 23:00").
PANEL_CENTER_HALF = 62     # half-width of the protected center column
PANEL_SIDE_PAD = 18        # inner padding from the panel edge to a name/badge
PANEL_VS_FONT = 46
PANEL_NAME_FONT = 20       # base; auto-shrinks to fit the side column
PANEL_NAME_FONT_MIN = 13
PANEL_INFO_FONT = 17       # base; auto-shrinks to fit the center column
PANEL_INFO_FONT_MIN = 12
PANEL_ODDS_FONT = 34

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
    size: int = LOGO_SIZE,
) -> None:
    """Crop transparent padding from the source logo, scale (up or down) to
    fill `size` preserving aspect ratio, then center it inside the `size`
    square so rectangular flags don't appear tiny in the corner.

    PIL's `Image.thumbnail` only DOWNSCALES, so for small source logos we
    must compute the scale factor explicitly and use `resize`."""
    if not logo_bytes:
        return
    try:
        logo = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        bbox = logo.getbbox()
        if bbox:
            logo = logo.crop(bbox)
        # Scale to fit `size` on the limiting axis, preserving aspect.
        scale = min(size / logo.width, size / logo.height)
        new_w = max(1, int(round(logo.width * scale)))
        new_h = max(1, int(round(logo.height * scale)))
        logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # Center inside a transparent size×size canvas.
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(logo, ((size - new_w) // 2, (size - new_h) // 2), logo)
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


def _match_info(match: Match) -> str:
    """Short header label: live status/score when the match is in play,
    otherwise the kickoff time. Kept terse so it stays legible once the face
    is shrunk onto the spinning-cube GIF."""
    if (match.status or "").lower() == "live":
        if match.home_score is not None and match.away_score is not None:
            return f"EN VIVO  {match.home_score}-{match.away_score}"
        return "EN VIVO"
    return (match.time_raw or "").strip()


def _fit_font(
    d: ImageDraw.ImageDraw, text: str, max_width: int, base: int, min_size: int
) -> ImageFont.ImageFont:
    """Largest font (base..min) whose rendered `text` width fits `max_width`."""
    size = base
    while size > min_size and d.textlength(text, font=_font(size)) > max_width:
        size -= 1
    return _font(size)


def _draw_logo_badge(
    img: Image.Image, d: ImageDraw.ImageDraw, logo_bytes: Optional[bytes],
    cx: int, cy: int, r: int = PANEL_BADGE_R,
) -> None:
    """White circular badge with a purple ring, team logo fit inside. Gives
    rectangular flags a consistent, intentional 'coin' look on the panel."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_WHITE,
              outline=_BRAND_PURPLE, width=3)
    # Keep the logo well inside the circle (square side < circle diameter).
    box = int(r * 1.3)
    _paste_logo(img, logo_bytes, (cx - box // 2, cy - box // 2), size=box)


def _render_big_panel(img: Image.Image, match: Match) -> None:
    """Draw the enlarged white matchup card over the template (worldcup).

    Grows the dynamic card up over the lower ball/trophy so logos, names, the
    kickoff/status line and odds are all large enough to read once the face is
    perspective-warped and colour-reduced onto the GIF. Flat fills compress far
    better in GIF than the photographic hero they cover, so this also shrinks
    the file. The JUGABET header + upper hero stay visible above the card.

    Layout uses three columns — left team / center (VS + kickoff) / right team —
    with the center band reserved so long names auto-shrink instead of
    overlapping the centered text."""
    W = img.width
    d = ImageDraw.Draw(img)
    cx_mid = W / 2

    # Lime frame + near-white card.
    d.rounded_rectangle([10, PANEL_TOP_Y - 6, W - 10, 372], radius=28, fill=_LIME)
    d.rounded_rectangle([16, PANEL_TOP_Y, W - 16, 366], radius=24, fill=_PANEL_BG)

    home_name = (match.home_name or "").strip()
    away_name = (match.away_name or "").strip()

    # Column geometry: side columns sit outside the protected center band.
    side_inner = int(cx_mid - PANEL_CENTER_HALF)      # inner edge of side columns
    home_cx = (PANEL_SIDE_PAD + side_inner) // 2
    away_cx = W - home_cx
    name_max_w = side_inner - PANEL_SIDE_PAD - 6      # width a name may occupy

    # Circular team badges (real logo, else initials).
    home_bytes = get_logo_png_bytes(match.home_logo) or render_initials_png(home_name, 2 * PANEL_BADGE_R)
    away_bytes = get_logo_png_bytes(match.away_logo) or render_initials_png(away_name, 2 * PANEL_BADGE_R)
    badge_cy = 198
    _draw_logo_badge(img, d, home_bytes, home_cx, badge_cy)
    _draw_logo_badge(img, d, away_bytes, away_cx, badge_cy)

    # VS — centered in the protected band, dropped down to sit level with the
    # team badges (badge_cy) rather than crowding the top of the panel.
    d.text((cx_mid, badge_cy), "VS", font=_font(PANEL_VS_FONT), fill=_BRAND_PURPLE, anchor="mm")

    # Kickoff / live status — centered just under VS, shrunk to the center band.
    info = _match_info(match)
    if info:
        info_font = _fit_font(d, info, 2 * PANEL_CENTER_HALF - 8,
                              PANEL_INFO_FONT, PANEL_INFO_FONT_MIN)
        d.text((cx_mid, badge_cy + 36), info, font=info_font, fill=_BRAND_PURPLE, anchor="mm")

    # Team names — under each badge, auto-shrunk to fit their column.
    name_y = 256
    home_font = _fit_font(d, home_name.upper(), name_max_w, PANEL_NAME_FONT, PANEL_NAME_FONT_MIN)
    away_font = _fit_font(d, away_name.upper(), name_max_w, PANEL_NAME_FONT, PANEL_NAME_FONT_MIN)
    d.text((home_cx, name_y), home_name.upper(), font=home_font, fill=_BRAND_PURPLE, anchor="mm")
    d.text((away_cx, name_y), away_name.upper(), font=away_font, fill=_BRAND_PURPLE, anchor="mm")

    # Three enlarged odds pills (purple / white / purple), odds centred inside.
    p1, dr, p2 = _parse_odds(match)
    odds = (p1, dr, p2)
    fills = (_BRAND_PURPLE, _PANEL_BG, _BRAND_PURPLE)
    txts = (_WHITE, _BRAND_PURPLE, _WHITE)
    pad, y0, y1 = 16, 290, 346
    inner = W - 32
    bw = (inner - 4 * pad) // 3
    fo = _font(PANEL_ODDS_FONT)
    for i in range(3):
        x0 = 16 + pad + i * (bw + pad)
        x1 = x0 + bw
        d.rounded_rectangle([x0, y0, x1, y1], radius=16, fill=fills[i],
                            outline=_BRAND_PURPLE if i == 1 else None, width=2)
        d.text(((x0 + x1) / 2, (y0 + y1) / 2), odds[i], font=fo,
               fill=txts[i], anchor="mm")


def render_odds_face(match: Optional[Match], theme_slug: str = "ucl") -> bytes:
    """Composite live odds (and logos when configured) onto the theme's dynamic template."""
    cfg = _THEME_CONFIG.get(theme_slug) or _THEME_CONFIG["ucl"]
    template_path: Path = cfg["template"]
    boxes: Tuple = cfg.get("boxes", ((0, 0, 0, 0),) * 3)

    if not template_path.exists():
        logger.error(f"cube odds renderer: template missing at {template_path}")
        img = Image.new("RGB", (420, 380), (20, 20, 40))
    else:
        img = Image.open(template_path).convert("RGBA")

    if match is None:
        out = BytesIO()
        img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

    # Themes flagged big_panel draw an enlarged code-rendered matchup card
    # (logos + names + kickoff/status + odds) instead of the small baked boxes.
    if cfg.get("big_panel"):
        _render_big_panel(img, match)
        out = BytesIO()
        img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

    # Team logos (worldcup only — UCL has logos baked into the template)
    if "logo_home" in cfg:
        home_name = (match.home_name or "").strip()
        away_name = (match.away_name or "").strip()
        home_bytes = get_logo_png_bytes(match.home_logo) or render_initials_png(home_name, LOGO_SIZE)
        away_bytes = get_logo_png_bytes(match.away_logo) or render_initials_png(away_name, LOGO_SIZE)
        _paste_logo(img, home_bytes, cfg["logo_home"])
        _paste_logo(img, away_bytes, cfg["logo_away"])

        if "name_home" in cfg:
            d_tmp = ImageDraw.Draw(img)
            fn = _font(NAME_FONT_SIZE)
            cx_h, y_h = cfg["name_home"]
            cx_a, y_a = cfg["name_away"]
            _draw_team_name(d_tmp, home_name.upper(), cx_h, y_h, fn)
            _draw_team_name(d_tmp, away_name.upper(), cx_a, y_a, fn)

            if "info_pos" in cfg:
                info = _match_info(match)
                if info:
                    cx_i, y_i = cfg["info_pos"]
                    _draw_team_name(d_tmp, info, cx_i, y_i, _font(INFO_FONT_SIZE))

    d = ImageDraw.Draw(img)
    p1, dr, p2 = _parse_odds(match)
    fo = _font(ODDS_FONT_SIZE)
    colors = cfg.get("box_colors", (_PURPLE, _PURPLE, _PURPLE))

    _draw_center(d, boxes[0], p1, fo, colors[0])
    _draw_center(d, boxes[1], dr, fo, colors[1])
    _draw_center(d, boxes[2], p2, fo, colors[2])

    out = BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
