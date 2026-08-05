#!/usr/bin/env python3
"""Contract for the Sport Wheel of Fortune generator — offline, no key, no network.

The randomizers had no test at all, which is how every wheel came to share one
visual content record. This pins the rules the rebuilt flow exists to enforce:

  * each wheel mints its OWN contentId/frontId — the captured pair never ships,
    and the master tree is only ever a copy SOURCE;
  * the media paths inside the visual payload follow the fresh id, or the new
    wheel renders the captured wheel's images;
  * no slice shows an internal journey name to players (the capture shipped
    four that did) — the build refuses rather than warns;
  * copy for slices the wheel no longer has is dropped, not carried;
  * a batch cannot repeat a urlShortName (it is unique server-side, so the
    second wheel 409s after the first is already created).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "journey-cloner"))

import randomizer_campaign as R  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)


PRIZES = "\n".join([
    "Money bonus $5.000\tBono de dinero $5.000",
    "Free bonuses\tBonos gratis",
    "Bonuses for deposit\tBonos por depósito",
    "Bet Insurance\tSeguro de apuesta",
    "Free bets for deposit\tApuestas gratis por depósito",
    "Free bets for bet\tApuestas gratis por apostar",
    "10% extra free bet\tApuesta gratis 10% extra",
])

# The realistic run: only the brand-new slice needs copy, the other six inherit
# the previous wheel's.
ONE_LINE = "7\t10% extra free bet\tApuesta gratis 10% extra"

CFG = R.KINDS["sport_wof"]


def main() -> int:
    print("Sport Wheel of Fortune contract\n")

    b, report = R.prepare_visual("sport_wof", "2026-08-03", prize_text=PRIZES)
    create, save, uploads = b["create"], b["save"], b["uploads"]
    blob = json.dumps(create) + json.dumps(save) + json.dumps(uploads, ensure_ascii=False)

    print("the wheel owns its own visual content:")
    check(create["contentId"] == R.CONTENT_ID_TOKEN
          and create["frontId"] == R.FRONT_ID_TOKEN,
          "contentId + frontId are per-draft placeholders")
    check("2fdd15cd-7d71-4ac1-a499-8fe5df632045" not in blob
          and "09c24e9b-69e8-4eaa-9f63-9a62dd458584" not in blob,
          "the captured run's content ids are gone")
    check("50691caf-4694-4a47-9ff2-bac498c3a8ee" not in blob
          and "a3d54b7c-a8e2-4970-b6d3-7f6ef8e76480" not in blob,
          "the OLD shared pair every wheel used is gone")
    check(CFG["master_content"] not in blob and CFG["master_front"] not in blob,
          "the master tree is a copy source only, never written into a payload")
    media = {v for f in uploads if isinstance(f.get("data"), dict)
             for v in f["data"].values()
             if isinstance(v, str) and "media/" in v}
    # "Randomizer/assets/..." is a shared platform asset (the default prize box),
    # not per-wheel content; everything else must follow the fresh id.
    own = {m for m in media if not m.startswith("Randomizer/assets/")}
    check(bool(own) and all(m.startswith(R.CONTENT_ID_TOKEN) for m in own),
          f"every per-wheel media path follows the fresh content id "
          f"({len(own)} path(s), {len(media) - len(own)} shared platform asset(s))")

    print("\nthe 8 visual files, into the right tree:")
    rels = [(f["target"], f["rel"]) for f in uploads]
    check(len(uploads) == 8, f"8 files uploaded ({len(uploads)})")
    check(sum(1 for t, _ in rels if t == "content") == 6
          and sum(1 for t, _ in rels if t == "front") == 2,
          "6 into the content tree, 2 (the settings) into the front tree")
    manifests = {f["rel"]: f["data"] for f in uploads if f["rel"].endswith("manifest.json")}
    named = {f["rel"].rsplit("/", 1)[-1] for f in uploads if "/content/" in f["rel"]}
    check(all(v in named for m in manifests.values() for v in m.values()),
          f"every manifest points at a file that is actually uploaded ({manifests})")

    print("\nthe re-pointed slices inherit the previous wheel's copy:")
    b1, _ = R.prepare_visual("sport_wof", "2026-08-03", prize_text=ONE_LINE)
    spa = R.content_files(b1["uploads"])
    check(len(spa) == 2, f"prize copy lives in the spa content pair only ({len(spa)})")
    widget = [f for f in b1["uploads"] if f["rel"].startswith("widget/content/")]
    check(all(not any(k.startswith("prize_") for k in f["data"]) for f in widget),
          "no prize key is invented in the widget teaser, which has none")
    en1 = next(f["data"] for f in spa if "-en-" in f["rel"])
    es1 = next(f["data"] for f in spa if "-es-" in f["rel"])
    ids1 = b1["prize_ids"]
    check(R.strip_html(en1[f"prize_{ids1[1]}.prizeTextKey"]).startswith("For Free:"),
          "the re-pointed Free|Bonuses slice inherited its real copy")
    check(R.strip_html(en1[f"prize_{ids1[2]}.prizeTextKey"]) == "Bonuses for deposit",
          "the re-pointed Dep|Bonus slice inherited its real copy")
    check(R.strip_html(en1[f"prize_{ids1[4]}.prizeTextKey"]) == "Free bets for deposit",
          "the re-pointed Dep|Freebet slice inherited its real copy")
    # The captured ES file held copy for only three of the seven slices, so a
    # build that wrote only over EXISTING keys dropped Spanish silently.
    blank_es = [i + 1 for i, a in enumerate(ids1)
                if not R.strip_html(es1.get(f"prize_{a}.prizeTextKey", ""))]
    check(not blank_es, f"no slice is blank in Spanish ({blank_es})")
    check(R.strip_html(es1[f"prize_{ids1[6]}.prizeTextKey"]) == "Apuesta gratis 10% extra",
          "the operator's ES copy reaches the ES file, not just the EN one")
    for ok, msg in R.verify_visual(b1):
        check(ok, "one-line run: " + msg)

    print("\nprize copy — refused rather than warned:")
    ids = b["prize_ids"]
    check(len(ids) == 7 and all(ids), "7 prize slices, each with an activityId")
    weights = [float(p["weight"]) for p in create["prizes"]]
    check(abs(sum(weights) - 100) < 0.01, f"weights sum to 100 ({weights})")
    en = next(f["data"] for f in uploads if f["rel"].endswith("content-en-da1f0394ccb8.json"))
    es = next(f["data"] for f in uploads if f["rel"].endswith("content-es-1f8572550e71.json"))
    check(en[f"prize_{ids[0]}.prizeTextKey"] == "Money bonus $5.000"
          and es[f"prize_{ids[0]}.prizeTextKey"] == "Bono de dinero $5.000",
          "EN and ES copy land in their own files, not one over both")
    check(en[f"prize_{ids[6]}.prizeTextKey"] == "10% extra free bet",
          "the new 10%- slice carries player-facing copy")
    stale = [k for f in uploads if isinstance(f.get("data"), dict) for k in f["data"]
             if k.startswith("prize_") and k.endswith(".prizeTextKey")
             and k[len("prize_"):-len(".prizeTextKey")] not in set(ids)]
    check(not stale, f"no copy for slices this wheel does not have ({stale[:3]})")
    internal = [v for f in uploads if isinstance(f.get("data"), dict)
                for k, v in f["data"].items()
                if k.endswith(".prizeTextKey") and R.INTERNAL_COPY_RE.search(R.strip_html(v))]
    check(not internal, f"no internal journey name reaches a player ({internal[:2]})")

    print("\ncreate and save agree:")
    check(create["showDate"] == save["initialShowDate"]
          and create["endDate"] == save["initialEndDate"], "the wheel's window")
    check(create["internalName"] == save["internalName"]
          and create["urlShortName"] == save["urlShortName"], "the name")
    check(all(p.get("id") is None for p in save["prizes"]),
          "the save posts prizes without ids, as the capture does")
    check(save.get("hasCsv") is False and save.get("currencyMode") is None,
          "the save's own field shapes are kept")

    print("\nverify (happy path):")
    for ok, msg in R.verify_visual(b):
        check(ok, msg)

    print("\ndate-only run (no prize copy — every slice ships its baked copy):")
    bd, _ = R.prepare_visual("sport_wof", "2026-08-05")
    for ok, msg in R.verify_visual(bd):
        check(ok, msg)

    print("\nrefusals:")
    def raises(fn, label):
        try:
            fn()
        except SystemExit as exc:
            check(True, f"{label} -> refused ({str(exc).splitlines()[0][:44]})")
            return
        check(False, f"{label} -> NOT refused")

    raises(lambda: R.prepare_visual("sport_wof", "2026-08-03", prize_text="9\tx\ty"),
           "copy aimed at a slice number the wheel does not have")
    raises(lambda: R.prepare_visual("sport_wof", "2026-08-03", prize_text="7\tx\ty\nplain line"),
           "numbered and unnumbered lines mixed")
    raises(lambda: R.prepare_visual("sport_wof", "2026-08-03",
                                    prize_text="only\tone line"),
           "fewer copy lines than slices")
    raises(lambda: R.prepare_visual(
        "sport_wof", "2026-08-03",
        prize_text=PRIZES.replace("Free bonuses", "JBCL | SP | RB - Wheel of fortune")),
        "copy pasted straight from a journey name")

    print("\nbatch safety:")
    b2, _ = R.prepare_visual("sport_wof", "2026-08-10", prize_text=PRIZES)
    check(b2["create"]["urlShortName"] != create["urlShortName"],
          f"two dates get distinct urlShortNames ({create['urlShortName']}, {b2['create']['urlShortName']})")
    check(b2["create"]["internalName"] != create["internalName"],
          "two dates get distinct internalNames")

    print("\nthe console script:")
    js = R.build_visual_js([b, b2])
    check("crypto.randomUUID" in js and "buildOne" in js,
          "a fresh uuid pair is minted per wheel, at paste time")
    check(js.count("%%CONTENT_ID%%") >= 1 and "split('%%CONTENT_ID%%').join(contentId)" in js,
          "the token is filled from that uuid")
    check("/contents/v1/copy" in js and "/promo/v2/s3/upload" in js
          and "/promo/v2/promo-drafts/randomizer/' + id + '?draftId=" in js,
          "all three new calls are in the script (copy, upload, PUT save)")
    check("/promo/v2/randomizer?draftId=" not in js,
          "the old wrong fill endpoint is gone")
    check(CFG["master_content"] in js and CFG["master_front"] in js,
          "the master ids appear only as the copy source")

    print()
    if FAILURES:
        print(f"FAILED — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
