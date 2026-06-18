#!/usr/bin/env python3
"""
List and prune admin/operator accounts.

Usage:
  python scripts/manage_users.py list
  python scripts/manage_users.py delete-others --keep sandros7          # dry run
  python scripts/manage_users.py delete-others --keep sandros7 --yes    # do it

`delete-others` removes every account except the ones named in --keep. It
refuses to run if a kept username doesn't exist, or if deleting would leave no
admin account, so you can't lock yourself out. Without --yes it only previews.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import db_session  # noqa: E402
from app.repositories.user_repo import UserRepository  # noqa: E402


def _fmt(user) -> str:
    flags = []
    if not user.is_active:
        flags.append("inactive")
    if user.must_change_password:
        flags.append("must-change-pw")
    last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "never"
    extra = f"  [{', '.join(flags)}]" if flags else ""
    return f"  {user.role:7} {user.username:24} last login: {last}{extra}"


def cmd_list() -> int:
    with db_session() as session:
        users = UserRepository(session).all()
    print(f"{len(users)} account(s):")
    for u in users:
        print(_fmt(u))
    return 0


def cmd_delete_others(keep: list[str], yes: bool) -> int:
    keep_set = {k.strip().lower() for k in keep if k.strip()}
    if not keep_set:
        print("Refusing: --keep must name at least one account.", file=sys.stderr)
        return 1

    with db_session() as session:
        repo = UserRepository(session)
        users = repo.all()
        present = {u.username for u in users}

        missing = keep_set - present
        if missing:
            print(f"Refusing: --keep names unknown account(s): {', '.join(sorted(missing))}",
                  file=sys.stderr)
            return 1

        kept = [u for u in users if u.username in keep_set]
        to_delete = [u for u in users if u.username not in keep_set]

        if not any(u.role == "admin" and u.is_active for u in kept):
            print("Refusing: that would leave no active admin account. "
                  "Keep at least one admin.", file=sys.stderr)
            return 1

        if not to_delete:
            print("Nothing to delete — only the kept account(s) exist.")
            return 0

        print(f"Keeping {len(kept)}: {', '.join(sorted(keep_set))}")
        print(f"Will delete {len(to_delete)}:")
        for u in to_delete:
            print(_fmt(u))

        if not yes:
            print("\nDry run. Re-run with --yes to actually delete.")
            return 0

        for u in to_delete:
            repo.delete(u.username)
        print(f"\nDeleted {len(to_delete)} account(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="List and prune accounts.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show all accounts.")
    d = sub.add_parser("delete-others", help="Delete every account except --keep.")
    d.add_argument("--keep", nargs="+", required=True, help="Username(s) to keep.")
    d.add_argument("--yes", action="store_true", help="Actually delete (otherwise dry run).")
    args = parser.parse_args()

    if args.command == "list":
        return cmd_list()
    if args.command == "delete-others":
        return cmd_delete_others(args.keep, args.yes)
    return 1


if __name__ == "__main__":
    sys.exit(main())
