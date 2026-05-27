"""
Admin HTML pages — minimal surface remaining after Phase C cleanup.

  GET  /admin                  → dashboard (stats over matches + clubs)
  GET  /admin/matches          → searchable match list

Phase C removed:
  - /admin/campaigns/*  (campaigns UI; data layer kept for /r/{slug}.png)
  - /admin/hot          (hot override dashboard; replaced by /api/hot/override/*)
  - /admin/manual-slots (legacy admin_html.py)

Auth, audit log, RBAC, and the public render endpoints all remain.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from datetime import datetime, timedelta

from sqlalchemy import func

from ..auth.dependencies import require_login
from ..database import db_session
from ..models import Campaign, Club, HotBoost, Match, User
from ..repositories.match_repo import MatchRepository

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(require_login)) -> HTMLResponse:
    with db_session() as session:
        match_repo = MatchRepository(session)

        # Counts
        matches_total = session.query(func.count(Match.event_id)).scalar() or 0
        matches_active = match_repo.count_active()
        clubs_total = session.query(func.count(Club.slug)).scalar() or 0
        campaigns_total = session.query(func.count(Campaign.slug)).scalar() or 0
        campaigns_auto = session.query(func.count(Campaign.slug)).filter(Campaign.mode == "auto").scalar() or 0
        campaigns_manual = session.query(func.count(Campaign.slug)).filter(Campaign.mode == "manual").scalar() or 0
        campaigns_enabled = session.query(func.count(Campaign.slug)).filter(Campaign.enabled.is_(True)).scalar() or 0
        # Only count overrides that target a currently-active match. Without
        # the join, a pin/suppress left behind on a deactivated match keeps
        # contributing to the global count even though no per-sport browse
        # page ever lists it — admins saw "5 suppressed" with nothing to
        # un-suppress.
        hot_pinned = (
            session.query(func.count(HotBoost.event_id))
            .join(Match, Match.event_id == HotBoost.event_id)
            .filter(HotBoost.position.is_not(None))
            .filter(Match.is_active.is_(True))
            .scalar() or 0
        )
        hot_suppressed = (
            session.query(func.count(HotBoost.event_id))
            .join(Match, Match.event_id == HotBoost.event_id)
            .filter(HotBoost.suppress.is_(True))
            .filter(Match.is_active.is_(True))
            .scalar() or 0
        )

        # Freshness signal — when was the most recently touched match updated?
        last_update_row = (
            session.query(func.max(Match.last_updated_at)).scalar()
        )
        if last_update_row is not None:
            age_sec = max(0, int((datetime.utcnow() - last_update_row).total_seconds()))
        else:
            age_sec = None

        latest = match_repo.search(limit=5)

    # Health signals based on real data, not hard-coded strings.
    parser_state = _parser_freshness(age_sec)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active_page": "dashboard",
            "stats": {
                "matches_total": matches_total,
                "matches_active": matches_active,
                "clubs_total": clubs_total,
                "campaigns_total": campaigns_total,
                "campaigns_auto": campaigns_auto,
                "campaigns_manual": campaigns_manual,
                "campaigns_enabled": campaigns_enabled,
                "hot_pinned": hot_pinned,
                "hot_suppressed": hot_suppressed,
            },
            "parser_state": parser_state,
            "last_update_age_sec": age_sec,
            "latest_matches": [m for m in latest],
            "current_user": user,
        },
    )


def _parser_freshness(age_sec):
    """Map seconds-since-last-match-update to a health verdict + label."""
    if age_sec is None:
        return {"label": "No data yet", "color": "muted", "detail": "Parser hasn't written anything yet."}
    if age_sec < 120:
        return {"label": "Fresh", "color": "green", "detail": f"updated {age_sec}s ago"}
    if age_sec < 600:
        return {"label": "Recent", "color": "green", "detail": f"updated {age_sec // 60}m ago"}
    if age_sec < 3600:
        return {"label": "Stale", "color": "yellow", "detail": f"no update for {age_sec // 60}m"}
    return {"label": "Stalled", "color": "red", "detail": f"no update for {age_sec // 3600}h"}


@router.get("/admin/matches", response_class=HTMLResponse)
def matches_list(
    request: Request,
    q: str = "",
    sport: str = "",
    status: str = "",
    tournament: str = "",
    include_synthetic: int = 0,
    page: int = 1,
    user: User = Depends(require_login),
) -> HTMLResponse:
    page = max(1, page)
    per_page = 25
    offset = (page - 1) * per_page
    show_synth = bool(include_synthetic)

    with db_session() as session:
        repo = MatchRepository(session)
        matches = repo.search(
            query=q or None,
            sport=sport or None,
            status=status or None,
            tournament=tournament or None,
            limit=per_page + 1,
            offset=offset,
            include_synthetic=show_synth,
        )
        has_next = len(matches) > per_page
        matches = matches[:per_page]
        tournaments = repo.list_tournaments(
            sport=sport or None, include_synthetic=show_synth
        )
        total_active = repo.count_active()

    return templates.TemplateResponse(
        request,
        "matches/list.html",
        {
            "active_page": "matches",
            "matches": matches,
            "q": q,
            "sport": sport,
            "status": status,
            "tournament": tournament,
            "include_synthetic": show_synth,
            "tournaments": tournaments,
            "total_active": total_active,
            "page": page,
            "has_next": has_next,
            "current_user": user,
        },
    )


# Convenience redirect: bare /admin/ → /admin
@router.get("/admin/")
def admin_trailing_slash() -> RedirectResponse:
    return RedirectResponse(url="/admin")
