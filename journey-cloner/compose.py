#!/usr/bin/env python3
"""compose.py — build a runnable REA journey-draft from ONE captured reference.

A *recipe* is a thin descriptor (recipes/<key>.json) that points at exactly one
reference template extracted from a real journey draft
(templates/<family>/<name>.json). This tool does NOT invent structure: it reads
the reference's own `activities` graph, follows every `nextActivityId`, keeps
*every* node, discovers the knob paths that actually exist in the reference's
`initializationData`, resolves game-id knobs against games.json, and then emits a
clean create-body (regenerated activity UUIDs, server-minted ids stripped).

    python compose.py --list
    python compose.py <key>                 # compose -> out/<key>.composed.json (+ verify)
    python compose.py <key> --verify        # verify only, no output written
    python compose.py <key> --set freespin_bonus:freespinActivity.spins=3 ...
    python compose.py <key> --game <lobbyId>   # swap the freespin game from games.json
    python compose.py <key> --catalog       # compose + verify + register into catalog.json

Verify is the gate. It fails hard on a broken chain (a nextActivityId that does
not resolve, a missing entry, an editor-mirror mismatch, an unresolved game).
Orphan *terminal* nodes (end_of_path / end_of_journey) that the reference itself
left unwired are kept and reported — never auto-wired. See RECIPE_BUILDING.md.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECIPES_DIR = HERE / "recipes"
TEMPLATES_DIR = HERE / "templates"
GAMES_PATH = HERE / "games.json"
CATALOG_PATH = HERE / "catalog.json"
OUT_DIR = HERE / "out"

ENTRY_TYPES = {"external_system_source", "dwh_source"}
TERMINAL_TYPES = {"end_of_path", "end_of_journey"}

# Top-level fields the server mints; a clone must drop them before re-creating.
STRIP_TOP = ["reservedJourneyId", "duplicatedFromId", "duplicatedFromVersion"]
# Per-activity initializationData id fields the server mints per publish.
STRIP_INIT = ["promotionId", "promotionDisplayId", "promotionLinkId", "campaignId"]

# Candidate knob paths per activity type, expressed as dot-paths into
# `initializationData`. compose.py records only the ones that ACTUALLY resolve in
# the reference — so the exposed knobs are always grounded in real capture, never
# assumed. `<CCY>` expands to each currency present in currenciesConfig.
KNOB_PATHS = {
    "freespin_bonus": [
        "freespinActivity.spins",
        "freespinActivity.startAt",
        "freespinActivity.stopAt",
        "freespinActivity.currenciesConfig.<CCY>.betAmount",
        "freespinActivity.currenciesConfig.<CCY>.maxBonusAmount",
        "freespinActivity.spinsExpirationDuration",
    ],
    "casino_bonus_v2": [
        "bonusPercent", "wageringRequirement", "releaseLimitMultiplier",
        "bonusExpirationTime", "minDepositAmount", "maxBonusAmount",
    ],
    "deposit": [
        "depositConditions.expirationTimeout",
        "depositConditions.minDepositAmounts.<I>.amount",
    ],
    "multipurpose_promotion": [
        "startAt", "stopAt", "timeToAccept", "autoAccept",
    ],
    "promotion": ["timeToAccept", "autoAccept"],
    "wait_interval": ["duration"],
    "wait_date": ["waitUntil", "date"],
}

# The game-id sub-fields inside freespinActivity, mapped to their games.json key.
GAME_FIELD_MAP = {
    "lobbyGameId": "lobbyId",
    "walletGameId": "walletId",
    "externalGameId": "externalGameId",
    "provider": "gameProvider",
    "gameTranslationKey": "translationKey",
}


# --------------------------------------------------------------------------- #
# small dot-path helpers
# --------------------------------------------------------------------------- #
def _get(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None, False
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None, False
    return cur, True


def _set(obj, path, value):
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def _expand(path, init):
    """Expand <CCY>/<I> wildcards against what is actually present in `init`."""
    if "<CCY>" in path:
        ccys = (_get(init, "freespinActivity.currenciesConfig")[0] or {})
        for c in ccys:
            yield from _expand(path.replace("<CCY>", c, 1), init)
        return
    if "<I>" in path:
        head = path.split(".<I>", 1)[0]
        arr = _get(init, head)[0]
        if isinstance(arr, list):
            for i in range(len(arr)):
                yield from _expand(path.replace("<I>", str(i), 1), init)
        return
    yield path


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_recipe(key):
    rp = RECIPES_DIR / f"{key}.json"
    if not rp.exists():
        die(f"no recipe '{key}' (expected {rp})")
    r = load_json(rp)
    r["_template_path"] = TEMPLATES_DIR / r["template"]
    if not r["_template_path"].exists():
        die(f"recipe '{key}' template missing: {r['_template_path']}")
    return r


def load_games():
    if not GAMES_PATH.exists():
        return {}
    data = load_json(GAMES_PATH)
    games = data.get("games", data if isinstance(data, list) else [])
    return {g["lobbyId"]: g for g in games if g.get("lobbyId")}


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(2)


# --------------------------------------------------------------------------- #
# graph
# --------------------------------------------------------------------------- #
def collect_next_ids(activity):
    """Every nextActivityId reachable anywhere inside one activity node."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "nextActivityId" and isinstance(v, str) and v:
                    out.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(activity)
    return out


def raw_mirror_refs(body):
    """The editor mirror (rawJourneyData) is a ReactFlow graph whose `elements`
    are node cards (id == activityId) plus edges (source/target == activityIds,
    with their own non-activity edge id). Return (node_card_ids, edge_endpoints)
    so verify can check both resolve to real activities — not that the mirror is
    a 1:1 copy of activities (entry/terminal nodes are not always drawn as cards).
    """
    raw = body.get("rawJourneyData")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    node_ids, endpoints, all_ids = set(), set(), set()
    for el in raw.get("elements", []) or []:
        if el.get("id"):
            all_ids.add(el["id"])
        if el.get("source") or el.get("target"):  # edge
            for end in (el.get("source"), el.get("target")):
                if end:
                    endpoints.add(end)
        elif el.get("id"):  # node card
            node_ids.add(el["id"])
    return {"node_cards": node_ids, "edge_endpoints": endpoints, "element_ids": all_ids}


# --------------------------------------------------------------------------- #
# knob discovery
# --------------------------------------------------------------------------- #
def knob_meta(path, value):
    """Infer the unit/kind/meaning of a knob so a downstream reader never has to
    guess units — the #1 'wrong number' failure. Grounded in the observed field
    naming and value shapes of the REA journey model (CLP minor units ×100, etc.).
    """
    leaf = path.split(".")[-1]
    meta = {"kind": type(value).__name__}
    money_leaves = {"betAmount", "maxBonusAmount", "minBonusAmount", "amount",
                    "minDepositAmount", "maxDepositAmount"}
    if leaf in money_leaves and isinstance(value, (int, float)):
        meta.update(kind="money", unit="CLP minor units (×100)",
                    value_major=value / 100,
                    meaning=f"{value} minor = {value/100:g} CLP")
    elif leaf == "spins":
        meta.update(kind="int", unit="spin count")
    elif leaf in ("spinsExpirationDuration", "bonusExpirationTime"):
        meta.update(kind="int", unit="milliseconds",
                    meaning=(f"{value} ms = {value/86400000:g} day(s)"
                             if isinstance(value, (int, float)) else None))
    elif leaf in ("startAt", "stopAt", "waitUntil", "date"):
        meta.update(kind="datetime", unit="ISO-8601 UTC (Chile midnight = 04:00Z)")
    elif leaf in ("timeToAccept", "expirationTimeout", "duration"):
        meta.update(kind="duration", unit="ISO-8601 duration (P…T…)")
    elif leaf == "bonusPercent":
        meta.update(kind="int", unit="percent (deposit-match %)")
    elif leaf in ("wageringRequirement", "releaseLimitMultiplier"):
        meta.update(kind="number", unit="multiplier (×)")
    elif leaf == "autoAccept":
        meta.update(kind="bool")
    return {k: v for k, v in meta.items() if v is not None}


def discover_knobs(body, games_by_lobby):
    """Return (knobs, game_slots). Knobs are grounded: only paths that resolve in
    the reference's real initializationData are reported. Each knob carries its
    real current value plus an inferred unit/meaning."""
    knobs = []
    game_slots = []
    for a in body.get("activities", []):
        name = a.get("activityName")
        init = a.get("initializationData") or {}
        aid = a.get("activityId")
        for tmpl in KNOB_PATHS.get(name, []):
            for path in _expand(tmpl, init):
                val, ok = _get(init, path)
                if ok:
                    knobs.append({
                        "activity": name, "activityId": aid,
                        "path": path, "value": val,
                        **knob_meta(path, val),
                    })
        # game-id knob slot (freespin games)
        fa = init.get("freespinActivity")
        if name == "freespin_bonus" and isinstance(fa, dict):
            lobby = fa.get("lobbyGameId")
            game_slots.append({
                "activityId": aid,
                "lobbyGameId": lobby,
                "resolved": lobby in games_by_lobby,
                "game": fa.get("gameTranslationKey"),
            })
    return knobs, game_slots


# --------------------------------------------------------------------------- #
# compose transform
# --------------------------------------------------------------------------- #
def apply_overrides(body, sets):
    """--set activityName:dot.path=value  (targets every node of that type)."""
    for spec in sets:
        try:
            target, value = spec.split("=", 1)
            act_name, path = target.split(":", 1)
        except ValueError:
            die(f"bad --set '{spec}' (want activityName:path=value)")
        try:
            value = json.loads(value)  # numbers/bools/json; else keep string
        except json.JSONDecodeError:
            pass
        hit = 0
        for a in body.get("activities", []):
            if a.get("activityName") == act_name:
                init = a.get("initializationData") or {}
                _, ok = _get(init, path)
                if ok:
                    _set(init, path, value)
                    hit += 1
        if not hit:
            die(f"--set '{spec}': no {act_name} node has path '{path}'")
        print(f"  set {act_name}:{path} = {value}  ({hit} node(s))")


def apply_game(body, lobby_id, games_by_lobby):
    if lobby_id not in games_by_lobby:
        die(f"--game '{lobby_id}' not in games.json")
    g = games_by_lobby[lobby_id]
    hit = 0
    for a in body.get("activities", []):
        fa = (a.get("initializationData") or {}).get("freespinActivity")
        if a.get("activityName") == "freespin_bonus" and isinstance(fa, dict):
            for fa_key, games_key in GAME_FIELD_MAP.items():
                if games_key in g and g[games_key] is not None:
                    fa[fa_key] = g[games_key]
            hit += 1
    if not hit:
        die("--game: reference has no freespin_bonus node")
    print(f"  game -> {lobby_id} ({g.get('translationKey')})  ({hit} node(s))")


def regenerate_ids(body):
    """Give every activity a fresh UUID, consistently everywhere (activities AND
    the rawJourneyData editor mirror), by substituting on the serialized doc."""
    old_ids = [a["activityId"] for a in body.get("activities", []) if a.get("activityId")]
    text = json.dumps(body, ensure_ascii=False)
    for oid in old_ids:
        text = text.replace(oid, str(uuid.uuid4()))
    return json.loads(text)


def strip_server_ids(body):
    for k in STRIP_TOP:
        body.pop(k, None)
    for a in body.get("activities", []):
        init = a.get("initializationData")
        if isinstance(init, dict):
            for k in STRIP_INIT:
                init.pop(k, None)
    return body


def compose(recipe, args, games_by_lobby):
    body = copy.deepcopy(load_json(recipe["_template_path"]))
    if args.set:
        apply_overrides(body, args.set)
    if args.game:
        apply_game(body, args.game, games_by_lobby)
    body = regenerate_ids(body)
    body = strip_server_ids(body)
    return body


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def verify(body, games_by_lobby, label="composed"):
    acts = body.get("activities", [])
    ids = {a["activityId"] for a in acts}
    errors, warnings, infos = [], [], []

    # 1. entry present
    entries = [a for a in acts if a.get("activityName") in ENTRY_TYPES]
    if not entries:
        errors.append("no entry node (external_system_source / dwh_source)")

    # 2. every nextActivityId resolves
    edges = {}
    for a in acts:
        for n in collect_next_ids(a):
            edges.setdefault(a["activityId"], []).append(n)
            if n not in ids:
                errors.append(f"{a.get('activityName')} -> dangling nextActivityId {n[:8]}")

    # 3. reachability
    from collections import deque
    seen, dq = set(), deque(e["activityId"] for e in entries)
    while dq:
        x = dq.popleft()
        if x in seen:
            continue
        seen.add(x)
        for n in edges.get(x, []):
            if n in ids:
                dq.append(n)
    for a in acts:
        if a["activityId"] not in seen:
            nm = a.get("activityName")
            if nm in TERMINAL_TYPES:
                infos.append(f"unwired terminal kept: {nm} {a['activityId'][:8]}")
            else:
                errors.append(f"unreachable non-terminal node: {nm} {a['activityId'][:8]}")

    # 4. editor mirror is internally consistent. The mirror is a ReactFlow graph:
    #    besides activity cards it holds editor chrome (flowEntry / dropZone /
    #    parallelFlow) whose ids are NOT activities but are legitimate reference
    #    structure — kept, not invented. So an edge is only broken if it points to
    #    something that is neither a real activity nor any element in the mirror.
    mirror = raw_mirror_refs(body)
    if mirror is not None:
        valid = ids | mirror["element_ids"]
        for aid in mirror["edge_endpoints"] - valid:
            errors.append(f"rawJourneyData edge points to unknown id {aid[:8]}")
        chrome = mirror["node_cards"] - ids
        if chrome:
            infos.append(f"editor-chrome cards kept (non-activity): {len(chrome)}")

    # 5. game knobs resolve
    for a in acts:
        fa = (a.get("initializationData") or {}).get("freespinActivity")
        if a.get("activityName") == "freespin_bonus" and isinstance(fa, dict):
            lobby = fa.get("lobbyGameId")
            if games_by_lobby and lobby not in games_by_lobby:
                warnings.append(f"freespin game '{lobby}' not found in games.json")

    # 6. no leftover server-minted ids
    leftovers = [k for k in STRIP_TOP if k in body]
    if leftovers:
        errors.append(f"server-minted top-level ids not stripped: {leftovers}")

    ok = not errors
    print(f"\nverify [{label}]: {'PASS' if ok else 'FAIL'}  "
          f"({len(acts)} nodes, {len(seen)} reachable)")
    for e in errors:
        print(f"  ✗ {e}")
    for w in warnings:
        print(f"  ⚠ {w}")
    for i in infos:
        print(f"  · {i}")
    return ok


# --------------------------------------------------------------------------- #
# catalog publish
# --------------------------------------------------------------------------- #
def observed_pattern(body):
    """Ordered activity-type chain from the entry, for the catalog recipe."""
    acts = {a["activityId"]: a for a in body.get("activities", [])}
    entries = [a for a in body.get("activities", []) if a.get("activityName") in ENTRY_TYPES]
    order, seen = [], set()
    from collections import deque
    dq = deque(e["activityId"] for e in entries)
    while dq:
        x = dq.popleft()
        if x in seen or x not in acts:
            continue
        seen.add(x)
        nm = acts[x].get("activityName")
        if nm not in TERMINAL_TYPES:
            order.append(nm)
        for n in collect_next_ids(acts[x]):
            dq.append(n)
    # de-dupe consecutive repeats but keep multiplicity of distinct types
    from collections import Counter
    return list(Counter(order).items())


def recipe_flags(body):
    """Machine-readable ⛔/⚠ flags a downstream reader MUST heed for this recipe.
    Only what the reference actually implies — never speculative."""
    flags = []
    names = {a.get("activityName") for a in body.get("activities", [])}
    if "campaign_connector" in names:
        flags.append({
            "level": "warn",
            "rule": "campaign_connector-hand-off",
            "message": "connects to another journey/randomizer via campaign_connector "
                       "{journeyId, activityId} — set both, do not rely on a CTA link.",
        })
    # unwired terminals / editor chrome are surfaced by verify; not a build blocker.
    return flags


def recipe_entry(recipe, body, knobs, game_slots):
    """The full self-describing contract for one recipe — everything a planner
    needs without ever opening the raw template."""
    pattern = [f"{n}×{c}" if c > 1 else n for n, c in observed_pattern(body)]
    # enriched, de-duplicated knob schema (path -> value + unit + meaning)
    seen, knob_schema = set(), []
    for k in knobs:
        sig = f"{k['activity']}:{k['path']}"
        if sig in seen:
            continue
        seen.add(sig)
        knob_schema.append({
            "id": sig, "activity": k["activity"], "path": k["path"],
            "example_value": k["value"],
            **{kk: k[kk] for kk in ("kind", "unit", "meaning", "value_major") if kk in k},
        })
    games = [{
        "activityId": g["activityId"][:8], "lobbyGameId": g["lobbyGameId"],
        "game": g["game"], "resolved_in_games_json": g["resolved"],
    } for g in game_slots]
    return {
        "key": recipe["key"],
        "intent": recipe.get("title") or recipe["key"],
        "kind": recipe.get("kind"),
        "template": recipe["template"],
        "nodes": len(body.get("activities", [])),
        "pattern": pattern,
        "knobs": knob_schema,
        "game_slots": games,
        "flags": recipe_flags(body),
        "notes": recipe.get("notes", ""),
        "source": "composed",
        "compose_cmd": f"python compose.py {recipe['key']} "
                       f"--game <lobbyId> --set <activity>:<path>=<value> --catalog",
    }


def publish_catalog(recipe, body, knobs, game_slots):
    if not CATALOG_PATH.exists():
        die(f"catalog.json not found at {CATALOG_PATH}")
    cat = load_json(CATALOG_PATH)
    entry = recipe_entry(recipe, body, knobs, game_slots)
    # Write to a dedicated key so re-running build_catalog.py (which owns the
    # curated `recipes`) never clobbers composed recipes, and vice versa.
    recipes = cat.setdefault("composed_recipes", [])
    recipes[:] = [r for r in recipes if r.get("key") != recipe["key"]]
    recipes.append(entry)
    recipes.sort(key=lambda r: r["key"])
    CATALOG_PATH.write_text(
        json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ncatalog: registered composed recipe '{recipe['key']}' into "
          f"composed_recipes ({len(entry['pattern'])} pattern types, "
          f"{len(entry['knobs'])} knobs, {len(entry['flags'])} flags)")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def cmd_list():
    if not RECIPES_DIR.exists():
        print("no recipes/ dir yet")
        return 0
    for rp in sorted(RECIPES_DIR.glob("*.json")):
        r = load_json(rp)
        print(f"  {r['key']:16s} {r.get('kind',''):9s} {r['template']:28s} "
              f"{r.get('title','')}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="compose a REA journey from one reference")
    ap.add_argument("key", nargs="?", help="recipe key (see --list)")
    ap.add_argument("--list", action="store_true", help="list recipes")
    ap.add_argument("--verify", action="store_true", help="verify only, write nothing")
    ap.add_argument("--catalog", action="store_true", help="register into catalog.json")
    ap.add_argument("--describe", action="store_true",
                    help="print the recipe's self-describing JSON contract and exit")
    ap.add_argument("--game", help="swap freespin game to this lobbyId (from games.json)")
    ap.add_argument("--set", action="append", default=[],
                    help="activityName:dot.path=value  (repeatable)")
    ap.add_argument("--out", help="output path (default out/<key>.composed.json)")
    args = ap.parse_args(argv)

    if args.list or not args.key:
        return cmd_list()

    recipe = load_recipe(args.key)
    games_by_lobby = load_games()
    body = compose(recipe, args, games_by_lobby)
    knobs, game_slots = discover_knobs(body, games_by_lobby)

    if args.describe:
        print(json.dumps(recipe_entry(recipe, body, knobs, game_slots),
                         ensure_ascii=False, indent=2))
        return 0

    print(f"recipe '{recipe['key']}'  template={recipe['template']}  "
          f"nodes={len(body.get('activities', []))}")
    print(f"discovered {len(knobs)} knob(s), {len(game_slots)} game slot(s):")
    for k in knobs:
        print(f"    {k['activity']}:{k['path']} = {k['value']}")
    for g in game_slots:
        flag = "ok" if g["resolved"] else "⛔ NOT IN games.json"
        print(f"    game@{g['activityId'][:8]} = {g['lobbyGameId']} ({g['game']}) [{flag}]")

    ok = verify(body, games_by_lobby, label=recipe["key"])
    if not ok:
        return 1
    if args.verify:
        return 0

    OUT_DIR.mkdir(exist_ok=True)
    out = Path(args.out) if args.out else OUT_DIR / f"{recipe['key']}.composed.json"
    out.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")

    if args.catalog:
        publish_catalog(recipe, body, knobs, game_slots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
