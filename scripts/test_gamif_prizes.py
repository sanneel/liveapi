#!/usr/bin/env python3
"""Contract for the JBCL gamification prize generator — offline, no network.

The brief is a price list, so the pins are that the list is what ships and that
the paste-time script cannot quietly turn a prize into a different one:

  * twelve prizes, in the four groups the brief names, with the rollover that
    belongs to each group and none on a money bonus;
  * every journey name spells its own amount, and no two are alike;
  * the emitted script refuses rather than creates: a journey that does not
    start at the API node, a surviving player_id filter, a missing amount;
  * it creates and saves drafts and never publishes or starts one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "journey-cloner"))

import gamif_prizes_jbcl_campaign as G  # noqa: E402

failures: list[str] = []


def check(good: bool, label: str) -> None:
    print(f"  [{'OK' if good else 'FAIL'}]   {label}")
    if not good:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n── {title}")


section("the price list")
by_group: dict[str, list[dict]] = {}
for p in G.PRIZES:
    by_group.setdefault(p["group"], []).append(p)
check(len(G.PRIZES) == 12, f"twelve prizes ({len(G.PRIZES)})")
check([p["amount"] for p in by_group["cash"]] == [90000, 120000, 150000], "cash 90k / 120k / 150k")
check([p["amount"] for p in by_group["1x"]] == [45000, 60000], "1x 45k / 60k")
check([p["amount"] for p in by_group["3x"]] == [20000, 30000], "3x 20k / 30k")
check([p["amount"] for p in by_group["5x"]] == [1000, 4000, 7000, 10000, 15000], "5x 1k / 4k / 7k / 10k / 15k")
check(all(p["kind"] == "money" for p in by_group["cash"]), "cash is a money bonus")
check(all(p["kind"] == "casino" for g in ("1x", "3x", "5x") for p in by_group[g]), "the rest are casino bonuses")
check(all(p["wagering"] == int(p["group"][0]) for g in ("1x", "3x", "5x") for p in by_group[g]),
      "each casino group rolls over by the number in its name")
check(all(p["wagering"] is None for p in by_group["cash"]), "a money bonus has no rollover")

section("names")
drafts, _report = G.prepare(list(G.GROUPS))
names = [d["name"] for d in drafts]
check(len(set(names)) == 12, "twelve distinct names")
check(all(d["amountText"] in d["name"] for d in drafts), "every name spells its own amount")
check(G.spaced(150000) == "150 000" and G.spaced(1000) == "1 000", "amounts are spaced the way the source writes them")
check(all("money bonus" in d["name"] for d in drafts if d["kind"] == "money"), "the cash names say money bonus")
check(all(f"casino bonus {d['wagering']}x" in d["name"] for d in drafts if d["kind"] == "casino"),
      "the casino names carry their rollover")
check(all(d["name"].startswith("JBCL | ") for d in drafts), "every name is branded JBCL")

section("verify() refuses")
check(all(c for c, _ in G.verify(drafts)), "a clean list passes")
dup = [dict(d) for d in drafts]
dup[1]["name"] = dup[0]["name"]
check(not all(c for c, _ in G.verify(dup)), "two journeys with one name are refused")
bad_roll = [dict(d) for d in drafts]
bad_roll[3]["wagering"] = 30
check(not all(c for c, _ in G.verify(bad_roll)), "a casino bonus rolling over 30x is refused")
money_roll = [dict(d) for d in drafts]
money_roll[0]["wagering"] = 5
check(not all(c for c, _ in G.verify(money_roll)), "a money bonus with a rollover is refused")
zero = [dict(d) for d in drafts]
zero[0]["amount"] = 0
check(not all(c for c, _ in G.verify(zero)), "a zero prize is refused")

section("--only picks a group")
cash, _ = G.prepare(["cash"])
check(len(cash) == 3 and all(d["kind"] == "money" for d in cash), "--only cash builds the three money bonuses")
five, _ = G.prepare(["5x"])
check(len(five) == 5 and all(d["wagering"] == 5 for d in five), "--only 5x builds the five 5x bonuses")

section("the emitted script")
js = G.build_js(drafts, "693903", "693908", keep_webhook=False)
check("apiBase(" in js, "it follows the API gateway the page is using")
check("createAndSaveDraft" in js, "it creates and saves each draft")
check("/publish" not in js and "/start" not in js, "it never publishes and never starts a journey")
check("the journey does not start at the API node" in js, "it refuses a journey that does not start at the API node")
check("a player_id filter survived the entry swap" in js, "it refuses a surviving player_id filter")
check("is nowhere in the body" in js, "it refuses when the amount did not land")
check("mixed amounts in the body" in js, "it refuses a body carrying two different amounts")
check("newWebhookId" in js and "KEEP_WEBHOOK_ID = false" in js, "each journey mints its own webhookId by default")
check("KEEP_WEBHOOK_ID = true" in G.build_js(drafts, "1", "2", keep_webhook=True), "--keep-webhook-id is wired through")
# The trap this generator hit on its first run: replacing the amount over the
# serialised body turned the number 3000000 into "30 0000".
check("Only STRING values are rewritten" in js, "the copy substitution is documented as string-only")
check(json.dumps(drafts, ensure_ascii=False) in js, "the prize table travels with the script")

section("the prize photo")
check("contents/v1/copy" in js, "each draft copies the promotion's artwork trees")
check(len(G.CONTENT_COPIES) == 6, "six copies, the set the UI makes")
check([c["part"] for c in G.CONTENT_COPIES if c["tree"] == "front"] == ["spa", "widget"],
      "the front tree copies spa and widget unfiltered")
check(all(c["files"] and "manifest.json" in c["files"] for c in G.CONTENT_COPIES if c["tree"] == "content"),
      "every content part copies its manifest and both languages")
check("s3/upload-content" in js, "the photo is uploaded as file content")
check("s3/upload" in js and "retreeContent" in js, "the content files are rewritten and put back")
check("the journey still points at the source content tree" in js,
      "it refuses a draft that never left the source card")
check("not one content part copied" in js, "it refuses when no part of the tree copied")
check("names no image slot" in js, "it refuses a photo with nowhere to go")
check("aws-get" in js, "it reads the copied files back before rewriting them")
check("?t=" in js, "the rewritten media paths carry a cache-buster")
no_photo = G.build_js(drafts, "1", "2", keep_webhook=False, with_photos=False)
check("WITH_PHOTOS = false" in no_photo and "WITH_PHOTOS = true" in js,
      "--no-photos is wired through and photos are the default")
check(js.index("contents/v1/copy") < js.index("await createDraft("),
      "the artwork is cloned before the draft is created, as the capture did")
check(js.index("await createDraft(") < js.index("await saveDraft("),
      "the photo lands between the create and the save, as the capture did")

section("what stopped the first live run")
# Seven of twelve drafts existed and the run went quiet: the eighth file dialog
# was dismissed, which fires 'cancel' and never 'change', so the promise never
# settled. A run this long also outlives the backoffice's five-minute token.
check("addEventListener('cancel'" in js, "a dismissed file dialog is handled")
check("keep the copied artwork" in js, "the picker offers a skip instead of blocking")
check("300000" in js and "no photo chosen" in js, "an unanswered picker gives up after five minutes")
check("document.body.contains(box)" in js, "the picker survives the backoffice re-rendering the page")
check("async function ensureToken" in js and "secondsLeft()" in js, "the token is checked, not assumed")
check(js.index("await ensureToken()") < js.index("await pickFile("),
      "the token is refreshed before the picker, not after it has gone stale")
check("HTTP 401|HTTP 403|No token in" in js, "a refused token stops the run instead of half-making drafts")
check("--only ' + left.join(',')" in js, "it prints the rerun command for whatever it did not create")

section("naming a source")
check(G.source_kind("JRN-0-685173") == "journey", "a JRN id is recognised")
check(G.source_kind("693903") == "draft", "a numeric draft id is recognised")
check(G.source_kind("JRN-0-685173 ") == "journey", "surrounding space does not matter")
for bad in ("", "JRN-685173", "https://…/drafts/693903", "abc", "12"):
    check(G.source_kind(bad) == "", f"{bad!r} is refused as a source id")
# A bare number cannot be told from a draft id, so it is taken as one and the
# 404 at paste time names it. Only the JRN prefix says "journey".
check(G.source_kind("685173") == "draft", "a bare number is read as a draft id, prefix or nothing")
check("/journeys/' : '/journey-drafts/'" in js, "the script picks the endpoint from the id it was given")
check("if (body.isImmediatelyAfterPublish) body.startAt = null" in js,
      "a running journey's start time does not travel into the new draft")
check("startAt" in G.POST_KEYS and "status" not in G.POST_KEYS and "version" not in G.POST_KEYS,
      "the posted keys are the ones the backoffice posts, not everything a journey read returns")

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
print("All gamification prize checks passed.")
