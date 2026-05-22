"""
Campaign management — admin UI routes.

HTML pages (require login):
  GET  /admin/campaigns                         list all campaigns
  GET  /admin/campaigns/new                     new campaign form
  POST /admin/campaigns                         create campaign (manual or auto)
  GET  /admin/campaigns/{slug}                  edit page
  POST /admin/campaigns/{slug}                  update settings
  POST /admin/campaigns/{slug}/delete           delete
  POST /admin/campaigns/{slug}/toggle           enable / disable
  POST /admin/campaigns/{slug}/duplicate        clone

JSON / HTMX endpoints (require login):
  GET  /api/admin/campaigns/{slug}/matches      ordered match list
  POST /api/admin/campaigns/{slug}/matches      add match (body: event_id)
  DELETE /api/admin/campaigns/{slug}/matches/{event_id}
  PUT  /api/admin/campaigns/{slug}/matches      reorder (body: event_ids in order)
  GET  /api/admin/campaigns/{slug}/picker       HTMX search results partial

A campaign is one of two shapes — UI never asks the user to choose a
"type", it asks which section they want to fill in:

  manual  Pick specific matches.
  auto    Pick a sport + league; render-time `?limit=` controls count.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..logging_config import get_logger
from ..models import User
from ..repositories.campaign_repo import CampaignRepository
from ..repositories.log_repo import LogRepository
from ..repositories.match_repo import MatchRepository
from ..services.hot_engine import HotEngine
from ..utils.slugify import slugify_league
from .public_render import DEFAULT_AUTO_LIMIT, _cache_invalidate, _clamp_limit

logger = get_logger("app.routes.campaigns")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}$")
VALID_SPORTS = ("football", "basketball", "tennis", "cybersport", "fights", "ufc", "mma", "boxing")
VALID_MODES = ("manual", "auto")


def _validate_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "Slug must be 2-50 chars, lowercase letters/digits/hyphens only.")
    return slug


def _normalise_league(league: Optional[str]) -> Optional[str]:
    if league is None:
        return None
    league = league.strip()
    return league or None


def _validate_sport(sport: str) -> str:
    sport = (sport or "").strip().lower()
    if sport not in VALID_SPORTS:
        raise HTTPException(400, f"Unknown sport. Use one of: {', '.join(VALID_SPORTS)}")
    return sport


def _validate_mode(mode: str) -> str:
    if mode not in VALID_MODES:
        raise HTTPException(400, f"Mode must be one of: {', '.join(VALID_MODES)}")
    return mode


# ═════════════════════════════════════════════════════════════════════
# HTML PAGES
# ═════════════════════════════════════════════════════════════════════

@router.get("/admin/campaigns", response_class=HTMLResponse)
def campaigns_list(request: Request, user: User = Depends(require_login)) -> HTMLResponse:
    with db_session() as session:
        repo = CampaignRepository(session)
        campaigns = repo.list_all()
        match_counts = {c.slug: len(repo.get_match_rows(c.slug)) for c in campaigns}

    return templates.TemplateResponse(
        request,
        "campaigns/list.html",
        {
            "active_page": "campaigns",
            "campaigns": campaigns,
            "match_counts": match_counts,
            "current_user": user,
        },
    )


@router.get("/admin/campaigns/new", response_class=HTMLResponse)
def campaigns_new(request: Request, user: User = Depends(require_role("editor"))) -> HTMLResponse:
    with db_session() as session:
        tournaments_by_sport = {
            s: MatchRepository(session).list_tournaments(sport=s) for s in VALID_SPORTS
        }
    return templates.TemplateResponse(
        request,
        "campaigns/new.html",
        {
            "active_page": "campaigns",
            "current_user": user,
            "valid_sports": VALID_SPORTS,
            "tournaments_by_sport": tournaments_by_sport,
            "error": None,
        },
    )


@router.post("/admin/campaigns")
def campaigns_create(
    request: Request,
    slug: str = Form(...),
    title: str = Form(...),
    sport: str = Form(...),
    mode: str = Form(...),
    league: Optional[str] = Form(None),
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    slug = _validate_slug(slug)
    sport = _validate_sport(sport)
    mode = _validate_mode(mode)
    league_v = _normalise_league(league) if mode == "auto" else None
    title = (title or slug).strip()[:120]

    with db_session() as session:
        repo = CampaignRepository(session)
        if repo.find_by_slug(slug):
            raise HTTPException(400, "A campaign with this slug already exists.")
        repo.create(slug=slug, title=title, sport=sport, mode=mode,
                    league=league_v, created_by=user.username)
        LogRepository(session).record(
            "campaign.create", username=user.username,
            target=slug, payload={"sport": sport, "mode": mode, "league": league_v},
        )

    return RedirectResponse(f"/admin/campaigns/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/campaigns/{slug}", response_class=HTMLResponse)
def campaigns_edit(
    request: Request, slug: str, user: User = Depends(require_login)
) -> HTMLResponse:
    slug = _validate_slug(slug)
    with db_session() as session:
        repo = CampaignRepository(session)
        campaign = repo.find_by_slug(slug)
        if not campaign:
            raise HTTPException(404, "Campaign not found.")
        selected_matches = repo.get_matches(slug)
        tournaments = MatchRepository(session).list_tournaments(sport=campaign.sport)

    return templates.TemplateResponse(
        request,
        "campaigns/edit.html",
        {
            "active_page": "campaigns",
            "current_user": user,
            "campaign": campaign,
            "selected_matches": selected_matches,
            "valid_sports": VALID_SPORTS,
            "tournaments": tournaments,
        },
    )


@router.get("/admin/campaigns/{slug}/edit", response_class=HTMLResponse)
def campaigns_edit_alias(
    request: Request, slug: str, user: User = Depends(require_login)
) -> HTMLResponse:
    return campaigns_edit(request=request, slug=slug, user=user)


@router.get("/admin/campaigns/{slug}/matches")
def campaigns_matches_alias(slug: str, user: User = Depends(require_login)) -> RedirectResponse:
    slug = _validate_slug(slug)
    return RedirectResponse(f"/admin/campaigns/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/campaigns/{slug}")
def campaigns_update(
    request: Request,
    slug: str,
    title: str = Form(...),
    sport: str = Form(...),
    league: Optional[str] = Form(None),
    enabled: Optional[str] = Form(None),
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    slug = _validate_slug(slug)
    sport = _validate_sport(sport)
    with db_session() as session:
        repo = CampaignRepository(session)
        c = repo.find_by_slug(slug)
        if not c:
            raise HTTPException(404)
        # `mode` is fixed at create time. Auto campaigns may change league.
        league_v = _normalise_league(league) if c.mode == "auto" else None
        repo.update(
            slug,
            title=(title or slug).strip()[:120],
            sport=sport,
            league=league_v,
            enabled=bool(enabled),
        )
        LogRepository(session).record(
            "campaign.update", username=user.username,
            target=slug, payload={
                "sport": sport, "league": league_v, "enabled": bool(enabled),
            },
        )
    _cache_invalidate(slug)

    return RedirectResponse(f"/admin/campaigns/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/campaigns/{slug}/delete")
def campaigns_delete(
    slug: str, user: User = Depends(require_role("admin"))
) -> RedirectResponse:
    slug = _validate_slug(slug)
    with db_session() as session:
        repo = CampaignRepository(session)
        if not repo.delete(slug):
            raise HTTPException(404)
        LogRepository(session).record("campaign.delete", username=user.username, target=slug)
    _cache_invalidate(slug)
    return RedirectResponse("/admin/campaigns", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/campaigns/{slug}/toggle")
def campaigns_toggle(
    slug: str, user: User = Depends(require_role("editor"))
) -> RedirectResponse:
    slug = _validate_slug(slug)
    with db_session() as session:
        repo = CampaignRepository(session)
        c = repo.find_by_slug(slug)
        if not c:
            raise HTTPException(404)
        c.enabled = not c.enabled
        LogRepository(session).record(
            "campaign.toggle", username=user.username,
            target=slug, payload={"enabled": c.enabled},
        )
    _cache_invalidate(slug)
    return RedirectResponse(f"/admin/campaigns/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/campaigns/{slug}/duplicate")
def campaigns_duplicate(
    slug: str, user: User = Depends(require_role("admin"))
) -> RedirectResponse:
    slug = _validate_slug(slug)
    new_slug = f"{slug}-copy"
    with db_session() as session:
        repo = CampaignRepository(session)
        src = repo.find_by_slug(slug)
        if not src:
            raise HTTPException(404)
        idx = 1
        candidate = new_slug
        while repo.find_by_slug(candidate):
            idx += 1
            candidate = f"{new_slug}-{idx}"
        repo.create(slug=candidate, title=src.title + " (copy)",
                    sport=src.sport, mode=src.mode, league=src.league,
                    created_by=user.username)
        # copy matches (only meaningful for manual; cheap no-op otherwise)
        match_rows = repo.get_match_rows(slug)
        repo.set_matches(candidate, [r.event_id for r in match_rows])
        LogRepository(session).record(
            "campaign.duplicate", username=user.username,
            target=candidate, payload={"source": slug},
        )

    return RedirectResponse(f"/admin/campaigns/{candidate}", status_code=status.HTTP_303_SEE_OTHER)


# ═════════════════════════════════════════════════════════════════════
# JSON / HTMX endpoints
# ═════════════════════════════════════════════════════════════════════

@router.get("/api/admin/campaigns/{slug}/matches")
def api_list_matches(slug: str, user: User = Depends(require_login)) -> dict:
    slug = _validate_slug(slug)
    with db_session() as session:
        repo = CampaignRepository(session)
        if not repo.find_by_slug(slug):
            raise HTTPException(404)
        matches = repo.get_matches(slug)
    return {
        "ok": True,
        "count": len(matches),
        "matches": [m.to_event_dict() for m in matches],
    }


@router.get("/api/admin/campaigns/{slug}/preview")
def api_preview(
    slug: str,
    limit: Optional[int] = None,
    user: User = Depends(require_login),
) -> dict:
    """Resolve the campaign as the public route would right now.

    Powers the inline preview on auto campaign edit pages so the admin can
    see WHICH matches their league filter will surface without opening the
    PNG. Returns the same shape as /api/admin/campaigns/{slug}/matches.
    """
    slug = _validate_slug(slug)
    n = _clamp_limit(limit) if limit is not None else DEFAULT_AUTO_LIMIT
    warning: Optional[str] = None
    with db_session() as session:
        repo = CampaignRepository(session)
        c = repo.find_by_slug(slug)
        if not c:
            raise HTTPException(404)
        if c.mode == "manual":
            matches = [m for m in repo.get_matches(slug) if m.is_active]
        else:
            engine = HotEngine(session, c.sport, league=c.league)
            matches = engine.resolve(n)
            if not matches:
                if c.league:
                    active_sport_matches = MatchRepository(session).find_active_by_sport(c.sport)
                    if active_sport_matches:
                        warning = (
                            f"League filter \"{c.league}\" matched 0 of {len(active_sport_matches)} "
                            f"candidate {c.sport} matches. The PNG will render empty "
                            f"until the parser sees a match in this league."
                        )
                    else:
                        warning = f"No active {c.sport} matches in the DB right now."
                else:
                    warning = f"No active {c.sport} matches in the DB right now."

        out = [{
            "event_id": m.event_id,
            "home_name": m.home_name,
            "away_name": m.away_name,
            "tournament_name": m.tournament_name,
            "time_raw": m.time_raw,
            "status": m.status,
        } for m in matches]
    return {
        "ok": True,
        "mode": c.mode,
        "league": c.league,
        "limit": n if c.mode == "auto" else None,
        "count": len(out),
        "matches": out,
        "warning": warning,
    }


@router.post("/api/admin/campaigns/{slug}/matches")
def api_add_match(
    slug: str,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> dict:
    slug = _validate_slug(slug)
    event_id = str(body.get("event_id") or "").strip()
    if not event_id:
        raise HTTPException(400, "event_id required")
    with db_session() as session:
        repo = CampaignRepository(session)
        c = repo.find_by_slug(slug)
        if not c:
            raise HTTPException(404)
        if c.mode != "manual":
            raise HTTPException(400, "Only manual campaigns can have manually-added matches.")
        if not MatchRepository(session).find_by_event_id(event_id):
            raise HTTPException(404, "Match not in DB")
        added = repo.add_match(slug, event_id)
        LogRepository(session).record(
            "campaign.match.add", username=user.username,
            target=slug, payload={"event_id": event_id, "new": added},
        )
    _cache_invalidate(slug)
    return {"ok": True, "added": added, "event_id": event_id}


@router.delete("/api/admin/campaigns/{slug}/matches/{event_id}")
def api_remove_match(
    slug: str, event_id: str,
    user: User = Depends(require_role("editor")),
) -> dict:
    slug = _validate_slug(slug)
    with db_session() as session:
        repo = CampaignRepository(session)
        if not repo.remove_match(slug, event_id):
            raise HTTPException(404)
        LogRepository(session).record(
            "campaign.match.remove", username=user.username,
            target=slug, payload={"event_id": event_id},
        )
    _cache_invalidate(slug)
    return {"ok": True}


@router.put("/api/admin/campaigns/{slug}/matches")
def api_reorder_matches(
    slug: str,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> dict:
    slug = _validate_slug(slug)
    event_ids: List[str] = list(body.get("event_ids") or [])
    event_ids = [str(e).strip() for e in event_ids if str(e).strip()]
    if len(event_ids) > 100:
        raise HTTPException(400, "Too many matches in one campaign.")
    if len(event_ids) != len(set(event_ids)):
        raise HTTPException(400, "Duplicate event_ids are not allowed.")
    with db_session() as session:
        repo = CampaignRepository(session)
        c = repo.find_by_slug(slug)
        if not c:
            raise HTTPException(404)
        if c.mode != "manual":
            raise HTTPException(400, "Only manual campaigns have an ordered match list.")
        existing = MatchRepository(session).find_by_event_ids(event_ids)
        if len(existing) != len(event_ids):
            raise HTTPException(400, "One or more matches are no longer available.")
        n = repo.set_matches(slug, event_ids)
        LogRepository(session).record(
            "campaign.match.reorder", username=user.username,
            target=slug, payload={"n": n},
        )
    _cache_invalidate(slug)
    return {"ok": True, "count": n}


@router.get("/api/admin/campaigns/{slug}/picker", response_class=HTMLResponse)
def api_picker_search(
    request: Request,
    slug: str,
    q: str = "",
    sport: str = "",
    tournament: str = "",
    team: str = "",
    user: User = Depends(require_login),
) -> HTMLResponse:
    """HTMX partial: search results for the manual match picker."""
    slug = _validate_slug(slug)
    with db_session() as session:
        c = CampaignRepository(session).find_by_slug(slug)
        if not c:
            raise HTTPException(404)
        effective_sport = sport or c.sport
        repo = MatchRepository(session)
        results = repo.search(
            query=q or None,
            sport=effective_sport,
            tournament=(tournament or None),
            team=(team or None),
            limit=25,
        )
        existing_ids = {r.event_id for r in CampaignRepository(session).get_match_rows(slug)}
        results = [m for m in results if m.event_id not in existing_ids]

    return templates.TemplateResponse(
        request,
        "campaigns/_picker_results.html",
        {"results": results, "slug": slug},
    )
