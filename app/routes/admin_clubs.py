"""
Admin CLUB API + UI.

  GET    /admin/clubs                           list page (HTML)
  GET    /admin/clubs/{slug}                    edit page (HTML)
  POST   /admin/clubs                           manual create from list page
  POST   /admin/clubs/{slug}                    update from edit page
  POST   /admin/clubs/{slug}/delete             delete from edit page

  GET    /api/admin/clubs                       list clubs (JSON)
  GET    /api/admin/clubs/{slug}                fetch one (JSON)
  POST   /api/admin/clubs                       manual create {slug, name, logo?}
  PUT    /api/admin/clubs/{slug}                update {name?, logo?}
  DELETE /api/admin/clubs/{slug}                delete

Clubs are admin-only — the parser does NOT auto-create. Slug is immutable.
Clubs render a pure PNG of the team's next upcoming match; there is no CTA
button, no fallback overlay, no HTML landing page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from datetime import datetime

from sqlalchemy import or_

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Club, Match, User
from ..repositories.club_repo import SLUG_RE, ClubRepository
from ..repositories.log_repo import LogRepository
from ..services import png_cache
from .public_render import _client_ip

logger = get_logger("app.routes.admin_clubs")

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _serialize(c: Club) -> Dict[str, Any]:
    return {
        "slug": c.slug,
        "name": c.name,
        "logo": c.logo,
        "hide_opponent_logo": bool(getattr(c, "hide_opponent_logo", False)),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _validate_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "slug must be 2-50 chars, lowercase letters/digits/hyphens.")
    return slug


def _validate_public_url(value: Optional[str], field: str) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(400, f"{field} must be a full https:// URL.")
    if "@" in parsed.netloc:
        raise HTTPException(400, f"{field} must not contain userinfo.")
    return value


def _next_matches_for_slugs(session, slugs: list[str]) -> Dict[str, Match]:
    """One query: for each club slug, find its next upcoming prematch match.

    Cheap because we ask the DB for the union of (home_slug OR away_slug) with
    a single index hit, then post-process the ordered result into per-slug
    "first wins". O(matches involving these clubs), not O(clubs × matches).
    """
    if not slugs:
        return {}
    now = datetime.utcnow()
    rows = (
        session.query(Match)
        .filter(Match.is_active.is_(True))
        .filter(Match.status == "prematch")
        .filter(Match.start_time_utc.is_not(None))
        .filter(Match.start_time_utc > now)
        .filter(or_(Match.home_slug.in_(slugs), Match.away_slug.in_(slugs)))
        .order_by(Match.start_time_utc.asc())
        .all()
    )
    out: Dict[str, Match] = {}
    for m in rows:
        for s in (m.home_slug, m.away_slug):
            if s in slugs and s not in out:
                out[s] = m
    return out


@router.get("/admin/clubs", response_class=HTMLResponse)
def clubs_admin_list(
    request: Request,
    q: str = "",
    user: User = Depends(require_login),
) -> HTMLResponse:
    with db_session() as session:
        rows = ClubRepository(session).list_all(limit=1000)
        if q:
            needle = q.strip().lower()
            rows = [
                c for c in rows
                if needle in c.slug.lower() or needle in c.name.lower()
            ]
        slugs = [c.slug for c in rows]
        next_matches = _next_matches_for_slugs(session, slugs)
        with_match = sum(1 for s in slugs if s in next_matches)
        match_summaries = {}
        for s, m in next_matches.items():
            opponent_name = m.away_name if m.home_slug == s else m.home_name
            match_summaries[s] = {
                "opponent": opponent_name,
                "tournament": m.tournament_name,
                "time_raw": m.time_raw,
                "status": m.status,
            }
    return templates.TemplateResponse(
        request,
        "clubs/list.html",
        {
            "active_page": "clubs",
            "current_user": user,
            "clubs": rows,
            "q": q,
            "match_summaries": match_summaries,
            "stats": {
                "total": len(rows),
                "with_upcoming": with_match,
                "no_upcoming": len(rows) - with_match,
            },
        },
    )


@router.get("/admin/clubs/{slug}", response_class=HTMLResponse)
def clubs_admin_edit(
    request: Request,
    slug: str,
    user: User = Depends(require_login),
) -> HTMLResponse:
    slug = _validate_slug(slug)
    with db_session() as session:
        club = ClubRepository(session).find_by_slug(slug)
        if club is None:
            raise HTTPException(404, "Club not found.")
        next_matches = _next_matches_for_slugs(session, [slug])
        next_match = next_matches.get(slug)
        next_match_dto = None
        if next_match is not None:
            opponent_name = (
                next_match.away_name if next_match.home_slug == slug else next_match.home_name
            )
            opponent_slug = (
                next_match.away_slug if next_match.home_slug == slug else next_match.home_slug
            )
            next_match_dto = {
                "event_id": next_match.event_id,
                "opponent_name": opponent_name,
                "opponent_slug": opponent_slug,
                "tournament": next_match.tournament_name,
                "time_raw": next_match.time_raw,
                "sport": next_match.sport,
            }
    return templates.TemplateResponse(
        request,
        "clubs/edit.html",
        {
            "active_page": "clubs",
            "current_user": user,
            "club": club,
            "next_match": next_match_dto,
        },
    )


@router.post("/admin/clubs")
def clubs_admin_create(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    logo: Optional[str] = Form(None),
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    """Manual club create from the admin list page. Admin-only creation —
    the parser never auto-creates clubs."""
    slug = _validate_slug(slug)
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    logo_v = _validate_public_url(logo, "logo")
    with db_session() as session:
        repo = ClubRepository(session)
        if repo.find_by_slug(slug) is not None:
            raise HTTPException(409, f"Club /{slug} already exists.")
        repo.ensure(slug, name, logo=logo_v)
        LogRepository(session).record(
            "club.create",
            username=user.username,
            target=slug,
            payload={"name": name, "logo": logo_v},
            ip=_client_ip(request),
        )
    return RedirectResponse(f"/admin/clubs/{slug}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/clubs/{slug}")
def clubs_admin_update(
    slug: str,
    request: Request,
    name: str = Form(...),
    logo: Optional[str] = Form(None),
    hide_opponent_logo: Optional[str] = Form(None),
    user: User = Depends(require_role("editor")),
) -> RedirectResponse:
    slug = _validate_slug(slug)
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    fields = {
        "name": name,
        "logo": _validate_public_url(logo, "logo"),
        "hide_opponent_logo": bool(hide_opponent_logo),
    }
    with db_session() as session:
        repo = ClubRepository(session)
        if repo.find_by_slug(slug) is None:
            raise HTTPException(404, "Club not found.")
        repo.update(slug, **fields)
        LogRepository(session).record(
            "club.update",
            username=user.username,
            target=slug,
            payload=fields,
            ip=_client_ip(request),
        )
    png_cache.invalidate(f"club:{slug}")
    return RedirectResponse(f"/admin/clubs/{slug}", status_code=status.HTTP_303_SEE_OTHER)


# ──────────────────────────────────────────────────────────────────────
@router.get("/api/admin/clubs")
def list_clubs(
    limit: int = 500, offset: int = 0, user: User = Depends(require_login)
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 500), 1000))
    offset = max(0, int(offset or 0))
    with db_session() as session:
        rows = ClubRepository(session).list_all(limit=limit, offset=offset)
        return {"count": len(rows), "clubs": [_serialize(r) for r in rows]}


@router.get("/api/admin/clubs/{slug}")
def get_club(slug: str, user: User = Depends(require_login)) -> Dict[str, Any]:
    slug = _validate_slug(slug)
    with db_session() as session:
        c = ClubRepository(session).find_by_slug(slug)
        if c is None:
            raise HTTPException(404, "Club not found.")
        return _serialize(c)


@router.post("/api/admin/clubs")
@limiter.limit("60/minute")
def create_club(
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    slug = _validate_slug(str(body.get("slug") or ""))
    name = (str(body.get("name") or "")).strip()
    if not name:
        raise HTTPException(400, "name required")
    logo: Optional[str] = _validate_public_url(body.get("logo") or None, "logo")

    with db_session() as session:
        repo = ClubRepository(session)
        existing = repo.find_by_slug(slug)
        if existing is not None:
            raise HTTPException(409, "Club already exists.")
        c = repo.ensure(slug, name, logo=logo)
        if c is None:
            raise HTTPException(400, "Failed to create club.")
        LogRepository(session).record(
            "club.create",
            username=user.username,
            target=slug,
            payload={"name": name},
            ip=_client_ip(request),
        )
        result = _serialize(c)

    png_cache.invalidate(f"club:{slug}")
    return result


@router.put("/api/admin/clubs/{slug}")
@limiter.limit("60/minute")
def update_club(
    slug: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    slug = _validate_slug(slug)
    fields: Dict[str, Any] = {}
    for k in ("name", "logo"):
        if k in body:
            v = body[k]
            if v is None or isinstance(v, str):
                fields[k] = (v.strip() if isinstance(v, str) else None) or None
    if "logo" in fields:
        fields["logo"] = _validate_public_url(fields["logo"], "logo")
    if not fields:
        raise HTTPException(400, "No editable fields provided.")
    with db_session() as session:
        repo = ClubRepository(session)
        if repo.find_by_slug(slug) is None:
            raise HTTPException(404, "Club not found.")
        c = repo.update(slug, **fields)
        LogRepository(session).record(
            "club.update",
            username=user.username,
            target=slug,
            payload=fields,
            ip=_client_ip(request),
        )
        result = _serialize(c)

    png_cache.invalidate(f"club:{slug}")
    return result


@router.delete("/api/admin/clubs/{slug}")
@limiter.limit("10/minute")
def delete_club(
    slug: str,
    request: Request,
    user: User = Depends(require_role("admin")),
) -> Dict[str, Any]:
    slug = _validate_slug(slug)
    with db_session() as session:
        if not ClubRepository(session).delete(slug):
            raise HTTPException(404, "Club not found.")
        LogRepository(session).record(
            "club.delete",
            username=user.username,
            target=slug,
            ip=_client_ip(request),
        )
    png_cache.invalidate(f"club:{slug}")
    return {"ok": True, "slug": slug}


@router.post("/admin/clubs/{slug}/delete")
def clubs_admin_delete(
    slug: str,
    request: Request,
    user: User = Depends(require_role("admin")),
) -> RedirectResponse:
    slug = _validate_slug(slug)
    with db_session() as session:
        if not ClubRepository(session).delete(slug):
            raise HTTPException(404, "Club not found.")
        LogRepository(session).record(
            "club.delete",
            username=user.username,
            target=slug,
            ip=_client_ip(request),
        )
    png_cache.invalidate(f"club:{slug}")
    return RedirectResponse("/admin/clubs", status_code=status.HTTP_303_SEE_OTHER)
