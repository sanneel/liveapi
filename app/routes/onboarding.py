"""
Operator onboarding — the guided tour a new joiner walks through on day one.

  GET   /admin/onboarding                  the tour itself (20 screens)  — any login
  GET   /onboarding                        the same page, shorter path   — any login
  GET   /api/admin/onboarding/progress     which practice tasks are done — any login
  POST  /api/admin/onboarding/progress     tick or clear one task        — any login

The page is deliberately *not* built on base.html: it is a full-viewport guided
tour with its own rail, and every screen has to fit without scrolling, which the
admin shell's own header and sidebar would break. The brand mark in its rail
links back to /admin so an operator is never stranded.

Screenshots and the mascot poses live under app/static/onboarding/ and are
served by the existing /static mount, so the browser caches them between
screens instead of re-fetching.

Playground progress is stored per operator, not per browser. The JSON pair lives
under /api/admin/ on purpose: that prefix is covered by the same-origin check in
app/middleware/security.py, so the POST cannot be driven from another site. Task
keys are validated against KNOWN_TASKS rather than trusted from the client, so a
stray or malicious key can never reach the table.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, Depends, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_login
from ..database import db_session
from ..logging_config import get_logger
from ..models import User
from ..repositories.onboarding_repo import OnboardingRepository

logger = get_logger("app.routes.onboarding")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Keep in sync with the TASKS list in templates/onboarding.html.
KNOWN_TASKS = frozenset(
    {
        "chooser-two-prizes",
        "gow-three-tiers",
        "clone-gow",
        "sport-freebet",
        "empty-prize",
        "comms-only",
        "winback-split",
    }
)

router = APIRouter()


def _render(request: Request, user: User) -> HTMLResponse:
    """Part 1 of onboarding: the standards, one live promotion end to end, how we
    track it, and the playground. Read-only, so viewers get it too."""
    logger.info(f"onboarding tour opened by {user.username} at {request.url.path}")
    return templates.TemplateResponse(request, "onboarding.html", {"user": user})


@router.get("/admin/onboarding", response_class=HTMLResponse, include_in_schema=False)
def onboarding_admin_page(request: Request, user: User = Depends(require_login)):
    """The canonical path. It stays under /admin/ because that prefix is what the
    reverse proxy in front of the app already forwards, and because it is the
    link people have in their bookmarks. Served, not redirected: a redirect to a
    top-level path only 404s again wherever the proxy does not forward it."""
    return _render(request, user)


@router.get("/onboarding", response_class=HTMLResponse)
def onboarding_page(request: Request, user: User = Depends(require_login)):
    """The same page at the shorter path, for anyone who has it open already."""
    return _render(request, user)


@router.get("/api/admin/onboarding/progress")
def onboarding_progress(user: User = Depends(require_login)) -> JSONResponse:
    """The practice tasks this operator has finished."""
    with db_session() as session:
        done = OnboardingRepository(session).done_for(user.username)
    return JSONResponse({"done": done})


@router.post("/api/admin/onboarding/progress")
def onboarding_progress_set(
    payload: dict = Body(...),
    user: User = Depends(require_login),
) -> JSONResponse:
    """Tick a task off, or clear it to redo it. Returns the full list either way."""
    task = str(payload.get("task") or "")
    if task not in KNOWN_TASKS:
        return JSONResponse(
            {"detail": "unknown task"}, status_code=status.HTTP_400_BAD_REQUEST
        )
    done_flag = payload.get("done", True) is not False

    with db_session() as session:
        repo = OnboardingRepository(session)
        if done_flag:
            repo.mark(user.username, task)
        else:
            repo.unmark(user.username, task)
        done = repo.done_for(user.username)
    return JSONResponse({"done": done})
