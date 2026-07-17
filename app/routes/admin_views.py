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
from typing import List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from datetime import datetime, timedelta

from sqlalchemy import func

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..models import Campaign, Club, HotBoost, Match, User
from ..parser.extra_feeds import add_extra_feed, delete_extra_feed, load_extra_feeds
from ..repositories.match_repo import MatchRepository
from ..services.journey_cloner_runner import (
    DEFAULT_TEAM,
    TEAMS,
    generate_comms_console_script,
    generate_console_script,
    generate_gow_combined_console_script,
    generate_gow_console_script,
    generate_tournament_pmcl_console_script,
    missing_templates,
    run_journey_cloner,
    save_template_from_fetch,
    team_inherits,
    template_status,
)

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

        # Active matches split by sport — feeds the dashboard donut.
        sport_rows = (
            session.query(Match.sport, func.count(Match.event_id))
            .filter(Match.is_active.is_(True))
            .group_by(Match.sport)
            .order_by(func.count(Match.event_id).desc())
            .all()
        )

    # Health signals based on real data, not hard-coded strings.
    parser_state = _parser_freshness(age_sec)
    sport_breakdown = _sport_breakdown(sport_rows, matches_active)

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
            "sport_breakdown": sport_breakdown,
            "last_update_age_sec": age_sec,
            "latest_matches": [m for m in latest],
            "current_user": user,
        },
    )


# Donut circumference for r=52 (2·π·52), matching the design reference.
_DONUT_CIRC = 326.726


def _sport_breakdown(rows, total: int):
    """Top 2 sports by active count + an 'Other' bucket, as donut segments
    (percentage + stroke-dasharray/offset). Returns [] when there's nothing
    active so the template can hide the chart."""
    if not total or not rows:
        return []
    top = rows[:2]
    other = sum(int(c) for _, c in rows[2:])
    buckets = [((s or "Other").capitalize(), int(c)) for s, c in top]
    if other:
        buckets.append(("Other", other))
    roles = ["accent", "dark", "muted"]
    segments = []
    cumulative = 0.0
    for i, (name, count) in enumerate(buckets):
        pct = count / total * 100.0
        segments.append(
            {
                "name": name,
                "count": count,
                "pct": round(pct),
                "dash": round(pct / 100.0 * _DONUT_CIRC, 1),
                "offset": round(-cumulative / 100.0 * _DONUT_CIRC, 1),
                "role": roles[i % len(roles)],
            }
        )
        cumulative += pct
    return segments


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
    include_inactive: int = 0,
    include_synthetic: int = 0,
    page: int = 1,
    user: User = Depends(require_login),
) -> HTMLResponse:
    page = max(1, page)
    per_page = 25
    offset = (page - 1) * per_page
    show_inactive = bool(include_inactive)
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
            include_inactive=show_inactive,
        )
        has_next = len(matches) > per_page
        matches = matches[:per_page]
        tournaments = repo.list_tournaments(
            sport=sport or None,
            include_synthetic=show_synth,
            include_inactive=show_inactive,
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
            "include_inactive": show_inactive,
            "include_synthetic": show_synth,
            "tournaments": tournaments,
            "total_active": total_active,
            "page": page,
            "has_next": has_next,
            "current_user": user,
        },
    )


# Convenience redirect: bare /admin/ → /admin
def _sync_live_parser_feeds() -> Optional[str]:
    try:
        import server as _server  # type: ignore

        sync = getattr(_server, "sync_extra_parser_feeds", None)
        if callable(sync):
            sync()
        return None
    except Exception as exc:
        return f"Parser link saved, but live parser sync failed: {exc}"


@router.get("/admin/parser-feeds", response_class=HTMLResponse)
def parser_feeds_page(
    request: Request,
    saved: int = 0,
    deleted: int = 0,
    sync_error: str = "",
    tg: str = "",
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    from ..services.telegram_notify import is_configured as _tg_configured

    feeds = load_extra_feeds()
    now_dt = datetime.utcnow()
    with db_session() as session:
        for feed in feeds:
            feed["status"] = _feed_db_status(
                session, feed["sport"], feed["mode"], feed["url"], now_dt
            )
    return templates.TemplateResponse(
        request,
        "parser_feeds.html",
        {
            "active_page": "parser_feeds",
            "current_user": user,
            "feeds": feeds,
            "saved": bool(saved),
            "deleted": bool(deleted),
            "sync_error": sync_error,
            "tg": tg,
            "telegram_configured": _tg_configured(),
        },
    )


# A live-bearing feed is "ok" when matches in its DB scope updated within this
# window. We read the DB (ground truth) instead of the parser's in-memory flag,
# which could read "failing" even while fresh rows were landing every minute.
FEED_OK_WINDOW_SEC = 15 * 60


def _scope_to_feed(query, sport: str, mode: str, url: str):
    """Narrow a Match query to the rows a given feed is responsible for:
    its tournament overlay (tournaments=…), its live firehose, or its sport."""
    params = parse_qs(urlparse(url).query)
    tids = [t.strip() for raw in params.get("tournaments", []) for t in raw.split(",") if t.strip()]
    if tids:
        return query.filter(Match.tournament_id.in_(tids))
    if mode == "live" or "/live/" in url:
        return query.filter(Match.sport == sport, Match.status == "live")
    return query.filter(Match.sport == sport)


def _feed_db_status(session, sport: str, mode: str, url: str, now_dt: datetime) -> dict:
    """Truthful per-feed status from the DB: how many active matches the feed
    covers and how long since any of them last updated."""
    base = session.query(
        func.max(Match.last_updated_at), func.count(Match.event_id)
    ).filter(Match.is_active.is_(True))
    last_update, count = _scope_to_feed(base, sport, mode, str(url)).one()
    age_sec = int((now_dt - last_update).total_seconds()) if last_update else None
    ok = age_sec is not None and age_sec < FEED_OK_WINDOW_SEC
    return {"count": int(count or 0), "age_sec": age_sec, "ok": ok}


def _live_parse_snapshot():
    """Live-bearing feeds (health derived from the DB, not the in-memory parser
    flag) plus the live games being tracked.

    Returns (feeds, live_by_league):
      feeds          per live-bearing feed: sport, mode, url, ok, count, age_sec
      live_by_league active in-play matches grouped by tournament
    A feed "carries live" if its mode is live OR it is a tournament overlay
    (/all/?tournaments=...) — overlays serve both live and prematch.
    """
    feed_map: dict = {}
    try:
        import server as _server  # already-loaded main module

        feed_map = dict(getattr(_server, "FEEDS", {}) or {})
    except Exception:
        feed_map = {}

    now_dt = datetime.utcnow()
    feeds: list = []
    live_by_league: list = []
    with db_session() as session:
        for key, url in feed_map.items():
            sport, mode = key
            url = str(url)
            carries_live = (mode == "live") or ("tournaments=" in url) or ("/all/" in url)
            if not carries_live:
                continue
            st = _feed_db_status(session, sport, mode, url, now_dt)
            feeds.append(
                {
                    "sport": sport,
                    "mode": mode,
                    "url": url,
                    "ok": st["ok"],
                    "count": st["count"],
                    "age_sec": st["age_sec"],
                    "error": None if st["ok"] else "no fresh matches from this feed",
                }
            )
        feeds.sort(key=lambda r: (r["sport"], r["mode"], r["url"]))

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


@router.get("/admin/journey-cloner")
def journey_cloner_page(
    template_saved: str = "",
    template_error: str = "",
    team: str = DEFAULT_TEAM,
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    # Journey Cloner now lives as a tab inside the unified Promotions page.
    params = {"tab": "journey_cloner", "team": team if team in TEAMS else DEFAULT_TEAM}
    if template_saved:
        params["template_saved"] = template_saved
    if template_error:
        params["template_error"] = template_error
    return RedirectResponse(f"/admin/promotions?{urlencode(params)}", status_code=status.HTTP_302_FOUND)


@router.post("/admin/journey-cloner", response_class=HTMLResponse)
def journey_cloner_run(
    request: Request,
    token: str = Form(""),
    team: str = Form(DEFAULT_TEAM),
    home: str = Form(...),
    away: str = Form(...),
    date: str = Form(...),
    chile_time: str = Form(...),
    code: str = Form(...),
    types: List[str] = Form(["followup", "bfr", "two_hours", "aft"]),
    dry_run: Optional[str] = Form(None),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    team = team if team in TEAMS else DEFAULT_TEAM
    selected_types = [t for t in types if t in {"followup", "bfr", "two_hours", "aft"}]
    is_dry_run = bool(dry_run)
    form = {
        "home": home,
        "away": away,
        "date": date,
        "chile_time": chile_time,
        "code": code,
    }
    error = ""
    result = None

    if not selected_types:
        error = "Select at least one draft type."
    elif not is_dry_run and not token.strip():
        error = "Bearer token is required when dry run is unchecked."
    else:
        missing = missing_templates(selected_types, team)
        if missing:
            error = "Missing templates: " + ", ".join(
                f"templates/{team}/{m}.json" for m in missing
            )

    if not error:
        try:
            exit_code, output, display_cmd = run_journey_cloner(
                token=token,
                home=home,
                away=away,
                code=code,
                date=date,
                chile_time=chile_time,
                selected_types=selected_types,
                dry_run=is_dry_run,
                team=team,
            )
            result = {
                "exit_code": exit_code,
                "output": output,
                "command": display_cmd,
                "ok": exit_code == 0,
            }
        except Exception as exc:
            error = str(exc)

    ctx = _promotions_context(
        user=user,
        active_tab="journey_cloner",
        jc=_jc_ns(team=team, form=form, selected_types=selected_types,
                  dry_run=is_dry_run, result=result, error=error),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.post("/admin/journey-cloner/console-script", response_class=HTMLResponse)
def journey_cloner_console_script(
    request: Request,
    team: str = Form(DEFAULT_TEAM),
    home: str = Form(...),
    away: str = Form(...),
    date: str = Form(...),
    chile_time: str = Form(...),
    code: str = Form(...),
    types: List[str] = Form(["followup", "bfr", "two_hours", "aft"]),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    team = team if team in TEAMS else DEFAULT_TEAM
    selected_types = [t for t in types if t in {"followup", "bfr", "two_hours", "aft"}]
    form = {
        "home": home,
        "away": away,
        "date": date,
        "chile_time": chile_time,
        "code": code,
    }
    error = ""
    result = None
    console_script = None

    if not selected_types:
        error = "Select at least one draft type."
    else:
        missing = missing_templates(selected_types, team)
        if missing:
            error = "Missing templates: " + ", ".join(
                f"templates/{team}/{m}.json" for m in missing
            )

    if not error:
        try:
            exit_code, output, display_cmd, js_text, js_name = generate_console_script(
                home=home,
                away=away,
                code=code,
                date=date,
                chile_time=chile_time,
                selected_types=selected_types,
                team=team,
            )
            result = {
                "exit_code": exit_code,
                "output": output,
                "command": display_cmd,
                "ok": exit_code == 0 and js_text is not None,
            }
            if exit_code == 0 and js_text is not None:
                console_script = {"name": js_name, "text": js_text}
            else:
                error = "Console script was not generated. Check the run output below."
        except Exception as exc:
            error = str(exc)

    ctx = _promotions_context(
        user=user,
        active_tab="journey_cloner",
        jc=_jc_ns(team=team, form=form, selected_types=selected_types,
                  result=result, error=error, console_script=console_script),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.post("/admin/journey-cloner/templates", response_class=HTMLResponse)
def journey_cloner_save_template(
    request: Request,
    template_type: str = Form(...),
    fetch_text: str = Form(...),
    team: str = Form(DEFAULT_TEAM),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    team = team if team in TEAMS else DEFAULT_TEAM
    template_saved = ""
    template_error = ""
    try:
        info = save_template_from_fetch(template_type, fetch_text, team)
        name = info.get("journeyName") or template_type
        template_saved = (
            f"Saved {TEAMS[team]} {template_type}.json from template: {name}"
        )
    except Exception as exc:
        template_error = str(exc)

    ctx = _promotions_context(
        user=user,
        active_tab="journey_cloner",
        jc=_jc_ns(team=team, template_saved=template_saved, template_error=template_error),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.get("/admin/gow")
def gow_page(user: User = Depends(require_role("editor"))) -> RedirectResponse:
    # GOW now lives as a tab inside the unified Promotions page.
    return RedirectResponse("/admin/promotions?tab=gow", status_code=status.HTTP_302_FOUND)


def _figma_context(*, form, result=None, error="", images=None):
    from ..services import figma_runner
    return {
        "active_page": "figma",
        "form": form,
        "result": result,
        "error": error,
        "images": images or [],
        "token_present": figma_runner.token_present(),
    }


@router.get("/admin/figma", response_class=HTMLResponse)
def figma_page(request: Request, user: User = Depends(require_role("editor"))) -> HTMLResponse:
    ctx = _figma_context(form={"file_key": "go1ZVyvYRnccMRGxzgiucv", "page": "GAME OF THE WEEK (JULY)"})
    ctx["current_user"] = user
    return templates.TemplateResponse(request, "figma.html", ctx)


@router.post("/admin/figma/run", response_class=HTMLResponse)
def figma_run(
    request: Request,
    file_key: str = Form(...),
    page: str = Form(""),
    game: str = Form(""),
    ids: str = Form(""),
    mode: str = Form("inspect"),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    from ..services import figma_runner
    form = {"file_key": file_key, "page": page, "game": game, "ids": ids, "mode": mode}
    error, result, images = "", None, []
    try:
        if not file_key.strip():
            raise ValueError("File key is required.")
        if mode == "export":
            if not game.strip():
                raise ValueError("Game name is required for export.")
            rc, out, cmd, images = figma_runner.export(file_key, game, page)
        elif mode == "seed":
            if not game.strip():
                raise ValueError("Game name is required to seed node ids.")
            if not ids.strip():
                raise ValueError("Paste the node ids, e.g. popup_bg=1078:2286,email_hero=1078:2810,campaign=1078:2911")
            rc, out, cmd, images = figma_runner.seed(file_key, game, ids)
        else:
            rc, out, cmd = figma_runner.inspect(file_key, page)
        result = {"exit_code": rc, "output": out, "command": cmd, "ok": rc == 0}
        if rc != 0:
            error = "figma_export returned a non-zero exit code (see output)."
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    ctx = _figma_context(form=form, result=result, error=error, images=images)
    ctx["current_user"] = user
    return templates.TemplateResponse(request, "figma.html", ctx)


_PROMO_TABS = {"overview", "gow", "tournament_pmcl", "journey_cloner", "randomizers", "nc_discount", "scripts"}
_JC_TYPES = ["followup", "bfr", "two_hours", "aft"]


def _gow_ns(*, form=None, error="", result=None, console_script=None, warn="") -> dict:
    return {
        "form": form if form is not None else {"create_campaign": "on", "create_communication": "on"},
        "error": error,
        "result": result,
        "console_script": console_script,
        "warn": warn,
    }


def _tournament_ns(*, form=None, error="", result=None, console_script=None) -> dict:
    return {
        "form": form if form is not None else {},
        "error": error,
        "result": result,
        "console_script": console_script,
    }


def _jc_ns(*, team=DEFAULT_TEAM, form=None, selected_types=None, dry_run=True,
           result=None, error="", template_saved="", template_error="", console_script=None) -> dict:
    team = team if team in TEAMS else DEFAULT_TEAM
    return {
        "teams": TEAMS,
        "team": team,
        "template_status": template_status(team),
        "team_inherits": team_inherits(team),
        "selected_types": selected_types if selected_types is not None else list(_JC_TYPES),
        "dry_run": dry_run,
        "result": result,
        "error": error,
        "template_saved": template_saved,
        "template_error": template_error,
        "form": form or {},
        "console_script": console_script,
    }


def _rnd_ns(*, kind="sport_wof", date="", days="", weights="", journeys="",
           error="", result=None, console_script=None) -> dict:
    from ..services.journey_cloner_runner import RANDOMIZER_KINDS
    return {
        "kinds": RANDOMIZER_KINDS,
        "kind": kind if kind in RANDOMIZER_KINDS else "sport_wof",
        "date": date,
        "days": days,
        "weights": weights,
        "journeys": journeys,
        "error": error,
        "result": result,
        "console_script": console_script,
    }


def _nc_ns(*, error="", result=None, console_script=None,
           pmcl_error="", pmcl_result=None, pmcl_console_script=None,
           git_result=None) -> dict:
    return {
        "error": error, "result": result, "console_script": console_script,
        "pmcl_error": pmcl_error, "pmcl_result": pmcl_result,
        "pmcl_console_script": pmcl_console_script,
        "git_result": git_result,
    }


def _promotions_context(*, user, active_tab="overview", gow=None, tournament=None, jc=None, rnd=None, nc=None) -> dict:
    """Full context for the unified Promotions page: automation graph + the
    embedded generators (GOW, Journey Cloner, Randomizers, Discount NC) +
    all-scripts list."""
    from ..services import promotions_catalog as pc
    cat = pc.load_catalog()
    tab = active_tab if active_tab in _PROMO_TABS else "overview"
    # The Notification Cloner (Discount NC) also has its own sidebar entry, so
    # highlight that nav item when its tab is active instead of "Promotions".
    return {
        "active_page": "nc_cloner" if tab == "nc_discount" else "promotions",
        "current_user": user,
        "active_tab": tab,
        "meta": cat.get("meta", {}),
        "automations": pc.automations(),
        "all_scripts": pc.all_scripts(),
        "gow": gow if gow is not None else _gow_ns(),
        "tournament": tournament if tournament is not None else _tournament_ns(),
        "jc": jc if jc is not None else _jc_ns(),
        "rnd": rnd if rnd is not None else _rnd_ns(),
        "nc": nc if nc is not None else _nc_ns(),
    }


@router.get("/admin/promotions", response_class=HTMLResponse)
def promotions_page(
    request: Request,
    tab: str = "overview",
    team: str = DEFAULT_TEAM,
    template_saved: str = "",
    template_error: str = "",
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    """Promotions hub: automation graph + the GOW and Journey Cloner generators
    (as tabs) + every generator script and captured template."""
    ctx = _promotions_context(
        user=user,
        active_tab=tab,
        jc=_jc_ns(team=team, template_saved=template_saved, template_error=template_error),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.get("/admin/promotions/download")
def promotions_download(
    path: str,
    dl: str = "",
    user: User = Depends(require_role("editor")),
) -> FileResponse:
    """Serve a single journey-cloner script/template. Inline for viewing in the
    browser, or as an attachment when dl=1. Path-whitelisted to journey-cloner/."""
    from ..services import promotions_catalog as pc
    resolved = pc.resolve_script(path)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Script not found.")
    disposition = "attachment" if dl.strip() in ("1", "true", "yes") else "inline"
    return FileResponse(
        resolved,
        media_type="text/plain; charset=utf-8",
        filename=resolved.name,
        content_disposition_type=disposition,
    )


@router.post("/admin/promotions/randomizer", response_class=HTMLResponse)
def promotions_randomizer(
    request: Request,
    kind: str = Form(...),
    date: str = Form(...),
    days: str = Form(""),
    weights: str = Form(""),
    journeys: str = Form(""),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    """Generate a Randomizer console script (Sport WOF / Casino WOF / Scratch
    card) from the Promotions page's Randomizers tab."""
    from ..services.journey_cloner_runner import (
        RANDOMIZER_KINDS,
        generate_randomizer_console_script,
    )
    error = ""
    result = None
    console_script = None
    try:
        if kind not in RANDOMIZER_KINDS:
            raise ValueError("Pick a randomizer type.")
        if not date.strip():
            raise ValueError("Date is required.")
        if days.strip():
            int(days.strip())  # validate
        exit_code, output, display_cmd, js_text, js_name = generate_randomizer_console_script(
            kind=kind, date=date, days=days, weights=weights, journeys=journeys,
        )
        result = {"exit_code": exit_code, "output": output, "command": display_cmd,
                  "ok": exit_code == 0 and js_text is not None}
        if exit_code == 0 and js_text is not None:
            console_script = {"name": js_name, "text": js_text}
        else:
            error = "Console script was not generated. Check the run output below."
    except ValueError as exc:
        error = str(exc) if "invalid literal" not in str(exc) else "Days must be a whole number."
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    ctx = _promotions_context(
        user=user,
        active_tab="randomizers",
        rnd=_rnd_ns(kind=kind, date=date, days=days, weights=weights, journeys=journeys,
                    error=error, result=result, console_script=console_script),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.post("/admin/promotions/nc-discount", response_class=HTMLResponse)
def promotions_nc_discount(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    """Generate the "NC For Discount" console script (one notification journey
    per game/day from the baked July calendar)."""
    from ..services.journey_cloner_runner import generate_nc_discount_console_script
    error = ""
    result = None
    console_script = None
    try:
        exit_code, output, display_cmd, js_text, js_name = generate_nc_discount_console_script()
        result = {"exit_code": exit_code, "output": output, "command": display_cmd,
                  "ok": exit_code == 0 and js_text is not None}
        if exit_code == 0 and js_text is not None:
            console_script = {"name": js_name, "text": js_text}
        else:
            error = "Console script was not generated. Check the run output below."
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    ctx = _promotions_context(
        user=user,
        active_tab="nc_discount",
        nc=_nc_ns(error=error, result=result, console_script=console_script),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.post("/admin/promotions/nc-discount-pmcl", response_class=HTMLResponse)
def promotions_nc_discount_pmcl(
    request: Request,
    folder_id: str = Form(""),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    """Generate the "NC For Discount PMCL" console script for fortunazo.cl."""
    from ..services.journey_cloner_runner import generate_nc_discount_pmcl_console_script
    pmcl_error = ""
    pmcl_result = None
    pmcl_console_script = None
    if not folder_id.strip():
        pmcl_error = "Media Library Folder ID is required. Find it in the PMCL backoffice URL: /media-library/folders/<uuid>."
        ctx = _promotions_context(
            user=user,
            active_tab="nc_discount",
            nc=_nc_ns(pmcl_error=pmcl_error),
        )
        return templates.TemplateResponse(request, "promotions.html", ctx)
    try:
        exit_code, output, display_cmd, js_text, js_name = generate_nc_discount_pmcl_console_script(folder_id.strip())
        pmcl_result = {"exit_code": exit_code, "output": output, "command": display_cmd,
                       "ok": exit_code == 0 and js_text is not None}
        if exit_code == 0 and js_text is not None:
            pmcl_console_script = {"name": js_name, "text": js_text}
        else:
            pmcl_error = "Console script was not generated. Check the run output below."
    except Exception as exc:  # noqa: BLE001
        pmcl_error = str(exc)

    ctx = _promotions_context(
        user=user,
        active_tab="nc_discount",
        nc=_nc_ns(pmcl_error=pmcl_error, pmcl_result=pmcl_result,
                  pmcl_console_script=pmcl_console_script),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.post("/admin/promotions/git-pull", response_class=HTMLResponse)
def promotions_git_pull(
    request: Request,
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    """Run git pull in the repo root and display output on the Discount NC tab."""
    from ..services.journey_cloner_runner import git_pull
    try:
        exit_code, output = git_pull()
        git_result = {"exit_code": exit_code, "output": output, "ok": exit_code == 0}
    except Exception as exc:  # noqa: BLE001
        git_result = {"exit_code": 1, "output": str(exc), "ok": False}

    ctx = _promotions_context(
        user=user,
        active_tab="nc_discount",
        nc=_nc_ns(git_result=git_result),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.post("/admin/gow/console-script", response_class=HTMLResponse)
def gow_console_script(
    request: Request,
    date: str = Form(...),
    spec: str = Form(...),
    create_campaign: str = Form(""),
    create_communication: str = Form(""),
    days: str = Form("1"),
    spins: str = Form(""),
    promo_page_id: str = Form(""),
    public_domain: str = Form(""),
    journey_name: str = Form(""),
    use_figma: str = Form(""),
    figma_game: str = Form(""),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    do_campaign = create_campaign.strip().lower() in ("on", "true", "1", "yes")
    do_comms = create_communication.strip().lower() in ("on", "true", "1", "yes")
    do_figma = use_figma.strip().lower() in ("on", "true", "1", "yes")
    # The toggle gates the Figma export: only pull from Figma when it's on AND a
    # game is named. Off (or blank game) -> file pickers at paste time, as before.
    effective_figma_game = figma_game.strip() if do_figma else ""
    form = {
        "date": date,
        "spec": spec,
        "create_campaign": "on" if do_campaign else "",
        "create_communication": "on" if do_comms else "",
        "days": days,
        "spins": spins,
        "promo_page_id": promo_page_id,
        "public_domain": public_domain,
        "journey_name": journey_name,
        "use_figma": "on" if do_figma else "",
        "figma_game": figma_game,
    }
    error = ""
    result = None
    console_script = None

    parsed_days: Optional[int] = None
    parsed_spins: Optional[int] = None
    try:
        if not date.strip():
            raise ValueError("Date is required.")
        if not spec.strip():
            raise ValueError("Paste the spec blob (Product/Offer/Communication channels table).")
        if not do_campaign and not do_comms:
            raise ValueError("Tick at least one of Create Campaign / Create Communication.")
        if do_comms and not do_campaign and not promo_page_id.strip():
            raise ValueError(
                "Promo-page id is required when creating Communication without Campaign "
                "(from a previously created GOW promo page)."
            )
        if do_figma and not figma_game.strip():
            raise ValueError("Enter the Figma game name, or turn off 'Pull images from Figma'.")
        if do_figma and not do_campaign:
            raise ValueError("Figma images apply to the Campaign — tick Create Campaign, or turn Figma off.")
        if days.strip():
            parsed_days = int(days.strip())
        if spins.strip():
            parsed_spins = int(spins.strip())
    except ValueError as exc:
        error = str(exc) if "invalid literal" not in str(exc) else "Days/Free spins must be whole numbers."

    if not error:
        try:
            if do_campaign and do_comms:
                exit_code, output, display_cmd, js_text, js_name = generate_gow_combined_console_script(
                    date=date,
                    spec_text=spec,
                    days=parsed_days or 1,
                    spins=parsed_spins,
                    public_domain=public_domain,
                    journey_name=journey_name,
                    figma_game=effective_figma_game,
                )
            elif do_campaign:
                exit_code, output, display_cmd, js_text, js_name = generate_gow_console_script(
                    date=date,
                    spec_text=spec,
                    spins=parsed_spins,
                    figma_game=effective_figma_game,
                )
            else:
                exit_code, output, display_cmd, js_text, js_name = generate_comms_console_script(
                    date=date,
                    spec_text=spec,
                    promo_page_id=promo_page_id,
                    public_domain=public_domain,
                    journey_name=journey_name,
                )
            result = {
                "exit_code": exit_code,
                "output": output,
                "command": display_cmd,
                "ok": exit_code == 0 and js_text is not None,
            }
            if exit_code == 0 and js_text is not None:
                console_script = {"name": js_name, "text": js_text}
            else:
                error = "Console script was not generated. Check the run output below."
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

    # The Figma toggle was on but the export fell back to file pickers — say so
    # loudly instead of showing a plain "ready", and surface the actual reason.
    warn = ""
    if effective_figma_game and result and console_script:
        out_low = (result.get("output") or "").lower()
        if "falling back to" in out_low or "figma export failed" in out_low or "figma export error" in out_low:
            reason = _extract_figma_reason(result.get("output") or "")
            warn = (
                f"⚠️ Figma export did NOT run for “{effective_figma_game}”, so the script still uses "
                f"file pickers. Reason: {reason} "
                "Fix: set FIGMA_TOKEN in the server env, make sure the game name matches the Figma board exactly, "
                "and (for a new game) seed its node ids once via the Figma tab / figma_export.py --ids."
            )

    ctx = _promotions_context(
        user=user,
        active_tab="gow",
        gow=_gow_ns(form=form, error=error, result=result, console_script=console_script, warn=warn),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


@router.post("/admin/promotions/tournament-pmcl", response_class=HTMLResponse)
def promotions_tournament_pmcl(
    request: Request,
    date: str = Form(...),
    spec: str = Form(...),
    tournament_id: str = Form(""),
    folder_id: str = Form(""),
    journey_name: str = Form(""),
    user: User = Depends(require_role("editor")),
) -> HTMLResponse:
    """Generate the PMCL (Fortunazo) Tournament comms console script — the same
    paste-a-sheet → console-script flow as GOW comms, wired to the Smartico
    tournament deeplink instead of a promo page."""
    form = {
        "date": date,
        "spec": spec,
        "tournament_id": tournament_id,
        "folder_id": folder_id,
        "journey_name": journey_name,
    }
    error = ""
    result = None
    console_script = None
    try:
        if not date.strip():
            raise ValueError("Date is required.")
        if not spec.strip():
            raise ValueError("Paste the spec blob (Communication channels table from the sheet).")
        exit_code, output, display_cmd, js_text, js_name = generate_tournament_pmcl_console_script(
            date=date,
            spec_text=spec,
            tournament_id=tournament_id,
            folder_id=folder_id,
            journey_name=journey_name,
        )
        result = {
            "exit_code": exit_code,
            "output": output,
            "command": display_cmd,
            "ok": exit_code == 0 and js_text is not None,
        }
        if exit_code == 0 and js_text is not None:
            console_script = {"name": js_name, "text": js_text}
        else:
            error = "Console script was not generated. Check the run output below."
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    ctx = _promotions_context(
        user=user,
        active_tab="tournament_pmcl",
        tournament=_tournament_ns(form=form, error=error, result=result, console_script=console_script),
    )
    return templates.TemplateResponse(request, "promotions.html", ctx)


def _extract_figma_reason(output: str) -> str:
    """Pull the human reason out of a gow_*.py Figma fallback WARN line."""
    for line in output.splitlines():
        low = line.lower()
        if "falling back" in low or "figma export" in low:
            # e.g. "  WARN  Figma export failed (Figma rate-limited (429)...); falling back..."
            import re
            m = re.search(r"\((.*)\)", line)
            if m:
                return m.group(1).strip()
            return line.strip().lstrip("WARN").strip()
    return "see the run output below."


@router.post("/admin/parser-feeds")
def parser_feeds_create(
    label: str = Form(...),
    sport: str = Form(...),
    mode: str = Form(...),
    url: str = Form(...),
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    add_extra_feed(label=label, sport=sport, mode=mode, url=url)
    sync_error = _sync_live_parser_feeds()
    qs = {"saved": "1"}
    if sync_error:
        qs["sync_error"] = sync_error
    return RedirectResponse(
        f"/admin/parser-feeds?{urlencode(qs)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/parser-feeds/{feed_id}/delete")
def parser_feeds_delete(
    feed_id: str,
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    delete_extra_feed(feed_id)
    sync_error = _sync_live_parser_feeds()
    qs = {"deleted": "1"}
    if sync_error:
        qs["sync_error"] = sync_error
    return RedirectResponse(
        f"/admin/parser-feeds?{urlencode(qs)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/parser-feeds/test-telegram")
def parser_feeds_test_telegram(
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    """Send a test alert + a live summary of currently-dead campaigns so the
    operator can confirm their Telegram bot is wired up correctly."""
    from ..services.campaign_monitor import evaluate
    from ..services.telegram_notify import is_configured, send_telegram

    if not is_configured():
        return RedirectResponse(
            f"/admin/parser-feeds?{urlencode({'tg': 'unconfigured'})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    healths = evaluate()
    dead = [h for h in healths if h.dead]
    if dead:
        lines = "\n".join(f"• {h.title} (/{h.slug}) — {h.reason}" for h in dead[:10])
        body = f"\n\n<b>{len(dead)} campaign(s) currently dead:</b>\n{lines}"
    else:
        body = f"\n\nAll {len(healths)} campaigns healthy ✅"
    ok = send_telegram("✅ <b>Jugabet Admin</b> — test alert." + body)
    return RedirectResponse(
        f"/admin/parser-feeds?{urlencode({'tg': 'ok' if ok else 'fail'})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/admin/")
def admin_trailing_slash() -> RedirectResponse:
    return RedirectResponse(url="/admin")
