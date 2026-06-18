"""
User repository.

Includes simple in-memory brute-force tracking — N failed attempts from the
same username within the window locks them out temporarily. Per-IP lockout
is enforced by slowapi in the route layer (Phase 5).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..config import get_settings
from ..logging_config import get_logger
from ..models import User

logger = get_logger("app.repositories.user")


# ─── In-memory failed-login tracker ────────────────────────────────────
_attempts_lock = threading.Lock()
_attempts: Dict[str, List[datetime]] = {}  # username -> list of recent fail timestamps


def _is_locked_out(username: str) -> Tuple[bool, Optional[int]]:
    settings = get_settings()
    window = timedelta(minutes=settings.admin_login_lockout_minutes)
    now = datetime.utcnow()
    with _attempts_lock:
        fails = [t for t in _attempts.get(username, []) if (now - t) < window]
        _attempts[username] = fails
        if len(fails) >= settings.admin_login_max_attempts:
            unlock_at = max(fails) + window
            seconds_left = max(0, int((unlock_at - now).total_seconds()))
            return True, seconds_left
        return False, None


def _record_failure(username: str) -> None:
    with _attempts_lock:
        _attempts.setdefault(username, []).append(datetime.utcnow())


def _clear_failures(username: str) -> None:
    with _attempts_lock:
        _attempts.pop(username, None)


# ─── Repository ────────────────────────────────────────────────────────
class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find(self, username: str) -> Optional[User]:
        return self.session.get(User, username.strip().lower())

    def create(
        self,
        username: str,
        password_hash: str,
        role: str = "viewer",
        must_change_password: bool = False,
    ) -> User:
        user = User(
            username=username.strip().lower(),
            password_hash=password_hash,
            role=role,
            is_active=True,
            must_change_password=must_change_password,
        )
        self.session.add(user)
        logger.info(
            f"user.create username={user.username} role={role} "
            f"must_change_password={must_change_password}"
        )
        return user

    def set_password(
        self, user: User, password_hash: str, must_change_password: bool = False
    ) -> None:
        """Set a new password hash and the one-time-password flag together."""
        user.password_hash = password_hash
        user.must_change_password = must_change_password
        logger.info(
            f"user.set_password username={user.username} "
            f"must_change_password={must_change_password}"
        )

    def all(self) -> List[User]:
        return self.session.query(User).order_by(User.username).all()

    def delete(self, username: str) -> bool:
        user = self.find(username)
        if user is None:
            return False
        self.session.delete(user)
        logger.info(f"user.delete username={user.username}")
        return True

    def count(self) -> int:
        return self.session.query(User).count()

    def mark_login(self, user: User) -> None:
        user.last_login_at = datetime.utcnow()

    # ── lockout state ───────────────────────────────────────────────
    def is_locked_out(self, username: str) -> Tuple[bool, Optional[int]]:
        return _is_locked_out(username.strip().lower())

    def record_failure(self, username: str) -> None:
        _record_failure(username.strip().lower())

    def clear_failures(self, username: str) -> None:
        _clear_failures(username.strip().lower())
