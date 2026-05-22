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
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Match
from ..render.cube_render import render_cube_png
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
        "Cache-Control": "public, max-age=30, stale-while-revalidate=60",
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


@router.get("/cube/{theme}", response_class=HTMLResponse)
def cube_html(theme: str, request: Request) -> HTMLResponse:
    """HTML preview page. Auto-refreshes the PNG so the displayed image
    tracks the latest parse cycle without the user reloading."""
    t = get_theme(theme)
    if t is None:
        raise HTTPException(404, f"Unknown cube theme: {theme}")
    return templates.TemplateResponse(
        request,
        "cube/theme.html",
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
    keys dropped."""
    n = 0
    for slug in CUBE_THEMES:
        png_cache.invalidate(_cache_key(slug))
        n += 1
    return n
