"""
Public CLUB endpoint.

  GET /club/{slug}.png  -> PNG snapshot of the club's next match

Clubs are a pure pass-through to the campaign renderer: when the parser
sees an upcoming match for this slug, we render it with `render_for_sport`
— exactly the same visual as `/r/{slug}.png`. When no match exists, we
return a 1×1 transparent PNG (just like an empty campaign). There is no
club-specific fallback design, no CTA, no HTML page.

The only club-side mutation we apply to the event before rendering is the
`hide_opponent_logo` flag (per club, admin-toggled): if set, we wipe the
opposing team's logo so fan-base creatives don't carry a rival's mark.
"""

from __future__ import annotations

import re
from typing import List

from fastapi import APIRouter, HTTPException, Request, Response

from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Match
from ..render import render_for_sport
from ..repositories.club_repo import ClubRepository
from ..services import png_cache
from ..services.club_resolver import ClubResolver

logger = get_logger("app.routes.public_club")

router = APIRouter()

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}$")

TRANSPARENT_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _validate_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(404, "Club not found")
    return slug


@router.get("/club/{slug}.png")
@limiter.limit("600/minute")
def club_png(slug: str, request: Request) -> Response:
    slug = _validate_slug(slug)
    cache_key = f"club:{slug}"

    cached = png_cache.get(cache_key)
    if cached is not None:
        return _png_response(cached, cache_status="HIT")

    with db_session() as session:
        club = ClubRepository(session).find_by_slug(slug)
        if club is None:
            return _png_response(TRANSPARENT_PNG_1X1, cache_status="MISS", status_code=404)
        matches: List[Match] = ClubResolver(session, slug).resolve(limit=1)
        match = matches[0] if matches else None
        hide_opponent_logo = bool(getattr(club, "hide_opponent_logo", False))
        if match is not None and slug not in (match.home_slug, match.away_slug):
            # Resolver query filters on (home_slug == slug OR away_slug == slug),
            # so the slug MUST be on one side. Anything else means data
            # corruption — fall through to empty rather than render the wrong
            # opponent.
            logger.warning(
                f"club_png: data corruption — slug={slug!r} matched event "
                f"{match.event_id} (home={match.home_slug!r} away={match.away_slug!r}); "
                f"falling back to empty PNG."
            )
            match = None

        if match is None:
            # No upcoming match → empty PNG. Same contract as an empty
            # campaign. Cache the empty result so a quiet slug doesn't
            # re-query the DB every request.
            png_cache.put(cache_key, TRANSPARENT_PNG_1X1)
            return _png_response(TRANSPARENT_PNG_1X1, cache_status="EMPTY")

        sport = match.sport
        event = match.to_event_dict()
        if hide_opponent_logo:
            # Wipe whichever side is the opponent so the renderer draws
            # nothing for it. The shared sport renderers handle null logos.
            opponent_side = "away" if match.home_slug == slug else "home"
            opp = event.get("competitors", {}).get(opponent_side)
            if isinstance(opp, dict):
                opp["logo"] = None
        events = [event]

    try:
        png = render_for_sport(sport, events)
    except Exception:
        logger.exception(f"club_png render failed slug={slug}")
        return _png_response(TRANSPARENT_PNG_1X1, cache_status="ERROR", status_code=500)

    png_cache.put(cache_key, png)
    return _png_response(png, cache_status="MISS")


def _png_response(png: bytes, cache_status: str, status_code: int = 200) -> Response:
    return Response(
        content=png,
        media_type="image/png",
        status_code=status_code,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Cache": cache_status,
        },
    )
