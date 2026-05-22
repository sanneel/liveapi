"""
JWT encode/decode for admin session tokens.

Tokens carry:
  - sub:  username
  - role: admin | editor | viewer
  - exp:  expiry timestamp
  - iat:  issued-at
  - typ:  "access" | "refresh"

Stored in an HTTPOnly cookie — never readable from JavaScript.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt

from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger("app.auth.jwt")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(username: str, role: str, totp_verified: bool = True) -> str:
    """
    Create an access token.

    `totp_verified=False` is set right after password check when the user has
    2FA enabled — they must hit /admin/2fa/verify before this token grants
    access to anything beyond the 2FA-verify page itself.
    """
    settings = get_settings()
    payload = {
        "sub": username,
        "role": role,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(minutes=settings.jwt_access_expire_minutes)).timestamp()),
        "typ": "access",
        "totp_verified": bool(totp_verified),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a token. Returns None on failure."""
    if not token:
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        logger.debug(f"jwt decode failed: {e}")
        return None
