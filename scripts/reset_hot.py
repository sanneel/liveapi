#!/usr/bin/env python3
"""
Inspect and reset the Hot leaderboard overrides (`hot_override` table).

The Hot engine DROPS suppressed events before scoring, so a handful of
suppressed matches is the usual reason the leaderboard shows fewer than the
Top 10 (e.g. "6 instead of 10"). Pins/positions can also distort the order.
This tool lets you see those overrides and clear them.

Usage:
  python scripts/reset_hot.py                       # list ALL overrides (read-only)
  python scripts/reset_hot.py --sport football      # list overrides for one sport
  python scripts/reset_hot.py --unsuppress          # un-hide every match (keeps pins)
  python scripts/reset_hot.py --unsuppress --sport football
  python scripts/reset_hot.py --clear-all           # remove every override row entirely
  python scripts/reset_hot.py --clear-all --sport football --yes

Default action is LIST. Any mutation requires --unsuppress or --clear-all and,
unless --yes is given, an interactive confirmation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import db_session  # noqa: E402
from app.logging_config import get_logger  # noqa: E402
from app.models import HotBoost, Match  # noqa: E402

logger = get_logger("reset_hot")


def _label(session, event_id: str) -> str:
    """Human-readable 'sport: Home vs Away (inactive)' for an override row."""
    match: Optional[Match] = session.get(Match, event_id)
    if match is None:
        return f"<no match row for {event_id}>"
    flag = "" if match.is_active else " (inactive)"
    return f"{match.sport}: {match.home_name} vs {match.away_name}{flag}"


def _rows_for_sport(session, sport: Optional[str]) -> List[HotBoost]:
    """All override rows, optionally filtered to a sport via the matches join."""
    rows: List[HotBoost] = session.query(HotBoost).all()
    if not sport:
        return rows
    sport = sport.strip().lower()
    kept: List[HotBoost] = []
    for row in rows:
        match = session.get(Match, row.event_id)
        if match is not None and match.sport == sport:
            kept.append(row)
    return kept


def _print_rows(session, rows: List[HotBoost]) -> None:
    if not rows:
        print("No hot overrides found.")
        return
    suppressed = sum(1 for r in rows if r.suppress)
    pinned = sum(1 for r in rows if r.pin or r.position is not None)
    print(f"{len(rows)} override row(s) — {suppressed} suppressed, {pinned} pinned/positioned\n")
    for r in rows:
        marks = []
        if r.suppress:
            marks.append("SUPPRESSED")
        if r.pin:
            marks.append("PIN")
        if r.position is not None:
            marks.append(f"pos={r.position}")
        if r.boost:
            marks.append(f"boost={r.boost}")
        tag = ", ".join(marks) or "no-op row"
        print(f"  [{tag}] {_label(session, r.event_id)}  (event_id={r.event_id})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect/reset Hot leaderboard overrides.")
    parser.add_argument("--sport", help="Scope to one sport (e.g. football, basketball, fights).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--unsuppress",
        action="store_true",
        help="Set suppress=False on every (scoped) row so hidden matches return to the leaderboard. Keeps pins/positions.",
    )
    group.add_argument(
        "--clear-all",
        action="store_true",
        help="Delete every (scoped) override row entirely — full reset of pins, positions and suppressions.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    with db_session() as session:
        rows = _rows_for_sport(session, args.sport)

        # Read-only listing.
        if not args.unsuppress and not args.clear_all:
            scope = f" for sport={args.sport}" if args.sport else ""
            print(f"Current hot overrides{scope}:\n")
            _print_rows(session, rows)
            print("\n(no changes made — pass --unsuppress or --clear-all to modify)")
            return 0

        if not rows:
            print("Nothing to do — no matching override rows.")
            return 0

        action = "un-suppress" if args.unsuppress else "DELETE"
        targets = (
            [r for r in rows if r.suppress] if args.unsuppress else rows
        )
        if not targets:
            print("Nothing to do — no suppressed rows in scope.")
            return 0

        print(f"About to {action} {len(targets)} override row(s):\n")
        _print_rows(session, targets)

        if not args.yes:
            confirm = input(f"\nProceed to {action} these {len(targets)} row(s)? [y/N] ").strip().lower()
            if confirm not in ("y", "yes"):
                print("Aborted — no changes made.")
                return 1

        changed = 0
        for row in targets:
            if args.unsuppress:
                row.suppress = False
            else:
                session.delete(row)
            changed += 1

        logger.info(f"reset_hot action={action} sport={args.sport or 'ALL'} rows={changed}")
        print(f"\n[success] {action}d {changed} override row(s). The leaderboard will rebuild on next render.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
