#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, Response
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter

from app.render.logos import (
    get_logo_bytes_for_team,
    get_logo_png_bytes as _shared_get_logo_png_bytes,
)


# ===== CONFIG =====
DATA_API_BASE = "http://127.0.0.1:8000"

DEFAULT_LIMIT = 5
MAX_LIMIT = 50

PNG_TTL_SECONDS = 120          # cache rendered PNG for 2 minutes
REQUEST_TIMEOUT = 10           # seconds (json + logo downloads)
LOGO_TTL_SECONDS = 6 * 3600    # cache logos for 6 hours
LOGO_MAX_CACHE = 500           # max cached logos in memory

WIDTH = 1000
PADDING = 0

LOGO_BOX = 104                 # TV feel
LOGO_RADIUS = 8
LOGO_INNER_PAD = 10
LOGO_INNER = LOGO_BOX - 2 * LOGO_INNER_PAD

CENTER_SAFE_ZONE = 240         # keep as-is (do not change)

BASE_TEAM_FONT = 36
MIN_TEAM_FONT = 20
TEAM_FONT_STEP = 2

LIVE_SCORE_FONT = 86           # keep as-is

TEAM_Y_OFFSET = -20
ODDS_Y_OFFSET = -4

# Header autosize (league/time)
LEAGUE_FONT_BASE = 20
LEAGUE_FONT_MIN = 14
LEAGUE_FONT_STEP = 1

TIME_FONT_BASE = 20
TIME_FONT_MIN = 14
TIME_FONT_STEP = 1

HEADER_TIME_GAP = 16  # px gap between league and centered time

CARD_BEVEL_CUT = 24

# Brand logo (Jugabet) in top-right of each card
BRAND_LOGO_REL_PATH = "logos/logo_jugabet.png"
BRAND_LOGO_HEIGHT = 40     # px (rendered height)
BRAND_PAD = 22             # padding from card edges (kept)
# ==================

#1px x 1px if feed is empty:
TRANSPARENT_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

app = FastAPI(title="Basketball Hot PNG Renderer", version="1.0")


# ---------- Fonts ----------
_BASE_DIR = Path(__file__).resolve().parent
_FONTS_DIR = _BASE_DIR / "fonts"

_FONT_REGULAR = _FONTS_DIR / "RobotoCondensed-Regular.ttf"
_FONT_EXTRABOLD = _FONTS_DIR / "RobotoCondensed-ExtraBold.ttf"

_font_lock = threading.Lock()
_font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def _pick_font(size: int, extrabold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _FONT_EXTRABOLD if extrabold else _FONT_REGULAR
    key = (str(path), int(size))

    with _font_lock:
        f = _font_cache.get(key)
        if f is not None:
            return f

    try:
        f = ImageFont.truetype(str(path), size=int(size))
    except Exception:
        f = ImageFont.load_default()

    with _font_lock:
        _font_cache[key] = f
    return f


# ---------- Brand logo cache ----------
_brand_lock = threading.Lock()
_brand_cache: Dict[int, Optional[Image.Image]] = {}  # height -> RGBA image resized


def _get_brand_logo(height: int) -> Optional[Image.Image]:
    h = max(1, int(height))
    with _brand_lock:
        cached = _brand_cache.get(h)
        if cached is not None:
            return cached

    path = _BASE_DIR / BRAND_LOGO_REL_PATH
    if not path.exists():
        return None

    try:
        im = Image.open(path).convert("RGBA")
        if im.height <= 0:
            return None
        ratio = h / float(im.height)
        w = max(1, int(im.width * ratio))
        im = im.resize((w, h), resample=Image.Resampling.LANCZOS)
    except Exception:
        return None

    with _brand_lock:
        _brand_cache[h] = im
    return im


def _txt(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _display_team_name(ev: Dict[str, Any], side: str) -> str:
    comp = ((ev.get("competitors") or {}).get(side) or {})
    name = _txt(comp.get("name")) or "-"
    return name


def _time_raw(event: Dict[str, Any]) -> str:
    return _txt((event.get("time") or {}).get("raw"))


def _score_text(event: Dict[str, Any]) -> str:
    sc = event.get("score") or {}
    h = sc.get("home")
    a = sc.get("away")
    if h is None or a is None:
        return ""
    return f"{h}–{a}"


# ---------- Basketball header center text ----------
_Q_RE = re.compile(r"(\d+)\s*º\s*cuarto", re.IGNORECASE)
_MIN_RE = re.compile(r"(\d+)\s*['’]", re.IGNORECASE)
_OT_RE = re.compile(r"prórroga|prorroga", re.IGNORECASE)


def _normalize_basket_live_time(tr: str) -> str:
    s = " ".join((tr or "").strip().split())
    if not s:
        return "LIVE"

    sl = s.lower()

    # Half-time
    if "descanso" in sl:
        return "HT"

    # Overtime
    if _OT_RE.search(s):
        mmin = _MIN_RE.search(s)
        if mmin:
            return f"OT {mmin.group(1)}'"
        return "OT"

    # Quarter
    mq = _Q_RE.search(s)
    if mq:
        q = mq.group(1)
        mmin = _MIN_RE.search(s)
        if mmin:
            return f"Q{q} {mmin.group(1)}'"
        return f"Q{q}"

    # Fallback: keep compact uppercase but avoid super long
    out = s.upper()
    if len(out) > 12:
        out = out[:11] + "…"
    return out


def _header_center_text(ev: Dict[str, Any]) -> str:
    """
    Basketball rule (variant 1 "like tennis"):
      - LIVE: show normalized quarter/clock (from time.raw)
      - PREMATCH: show time.raw as-is (uppercased)
    """
    status = (_txt(ev.get("status"))).lower()
    tr = _time_raw(ev)

    if status == "live":
        return _normalize_basket_live_time(tr)

    return tr.upper() if tr else ""


def _odds_values_winner(event: Dict[str, Any]) -> Tuple[str, str]:
    """
    Keep EXACT same odds behavior as tennis renderer:
    market.type == 'winner' -> render (p1, p2)
    """
    market = event.get("market") or {}
    odds = (market.get("odds") or {}) if (market.get("type") == "winner") else {}

    def f(x: Any) -> str:
        s = _txt(x)
        return s if s else "-"

    return f(odds.get("p1")), f(odds.get("p2"))


# ---------- Logo cache (anti-DDOS) ----------
_logo_lock = threading.Lock()
_logo_cache: Dict[str, Dict[str, Any]] = {}
# entry: url -> {"ts": epoch, "png": bytes (RGBA PNG resized to LOGO_INNER) or None}


def _prune_logo_cache() -> None:
    now = time.time()
    expired = [u for u, e in _logo_cache.items() if (now - e["ts"]) > LOGO_TTL_SECONDS]
    for u in expired:
        _logo_cache.pop(u, None)

    if len(_logo_cache) <= LOGO_MAX_CACHE:
        return

    items = sorted(_logo_cache.items(), key=lambda kv: kv[1]["ts"])
    for u, _ in items[: max(0, len(_logo_cache) - LOGO_MAX_CACHE)]:
        _logo_cache.pop(u, None)


def _download_logo(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "hot-render/1.0"})
        if r.status_code != 200 or not r.content:
            return None

        im = Image.open(BytesIO(r.content)).convert("RGBA")
        im = im.resize((LOGO_INNER, LOGO_INNER), resample=Image.Resampling.LANCZOS)

        out = BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return None


def get_logo_png_bytes(url: Optional[str]) -> Optional[bytes]:
    return _shared_get_logo_png_bytes(url)


def _rounded_rect(draw: ImageDraw.ImageDraw, box, r: int, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def paste_logo_box(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    logo_png: Optional[bytes],
    x: int,
    y: int,
    box_size: int,
    inner_pad: int,
    box_fill,
):
    _rounded_rect(draw, (x, y, x + box_size, y + box_size), r=LOGO_RADIUS, fill=box_fill)
    if not logo_png:
        return
    try:
        logo = Image.open(BytesIO(logo_png)).convert("RGBA")
        target = (box_size - 2 * inner_pad, box_size - 2 * inner_pad)
        if logo.size != target:
            logo = logo.resize(target, resample=Image.Resampling.LANCZOS)
        img.alpha_composite(logo, dest=(x + inner_pad, y + inner_pad))
    except Exception:
        return


# ---------- Facet / bevel helpers ----------
def _bevel_mask(w: int, h: int, cut: int) -> Image.Image:
    c = max(0, int(cut))
    c = min(c, w // 2, h // 2)

    mask = Image.new("L", (w, h), 255)
    md = ImageDraw.Draw(mask)

    md.polygon([(0, 0), (c, 0), (0, c)], fill=0)
    md.polygon([(w - 1, 0), (w - 1 - c, 0), (w - 1, c)], fill=0)
    md.polygon([(w - 1, h - 1), (w - 1 - c, h - 1), (w - 1, h - 1 - c)], fill=0)
    md.polygon([(0, h - 1), (c, h - 1), (0, h - 1 - c)], fill=0)

    return mask


def _paste_beveled_rect(img: Image.Image, x0: int, y0: int, x1: int, y1: int, fill_rgba, cut: int) -> Image.Image:
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return Image.new("L", (max(1, w), max(1, h)), 0)

    card_img = Image.new("RGBA", (w, h), fill_rgba)
    mask = _bevel_mask(w, h, cut=cut)
    img.paste(card_img, (x0, y0), mask)
    return mask


# ---------- Gradient helpers ----------
def _make_center_glow_overlay(w: int, h: int, color_rgb: Tuple[int, int, int], peak_alpha: int) -> Image.Image:
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = overlay.load()
    mid = (w - 1) / 2.0
    if mid <= 0:
        return overlay

    r, g, b = color_rgb
    for x in range(w):
        t = 1.0 - (abs(x - mid) / mid)
        if t < 0:
            t = 0
        a = int(peak_alpha * (t * 1.3))
        if a <= 0:
            continue
        for y in range(h):
            px[x, y] = (r, g, b, a)
    return overlay


def _make_vignette_overlay(w: int, h: int, strength: int = 55) -> Image.Image:
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = overlay.load()
    cx = (w - 1) / 2.0
    cy = (h - 1) / 2.0
    maxd = (cx * cx + cy * cy) ** 0.5
    if maxd <= 0:
        return overlay

    for y in range(h):
        for x in range(w):
            dx = x - cx
            dy = y - cy
            d = (dx * dx + dy * dy) ** 0.5
            t = d / maxd
            a = int(strength * (t * t))
            if a:
                px[x, y] = (0, 0, 0, a)
    return overlay


def _apply_card_fx_masked(img: Image.Image, x0: int, y0: int, x1: int, y1: int, is_live: bool, mask: Image.Image) -> None:
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return

    fx = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fx.alpha_composite(_make_vignette_overlay(w, h, strength=48), dest=(0, 0))

    if is_live:
        fx.alpha_composite(_make_center_glow_overlay(w, h, color_rgb=(160, 40, 40), peak_alpha=95), dest=(0, 0))
    else:
        fx.alpha_composite(_make_center_glow_overlay(w, h, color_rgb=(0, 92, 255), peak_alpha=45), dest=(0, 0))

    a = fx.getchannel("A")
    a = ImageChops.multiply(a, mask)
    fx.putalpha(a)

    img.alpha_composite(fx, dest=(x0, y0))


def _apply_inner_shadow(
    img: Image.Image,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    mask: Image.Image,
    color_rgb: Tuple[int, int, int],
    thickness: int = 8,
    blur_radius: int = 24,
):
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return

    if w - 2 * thickness <= 2 or h - 2 * thickness <= 2:
        return

    outer = mask

    inner = _bevel_mask(
        w - 2 * thickness,
        h - 2 * thickness,
        cut=max(0, CARD_BEVEL_CUT - thickness // 2),
    )

    inner_full = Image.new("L", (w, h), 0)
    inner_full.paste(inner, (thickness, thickness))

    shadow_mask = ImageChops.subtract(outer, inner_full)
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(blur_radius))
    shadow_mask = ImageChops.multiply(shadow_mask, outer)

    r, g, b = color_rgb
    shadow_layer = Image.new("RGBA", (w, h), (r, g, b, 255))
    shadow_layer.putalpha(shadow_mask)

    img.alpha_composite(shadow_layer, dest=(x0, y0))


# ---------- Header autosize ----------
def _fit_header_font_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    base: int,
    min_size: int,
    step: int,
    max_width: int,
) -> int:
    size = base
    while size >= min_size:
        f = _pick_font(size)
        if draw.textlength(text, font=f) <= max_width:
            return size
        size -= step
    return min_size


# ---------- Team font autosize (NO ellipsis; one size for both) ----------
def _fit_team_font_size(
    draw: ImageDraw.ImageDraw,
    home_name: str,
    away_name: str,
    max_home_w: int,
    max_away_w: int,
    min_size: int,
) -> int:
    size = BASE_TEAM_FONT
    min_size = int(min_size)
    while size >= min_size:
        f = _pick_font(size)
        if draw.textlength(home_name, font=f) <= max_home_w and draw.textlength(away_name, font=f) <= max_away_w:
            return size
        size -= TEAM_FONT_STEP
    return min_size


# ---------- Rendering ----------
def render_hot_png(events: List[Dict[str, Any]]) -> bytes:
    card_h = 270
    gap = 18

    # same palette as football renderer (do not change styles)
    card = (3, 16, 42)
    card_live = (3, 16, 42)

    text_main = (245, 245, 245)
    accent = (182, 222, 19)
    red = (238, 49, 36)

    logo_plate = (29, 47, 90)
    logo_plate_live = (31, 36, 51)

    odds_plate = (23, 45, 86)
    odds_plate_live = (45, 39, 59)

    font_score = _pick_font(LIVE_SCORE_FONT, extrabold=True)  # ExtraBold (LIVE score)
    font_vs = _pick_font(LIVE_SCORE_FONT, extrabold=True)     # ExtraBold
    font_odds = _pick_font(36)                                # Regular

    brand_logo = _get_brand_logo(BRAND_LOGO_HEIGHT)

    n = min(len(events), 50)

    if n == 0:
        # Нема матчів → повертаємо прозорий 1x1 PNG (щоб <img> не ламався)
        return TRANSPARENT_PNG_1X1

    height = PADDING + n * card_h + (n - 1) * gap + PADDING
    img = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    y = PADDING

    for i in range(n):
        ev = events[i]
        status = (ev.get("status") or "").strip().lower()
        is_live = status == "live"

        x0, y0 = PADDING, y
        x1, y1 = WIDTH - PADDING, y + card_h
        center_x = (x0 + x1) // 2

        # Main card: beveled corners
        fill_color = (card_live if is_live else card)
        bevel_mask = _paste_beveled_rect(img, x0, y0, x1, y1, fill_rgba=fill_color, cut=CARD_BEVEL_CUT)

        _apply_card_fx_masked(img, x0, y0, x1, y1, is_live=is_live, mask=bevel_mask)

        shadow_color = (255, 0, 40) if is_live else (0, 92, 255)
        _apply_inner_shadow(
            img,
            x0, y0, x1, y1,
            mask=bevel_mask,
            color_rgb=shadow_color,
            thickness=6,
            blur_radius=10,
        )

        # Green accent border (2px)
        border_color = (182, 222, 19, 255)
        border_width = 2

        outer_mask = _bevel_mask(x1 - x0, y1 - y0, cut=CARD_BEVEL_CUT)
        inner_mask = _bevel_mask(
            (x1 - x0) - 2 * border_width,
            (y1 - y0) - 2 * border_width,
            cut=max(0, CARD_BEVEL_CUT - border_width),
        )

        border_layer = Image.new("RGBA", (x1 - x0, y1 - y0), border_color)
        border_alpha = outer_mask.copy()

        inner_alpha = Image.new("L", (x1 - x0, y1 - y0), 0)
        inner_alpha.paste(inner_mask, (border_width, border_width))
        border_alpha = ImageChops.subtract(border_alpha, inner_alpha)

        border_layer.putalpha(border_alpha)
        img.alpha_composite(border_layer, dest=(x0, y0))

        # Brand logo (top-right)
        if brand_logo is not None:
            bx = x1 - brand_logo.width
            by = y0
            if bx < x0:
                bx = x0
            if by < y0:
                by = y0
            img.alpha_composite(brand_logo, dest=(int(bx), int(by)))

        # top strip
        top_y = y0 + 20

        tournament = (_txt((ev.get("tournament") or {}).get("name")) or "-").upper()
        time_txt = _header_center_text(ev)

        left_pad = 22
        right_pad = 22
        league_x = x0 + left_pad

        # TIME (center): autosize and get real width first
        time_w = 0.0
        font_time = _pick_font(TIME_FONT_BASE)
        if time_txt:
            time_max_w = max(80, (x1 - x0) - (left_pad + right_pad))
            time_font_size = _fit_header_font_size(
                d, time_txt,
                base=TIME_FONT_BASE, min_size=TIME_FONT_MIN, step=TIME_FONT_STEP,
                max_width=time_max_w,
            )
            font_time = _pick_font(time_font_size)
            time_w = d.textlength(time_txt, font=font_time)

        # Reserve centered zone for time (+ gap)
        time_left = (center_x - time_w / 2) - HEADER_TIME_GAP

        # LEAGUE: fit into area up to time_left
        league_max_w = max(80, int(time_left - league_x))

        league_font_size = _fit_header_font_size(
            d, tournament,
            base=LEAGUE_FONT_BASE, min_size=LEAGUE_FONT_MIN, step=LEAGUE_FONT_STEP,
            max_width=league_max_w,
        )
        font_tour = _pick_font(league_font_size)

        d.text((league_x, top_y), tournament, fill=(255, 255, 255), font=font_tour)

        if time_txt:
            d.text((center_x - time_w / 2, top_y), time_txt, fill=(255, 255, 255), font=font_time)

        # main row baseline
        baseline_y = y0 + 118

        logo_y = int(baseline_y - (LOGO_BOX / 2))

        left_logo_x = x0 + 22
        right_logo_x = x1 - 22 - LOGO_BOX

        home = ((ev.get("competitors") or {}).get("home") or {})
        away = ((ev.get("competitors") or {}).get("away") or {})

        home_name = _display_team_name(ev, "home")
        away_name = _display_team_name(ev, "away")

        home_logo = get_logo_bytes_for_team(home)
        away_logo = get_logo_bytes_for_team(away)

        paste_logo_box(
            img, d,
            home_logo,
            left_logo_x, logo_y,
            box_size=LOGO_BOX,
            inner_pad=LOGO_INNER_PAD,
            box_fill=(logo_plate_live if is_live else logo_plate),
        )
        paste_logo_box(
            img, d,
            away_logo,
            right_logo_x, logo_y,
            box_size=LOGO_BOX,
            inner_pad=LOGO_INNER_PAD,
            box_fill=(logo_plate_live if is_live else logo_plate),
        )

        left_name_x = left_logo_x + LOGO_BOX + 18
        left_name_max_right = center_x - (CENTER_SAFE_ZONE // 2)

        right_name_max_left = center_x + (CENTER_SAFE_ZONE // 2)
        right_name_right_edge = right_logo_x - 18

        max_home_w = max(60, left_name_max_right - left_name_x)
        max_away_w = max(60, right_name_right_edge - right_name_max_left)

        fitted_size = _fit_team_font_size(
            d,
            home_name,
            away_name,
            max_home_w,
            max_away_w,
            min_size=MIN_TEAM_FONT,
        )
        font_team = _pick_font(fitted_size)

        d.text((left_name_x, baseline_y + TEAM_Y_OFFSET), home_name, fill=text_main, font=font_team)

        away_w = d.textlength(away_name, font=font_team)
        d.text((right_name_right_edge - away_w, baseline_y + TEAM_Y_OFFSET), away_name, fill=text_main, font=font_team)

        # Center big text:
        #  - LIVE: big score "64–72"
        #  - PREMATCH: "VS"
        if is_live:
            score = _score_text(ev) or "—"
            sw = d.textlength(score, font=font_score)
            score_y = int(baseline_y - (LIVE_SCORE_FONT * 0.60))
            d.text((center_x - sw / 2, score_y), score, fill=red, font=font_score)
        else:
            vs_txt = "VS"
            vw = d.textlength(vs_txt, font=font_vs)
            vs_y = int(baseline_y - (font_vs.size * 0.60))
            d.text((center_x - vw / 2, vs_y), vs_txt, fill=accent, font=font_vs)

        # Odds block: EXACT same as tennis (2 pills p1/p2)
        p1, p2 = _odds_values_winner(ev)
        vals2 = [p1, p2]

        pill_y0 = y0 + 192
        pill_h = 54
        pill_gap = 14

        total_w = (x1 - x0) - 44
        pill_w = int((total_w - 1 * pill_gap) / 2)  # 2 pills, 1 gap

        start_x = x0 + 22
        for j in range(2):
            px0 = start_x + j * (pill_w + pill_gap)
            px1 = px0 + pill_w
            _rounded_rect(
                d,
                (px0, pill_y0, px1, pill_y0 + pill_h),
                r=8,
                fill=(odds_plate_live if is_live else odds_plate),
            )

            val = vals2[j] if vals2[j] else "-"
            tw = d.textlength(val, font=font_odds)
            text_y = pill_y0 + (pill_h / 2) - (font_odds.size / 2) + ODDS_Y_OFFSET
            d.text((px0 + (pill_w - tw) / 2, text_y), val, fill=(230, 230, 235), font=font_odds)

        y += card_h + gap

    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ---------- PNG cache ----------
_cache_lock = threading.Lock()
_png_cache: Dict[int, Dict[str, Any]] = {}  # limit -> {ts, bytes, meta}


def fetch_hot_json(limit: int) -> Dict[str, Any]:
    url = f"{DATA_API_BASE}/events/basketball/hot"
    r = requests.get(url, params={"limit": limit}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_cached_png(limit: int) -> Tuple[Optional[bytes], Dict[str, Any]]:
    now = time.time()
    with _cache_lock:
        entry = _png_cache.get(limit)
        if entry and (now - entry["ts"] <= PNG_TTL_SECONDS):
            return entry["bytes"], {"cached": True, "age_seconds": int(now - entry["ts"]), **entry.get("meta", {})}
    return None, {"cached": False}


def set_cached_png(limit: int, png_bytes: bytes, meta: Dict[str, Any]) -> None:
    with _cache_lock:
        _png_cache[limit] = {"ts": time.time(), "bytes": png_bytes, "meta": meta}


# ---------- API ----------
@app.get("/render/basketball/hot.png")
def render_basketball_hot_png(limit: int = DEFAULT_LIMIT) -> Response:
    limit = max(1, min(int(limit), MAX_LIMIT))

    cached, meta = get_cached_png(limit)
    if cached:
        return Response(
            content=cached,
            media_type="image/png",
            headers={"X-Cache": "HIT", "X-Cache-Age": str(meta.get("age_seconds", 0))},
        )

    try:
        hot = fetch_hot_json(limit)
        events = hot.get("events") or []
        png = render_hot_png(events)

        set_cached_png(limit, png, {"source_meta_ok": (hot.get("meta") or {}).get("ok", True)})
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Cache": "MISS",
            },
        )
    except Exception as e:
        return Response(content=f"render error: {e}".encode("utf-8"), media_type="text/plain", status_code=503)


def fetch_manual_json(slot: str) -> list:
    url = f"{DATA_API_BASE}/manual/slots/{slot}"
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json().get("events") or []


@app.get("/render/basketball/manual/{slot}.png")
def render_basketball_manual_png(slot: str) -> Response:
    """Render a manually curated slot as a PNG. No caching — always fresh."""
    try:
        events = fetch_manual_json(slot)
        png = render_hot_png(events)
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    except Exception as e:
        return Response(content=f"render error: {e}".encode(), media_type="text/plain", status_code=503)


@app.get("/health")
def health() -> Dict[str, Any]:
    with _cache_lock, _logo_lock:
        keys = sorted(_png_cache.keys())
        logo_cached = len(_logo_cache)
    return {
        "ok": True,
        "data_api_base": DATA_API_BASE,
        "png_ttl_seconds": PNG_TTL_SECONDS,
        "logo_ttl_seconds": LOGO_TTL_SECONDS,
        "logo_cache_size": logo_cached,
        "cached_limits": keys,
        "logo_box": LOGO_BOX,
        "center_safe_zone": CENTER_SAFE_ZONE,
        "team_font_base": BASE_TEAM_FONT,
        "team_font_min": MIN_TEAM_FONT,
        "live_score_font": LIVE_SCORE_FONT,
        "endpoint": "/render/basketball/hot.png",
    }