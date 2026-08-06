#!/usr/bin/env python3
"""Contract tests for multi-league auto campaigns.

An auto campaign could be restricted to exactly one league. It can now name
several, stored in the same `league` column: a plain string for one (so every row
written before this change is still valid and still means what it did), a JSON
array for several. One column rather than two, because a legacy `league` beside a
new `leagues` is two copies of one fact that can disagree.

  * a pre-existing single-league row parses to exactly that league
  * one league round-trips as a plain string, several as an array
  * blanks and duplicates from the repeated form field are dropped
  * a decode failure keeps the literal value rather than dropping the filter —
    losing it silently would widen a campaign to its whole sport
  * the engine unions the leagues, and keeps the scorer's per-tournament cap off
    so ?limit=N still returns N

Read-only against the live DB except for one campaign named zz-test-*, created
and deleted inside the run. Run: python scripts/test_campaign_leagues.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.database import db_session                          # noqa: E402
from app.models.campaign import Campaign, format_leagues, parse_leagues  # noqa: E402
from app.repositories.campaign_repo import CampaignRepository  # noqa: E402
from app.routes.admin_campaigns import _normalise_league     # noqa: E402
from app.services.hot_engine import HotEngine                # noqa: E402

FAILURES: list[str] = []
SLUG = "zz-test-multi-league"


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
        FAILURES.append(label if not detail else f"{label}: {detail}")


print("\nthe column reads the same as it always did")
check("a plain name is one league",
      parse_leagues("Premier League") == ["Premier League"])
check("empty means no filter", parse_leagues("") == [] and parse_leagues(None) == [])
check("a JSON array is several",
      parse_leagues('["A", "B"]') == ["A", "B"])
check("a broken array keeps the literal rather than dropping the filter",
      parse_leagues("[not json") == ["[not json"],
      "dropping it would widen the campaign to its whole sport")
check("one league is stored as a plain string, exactly as before",
      format_leagues(["A"]) == "A", repr(format_leagues(["A"])))
check("several are stored as an array", format_leagues(["A", "B"]) == '["A", "B"]')
check("nothing chosen stores NULL", format_leagues([]) is None)
check("it round-trips", parse_leagues(format_leagues(["A", "B"])) == ["A", "B"])

print("\nthe repeated form field is cleaned up")
check("the trailing empty box is dropped", _normalise_league(["A", "B", ""]) == '["A", "B"]',
      repr(_normalise_league(["A", "B", ""])))
check("all-empty means no filter", _normalise_league(["", "  "]) is None)
check("whitespace is trimmed", _normalise_league([" A ", "B"]) == '["A", "B"]')
check("the same league twice is collapsed", _normalise_league(["A", "A"]) == "A",
      "a league twice would double its weight in the pool")
check("a bare string still works (any caller not yet passing a list)",
      _normalise_league("A") == "A")

print("\nthe label reads sensibly")
for names, want in ((["A"], "A"), (["A", "B"], "A + B"),
                    (["A", "B", "C"], "A + 2 more"), ([], "")):
    c = Campaign(slug="x", title="x", sport="football", league=format_leagues(names))
    check(f"{names} -> {want!r}", c.league_label == want, repr(c.league_label))

print("\nno existing campaign changed meaning")
with db_session() as s:
    autos = [c for c in CampaignRepository(s).list_all() if c.mode == "auto"]
    # Only the plain-string rows are "pre-existing": a JSON-array row was written
    # by this feature and is meant to parse to several.
    legacy = [c for c in autos if c.league and not c.league.strip().startswith("[")]
    changed = [c.slug for c in legacy if c.league_names != [c.league]]
    check(f"all {len(legacy)} single-league rows parse to their original league",
          not changed, str(changed))
    multi = [c for c in autos if len(c.league_names) > 1]
    print(f"  (note: {len(multi)} campaign(s) already use several leagues"
          f"{': ' + ', '.join('/' + c.slug for c in multi) if multi else ''})")

print("\nthe engine unions the leagues")
with db_session() as s:
    # Pick two leagues the scorer actually returns matches for, so the check is
    # about the union and not about the scorer's own quality rules.
    pool = HotEngine(s, "football").resolve(20)
    by_league = Counter(m.tournament_name for m in pool)
    picks = [name for name, _ in by_league.most_common(2)]
    if len(picks) < 2:
        print("  [SKIP] fewer than two football leagues have hot matches right now")
    else:
        A, B = picks
        a_only = HotEngine(s, "football", league=A).resolve(10)
        b_only = HotEngine(s, "football", league=B).resolve(10)
        both = HotEngine(s, "football", league=[A, B]).resolve(10)
        stored = HotEngine(s, "football", league=format_leagues([A, B])).resolve(10)
        names = {m.tournament_name for m in both}
        check("a single league still returns only its own matches",
              {m.tournament_name for m in a_only} == {A}, str({m.tournament_name for m in a_only}))
        check("two leagues return matches from both", names == {A, B}, str(names))
        check("the stored column form gives the identical result",
              [m.event_id for m in stored] == [m.event_id for m in both])
        check("the limit is still respected", len(both) <= 10, str(len(both)))
        check("pooling never returns less than the better league alone",
              len(both) >= max(len(a_only), len(b_only)),
              f"both={len(both)} a={len(a_only)} b={len(b_only)}")
        check("the per-tournament cap stays off for a multi-league filter",
              HotEngine(s, "football", league=[A, B]).leagues == [A, B])

print("\na campaign saves, reads back and renders")
try:
    with db_session() as s:
        r = CampaignRepository(s)
        if r.find_by_slug(SLUG):
            r.delete(SLUG)
    with db_session() as s:
        CampaignRepository(s).create(
            slug=SLUG, title="multi-league test", sport="football", mode="auto",
            league=_normalise_league(["Chile. Primera División", "Brasil. Serie A", ""]),
            created_by="test")
    with db_session() as s:
        c = CampaignRepository(s).find_by_slug(SLUG)
        check("both leagues came back",
              c.league_names == ["Chile. Primera División", "Brasil. Serie A"],
              str(c.league_names))
        check("the label shows both", " + " in c.league_label, c.league_label)
        CampaignRepository(s).update(SLUG, league=_normalise_league(["Chile. Primera División"]))
    with db_session() as s:
        c = CampaignRepository(s).find_by_slug(SLUG)
        check("editing down to one league restores a plain-string column",
              c.league == "Chile. Primera División", repr(c.league))
        CampaignRepository(s).update(SLUG, league=_normalise_league([""]))
    with db_session() as s:
        c = CampaignRepository(s).find_by_slug(SLUG)
        check("clearing every box removes the filter",
              c.league is None and c.league_names == [], repr(c.league))
finally:
    with db_session() as s:
        r = CampaignRepository(s)
        if r.find_by_slug(SLUG):
            r.delete(SLUG)
            print(f"  (cleaned up /{SLUG})")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All campaign-league checks passed.")
