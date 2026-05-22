#!/usr/bin/env python3
"""
Create or update an admin user.

Usage:
  python scripts/create_admin.py              # interactive prompt
  python scripts/create_admin.py --username admin --password 'secret' --role admin
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.password import hash_password  # noqa: E402
from app.database import db_session  # noqa: E402
from app.logging_config import get_logger  # noqa: E402
from app.repositories.user_repo import UserRepository  # noqa: E402

logger = get_logger("create_admin")

VALID_ROLES = ("admin", "editor", "viewer")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update an admin user.")
    parser.add_argument("--username", help="Username (lowercase)")
    parser.add_argument("--password", help="Password (omit to be prompted)")
    parser.add_argument("--role", choices=VALID_ROLES, default="admin")
    args = parser.parse_args()

    username = args.username
    if not username:
        username = input("Username: ").strip()
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        print("Invalid username. Use 3-64 lowercase letters, numbers, dots, underscores, or hyphens.", file=sys.stderr)
        return 1

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords don't match.", file=sys.stderr)
            return 1
    if len(password) < 14:
        print("Password must be at least 14 characters.", file=sys.stderr)
        return 1

    role = args.role
    if role not in VALID_ROLES:
        print(f"Invalid role. Must be one of {VALID_ROLES}.", file=sys.stderr)
        return 1

    with db_session() as session:
        repo = UserRepository(session)
        user = repo.find(username)
        pw_hash = hash_password(password)
        if user is None:
            repo.create(username=username, password_hash=pw_hash, role=role)
            print(f"[success] Created user '{username}' with role '{role}'.")
        else:
            user.password_hash = pw_hash
            user.role = role
            user.is_active = True
            print(f"[success] Updated user '{username}' (role={role}).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
