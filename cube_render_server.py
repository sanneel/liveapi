#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import threading
import time
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import FastAPI, Response
from PIL import Image, ImageDraw, ImageFont

# ===== CONFIG =====
DATA_API_BASE = "http://127.0.0.1:8000"
SOURCE_PATH = "/events/football/hot"

# В корні поруч зі скриптом
TEMPLATE_FILENAME = "logos/media-cub-template.png"
FONT_FILENAME = "fonts/Jugabet-BlackItalic.ttf"

REQUEST_TIMEOUT = 10
PNG_TTL_SECONDS = 120  # cache готового PNG

# --- Layout (під шаблон 420x380) ---
# Назви нижче і менший шрифт (як на прикладі)
NAME_HOME_BOX = (40, 290, 180, 335)  # (x0,y0,x1,y1)
NAME_AWAY_BOX = (250, 290, 370, 335)

ODD_P1_BOX = (39, 322, 140, 370)
ODD_DRAW_BOX = (158, 322, 261, 370)
ODD_P2_BOX = (277, 322, 373, 370)

# Fonts autosize for team names (same size for both)
BASE_TEAM_FONT = 16
MIN_TEAM_FONT = 10
TEAM_FONT_STEP = 1

ODDS_FONT_SIZE = 22
# ==================

app = FastAPI(title="Media Cub Renderer", version="1.1")


def _here_path(filename: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, filename)


# ---------- Font: ONLY Jugabet-BlackItalic.ttf ----------
_font_lock = threading.Lock()
_font_cache: Dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _jugabet_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = int(size)
    with _font_lock:
        f = _font_cache.get(size)
        if f is not None:
            return f

    path = _here_path(FONT_FILENAME)
    try:
        f = ImageFont.truetype(path, size=size)
    except Exception:
        f = ImageFont.load_default()

    with _font_lock:
        _font_cache[size] = f
    return f


def _txt(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


# ---------- Template cache ----------
_tpl_lock = threading.Lock()
_tpl_img: Optional[Image.Image] = None
_tpl_mtime: float = 0.0


def _template_path() -> str:
    return _here_path(TEMPLATE_FILENAME)


def _load_template() -> Image.Image:
    global _tpl_img, _tpl_mtime
    path = _template_path()

    st = os.stat(path)
    mtime = st.st_mtime

    with _tpl_lock:
        if _tpl_img is not None and abs(_tpl_mtime - mtime) < 1e-6:
            return _tpl_img

        im = Image.open(path).convert("RGBA")
        _tpl_img = im
        _tpl_mtime = mtime
        return _tpl_img


# ---------- JSON fetch ----------
def fetch_hot_json() -> Dict[str, Any]:
    url = f"{DATA_API_BASE}{SOURCE_PATH}"
    r = requests.get(url, params={"limit": 5}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _extract_top_event(hot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    events = hot.get("events") or []
    if not events:
        return None
    return events[0]


def _odds_1x2(ev: Dict[str, Any]) -> Tuple[str, str, str]:
    market = ev.get("market") or {}
    odds = (market.get("odds") or {}) if (market.get("type") == "1x2") else {}

    def f(x: Any) -> str:
        s = _txt(x)
        return s if s else "-"

    return f(odds.get("p1")), f(odds.get("draw")), f(odds.get("p2"))

# ---------- Text helpers ----------
def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])


def _fit_same_font_for_two(
    draw: ImageDraw.ImageDraw,
    t1: str,
    t2: str,
    box1: Tuple[int, int, int, int],
    box2: Tuple[int, int, int, int],
) -> ImageFont.ImageFont:
    max_w1 = max(10, (box1[2] - box1[0]) - 8)
    max_w2 = max(10, (box2[2] - box2[0]) - 8)

    size = BASE_TEAM_FONT
    while size >= MIN_TEAM_FONT:
        f = _jugabet_font(size)
        w1, _ = _text_size(draw, t1, f)
        w2, _ = _text_size(draw, t2, f)
        if w1 <= max_w1 and w2 <= max_w2:
            return f
        size -= TEAM_FONT_STEP

    return _jugabet_font(MIN_TEAM_FONT)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill=(255, 255, 255, 255),
) -> None:
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0

    tw, th = _text_size(draw, text, font)
    x = x0 + (w - tw) / 2.0
    y = y0 + (h - th) / 2.0
    draw.text((x, y), text, font=font, fill=fill)  # без обводки


# ---------- Rendering ----------
def render_media_cub_png(ev: Optional[Dict[str, Any]]) -> bytes:
    base = _load_template().copy()
    d = ImageDraw.Draw(base)

    if not ev:
        out = BytesIO()
        base.save(out, format="PNG", optimize=True)
        return out.getvalue()

    home = ((ev.get("competitors") or {}).get("home") or {})
    away = ((ev.get("competitors") or {}).get("away") or {})
    home_name = _txt(home.get("name")) or "-"
    away_name = _txt(away.get("name")) or "-"

    p1, dr, p2 = _odds_1x2(ev)

    # Team names: одинаковый шрифт и авто-уменьшение под блоки
    font_team = _fit_same_font_for_two(d, home_name, away_name, NAME_HOME_BOX, NAME_AWAY_BOX)

    # Odds font (тот же Jugabet)
    font_odds = _jugabet_font(ODDS_FONT_SIZE)

    # Draw names (нижче)
    _draw_centered_text(d, NAME_HOME_BOX, home_name, font_team)
    _draw_centered_text(d, NAME_AWAY_BOX, away_name, font_team)

    # Draw odds (нижче)
    _draw_centered_text(d, ODD_P1_BOX, p1, font_odds)
    _draw_centered_text(d, ODD_DRAW_BOX, dr, font_odds)
    _draw_centered_text(d, ODD_P2_BOX, p2, font_odds)

    out = BytesIO()
    base.save(out, format="PNG", optimize=True)
    return out.getvalue()


# ---------- PNG cache ----------
_cache_lock = threading.Lock()
_png_cache: Dict[str, Dict[str, Any]] = {}  # key -> {ts, bytes}


def _get_cached(key: str) -> Tuple[Optional[bytes], int]:
    now = time.time()
    with _cache_lock:
        e = _png_cache.get(key)
        if e and (now - e["ts"] <= PNG_TTL_SECONDS):
            return e["bytes"], int(now - e["ts"])
    return None, 0


def _set_cached(key: str, png: bytes) -> None:
    with _cache_lock:
        _png_cache[key] = {"ts": time.time(), "bytes": png}


# ---------- API ----------
@app.get("/render/football/media-cub.png")
def render_media_buy_creative() -> Response:
    cache_key = "football_media_cub"

    cached, age = _get_cached(cache_key)
    if cached:
        return Response(
            content=cached,
            media_type="image/png",
            headers={"X-Cache": "HIT", "X-Cache-Age": str(age)},
        )

    try:
        hot = fetch_hot_json()
        ev = _extract_top_event(hot)
        png = render_media_cub_png(ev)

        _set_cached(cache_key, png)
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


@app.get("/health")
def health() -> Dict[str, Any]:
    tpl_path = _template_path()
    font_path = _here_path(FONT_FILENAME)
    return {
        "ok": True,
        "data_api_base": DATA_API_BASE,
        "source_path": SOURCE_PATH,
        "template_path": tpl_path,
        "template_exists": os.path.exists(tpl_path),
        "font_path": font_path,
        "font_exists": os.path.exists(font_path),
        "png_ttl_seconds": PNG_TTL_SECONDS,
        "name_boxes": {"home": NAME_HOME_BOX, "away": NAME_AWAY_BOX},
        "odds_boxes": {"p1": ODD_P1_BOX, "draw": ODD_DRAW_BOX, "p2": ODD_P2_BOX},
        "team_font": {"base": BASE_TEAM_FONT, "min": MIN_TEAM_FONT, "step": TEAM_FONT_STEP},
        "odds_font_size": ODDS_FONT_SIZE,
    }
