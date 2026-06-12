"""
Themed cube endpoints.

Two endpoints per theme:
  GET /cube/{theme}.png   →  branded PNG of the top in-scope match
  GET /cube/{theme}       →  HTML preview page (auto-refreshes the PNG)

Themes are registered in `app.services.cube_themes`. Adding a new theme
does NOT require editing this file.

Cache:
  PNG bytes go through the shared `png_cache` keyed `cube:{theme}` so the
  parser's post-cycle invalidation hook clears stale cubes the same way
  /hot/{sport}.png is cleared.
"""

from __future__ import annotations

import hashlib
import json as _json
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Match
from ..render.cube_gif_render import (
    FACE_H,
    FACE_W,
    GIF_FRAMES,
    GIF_FRAMES_MAX,
    GIF_FRAMES_MIN,
    GIF_SECONDS_DEFAULT,
    GIF_SECONDS_MAX,
    GIF_SECONDS_MIN,
    GIF_SIZE,
    GIF_SIZE_MAX,
    GIF_SIZE_MIN,
    GIF_TILT_DEFAULT,
    GIF_TILT_MAX,
    GIF_TILT_MIN,
    render_cube_gif,
)
from ..render.cube_render import render_cube_png
from ..render.cube_odds_render import render_odds_face
from ..services import png_cache
from ..services.cube_resolver import resolve_for_theme
from ..services.cube_themes import CUBE_THEMES, CubeTheme, get_theme, list_themes

logger = get_logger("app.routes.public_cube")

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 1×1 transparent fallback shared with public_hot.py contract.
_TRANSPARENT_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _cache_key(theme_slug: str) -> str:
    return f"cube:{theme_slug}"


def _etag(png: bytes) -> str:
    return '"' + hashlib.md5(png).hexdigest() + '"'


def _png_response(
    png: bytes,
    cache_status: str,
    status_code: int = 200,
    etag: str = "",
) -> Response:
    headers = {
        # Short stale window so an admin pin/swap shows up promptly instead of
        # the previous match lingering on screen (the "Brazil for 2s, then
        # France" flash). The server-side png_cache still absorbs render load;
        # this only governs how long clients may reuse a now-stale image.
        "Cache-Control": "public, max-age=15, stale-while-revalidate=15",
        "X-Cache": cache_status,
    }
    if etag:
        headers["ETag"] = etag
    return Response(
        content=png,
        media_type="image/png",
        status_code=status_code,
        headers=headers,
    )


@router.get("/cube", response_class=HTMLResponse)
def cube_index(request: Request) -> HTMLResponse:
    """Tiny landing page that lists registered themes — useful for QA."""
    themes = list_themes()
    return templates.TemplateResponse(
        request,
        "cube/index.html",
        {"themes": themes},
    )


@router.get("/cube/{theme}.png")
@limiter.limit("600/minute")
def cube_png(theme: str, request: Request) -> Response:
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")

    key = _cache_key(t.slug)
    cached = png_cache.get(key)
    if cached is not None:
        etag = _etag(cached)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return _png_response(cached, cache_status="HIT", etag=etag)

    with db_session() as session:
        matches = resolve_for_theme(session, t, limit=1)
        match = matches[0] if matches else None

    try:
        png = render_cube_png(t, match)
    except Exception:
        logger.exception(f"cube render failed theme={t.slug}")
        return _png_response(_TRANSPARENT_PNG_1X1, cache_status="ERROR", status_code=500)

    png_cache.put(key, png)
    etag = _etag(png)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return _png_response(png, cache_status="MISS", etag=etag)


def _gif_response(gif: bytes, cache_status: str, etag: str = "") -> Response:
    headers = {
        "Cache-Control": "public, max-age=30, stale-while-revalidate=30",
        "X-Cache": cache_status,
    }
    if etag:
        headers["ETag"] = etag
    return Response(content=gif, media_type="image/gif", headers=headers)


def _load_static_image(url: str) -> Optional[Image.Image]:
    """Load a local /static/... face image. External URLs are not fetched
    server-side (the cube's promo assets all live under app/static)."""
    if not url:
        return None
    prefix = "/static/"
    if not url.startswith(prefix):
        logger.warning("cube gif: non-static face image_url ignored: %s", url)
        return None
    path = BASE_DIR / "static" / url[len(prefix):]
    if not path.exists():
        logger.warning("cube gif: static face image not found: %s", path)
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        logger.exception("cube gif: failed to open static face %s", path)
        return None


def _placeholder_face(t: CubeTheme) -> Image.Image:
    """Opaque theme-colored fallback used when a face image is unavailable."""
    return Image.new("RGBA", (FACE_W, FACE_H), (*t.bg_top, 255))


def _build_cube_faces(t: CubeTheme) -> List[Image.Image]:
    """Build the four cube sides for the GIF: one promo (static) face plus
    three odds faces, in spin order [promo, odds, odds, odds]. The three odds
    faces show up to three different in-scope matches when available, otherwise
    they repeat the featured match — so the cube always shows odds on 3 sides
    and the promo on 1, exactly once per revolution."""
    with db_session() as session:
        matches = resolve_for_theme(session, t, limit=3)

    def odds_face(match: Optional[Match]) -> Image.Image:
        try:
            return Image.open(
                BytesIO(render_odds_face(match, theme_slug=t.slug))
            ).convert("RGBA")
        except Exception:
            logger.exception("cube gif: odds face render failed theme=%s", t.slug)
            return _placeholder_face(t)

    promo = _load_static_image(t.promo_image_url) or _placeholder_face(t)

    faces: List[Image.Image] = [promo]
    for i in range(3):
        # Cycle through resolved matches; fall back to the featured one (or an
        # empty odds template if nothing is in scope) so all 3 sides render.
        match = matches[i] if i < len(matches) else (matches[0] if matches else None)
        faces.append(odds_face(match))
    return faces


@router.get("/cube/{theme}.gif")
@limiter.limit("120/minute")
def cube_gif(
    theme: str,
    request: Request,
    transparent: str = "0",
    size: int = GIF_SIZE,
    frames: int = GIF_FRAMES,
    seconds: float = GIF_SECONDS_DEFAULT,
    tilt: float = GIF_TILT_DEFAULT,
) -> Response:
    """Animated GIF of the spinning 3D cube for email communications.

    Mirrors /cube/{theme}.png but returns a looping GIF that renders in email
    clients (which run no CSS 3D or JS). Each request bakes in the current
    live odds for the resolved match(es); bytes are cached under
    `cube_gif:{theme}:{size}:{frames}:{ms}:{transparent}` and cleared by the
    same parser-cycle invalidation as the PNG endpoints.

    Query params:
      transparent=1  drop the branded background (1-bit GIF transparency)
      size=NNN       square pixel size (clamped 160–512, default 360)
      frames=NN      rotation frames (clamped 8–48, default 36)
      seconds=N      seconds per full revolution (clamped 1–12, default ~1.9);
                     raise it to slow the spin down
      tilt=NN        downward view angle in degrees (clamped 0–40, default 16);
                     0 = straight-on (flat faces), higher = more top visible
    """
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")

    # Lenient bool so a mistyped URL like `transparent=1?tilt=30` (a stray
    # second '?') is treated as truthy instead of 422-ing the whole request.
    is_transparent = transparent.strip().lower().startswith(("1", "true", "yes", "on"))
    size = max(GIF_SIZE_MIN, min(int(size), GIF_SIZE_MAX))
    frames = max(GIF_FRAMES_MIN, min(int(frames), GIF_FRAMES_MAX))
    seconds = max(GIF_SECONDS_MIN, min(float(seconds), GIF_SECONDS_MAX))
    tilt = max(GIF_TILT_MIN, min(float(tilt), GIF_TILT_MAX))
    # Full 360° loop. GIF timing is 10ms-quantized; round so the spin stays even.
    frame_ms = max(20, int(round(seconds * 1000 / frames / 10)) * 10)

    key = f"cube_gif:{t.slug}:{size}:{frames}:{frame_ms}:{tilt:g}:{int(is_transparent)}"
    cached = png_cache.get(key)
    if cached is not None:
        etag = _etag(cached)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return _gif_response(cached, cache_status="HIT", etag=etag)

    try:
        faces = _build_cube_faces(t)
        gif = render_cube_gif(
            t, faces, size=size, frames=frames, frame_ms=frame_ms,
            transparent=is_transparent, tilt_deg=tilt,
        )
    except Exception:
        logger.exception("cube gif render failed theme=%s", t.slug)
        return Response(
            content=_TRANSPARENT_PNG_1X1,
            media_type="image/png",
            status_code=500,
        )

    png_cache.put(key, gif)
    etag = _etag(gif)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return _gif_response(gif, cache_status="MISS", etag=etag)


@router.get("/cube/{theme}/odds.png")
@limiter.limit("600/minute")
def cube_odds_png(theme: str, request: Request, slot: int = 0) -> Response:
    """Live odds face for a specific match slot.

    `slot` is 0-indexed; default 0 keeps backward compatibility for callers
    that don't know about multi-slot themes. The widget cycles through
    `slot=0,1,2,…` every 20 seconds to rotate the displayed fixture.

    Each slot caches separately (`cube_odds:{theme}:{slot}`) so a pin or
    suppress for slot N only invalidates that slot's cache, not all of them.
    """
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")

    # Clamp slot to the number of match-faces this theme has, so a stale
    # client URL doesn't render slot 9 of a 1-slot theme.
    max_slot = 0
    for face in t.faces:
        if face.kind == "match" and face.match_index > max_slot:
            max_slot = face.match_index
    slot = max(0, min(int(slot or 0), max_slot))

    key = f"cube_odds:{t.slug}:{slot}"
    cached = png_cache.get(key)
    if cached is not None:
        etag = _etag(cached)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return _png_response(cached, cache_status="HIT", etag=etag)

    with db_session() as session:
        matches = resolve_for_theme(session, t, limit=slot + 1)
        match = matches[slot] if slot < len(matches) else None

    try:
        png = render_odds_face(match, theme_slug=t.slug)
    except Exception:
        logger.exception(f"cube odds render failed theme={t.slug} slot={slot}")
        return _png_response(_TRANSPARENT_PNG_1X1, cache_status="ERROR", status_code=500)

    png_cache.put(key, png)
    etag = _etag(png)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return _png_response(png, cache_status="MISS", etag=etag)


# Static face — a fully transparent 420×380 placeholder. The partner cube
# pairs this (the campaign drops its own generic-message art here) with the
# dynamic odds face at /cube/{theme}/odds.png, so we deliberately ship
# transparency rather than a baked-in Jugabet promo image.
_STATIC_FACE_W, _STATIC_FACE_H = 420, 380
_static_face_png: Optional[bytes] = None


def _transparent_static_face() -> bytes:
    global _static_face_png
    if _static_face_png is None:
        buf = BytesIO()
        Image.new("RGBA", (_STATIC_FACE_W, _STATIC_FACE_H), (0, 0, 0, 0)).save(
            buf, format="PNG", optimize=True
        )
        _static_face_png = buf.getvalue()
    return _static_face_png


@router.get("/cube/{theme}/static.png")
@limiter.limit("600/minute")
def cube_static_png(theme: str, request: Request) -> Response:
    """Transparent placeholder for the cube's STATIC face (420×380).

    The campaign overlays its own generic-message image on this face, so we
    serve pure transparency — no Jugabet branding bleeds through. Its companion
    is the dynamic, auto-updating match + odds face at /cube/{theme}/odds.png.
    """
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")
    png = _transparent_static_face()
    etag = _etag(png)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return _png_response(png, cache_status="STATIC", etag=etag)


@router.get("/cube/{theme}", response_class=HTMLResponse)
def cube_html(theme: str, request: Request) -> HTMLResponse:
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")
    return templates.TemplateResponse(
        request,
        "cube/widget.html",
        {"theme": t},
    )


def _match_payload(match: Optional[Match]) -> Optional[Dict[str, Any]]:
    """Serialize a Match into the minimal shape the widget needs.

    Kept small so the data.json response stays cacheable and easy to diff
    on the client. Live status / score are surfaced explicitly so the
    widget can render a LIVE badge without parsing time_raw."""
    if match is None:
        return None
    odds: Dict[str, Optional[str]] = {"p1": None, "draw": None, "p2": None}
    if match.odds_json:
        try:
            o = _json.loads(match.odds_json)
            if isinstance(o, dict):
                for k in ("p1", "draw", "p2"):
                    v = o.get(k)
                    odds[k] = str(v).strip() if v not in (None, "") else None
        except Exception:
            pass
    is_live = (match.status or "").lower() == "live"
    return {
        "event_id": match.event_id,
        "home": (match.home_name or "").strip(),
        "away": (match.away_name or "").strip(),
        "tournament": (match.tournament_name or "").strip(),
        "time": (match.time_raw or "").strip(),
        "status": match.status,
        "is_live": is_live,
        "score": {
            "home": match.home_score,
            "away": match.away_score,
        },
        "odds": odds,
    }


@router.get("/cube/{theme}/data.json")
@limiter.limit("600/minute")
def cube_data(theme: str, request: Request) -> JSONResponse:
    """JSON payload consumed by the rotating widget. Returns one entry
    per match-face declared in the theme, plus theme metadata so the
    client can render brand faces without a second request."""
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")

    # Find the highest match_index any face asks for so we resolve once.
    max_idx = 0
    for face in t.faces:
        if face.kind == "match" and face.match_index > max_idx:
            max_idx = face.match_index
    limit = max(1, max_idx + 1)

    with db_session() as session:
        matches = resolve_for_theme(session, t, limit=limit)

    faces_payload: List[Dict[str, Any]] = []
    for face in t.faces:
        if face.kind == "brand":
            faces_payload.append({
                "kind": "brand",
                "label": face.label,
                "sublabel": face.sublabel,
                "bg": face.bg or _rgb_to_hex(t.bg_top),
                "fg": face.fg or "#ffffff",
                "accent": face.accent or _rgb_to_hex(t.accent),
            })
        elif face.kind == "image":
            faces_payload.append({
                "kind": "image",
                "image_url": face.image_url,
                "bg": face.bg or _rgb_to_hex(t.bg_top),
            })
        else:
            m = matches[face.match_index] if face.match_index < len(matches) else None
            faces_payload.append({
                "kind": "match",
                "match": _match_payload(m),
                "bg": face.bg or _rgb_to_hex(t.bg_top),
                "fg": face.fg or _rgb_to_hex(t.text_primary),
                "accent": face.accent or _rgb_to_hex(t.accent),
            })

    payload = {
        "theme": {
            "slug": t.slug,
            "display_name": t.display_name,
            "badge_text": t.badge_text,
            "subtitle": t.subtitle,
            "bg_top": _rgb_to_hex(t.bg_top),
            "bg_bottom": _rgb_to_hex(t.bg_bottom),
            "accent": _rgb_to_hex(t.accent),
        },
        "faces": faces_payload,
    }
    # Short browser cache; client also polls on its own interval.
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "public, max-age=15, stale-while-revalidate=30"},
    )


@router.get("/cube/{theme}/widget", response_class=HTMLResponse)
def cube_widget(theme: str, request: Request) -> HTMLResponse:
    """Embeddable rotating 3D cube widget. Self-contained HTML page
    (no chrome, no nav) designed to be loaded inside an <iframe> on
    partner sites at sizes like 240×240 or 300×300.

    Usage:
      <iframe src="https://jugabet.cl/cube/ucl/widget"
              width="240" height="240" frameborder="0"
              allowtransparency="true"></iframe>
    """
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")
    return templates.TemplateResponse(
        request,
        "cube/widget.html",
        {"theme": t},
    )


def _rgb_to_hex(rgb: tuple) -> str:
    r, g, b = (int(c) & 0xFF for c in rgb[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def invalidate_all_cubes() -> int:
    """Called by the parser persistence hook after a football cycle so
    cube PNGs reflect fresh odds within one cycle. Returns the number of
    keys dropped.

    Wipes both the main face cache and EVERY per-slot odds cache for each
    registered theme (cube_odds:{slug}:{slot}). The per-slot keys use a
    consistent prefix so a single invalidate_prefix("cube_odds:{slug}")
    call handles all slots without needing to know how many there are.
    """
    n = 0
    for slug, theme in CUBE_THEMES.items():
        png_cache.invalidate(_cache_key(slug))
        png_cache.invalidate_prefix(f"cube_odds:{slug}")
        png_cache.invalidate_prefix(f"cube_gif:{slug}")
        n += 1
    return n
