#!/usr/bin/env python3
"""Journey Composer — build a REAL custom journey draft JSON from a chain spec.

This is the "AI creates journeys by itself" tool. Input is a chain of activity
types with per-node settings; output is a full POST /journey-drafts body
(activities[] + rawJourneyData mirror), assembled from REAL captured nodes in
templates/casino/gow.json and gow_comms.json — never invented shapes.

How it stays accurate (grounded in REA_BACKOFFICE_AND_JOURNEYS.md):
  * every activity is a deep-cloned captured node, with ALL its captured
    events, initializationData and editor mirror entry;
  * chain wiring uses each node's real "happy path" completion event; every
    other completion event routes to its own end_of_journey activity — exactly
    like the capture (which has 18 undrawn end_of_journey targets);
  * dependencies (CurrencyCode -> source, PromotionId -> promotion, ...) are
    rewired by role to the nearest upstream node of the same captured type;
  * external reference ids (promotionId, ContentId, templates, ...) are never
    touched; internal activity ids are freshly regenerated per node via the
    documented global-string-replace technique;
  * lineage (duplicatedFromId) and server-minted promotionDisplayId are
    stripped so the platform mints fresh ones.

Usage (AI or human):

  # 1. what can I chain, and which settings does each node take?
  python journey_composer.py options --json

  # 2. echo back the interpreted chain for confirmation ("you want this?")
  python journey_composer.py describe spec.json

  # 3. compose the real journey JSON -> out/<name>.journey.json
  python journey_composer.py compose spec.json --json

Spec example (the user's "active segment deposit freespins then wagering"):

  {
    "name": "JBCL | CS | Active seg | Dep -> 50FS -> Wager x30",
    "source": {"type": "segment"},
    "chain": [
      {"type": "promotion"},
      {"type": "deposit", "min_deposit": 1500000},
      {"type": "freespins", "spins": 50, "game": "lagrancopa"},
      {"type": "casino_bonus", "bonus_percent": 100, "wagering": 30}
    ],
    "date": "2026-08-01",
    "days": 1
  }

The composed JSON has reservedJourneyId left blank: creating it live is the
existing hand-off (console script / create_journeys.py machinery reserves a
JRN id and POSTs). This tool never calls the API.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TPL = HERE / "templates" / "casino"
OUT = HERE / "out"
CONSOLE_OUT = HERE / "console_scripts"     # shared with compose.py / the runner

GOW = TPL / "gow.json"
COMMS = TPL / "gow_comms.json"
DEFAULT_SEGMENT = TPL / "segment_cs_301.json"

# Every capture the library draws activity types from, in priority order: the
# first template containing a type supplies the canonical instance.
#
# The "one reference per journey, never mix" rule in COMPOSER_RULES.md is about
# compose.py's RECIPE model, which lifts a whole chain out of one capture and
# depends on that capture's shared shell. This composer works differently — it
# deep-clones each activity WITH its own mirror element, regenerates ids per
# node and rewires dependencies by role — so a node from a second capture is no
# more foreign than a second node from the first. Sport activities (freebet,
# registration) live only in the udch captures, and excluding them made every
# sport prize unbuildable.
SOURCES = (
    GOW,
    COMMS,
    HERE / "templates" / "udch" / "two_hours.json",     # freebet, registration
    HERE / "templates" / "udch" / "followup.json",      # multipurpose + freebet
)

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Known games (mirrors casino_journey.py GAMES — the only captured-valid tuples).
GAMES: dict[str, dict[str, str]] = {
    "lagrancopa": {
        "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
        "walletGameId": "gg_la_gran_copa_jugabet",
        "externalGameId": "gg_la_gran_copa_jugabet",
        "provider": "jugabet-games",
        "gameTranslationKey": "La Gran Copa Jugabet",
    },
    "spinandscoremegaways": {
        "lobbyGameId": "pragmatic-spin-score-megaways",
        "walletGameId": "vswaysfrywld",
        "externalGameId": "vswaysfrywld",
        "provider": "pragmatic",
        "gameTranslationKey": "Spin & Score Megaways",
    },
}

# The two entries above are legacy shorthands. The authoritative registry is
# library/games.json (106 games), the same file compose.py grounds against —
# hardcoding a two-game list here meant every other game was unbuildable.
GAMES_FILE = HERE / "library" / "games.json"
_GAME_FIELDS = ("lobbyGameId", "walletGameId", "externalGameId", "provider",
                "gameTranslationKey", "providerTranslationKey")


def _norm(s: str) -> str:
    """Loose key for name matching: 'La Gran Copa Jugabet' -> 'lagrancopajugabet'."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _game_index() -> dict[str, dict[str, str]]:
    """Every way a brief might name a game -> that game's captured id tuple.
    Indexes lobbyGameId, each alias, and the display name, all normalised."""
    if not hasattr(_game_index, "_cache"):
        idx: dict[str, dict[str, str]] = {}
        for slug, entry in GAMES.items():          # legacy shorthands win ties
            idx[_norm(slug)] = dict(entry)
        try:
            registry = json.loads(GAMES_FILE.read_text(encoding="utf-8")).get("games") or {}
        except (OSError, ValueError):
            registry = {}
        for lobby_id, entry in registry.items():
            tup = {f: entry.get(f) for f in _GAME_FIELDS if entry.get(f)}
            if not tup.get("providerTranslationKey") and entry.get("provider"):
                tup["providerTranslationKey"] = " ".join(
                    w.capitalize() for w in str(entry["provider"]).replace("_", "-").split("-") if w)
            if not tup.get("lobbyGameId"):
                continue
            keys = [lobby_id, entry.get("gameTranslationKey"), *(entry.get("aliases") or [])]
            for k in keys:
                if k:
                    idx.setdefault(_norm(k), tup)
        _game_index._cache = idx
    return _game_index._cache


def resolve_game(name: str) -> dict[str, str]:
    """Resolve a brief's game name to its captured id tuple, or refuse.

    Previously an unknown game only warned and kept the reference template's
    game, so a journey would silently award spins on gow.json's own game under
    a fully green build. A game nobody can resolve is a plan with a hole."""
    idx = _game_index()
    hit = idx.get(_norm(name))
    if hit:
        return hit
    import difflib
    key = _norm(name)
    near = difflib.get_close_matches(key, list(idx), n=3, cutoff=0.6)
    # Briefs often use a short form ("Big Bass"), which scores too low for
    # difflib but is an unambiguous prefix/substring of the real title.
    if len(key) >= 4:
        near += [k for k in idx if key in k and k not in near][:5]
    suggestions = sorted({idx[n].get("gameTranslationKey") or n for n in near})[:5]
    raise SystemExit(
        f"unknown game {name!r} — not in {GAMES_FILE.name} ({len(idx)} lookup keys). "
        + (f"Did you mean: {suggestions}? " if suggestions else "")
        + "Refusing to keep the reference template's game, which would award "
          "spins on the wrong title.")

# chain-type aliases -> canonical captured activity key (every captured type)
ALIASES = {
    "csv": "dwh_source", "segment": "dwh_source", "dwh_source": "dwh_source",
    "api": "external_system_source", "external_system_source": "external_system_source",
    "promotion": "promotion",
    "drip": "multipurpose_promotion", "multipurpose_promotion": "multipurpose_promotion",
    "deposit": "deposit",
    "freespin": "freespin_bonus", "freespins": "freespin_bonus", "freespin_bonus": "freespin_bonus",
    "bonus": "casino_bonus_v2", "casino_bonus": "casino_bonus_v2", "wagering": "casino_bonus_v2",
    "casino_bonus_v2": "casino_bonus_v2",
    "notification": "notification_center#contract1", "nc": "notification_center#contract1",
    # The canonical activity name must resolve too. Without it a spec written
    # with the platform's own wire name — which is what the knowledge base and
    # MODE 1/2 output both use — was refused as an unknown chain type.
    "notification_center": "notification_center#contract1",
    "onsite": "notification_center#contract1",
    "popup": "notification_center#contract5",
    # Sport activities, available since the udch captures joined SOURCES.
    "freebet": "freebet", "free_bet": "freebet", "sport_freebet": "freebet",
    "sport_bonus": "sport_bonus", "sportbonus": "sport_bonus",
    "registration": "registration", "promocode": "registration",
    "reference_codes": "registration",
    "campaign_connector": "campaign_connector", "connector": "campaign_connector",
    "random_split": "random_split", "randomsplit": "random_split",
    "sms": "dextra_sms", "dextra_sms": "dextra_sms",
    "email": "dextra_email", "dextra_email": "dextra_email",
    "wait": "wait_interval", "wait_interval": "wait_interval",
    "event": "event_detector", "event_detector": "event_detector",
    "ncsplit": "notification_center_engagement_split",
    "notification_center_engagement_split": "notification_center_engagement_split",
    "emailsplit": "email_engagement_split", "email_engagement_split": "email_engagement_split",
    "decisionsplit": "ams_decision_split", "ams_decision_split": "ams_decision_split",
}
# Entry activities. `registration` (the backoffice's "Reference codes" node)
# fires PlayerAdded, an ACTIVATION — it starts a journey, it cannot sit in
# the middle of one, so it belongs here rather than among the chain types.
SOURCE_TYPES = {"dwh_source", "external_system_source", "registration"}

# The default forward completion event per node type — all are real captured
# events. Override per node with "follow": "<EventName>"; route other events
# into sub-chains with "branches": {"<EventName>": [ ...nodes ]}.
HAPPY = {
    "promotion": "PromotionAccepted",
    "multipurpose_promotion": "PromotionAccepted",
    "deposit": "DepositConditionSatisfied",
    "freespin_bonus": "FreespinBonusCollectingFinished",
    "casino_bonus_v2": "WageringBonusFinished",
    "notification_center#contract1": "NotificationSent",
    "notification_center#contract5": "NotificationSent",
    "dextra_sms": "SuccessSmsSend",
    "dextra_email": "SuccessEmailSend",
    "freebet": "PlayerFreebetUsed",
    "sport_bonus": "SportBonusFinished",
    "campaign_connector": "PlayerAddedToCampaign",
    "wait_interval": "WaitTimeCompleted",
    "event_detector": "DetectorSuccess",
    # splits: default to the captured "engaged" path; use follow/branches to
    # route the other paths (all path events are real captured Completions)
    "notification_center_engagement_split": "NCEngagementSplitPassedPath02",
    "email_engagement_split": "Path2",
    "ams_decision_split": "DecisionSplitPassedPath01",
}

# Per-node settings the composer knows how to apply (documented for `options`).
SETTINGS_DOC = {
    "dwh_source": {"segment_file": "path to a captured dwh initializationData fragment (default segment_cs_301.json)"},
    "external_system_source": {"description": "free-text label shown on the API entry node"},
    "promotion": {"(none)": "external promotion refs are kept from the capture; promotionDisplayId is stripped"},
    "deposit": {"min_deposit": "minimum deposit amount, platform minor units (all tiers set to this)",
                "timeout": "ISO-8601 window, e.g. P0Y0M1DT0H0M0S"},
    "freespin_bonus": {"spins": "free-spin count",
                       "spins_expiration_ms": "how long the spins stay usable, in "
                                              "milliseconds (24h = 86400000)",
                       "with_wagering": "false for an INSTANT bonus (no wagering "
                                        "grind, no casino_bonus follow-up node)",
                       "game": "game name, id or alias from library/games.json "
                               "(see the `games` key); unknown names are REFUSED",
                       "bet_amount": "currenciesConfig.CLP.betAmount (minor units)"},
    "freebet": {"amount": "free-bet value, platform MINOR units (3,000 CLP -> 300000)",
                "max_odds": "maximum odds the free bet can be used at",
                "expire_days": "days the free bet stays valid once issued"},
    "registration": {"promocode": "the promocode players redeem to enter"},
    "casino_bonus_v2": {"bonus_percent": "deposit-match %", "wagering": "wagering requirement (x)",
                        "release_multiplier": "releaseLimitMultiplier", "expiration_ms": "bonusExpirationTime in ms"},
    "notification_center#contract1": {"title_en/es, desc_en/es, caption_en/es": "on-site notification copy",
                                      "icon": "notification artwork URL — set it, or the card shows "
                                              "the captured campaign's image",
                                      "link_en/es": "where the card sends the player",
                                      "deeplink": "app deeplink, when there is one"},
    "notification_center#contract5": {"title_en/es, desc_en/es, caption_en/es": "pop-up (Cat-fish) copy",
                                      "image": "pop-up background artwork URL — set it, or the "
                                               "journey shows the captured campaign's picture"},
    "dextra_sms": {"text_en/es": "SMS body"},
    "dextra_email": {"template": "content-studio email id (e.g. CSE-0-14458). Set it, or the "
                                 "journey emails the CAPTURED campaign's template — which the "
                                 "inherited-content check refuses to build",
                     "from_name": "from-line text (default: the reference's)"},
    "wait_interval": {"wait": "ISO-8601 duration, e.g. P0Y0M0DT1H0M0S"},
    "event_detector": {"(none)": "captured deposit-band watcher kept as-is"},
    "multipurpose_promotion": {"(none)": "captured choosable-flow drip kept as-is (see warning on compose)"},
    "notification_center_engagement_split": {"(none)": "branch with follow/branches on NCEngagementSplitPassedPath01..05"},
    "email_engagement_split": {"(none)": "branch with follow/branches on Path1..Path6"},
    "ams_decision_split": {"(none)": "branch with follow/branches on DecisionSplitPassedPath01..20/RemainderPath"},
}
# keys valid on every chain node, besides type + per-type settings
UNIVERSAL_KEYS = {"type", "follow", "branches", "parallel"}


# ── template library ─────────────────────────────────────────────────────────
def _akey(activity: dict) -> str:
    name = activity.get("activityName", "?")
    init = activity.get("initializationData") or {}
    if name == "notification_center" and "contract" in init:
        return f"{name}#contract{init['contract']}"
    return name


def load_library() -> dict:
    """Pick ONE canonical captured instance per activity type, with its mirror
    element, activitiesConfiguration entry, pathesConfiguration entry, and its
    captured outgoing edges keyed by eventName."""
    lib: dict[str, dict] = {}
    for path in SOURCES:
        body = json.loads(path.read_text(encoding="utf-8-sig"))
        raw = body["rawJourneyData"]
        els = raw["elements"]
        nodes = {e["id"]: e for e in els if "source" not in e}
        edges_by_src: dict[str, dict] = {}
        for e in els:
            if "source" in e:
                edges_by_src.setdefault(e["source"], {})[(e.get("data") or {}).get("eventName")] = e
        acfg = raw.get("activitiesConfiguration") or {}
        pcfg = raw.get("pathesConfiguration") or {}
        by_id = {a["activityId"]: a for a in body["activities"]}
        for a in body["activities"]:
            k = _akey(a)
            if k in lib:
                continue
            aid = a["activityId"]
            lib[k] = {
                "activity": a,
                "element": nodes.get(aid),
                "config": acfg.get(aid),
                "paths": pcfg.get(aid),
                "edges": edges_by_src.get(aid, {}),
                "captured_neighbors": by_id,   # to resolve captured dep targets
                "template": path.name,
            }
    # journey skeleton: gow.json top level (drop the graph, keep the envelope)
    skel = json.loads(GOW.read_text(encoding="utf-8-sig"))
    return {"types": lib, "skeleton": skel}


# ── cloning with fresh ids ───────────────────────────────────────────────────
def load_parallel_parts() -> dict | None:
    """The captured parallelFlow container and one flowEntry header.

    Parallel flows are the one structure that is not a plain activity: the owner
    activity's forward event carries `split.paths`, and the canvas gets a
    container element whose children are re-parented into it. Both pieces are
    CAPTURED in gow.json, so this clones them like everything else rather than
    synthesising canvas — synthesising is what produces blank drafts.

    Layout constants come from the capture: flows are columns 480px apart, the
    header sits 88px down, content starts at 208px.
    """
    if not hasattr(load_parallel_parts, "_cache"):
        parts = None
        try:
            els = json.loads(GOW.read_text(encoding="utf-8-sig"))["rawJourneyData"]["elements"]
            container = next(e for e in els if e.get("type") == "parallelFlow")
            entry = next(e for e in els
                         if e.get("type") == "flowEntry"
                         and e.get("parentNode") == container["id"])
            parts = {"container": container, "flow_entry": entry,
                     "col_step": 480, "header_y": 88, "content_y": 208}
        except (OSError, ValueError, StopIteration, KeyError):
            parts = None
        load_parallel_parts._cache = parts
    return load_parallel_parts._cache


def clone_with_fresh_id(entry: dict) -> dict:
    """Deep-clone a library node and swap its captured activityId for a fresh
    uuid4 via serialized string replace (ports/handles/config keys embed the id
    as a substring — the documented technique)."""
    old = entry["activity"]["activityId"]
    new = str(uuid.uuid4())
    blob = json.dumps({
        "activity": entry["activity"],
        "element": entry["element"],
        "config": entry["config"],
        "paths": entry["paths"],
    }, ensure_ascii=False).replace(old, new)
    out = json.loads(blob)
    out["new_id"] = new
    out["captured_id"] = old
    return out


def make_end_of_journey(lib: dict) -> dict:
    """A fresh end_of_journey activity (undrawn, exactly like the capture's 18)."""
    tpl = lib["types"]["end_of_journey"]["activity"]
    a = copy.deepcopy(tpl)
    a["activityId"] = str(uuid.uuid4())
    return a


# ── settings appliers (edit activity init + mirror config) ───────────────────
def _apply_settings(kind: str, node: dict, s: dict, report: list, warnings: list) -> None:
    act = node["activity"]
    init = act.get("initializationData") or {}
    cfg = (node.get("config") or {}).get("data") if node.get("config") else None

    def note(field, old, newv):
        report.append(f"{kind}: {field}: {old!r} -> {newv!r}")

    if kind == "deposit":
        if "min_deposit" in s:
            for t in (init.get("depositConditions") or {}).get("minDepositAmounts", []):
                note("minDepositAmounts.amount", t.get("amount"), s["min_deposit"])
                t["amount"] = s["min_deposit"]
        if "timeout" in s:
            dc = init.get("depositConditions") or {}
            note("expirationTimeout", dc.get("expirationTimeout"), s["timeout"])
            dc["expirationTimeout"] = s["timeout"]
    elif kind == "freespin_bonus":
        fa = init.get("freespinActivity") or {}
        if "spins" in s:
            note("spins", fa.get("spins"), s["spins"]); fa["spins"] = s["spins"]
        if "game" in s:
            # resolve_game refuses an unresolvable name rather than leaving the
            # reference template's game in place under a green build.
            for k, v in resolve_game(str(s["game"])).items():
                note(k, fa.get(k), v); fa[k] = v
        if "spins_expiration_ms" in s:
            note("spinsExpirationDuration", fa.get("spinsExpirationDuration"), s["spins_expiration_ms"])
            fa["spinsExpirationDuration"] = s["spins_expiration_ms"]
        if "with_wagering" in s:
            # The instant-bonus marker: freespinActivity.withWagering false and
            # no wagering follow-up node. Without this setting an instant bonus
            # could only be expressed by omitting the casino_bonus_v2 node, and
            # the captured node's own withWagering=true survived into it.
            v = bool(s["with_wagering"])
            note("withWagering", fa.get("withWagering"), v); fa["withWagering"] = v
        if "bet_amount" in s:
            cc = (fa.get("currenciesConfig") or {}).get("CLP") or {}
            note("betAmount", cc.get("betAmount"), s["bet_amount"]); cc["betAmount"] = s["bet_amount"]
            if "betAmount_majorUnits" in cc:      # proven pipeline keeps both in sync
                cc["betAmount_majorUnits"] = int(s["bet_amount"]) // 100
    elif kind == "freebet":
        props = init.get("properties") or {}
        if "amount" in s:
            cur = props.get("freeBetAmount") or {}
            for ccy in (cur or {"CLP": None}):
                note(f"freeBetAmount.{ccy}", cur.get(ccy), s["amount"]); cur[ccy] = s["amount"]
            props["freeBetAmount"] = cur
        if "max_odds" in s:
            note("maxOdd", props.get("maxOdd"), s["max_odds"]); props["maxOdd"] = s["max_odds"]
        if "expire_days" in s:
            note("expireInDays", props.get("expireInDays"), s["expire_days"])
            props["expireInDays"] = s["expire_days"]
    elif kind == "registration":
        if "promocode" in s:
            # The captured entry node carries a real promocode (VAMOSBULLA);
            # leaving it is how another campaign's code reached a new journey.
            ps = init.get("promocodeSettings") or {}
            note("promocodeSettings.values", ps.get("values"), [s["promocode"]])
            ps["values"] = [s["promocode"]]
            init["displayData"] = [f"Promo codes: {s['promocode']}"]
    elif kind == "casino_bonus_v2":
        pairs = {"bonus_percent": "bonusPercent", "wagering": "wageringRequirement",
                 "release_multiplier": "releaseLimitMultiplier", "expiration_ms": "bonusExpirationTime"}
        for sk, fk in pairs.items():
            if sk in s:
                note(fk, init.get(fk), s[sk]); init[fk] = s[sk]
                wa = init.get("wageringActivity")
                if isinstance(wa, dict) and fk in wa:      # nested mirror
                    wa[fk] = s[sk]
    elif kind in ("notification_center#contract1", "notification_center#contract5"):
        # copy lives in objectForSend.variables AND singleChannel.localizedLanguagesTab
        # (contract1 keys: title-en/des-en/caption-en; contract5: title_en/description_en/caption_en)
        vars_ = (init.get("objectForSend") or {}).get("variables") or []
        tabs = (init.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
        # `link` matters as much as the copy: a captured card carries the OLD
        # campaign's promo-page URL, so a new journey silently linked players to
        # the previous promotion.
        keymap = {"title": "title", "desc": "des", "caption": "caption", "link": "link"}
        for skey, stem in keymap.items():
            for lang in ("en", "es"):
                val = s.get(f"{skey}_{lang}")
                if val is None:
                    continue
                hit = False
                for v in vars_:
                    n = (v.get("name") or "").lower()
                    if stem in n and lang in n:
                        note(v["name"], v.get("value"), val); v["value"] = val; hit = True
                for tab in tabs.values():
                    if not isinstance(tab, dict):
                        continue
                    for tk in tab:
                        tn = tk.lower()
                        if stem in tn and lang in tn:
                            tab[tk] = val; hit = True
                if not hit:
                    warnings.append(f"{kind}: no captured variable matched {skey}_{lang}")
        # Language-independent fields, held once in the `common` tab.
        for skey, stems in (("icon", ("icon",)),
                            # the pop-up's artwork is a background image, not an
                            # icon — a chain that set only `icon` still shipped
                            # the captured campaign's picture
                            ("image", ("background_image_src", "backgroundimagesrc")),
                            ("deeplink", ("deeplink",))):
            val = s.get(skey)
            if val is None:
                continue
            for v in vars_:
                if (v.get("name") or "").lower() in stems:
                    note(v["name"], v.get("value"), val); v["value"] = val
            for tab in tabs.values():
                if isinstance(tab, dict):
                    for tk in list(tab):
                        if tk.lower() in stems:
                            tab[tk] = val
    elif kind == "dextra_email":
        # The email node is copied whole, so without this it keeps the captured
        # campaign's template — and the inherited-content guard (rightly) refuses
        # to build a comms journey that would email players the old promotion.
        es = init.get("emailSettings") or {}
        if "template" in s and es:
            tpl = es.get("template") or {}
            note("emailSettings.template.id", tpl.get("id"), s["template"])
            tpl["id"] = s["template"]
            es["template"] = tpl
            # displayData is what the builder shows on the card; leaving the old
            # id there is how a reviewer sees the wrong template name.
            init["displayData"] = [str(s["template"])]
        if "from_name" in s and es:
            note("emailSettings.fromLineText", es.get("fromLineText"), s["from_name"])
            es["fromLineText"] = s["from_name"]
    elif kind == "dextra_sms":
        for lang in ("en", "es"):
            val = s.get(f"text_{lang}")
            if val is None:
                continue
            for holder in (init.get("rawValues"), init.get("smsSettings")):
                if not isinstance(holder, dict):
                    continue
                if lang == "en" and "messageText" in holder:
                    note("messageText", holder["messageText"], val); holder["messageText"] = val
                # localizedMessageTexts appears in BOTH captured shapes:
                #   rawValues:   {"en": {messageText,...}, "es": {...}}   (dict by lang)
                #   smsSettings: [{messageText, languageCode}, ...]       (list)
                loc = holder.get("localizedMessageTexts")
                if isinstance(loc, dict):
                    for k in list(loc):
                        if k.lower() != lang:
                            continue
                        if isinstance(loc[k], dict) and "messageText" in loc[k]:
                            note(f"localizedMessageTexts.{k}.messageText", loc[k]["messageText"], val)
                            loc[k]["messageText"] = val
                        else:
                            note(f"localizedMessageTexts.{k}", loc[k], val)
                            loc[k] = val
                elif isinstance(loc, list):
                    for item in loc:
                        if isinstance(item, dict) and str(item.get("languageCode", "")).lower() == lang:
                            note(f"localizedMessageTexts[{lang}].messageText", item.get("messageText"), val)
                            item["messageText"] = val
    elif kind == "wait_interval":
        if "wait" in s:
            note("waitPeriod", init.get("waitPeriod"), s["wait"]); init["waitPeriod"] = s["wait"]
    elif kind == "external_system_source":
        if "description" in s:
            note("description", init.get("description"), s["description"])
            init["description"] = s["description"]
            if cfg is not None and "description" in cfg:
                cfg["description"] = s["description"]
    elif kind == "dwh_source":
        frag_path = Path(s.get("segment_file") or DEFAULT_SEGMENT)
        if not frag_path.is_absolute():
            frag_path = HERE / frag_path
        frag = json.loads(frag_path.read_text(encoding="utf-8-sig"))
        for k in ("filterDetails", "currentTemplate", "dataSourceName"):
            if k in frag:
                init[k] = frag[k]
                if cfg is not None and k in cfg:    # keep the editor mirror in sync
                    cfg[k] = copy.deepcopy(frag[k])
        report.append(f"dwh_source: segment <- {frag_path.name} "
                      f"({(frag.get('currentTemplate') or {}).get('name')!r})")

    # DUAL STORAGE: the editor mirror keeps its own copy of the activity config,
    # and the setters above edit only initializationData. Without this sync the
    # journey RUNS with the new copy while the builder still SHOWS the captured
    # campaign's — the notification content set on a wheel-prize journey landed
    # on the activity and left "🏆 La Gran Copa JugaBet" in the mirror.
    if cfg is not None:
        for mirror_key in list(cfg.keys()):
            if mirror_key in init:
                cfg[mirror_key] = copy.deepcopy(init[mirror_key])
    # displayData is the label the builder prints on the node, and it lives at
    # the mirror entry's TOP level, a sibling of `data` — so the loop above never
    # reached it and a renamed promocode still showed "Promo codes: VAMOSBULLA".
    conf = node.get("config")
    if isinstance(conf, dict):
        for top_key in ("displayData",):
            if top_key in conf and top_key in init:
                conf[top_key] = copy.deepcopy(init[top_key])

    # Unknown keys are REFUSED, not warned about. A warning here meant a spec
    # that nested its values under "settings", or used a recipe knob name like
    # spin_bet_clp instead of bet_amount, composed cleanly and shipped the
    # captured template's own values — 50 spins on La Gran Copa when the brief
    # asked for 30 on Big Bass, "VERIFIED OK", exit 0.
    known = {
        "deposit": {"min_deposit", "timeout"},
        "freespin_bonus": {"spins", "game", "bet_amount", "with_wagering",
                           "spins_expiration_ms"},
        "freebet": {"amount", "max_odds", "expire_days"},
        "registration": {"promocode"},
        "casino_bonus_v2": {"bonus_percent", "wagering", "release_multiplier", "expiration_ms"},
        "notification_center#contract1": {f"{a}_{l}" for a in ("title", "desc", "caption", "link") for l in ("en", "es")} | {"icon", "image", "deeplink"},
        "notification_center#contract5": {f"{a}_{l}" for a in ("title", "desc", "caption", "link") for l in ("en", "es")} | {"icon", "image", "deeplink"},
        "dextra_sms": {"text_en", "text_es"},
        "dextra_email": {"template", "from_name"},
        "wait_interval": {"wait"},
        "external_system_source": {"description"},
        "dwh_source": {"segment_file"},
    }.get(kind, set())
    bad = [k for k in s if k not in known and k not in UNIVERSAL_KEYS]
    if bad:
        hint = ""
        if "settings" in bad:
            hint = (" — put settings INLINE on the node "
                    '({"type": "freespins", "spins": 30}), not nested under a '
                    '"settings" key')
        raise SystemExit(
            f"{kind}: unsupported setting(s) {sorted(bad)}{hint}. "
            f"Known for this activity: {sorted(known)} (plus {sorted(UNIVERSAL_KEYS)}). "
            f"Refusing to build — an ignored setting ships the captured "
            f"template's own value instead of the one you asked for.")


# ── the composer ─────────────────────────────────────────────────────────────
def compose(spec: dict) -> dict:
    lib = load_library()
    types = lib["types"]
    report: list[str] = []
    warnings: list[str] = []

    # resolve source
    src_spec = spec.get("source") or {}
    src_kind = ALIASES.get(str(src_spec.get("type", "")).lower())
    if src_kind not in SOURCE_TYPES:
        raise SystemExit(f"source.type must be one of csv/segment/api, got {src_spec.get('type')!r}")
    chain_specs = spec.get("chain") or []
    # A spec often ends with an explicit terminal because that is how MODE 1/2
    # writes the flow out ("... -> freespins -> end_of_journey"). The composer
    # appends the terminal itself, so an explicit one is redundant, not wrong —
    # refusing it made the model rewrite a correct chain to fix a non-problem.
    _TERMINALS = {"end", "end_of_journey", "end_of_path", "exit", "endofjourney"}
    while chain_specs and str((chain_specs[-1] or {}).get("type", "")).lower() in _TERMINALS:
        chain_specs = chain_specs[:-1]
    if not chain_specs:
        raise SystemExit("chain must have at least one node")

    def resolve_kind(c: dict) -> str:
        k = ALIASES.get(str(c.get("type", "")).lower())
        if k is None or k in SOURCE_TYPES:
            raise SystemExit(f"unknown chain node type {c.get('type')!r}. Known: "
                             + ", ".join(sorted(set(ALIASES) - {'csv', 'segment', 'api'})))
        if k not in types:
            raise SystemExit(f"{k} has no captured template node — cannot compose it accurately")
        return k

    src = clone_with_fresh_id(types[src_kind])
    _apply_settings(src_kind, src, src_spec, report, warnings)

    ends: list[dict] = []

    def fresh_end() -> str:
        e = make_end_of_journey(lib)
        ends.append(e)
        return e["activityId"]

    # placed: every chain/branch node with its upstream context for dep rewiring
    # entry: {kind, node, upstream: [(kind,new_id),...], col, row}
    placed: list[dict] = []
    edges_wanted: list[tuple] = []     # (node_entry|"src", event, target_id)
    exits_drawn: list[tuple] = []      # (end_id, col, row)
    parallel_blocks: list[dict] = []   # filled by build_level, drawn after layout
    col_counter = [0]

    def completion_events(kind: str) -> set:
        return {e["eventName"] for e in types[kind]["activity"].get("events", [])
                if e.get("eventType") == "Completion"}

    def build_level(specs: list[dict], upstream: list[tuple], row: int) -> str:
        """Clone+wire one chain level; returns the head node's new id."""
        level: list[dict] = []
        for c in specs:
            k = resolve_kind(c)
            node = clone_with_fresh_id(types[k])
            _apply_settings(k, node, c, report, warnings)
            if k == "multipurpose_promotion":
                warnings.append("multipurpose_promotion: choosable-flow sub-elements are not "
                                "re-drawn; open the draft in the editor to verify the flows")
            level.append({"kind": k, "node": node, "spec": c})

        term = fresh_end()
        col0 = col_counter[0]
        for i, entry in enumerate(level):
            k, node, c = entry["kind"], entry["node"], entry["spec"]
            comp = completion_events(k)
            follow = c.get("follow") or HAPPY.get(k)
            if follow not in comp:
                raise SystemExit(f"{k}: follow event {follow!r} is not a captured Completion "
                                 f"event (captured: {sorted(comp)})")
            branches = c.get("branches") or {}
            for bev in branches:
                if bev not in comp:
                    raise SystemExit(f"{k}: branch event {bev!r} is not a captured Completion "
                                     f"event (captured: {sorted(comp)})")
                if bev == follow:
                    raise SystemExit(f"{k}: event {bev!r} cannot be both follow and branch")

            node_upstream = upstream + [(e["kind"], e["node"]["new_id"]) for e in level[:i + 1]]
            placed.append({"kind": k, "node": node, "upstream": node_upstream[:-1],
                           "col": col_counter[0], "row": row})
            col_counter[0] += 1

            nxt = level[i + 1]["node"]["new_id"] if i + 1 < len(level) else term
            branch_heads = {bev: build_level(bspecs, node_upstream, row + 1 + list(branches).index(bev))
                            for bev, bspecs in branches.items()}

            # PARALLEL: the follow event fans out into N simultaneous flows via
            # split.paths instead of a single nextActivityId. Each flow is an
            # ordinary chain; the wrap into a container element happens after
            # layout, in _wrap_parallel().
            parallel_specs = c.get("parallel") or []
            parallel_plan = None
            if parallel_specs:
                if not isinstance(parallel_specs, list) or not all(
                        isinstance(f, list) and f for f in parallel_specs):
                    raise SystemExit(
                        f"{k}: `parallel` must be a list of flows, each a non-empty "
                        f"list of chain nodes — e.g. "
                        f'"parallel": [[{{"type":"freespins","spins":100}}], [...], [...]]')
                if branches:
                    raise SystemExit(
                        f"{k}: use either `branches` (one event each) or `parallel` "
                        f"(one event, simultaneous flows), not both on one node.")
                flows = []
                for fi, fspecs in enumerate(parallel_specs):
                    head = build_level(fspecs, node_upstream, row + 1 + fi)
                    flows.append({"flow_id": str(uuid.uuid4()), "head": head,
                                  "path_id": fi + 1, "name": f"Flow {fi + 1}"})
                parallel_plan = {"owner": entry, "event": follow, "flows": flows, "after": nxt}
                parallel_blocks.append(parallel_plan)

            for ev in node["activity"].get("events", []):
                # A captured node can arrive with `split` already on one of its
                # events — the original journey's parallel block. Its flowIds and
                # nextActivityIds point at nodes that do not exist here, so it is
                # a dangling reference on every event we are not fanning out on.
                if not (parallel_plan and ev.get("eventName") == follow):
                    ev.pop("split", None)
                if ev.get("eventType") != "Completion":
                    ev.pop("nextActivityId", None)      # boundary events carry no next
                    continue
                en = ev.get("eventName")
                if en == follow and parallel_plan:
                    # The capture keeps nextActivityId alongside split; the split
                    # is what the engine fans out on.
                    ev["split"] = {"paths": [
                        {"pathId": f["path_id"], "pathName": f["name"],
                         "flowId": f["flow_id"], "nextActivityId": f["head"]}
                        for f in parallel_plan["flows"]]}
                    ev["nextActivityId"] = parallel_plan["flows"][0]["head"]
                elif en == follow:
                    ev["nextActivityId"] = nxt
                    edges_wanted.append((entry, en, nxt))
                elif en in branch_heads:
                    ev["nextActivityId"] = branch_heads[en]
                    edges_wanted.append((entry, en, branch_heads[en]))
                else:
                    ev["nextActivityId"] = fresh_end()  # undrawn end, like the capture
        exits_drawn.append((term, col0 + len(level), row))
        return level[0]["node"]["new_id"]

    head_id = build_level(chain_specs, [(src_kind, src["new_id"])], 0)

    # source activation -> chain head
    for ev in src["activity"].get("events", []):
        if ev.get("eventType") == "Activation":
            ev["nextActivityId"] = head_id

    # ── dependency rewiring by role (upstream-aware, branch-aware) ──
    def rewire_deps(entry: dict) -> None:
        k, node = entry["kind"], entry["node"]
        cap_neighbors = types[k]["captured_neighbors"]
        act = node["activity"]
        ups = entry["upstream"]
        for dep_list_key in ("dependencies", "dataDependencies"):
            deps = act.get(dep_list_key)
            if not isinstance(deps, list):
                continue
            kept = []
            for d in deps:
                if not isinstance(d, dict) or "journeyActivityId" not in d:
                    kept.append(d)
                    continue
                tgt_cap = cap_neighbors.get(d["journeyActivityId"])
                role = _akey(tgt_cap) if tgt_cap else None
                if role in SOURCE_TYPES:
                    d["journeyActivityId"] = src["new_id"]
                    kept.append(d)
                    continue
                up = next((uid for un, uid in reversed(ups) if un == role), None)
                if up:
                    d["journeyActivityId"] = up
                    kept.append(d)
                else:
                    warnings.append(
                        f"{k}: dropped dependency {d.get('key')!r} -> {role or 'unknown'} "
                        f"(no upstream {role} in this chain; the platform may reject if it is required)")
            act[dep_list_key] = kept

    for entry in placed:
        rewire_deps(entry)

    # ── mirror: elements, edges, configs ──
    elements: list[dict] = []
    X0, XSTEP, Y0, YSTEP = 120, 420, 300, 260

    def put(el: dict | None, col: int, row: int, kind: str) -> None:
        if not el:
            warnings.append(f"{kind}: captured node had no mirror element; left undrawn")
            return
        pos = {"x": X0 + col * XSTEP, "y": Y0 + row * YSTEP}
        el["position"] = dict(pos)
        el["positionAbsolute"] = dict(pos)
        elements.append(el)

    put(src.get("element"), 0, 0, src_kind)
    for entry in placed:
        put(entry["node"].get("element"), entry["col"] + 1, entry["row"], entry["kind"])
    for end_id, col, row in exits_drawn:
        elements.append({
            "id": end_id,
            "data": {"name": "end_of_journey", "ports": [{"id": f"input-{end_id}"}],
                     "width": 40, "height": 40},
            "type": "exit", "style": {}, "width": 40, "height": 40, "hidden": False, "zIndex": 2,
            "position": {"x": X0 + (col + 1) * XSTEP, "y": Y0 + row * YSTEP},
            "selected": False, "draggable": True, "connectable": True,
            "positionAbsolute": {"x": X0 + (col + 1) * XSTEP, "y": Y0 + row * YSTEP},
        })

    def names_raw(k: str) -> str:
        return k.split("#", 1)[0]

    def make_edge(sid: str, src_kind_: str, ev_name: str, tgt_id: str) -> dict:
        # prefer the node's own captured edge for this event; else any captured
        # edge with the event; else synthesize the minimal captured edge shape
        cap = types[src_kind_]["edges"].get(ev_name)
        if cap is None:
            for t in types.values():
                if ev_name in t["edges"]:
                    cap = t["edges"][ev_name]
                    break
        if cap is not None:
            blob = json.dumps(cap, ensure_ascii=False)
            blob = blob.replace(cap["source"], sid).replace(cap["target"], tgt_id)
            e = json.loads(blob)
            e["id"] = str(uuid.uuid4())
            return e
        return {
            "id": str(uuid.uuid4()),
            "data": {"isHidden": False, "eventName": ev_name, "eventType": "Completion",
                     "activityName": names_raw(src_kind_), "isLabelHidden": True,
                     "isReconnectable": False, "eventDisplayName": ev_name,
                     "isDisconnectable": False, "canBeUsedInChoosableFlow": False},
            "type": "default", "style": {}, "hidden": False,
            "source": sid, "target": tgt_id, "zIndex": 1,
            "sourceHandle": f"{ev_name}-{sid}", "targetHandle": f"input-{tgt_id}",
        }

    def port_edge(sid: str, tgt_id: str, source_handle: str, activity_name: str,
                  event_name: str = "") -> dict:
        """An edge whose source port is NOT an event handle — the container and
        flowEntry connectors, which hang off named ports instead."""
        return {
            "id": str(uuid.uuid4()),
            "data": {"isHidden": False, "eventName": event_name,
                     "eventType": "Completion" if event_name else None,
                     "activityName": activity_name, "isLabelHidden": True,
                     "isReconnectable": False, "eventDisplayName": event_name,
                     "isDisconnectable": False, "canBeUsedInChoosableFlow": False},
            "type": "default", "style": {"strokeDasharray": "3"}, "hidden": False,
            "source": sid, "target": tgt_id, "zIndex": 1,
            "sourceHandle": source_handle, "targetHandle": f"input-{tgt_id}",
            "labelBgPadding": [10, 3], "labelBgBorderRadius": 4,
            "labelStyle": {"color": "#000", "fontSize": 14, "fontWeight": 700},
            "labelBgStyle": {"fill": "#D2D2D2"},
        }

    act_ev = next((e["eventName"] for e in src["activity"].get("events", [])
                   if e.get("eventType") == "Activation"), "PlayerAdded")
    elements.append(make_edge(src["new_id"], src_kind, act_ev, head_id))
    for entry, ev_name, tgt in edges_wanted:
        elements.append(make_edge(entry["node"]["new_id"], entry["kind"], ev_name, tgt))

    # ── wrap parallel blocks: container element + flowEntry headers ──
    # Done AFTER layout so each flow is laid out as an ordinary chain first and
    # then re-parented, rather than teaching the grid about nested coordinates.
    for block in parallel_blocks:
        parts = load_parallel_parts()
        if not parts:
            warnings.append("parallel: gow.json has no captured parallelFlow container; "
                            "flows are wired in the activities but not drawn")
            continue
        by_id = {e["id"]: e for e in elements if "source" not in e}
        owner_id = block["owner"]["node"]["new_id"]
        cont = copy.deepcopy(parts["container"])
        cont_id = str(uuid.uuid4())
        cont["id"] = cont_id
        cont["data"] = dict(cont.get("data") or {})
        cont["data"]["ports"] = [{"id": f"input-{cont_id}"},
                                 {"id": f"parallel-flow-output-{cont_id}"}]
        # Collect each flow's elements: its head plus everything downstream of it
        # that layout put on the same row.
        flow_members: list[list[dict]] = []
        for flow in block["flows"]:
            head_el = by_id.get(flow["head"])
            row = next((e["row"] for e in placed
                        if e["node"]["new_id"] == flow["head"]), None)
            members = [by_id[e["node"]["new_id"]] for e in placed
                       if e["row"] == row and e["node"]["new_id"] in by_id] if row is not None else []
            if head_el and head_el not in members:
                members.insert(0, head_el)
            flow_members.append(members)

        col_step, header_y, content_y = parts["col_step"], parts["header_y"], parts["content_y"]
        base_x, base_y = 120, 300 + 260 * (max(
            (e["row"] for e in placed), default=0) + 1)
        cont["position"] = {"x": base_x, "y": base_y}
        cont["positionAbsolute"] = dict(cont["position"])
        cont["width"] = cont["data"]["width"] = max(col_step * len(block["flows"]) + 120, 600)
        cont["height"] = cont["data"]["height"] = 602
        cont["style"] = {"width": f"{cont['width']}px", "cursor": "pointer",
                         "height": f"{cont['height']}px"}
        elements.append(cont)

        for fi, (flow, members) in enumerate(zip(block["flows"], flow_members)):
            fx = 96 + fi * col_step
            # flowEntry header — its id IS the flowId the split refers to.
            fe = copy.deepcopy(parts["flow_entry"])
            fe["id"] = flow["flow_id"]
            fe["data"] = dict(fe.get("data") or {})
            fe["data"]["order"] = fi + 1
            fe["data"]["ports"] = [{"id": f"flow-entry-output-{flow['flow_id']}"}]
            fe["data"]["parentNode"] = owner_id
            fe["parentNode"] = cont_id
            fe["extent"] = "parent"
            fe["position"] = {"x": fx, "y": header_y}
            fe["positionAbsolute"] = {"x": base_x + fx, "y": base_y + header_y}
            elements.append(fe)
            # re-parent the flow's own nodes into the container
            for mi, el in enumerate(members):
                el["parentNode"] = cont_id
                el["extent"] = "parent"
                el["position"] = {"x": fx, "y": content_y + mi * 120}
                el["positionAbsolute"] = {"x": base_x + el["position"]["x"],
                                          "y": base_y + el["position"]["y"]}
            if members:
                # flowEntry -> the flow's first node, off the header's own port
                elements.append(port_edge(
                    flow["flow_id"], members[0]["id"],
                    f"flow-entry-output-{flow['flow_id']}", "flowEntry"))
        # owner -> container (the event's handle into the container's input),
        # then container -> whatever follows the whole block.
        elements.append(port_edge(
            owner_id, cont_id, f"{block['event']}-{owner_id}",
            names_raw(block["owner"]["kind"]), event_name=block["event"]))
        elements.append(port_edge(
            cont_id, block["after"], f"parallel-flow-output-{cont_id}", "parallelFlow"))

    all_nodes = [src] + [e["node"] for e in placed]
    acfg = {n["new_id"]: n["config"] for n in all_nodes if n.get("config")}
    pcfg = {n["new_id"]: n["paths"] for n in all_nodes if n.get("paths")}

    # ── assemble the body ──
    body = copy.deepcopy(lib["skeleton"])
    body["activities"] = [n["activity"] for n in all_nodes] + ends
    kinds = [e["kind"] for e in placed]
    raw = body["rawJourneyData"]
    raw["elements"] = elements
    raw["activitiesConfiguration"] = acfg
    raw["pathesConfiguration"] = pcfg
    raw["boundaryConfiguration"] = {}
    raw["exitCriteriaSettings"] = None

    # name — top-level, infoValues, AND every notification's
    # objectForSend.metadata.journeyName (the documented three places)
    name = spec.get("name") or f"JBCL | composed | {' -> '.join(kinds)}"
    body["journeyName"] = name
    raw["infoValues"]["journeyName"] = name
    for d in _walk_dicts(body):
        md = d.get("metadata")
        if isinstance(md, dict) and "journeyName" in md:
            md["journeyName"] = name

    # dates — byte-identical behavior to the proven set_dates() /
    # set_immediately_after_publish(): top-level in .NET ".0000000Z" form,
    # infoValues in plain "Z" form, and startAt is NULL when immediate.
    date = spec.get("date")
    days = int(spec.get("days", 1))
    immediately = bool(spec.get("immediately", True))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if date:
        y, m, d = (int(x) for x in date.split("-"))
        start = datetime(y, m, d, 4, 0, tzinfo=timezone.utc)      # Chile midnight
        stop = start + timedelta(days=days)
    else:
        start = now
        stop = now + timedelta(days=days)
    dotnet = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    plain = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    info = raw["infoValues"]
    body["stopAt"] = dotnet(stop)
    info["stopAt"] = plain(stop)
    body["timeZoneId"] = info["timeZoneId"] = "Chile/Continental"
    body["isImmediatelyAfterPublish"] = info["isImmediatelyAfterPublish"] = immediately
    if immediately:
        body["startAt"] = info["startAt"] = None    # captured immediate-publish state
    else:
        body["startAt"] = dotnet(start)
        info["startAt"] = plain(start)
    # free-spin validity window: starts with the campaign, claimable for a week
    for a in body["activities"]:
        fa = (a.get("initializationData") or {}).get("freespinActivity")
        if isinstance(fa, dict):
            fa["startAt"] = plain(start)
            fa["stopAt"] = plain(start + timedelta(days=7))

    # placeholder matching the proven console-script swap; lineage stripped
    body["reservedJourneyId"] = "DRY-RUN-CASINO"
    for k in ("duplicatedFromId", "duplicatedFromVersion"):
        body.pop(k, None)

    _strip_key_everywhere(body, "promotionDisplayId")

    return {"body": body, "report": report, "warnings": warnings,
            "chain": [src_kind] + kinds, "name": name}


def _walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


def _strip_key_everywhere(obj, key: str) -> int:
    n = 0
    if isinstance(obj, dict):
        if key in obj:
            obj.pop(key); n += 1
        for v in obj.values():
            n += _strip_key_everywhere(v, key)
    elif isinstance(obj, list):
        for v in obj:
            n += _strip_key_everywhere(v, key)
    return n


# ── verification (the composer's own gatekeeper) ─────────────────────────────
def verify(body: dict) -> list[str]:
    errs: list[str] = []
    acts = body["activities"]
    ids = [a["activityId"] for a in acts]
    if len(ids) != len(set(ids)):
        errs.append("duplicate activityIds")
    idset = set(ids)
    for a in acts:
        for ev in a.get("events", []):
            nid = ev.get("nextActivityId")
            if nid and nid not in idset:
                errs.append(f"{a['activityName']}.{ev.get('eventName')} -> dangling nextActivityId")
        for dl in ("dependencies", "dataDependencies"):
            for d in a.get(dl) or []:
                if isinstance(d, dict) and d.get("journeyActivityId") and d["journeyActivityId"] not in idset:
                    errs.append(f"{a['activityName']} {dl} {d.get('key')} -> dangling journeyActivityId")
    raw = body["rawJourneyData"]
    el_ids = {e["id"] for e in raw["elements"] if "source" not in e}
    for e in raw["elements"]:
        if "source" in e:
            if e["source"] not in el_ids or e["target"] not in el_ids:
                errs.append(f"edge {e.get('data', {}).get('eventName')} references undrawn node")
    for k in raw.get("activitiesConfiguration", {}):
        if k not in idset:
            errs.append("activitiesConfiguration key not an activity id")
    if not body.get("journeyName"):
        errs.append("journeyName missing")
    if body.get("duplicatedFromId"):
        errs.append("lineage not stripped")
    if _count_key(body, "promotionDisplayId"):
        errs.append("promotionDisplayId not stripped")
    return errs


def _count_key(obj, key: str) -> int:
    if isinstance(obj, dict):
        return (key in obj) + sum(_count_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_key(v, key) for v in obj)
    return 0


def captured_connections() -> list[dict]:
    """Every (from, event, to) connection actually captured — the AI's full
    connection grammar, straight from the templates (like build_catalog)."""
    conns: list[dict] = []
    seen: set = set()
    for path in SOURCES:
        body = json.loads(path.read_text(encoding="utf-8-sig"))
        by_id = {a["activityId"]: a for a in body["activities"]}
        for a in body["activities"]:
            for ev in a.get("events", []):
                nxt = by_id.get(ev.get("nextActivityId"))
                if nxt is None:
                    continue
                sig = (_akey(a), ev.get("eventName"), _akey(nxt))
                if sig in seen:
                    continue
                seen.add(sig)
                conns.append({"from": sig[0], "event": sig[1], "to": sig[2],
                              "event_type": ev.get("eventType"), "captured_in": path.name})
    return sorted(conns, key=lambda c: (c["from"], c["event"] or "", c["to"]))


# ── CLI ──────────────────────────────────────────────────────────────────────
def options() -> dict:
    """The composable palette as data: sources, activities, their captured
    events and settings, the games registry and the spec shape.

    Split out of cmd_options so it can be imported — compose.py's catalog()
    publishes a compacted form into the planner prompt, which is what lets the
    planner emit chain specs instead of only the four fixed recipes."""
    lib = load_library()
    have = sorted(k for k in lib["types"] if k not in ("end_of_journey", "end_of_path"))

    def events_of(k: str) -> dict:
        evs = lib["types"][k]["activity"].get("events", [])
        return {"completion": sorted(e["eventName"] for e in evs if e.get("eventType") == "Completion"),
                "boundary": sorted(e["eventName"] for e in evs if e.get("eventType") == "Boundary"),
                "activation": sorted(e["eventName"] for e in evs if e.get("eventType") == "Activation")}

    return {
        "sources": {"csv/segment": "dwh_source (segment/CSV-seeded audience)",
                    "api": "external_system_source (API entry) — use this for a "
                           "journey a randomizer routes winners into",
                    "promocode": "registration (Reference codes entry; takes "
                                 "`promocode`)"},
        "chain_types": {k: {"aliases": sorted(a for a, v in ALIASES.items() if v == k),
                            "default_follow": HAPPY.get(k),
                            "events": events_of(k),
                            "settings": SETTINGS_DOC.get(k, {}),
                            "captured_in": lib["types"][k]["template"]}
                        for k in have if k not in SOURCE_TYPES},
        "captured_connections": captured_connections(),
        # The full registry, so a caller (or an LLM) can resolve a brief's game
        # name without guessing. Keyed by lobbyGameId -> display name.
        "games": {e["lobbyGameId"]: e.get("gameTranslationKey") or e["lobbyGameId"]
                  for e in _game_index().values()},
        "spec_shape": {"name": "str", "source": {"type": "segment|csv|api", "...settings": "?"},
                       "chain": [{"type": "<chain type>", "...settings": "?",
                                  "follow": "optional Completion event that continues the chain (default: default_follow)",
                                  "branches": {"<Completion event>": ["... nested chain nodes ..."]}}],
                       "date": "YYYY-MM-DD (stop anchor)", "days": "int (default 1)",
                       "immediately": "bool (default true)"},
    }


def cmd_options(as_json: bool) -> int:
    out = options()
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for k, v in out["chain_types"].items():
            print(f"{k}: follow={v['default_follow']} settings={list(v['settings'])}")
        print(f"\ncaptured connections: {len(out['captured_connections'])}")
    return 0


def cmd_describe(spec: dict) -> int:
    src = ALIASES.get(str((spec.get("source") or {}).get("type", "")).lower(), "?")
    parts = [f"{src.upper()}"]
    for c in spec.get("chain", []):
        k = ALIASES.get(str(c.get("type", "")).lower(), f"?{c.get('type')}")
        s = {a: b for a, b in c.items() if a != "type"}
        parts.append(f"{k.upper()}({', '.join(f'{a}={b}' for a, b in s.items())})" if s else k.upper())
    parts.append("END")
    print("You want this journey?\n\n  " + "  ->  ".join(parts))
    print(f"\n  name : {spec.get('name') or '(auto)'}")
    print(f"  when : stop {spec.get('date') or '(now+days)'} +{spec.get('days', 1)}d, "
          f"start {'immediately' if spec.get('immediately', True) else 'on date'}")
    return 0


def emit_console_script(body: dict, out_path: Path) -> str:
    """Render the paste-ready browser console script using the PROVEN scaffold
    from casino_journey.py (token auto-capture -> reserve JRN id -> regenerate
    activity uuids at paste time -> POST /journey-drafts -> aggregatedError log).
    """
    from casino_journey import build_js  # the battle-tested JS template
    # body already carries the DRY-RUN-CASINO placeholder the script swaps
    js = build_js(body)
    out_path.write_text(js, encoding="utf-8")
    return str(out_path)


def _inherited_content_errors(body: dict) -> list[str]:
    """Campaign content this chain still shares with the templates it was cloned
    from. A chain picks its own activities, but a communication node is copied
    whole — so an SMS node the spec gave no text to still carries the captured
    campaign's message, links and email template."""
    try:
        from compose import audit_inherited_content
    except Exception:
        return []
    leaks: dict[str, None] = {}
    for path in SOURCES:
        try:
            ref = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        for line in audit_inherited_content(body, ref):
            leaks.setdefault(line, None)
    return list(leaks)


def cmd_compose(spec: dict, as_json: bool, script: bool, basename: str | None = None) -> int:
    res = compose(spec)
    errs = verify(res["body"])
    # Treat leaked campaign content as a verification failure: a journey that
    # messages players with another campaign's copy is not a usable draft, and
    # "VERIFIED OK" on one is exactly how the wrong SMS reached a real draft.
    errs = errs + [f"inherited content — {line}" for line in _inherited_content_errors(res["body"])]
    OUT.mkdir(exist_ok=True)
    slug = re.sub(r"[^\w]+", "_", res["name"].lower()).strip("_")[:60]
    out_path = OUT / f"{slug}.journey.json"
    out_path.write_text(json.dumps(res["body"], ensure_ascii=False, indent=2), encoding="utf-8")

    js_path = None
    if script and not errs:
        if basename:
            # Called by the backoffice runner, which reads back exactly
            # console_scripts/<basename>_console.js — same convention as every
            # other generator. Bare CLI runs keep the name-derived out/ path.
            CONSOLE_OUT.mkdir(parents=True, exist_ok=True)
            js_path = emit_console_script(res["body"], CONSOLE_OUT / f"{basename}_console.js")
        else:
            js_path = emit_console_script(res["body"], OUT / f"{slug}.console.js")

    summary = {
        "ok": not errs,
        "output": str(out_path),
        "console_script": js_path,
        "chain": res["chain"],
        "activities": len(res["body"]["activities"]),
        "elements": len(res["body"]["rawJourneyData"]["elements"]),
        "settings_applied": res["report"],
        "warnings": res["warnings"],
        "verify_errors": errs,
        "handoff": ("Paste the console script into a logged-in backoffice DevTools console to "
                    "create the draft (it reserves the JRN id and POSTs)."
                    if js_path else
                    "reservedJourneyId carries the DRY-RUN-CASINO placeholder: re-run with "
                    "--script for a paste-ready console script that swaps in a real JRN id. "
                    "This tool never calls the API."),
    }
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"chain    : {' -> '.join(res['chain'])} -> end")
        print(f"output   : {out_path}")
        if js_path:
            print(f"script   : {js_path}")
        print(f"activities {summary['activities']}, elements {summary['elements']}")
        for line in res["report"]:
            print(f"  set   {line}")
        for w in res["warnings"]:
            print(f"  WARN  {w}")
        for e in errs:
            print(f"  ERROR {e}")
        print("VERIFIED OK" if not errs else "VERIFY FAILED")
    return 0 if not errs else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)
    po = sub.add_parser("options"); po.add_argument("--json", action="store_true")
    pd = sub.add_parser("describe"); pd.add_argument("spec")
    pc = sub.add_parser("compose"); pc.add_argument("spec"); pc.add_argument("--json", action="store_true")
    pc.add_argument("--script", action="store_true",
                    help="also emit the paste-ready browser console script (reserve id -> POST)")
    pc.add_argument("--name", default=None,
                    help="emit console_scripts/<name>_console.js instead of a "
                         "name-derived path under out/ (used by the backoffice runner)")
    a = p.parse_args()
    if a.mode == "options":
        return cmd_options(a.json)
    raw = sys.stdin.read() if a.spec == "-" else Path(a.spec).read_text(encoding="utf-8")
    # Tolerate a planner reply verbatim: ```json fences and prose lead-ins are
    # what the model actually emits, and a bare json.loads turns that into a
    # traceback instead of a usable message.
    from compose import _extract_json, SpecError
    try:
        spec = _extract_json(raw)
    except SpecError as exc:
        raise SystemExit(f"⛔ REFUSED — {exc}")
    if a.mode == "describe":
        return cmd_describe(spec)
    return cmd_compose(spec, a.json, a.script, a.name)


if __name__ == "__main__":
    raise SystemExit(main())
