"""
Admin USER management UI.

  GET  /admin/users                            list page (HTML)
  POST /admin/users                            create a user, issue a one-time password
  POST /admin/users/{username}/role            change role
  POST /admin/users/{username}/password        issue a fresh one-time password
  POST /admin/users/{username}/active          enable / disable sign-in
  POST /admin/users/{username}/delete          delete

Admin-only, same as /admin/logs — being able to mint an account is the most
privileged thing in the back office.

Passwords are never typed in by the operator and never travel in a URL: the
server generates a one-time password, shows it EXACTLY ONCE on the page that
created it (rendered directly, not through a redirect, so it cannot land in a
proxy access log or the browser history), and the new user is forced to replace
it on first login via `must_change_password`.

The refusals here exist because the failure they prevent is unrecoverable from
the UI: strip the last active admin of its role and nobody can reach this page
again — the only fix is shell access and `scripts/create_admin.py`.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..auth.dependencies import require_role
from ..auth.password import MIN_PASSWORD_LENGTH, hash_password
from ..database import db_session
from ..logging_config import get_logger
from ..middleware import limiter
from ..models import User
from ..repositories.log_repo import LogRepository
from ..repositories.user_repo import UserRepository

logger = get_logger("app.routes.admin_users")

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

VALID_ROLES = ("admin", "editor", "viewer")
# Same rule as scripts/create_admin.py, so an account made here and one made on
# the CLI can never disagree about what a valid username is.
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")

# One-time password alphabet: no O/0, I/l/1 — this string gets read off a screen
# and retyped, and an ambiguous glyph turns into a support ticket.
_OTP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
_OTP_LENGTH = max(18, MIN_PASSWORD_LENGTH)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _new_otp() -> str:
    return "".join(secrets.choice(_OTP_ALPHABET) for _ in range(_OTP_LENGTH))


def _validate_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            400,
            "Username must be 3-64 characters: lowercase letters, digits, dots, "
            "underscores or hyphens, starting with a letter or digit.",
        )
    return username


def _validate_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(400, f"Role must be one of {', '.join(VALID_ROLES)}.")
    return role


def _render(request: Request, user: User, *, issued: Optional[dict] = None,
            error: str = "") -> HTMLResponse:
    """The list page. `issued` carries a just-created one-time password, which is
    why every mutation renders through here instead of redirecting."""
    with db_session() as session:
        repo = UserRepository(session)
        rows = [
            {
                "username": u.username,
                "role": u.role,
                "is_active": bool(u.is_active),
                "must_change_password": bool(u.must_change_password),
                "last_login_at": u.last_login_at,
                "created_at": getattr(u, "created_at", None),
            }
            for u in repo.all()
        ]
        admins = repo.count_active_admins()
    return templates.TemplateResponse(
        request,
        "users/list.html",
        {
            "active_page": "users",
            "current_user": user,
            "users": rows,
            "roles": VALID_ROLES,
            "active_admins": admins,
            "issued": issued,
            "error": error,
            "otp_length": _OTP_LENGTH,
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
def users_page(
    request: Request,
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    return _render(request, user)


@router.post("/admin/users")
@limiter.limit("20/minute")
def users_create(
    request: Request,
    username: str = Form(...),
    role: str = Form("viewer"),
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    """Create an account and hand back a one-time password, shown once."""
    new_username = _validate_username(username)
    new_role = _validate_role(role)
    otp = _new_otp()
    with db_session() as session:
        repo = UserRepository(session)
        if repo.find(new_username) is not None:
            raise HTTPException(409, f"User '{new_username}' already exists.")
        repo.create(
            username=new_username,
            password_hash=hash_password(otp),
            role=new_role,
            must_change_password=True,
        )
        # The password itself is NEVER audited — only that one was issued.
        LogRepository(session).record(
            "user.create",
            username=user.username,
            target=new_username,
            payload={"role": new_role, "must_change_password": True},
            ip=_client_ip(request),
        )
    logger.info("user.create by=%s target=%s role=%s", user.username, new_username, new_role)
    return _render(request, user, issued={"username": new_username, "password": otp,
                                          "role": new_role, "created": True})


@router.post("/admin/users/{target}/role")
@limiter.limit("20/minute")
def users_set_role(
    target: str,
    request: Request,
    role: str = Form(...),
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    target = _validate_username(target)
    new_role = _validate_role(role)
    with db_session() as session:
        repo = UserRepository(session)
        row = repo.find(target)
        if row is None:
            raise HTTPException(404, f"User '{target}' not found.")
        if row.role == new_role:
            return _render(request, user)
        # Demoting yourself out of admin is the fastest way to lose the back
        # office; demoting the last admin does it for everyone.
        if target == user.username.strip().lower() and new_role != "admin":
            raise HTTPException(
                400, "You cannot change your own role away from admin — ask another "
                     "admin to do it, so there is always someone who can undo it.")
        if row.role == "admin" and new_role != "admin" \
                and repo.count_active_admins(excluding=target) == 0:
            raise HTTPException(
                400, f"'{target}' is the only active admin. Promote someone else to "
                     "admin first, or the back office becomes unreachable.")
        old_role = row.role
        repo.set_role(row, new_role)
        LogRepository(session).record(
            "user.role_change", username=user.username, target=target,
            payload={"from": old_role, "to": new_role}, ip=_client_ip(request),
        )
    return _render(request, user)


@router.post("/admin/users/{target}/password")
@limiter.limit("20/minute")
def users_reset_password(
    target: str,
    request: Request,
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    """Issue a fresh one-time password — the 'they forgot it' path."""
    target = _validate_username(target)
    otp = _new_otp()
    with db_session() as session:
        repo = UserRepository(session)
        row = repo.find(target)
        if row is None:
            raise HTTPException(404, f"User '{target}' not found.")
        repo.set_password(row, hash_password(otp), must_change_password=True)
        LogRepository(session).record(
            "user.password_reset", username=user.username, target=target,
            payload={"must_change_password": True}, ip=_client_ip(request),
        )
    return _render(request, user, issued={"username": target, "password": otp,
                                          "role": None, "created": False})


@router.post("/admin/users/{target}/active")
@limiter.limit("20/minute")
def users_set_active(
    target: str,
    request: Request,
    active: str = Form(...),
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    target = _validate_username(target)
    want_active = str(active).strip().lower() in ("1", "true", "yes", "on")
    with db_session() as session:
        repo = UserRepository(session)
        row = repo.find(target)
        if row is None:
            raise HTTPException(404, f"User '{target}' not found.")
        if not want_active:
            if target == user.username.strip().lower():
                raise HTTPException(400, "You cannot disable your own account.")
            if row.role == "admin" and repo.count_active_admins(excluding=target) == 0:
                raise HTTPException(
                    400, f"'{target}' is the only active admin — disabling it locks "
                         "everyone out of the back office.")
        repo.set_active(row, want_active)
        LogRepository(session).record(
            "user.activate" if want_active else "user.deactivate",
            username=user.username, target=target, ip=_client_ip(request),
        )
    return _render(request, user)


@router.post("/admin/users/{target}/delete")
@limiter.limit("10/minute")
def users_delete(
    target: str,
    request: Request,
    user: User = Depends(require_role("admin")),
) -> HTMLResponse:
    target = _validate_username(target)
    with db_session() as session:
        repo = UserRepository(session)
        row = repo.find(target)
        if row is None:
            raise HTTPException(404, f"User '{target}' not found.")
        if target == user.username.strip().lower():
            raise HTTPException(400, "You cannot delete your own account.")
        if row.role == "admin" and repo.count_active_admins(excluding=target) == 0:
            raise HTTPException(
                400, f"'{target}' is the only active admin — deleting it locks "
                     "everyone out of the back office.")
        repo.delete(target)
        LogRepository(session).record(
            "user.delete", username=user.username, target=target,
            payload={"role": row.role}, ip=_client_ip(request),
        )
    return _render(request, user)
