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

GOW = TPL / "gow.json"
COMMS = TPL / "gow_comms.json"
DEFAULT_SEGMENT = TPL / "segment_cs_301.json"

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
    "popup": "notification_center#contract5",
    "sms": "dextra_sms", "dextra_sms": "dextra_sms",
    "email": "dextra_email", "dextra_email": "dextra_email",
    "wait": "wait_interval", "wait_interval": "wait_interval",
    "event": "event_detector", "event_detector": "event_detector",
    "ncsplit": "notification_center_engagement_split",
    "notification_center_engagement_split": "notification_center_engagement_split",
    "emailsplit": "email_engagement_split", "email_engagement_split": "email_engagement_split",
    "decisionsplit": "ams_decision_split", "ams_decision_split": "ams_decision_split",
}
SOURCE_TYPES = {"dwh_source", "external_system_source"}

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
    "freespin_bonus": {"spins": "free-spin count", "game": f"one of {list(GAMES)}",
                       "bet_amount": "currenciesConfig.CLP.betAmount (minor units)"},
    "casino_bonus_v2": {"bonus_percent": "deposit-match %", "wagering": "wagering requirement (x)",
                        "release_multiplier": "releaseLimitMultiplier", "expiration_ms": "bonusExpirationTime in ms"},
    "notification_center#contract1": {"title_en/es, desc_en/es, caption_en/es": "on-site notification copy"},
    "notification_center#contract5": {"title_en/es, desc_en/es, caption_en/es": "pop-up (Cat-fish) copy"},
    "dextra_sms": {"text_en/es": "SMS body"},
    "dextra_email": {"(none)": "email references a content-studio CSE id; swap it after creating email content"},
    "wait_interval": {"wait": "ISO-8601 duration, e.g. P0Y0M0DT1H0M0S"},
    "event_detector": {"(none)": "captured deposit-band watcher kept as-is"},
    "multipurpose_promotion": {"(none)": "captured choosable-flow drip kept as-is (see warning on compose)"},
    "notification_center_engagement_split": {"(none)": "branch with follow/branches on NCEngagementSplitPassedPath01..05"},
    "email_engagement_split": {"(none)": "branch with follow/branches on Path1..Path6"},
    "ams_decision_split": {"(none)": "branch with follow/branches on DecisionSplitPassedPath01..20/RemainderPath"},
}
# keys valid on every chain node, besides type + per-type settings
UNIVERSAL_KEYS = {"type", "follow", "branches"}


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
    for path in (GOW, COMMS):
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
            g = GAMES.get(str(s["game"]))
            if not g:
                warnings.append(f"unknown game {s['game']!r}; known: {list(GAMES)} — kept template game")
            else:
                for k, v in g.items():
                    note(k, fa.get(k), v); fa[k] = v
        if "bet_amount" in s:
            cc = (fa.get("currenciesConfig") or {}).get("CLP") or {}
            note("betAmount", cc.get("betAmount"), s["bet_amount"]); cc["betAmount"] = s["bet_amount"]
            if "betAmount_majorUnits" in cc:      # proven pipeline keeps both in sync
                cc["betAmount_majorUnits"] = int(s["bet_amount"]) // 100
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
        keymap = {"title": "title", "desc": "des", "caption": "caption"}
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

    # unknown keys: loud, never silent
    known = {
        "deposit": {"min_deposit", "timeout"},
        "freespin_bonus": {"spins", "game", "bet_amount"},
        "casino_bonus_v2": {"bonus_percent", "wagering", "release_multiplier", "expiration_ms"},
        "notification_center#contract1": {f"{a}_{l}" for a in ("title", "desc", "caption") for l in ("en", "es")},
        "notification_center#contract5": {f"{a}_{l}" for a in ("title", "desc", "caption") for l in ("en", "es")},
        "dextra_sms": {"text_en", "text_es"},
        "wait_interval": {"wait"},
        "external_system_source": {"description"},
        "dwh_source": {"segment_file"},
    }.get(kind, set())
    for k in s:
        if k not in known and k not in UNIVERSAL_KEYS:
            warnings.append(f"{kind}: setting {k!r} is not supported (known: {sorted(known)})")


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
            for ev in node["activity"].get("events", []):
                if ev.get("eventType") != "Completion":
                    ev.pop("nextActivityId", None)      # boundary events carry no next
                    continue
                en = ev.get("eventName")
                if en == follow:
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

    act_ev = next((e["eventName"] for e in src["activity"].get("events", [])
                   if e.get("eventType") == "Activation"), "PlayerAdded")
    elements.append(make_edge(src["new_id"], src_kind, act_ev, head_id))
    for entry, ev_name, tgt in edges_wanted:
        elements.append(make_edge(entry["node"]["new_id"], entry["kind"], ev_name, tgt))

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
    for path in (GOW, COMMS):
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
def cmd_options(as_json: bool) -> int:
    lib = load_library()
    have = sorted(k for k in lib["types"] if k not in ("end_of_journey", "end_of_path"))

    def events_of(k: str) -> dict:
        evs = lib["types"][k]["activity"].get("events", [])
        return {"completion": sorted(e["eventName"] for e in evs if e.get("eventType") == "Completion"),
                "boundary": sorted(e["eventName"] for e in evs if e.get("eventType") == "Boundary"),
                "activation": sorted(e["eventName"] for e in evs if e.get("eventType") == "Activation")}

    out = {
        "sources": {"csv/segment": "dwh_source (segment/CSV-seeded audience)",
                    "api": "external_system_source (API entry)"},
        "chain_types": {k: {"aliases": sorted(a for a, v in ALIASES.items() if v == k),
                            "default_follow": HAPPY.get(k),
                            "events": events_of(k),
                            "settings": SETTINGS_DOC.get(k, {}),
                            "captured_in": lib["types"][k]["template"]}
                        for k in have if k not in SOURCE_TYPES},
        "captured_connections": captured_connections(),
        "games": {k: v["gameTranslationKey"] for k, v in GAMES.items()},
        "spec_shape": {"name": "str", "source": {"type": "segment|csv|api", "...settings": "?"},
                       "chain": [{"type": "<chain type>", "...settings": "?",
                                  "follow": "optional Completion event that continues the chain (default: default_follow)",
                                  "branches": {"<Completion event>": ["... nested chain nodes ..."]}}],
                       "date": "YYYY-MM-DD (stop anchor)", "days": "int (default 1)",
                       "immediately": "bool (default true)"},
    }
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


def cmd_compose(spec: dict, as_json: bool, script: bool) -> int:
    res = compose(spec)
    errs = verify(res["body"])
    OUT.mkdir(exist_ok=True)
    slug = re.sub(r"[^\w]+", "_", res["name"].lower()).strip("_")[:60]
    out_path = OUT / f"{slug}.journey.json"
    out_path.write_text(json.dumps(res["body"], ensure_ascii=False, indent=2), encoding="utf-8")

    js_path = None
    if script and not errs:
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
    a = p.parse_args()
    if a.mode == "options":
        return cmd_options(a.json)
    spec = json.loads(sys.stdin.read() if a.spec == "-" else Path(a.spec).read_text(encoding="utf-8"))
    if a.mode == "describe":
        return cmd_describe(spec)
    return cmd_compose(spec, a.json, a.script)


if __name__ == "__main__":
    raise SystemExit(main())
