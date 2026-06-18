"""
Tutorial library — admin upload + per-operator playback.

  GET  /admin/tutorials              management page (list + upload form) — admin
  POST /admin/tutorials              upload a video with a title           — admin
  POST /admin/tutorials/{id}/delete  remove a tutorial + its file          — admin
  GET  /api/admin/tutorials          JSON list for the Help modal          — any login

Video files are stored under app/static/tutorials/<uuid>.<ext> and served by
the existing /static mount. The stored filename is always a server-generated
UUID — the uploaded name is never used as a path, so there's no traversal risk.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_login, require_role
from ..database import db_session
from ..logging_config import get_logger
from ..models import User
from ..repositories.log_repo import LogRepository
from ..repositories.tutorial_repo import TutorialRepository

logger = get_logger("app.routes.admin_tutorials")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TUTORIALS_DIR = BASE_DIR / "static" / "tutorials"

# Accept the common browser-playable container formats only.
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v"}
MAX_TITLE_LENGTH = 120
MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB
_CHUNK = 1024 * 1024

router = APIRouter()


def _save_upload(upload: UploadFile) -> tuple[str, int]:
    """Stream the upload to disk under a generated name. Returns (filename, size).
    Raises ValueError on a bad extension or oversize file."""
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "Unsupported file type. Use one of: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
        )

    TUTORIALS_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}{ext}"
    dest = TUTORIALS_DIR / stored_name

    total = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = upload.file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError("File is too large (max 512 MB).")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return stored_name, total


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


@router.get("/admin/tutorials", response_class=HTMLResponse)
def tutorials_page(
    request: Request,
    saved: int = 0,
    deleted: int = 0,
    error: str = "",
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    with db_session() as session:
        tutorials = TutorialRepository(session).list_all()
        session.expunge_all()
    return templates.TemplateResponse(
        request,
        "tutorials/index.html",
        {
            "active_page": "tutorials",
            "current_user": user,
            "tutorials": tutorials,
            "saved": bool(saved),
            "deleted": bool(deleted),
            "error": error,
            "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        },
    )


@router.post("/admin/tutorials")
def tutorials_upload(
    request: Request,
    title: str = Form(...),
    video: UploadFile = File(...),
    user: User = Depends(require_role("admin")),
) -> RedirectResponse:
    title = (title or "").strip()

    def _retry(message: str) -> RedirectResponse:
        return RedirectResponse(
            f"/admin/tutorials?{urlencode({'error': message})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not title:
        return _retry("Please enter a title.")
    if len(title) > MAX_TITLE_LENGTH:
        return _retry(f"Title must be {MAX_TITLE_LENGTH} characters or fewer.")
    if not video or not video.filename:
        return _retry("Please choose a video file.")

    try:
        stored_name, size = _save_upload(video)
    except ValueError as exc:
        return _retry(str(exc))
    except Exception:
        logger.exception("tutorial upload failed")
        return _retry("Upload failed. Please try again.")

    with db_session() as session:
        TutorialRepository(session).create(
            title=title,
            filename=stored_name,
            original_name=video.filename,
            content_type=video.content_type,
            size_bytes=size,
            uploaded_by=user.username,
        )
        LogRepository(session).record(
            "tutorial.upload", username=user.username, ip=_client_ip(request),
            payload={"title": title, "filename": stored_name, "size": size},
        )

    return RedirectResponse(
        f"/admin/tutorials?{urlencode({'saved': 1})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/tutorials/{tutorial_id}/delete")
def tutorials_delete(
    request: Request,
    tutorial_id: int,
    user: User = Depends(require_role("admin")),
) -> RedirectResponse:
    with db_session() as session:
        repo = TutorialRepository(session)
        tutorial = repo.get(tutorial_id)
        if tutorial is not None:
            stored_name = tutorial.filename
            repo.delete(tutorial)
            LogRepository(session).record(
                "tutorial.delete", username=user.username, ip=_client_ip(request),
                payload={"id": tutorial_id, "filename": stored_name},
            )
            # Best-effort: remove the file after the row is gone.
            (TUTORIALS_DIR / stored_name).unlink(missing_ok=True)

    return RedirectResponse(
        f"/admin/tutorials?{urlencode({'deleted': 1})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/api/admin/tutorials")
def tutorials_api(request: Request, user: User = Depends(require_login)) -> JSONResponse:
    """Title + playback URL list for the Help modal (any logged-in operator)."""
    with db_session() as session:
        items = [
            {"id": t.id, "title": t.title, "url": f"/static/tutorials/{quote(t.filename)}"}
            for t in TutorialRepository(session).list_all()
        ]
    return JSONResponse(items)
