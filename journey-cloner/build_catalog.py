#!/usr/bin/env python3
"""Extract a machine-readable catalog of the REA backoffice from our captured
templates, so an LLM planner can reason about activities, how they connect, and
what varies per campaign — without ever touching raw 600KB journey JSON.

This is Phase 1 of the planner system: it does NOT invent anything. Everything
in activities/transitions/channels/rewards/segments is read straight out of the
real templates in templates/casino/. The only hand-authored parts are the
`recipes` (intent -> pattern) and the `knob_hints` (which fields the compilers
substitute), both clearly marked source:"curated".

Run:  python build_catalog.py    -> writes catalog.json (+ prints a summary)
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TPL = HERE / "templates" / "casino"
JOURNEY_TEMPLATES = {"gow_campaign": "gow.json", "gow_comms": "gow_comms.json"}
EMAIL_TEMPLATE = "gow_email.json"
SEGMENT_FRAGMENTS = ["segment_cs_301.json"]


def load(name: str) -> dict:
    return json.loads((TPL / name).read_text(encoding="utf-8-sig"))


def akey(activity: dict) -> str:
    """Stable key for an activity *type* (notification_center is split by contract)."""
    name = activity.get("activityName", "?")
    init = activity.get("initializationData") or {}
    if name == "notification_center" and "contract" in init:
        return f"{name}#contract{init['contract']}"
    return name


# Human-readable purpose per activity type (curated, kept short).
PURPOSE = {
    "dwh_source": "Entry source: segment/DWH-targeted audience (filterDetails).",
    "external_system_source": "Entry source: API/external trigger (no audience filter).",
    "multipurpose_promotion": "Lobby/cashier 'flat drip' offer with a deposit ask.",
    "promotion": "Generic offer (Offered->Accepted->Expired) carrying a reward placement.",
    "deposit": "Deposit-condition gate; emits Satisfied/Unsatisfied/Canceled, can split.",
    "freespin_bonus": "Awards casino free spins on a specific game.",
    "casino_bonus_v2": "Wagering (deposit-match) bonus; wagers winnings from a prior mechanic.",
    "wait_interval": "Delay for a fixed ISO-8601 duration.",
    "event_detector": "Waits for a server-side event before continuing.",
    "notification_center#contract1": "On-site Notification (bell), template-based.",
    "notification_center#contract5": "On-site Pop-up (Cat-fish), template-based.",
    "notification_center_engagement_split": "Branch on Clicked/Read/Sent of a prior on-site message.",
    "email_engagement_split": "Branch on open/click of a prior email.",
    "native_push": "Mobile push (Android/iOS).",
    "dextra_sms": "SMS (inline copy in rawValues/smsSettings/displayData).",
    "dextra_email": "Email; references a content-studio content by CSE id.",
    "ams_decision_split": "Rules-based audience split.",
    "end_of_path": "Terminates one parallel-flow branch.",
    "end_of_journey": "Terminates the whole journey.",
}

# Fields the compilers substitute per run (curated; source of 'knobs').
KNOB_HINTS = {
    "freespin_bonus": ["freespinActivity.spins", "freespinActivity.lobbyGameId",
                       "freespinActivity.walletGameId", "freespinActivity.externalGameId",
                       "freespinActivity.gameTranslationKey", "freespinActivity.currenciesConfig.<CCY>.betAmount",
                       "freespinActivity.startAt", "freespinActivity.stopAt"],
    "deposit": ["depositConditions.minDepositAmounts[].amount", "depositConditions.expirationTimeout"],
    "notification_center#contract1": ["objectForSend.variables[title-en/es,des-en/es,caption-en/es,link-en/es,deeplink,icon]",
                                      "singleChannel.localizedLanguagesTab"],
    "notification_center#contract5": ["objectForSend.variables[title_en/es,description_en/es,caption_en/es,link,deeplink,background_image_src]",
                                      "singleChannel.localizedLanguagesTab"],
    "dextra_sms": ["rawValues.messageText", "rawValues.localizedMessageTexts", "smsSettings.messageText",
                   "smsSettings.localizedMessageTexts", "displayData", "listOfUsedVariables(BrandDomain)"],
    "dextra_email": ["emailSettings.template.id (CSE)", "displayData"],
    "dwh_source": ["filterDetails", "currentTemplate", "dataSourceName"],
}

# Intent -> activity pattern (curated, grounded in the GOW templates).
RECIPES = [
    {"intent": "free spins after a deposit",
     "pattern": ["deposit", "promotion", "freespin_bonus", "casino_bonus_v2"],
     "notes": "deposit gate -> offer -> award spins -> wager winnings. The GOW campaign uses 3 such reward flows behind one deposit."},
    {"intent": "on-site + SMS + email comms blast for a promo",
     "pattern": ["dwh_source", "notification_center#contract1", "notification_center#contract5", "dextra_sms", "dextra_email"],
     "notes": "Segment entry -> Notification -> Pop-up -> SMS -> Email, all linking the same promo page. GOW comms window 12:00-19:00 Chile."},
    {"intent": "lobby drip offer with deposit ask",
     "pattern": ["external_system_source", "multipurpose_promotion", "deposit"],
     "notes": "API entry -> flat-drip lobby/cashier card -> deposit gate. GOW campaign head."},
]


# Anti-hallucination rules, machine-readable so a planner reading ONLY catalog.json
# (never the prose RECIPE_BUILDING.md) still gets them. Grounded corrections: the
# failure class they guard is "inventing a connection mechanic with no ground truth."
KB_RULES = [
    {"id": "connections-use-campaign_connector",
     "level": "must",
     "rule": "Journeys connect to other journeys/randomizers via the campaign_connector "
             "activity + the {journeyId, activityId} hand-off — NOT via a notification/CTA "
             "link. A CTA is marketing (tells the player); it is never the structural "
             "connection. Granting/unlocking a randomizer after a condition is a "
             "campaign_connector to the randomizer's entry."},
    {"id": "journey-grants-randomizer-uncaptured",
     "level": "flag",
     "symbol": "⛔",
     "rule": "The journey → randomizer direction is UNCAPTURED. Every captured example is "
             "randomizer → journey (prize routes into a reward). A journey GRANTING a "
             "randomizer shot (deposit → unlock scratch card) has NO captured example. "
             "Flag ⛔ 'journey-grants-randomizer mechanic unverified — confirm how the shot "
             "entitlement is wired before building' instead of inventing it."},
]


def build_automations() -> list[dict]:
    """The top-level 'automation graph': the named things you can generate in
    this backoffice, each a distinct endpoint/output. Curated, but the WOF
    prize routing is read from the captured template."""
    autos = [
        {
            "key": "promo_page",
            "label": "Promo Page (journey-cloner)",
            "creates": "a /promo/offers/promoPage/<id> landing page draft",
            "endpoint": "POST /promo/v2/promo-drafts/promo-page",
            "knobs": ["internal name", "show/start/end dates", "contentId/frontId visual bundle", "reward items"],
            "notes": "The page every channel links to. Built by gow_campaign.py's run alongside the campaign.",
        },
        {
            "key": "gow",
            "label": "Game of the Week (GOW)",
            "creates": "campaign journey + promo page + 2 comms journeys (CS&SP, CS) + email content",
            "endpoint": "POST /journey-drafts (+ promo-page, + content-studio email)",
            "knobs": ["game/provider", "4 bet tiers", "spins", "date", "per-channel EN/ES copy", "photos", "segment (CS&SP/CS-301)"],
            "compiler": "gow_combined.py / gow_campaign.py / comms_campaign.py",
            "starts": "immediately after publish",
        },
    ]
    # Sport Wheel of Fortune (randomizer) — read prize routing from the template
    wof_path = TPL.parent / "sport" / "sport_wof_randomizer.json"
    wof = {
        "key": "sport_wof",
        "label": "Sport Wheel of Fortune (Randomizer)",
        "creates": "a FortuneWheel randomizer promo whose weighted slices route winners to journeys",
        "endpoint": "POST /promo/v2/randomizer?draftId=<draftId>",
        "knobs": ["draftId", "show/start/hide/end dates (promoDay 04:00Z window)",
                  "urlShortName sport-dd-mm-yyyy", "internalName JBCL|SP|WOF|dd.mm.yy",
                  "prizes[].weight", "prizes[].journeyPrizeSettings.{journeyId,activityId}", "segment filterConditions"],
        "shot_policy": "Once",
        "segment": "fairplay_sport_segment notIn [VIP*, risk/abuse statuses]",
        "template": "templates/sport/sport_wof_randomizer.json",
    }
    if wof_path.exists():
        w = json.loads(wof_path.read_text(encoding="utf-8"))
        wof["prizes"] = _prize_table(w)
    autos.append(wof)

    # Other captured randomizers (scratch card, casino wheel) — read generically.
    more = [
        ("casino_scratch_card", "Casino Scratch Card (Raspa y Gana)",
         "a ScratchCard randomizer; scratch slices route winners to journeys",
         "casino/raspaygana_scratchcard.json"),
        ("casino_wof", "Casino Wheel of Fortune",
         "a FortuneWheel randomizer (casino, distinct from the sport WOF)",
         "casino/casino_wof_randomizer.json"),
    ]
    for key, label, creates, rel in more:
        path = TPL.parent / rel
        if not path.exists():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        autos.append({
            "key": key, "label": label, "creates": creates,
            "endpoint": "POST /promo/v2/promo-drafts/randomizer  then  PUT .../randomizer/<id>",
            "randomizationType": d.get("randomizationType"),
            "brand": (d.get("currencies") or [{}])[0].get("brand"),
            "shot_policy": d.get("randomizerShotPolicy"),
            "segment": [f.get("filterType") for f in d.get("filterConditions", [])],
            "visual": {"contentId": d.get("contentId"), "frontId": d.get("frontId")},
            "template": f"templates/{rel}",
            "prizes": _prize_table(d),
        })
    return autos


def _prize_table(d: dict) -> list[dict]:
    return [
        {"weight": p.get("weight"),
         "routes_to_journey": (p.get("journeyPrizeSettings") or {}).get("journeyId"),
         "description": (p.get("journeyPrizeSettings") or {}).get("activityDescription")}
        for p in d.get("prizes", [])
    ]


def build() -> dict:
    activities: dict[str, dict] = {}
    transitions: list[dict] = []
    seen_transitions: set = set()

    for tkey, fname in JOURNEY_TEMPLATES.items():
        body = load(fname)
        acts = body.get("activities", [])
        by_id = {a.get("activityId"): a for a in acts}
        for a in acts:
            k = akey(a)
            init = a.get("initializationData") or {}
            entry = activities.setdefault(k, {
                "activity": a.get("activityName"),
                "contract": init.get("contract"),
                "display_name": a.get("activityDisplayName"),
                "purpose": PURPOSE.get(k, ""),
                "emits_events": set(),
                "init_fields": set(),
                "knobs": KNOB_HINTS.get(k, []),
                "seen_in": set(),
            })
            entry["seen_in"].add(tkey)
            entry["init_fields"].update(init.keys())
            for ev in a.get("events", []):
                en = ev.get("eventName")
                if en:
                    entry["emits_events"].add(f"{en} ({ev.get('eventType','')})")
                # observed grammar: this activity.event -> successor activity type
                nxt = by_id.get(ev.get("nextActivityId"))
                if nxt is not None:
                    sig = (k, en, akey(nxt))
                    if sig not in seen_transitions:
                        seen_transitions.add(sig)
                        transitions.append({"from": k, "on_event": en, "to": akey(nxt)})

    # normalize sets -> sorted lists
    out_activities = []
    for k, e in sorted(activities.items()):
        out_activities.append({
            "key": k,
            "activity": e["activity"],
            "contract": e["contract"],
            "display_name": e["display_name"],
            "purpose": e["purpose"],
            "emits_events": sorted(e["emits_events"]),
            "init_fields": sorted(e["init_fields"]),
            "knobs": e["knobs"],
            "seen_in": sorted(e["seen_in"]),
        })

    # rewards presets (read from gow campaign)
    rewards = []
    camp = load(JOURNEY_TEMPLATES["gow_campaign"])
    for a in camp.get("activities", []):
        init = a.get("initializationData") or {}
        if a.get("activityName") == "freespin_bonus":
            fa = init.get("freespinActivity") or {}
            cc = (fa.get("currenciesConfig") or {}).get("CLP") or {}
            rewards.append({"mechanic": "freespin_bonus", "spins": fa.get("spins"),
                            "provider": fa.get("provider"), "lobbyGameId": fa.get("lobbyGameId"),
                            "game": fa.get("gameTranslationKey"),
                            "betAmount_minor": cc.get("betAmount"), "withWagering": fa.get("withWagering")})
            break
    for a in camp.get("activities", []):
        if a.get("activityName") == "casino_bonus_v2":
            init = a.get("initializationData") or {}
            rewards.append({"mechanic": "casino_bonus_v2", "bonusPercent": init.get("bonusPercent"),
                            "wageringRequirement": init.get("wageringRequirement"),
                            "releaseLimitMultiplier": init.get("releaseLimitMultiplier"),
                            "bonusExpirationTime_ms": init.get("bonusExpirationTime")})
            break

    # segments catalog (from comms template + fragments)
    segments = []
    def seg_from_dwh(init, source):
        ct = init.get("currentTemplate") or {}
        fd = init.get("filterDetails") or {}
        cols = sorted({n.get("name") for n in fd.get("filtersTree", []) if n.get("nodeType") == "Filter" and n.get("name")})
        has_pid = any(n.get("name") == "player_id" for n in fd.get("filtersTree", []) if n.get("nodeType") == "Filter")
        return {"template_id": ct.get("id"), "name": ct.get("name"), "columns": cols,
                "has_player_id_seed": has_pid, "source": source}
    comms = load(JOURNEY_TEMPLATES["gow_comms"])
    for a in comms.get("activities", []):
        if a.get("activityName") == "dwh_source":
            segments.append(seg_from_dwh(a["initializationData"], "gow_comms.json"))
    for frag in SEGMENT_FRAGMENTS:
        segments.append(seg_from_dwh(load(frag), frag))

    # channels summary
    channels = {
        "notification_center#contract1": {"channel": "On-site Notification", "copy_storage": "objectForSend.variables + singleChannel tabs + rawJourneyData mirror"},
        "notification_center#contract5": {"channel": "On-site Pop-up (Cat-fish)", "copy_storage": "same as contract1"},
        "dextra_sms": {"channel": "SMS", "copy_storage": "rawValues + smsSettings + displayData (x3)", "link": "https://{{BrandDomain}}//services/promo/offers/promoPage/<id>", "needs": "BrandDomain in listOfUsedVariables"},
        "dextra_email": {"channel": "Email", "copy_storage": "content-studio (CSE), referenced by emailSettings.template.id", "flow": "create->save->publish, then swap CSE into activity"},
        "native_push": {"channel": "Mobile push", "copy_storage": "defaultNotification.{pushTitle,pushMessage} + imageUrl"},
    }

    return {
        "meta": {
            "brand": "JBCL", "operator": "PMI", "currency": "CLP (minor units x100)",
            "timezone": "Chile/Continental",
            "note": "Auto-extracted from templates/casino/. activities/transitions/rewards/segments are read from real journeys; recipes and knobs are curated.",
            "source_templates": list(JOURNEY_TEMPLATES.values()) + [EMAIL_TEMPLATE] + SEGMENT_FRAGMENTS + ["sport/sport_wof_randomizer.json"],
        },
        "automations": build_automations(),
        "activities": out_activities,
        "transitions_observed": sorted(transitions, key=lambda t: (t["from"], t["on_event"], t["to"])),
        "channels": channels,
        "reward_presets": rewards,
        "segments": segments,
        "recipes": RECIPES,
        "kb_rules": KB_RULES,
        "games_catalog": {
            "file": "games.json",
            "note": "Game-id knob source, captured from GET .../free-spins-bonus-deposit/"
                    "data/games. Partial: 100 of 293 games (page 1 of 3 only). A freespin "
                    "game absent here is not invalid — it may live on an uncaptured page; "
                    "compose.py verify flags it ⚠, never invents a row.",
            "fields": {"lobbyId": "freespinActivity.lobbyGameId",
                       "walletId": "freespinActivity.walletGameId",
                       "externalGameId": "freespinActivity.externalGameId",
                       "gameProvider": "freespinActivity.provider",
                       "translationKey": "freespinActivity.gameTranslationKey"},
        },
        "composed_recipes_note": "Recipes built by compose.py from ONE captured reference "
                                 "each; see the composed_recipes key (added by "
                                 "`compose.py <key> --catalog`). Curated `recipes` above are "
                                 "intent→pattern sketches; composed_recipes carry real node "
                                 "counts, chains, and unit-annotated knobs.",
        "invariants": [
            "compiled body.activities MUST equal the rawJourneyData editor mirror",
            "every activity UUID regenerated consistently on clone; never reuse JRN/CSE ids",
            "strip duplicatedFromId/Version and stale promotionDisplayId",
            "every nextActivityId/journeyActivityId must resolve to an existing activity",
            "channel copy must be present for every channel flagged TRUE in the spec",
        ],
    }


def main() -> int:
    cat = build()
    out = HERE / "catalog.json"
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"  automations: {[a['key'] for a in cat['automations']]}")
    print(f"  activities: {len(cat['activities'])}")
    print(f"  observed transitions: {len(cat['transitions_observed'])}")
    print(f"  reward presets: {len(cat['reward_presets'])}  segments: {len(cat['segments'])}  recipes: {len(cat['recipes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
