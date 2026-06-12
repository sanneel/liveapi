"""
Cube override admin — UI + JSON API.

Mirrors `admin_hot.py` structure so the UX is identical: pick a cube,
drag matches into slots, suppress matches, search for more candidates.

Endpoints:
  GET  /admin/cube                                       dashboard (one card per theme)
  GET  /admin/cube/{theme}                               per-cube management page
  GET  /api/admin/cube/{theme}/leaderboard?q=…&limit=N   in-scope matches + override state
  POST /api/admin/cube/{theme}/pin/{event_id}            body: position=0|1|…|null
  POST /api/admin/cube/{theme}/suppress/{event_id}       body: suppress=true|false
  DELETE /api/admin/cube/{theme}/override/{event_id}     wipe both pin + suppress

All mutations:
  * require_role("editor")
  * audit-logged via LogRepository
  * invalidate cube + cube_odds PNG cache for the affected theme
  * rate-limited via slowapi
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
from ..repositories.cube_override_repo import CubeOverrideRepository
from ..repositories.log_repo import LogRepository
from ..repositories.match_repo import MatchRepository
from ..services import png_cache
from ..services.cube_resolver import candidates_for_theme, resolve_for_theme
from ..services.cube_themes import CUBE_THEMES, CubeTheme, get_theme, list_themes
from .public_render import _client_ip

logger = get_logger("app.routes.admin_cube")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

LEADERBOARD_MAX = 100

# Per-cube reorder mutex. Two admins reordering the same cube simultaneously
# would otherwise race the clear-then-set window of the slot map. In single
# worker mode this in-process lock is sufficient.
_REORDER_LOCKS: Dict[str, threading.Lock] = defaultdict(threading.Lock)
_REORDER_TIMEOUT_SEC = 2.0


def _validate_theme(theme_slug: str) -> CubeTheme:
    t = get_theme(theme_slug)
    if t is None:
        raise HTTPException(
            400,
            f"Unknown cube theme. Registered: {', '.join(CUBE_THEMES.keys())}",
        )
    return t


def _max_match_slots(theme: CubeTheme) -> int:
    """How many match-faces this theme has. The pin position must be < this."""
    n = 0
    for face in theme.faces:
        if face.kind == "match" and face.match_index >= n:
            n = face.match_index + 1
    return max(1, n)


def _match_row(
    m: Match,
    *,
    position: Optional[int],
    suppressed: bool,
    in_theme: bool = True,
) -> Dict[str, Any]:
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
        "is_active": bool(m.is_active),
        "is_synthetic": bool(m.is_synthetic),
        "in_theme": in_theme,
        "reason": _reason(m, position, suppressed),
    }


def _reason(m: Match, position: Optional[int], suppressed: bool) -> str:
    if suppressed:
        return "suppressed"
    if position is not None:
        return f"pinned · slot {position + 1}"
    if (m.status or "").lower() == "live":
        return "live now"
    if m.start_time_utc:
        hours = (m.start_time_utc - datetime.utcnow()).total_seconds() / 3600.0
        if 0 <= hours < 6:
            return "starts soon"
        if hours < 0:
            return "auto · started"
    return "auto"


def _invalidate_theme_cache(theme_slug: str) -> None:
    """Drop both render and odds-face caches so the next request renders fresh.

    Uses invalidate_prefix on `cube_odds:{slug}` because the odds endpoint
    keys per-slot (`cube_odds:{slug}:0`, `:1`, `:2` …) and a pin in any
    slot can shift downstream slots. Cheap — bounded by the cube's slot count.
    """
    png_cache.invalidate(f"cube:{theme_slug}")
    png_cache.invalidate_prefix(f"cube_odds:{theme_slug}")
    png_cache.invalidate_prefix(f"cube_gif:{theme_slug}")


# ════════════════════════════════════════════════════════════════════════
# HTML
# ════════════════════════════════════════════════════════════════════════

@router.get("/admin/cube", response_class=HTMLResponse)
def cube_dashboard(request: Request, user: User = Depends(require_login)) -> HTMLResponse:
    """Landing page: list of registered cube themes with quick stats."""
    themes = list_themes()
    rows: List[Dict[str, Any]] = []
    with db_session() as session:
        override_repo = CubeOverrideRepository(session)
        for t in themes:
            in_theme = candidates_for_theme(session, t, limit=LEADERBOARD_MAX)
            overrides = override_repo.list_for_cube(t.slug)
            pinned = sum(1 for o in overrides if o.position is not None)
            suppressed = sum(1 for o in overrides if o.suppress)
            rows.append(
                {
                    "slug": t.slug,
                    "display_name": t.display_name,
                    "sport": t.sport,
                    "in_theme": len(in_theme),
                    "pinned": pinned,
                    "suppressed": suppressed,
                    "slots": _max_match_slots(t),
                    "prefer_live": t.prefer_live,
                }
            )
    return templates.TemplateResponse(
        request,
        "cube/admin_dashboard.html",
        {
            "active_page": "cube",
            "current_user": user,
            "cube_rows": rows,
        },
    )


@router.get("/admin/cube/{theme}", response_class=HTMLResponse)
def cube_admin_detail(
    request: Request,
    theme: str,
    user: User = Depends(require_login),
) -> HTMLResponse:
    t = _validate_theme(theme)
    return templates.TemplateResponse(
        request,
        "cube/admin_detail.html",
        {
            "active_page": "cube",
            "current_user": user,
            "theme": t,
            "slot_count": _max_match_slots(t),
            "leaderboard_max": LEADERBOARD_MAX,
        },
    )


# ════════════════════════════════════════════════════════════════════════
# JSON
# ════════════════════════════════════════════════════════════════════════

@router.get("/api/admin/cube/{theme}/leaderboard")
def api_cube_leaderboard(
    theme: str,
    q: Optional[str] = None,
    limit: int = 50,
    user: User = Depends(require_login),
) -> Dict[str, Any]:
    """Return:
      * `top`            current resolver output for this cube (slot 1..N)
      * `candidates`     every in-theme active match (drag pool)
      * `suppressed`     in-theme matches the admin has hidden from this cube
      * `search_results` global match search (cross-tournament, cross-sport)
                         when `q` is given — for adding a match that's NOT in
                         the theme yet (the override system can still pin it;
                         the resolver honors pins regardless of theme filter).
      * `slot_count`     how many match-faces this cube has
    """
    t = _validate_theme(theme)
    limit = max(1, min(int(limit or 50), LEADERBOARD_MAX))
    slot_count = _max_match_slots(t)

    with db_session() as session:
        match_repo = MatchRepository(session)
        override_repo = CubeOverrideRepository(session)

        # 1. The current cube output (resolver-decided slots).
        top_matches = resolve_for_theme(session, t, limit=slot_count)
        top_ids = [m.event_id for m in top_matches]
        top_positions = {m.event_id: i for i, m in enumerate(top_matches)}
        pinned_map = override_repo.all_pinned(t.slug)  # {slot: eid}
        suppressed_set = override_repo.all_suppressed(t.slug)
        top_rows = []
        for i, m in enumerate(top_matches):
            pinned_here = next(
                (slot for slot, eid in pinned_map.items() if eid == m.event_id),
                None,
            )
            top_rows.append(
                _match_row(
                    m,
                    position=pinned_here,
                    suppressed=m.event_id in suppressed_set,
                )
            )

        # 2. All in-theme candidates (drag pool).
        candidates = candidates_for_theme(session, t, limit=limit)
        candidate_ids = [m.event_id for m in candidates]
        candidate_positions = override_repo.positions_for(t.slug, candidate_ids)
        candidate_suppressed = override_repo.suppressed_for(t.slug, candidate_ids)
        candidate_rows = []
        for m in candidates:
            if m.event_id in top_positions:
                # Already shown in top; don't duplicate in the candidate pool.
                continue
            candidate_rows.append(
                _match_row(
                    m,
                    position=candidate_positions.get(m.event_id),
                    suppressed=m.event_id in candidate_suppressed,
                )
            )

        # 3. Suppressed-but-known bucket so admins can un-suppress without
        # hunting.
        suppressed_rows: List[Dict[str, Any]] = []
        for m in candidates:
            if m.event_id in candidate_suppressed:
                suppressed_rows.append(
                    _match_row(
                        m,
                        position=candidate_positions.get(m.event_id),
                        suppressed=True,
                    )
                )

        # 4. Free-text search RESTRICTED TO IN-THEME matches.
        #
        # We deliberately bypass match_repo.search's SQL ILIKE here because:
        #   * SQLite's LIKE is reliable case-insensitive only for ASCII —
        #     "Checa" vs "checa" works, but "Á" vs "á" / "ñ" vs "Ñ" fail
        #     in some collations. "República" searches that "should" work
        #     came back empty depending on the collation in effect.
        #   * Operators expect "rep" to find "República", "arge" to find
        #     "Argentina", "brazil arg" (two tokens, either order) to find
        #     Brazil vs Argentina — none of which a single LIKE handles
        #     well.
        #
        # Fix: pull the entire in-theme candidate pool (already small —
        # bounded by candidates_for_theme), normalize team + tournament
        # names with the same NFKD/diacritic-strip used elsewhere, and
        # do a multi-token substring AND-match in Python.
        search_rows: List[Dict[str, Any]] = []
        if q and q.strip():
            from ..utils.quality import _normalize as _norm
            tokens = [tok for tok in _norm(q).split() if tok]
            if tokens:
                # Pull a generous in-theme pool: live + prematch, no SQL
                # text filter (theme is the filter; we then sieve by tokens).
                pool = candidates_for_theme(session, t, limit=500)
                def _haystack(m: Match) -> str:
                    return _norm(
                        " ".join(
                            filter(
                                None,
                                [
                                    m.home_name,
                                    m.away_name,
                                    m.tournament_name,
                                ],
                            )
                        )
                    )
                matched: List[Match] = []
                for m in pool:
                    hay = _haystack(m)
                    if all(tok in hay for tok in tokens):
                        matched.append(m)
                    if len(matched) >= limit:
                        break

                result_ids = [m.event_id for m in matched]
                search_positions = override_repo.positions_for(t.slug, result_ids)
                search_suppressed = override_repo.suppressed_for(t.slug, result_ids)
                for m in matched:
                    if m.event_id in top_positions:
                        continue
                    search_rows.append(
                        _match_row(
                            m,
                            position=search_positions.get(m.event_id),
                            suppressed=m.event_id in search_suppressed,
                            in_theme=True,
                        )
                    )

    return {
        "theme": t.slug,
        "display_name": t.display_name,
        "slot_count": slot_count,
        "top": top_rows,
        "candidates": candidate_rows,
        "suppressed": suppressed_rows,
        "search_results": search_rows,
    }


@router.post("/api/admin/cube/{theme}/pin/{event_id}")
@limiter.limit("60/minute")
def api_cube_pin(
    theme: str,
    event_id: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Pin one event to a specific slot in this cube (or unpin with position=null).

    If `position` collides with an existing pin, the previous occupant is
    bumped back to auto-rank. Slots are 0-indexed in the API to match
    CubeTheme.faces[i].match_index; the UI translates to 1-indexed labels.
    """
    t = _validate_theme(theme)
    event_id = str(event_id or "").strip()
    if not event_id:
        raise HTTPException(400, "event_id required")
    slot_count = _max_match_slots(t)

    raw_pos = body.get("position", None)
    position: Optional[int]
    if raw_pos is None:
        position = None
    else:
        try:
            position = int(raw_pos)
        except (TypeError, ValueError):
            raise HTTPException(400, "position must be 0..N-1 or null")
        if not (0 <= position < slot_count):
            raise HTTPException(
                400, f"position must be 0..{slot_count - 1} or null"
            )

    lock = _REORDER_LOCKS[t.slug]
    if not lock.acquire(timeout=_REORDER_TIMEOUT_SEC):
        raise HTTPException(
            409, f"Another pin on cube {t.slug} is in progress; retry shortly."
        )
    displaced_count = 0
    try:
        with db_session() as session:
            match_repo = MatchRepository(session)
            match = match_repo.find_by_event_id(event_id)
            if match is None:
                raise HTTPException(404, "Match not in DB")
            override_repo = CubeOverrideRepository(session)
            if position is not None:
                # Defensive: clear ANY other event currently pinned to this
                # position before assigning the new pin. event_at_position
                # only returns one row; if rapid drags or a prior bug left
                # duplicates, those orphan rows would silently hold the
                # slot forever and the resolver would render the wrong
                # match. clear_position_at_slot guarantees a clean slot.
                displaced_count = override_repo.clear_position_at_slot(
                    t.slug, position, except_event_id=event_id
                )
            override_repo.set_position(t.slug, event_id, position, by=user.username)
            # Pinning implies un-suppressing — otherwise the pin would render
            # nothing because the resolver would still drop the event.
            if position is not None:
                override_repo.set_suppress(
                    t.slug, event_id, False, by=user.username
                )
            LogRepository(session).record(
                "cube.pin",
                username=user.username,
                target=t.slug,
                payload={
                    "event_id": event_id,
                    "position": position,
                    "displaced_count": displaced_count,
                },
                ip=_client_ip(request),
            )
    finally:
        lock.release()

    _invalidate_theme_cache(t.slug)
    return {
        "ok": True,
        "cube": t.slug,
        "event_id": event_id,
        "position": position,
        "displaced_count": displaced_count,
    }


@router.post("/api/admin/cube/{theme}/reorder")
@limiter.limit("60/minute")
def api_cube_reorder(
    theme: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Pin several events to specific slots atomically — used for slot↔slot
    SWAPS.

    Body: ``{"pins": [{"event_id": "...", "position": 0}, ...]}``.

    Doing a swap as two sequential /pin calls is racy: the first pin's
    `clear_position_at_slot` bumps the other event to auto before the second
    pin lands, so the two never cleanly trade places. Here every target slot
    is vacated first, then every event is pinned, inside one locked
    transaction. Slots NOT listed keep their current pin/auto state, so
    untouched slots still auto-rank.
    """
    t = _validate_theme(theme)
    slot_count = _max_match_slots(t)

    raw_pins = body.get("pins")
    if not isinstance(raw_pins, list) or not raw_pins:
        raise HTTPException(400, "pins must be a non-empty list")
    if len(raw_pins) > slot_count:
        raise HTTPException(400, f"at most {slot_count} pins")

    pins: List[Any] = []  # (event_id, position) after validation
    seen_positions: set = set()
    seen_events: set = set()
    for p in raw_pins:
        eid = str((p or {}).get("event_id") or "").strip()
        if not eid:
            raise HTTPException(400, "each pin needs an event_id")
        try:
            pos = int(p.get("position"))
        except (TypeError, ValueError):
            raise HTTPException(400, "each pin needs an integer position")
        if not (0 <= pos < slot_count):
            raise HTTPException(400, f"position must be 0..{slot_count - 1}")
        if pos in seen_positions:
            raise HTTPException(400, "two pins target the same slot")
        if eid in seen_events:
            raise HTTPException(400, "the same event is pinned twice")
        seen_positions.add(pos)
        seen_events.add(eid)
        pins.append((eid, pos))

    lock = _REORDER_LOCKS[t.slug]
    if not lock.acquire(timeout=_REORDER_TIMEOUT_SEC):
        raise HTTPException(
            409, f"Another change on cube {t.slug} is in progress; retry shortly."
        )
    try:
        with db_session() as session:
            match_repo = MatchRepository(session)
            override_repo = CubeOverrideRepository(session)
            for eid, _pos in pins:
                if match_repo.find_by_event_id(eid) is None:
                    raise HTTPException(404, f"Match not in DB: {eid}")
            # Vacate every target slot first (so a swap can't leave two events
            # sharing one slot), then assign the new pins.
            for eid, pos in pins:
                override_repo.clear_position_at_slot(t.slug, pos, except_event_id=eid)
            for eid, pos in pins:
                override_repo.set_position(t.slug, eid, pos, by=user.username)
                # Pinning implies un-suppressing, same as the single-pin path.
                override_repo.set_suppress(t.slug, eid, False, by=user.username)
            LogRepository(session).record(
                "cube.reorder",
                username=user.username,
                target=t.slug,
                payload={"pins": [{"event_id": e, "position": p} for e, p in pins]},
                ip=_client_ip(request),
            )
    finally:
        lock.release()

    _invalidate_theme_cache(t.slug)
    return {
        "ok": True,
        "cube": t.slug,
        "pins": [{"event_id": e, "position": p} for e, p in pins],
    }


@router.post("/api/admin/cube/{theme}/suppress/{event_id}")
@limiter.limit("60/minute")
def api_cube_suppress(
    theme: str,
    event_id: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    t = _validate_theme(theme)
    event_id = str(event_id or "").strip()
    if not event_id:
        raise HTTPException(400, "event_id required")
    suppress = bool(body.get("suppress"))
    with db_session() as session:
        match = MatchRepository(session).find_by_event_id(event_id)
        if match is None:
            raise HTTPException(404, "Match not in DB")
        override_repo = CubeOverrideRepository(session)
        override_repo.set_suppress(t.slug, event_id, suppress, by=user.username)
        # Suppressing also drops the event out of any slot pin.
        if suppress:
            override_repo.set_position(t.slug, event_id, None, by=user.username)
        LogRepository(session).record(
            "cube.suppress",
            username=user.username,
            target=t.slug,
            payload={"event_id": event_id, "suppress": suppress},
            ip=_client_ip(request),
        )
    _invalidate_theme_cache(t.slug)
    return {"ok": True, "cube": t.slug, "event_id": event_id, "suppress": suppress}


@router.delete("/api/admin/cube/{theme}/override/{event_id}")
@limiter.limit("60/minute")
def api_cube_clear_override(
    theme: str,
    event_id: str,
    request: Request,
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    t = _validate_theme(theme)
    event_id = str(event_id or "").strip()
    with db_session() as session:
        override_repo = CubeOverrideRepository(session)
        removed = override_repo.clear(t.slug, event_id)
        LogRepository(session).record(
            "cube.clear",
            username=user.username,
            target=t.slug,
            payload={"event_id": event_id, "removed": removed},
            ip=_client_ip(request),
        )
    _invalidate_theme_cache(t.slug)
    return {"ok": removed, "cube": t.slug, "event_id": event_id}


@router.delete("/api/admin/cube/{theme}/overrides")
@limiter.limit("10/minute")
def api_cube_reset_all(
    theme: str,
    request: Request,
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Wipe EVERY override row for this cube. Cube reverts to fully
    auto-ranked. Use this to recover from a confused state after
    experimenting with pins."""
    t = _validate_theme(theme)
    with db_session() as session:
        override_repo = CubeOverrideRepository(session)
        removed = override_repo.clear_all_for_cube(t.slug)
        LogRepository(session).record(
            "cube.reset_all",
            username=user.username,
            target=t.slug,
            payload={"removed": removed},
            ip=_client_ip(request),
        )
    _invalidate_theme_cache(t.slug)
    return {"ok": True, "cube": t.slug, "removed": removed}
