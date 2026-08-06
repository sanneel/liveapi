#!/usr/bin/env python3
"""Welcome Pack - 1st Deposit / Aff: one promocode, one brand, one mode -> one draft.

Two brands (JBCL, PMCL a.k.a. FTCL) x two modes (normal, boosted). "Boosted"
is the variant carrying the extra Sport FreeBet promotion after the deposit
detector; "normal" is the same journey without it.

    python welcome_pack_campaign.py --code JUGAWELCOME --brand jbcl --mode normal
    python welcome_pack_campaign.py --code TIPSTERX,JUGATW --brand jbcl --mode boosted
    python welcome_pack_campaign.py --code FORTW --brand pmcl --mode boosted

WHY THIS ONE HAS NO templates/ FILE
-----------------------------------
Every other generator here stores the captured POST body under templates/. This
one deliberately does not: the console script GETs the four source drafts at
paste time and clones what it finds. Two reasons, both from the capture:

  * the four sources are maintained by hand in the backoffice, so a stored copy
    would drift silently the first time someone edits one there;
  * the POST body is ~150 KB per journey and only three of the four were ever
    captured (JBCL/normal, draft 657229, never was).

The trade is real and worth stating: shape is whatever those four drafts are on
the day you paste. If someone edits 657225/6/9/30, the next run inherits it.
Check the source drafts still look right before a run that matters.

KNOWN LIMITATION - SHARED PROMOTIONS
------------------------------------
When the backoffice's own Copy button duplicates one of these journeys it also
duplicates the promotions behind it: two copies of draft 657226 came back with
different promotionId / promotionLinkId / FrontId / ContentId and a new
server-assigned promotionDisplayId. Those promotions are created by API calls
that were never captured, so this script cannot reproduce them.

Consequence: each draft it creates points at the SAME promotion (and therefore
the same /services/promo/promotion/<id> link in every SMS, NC and pop-up) as
its source draft. The script prints the shared ids per draft and will not let
you miss them, but it cannot fix them. Re-point the promotion nodes by hand in
the created draft before publishing, or capture the copy flow's promotion calls
and this limitation goes away.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "console_scripts"

BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"

BRANDS = ("JBCL", "PMCL")
MODES = ("normal", "boosted")

# The four hand-maintained drafts this clones. Confirmed from the captured
# create calls: each POST carried duplicatedFromId pointing at one of these,
# and the boosted pair are the ones with the extra freebet promotion.
SOURCE_DRAFTS: dict[tuple[str, str], int] = {
    ("PMCL", "boosted"): 657225,   # FTCL | SP | Welcome Pack - 1st Deposit / Aff | ... / Extra 1000$ FB
    ("PMCL", "normal"): 657226,    # FTCL | SP | Welcome Pack - 1st Deposit / Aff | ...
    ("JBCL", "normal"): 657229,    # JBCL | SP | Welcome Pack - 1st Deposit / Aff / ...
    ("JBCL", "boosted"): 657230,   # JBCL | SP | ... / Extra 1500$ FB
}

# Exactly the top-level keys the backoffice sends when it creates one of these
# drafts. A GET returns more than a POST accepts, so the script rebuilds the
# body from this whitelist rather than posting the fetched object back.
POST_KEYS = [
    "journeyName", "brand", "currencyCodes", "activities", "metadata",
    "reEntryRule", "timeZoneId", "testControlGroupParameters",
    "activityEventConversionMetrics", "reservedJourneyId", "journeySource",
    "isArchived", "isUnlimited", "isImmediatelyAfterPublish", "rawJourneyData",
    "duplicatedFromId",
]

# A promocode that is not this shape is a promocode that silently ships wrong.
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")


def parse_codes(raw: str) -> list[str]:
    codes = [c.strip().upper() for c in raw.replace(";", ",").split(",")]
    return [c for c in codes if c]


def prepare(codes: list[str], brands: list[str], modes: list[str]) -> tuple[dict, list[str]]:
    """codes + selection -> the plan the console script is rendered from."""
    targets = []
    for brand in brands:
        for mode in modes:
            targets.append({
                "key": f"{brand.lower()}_{mode}",
                "brand": brand,
                "mode": mode,
                "sourceId": SOURCE_DRAFTS[(brand, mode)],
            })
    plan = {"codes": codes, "targets": targets, "baseUrl": BASE_URL,
            "postKeys": POST_KEYS}
    report = [
        f"promocode(s) = {', '.join(codes)}",
        f"drafts = {len(targets)} ({', '.join(t['key'] for t in targets)})",
        "templates = fetched from the source drafts at paste time",
    ]
    return plan, report


def verify(plan: dict) -> list[tuple[bool, str]]:
    """Refuse rather than emit a script that would build the wrong thing."""
    checks: list[tuple[bool, str]] = []
    codes = plan["codes"]

    checks.append((bool(codes), f"at least one promocode given ({len(codes)})"))
    for code in codes:
        checks.append((bool(CODE_RE.match(code)),
                       f"promocode {code!r} is A-Z/0-9/-/_ , 3-32 chars"))
    checks.append((len(set(codes)) == len(codes),
                   "promocodes are distinct" + ("" if len(set(codes)) == len(codes) else f" (got {codes})")))

    targets = plan["targets"]
    checks.append((bool(targets), f"at least one brand/mode selected ({len(targets)})"))
    ids = [t["sourceId"] for t in targets]
    checks.append((len(set(ids)) == len(ids), "each draft clones a distinct source"))
    for t in targets:
        checks.append((SOURCE_DRAFTS.get((t["brand"], t["mode"])) == t["sourceId"],
                       f"{t['key']} -> source draft {t['sourceId']}"))

    # The registration node is where the promocode lives; without it in the
    # source there is nothing to substitute and the clone would ship the
    # captured campaign's code.
    checks.append(("promocodeSettings" in _render_js(plan),
                   "emitted script substitutes promocodeSettings"))
    return checks


def _render_js(plan: dict) -> str:
    tpl = (HERE / "templates" / "welcome_pack_console.js.tpl").read_text(encoding="utf-8")
    return (tpl
            .replace("/*__BASE__*/null", json.dumps(plan["baseUrl"]))
            .replace("/*__CODES__*/null", json.dumps(plan["codes"]))
            .replace("/*__TARGETS__*/null", json.dumps(plan["targets"], indent=2))
            .replace("/*__POST_KEYS__*/null", json.dumps(plan["postKeys"]))
            .replace("/*__GENERATED__*/", datetime.now().strftime("%Y-%m-%d %H:%M")))


def emit(plan: dict, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}_console.js"
    path.write_text(_render_js(plan), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--code", required=True,
                    help="promocode, or several comma-separated (JBCL's source carries two)")
    # No "both": one run builds one draft. Each draft inherits its own source's
    # promotion and promo links, so a four-draft run left four separate things to
    # re-point before publishing — and a defaulted brand is how a Fortunazo
    # operator ends up holding a JugaBet draft. Both are required choices.
    ap.add_argument("--brand", required=True, choices=["jbcl", "pmcl"])
    ap.add_argument("--mode", required=True, choices=["normal", "boosted"])
    ap.add_argument("--name", default=None, help="output script name (default: the first code)")
    args = ap.parse_args()

    codes = parse_codes(args.code)
    brands = [args.brand.upper()]
    modes = [args.mode]

    plan, report = prepare(codes, brands, modes)
    for line in report:
        print(f"  {line}")

    checks = verify(plan)
    failed = [msg for ok, msg in checks if not ok]
    for ok, msg in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
    if failed:
        print("\nRefusing to emit: " + "; ".join(failed), file=sys.stderr)
        return 1

    name = args.name or codes[0]
    path = emit(plan, name)
    print(f"\nWrote {path}")
    print("Paste it into a logged-in backoffice tab (F12 -> Console).")
    print("It creates DRAFTS only. Each draft shares its source's promotion -")
    print("the script prints which; re-point them before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
