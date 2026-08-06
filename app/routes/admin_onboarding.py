"""
CRM Onboarding SPA — React + Vite + Tailwind.

  GET /admin/onboarding        → serves the SPA index.html
  GET /admin/onboarding/       → same (trailing slash)

All other sub-paths (assets) are served by the static mount:
  /admin/onboarding/assets/*   → onboarding/dist/assets/*

The SPA handles its own client-side routing, so any unknown sub-path
returns the same index.html.  The static mount must be registered BEFORE
this router, otherwise asset requests would fall through to the wildcard.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from ..auth.dependencies import require_login
from ..models import User

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DIST_DIR = BASE_DIR / "onboarding" / "dist"

router = APIRouter()


def _index() -> FileResponse | HTMLResponse:
    index = DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return HTMLResponse(
        "<h2>Onboarding app not built yet.</h2>"
        "<p>Run <code>cd onboarding && npm install && npm run build</code></p>",
        status_code=503,
    )


@router.get("/admin/onboarding", include_in_schema=False, response_model=None)
@router.get("/admin/onboarding/", include_in_schema=False, response_model=None)
def onboarding_root(_user: User = Depends(require_login)):
    return _index()


@router.get("/admin/onboarding/{rest:path}", include_in_schema=False, response_model=None)
def onboarding_spa(_rest: str, _user: User = Depends(require_login)):
    """Catch-all: return index.html so the client-side router handles the path."""
    return _index()
