"""
Login / logout HTTP routes.

  GET  /admin/login       render login form
  POST /admin/login       handle credentials, set JWT cookie, redirect
  POST /admin/logout      clear cookie, redirect to /admin/login

Every attempt — success OR failure — is recorded in admin_logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..repositories.log_repo import LogRepository
from ..repositories.user_repo import UserRepository
from .dependencies import COOKIE_NAME
from .jwt_handler import create_access_token
from .password import verify_password

logger = get_logger("app.auth.routes")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For when behind a known proxy (Cloudflare/Caddy).
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _safe_next_url(value: str, default: str = "/admin") -> str:
    value = (value or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return default
    return value


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/admin", error: Optional[str] = None) -> HTMLResponse:
    next = _safe_next_url(next)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next": next, "error": error},
    )


@router.post("/admin/login")
@limiter.limit("10/minute")  # 10 login attempts/IP/min (separate from the per-user lockout)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/admin"),
) -> RedirectResponse:
    settings = get_settings()
    ip = _client_ip(request)
    username = (username or "").strip().lower()
    next = _safe_next_url(next)

    with db_session() as session:
        users = UserRepository(session)
        logs = LogRepository(session)

        # ── Lockout check ──
        locked, seconds_left = users.is_locked_out(username)
        if locked:
            logs.record(
                "login.lockout", username=username, ip=ip,
                payload={"seconds_left": seconds_left},
            )
            return _redirect_to_login(next, f"Too many failed attempts. Try again in {seconds_left}s.")

        user = users.find(username)
        if user is None or not user.is_active:
            users.record_failure(username)
            logs.record("login.failed", username=username, ip=ip, payload={"reason": "no_user_or_inactive"})
            return _redirect_to_login(next, "Invalid credentials.")

        if not verify_password(password, user.password_hash):
            users.record_failure(username)
            logs.record("login.failed", username=username, ip=ip, payload={"reason": "bad_password"})
            return _redirect_to_login(next, "Invalid credentials.")

        # Success
        users.clear_failures(username)
        users.mark_login(user)

        # 2FA has been removed. Issue a fully-verified token regardless of
        # the legacy `totp_enabled` flag; the column is still on the User
        # model for forward compatibility but is not enforced at login.
        logs.record("login.success", username=username, ip=ip)
        token = create_access_token(user.username, user.role, totp_verified=True)
        redirect_to = next or "/admin"

    response = RedirectResponse(url=redirect_to, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.jwt_access_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    return response


@router.post("/admin/logout")
def logout(request: Request) -> RedirectResponse:
    user = getattr(request.state, "current_user", None)
    username = user.username if user else None
    ip = _client_ip(request)
    with db_session() as session:
        LogRepository(session).record("logout", username=username, ip=ip)

    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def _redirect_to_login(next_url: str, error: str) -> RedirectResponse:
    next_url = _safe_next_url(next_url)
    url = f"/admin/login?next={quote(next_url or '/admin')}&error={quote(error)}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
