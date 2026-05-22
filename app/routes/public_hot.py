"""
Public HOT endpoints (Phase A).

  GET /hot                      → 302 redirect to /hot/football
  GET /hot/{sport}              → JSON feed (sorted matches, override-applied)
  GET /hot/{sport}.png          → PNG snapshot of /hot/{sport}

Sport scope is independent — football scoring does not bleed into tennis.
PNG cached for `public_cache_seconds`; JSON not cached server-side (cheap
DB read + scorer run; revisit if hot-path load proves otherwise).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Match
from ..render import render_for_sport
from ..services import png_cache
from ..services.hot_engine import HotEngine

logger = get_logger("app.routes.public_hot")

router = APIRouter()

VALID_SPORTS = (
    "football", "basketball", "tennis", "cybersport",
    "fights", "ufc", "mma", "boxing",
)
DEFAULT_LIMIT = 5
MAX_LIMIT = 20

# 1×1 transparent PNG (mirrors public_render.TRANSPARENT_PNG_1X1)
TRANSPARENT_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _validate_sport(sport: str) -> str:
    sport = (sport or "").strip().lower()
    if sport not in VALID_SPORTS:
        raise HTTPException(404, "Unknown sport")
    return sport


def _validate_limit(limit: int) -> int:
    try:
        n = int(limit or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        n = DEFAULT_LIMIT
    return max(1, min(n, MAX_LIMIT))


def _match_to_json(m: Match) -> Dict[str, Any]:
    return {
        "event_id": m.event_id,
        "sport": m.sport,
        "status": m.status,
        "home": {"name": m.home_name, "slug": m.home_slug, "logo": m.home_logo},
        "away": {"name": m.away_name, "slug": m.away_slug, "logo": m.away_logo},
        "tournament": m.tournament_name,
        "time": {
            "raw": m.time_raw,
            "utc": m.start_time_utc.isoformat() if m.start_time_utc else None,
        },
        "score": {"home": m.home_score, "away": m.away_score},
        "href": m.href,
    }


# ──────────────────────────────────────────────────────────────────────
# Route registration order matters: `/hot/{sport}` greedily matches
# `/hot/football.png` (sport="football.png") if registered first, so the
# more-specific `.png` route MUST come before the JSON route.

@router.get("/hot")
def hot_root() -> Response:
    """Redirect bare /hot to the default sport."""
    return RedirectResponse("/hot/football", status_code=302)


@router.get("/hot/{sport}.png")
@limiter.limit("600/minute")
def hot_png(sport: str, request: Request, limit: int = DEFAULT_LIMIT) -> Response:
    sport = _validate_sport(sport)
    n = _validate_limit(limit)
    cache_key = f"hot:{sport}:{n}"

    cached = png_cache.get(cache_key)
    if cached is not None:
        etag = _etag(cached)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return _png_response(cached, cache_status="HIT", etag=etag)

    with db_session() as session:
        matches = HotEngine(session, sport).resolve(n)
        events: List[Dict[str, Any]] = [m.to_event_dict() for m in matches]

    if not events:
        # No matches for this sport — return 1×1 transparent (not an error).
        return _png_response(TRANSPARENT_PNG_1X1, cache_status="EMPTY")

    try:
        png = render_for_sport(sport, events)
    except Exception:
        logger.exception(f"hot_png render failed sport={sport}")
        return _png_response(TRANSPARENT_PNG_1X1, cache_status="ERROR", status_code=500)

    png_cache.put(cache_key, png)
    etag = _etag(png)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return _png_response(png, cache_status="MISS", etag=etag)


@router.get("/hot/{sport}")
@limiter.limit("300/minute")
def hot_json(sport: str, request: Request, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    sport = _validate_sport(sport)
    n = _validate_limit(limit)
    with db_session() as session:
        matches = HotEngine(session, sport).resolve(n)
        payload = {
            "sport": sport,
            "count": len(matches),
            "matches": [_match_to_json(m) for m in matches],
        }
    return payload


def _etag(png: bytes) -> str:
    return '"' + hashlib.md5(png).hexdigest() + '"'


def _png_response(
    png: bytes,
    cache_status: str,
    status_code: int = 200,
    etag: str = "",
) -> Response:
    # ARCH-04: short browser-side cache with stale-while-revalidate so a
    # burst of email-open requests doesn't all hit the renderer. Server-side
    # png_cache is still authoritative; ETag enables 304 short-circuit.
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
