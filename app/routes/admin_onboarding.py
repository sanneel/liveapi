"""
CRM Onboarding SPA — React + Vite + Tailwind.

  GET /admin/onboarding        → serves the SPA index.html
  GET /admin/onboarding/       → same (trailing slash)
  GET /admin/onboarding/<any>  → the built file if it exists, else index.html
                                 (the SPA does its own client-side routing)

Everything here is behind `require_login`, assets included. It used to be a
`StaticFiles` mount in server.py, registered before the routers so it would win
the wildcard below — but a Mount takes no dependencies, so the whole SPA and its
bundle answered 200 to anonymous callers while every other /admin/* path 404s.
The course is internal training material that quotes real campaign ids, so it
now goes through the same cloak as the rest of the admin.

Serving files by hand is the price of that. `_safe_path` is what keeps it
honest: the request path is resolved and then checked to be inside dist/, so
`../../.env` cannot be walked out to.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse

from ..auth.dependencies import require_login
from ..models import User

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DIST_DIR = (BASE_DIR / "onboarding" / "dist").resolve()

router = APIRouter()


def _index() -> FileResponse | HTMLResponse:
    index = DIST_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return HTMLResponse(
        "<h2>Onboarding app not built yet.</h2>"
        "<p>Run <code>cd onboarding &amp;&amp; npm install &amp;&amp; npm run build</code></p>",
        status_code=503,
    )


def _safe_path(rest: str) -> Path | None:
    """The requested file inside dist/, or None if it escapes or is not a file.

    `resolve()` collapses any `..` before the containment check, so the check
    cannot be fooled by a path that only looks contained.
    """
    if not rest:
        return None
    try:
        candidate = (DIST_DIR / rest).resolve()
    except (OSError, ValueError):          # malformed path, NUL byte, too long
        return None
    if candidate != DIST_DIR and DIST_DIR not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


@router.get("/admin/onboarding", include_in_schema=False, response_model=None)
@router.get("/admin/onboarding/", include_in_schema=False, response_model=None)
def onboarding_root(_user: User = Depends(require_login)):
    return _index()


@router.get("/admin/onboarding/{rest:path}", include_in_schema=False, response_model=None)
def onboarding_spa(rest: str, _user: User = Depends(require_login)):
    """A built asset if the path names one; otherwise index.html, so the
    client-side router can handle its own deep links."""
    asset = _safe_path(rest)
    if asset is not None:
        # media type is inferred from the suffix — .js, .css, .png all correct
        return FileResponse(str(asset))
    return _index()
