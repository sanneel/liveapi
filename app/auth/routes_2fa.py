"""
TOTP 2FA HTTP routes.

  GET  /admin/2fa             enrollment page (QR + setup)
  POST /admin/2fa/enable      verify code, flip totp_enabled=True
  POST /admin/2fa/disable     turn off 2FA (requires current code)

  GET  /admin/2fa/verify      shown after password login when 2FA is on
  POST /admin/2fa/verify      validate 6-digit code, upgrade token
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..database import db_session
from ..logging_config import get_logger
from ..models import User
from ..repositories.log_repo import LogRepository
from .dependencies import COOKIE_NAME, _user_from_request, _user_pending_totp, require_login
from .jwt_handler import create_access_token
from .totp import generate_secret, provisioning_uri, verify_code

logger = get_logger("app.auth.2fa")

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _client_ip(request: Request) -> str:
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


# ═════════════════════════════════════════════════════════════════════
# ENROLLMENT  (logged-in user enables 2FA)
# ═════════════════════════════════════════════════════════════════════

@router.get("/admin/2fa", response_class=HTMLResponse)
def setup_page(request: Request, user: User = Depends(require_login)) -> HTMLResponse:
    """Either show 'Enable 2FA' (with QR) or 'Disable 2FA' depending on state."""
    if user.totp_enabled:
        return templates.TemplateResponse(
            request,
            "2fa/manage.html",
            {"active_page": "2fa", "current_user": user},
        )

    # Generate a *pending* secret. We don't save it until the user confirms
    # by entering a valid code below. The secret lives in the session for now.
    with db_session() as session:
        u = session.get(User, user.username)
        if not u.totp_secret:
            u.totp_secret = generate_secret()
        secret = u.totp_secret
    uri = provisioning_uri(user.username, secret)

    return templates.TemplateResponse(
        request,
        "2fa/setup.html",
        {
            "active_page": "2fa",
            "current_user": user,
            "secret": secret,
            "otpauth_uri": uri,
        },
    )


@router.post("/admin/2fa/enable")
def enable_2fa(
    request: Request,
    code: str = Form(...),
    user: User = Depends(require_login),
) -> RedirectResponse:
    settings = get_settings()
    ip = _client_ip(request)

    with db_session() as session:
        u = session.get(User, user.username)
        if not u.totp_secret:
            raise HTTPException(400, "No pending secret. Reload the setup page.")
        if not verify_code(u.totp_secret, code):
            LogRepository(session).record(
                "2fa.enable.failed", username=u.username, ip=ip,
            )
            return RedirectResponse("/admin/2fa?error=bad_code", status_code=status.HTTP_303_SEE_OTHER)
        u.totp_enabled = True
        LogRepository(session).record("2fa.enabled", username=u.username, ip=ip)

    # Re-issue the cookie with totp_verified=True so the user stays logged in.
    token = create_access_token(user.username, user.role, totp_verified=True)
    response = RedirectResponse("/admin?2fa=enabled", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        max_age=settings.jwt_access_expire_minutes * 60,
        httponly=True, secure=settings.cookie_secure,
        samesite=settings.cookie_samesite, path="/",
    )
    return response


@router.post("/admin/2fa/disable")
def disable_2fa(
    request: Request,
    code: str = Form(...),
    user: User = Depends(require_login),
) -> RedirectResponse:
    ip = _client_ip(request)
    with db_session() as session:
        u = session.get(User, user.username)
        if not u.totp_enabled:
            return RedirectResponse("/admin/2fa", status_code=status.HTTP_303_SEE_OTHER)
        if not verify_code(u.totp_secret, code):
            LogRepository(session).record("2fa.disable.failed", username=u.username, ip=ip)
            return RedirectResponse("/admin/2fa?error=bad_code", status_code=status.HTTP_303_SEE_OTHER)
        u.totp_enabled = False
        u.totp_secret = None
        LogRepository(session).record("2fa.disabled", username=u.username, ip=ip)

    return RedirectResponse("/admin/2fa?disabled=1", status_code=status.HTTP_303_SEE_OTHER)


# ═════════════════════════════════════════════════════════════════════
# POST-LOGIN VERIFY (user already passed password, must enter code)
# ═════════════════════════════════════════════════════════════════════

@router.get("/admin/2fa/verify", response_class=HTMLResponse)
def verify_page(request: Request, next: str = "/admin", error: str = "") -> HTMLResponse:
    next = _safe_next_url(next)
    # This page is only reachable if you have a pending-totp cookie.
    user = _user_pending_totp(request)
    if user is None:
        return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "2fa/verify.html",
        {"next": next, "error": error},
    )


@router.post("/admin/2fa/verify")
def verify_submit(
    request: Request,
    code: str = Form(...),
    next: str = Form("/admin"),
) -> RedirectResponse:
    settings = get_settings()
    ip = _client_ip(request)
    next = _safe_next_url(next)
    user = _user_pending_totp(request)
    if user is None:
        return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)

    with db_session() as session:
        u = session.get(User, user.username)
        if not verify_code(u.totp_secret, code):
            LogRepository(session).record(
                "login.2fa_failed", username=u.username, ip=ip,
            )
            return RedirectResponse(
                f"/admin/2fa/verify?next={quote(next)}&error=Invalid code",
                status_code=status.HTTP_303_SEE_OTHER,
            )
        LogRepository(session).record("login.2fa_ok", username=u.username, ip=ip)

    token = create_access_token(user.username, user.role, totp_verified=True)
    response = RedirectResponse(next or "/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME, value=token,
        max_age=settings.jwt_access_expire_minutes * 60,
        httponly=True, secure=settings.cookie_secure,
        samesite=settings.cookie_samesite, path="/",
    )
    return response
