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

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from datetime import datetime, timedelta

from sqlalchemy import func

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..models import Campaign, Club, HotBoost, Match, User
from ..parser.extra_feeds import add_extra_feed, delete_extra_feed, load_extra_feeds
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
def _sync_live_parser_feeds() -> None:
    try:
        import server as _server  # type: ignore

        sync = getattr(_server, "sync_extra_parser_feeds", None)
        if callable(sync):
            sync()
    except Exception:
        pass


@router.get("/admin/parser-feeds", response_class=HTMLResponse)
def parser_feeds_page(
    request: Request,
    saved: int = 0,
    deleted: int = 0,
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "parser_feeds.html",
        {
            "active_page": "parser_feeds",
            "current_user": user,
            "feeds": load_extra_feeds(),
            "saved": bool(saved),
            "deleted": bool(deleted),
        },
    )


def _live_parse_snapshot():
    """Read the parser's live-bearing feeds + the live games being tracked.

    Returns (feeds, live_by_league):
      feeds          per live-bearing feed: sport, mode, url, ok, count, age_sec
      live_by_league active in-play matches grouped by tournament
    A feed "carries live" if its mode is live OR it is a tournament overlay
    (/all/?tournaments=...) — overlays serve both live and prematch.
    """
    import time as _time

    feeds: list = []
    try:
        import server as _server  # already-loaded main module

        feed_map = dict(getattr(_server, "FEEDS", {}) or {})
        state = getattr(_server, "_state", {}) or {}
        lock = getattr(_server, "_state_lock", None)
        now = _time.time()

        meta_snap: dict = {}
        if lock is not None:
            with lock:
                for key, st in state.items():
                    meta_snap[key] = dict(getattr(st, "meta", {}) or {})

        for key, url in feed_map.items():
            sport, mode = key
            url = str(url)
            carries_live = (mode == "live") or ("tournaments=" in url) or ("/all/" in url)
            if not carries_live:
                continue
            meta = meta_snap.get(key, {})
            last_ok = meta.get("last_success_epoch") or 0
            feeds.append(
                {
                    "sport": sport,
                    "mode": mode,
                    "url": meta.get("source_url") or url,
                    "ok": bool(meta.get("ok")),
                    "count": int(meta.get("count") or 0),
                    "age_sec": int(now - last_ok) if last_ok else None,
                    "error": None if meta.get("ok") else meta.get("error"),
                }
            )
        feeds.sort(key=lambda r: (r["sport"], r["mode"], r["url"]))
    except Exception:
        feeds = []

    live_by_league: list = []
    with db_session() as session:
        rows = (
            session.query(Match.sport, Match.tournament_name, func.count(Match.event_id))
            .filter(Match.is_active.is_(True))
            .filter(Match.status == "live")
            .filter(Match.is_synthetic.is_(False))
            .group_by(Match.sport, Match.tournament_name)
            .order_by(func.count(Match.event_id).desc())
            .all()
        )
        live_by_league = [
            {"sport": sp, "league": tn or "—", "count": int(c)} for sp, tn, c in rows
        ]
    return feeds, live_by_league


@router.get("/admin/live-parses", response_class=HTMLResponse)
def live_parses_page(
    request: Request,
    user: User = Depends(require_login),
) -> HTMLResponse:
    feeds, live_by_league = _live_parse_snapshot()
    healthy = sum(1 for f in feeds if f["ok"])
    live_total = sum(row["count"] for row in live_by_league)
    return templates.TemplateResponse(
        request,
        "live_parses.html",
        {
            "active_page": "live_parses",
            "current_user": user,
            "feeds": feeds,
            "live_by_league": live_by_league,
            "healthy": healthy,
            "feeds_total": len(feeds),
            "live_total": live_total,
        },
    )


@router.post("/admin/parser-feeds")
def parser_feeds_create(
    label: str = Form(...),
    sport: str = Form(...),
    mode: str = Form(...),
    url: str = Form(...),
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    add_extra_feed(label=label, sport=sport, mode=mode, url=url)
    _sync_live_parser_feeds()
    return RedirectResponse("/admin/parser-feeds?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/parser-feeds/{feed_id}/delete")
def parser_feeds_delete(
    feed_id: str,
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    delete_extra_feed(feed_id)
    _sync_live_parser_feeds()
    return RedirectResponse("/admin/parser-feeds?deleted=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/")
def admin_trailing_slash() -> RedirectResponse:
    return RedirectResponse(url="/admin")
