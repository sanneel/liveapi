"""
Password hashing with bcrypt.

Why bcrypt (not argon2 / scrypt):
  - widely supported, audited
  - tunable work factor
  - 12 rounds = ~250ms on modern hardware (slows brute force)
"""

from __future__ import annotations

from typing import Optional

import bcrypt

# 12 rounds: ~250ms/hash. Raise if hardware gets faster.
BCRYPT_ROUNDS = 12

# Minimum password length. Kept in sync with scripts/create_admin.py so a
# one-time password issued there always satisfies the change-password form.
MIN_PASSWORD_LENGTH = 14


def validate_password_strength(plain: str) -> Optional[str]:
    """Return an error message if the password is too weak, else None."""
    if not plain:
        return "Password cannot be empty."
    if len(plain) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the password (utf-8 string)."""
    if not plain:
        raise ValueError("password cannot be empty")
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time password check. Returns False for invalid hashes."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
