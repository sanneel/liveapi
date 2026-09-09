#!/usr/bin/env python3
"""Contract for the Sorry Bonus generator — offline, no key, no network.

The bonus amount is money and the segment is one named player, so the pins are
about those two landing everywhere and nothing of the capture surviving:

  * the amount is written in BOTH units in all six places it is stored (the
    bonus activity, its wageringActivity, the promotion placement, and each of
    their rawJourneyData mirrors) — the captured $10200 must not survive;
  * the segment targets exactly the player asked for;
  * both storages agree on the name and the stop date;
  * the paste-time placeholders are all still there (a filled-in one would mean
    a captured id shipped);
  * the id regen the console script runs leaves no id shared between drafts;
  * verify() refuses on one broken rule at a time.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "journey-cloner"))

import sorry_bonus_pmcl_campaign as S  # noqa: E402
from create_journeys import LOCAL_TZ, walk_dicts  # noqa: E402

PLAYER = "pmcltest0000000001"
AMOUNT = 3400
STOP = datetime.combine((datetime.now(LOCAL_TZ) + timedelta(days=2)).date(), time(0, 0), tzinfo=LOCAL_TZ)

failures: list[str] = []


def check(good: bool, label: str) -> None:
    print(f"  [{'OK' if good else 'FAIL'}]   {label}")
    if not good:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n── {title}")


section("the pasted list")
rows, problems = S.parse_list(
    "pmcl0000000000000a1 - 6240 casino\n"
    "pmcl0000000000000b2 - 1680 casino bonus\n"
    "\n"
    "# a comment\n"
    "pmcl0000000000000b2 - 999 casino bonus\n"
    "nonsense line\n"
)
check(rows == [("pmcl0000000000000a1", 6240), ("pmcl0000000000000b2", 1680)],
      f"reads player and amount, ignores blanks and comments ({rows})")
check(any("twice" in p for p in problems), "a repeated player is reported, not built twice")
check(any("cannot read" in p for p in problems), "an unreadable line is reported")

section("one prepared draft")
body, _report = S.prepare(PLAYER, AMOUNT, STOP)
text = json.dumps(body, ensure_ascii=False)
amounts = {(d["fixedBonusAmount"], d["fixedBonusAmount_majorUnits"]) for d in walk_dicts(body)
           if "fixedBonusAmount" in d and "fixedBonusAmount_majorUnits" in d}
check(amounts == {(AMOUNT * 100, AMOUNT)}, f"every bonus field is the run's amount ({sorted(amounts)})")
check(len([d for d in walk_dicts(body) if "fixedBonusAmount" in d]) == 6,
      "the amount is stored in six places and all six were written")
check(str(S.TPL_AMOUNT_MAJOR) not in text, "the captured $10200 is gone from the whole body")
players = {v for d in walk_dicts(body) if d.get("fieldName") == "player_id" for v in (d.get("values") or [])}
check(players == {PLAYER}, f"the segment targets exactly the player ({players})")
check(body["journeyName"] == f"PMCL | CS | Sorry Bonus | ${AMOUNT} Casino Bonus", "journeyName carries the amount")
check(body["journeyName"] == body["rawJourneyData"]["infoValues"]["journeyName"], "both storages agree on the name")
check(body["stopAt"][:16] == body["rawJourneyData"]["infoValues"]["stopAt"][:16], "both storages agree on stopAt")
check(S.TPL_STOP_AT not in text, "the captured stop date is gone")
for token in (S.RESERVED_TOKEN, S.PROMO_DISPLAY_TOKEN, S.FRONT_TOKEN, S.CONTENT_TOKEN):
    check(token in text, f"{token} is still a placeholder (filled at paste)")
check(S.PLAYER_TOKEN not in text, "the player placeholder was filled")
check(body.get("duplicatedFromId") is None, "no 'duplicated from' lineage")
check(all(c for c, _ in S.verify(body, PLAYER, AMOUNT)), "verify() passes a good draft")

section("verify() refuses, one rule at a time")
broken = json.loads(json.dumps(body))
broken["journeyName"] = "Copy of PMCL | CS | Sorry Bonus | $10200 Casino Bonus"
check(not all(c for c, _ in S.verify(broken, PLAYER, AMOUNT)), "a 'Copy of' name is refused")

broken = json.loads(json.dumps(body))
for d in walk_dicts(broken):
    if "fixedBonusAmount" in d:
        d["fixedBonusAmount"] = S.TPL_AMOUNT_MAJOR * 100
        d["fixedBonusAmount_majorUnits"] = S.TPL_AMOUNT_MAJOR
        break                       # one place left behind is the whole bug
check(not all(c for c, _ in S.verify(broken, PLAYER, AMOUNT)), "one un-rewritten amount is refused")

broken = json.loads(json.dumps(body))
for d in walk_dicts(broken):
    if d.get("fieldName") == "player_id":
        d["values"] = ["pmclsomeoneelse00001"]
        break
check(not all(c for c, _ in S.verify(broken, PLAYER, AMOUNT)), "a segment naming another player is refused")

broken = json.loads(json.dumps(body))
broken["rawJourneyData"]["infoValues"]["journeyName"] = "something else"
check(not all(c for c, _ in S.verify(broken, PLAYER, AMOUNT)), "the two storages disagreeing is refused")

section("the id regen the console script runs")
UUID_RE = re.compile(r'"(?:activityId|id|promotionId|promotionLinkId)"\s*:\s*'
                     r'"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"')


def regen(txt: str) -> str:
    for old in set(UUID_RE.findall(txt)):
        txt = txt.replace(old, str(uuid.uuid4()))
    return txt


one, two = regen(text), regen(text)
ids_one, ids_two = set(UUID_RE.findall(one)), set(UUID_RE.findall(two))
check(bool(ids_one) and not (ids_one & ids_two), "two drafts from one template share no id")
check(not (set(UUID_RE.findall(text)) & ids_one), "no captured id survives the regen")
a1 = json.loads(one)
check(json.dumps(a1["activities"], sort_keys=True) != json.dumps(body["activities"], sort_keys=True),
      "the regen actually rewrote the activities")
promo = next(a for a in a1["activities"] if a["activityName"] == "promotion")["initializationData"]
bonus = next(a for a in a1["activities"] if a["activityName"] == "casino_bonus_v2")
check(promo["placements"][0]["data"]["campaignId"] == bonus["activityId"],
      "the promotion still points at the bonus activity after the regen")

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("All Sorry Bonus checks passed.")
