"""
FastAPI dependencies for auth.

Usage:
    @router.get("/admin/something")
    def view(user: User = Depends(require_role("editor"))):
        ...

  current_user(request) -> User | None    cookie present + valid? returns the User
  require_login         -> User           redirects to /admin/login if not logged in
  require_role(role)    -> User           same but also checks role hierarchy

Role hierarchy: admin > editor > viewer
A user with role X also satisfies require_role(Y) where Y ≤ X.
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import HTTPException, Request, status

from ..database import db_session
from ..logging_config import get_logger
from ..models import User
from .jwt_handler import decode_token

logger = get_logger("app.auth.deps")

COOKIE_NAME = "jugabet_session"


ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}


def _user_from_request(request: Request, require_totp: bool = True) -> Optional[User]:
    # NOTE: 2FA has been removed from the user-facing flow. `require_totp`
    # is kept as a parameter only for backward compatibility with callers
    # like `_user_pending_totp` that previously needed it. The TOTP gate
    # below is now a no-op; legacy `totp_enabled` rows in the DB are
    # ignored at auth time.
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("typ") != "access":
        return None
    username = payload.get("sub")
    if not username:
        return None

    with db_session() as session:
        user = session.get(User, username)
        if user is None or not user.is_active:
            return None
        session.expunge(user)
        return user


def _user_pending_totp(request: Request) -> Optional[User]:
    """Return the user only when they're awaiting TOTP verification.
       Used by /admin/2fa/verify itself."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("typ") != "access":
        return None
    username = payload.get("sub")
    if not username:
        return None
    with db_session() as session:
        user = session.get(User, username)
        if user is None or not user.is_active or not user.totp_enabled:
            return None
        session.expunge(user)
        return user


def current_user(request: Request) -> Optional[User]:
    """Returns the logged-in User or None. Use this for optional auth."""
    user = _user_from_request(request)
    request.state.current_user = user
    return user


def require_login(request: Request) -> User:
    """Require a valid logged-in user, else return 404.

    We deliberately return 404 (not a 307 redirect to /admin/login) for
    unauthenticated requests so anonymous probes can't enumerate which admin
    paths are real — every protected path looks equally non-existent. The login
    page at /admin/login is a separate public route and stays reachable, so
    operators simply start there.
    """
    user = _user_from_request(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    request.state.current_user = user
    return user


def require_role(min_role: str) -> Callable:
    """Dependency factory: require at least `min_role`. e.g. require_role('editor')."""
    min_rank = ROLE_RANK.get(min_role, 0)
    if min_rank == 0:
        raise ValueError(f"unknown role: {min_role}")

    def _dep(request: Request) -> User:
        user = require_login(request)
        user_rank = ROLE_RANK.get(user.role, 0)
        if user_rank < min_rank:
            logger.warning(
                f"forbidden: user={user.username} role={user.role} needed={min_role}"
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dep
