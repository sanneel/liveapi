"""
Admin HOT override API (Phase A) — JSON only, no UI.

  GET    /api/hot/override                       list all overrides
  GET    /api/hot/override/{event_id}            current state for one event
  POST   /api/hot/override/{event_id}            upsert {boost?, pin?}
  DELETE /api/hot/override/{event_id}            remove override entirely

All mutations:
  - require_role('editor')
  - LogRepository.record audit trail
  - invalidate /hot PNG cache for the affected sport
  - rate-limited via slowapi
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import User
from ..repositories.hot_boost_repo import HotBoostRepository
from ..repositories.log_repo import LogRepository
from ..repositories.match_repo import MatchRepository
from ..services import png_cache
from .public_render import _client_ip

logger = get_logger("app.routes.admin_hot_override")

router = APIRouter()
MAX_ABS_BOOST = 1000.0


def _serialize(row) -> Dict[str, Any]:
    return {
        "event_id": row.event_id,
        "boost": float(row.boost),
        "pin": bool(row.pin),
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ──────────────────────────────────────────────────────────────────────
@router.get("/api/hot/override")
def list_overrides(user: User = Depends(require_login)) -> Dict[str, Any]:
    with db_session() as session:
        rows = HotBoostRepository(session).list_all()
        return {"count": len(rows), "overrides": [_serialize(r) for r in rows]}


@router.get("/api/hot/override/{event_id}")
def get_override(event_id: str, user: User = Depends(require_login)) -> Dict[str, Any]:
    with db_session() as session:
        row = HotBoostRepository(session).get(event_id)
        if row is None:
            raise HTTPException(404, "No override for this event_id.")
        return _serialize(row)


@router.post("/api/hot/override/{event_id}")
@limiter.limit("60/minute")
def upsert_override(
    event_id: str,
    request: Request,
    body: dict = Body(...),
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    event_id = (event_id or "").strip()
    if not event_id:
        raise HTTPException(400, "event_id required")

    boost: Optional[float] = None
    pin: Optional[bool] = None
    if "boost" in body:
        try:
            boost = float(body["boost"])
        except (TypeError, ValueError):
            raise HTTPException(400, "boost must be a number")
        if not math.isfinite(boost):
            raise HTTPException(400, "boost must be a finite number")
        if abs(boost) > MAX_ABS_BOOST:
            raise HTTPException(400, f"boost must be between -{MAX_ABS_BOOST:g} and {MAX_ABS_BOOST:g}")
    if "pin" in body:
        if not isinstance(body["pin"], bool):
            raise HTTPException(400, "pin must be a boolean")
        pin = body["pin"]
    if boost is None and pin is None:
        raise HTTPException(400, "Provide at least one of: boost, pin")

    with db_session() as session:
        m = MatchRepository(session).find_by_event_id(event_id)
        if m is None:
            raise HTTPException(404, "Match not in DB")
        row = HotBoostRepository(session).upsert(
            event_id, boost=boost, pin=pin, by=user.username
        )
        LogRepository(session).record(
            "hot_override.upsert",
            username=user.username,
            target=event_id,
            payload={"boost": row.boost, "pin": row.pin, "sport": m.sport},
            ip=_client_ip(request),
        )
        sport = m.sport
        result = _serialize(row)

    # Drop cached PNGs for the affected sport so the change is visible
    # on the next /hot/{sport}.png request.
    png_cache.invalidate_prefix(f"hot:{sport}:")
    return result


@router.delete("/api/hot/override/{event_id}")
@limiter.limit("60/minute")
def delete_override(
    event_id: str,
    request: Request,
    user: User = Depends(require_role("editor")),
) -> Dict[str, Any]:
    with db_session() as session:
        m = MatchRepository(session).find_by_event_id(event_id)
        if HotBoostRepository(session).delete(event_id) is False:
            raise HTTPException(404, "No override for this event_id.")
        LogRepository(session).record(
            "hot_override.delete",
            username=user.username,
            target=event_id,
            payload={"sport": m.sport if m else None},
            ip=_client_ip(request),
        )
        sport = m.sport if m else None

    if sport:
        png_cache.invalidate_prefix(f"hot:{sport}:")
    return {"ok": True, "event_id": event_id}
