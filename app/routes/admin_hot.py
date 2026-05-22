"""
Hot override admin — UI + API.

  GET  /admin/hot                                     dashboard (8 sport cards)
  GET  /api/admin/hot/{sport}/leaderboard?limit=50    ranked list + override state
  PUT  /api/admin/hot/{sport}/reorder                 body: event_ids=[...] (slot 1..N)
  POST /api/admin/hot/{sport}/suppress/{event_id}     body: suppress=true|false
  DELETE /api/admin/hot/{sport}/override/{event_id}   clear all overrides for one match

All mutations:
  - audit log entry via LogRepository
  - call _cache_invalidate_sport(sport) and png_cache.invalidate_prefix(...)
    so /r/{slug}.png and /hot/{sport}.png pick up the change within ~1 s.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Match, User
from ..repositories.hot_boost_repo import HotBoostRepository
from ..repositories.log_repo import LogRepository
from ..repositories.match_repo import MatchRepository
from ..services import png_cache
from ..services.hot_engine import HotEngine
from .public_render import _cache_invalidate_sport, _client_ip

logger = get_logger("app.routes.admin_hot")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

VALID_SPORTS = (
    "football", "basketball", "tennis", "cybersport",
    "fights", "ufc", "mma", "boxing",
)
TOP_N = 10
LEADERBOARD_MAX = 50

# Per-sport mutex for the reorder write path. Two admins reordering the
# same sport simultaneously would otherwise step on each other's slot map
# inside the clear-then-set window. Single-worker assumption keeps this
# in-process lock sufficient.
_REORDER_LOCKS: Dict[str, threading.Lock] = defaultdict(threading.Lock)
_REORDER_TIMEOUT_SEC = 2.0


def _validate_sport(sport: str) -> str:
    sport = (sport or "").strip().lower()
    if sport not in VALID_SPORTS:
        raise HTTPException(400, f"Unknown sport. Use one of: {', '.join(VALID_SPORTS)}")
    return sport


def _invalidate_sport_caches(sport: str) -> None:
    """Drop every cached PNG that could now be stale for this sport."""
    _cache_invalidate_sport(sport)
    png_cache.invalidate_prefix(f"hot:{sport}")


def _match_row(m: Match, position: Optional[int], suppressed: bool) -> Dict[str, Any]:
    return {
        "event_id": m.event_id,
        "sport": m.sport,
        "status": m.status,
        "home_name": m.home_name,
        "away_name": m.away_name,
        "tournament_name": m.tournament_name,
        "time_raw": m.time_raw,
        "start_time_utc": m.start_time_utc.isoformat() if m.start_time_utc else None,
        "position": position,
        "suppressed": suppressed,
    }


# ═════════════════════════════════════════════════════════════════════
# HTML
# ═════════════════════════════════════════════════════════════════════

@router.get("/admin/hot", response_class=HTMLResponse)
def hot_dashboard(request: Request, user: User = Depends(require_login)) -> HTMLResponse:
    """Landing: simple list of sports + Browse links to per-sport pages."""
    with db_session() as session:
        match_repo = MatchRepository(session)
        boost_repo = HotBoostRepository(session)
        # Cheap per-sport summary: active count + pinned/suppressed counts.
        rows: List[Dict[str, Any]] = []
        for sport in VALID_SPORTS:
            if sport == "fights":
                sports_in_scope = ("boxing", "mma", "ufc")
            else:
                sports_in_scope = (sport,)
            active: List[Match] = []
            for s in sports_in_scope:
                active.extend(match_repo.find_active_by_sport(s))
            ids = [m.event_id for m in active]
            pinned = len(boost_repo.positions_for(ids)) if ids else 0
            suppressed = len(boost_repo.suppressed_for(ids)) if ids else 0
            rows.append({
                "sport": sport,
                "active": len(active),
                "pinned": pinned,
                "suppressed": suppressed,
            })
    return templates.TemplateResponse(
        request,
        "hot/dashboard.html",
        {
            "active_page": "hot",
            "current_user": user,
            "sport_rows": rows,
            "top_n": TOP_N,
        },
    )


@router.get("/admin/hot/{sport}", response_class=HTMLResponse)
def hot_sport_detail(
    request: Request,
    sport: str,
    user: User = Depends(require_login),
) -> HTMLResponse:
    sport = _validate_sport(sport)
    return templates.TemplateResponse(
        request,
        "hot/sport.html",
        {
            "active_page": "hot",
            "current_user": user,
            "sport": sport,
            "top_n": TOP_N,
            "leaderboard_max": LEADERBOARD_MAX,
        },
    )


# ═════════════════════════════════════════════════════════════════════
# JSON / HTMX
# ═════════════════════════════════════════════════════════════════════

@router.get("/api/admin/hot/{sport}/leaderboard")
def api_leaderboard(
    sport: str,
    q: Optional[str] = None,
    limit: int = 20,
    user: User = Depends(require_login),
) -> Dict[str, Any]:
    """Return the engine's ordered hot list plus every active candidate
    not currently shown — together that's the "browsing" view the admin
    UI drags from."""
    sport = _validate_sport(sport)
    limit = max(1, min(int(limit or 20), LEADERBOARD_MAX))

    with db_session() as session:
        engine = HotEngine(session, sport)
        top = engine.resolve(limit)
        match_repo = MatchRepository(session)
        if sport == "fights":
            sports_in_scope = ("boxing", "mma", "ufc")
        else:
            sports_in_scope = (sport,)
        # Admin Browse must surface every active candidate, not only those the
        # scorer accepts. The scorer filters on 1x2/odds/horizon for the PNG
        # render path; admins still need to pin or suppress events that fall
        # outside those filters. Fall back to raw active rows when the engine
        # returns nothing.
        if not top:
            raw: List[Match] = []
            for s in sports_in_scope:
                raw.extend(match_repo.find_active_by_sport(s))
            raw.sort(
                key=lambda m: m.last_updated_at or datetime.min,
                reverse=True,
            )
            top = raw[:limit]
        boost_repo = HotBoostRepository(session)
        top_ids = [m.event_id for m in top]
        positions = boost_repo.positions_for(top_ids)
        suppressed_top = boost_repo.suppressed_for(top_ids)

        top_rows = []
        for idx, m in enumerate(top, start=1):
            top_rows.append(_match_row(m, position=positions.get(m.event_id), suppressed=False))

        # Suppressed-but-known matches go in a separate bucket so admins
        # can un-suppress without hunting. They're hidden from the auto cut.
        suppressed_rows: List[Dict[str, Any]] = []
        all_active: List[Match] = []
        for s in sports_in_scope:
            all_active.extend(match_repo.find_active_by_sport(s))
        all_ids = [m.event_id for m in all_active]
        suppressed_set = boost_repo.suppressed_for(all_ids)
        for m in all_active:
            if m.event_id in suppressed_set:
                suppressed_rows.append(_match_row(m, position=None, suppressed=True))

        search_rows: List[Dict[str, Any]] = []
        if q and q.strip():
            top_10_ids = set(top_ids[:10])
            search_matches = []
            if sport == "fights":
                for s in ("boxing", "mma", "ufc"):
                    search_matches.extend(match_repo.search(query=q.strip(), sport=s, limit=20))
                # Sort by hot_score desc, last_updated_at desc
                search_matches.sort(key=lambda m: (m.hot_score if m.hot_score is not None else -999999, m.last_updated_at or datetime.min), reverse=True)
                search_matches = search_matches[:20]
            else:
                search_matches = match_repo.search(query=q.strip(), sport=sport, limit=20)
            
            for m in search_matches:
                if m.event_id not in top_10_ids:
                    search_rows.append(_match_row(m, position=positions.get(m.event_id), suppressed=m.event_id in suppressed_set))

    return {
        "sport": sport,
        "top_n": TOP_N,
        "limit": limit,
        "top": top_rows,
        "suppressed": suppressed_rows,
        "search_results": search_rows,
    }


@router.put("/api/admin/hot/{sport}/reorder")
@limiter.limit("60/minute")
def api_reorder(
    sport: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Lock the top-N order: slot i = event_ids[i-1].

    Serialized per-sport via an in-process lock. Concurrent reorder requests
    for the same sport would otherwise race in the clear-then-set window and
    silently overwrite each other's slot map.
    """
    sport = _validate_sport(sport)
    raw_ids: List[str] = list(body.get("event_ids") or [])
    event_ids = [str(e).strip() for e in raw_ids if str(e).strip()]
    if not event_ids:
        raise HTTPException(400, "event_ids required")
    if len(event_ids) > TOP_N:
        raise HTTPException(400, f"Cannot pin more than top {TOP_N} slots.")
    if len(event_ids) != len(set(event_ids)):
        raise HTTPException(400, "Duplicate event_ids are not allowed.")

    lock = _REORDER_LOCKS[sport]
    if not lock.acquire(timeout=_REORDER_TIMEOUT_SEC):
        raise HTTPException(
            409,
            f"Another reorder for {sport} is in progress; retry in a moment.",
        )
    try:
        with db_session() as session:
            match_repo = MatchRepository(session)
            matches = match_repo.find_by_event_ids(event_ids)
            by_id = {m.event_id: m for m in matches}
            missing = [e for e in event_ids if e not in by_id]
            if missing:
                raise HTTPException(400, f"Unknown event_ids: {missing[:3]}")

            # Validate sport alignment. For 'fights' allow any of boxing/mma/ufc.
            if sport == "fights":
                allowed_sports = {"boxing", "mma", "ufc"}
            else:
                allowed_sports = {sport}
            wrong = [e for e in event_ids if by_id[e].sport not in allowed_sports]
            if wrong:
                raise HTTPException(400, f"event_ids not in sport {sport}: {wrong[:3]}")

            # Reset every existing position for this sport, then write the new order.
            if sport == "fights":
                sports_in_scope = ("boxing", "mma", "ufc")
            else:
                sports_in_scope = (sport,)
            all_active: List[Match] = []
            for s in sports_in_scope:
                all_active.extend(match_repo.find_active_by_sport(s))
            boost_repo = HotBoostRepository(session)
            boost_repo.clear_positions_for_events([m.event_id for m in all_active])
            for slot, eid in enumerate(event_ids, start=1):
                boost_repo.set_position(eid, slot, by=user.username)

            LogRepository(session).record(
                "hot.reorder",
                username=user.username,
                target=sport,
                payload={"event_ids": event_ids},
                ip=_client_ip(request),
            )

        _invalidate_sport_caches(sport)
        return {"ok": True, "sport": sport, "count": len(event_ids)}
    finally:
        lock.release()


@router.post("/api/admin/hot/{sport}/suppress/{event_id}")
@limiter.limit("60/minute")
def api_set_suppress(
    sport: str,
    event_id: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    sport = _validate_sport(sport)
    event_id = str(event_id).strip()
    if not event_id:
        raise HTTPException(400, "event_id required")
    suppress = bool(body.get("suppress"))

    with db_session() as session:
        match = MatchRepository(session).find_by_event_id(event_id)
        if match is None:
            raise HTTPException(404, "Match not in DB")
        boost_repo = HotBoostRepository(session)
        boost_repo.set_suppress(event_id, suppress, by=user.username)
        # Suppressing an event also drops it out of the slot map.
        if suppress:
            boost_repo.set_position(event_id, None, by=user.username)
        LogRepository(session).record(
            "hot.suppress",
            username=user.username,
            target=sport,
            payload={"event_id": event_id, "suppress": suppress},
            ip=_client_ip(request),
        )

    _invalidate_sport_caches(sport)
    return {"ok": True, "event_id": event_id, "suppress": suppress}


@router.delete("/api/admin/hot/{sport}/override/{event_id}")
@limiter.limit("60/minute")
def api_clear_override(
    sport: str,
    event_id: str,
    request: Request,
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Wipe every override row for this event (position + suppress)."""
    sport = _validate_sport(sport)
    event_id = str(event_id).strip()
    with db_session() as session:
        boost_repo = HotBoostRepository(session)
        removed = boost_repo.clear(event_id)
        LogRepository(session).record(
            "hot.clear",
            username=user.username,
            target=sport,
            payload={"event_id": event_id, "removed": removed},
            ip=_client_ip(request),
        )
    _invalidate_sport_caches(sport)
    return {"ok": removed, "event_id": event_id}
