#!/usr/bin/env python3
"""
Reset 2FA for a user (e.g. when they lose their phone).

Usage:
  python scripts/reset_2fa.py USERNAME
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import db_session  # noqa: E402
from app.repositories.user_repo import UserRepository  # noqa: E402
from app.repositories.log_repo import LogRepository  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/reset_2fa.py USERNAME", file=sys.stderr)
        return 1
    username = sys.argv[1].strip().lower()

    with db_session() as session:
        u = UserRepository(session).find(username)
        if u is None:
            print(f"User '{username}' not found.", file=sys.stderr)
            return 1
        u.totp_secret = None
        u.totp_enabled = False
        LogRepository(session).record(
            "2fa.reset_by_admin", username=username, payload={"via": "cli"},
        )

    print(f"✓ 2FA reset for '{username}'. They can enroll a new device at /admin/2fa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
