#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
animation_render_server.py

Анімований TV-style header (GIF) для HOT events.

Data API:
  GET {DATA_API_BASE}/events/{sport}/hot?limit=N

Render:
  GET /render/animation/{sport}/hot-header.gif?limit=10&w=2048&h=240&cb=1

Дизайн:
- Зліва: Presented by + зелена плашка JUGABET
- Далі: плитки матчів (badge, time, 2 рядки команд з логотипами, рахунок)
- Odds: акуратний "odds bar" з 3 плашками (1 / X / 2) внизу плитки
- Анімація (видима, але без крінжу):
  - легкий shimmer по всьому банеру
  - LIVE бейдж: glow (без масштабу) + blinking dot
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import FastAPI, Query
from fastapi.responses import Response
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# ================== CONFIG ==================
DATA_API_BASE = "http://127.0.0.1:8000"

DEFAULT_LIMIT = 10
MAX_LIMIT = 10

REQUEST_TIMEOUT = 10
LOGO_TIMEOUT = 8

# caches
GIF_TTL_SECONDS = 10
LOGO_TTL_SECONDS = 6 * 3600

# size
DEFAULT_W = 4096
DEFAULT_H = 240

# left brand area
LEFT_BRAND_W = 320

# tiles
MIN_TILE_W = 320
DIVIDER_W = 2

# animation
FRAMES = 24
DURATION_MS = 70

# shimmer
SHIMMER_BAND_W = 380
SHIMMER_ALPHA = 70

# live glow
LIVE_GLOW_MAX_ALPHA = 130
LIVE_GLOW_BLUR = 8

# odds bar
ODDS_PILL_H = 26
ODDS_PILL_PAD_X = 10
ODDS_PILL_RADIUS = 10

# local brand font (same as media-cub)
FONT_FILENAME = "fonts/Jugabet-BlackItalic.ttf"
# ===========================================

app = FastAPI(title="Animation Render Server (JUGABET)")

_BASE_DIR = Path(__file__).resolve().parent


# ================== CACHES ==================
@dataclass
class CacheItem:
    expires_at: float
    payload: bytes
    content_type: str


gif_cache_lock = threading.Lock()
gif_cache: Dict[str, CacheItem] = {}

logo_cache_lock = threading.Lock()
logo_cache: Dict[str, Tuple[float, Image.Image]] = {}  # url -> (expires_at, PIL RGBA)

_font_lock = threading.Lock()
_font_cache: Dict[Tuple[int, bool], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


# ================== HELPERS ==================
def now() -> float:
    return time.time()


def clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_LIMIT)


def _hash_key(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def anti_cache_headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0, s-maxage=0, proxy-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Surrogate-Control": "no-store",
        "Vary": "Accept-Encoding, User-Agent",
    }


def _font_path() -> str:
    return str((_BASE_DIR / FONT_FILENAME).resolve())


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Uses local Jugabet font only (fonts/Jugabet-BlackItalic.ttf).
    `bold` is kept for compatibility; same font is used.
    Cached to avoid disk IO per frame.
    """
    size = int(size)
    key = (size, bool(bold))

    with _font_lock:
        f = _font_cache.get(key)
        if f is not None:
            return f

    try:
        f = ImageFont.truetype(_font_path(), size=size)
    except Exception:
        f = ImageFont.load_default()

    with _font_lock:
        _font_cache[key] = f
    return f


def shorten(text: str, max_len: int) -> str:
    if not text:
        return ""
    t = str(text).strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def fetch_json(url: str) -> Any:
    r = requests.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_logo(url: str, size: Tuple[int, int]) -> Optional[Image.Image]:
    if not url:
        return None

    with logo_cache_lock:
        cached = logo_cache.get(url)
        if cached and cached[0] > now():
            return cached[1].copy().resize(size, Image.LANCZOS)

    try:
        r = requests.get(url, timeout=LOGO_TIMEOUT)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGBA")
        img = img.filter(ImageFilter.SMOOTH_MORE)

        with logo_cache_lock:
            logo_cache[url] = (now() + LOGO_TTL_SECONDS, img)

        return img.resize(size, Image.LANCZOS)
    except Exception:
        return None


def parse_hot_events(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        return [e for e in payload["events"] if isinstance(e, dict)]
    return []


def text_height(font: ImageFont.ImageFont, text: str) -> int:
    if not text:
        return 0
    try:
        bbox = font.getbbox(text)
        return max(0, bbox[3] - bbox[1])
    except Exception:
        return font.size if hasattr(font, "size") else 0


# ================== DRAW PRIMITIVES ==================
def rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    radius: int,
    fill,
    outline=None,
    width: int = 1,
):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_brand_panel(img: Image.Image, h: int) -> None:
    d = ImageDraw.Draw(img)

    d.rectangle((0, 0, LEFT_BRAND_W, h), fill=(246, 246, 246, 255))
    d.rectangle((LEFT_BRAND_W - DIVIDER_W, 0, LEFT_BRAND_W, h), fill=(210, 210, 210, 255))

    f_small = load_font(18, bold=False)
    f_big = load_font(44, bold=True)

    top = "Presented by"
    tw = d.textlength(top, font=f_small)
    d.text(((LEFT_BRAND_W - tw) / 2, 18), top, font=f_small, fill=(80, 80, 80, 255))

    plaque_h = 98
    plaque_w = LEFT_BRAND_W - 56
    x1 = (LEFT_BRAND_W - plaque_w) // 2
    y1 = (h - plaque_h) // 2 + 12
    x2 = x1 + plaque_w
    y2 = y1 + plaque_h

    rounded_rect(d, (x1, y1, x2, y2), radius=18, fill=(10, 190, 110, 255))

    brand = "JUGABET"
    tw2 = d.textlength(brand, font=f_big)
    d.text(((LEFT_BRAND_W - tw2) / 2, y1 + 22), brand, font=f_big, fill=(10, 20, 25, 255))


def draw_live_badge(img: Image.Image, x: int, y: int, text: str, phase: float) -> None:
    base = ImageDraw.Draw(img)
    f = load_font(20, bold=True)

    pad_x = 10
    tw = base.textlength(text, font=f)
    bw = int(tw) + pad_x * 2
    bh = 34

    glow = 0.35 + 0.65 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
    glow_alpha = int(LIVE_GLOW_MAX_ALPHA * glow)

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    rounded_rect(ld, (x, y, x + bw, y + bh), radius=10, fill=(255, 90, 90, glow_alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=LIVE_GLOW_BLUR))
    img.alpha_composite(layer)

    rounded_rect(
        base,
        (x, y, x + bw, y + bh),
        radius=10,
        fill=(255, 90, 90, 255),
        outline=(230, 70, 70, 255),
        width=2,
    )
    base.text((x + pad_x, y + 5), text, font=f, fill=(255, 255, 255, 255))

    if math.sin(2 * math.pi * phase) > 0:
        cx = x + bw + 10
        cy = y + bh // 2
        base.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=(255, 90, 90, 255), outline=(230, 70, 70, 255))


def draw_prematch_badge(img: Image.Image, x: int, y: int, text: str) -> None:
    d = ImageDraw.Draw(img)
    f = load_font(20, bold=True)

    pad_x = 10
    tw = d.textlength(text, font=f)
    bw = int(tw) + pad_x * 2
    bh = 34

    rounded_rect(d, (x, y, x + bw, y + bh), radius=10, fill=(245, 245, 245, 255), outline=(220, 220, 220, 255), width=2)
    d.text((x + pad_x, y + 5), text, font=f, fill=(70, 70, 70, 255))


def draw_odds_bar(img: Image.Image, x1: int, x2: int, y_bottom: int, p1: Optional[str], dr: Optional[str], p2: Optional[str]) -> None:
    """
    Малює 3 "пілли" 1/X/2 у нижній частині тайлу.
    """
    if p1 is None and dr is None and p2 is None:
        return

    d = ImageDraw.Draw(img)
    f = load_font(17, bold=True)

    items: List[Tuple[str, str]] = []
    if p1 is not None:
        items.append(("1", str(p1)))
    if dr is not None:
        items.append(("X", str(dr)))
    if p2 is not None:
        items.append(("2", str(p2)))

    if not items:
        return

    gap = 10
    pad_x = ODDS_PILL_PAD_X
    pill_h = ODDS_PILL_H

    pill_ws: List[int] = []
    for label, val in items:
        text = f"{label}  {val}"
        tw = d.textlength(text, font=f)
        pill_ws.append(int(tw) + pad_x * 2)

    total_w = sum(pill_ws) + gap * (len(pill_ws) - 1)

    x = x1 + max(14, (x2 - x1 - total_w) // 2)
    y1 = y_bottom - pill_h
    y2 = y_bottom

    for (label, val), pw in zip(items, pill_ws):
        rounded_rect(
            d,
            (x, y1, x + pw, y2),
            radius=ODDS_PILL_RADIUS,
            fill=(246, 246, 246, 255),
            outline=(220, 220, 220, 255),
            width=2,
        )

        tag_w = 26
        rounded_rect(
            d,
            (x + 4, y1 + 4, x + 4 + tag_w, y2 - 4),
            radius=8,
            fill=(35, 35, 35, 255),
            outline=None,
            width=1,
        )

        label_tw = d.textlength(label, font=f)
        d.text((x + 4 + (tag_w - label_tw) / 2, y1 + 5), label, font=f, fill=(255, 255, 255, 255))

        d.text((x + 4 + tag_w + 8, y1 + 5), f"{val}", font=f, fill=(70, 70, 70, 255))
        x += pw + gap


def draw_tile(img: Image.Image, x1: int, x2: int, h: int, ev: Dict[str, Any], phase: float) -> None:
    d = ImageDraw.Draw(img)

    d.rectangle((x1, 0, x2, h), fill=(255, 255, 255, 255))
    d.rectangle((x2 - DIVIDER_W, 0, x2, h), fill=(220, 220, 220, 255))

    status = str(ev.get("status") or "").strip().lower()
    badge_x, badge_y = x1 + 14, 12

    if status == "live":
        draw_live_badge(img, badge_x, badge_y, "LIVE", phase=phase)
    else:
        draw_prematch_badge(img, badge_x, badge_y, "PREMATCH")

    time_raw = ""
    if isinstance(ev.get("time"), dict):
        time_raw = str(ev["time"].get("raw") or "").strip()
    f_time = load_font(18, bold=False)
    if time_raw:
        d.text((x1 + 14, 54), shorten(time_raw, 26), font=f_time, fill=(95, 95, 95, 255))

    comp = ev.get("competitors") if isinstance(ev.get("competitors"), dict) else {}
    home = comp.get("home") if isinstance(comp.get("home"), dict) else {}
    away = comp.get("away") if isinstance(comp.get("away"), dict) else {}

    home_name = shorten(home.get("name") or "", 20)
    away_name = shorten(away.get("name") or "", 20)
    home_logo = str(home.get("logo") or "")
    away_logo = str(away.get("logo") or "")

    score = ev.get("score") if isinstance(ev.get("score"), dict) else {}
    hs = score.get("home")
    as_ = score.get("away")
    hs_txt = "" if hs is None else str(hs)
    as_txt = "" if as_ is None else str(as_)

    # odds (new: from market)
    market = ev.get("market") if isinstance(ev.get("market"), dict) else {}
    odds = market.get("odds") if (market.get("type") == "1x2" and isinstance(market.get("odds"), dict)) else {}
    p1 = odds.get("p1")
    dr = odds.get("draw")
    p2 = odds.get("p2")

    icon = 38
    row_top = 84
    row_gap = 58
    lx = x1 + 14
    tx = lx + icon + 12
    rx = x2 - 18

    f_team = load_font(26, bold=True)
    f_score = load_font(34, bold=True)

    hl = fetch_logo(home_logo, (icon, icon))
    al = fetch_logo(away_logo, (icon, icon))

    if hl is not None:
        img.alpha_composite(hl, (lx, row_top + 2))
    if al is not None:
        img.alpha_composite(al, (lx, row_top + row_gap + 2))

    home_th = text_height(f_team, home_name)
    away_th = text_height(f_team, away_name)
    home_text_y = row_top + (icon - home_th) // 2
    away_text_y = row_top + row_gap + (icon - away_th) // 2

    d.text((tx, home_text_y), home_name, font=f_team, fill=(28, 28, 28, 255))
    if hs_txt:
        tw = d.textlength(hs_txt, font=f_score)
        d.text((rx - tw, home_text_y - 6), hs_txt, font=f_score, fill=(15, 15, 15, 255))

    d.text((tx, away_text_y), away_name, font=f_team, fill=(120, 120, 120, 255))
    if as_txt:
        tw = d.textlength(as_txt, font=f_score)
        d.text((rx - tw, away_text_y - 6), as_txt, font=f_score, fill=(90, 90, 90, 255))

    draw_odds_bar(img, x1=x1, x2=x2, y_bottom=h - 12, p1=p1, dr=dr, p2=p2)


def make_base_frame(events: List[Dict[str, Any]], w: int, h: int, phase: float) -> Image.Image:
    img = Image.new("RGBA", (w, h), (245, 245, 245, 255))
    d = ImageDraw.Draw(img)

    d.rectangle((0, 0, w - 1, h - 1), outline=(210, 210, 210, 255), width=2)

    draw_brand_panel(img, h=h)

    x_start = LEFT_BRAND_W
    tiles_w = w - x_start

    max_tiles = max(1, tiles_w // MIN_TILE_W)
    visible = events[:max_tiles]
    n = max(1, len(visible))
    tile_w = tiles_w // n

    for i, ev in enumerate(visible):
        x1 = x_start + i * tile_w
        x2 = x_start + (i + 1) * tile_w
        draw_tile(img, x1, x2, h, ev, phase=phase)

    return img


def add_shimmer(img: Image.Image, w: int, h: int, t: float) -> Image.Image:
    band = Image.new("RGBA", (SHIMMER_BAND_W, h), (255, 255, 255, 0))
    bd = ImageDraw.Draw(band)

    for x in range(SHIMMER_BAND_W):
        tt = 1.0 - abs((x / (SHIMMER_BAND_W - 1)) * 2 - 1)
        a = int(SHIMMER_ALPHA * (tt ** 1.8))
        bd.line((x, 0, x, h), fill=(255, 255, 255, a))

    band = band.filter(ImageFilter.GaussianBlur(radius=6))

    start_x = -SHIMMER_BAND_W
    end_x = w
    x = int(start_x + (end_x - start_x) * t)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay.alpha_composite(band, (x, 0))

    out = Image.alpha_composite(img, overlay)
    out = ImageEnhance.Contrast(out).enhance(1.02)
    return out


def frames_to_gif_bytes(frames: List[Image.Image]) -> bytes:
    pal_frames: List[Image.Image] = []
    for fr in frames:
        try:
            p = fr.convert("P", palette=Image.Palette.ADAPTIVE, colors=256, dither=Image.Dither.NONE)
        except Exception:
            p = fr.convert("P", palette=Image.ADAPTIVE, colors=256)
        pal_frames.append(p)

    out = BytesIO()
    pal_frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=pal_frames[1:],
        optimize=True,
        duration=DURATION_MS,
        loop=0,
        disposal=2,
    )
    return out.getvalue()


def render_hot_header_gif(sport: str, limit: int, w: int, h: int) -> bytes:
    url = f"{DATA_API_BASE}/events/{sport}/hot?limit={limit}"
    payload = fetch_json(url)
    events = parse_hot_events(payload)

    frames: List[Image.Image] = []
    for i in range(FRAMES):
        t = i / max(1, (FRAMES - 1))
        phase = (i / FRAMES) % 1.0

        base = make_base_frame(events, w=w, h=h, phase=phase)
        frame = add_shimmer(base, w=w, h=h, t=t)
        frames.append(frame)

    return frames_to_gif_bytes(frames)


# ================== ROUTES ==================
@app.get("/render/animation/{sport}/hot-header.gif")
def hot_header_gif(
    sport: str,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    w: int = Query(DEFAULT_W, ge=800, le=4096),
    h: int = Query(DEFAULT_H, ge=120, le=600),
    cb: Optional[str] = Query(None, description="cache buster (optional)"),
):
    limit = clamp_limit(limit)

    cache_key = _hash_key(f"{sport}|{limit}|{w}|{h}")
    with gif_cache_lock:
        cached = gif_cache.get(cache_key)
        if cached and cached.expires_at > now():
            return Response(content=cached.payload, media_type=cached.content_type, headers=anti_cache_headers())

    try:
        gif_bytes = render_hot_header_gif(sport=sport, limit=limit, w=w, h=h)
    except Exception as e:
        msg = f"render error: {type(e).__name__}: {e}"
        return Response(content=msg.encode("utf-8"), media_type="text/plain", status_code=500, headers=anti_cache_headers())

    with gif_cache_lock:
        gif_cache[cache_key] = CacheItem(
            expires_at=now() + GIF_TTL_SECONDS,
            payload=gif_bytes,
            content_type="image/gif",
        )

    return Response(content=gif_bytes, media_type="image/gif", headers=anti_cache_headers())


@app.get("/health")
def health():
    font_path = str((_BASE_DIR / FONT_FILENAME).resolve())
    return {
        "ok": True,
        "service": "animation_render_server",
        "data_api_base": DATA_API_BASE,
        "font_filename": FONT_FILENAME,
        "font_path": font_path,
        "font_exists": (_BASE_DIR / FONT_FILENAME).exists(),
        "gif_ttl_seconds": GIF_TTL_SECONDS,
        "logo_ttl_seconds": LOGO_TTL_SECONDS,
        "frames": FRAMES,
        "duration_ms": DURATION_MS,
    }
