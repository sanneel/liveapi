#!/usr/bin/env python3
"""
Create operator accounts with auto-generated one-time passwords.

You type a username, it prints a strong password to hand to that person. They
are forced to change it on first login (must_change_password=True), and after
the change they get the welcome → tutorials nudge.

Usage:
  python scripts/new_user.py                 # interactive: pick role once, then
                                             # type usernames one per line
  python scripts/new_user.py alice bob       # batch: create alice and bob
  python scripts/new_user.py --role viewer alice
  python scripts/new_user.py --reset alice   # set a NEW one-time password for
                                             # an existing user

Roles: admin | editor | viewer  (default: editor)
"""

from __future__ import annotations

import argparse
import re
import secrets
import string
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.password import MIN_PASSWORD_LENGTH, hash_password  # noqa: E402
from app.database import db_session  # noqa: E402
from app.repositories.user_repo import UserRepository  # noqa: E402

VALID_ROLES = ("admin", "editor", "viewer")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")

# Generated-password length. >= MIN_PASSWORD_LENGTH so the one-time password
# always satisfies the change-password form. A couple extra chars for margin.
PASSWORD_LENGTH = max(16, MIN_PASSWORD_LENGTH + 2)

# Unambiguous alphabet — drops O/0/o/I/l/1 so the password is easy to read
# aloud and retype without confusion.
_AMBIGUOUS = set("O0oIl1")
_ALPHABET = "".join(c for c in (string.ascii_letters + string.digits) if c not in _AMBIGUOUS)


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    """Cryptographically-random password guaranteed to contain at least one
    lowercase, one uppercase, and one digit."""
    while True:
        pw = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
        ):
            return pw


def _print_credentials(username: str, password: str, role: str, action: str) -> None:
    line = "-" * 52
    print(line)
    print(f"  {action}")
    print(f"  username : {username}")
    print(f"  password : {password}")
    print(f"  role     : {role}")
    print("  note     : one-time password - user must change it on first login")
    print(line)


def create_one(username: str, role: str, allow_reset: bool) -> bool:
    """Create (or, with --reset, re-key) a single user. Returns True on success."""
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        print(
            f"[skip] '{username}': invalid username "
            "(3-64 chars: lowercase letters, numbers, dots, underscores, hyphens).",
            file=sys.stderr,
        )
        return False

    password = generate_password()
    pw_hash = hash_password(password)

    # Do the DB write inside the session; capture what to print and emit it
    # AFTER the commit so a console-encoding hiccup can never roll back the
    # account that was just created.
    with db_session() as session:
        repo = UserRepository(session)
        existing = repo.find(username)
        if existing is not None:
            if not allow_reset:
                print(
                    f"[skip] '{username}' already exists. "
                    "Re-run with --reset to issue a new one-time password.",
                    file=sys.stderr,
                )
                return False
            repo.set_password(existing, pw_hash, must_change_password=True)
            existing.is_active = True
            action, out_role = "RESET existing user", existing.role
        else:
            repo.create(
                username=username,
                password_hash=pw_hash,
                role=role,
                must_change_password=True,
            )
            action, out_role = "CREATED new user", role

    _print_credentials(username, password, out_role, action)
    return True


def _prompt_role() -> str:
    while True:
        raw = input(f"Role for new users {VALID_ROLES} [editor]: ").strip().lower()
        if not raw:
            return "editor"
        if raw in VALID_ROLES:
            return raw
        print(f"  Please enter one of {VALID_ROLES}.")


def _interactive(role: str, allow_reset: bool) -> int:
    print(f"\nCreating users with role '{role}'. Type a username and press Enter.")
    print("Blank line (or Ctrl-D) when you're done.\n")
    created = 0
    while True:
        try:
            username = input("username> ").strip()
        except EOFError:
            print()
            break
        if not username:
            break
        if create_one(username, role, allow_reset):
            created += 1
    return created


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create operator accounts with generated one-time passwords."
    )
    parser.add_argument("usernames", nargs="*", help="Usernames to create (omit for interactive mode)")
    parser.add_argument("--role", choices=VALID_ROLES, default="editor", help="Role for created users (default: editor)")
    parser.add_argument("--reset", action="store_true", help="If a user already exists, set a new one-time password instead of skipping.")
    args = parser.parse_args()

    if args.usernames:
        created = sum(create_one(u, args.role, args.reset) for u in args.usernames)
    else:
        role = _prompt_role()
        created = _interactive(role, args.reset)

    print(f"\nDone. {created} account(s) ready.")
    print("Hand each person their password; they'll be forced to change it on first login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
