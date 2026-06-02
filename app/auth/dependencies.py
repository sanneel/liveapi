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
from urllib.parse import quote

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


def _wants_html(request: Request) -> bool:
    """True for a top-level browser navigation (Accept: text/html), as opposed
    to a same-page fetch/XHR API call (Accept: */* or application/json)."""
    return "text/html" in request.headers.get("accept", "").lower()


def _login_redirect_url(request: Request) -> str:
    """`/admin/login?next=<the path they were trying to reach>` so re-login
    lands the operator back where they were."""
    nxt = request.url.path
    if request.url.query:
        nxt = f"{nxt}?{request.url.query}"
    return f"/admin/login?next={quote(nxt, safe='')}"


def _auth_challenge(request: Request) -> HTTPException:
    """Decide how to reject an unauthenticated request.

    Two very different callers reach this branch, and conflating them is what
    made the admin portal look "crashed":

    * A drive-by scanner / crawler with **no session cookie at all** — keep the
      admin surface invisible to them: every protected path returns a flat 404,
      exactly as before (commit 762763a), so they can't enumerate real routes.

    * A real operator whose **session cookie is present but expired/invalid**
      (the access token lapsed mid-shift). They already know these paths exist,
      so a 404 only looks like a broken portal — a raw `{"detail":"Not Found"}`
      wall on every page and a cryptic "Load failed: Not Found" on every save.
      Instead:
        - a full-page navigation (Accept: text/html) → 303 to /admin/login so
          they simply re-authenticate and return to where they were;
        - an API/fetch call → 401 `session_expired`, which the SPA turns into a
          clear notice + redirect rather than a confusing 404.

    The discriminator is **cookie presence**: anonymous scanners carry no
    cookie (→ 404), so the anti-enumeration guarantee is preserved for the only
    traffic it was meant to protect against.
    """
    if not request.cookies.get(COOKIE_NAME):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if _wants_html(request):
        return HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Session expired",
            headers={"Location": _login_redirect_url(request)},
        )
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_expired")


def require_login(request: Request) -> User:
    """Require a valid logged-in user.

    * No session cookie → 404 (anonymous probe; admin surface stays invisible).
    * Expired/invalid session cookie → 303 redirect to /admin/login for browser
      navigations, or 401 `session_expired` for API/fetch calls.
    * Valid → returns the User.

    See `_auth_challenge` for why the no-cookie and stale-cookie cases differ.
    The login page at /admin/login is a separate public route.
    """
    user = _user_from_request(request)
    if user is None:
        raise _auth_challenge(request)
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
