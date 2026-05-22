"""
Logs viewer.

  GET /admin/logs                    last 200 admin actions, filterable
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_role
from ..database import db_session
from ..models import User
from ..repositories.log_repo import LogRepository

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/admin/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    action: Optional[str] = None,
    limit: int = 200,
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    limit = max(10, min(int(limit or 200), 1000))
    with db_session() as session:
        entries = LogRepository(session).recent(limit=limit, action=action or None)

    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "active_page": "logs",
            "current_user": user,
            "entries": entries,
            "filter_action": action or "",
            "limit": limit,
        },
    )
