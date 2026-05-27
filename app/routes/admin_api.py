"""
JSON endpoints used by the admin UI.

All under /api/admin/* — these are NOT public render endpoints.
Phase 3 will protect these with auth.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..repositories.match_repo import MatchRepository

router = APIRouter(prefix="/api/admin", tags=["admin-api"], dependencies=[Depends(require_login)])


@router.get("/matches/search")
def search_matches(
    q: str = Query("", description="Free-text query across team/tournament"),
    sport: str = Query("", description="football | basketball | tennis | ..."),
    status: str = Query("", description="live | prematch | (empty for both)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False, description="Include matches not currently in the feed"),
    include_synthetic: bool = Query(False, description="Include virtual/replay/esports inventory"),
    _user=Depends(require_role("editor")),
) -> Dict[str, Any]:
    """Searchable match list for the picker. Editor-gated because it leaks
    every tournament/team name in the DB; the router-wide `require_login`
    is not enough."""
    with db_session() as session:
        repo = MatchRepository(session)
        results = repo.search(
            query=q or None,
            sport=sport or None,
            status=status or None,
            limit=limit,
            offset=offset,
            include_inactive=include_inactive,
            include_synthetic=include_synthetic,
        )
        return {
            "count": len(results),
            "matches": [m.to_event_dict() for m in results],
        }


@router.get("/matches/{event_id}")
def get_match(event_id: str) -> Dict[str, Any]:
    """Get a single match by event_id."""
    with db_session() as session:
        repo = MatchRepository(session)
        m = repo.find_by_event_id(event_id)
        if m is None:
            return {"found": False}
        return {"found": True, "match": m.to_event_dict()}


@router.get("/diagnostics")
def diagnostics() -> Dict[str, Any]:
    """Lightweight diagnostics for the admin dashboard.

    Surfaces the logo cache (so QA can see which CDN logos failed) and the
    feed-health snapshot from the parser. Used by the dashboard "Operational
    visibility" card.
    """
    from ..render.logos import cache_stats as _logo_stats

    out: Dict[str, Any] = {"logo_cache": _logo_stats()}

    try:
        import server as _server  # type: ignore

        feed_health = getattr(_server, "feed_health_snapshot", None)
        if callable(feed_health):
            out["feeds"] = feed_health()
    except Exception:
        pass

    return out


@router.get("/stats")
def stats() -> Dict[str, Any]:
    """Lightweight counts for the dashboard."""
    from sqlalchemy import func
    from ..models import Match

    with db_session() as session:
        repo = MatchRepository(session)
        per_sport: List[Dict[str, Any]] = (
            session.query(
                Match.sport,
                func.count(Match.event_id).label("total"),
                func.sum(func.cast(Match.is_active, __import__("sqlalchemy").Integer)).label("active"),
            )
            .group_by(Match.sport)
            .all()
        )
        return {
            "active": repo.count_active(),
            "total": session.query(func.count(Match.event_id)).scalar() or 0,
            "by_sport": [
                {"sport": s or "unknown", "total": int(t or 0), "active": int(a or 0)}
                for s, t, a in per_sport
            ],
        }
