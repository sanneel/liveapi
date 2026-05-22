"""
Admin users. Roles: admin > editor > viewer.

TOTP 2FA fields are present but unused until Phase 4 enables them.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, String

from .base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    username = Column(String, primary_key=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="viewer")   # admin | editor | viewer
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime, nullable=True)

    # 2FA — populated when the user enrolls; not enforced yet
    totp_secret = Column(String, nullable=True)
    totp_enabled = Column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<User {self.username} role={self.role}>"
