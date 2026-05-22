"""
Password hashing with bcrypt.

Why bcrypt (not argon2 / scrypt):
  - widely supported, audited
  - tunable work factor
  - 12 rounds = ~250ms on modern hardware (slows brute force)
"""

from __future__ import annotations

import bcrypt

# 12 rounds: ~250ms/hash. Raise if hardware gets faster.
BCRYPT_ROUNDS = 12


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
