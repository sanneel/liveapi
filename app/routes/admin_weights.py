"""
Admin "Weights" — manage the per-sport hot-scoring weights from the UI.

  GET    /admin/weights                          HTML page (sport selector + table)
  GET    /api/admin/weights/{sport}              list weights for a sport
  POST   /api/admin/weights/{sport}              create a weight
  PUT    /api/admin/weights/{sport}/{weight_id}  update a weight
  DELETE /api/admin/weights/{sport}/{weight_id}  delete a weight
  GET    /api/admin/weights/{sport}/leaderboard  top-N matches by score + the
                                                 weight breakdown each one earned

Every mutation:
  - require_role('editor')
  - audit log via LogRepository
  - weights_provider.invalidate(sport) so the next scoring cycle re-reads the DB
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError

from ..auth.dependencies import require_login, require_role
from ..config import get_settings
from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import Match, User
from ..models.hot_weight import WEIGHT_KINDS
from ..repositories.hot_weight_repo import HotWeightRepository
from ..repositories.log_repo import LogRepository
from ..repositories.match_repo import MatchRepository
from ..services import weights_provider
from ..services.hot_scoring_dispatch import run_scoring
from .public_render import _client_ip

logger = get_logger("app.routes.admin_weights")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

# Sports the weights UI exposes. Only those with a DB seed source are fully
# editable today (see weights_provider._SEED_SOURCES); the rest still show
# their slice (empty until seeded) so the page never 404s on a valid sport.
VALID_SPORTS = (
    "football", "basketball", "tennis", "cybersport",
    "ufc", "mma", "boxing",
)
LEADERBOARD_TOP_N = 10
MAX_ABS_POINTS = 100000


def _validate_sport(sport: str) -> str:
    sport = (sport or "").strip().lower()
    if sport not in VALID_SPORTS:
        raise HTTPException(400, f"Unknown sport. Use one of: {', '.join(VALID_SPORTS)}")
    return sport


def _parse_dt(value: Any) -> Optional[datetime]:
    """Accept '', None, 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DD HH:MM' -> datetime|None."""
    if value in (None, ""):
        return None
    s = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise HTTPException(400, f"Invalid date/time: {value!r} (use YYYY-MM-DD HH:MM)")


def _serialize(row) -> Dict[str, Any]:
    return {
        "id": row.id,
        "sport": row.sport,
        "kind": row.kind,
        "pattern": row.pattern,
        "points": int(row.points),
        "enabled": bool(row.enabled),
        "note": row.note,
        "starts_at": row.starts_at.isoformat(sep=" ", timespec="minutes") if row.starts_at else None,
        "ends_at": row.ends_at.isoformat(sep=" ", timespec="minutes") if row.ends_at else None,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _validate_points(raw: Any) -> int:
    try:
        pts = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, "points must be an integer")
    if abs(pts) > MAX_ABS_POINTS:
        raise HTTPException(400, f"points must be between -{MAX_ABS_POINTS} and {MAX_ABS_POINTS}")
    return pts


# ═════════════════════════════════════════════════════════════════════
# HTML
# ═════════════════════════════════════════════════════════════════════

@router.get("/admin/weights", response_class=HTMLResponse)
def weights_page(
    request: Request,
    sport: str = "football",
    user: User = Depends(require_login),
) -> HTMLResponse:
    sport = _validate_sport(sport)
    return templates.TemplateResponse(
        request,
        "weights/index.html",
        {
            "active_page": "weights",
            "current_user": user,
            "sport": sport,
            "sports": VALID_SPORTS,
            "kinds": WEIGHT_KINDS,
            "top_n": LEADERBOARD_TOP_N,
        },
    )


# ═════════════════════════════════════════════════════════════════════
# JSON API — CRUD
# ═════════════════════════════════════════════════════════════════════

@router.get("/api/admin/weights/{sport}")
def api_list(sport: str, user: User = Depends(require_login)) -> Dict[str, Any]:
    sport = _validate_sport(sport)
    # Populate the table from the static weights file the first time this
    # sport is viewed, so the list isn't empty before any scoring cycle runs.
    weights_provider.ensure_seeded(sport)
    with db_session() as session:
        rows = HotWeightRepository(session).list_for_sport(sport)
        data = [_serialize(r) for r in rows]
    return {
        "sport": sport,
        "kinds": list(WEIGHT_KINDS),
        "managed": weights_provider.has_db_weights(sport),
        "count": len(data),
        "weights": data,
    }


@router.post("/api/admin/weights/{sport}")
@limiter.limit("60/minute")
def api_create(
    sport: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    sport = _validate_sport(sport)
    kind = (body.get("kind") or "").strip().lower()
    if kind not in WEIGHT_KINDS:
        raise HTTPException(400, f"kind must be one of: {', '.join(WEIGHT_KINDS)}")
    pattern = (body.get("pattern") or "").strip()
    if not pattern:
        raise HTTPException(400, "pattern required")
    points = _validate_points(body.get("points"))
    starts_at = _parse_dt(body.get("starts_at"))
    ends_at = _parse_dt(body.get("ends_at"))
    if starts_at and ends_at and ends_at < starts_at:
        raise HTTPException(400, "ends_at must be after starts_at")

    with db_session() as session:
        repo = HotWeightRepository(session)
        try:
            row = repo.create(
                sport=sport,
                kind=kind,
                pattern=pattern,
                points=points,
                note=(body.get("note") or None),
                starts_at=starts_at,
                ends_at=ends_at,
                enabled=bool(body.get("enabled", True)),
                by=user.username,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except IntegrityError:
            # The (sport, kind, pattern) unique constraint.
            raise HTTPException(409, "A weight with this kind + pattern already exists.")
        LogRepository(session).record(
            "weights.create",
            username=user.username,
            target=sport,
            payload={"kind": kind, "pattern": pattern, "points": points},
            ip=_client_ip(request),
        )
        result = _serialize(row)

    weights_provider.invalidate(sport)
    return result


@router.put("/api/admin/weights/{sport}/{weight_id}")
@limiter.limit("120/minute")
def api_update(
    sport: str,
    weight_id: int,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    sport = _validate_sport(sport)
    fields: Dict[str, Any] = {}
    if "kind" in body:
        fields["kind"] = body["kind"]
    if "pattern" in body:
        fields["pattern"] = body["pattern"]
    if "points" in body:
        fields["points"] = _validate_points(body["points"])
    if "enabled" in body:
        fields["enabled"] = bool(body["enabled"])
    if "note" in body:
        fields["note"] = (body.get("note") or None)
    if "starts_at" in body:
        fields["starts_at"] = _parse_dt(body.get("starts_at"))
    if "ends_at" in body:
        fields["ends_at"] = _parse_dt(body.get("ends_at"))
    if not fields:
        raise HTTPException(400, "No editable fields provided.")

    with db_session() as session:
        repo = HotWeightRepository(session)
        existing = repo.get(weight_id)
        if existing is None or existing.sport != sport:
            raise HTTPException(404, "Weight not found for this sport.")
        try:
            row = repo.update(weight_id, by=user.username, **fields)
            session.flush()  # surface the unique-constraint violation here, as 409
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except IntegrityError:
            raise HTTPException(409, "A weight with this kind + pattern already exists.")
        LogRepository(session).record(
            "weights.update",
            username=user.username,
            target=sport,
            payload={"id": weight_id, **{k: str(v) for k, v in fields.items()}},
            ip=_client_ip(request),
        )
        result = _serialize(row)

    weights_provider.invalidate(sport)
    return result


@router.delete("/api/admin/weights/{sport}/{weight_id}")
@limiter.limit("60/minute")
def api_delete(
    sport: str,
    weight_id: int,
    request: Request,
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    sport = _validate_sport(sport)
    with db_session() as session:
        repo = HotWeightRepository(session)
        existing = repo.get(weight_id)
        if existing is None or existing.sport != sport:
            raise HTTPException(404, "Weight not found for this sport.")
        repo.delete(weight_id)
        LogRepository(session).record(
            "weights.delete",
            username=user.username,
            target=sport,
            payload={"id": weight_id, "pattern": existing.pattern},
            ip=_client_ip(request),
        )

    weights_provider.invalidate(sport)
    return {"ok": True, "id": weight_id}


# ═════════════════════════════════════════════════════════════════════
# JSON API — leaderboard (top matches + weight breakdown)
# ═════════════════════════════════════════════════════════════════════

@router.get("/api/admin/weights/{sport}/leaderboard")
def api_leaderboard(
    sport: str,
    limit: int = LEADERBOARD_TOP_N,
    user: User = Depends(require_login),
) -> Dict[str, Any]:
    """Score every active candidate with the CURRENT weights (debug mode, so
    each match carries `_hot_score` + `_hot_reasons`) and return the top N.

    This is computed live — it always reflects the latest weights, including
    edits made seconds ago, so the operator can immediately see the effect."""
    sport = _validate_sport(sport)
    limit = max(1, min(int(limit or LEADERBOARD_TOP_N), 50))

    if sport == "fights":
        sports_in_scope = ("boxing", "mma", "ufc")
    else:
        sports_in_scope = (sport,)

    with db_session() as session:
        match_repo = MatchRepository(session)
        candidates: List[Match] = []
        for s in sports_in_scope:
            candidates.extend(match_repo.find_active_by_sport(s))
        by_id = {m.event_id: m for m in candidates}

        events = []
        for m in candidates:
            d = m.to_event_dict()
            d["sport"] = m.sport
            events.append(d)

    tz = get_settings().forced_timezone
    # with_scores=True → scorer runs in debug mode and attaches _hot_score and
    # _hot_reasons. Ask for plenty so the diversity caps in pick_hot don't
    # truncate the ranking before we slice the top N.
    scored = run_scoring(events, sport, max(limit, 50), tz, with_scores=True)

    rows: List[Dict[str, Any]] = []
    for rank, e in enumerate(scored[:limit], start=1):
        m = by_id.get(e.get("event_id"))
        rows.append({
            "rank": rank,
            "event_id": e.get("event_id"),
            "home_name": m.home_name if m else (e.get("competitors", {}).get("home", {}) or {}).get("name"),
            "away_name": m.away_name if m else (e.get("competitors", {}).get("away", {}) or {}).get("name"),
            "tournament_name": m.tournament_name if m else (e.get("tournament", {}) or {}).get("name"),
            "status": e.get("status"),
            "score": e.get("_hot_score"),
            "reasons": e.get("_hot_reasons") or [],
        })

    return {
        "sport": sport,
        "top_n": limit,
        "candidates_scored": len(events),
        "rows": rows,
    }
