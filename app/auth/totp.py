"""
TOTP (RFC 6238) two-factor authentication.

The user scans a QR code with an authenticator app:
  - Google Authenticator
  - Authy
  - 1Password
  - Bitwarden
  - Microsoft Authenticator
  - Any other RFC 6238 compatible app

The app then shows a 6-digit code that changes every 30 seconds.
No SMS. No email. No third-party service. Free forever.
"""

from __future__ import annotations

from typing import Optional

import pyotp


ISSUER = "Jugabet Admin"


def generate_secret() -> str:
    """Return a fresh base32 TOTP secret (32 chars)."""
    return pyotp.random_base32()


def provisioning_uri(username: str, secret: str) -> str:
    """
    Build the otpauth:// URL that gets encoded into the QR code.
    Format:
        otpauth://totp/Issuer:user?secret=BASE32&issuer=Issuer
    """
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=ISSUER,
    )


def verify_code(secret: Optional[str], code: Optional[str]) -> bool:
    """
    Validate a 6-digit code against the secret.

    `valid_window=1` accepts the current code AND the immediately previous/next
    code, so a slow user (or 30s clock skew) still works. Adjust to 0 for strict.
    """
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "").replace("-", "")
    if not code.isdigit() or len(code) != 6:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False
