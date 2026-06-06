"""Standalone DB test for MatchRepository.deactivate_not_seen.

Run locally or on the VPS:
    python scripts/test_deactivate_not_seen.py
Exits 0 / prints OK on success; raises AssertionError otherwise.

Proves the safe replacement for the per-feed deactivate_stale:
  - reaps prematch rows not seen for >window
  - keeps fresh prematch rows (kept alive by any feed)
  - never touches live rows (mode filter) -> live rotation can't flicker
  - never touches synthetic rows (handled by its own reaper)
  - ignores already-inactive rows
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Campaign, HotBoost
from app.models.campaign_match import CampaignMatch
from app.models.match import Match
from app.repositories.match_repo import MatchRepository

WINDOW_MIN = 90


def _mk(eid, mode, mins_ago, synthetic=False, active=True):
    now = datetime.utcnow()
    return Match(
        event_id=eid,
        sport="football",
        mode=mode,
        status=mode,
        home_name="A",
        away_name="B",
        is_active=active,
        is_synthetic=synthetic,
        first_seen_at=now - timedelta(minutes=mins_ago),
        last_updated_at=now - timedelta(minutes=mins_ago),
    )


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    for model in (Match, Campaign, CampaignMatch, HotBoost):
        model.__table__.create(bind=engine)
    session = sessionmaker(bind=engine)()

    session.add_all([
        _mk("fresh_pm", "prematch", 5),                 # survives (fresh)
        _mk("stale_pm", "prematch", 120),               # reaped
        _mk("edge_in_pm", "prematch", 95),              # reaped (just over 90m)
        _mk("edge_out_pm", "prematch", 60),             # survives (under 90m)
        _mk("stale_live", "live", 600),                 # survives (mode filter)
        _mk("stale_syn", "prematch", 600, synthetic=True),  # survives (synthetic excl.)
        _mk("already_off", "prematch", 600, active=False),  # ignored
        _mk("camp_pm", "prematch", 600),                # stale BUT pinned -> survives
    ])
    # pin camp_pm to an enabled campaign
    session.add(Campaign(slug="wc", title="WC", sport="football", mode="manual", enabled=True))
    session.add(CampaignMatch(campaign_slug="wc", event_id="camp_pm"))
    session.commit()

    n = MatchRepository(session).deactivate_not_seen(WINDOW_MIN, modes=("prematch",))
    session.commit()

    def is_active(eid):
        return session.get(Match, eid).is_active

    assert n == 2, f"expected 2 reaped, got {n}"
    assert is_active("fresh_pm") is True, "fresh prematch wrongly reaped"
    assert is_active("edge_out_pm") is True, "60m prematch wrongly reaped"
    assert is_active("stale_pm") is False, "stale prematch not reaped"
    assert is_active("edge_in_pm") is False, "95m prematch not reaped"
    assert is_active("stale_live") is True, "live reaped (rotation flicker risk)"
    assert is_active("stale_syn") is True, "synthetic reaped by wrong reaper"
    assert is_active("camp_pm") is True, "campaign-pinned match wrongly reaped"

    # protected rows are not resurrected forever; an expired/finished selected
    # match must stay inactive so public renders and leaderboards can drop it.
    session.get(Match, "camp_pm").is_active = False
    session.commit()
    healed = MatchRepository(session).reactivate_protected()
    session.commit()
    assert healed == 0, f"expected no resurrection, got {healed}"
    assert is_active("camp_pm") is False, "reactivate_protected resurrected a pinned match"

    print("OK: deactivate_not_seen + campaign exemption passed all assertions")


if __name__ == "__main__":
    main()
