"""
JSON endpoints used by the admin UI.

All under /api/admin/* — these are NOT public render endpoints.
Phase 3 will protect these with auth.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from ..auth.dependencies import require_login
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
) -> Dict[str, Any]:
    """Searchable list of active matches for the match picker."""
    with db_session() as session:
        repo = MatchRepository(session)
        results = repo.search(
            query=q or None,
            sport=sport or None,
            status=status or None,
            limit=limit,
            offset=offset,
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
