#!/usr/bin/env python3
"""General journey COMPOSER — build a journey draft from a recipe + values.

Generalizes compose_comms.py. A recipe is an ordered chain of activities plus a
single REFERENCE journey (one that renders) to source every node/edge/config/
shell shape from — enforcing the "one node schema per recipe, no mixing" rule
from COMPOSER_RULES.md. The engine only rewires the chain, regenerates ids,
auto-lays-out, and re-emits both storage copies; it never invents structure.

Usage:
    python compose.py                     # list recipes
    python compose.py comms               # compose + emit console script
    python compose.py sport_deposit_freebet

Output: console_scripts/composed_<recipe>_console.js  (paste into a logged-in
backoffice tab; captures token, reserves JRN id, freshens ids, POSTs one draft).

Values (knobs) are an optional, generic override layer — see apply_values().
Full per-activity knob schemas come later (#3); today the reference journey's
real content is reused as-is and you can override any field by dotted path.
"""
from __future__ import annotations

import copy
import datetime
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
OUT = HERE / "console_scripts"
BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
DEFAULT_BRAND = "JBCL"
NODE_TYPES = ("source", "action", "exit", "flowEntry")


# ─────────────────────────── recipe model ───────────────────────────
@dataclass
class Node:
    activity: str                     # activityName, e.g. "deposit"
    primary: str                      # forward event to wire to the next node
    display: str | None = None        # optional activityDisplayName override


@dataclass
class Knob:
    """A named, LLM-facing value → a real dotted path on one activity. Paths vary
    per reference journey; a path that no longer resolves is a hard failure at
    compose time (see apply_values' MISS handling), never a silent no-op.

    `unit` describes the DESTINATION wire field, not the expected input — a spec
    always sends major CLP and the composer converts. `required=True` means a
    spec that omits the knob is refused rather than silently inheriting the
    reference template's own value (which is real production content)."""
    activity: str
    path: str
    unit: str = "raw"                 # raw | minor  (minor: major CLP × 100)
    desc: str = ""
    required: bool = False
    # Plausible range for the value AS SENT (major CLP for minor-unit knobs).
    # The unit contract is prose, and prose loses: a live planner reply asked for
    # "100 CLP per spin" and sent 10000 (minor), which the x100 conversion turned
    # into a 10,000 CLP spin. Bounds turn that class of error into a refusal.
    min_major: float | None = None
    max_major: float | None = None
    # Extra targets that must receive the SAME logical value, as
    # (activity, path) or (activity, path, unit). A platform value is often
    # duplicated across nodes — e.g. a promotion's promo-lobby card carries its
    # own copy of the freespin game/spins/bet. Setting only the reward node
    # ships a card advertising the reference template's game. Unit defaults to
    # this knob's unit; override it for `*_majorUnits` twin fields.
    also: tuple = ()


@dataclass
class Recipe:
    key: str
    reference: str                    # template path under templates/, must RENDER
    chain: list[Node]                 # ordered; last wires to the terminal
    brand: str = DEFAULT_BRAND
    unlimited: bool = True
    immediate: bool = True
    terminal: str = "end_of_journey"
    knobs: dict[str, Knob] = field(default_factory=dict)   # named -> path


# A promotion's promo-lobby card holds its own copy of the reward config. Reward
# knobs fan out here as well so the card and the bonus never disagree.
PROMO_FS = "initializationData.placements.0.data.freespinActivity."

RECIPES: dict[str, Recipe] = {
    # The proven comms chain (equivalent to compose_comms.py).
    "comms": Recipe(
        key="comms",
        reference="casino/gow_comms.json",
        chain=[
            Node("dwh_source", "PlayerAdded", "Segment — comms"),
            Node("notification_center", "NotificationSent", "On-site notification"),
            Node("notification_center", "NotificationSent", "On-site reminder"),
            Node("dextra_sms", "SuccessSmsSend", "SMS"),
            Node("dextra_email", "SuccessEmailSend", "Email"),
        ],
    ),
    # A sport reward chain — deposit-gated freebet. two_hours is the only
    # reference where deposit/promotion/freebet are NOT nested in a
    # multipurpose_promotion, so their nodes lift cleanly.
    "sport_deposit_freebet": Recipe(
        key="sport_deposit_freebet",
        reference="udch/two_hours.json",
        # two_hours has no STANDALONE notification_center (only boundary ones),
        # so this chain stops at the freebet — the engine refuses to source a
        # node the reference can't supply, which is the correct behaviour.
        chain=[
            Node("registration", "PlayerAdded", "Entry"),
            Node("deposit", "DepositConditionSatisfied", "Deposit gate"),
            Node("promotion", "PromotionAccepted", "Offer"),
            Node("freebet", "PlayerFreebetUsed", "Free bet"),
        ],
        # Named knobs → real paths in THIS recipe's reference (udch/two_hours).
        knobs={
            "deposit_min_clp": Knob(
                "deposit", "initializationData.depositConditions.minDepositAmounts.0.amount",
                "minor", "minimum deposit to unlock the offer, in CLP",
                min_major=100, max_major=1_000_000),
            "freebet_amount_clp": Knob(
                "freebet", "initializationData.properties.freeBetAmount.CLP",
                "minor", "free-bet value in CLP",
                min_major=100, max_major=1_000_000),
            "freebet_expire_days": Knob(
                "freebet", "initializationData.properties.expireInDays",
                "raw", "days the free bet stays valid",
                min_major=1, max_major=365),
            "freebet_max_odd": Knob(
                "freebet", "initializationData.properties.maxOdd",
                "raw", "maximum odds the free bet can be used at",
                min_major=1, max_major=1_000),
            "promocode": Knob(
                "registration", "initializationData.promocodeSettings.values.0",
                "raw", "entry promocode players redeem"),
        },
    ),
    # A casino reward chain — deposit-match freespins + wagering bonus. Its reward
    # nodes live nested inside gow.json's multipurpose_promotion choosable flow,
    # so this is the de-nesting path (place() strips parentNode/extent).
    "casino_deposit_freespins": Recipe(
        key="casino_deposit_freespins",
        reference="casino/gow.json",
        chain=[
            Node("external_system_source", "PlayerAdded", "Entry"),
            Node("deposit", "DepositConditionSatisfied", "Deposit gate"),
            Node("promotion", "PromotionAccepted", "Offer"),
            Node("freespin_bonus", "FreespinBonusCollectingFinished", "Free spins"),
            Node("casino_bonus_v2", "WageringBonusFinished", "Wagering bonus"),
        ],
        knobs={
            "deposit_min_clp": Knob(
                "deposit", "initializationData.depositConditions.minDepositAmounts.0.amount",
                "minor", "minimum deposit to unlock, in CLP",
                min_major=100, max_major=1_000_000),
            "spins": Knob(
                "freespin_bonus", "initializationData.freespinActivity.spins",
                "raw", "number of free spins granted",
                min_major=1, max_major=10_000),
            "spin_bet_clp": Knob(
                "freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.betAmount",
                "minor", "bet value per spin, in CLP",
                min_major=10, max_major=20_000),
            "bonus_percent": Knob(
                "casino_bonus_v2", "initializationData.bonusPercent",
                "raw", "deposit-match percent (100 = 100%)",
                min_major=1, max_major=1_000),
            "wagering_x": Knob(
                "casino_bonus_v2", "initializationData.wageringRequirement",
                "raw", "wagering multiplier (e.g. 30 = x30)",
                min_major=1, max_major=100),
            "bonus_expiry_ms": Knob(
                "casino_bonus_v2", "initializationData.bonusExpirationTime",
                "raw", "bonus validity in milliseconds (172800000 = 48h)"),
            "release_limit_x": Knob(
                "casino_bonus_v2", "initializationData.releaseLimitMultiplier",
                "raw", "max cashout as a multiple of the bonus",
                min_major=1, max_major=100),
        },
    ),
    # An INSTANT bonus — a promotion-gated freespin with NO wagering follow-up
    # (withWagering:false, no casino_bonus_v2). "Una Ronda de Bono Instantáneo".
    # Reference instfs.json renders (6 nodes). Linear: source→promotion→freespin.
    "casino_instant_freespin": Recipe(
        key="casino_instant_freespin",
        reference="casino/instfs.json",
        chain=[
            Node("external_system_source", "PlayerAdded", "Entry"),
            Node("promotion", "PromotionAccepted", "Offer"),
            Node("freespin_bonus", "FreespinBonusCollectingFinished", "Instant free spins"),
        ],
        # Game ids come from the games registry (library/games.json) — the planner
        # resolves a game NAME to these; never guess them.
        # PROMO is the promotion node's promo-lobby card. It carries its own full
        # copy of the freespin config (game, spins, bet), so every reward knob
        # below must write there too or the card advertises instfs.json's own
        # game/spins while the bonus grants something else.
        knobs={
            "spins": Knob(
                "freespin_bonus", "initializationData.freespinActivity.spins",
                "raw", "number of free spins granted",
                also=(("promotion", PROMO_FS + "spins"),),
                min_major=1, max_major=10_000),
            "spin_bet_clp": Knob(
                "freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.betAmount",
                "minor", "bet value per spin, in CLP",
                min_major=10, max_major=5_000,
                also=(
                    ("freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.betAmount_majorUnits", "raw"),
                    ("promotion", PROMO_FS + "currenciesConfig.CLP.betAmount", "minor"),
                    ("promotion", PROMO_FS + "currenciesConfig.CLP.betAmount_majorUnits", "raw"),
                )),
            # Game ids are `required`: omitting them used to silently ship the
            # reference template's own game (Sweet Bonanza Super Scatter), which
            # passes every verify() check. A spec must name the game explicitly.
            "spin_provider": Knob(
                "freespin_bonus", "initializationData.freespinActivity.provider",
                "raw", "game provider id (e.g. pragmatic) — from games registry",
                required=True, also=(("promotion", PROMO_FS + "provider"),)),
            "spin_game_lobby": Knob(
                "freespin_bonus", "initializationData.freespinActivity.lobbyGameId",
                "raw", "lobbyGameId — from games registry, never guessed",
                required=True, also=(("promotion", PROMO_FS + "lobbyGameId"),)),
            "spin_game_wallet": Knob(
                "freespin_bonus", "initializationData.freespinActivity.walletGameId",
                "raw", "walletGameId — from games registry", required=True,
                also=(("promotion", PROMO_FS + "walletGameId"),)),
            "spin_game_external": Knob(
                "freespin_bonus", "initializationData.freespinActivity.externalGameId",
                "raw", "externalGameId — from games registry", required=True,
                also=(("promotion", PROMO_FS + "externalGameId"),)),
        },
    ),
}


# ─────────────────────────── helpers ───────────────────────────
def _nid() -> str:
    return str(uuid.uuid4())


def _swap(obj, old: str, new: str):
    """Regenerate an id everywhere it's embedded (ports/handles/edges included)."""
    return json.loads(json.dumps(obj, ensure_ascii=False).replace(old, new))


def _load(ref: str) -> dict:
    b = json.load(open(TEMPLATES / ref, encoding="utf-8"))
    return b.get("body", b)


def _dotted_set(obj: dict, path: str, value) -> bool:
    """Set obj[a][b][c] = value for path 'a.b.c'. List indices allowed. Returns
    True if applied. Generic knob-override escape hatch used by apply_values()."""
    cur = obj
    parts = path.split(".")
    for p in parts[:-1]:
        key = int(p) if p.isdigit() else p
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return False
    last = parts[-1]
    key = int(last) if last.isdigit() else last
    try:
        cur[key] = value
        return True
    except (KeyError, IndexError, TypeError):
        return False


# ─────────────────────────── core ───────────────────────────
def compose(recipe: Recipe, values: dict | None = None) -> tuple[dict, str, list]:
    values = values or {}
    ref = _load(recipe.reference)
    ref_cfg = ref["rawJourneyData"].get("activitiesConfiguration", {}) or {}
    node_by_id = {e["id"]: e for e in ref["rawJourneyData"]["elements"]
                  if e.get("type") in NODE_TYPES}
    edge_tpl = next(e for e in ref["rawJourneyData"]["elements"]
                    if e.get("type") == "default")

    # Pick the first activity per name that has a CANVAS NODE — a reference like
    # two_hours has headless boundary notifications (a notification_center with
    # no element) that must not be chosen. Fall back to any activity only if
    # none of that type has a node.
    by_name: dict = {}
    for a in ref["activities"]:
        n = a.get("activityName")
        if n not in by_name and a["activityId"] in node_by_id:
            by_name[n] = a
    for a in ref["activities"]:
        by_name.setdefault(a.get("activityName"), a)

    # Fail loud if the reference can't supply a needed activity (assembler, not
    # generator — never fabricate a node the reference doesn't have).
    need = {n.activity for n in recipe.chain} | {recipe.terminal}
    missing = sorted(need - set(by_name))
    if missing:
        raise ValueError(
            f"reference {recipe.reference} is missing {missing}; "
            f"pick a reference journey that contains them all")

    insts = [{"node": n, "old": by_name[n.activity]["activityId"], "aid": _nid()}
             for n in recipe.chain]
    end_old = by_name[recipe.terminal]["activityId"]
    end_aid = _nid()
    chain_ids = [x["aid"] for x in insts] + [end_aid]

    activities, acts_cfg, elements = [], {}, []
    edge_specs = []   # (from_aid, event, etype, activityName, to_aid)

    def place(node_el, old, new, i):
        el = _swap(node_el, old, new)
        el["id"] = new
        pos = {"x": 0, "y": i * 170}
        el["position"], el["positionAbsolute"] = dict(pos), dict(pos)
        el.pop("parentNode", None)          # de-nest from any container...
        el.pop("extent", None)
        d = el.get("data")
        if isinstance(d, dict):             # ...and drop choosable-flow/branch
            for k in ("pathes", "pathId", "pathName", "joinedPathes"):
                d.pop(k, None)              # artifacts that don't exist in a
        return el                           # linear journey

    for i, inst in enumerate(insts):
        n, old, aid = inst["node"], inst["old"], inst["aid"]
        act = _swap(by_name[n.activity], old, aid)

        # find the primary event's real eventType from the node itself
        etype = None
        nxt = chain_ids[i + 1]
        for ev in act.get("events", []) or []:
            if ev.get("eventName") == n.primary:
                ev["nextActivityId"] = nxt
                etype = ev.get("eventType", "Completion")
            else:
                ev["nextActivityId"] = None
        if etype is None:
            raise ValueError(
                f"{n.activity} in {recipe.reference} has no event '{n.primary}'; "
                f"events: {[e.get('eventName') for e in act.get('events', [])]}")
        if n.display:
            act["activityDisplayName"] = n.display
        activities.append(act)

        if old in ref_cfg:
            acts_cfg[aid] = _swap(ref_cfg[old], old, aid)
        elements.append(place(node_by_id[old], old, aid, i))
        edge_specs.append((aid, n.primary, etype, n.activity, nxt))

    # terminal
    end_act = _swap(by_name[recipe.terminal], end_old, end_aid)
    end_act["events"] = []
    activities.append(end_act)
    if end_old in node_by_id:
        elements.append(place(node_by_id[end_old], end_old, end_aid, len(insts)))
    else:
        elements.append({
            "id": end_aid,
            "data": {"name": recipe.terminal,
                     "ports": [{"id": f"input-{end_aid}"}], "width": 40, "height": 40},
            "type": "exit", "style": {"cursor": "default"}, "width": 40, "height": 40,
            "hidden": False, "zIndex": 5,
            "position": {"x": 0, "y": len(insts) * 170},
            "positionAbsolute": {"x": 0, "y": len(insts) * 170},
            "selected": False, "draggable": False, "connectable": False,
        })

    # edges — stamped from a real reference edge (keeps eventDisplayName/payloadKeys)
    for frm, event, etype, aname, to in edge_specs:
        e = copy.deepcopy(edge_tpl)
        e["id"] = _nid()
        e["source"], e["target"] = frm, to
        e["sourceHandle"] = f"{event}-{frm}"
        e["targetHandle"] = f"input-{to}"
        d = e.setdefault("data", {})
        d["eventName"], d["eventType"], d["activityName"] = event, etype, aname
        elements.append(e)

    # shell from the reference (a rendering journey of the right family)
    name = values.get("journey_name") or \
        f"{recipe.brand} | COMPOSE {recipe.key} {datetime.datetime.utcnow():%d.%m %H%M}"
    shell = _load(recipe.reference)
    for k in ("duplicatedFromId", "duplicatedFromVersion", "changeHistory"):
        shell.pop(k, None)
    shell["journeyName"] = name
    shell["activities"] = activities
    shell["reservedJourneyId"] = "DRY-RUN-JOURNEY"
    shell["isUnlimited"] = recipe.unlimited
    shell["isImmediatelyAfterPublish"] = recipe.immediate
    shell["startAt"] = None
    shell["stopAt"] = None
    shell["isArchived"] = False
    shell["rawJourneyData"] = {
        "elements": elements,
        "infoValues": {
            "brand": shell.get("brand", recipe.brand),
            "startAt": None, "stopAt": None,
            "metadata": shell.get("metadata"),
            "timeZoneId": shell.get("timeZoneId", "Chile/Continental"),
            "isUnlimited": recipe.unlimited,
            "journeyName": name,
            "reEntryRule": shell.get("reEntryRule"),
            "currencyCodes": shell.get("currencyCodes", ["CLP"]),
            "isImmediatelyAfterPublish": recipe.immediate,
        },
        "pathesConfiguration": {},
        "boundaryConfiguration": {},
        "exitCriteriaSettings": None,
        "activitiesConfiguration": acts_cfg,
    }
    apply_log = apply_values(shell, values)
    # A MISS means a knob path did not resolve against this reference — the value
    # never landed and the journey would ship the template's own value instead.
    # That used to be invisible (the log was discarded here). Fail closed.
    misses = [line for line in apply_log if line.startswith("MISS ")]
    if misses:
        joined = "\n    ".join(misses)
        raise SpecError(
            f"{len(misses)} knob path(s) did not resolve against reference "
            f"{recipe.reference} — the value would NOT have been applied and the "
            f"journey would ship the template's own value:\n    {joined}\n"
            f"  The reference template's shape has changed; re-check the knob "
            f"paths in RECIPES for this recipe.")
    fix_dates(shell)
    return shell, name, chain_ids


def spec_to_values(recipe: Recipe, spec: dict) -> tuple[dict, list[str]]:
    """Translate an LLM spec {recipe, journey_name, knobs:{name:value}} into the
    generic values dict compose() takes. Returns (values, unknown_knob_names).
    Unit-converts CLP majors to minor units. Unknown knobs are refused, not
    guessed (assembler discipline)."""
    def conv(unit, raw):
        return int(round(raw * 100)) if unit == "minor" else raw

    values: dict = {}
    if spec.get("journey_name"):
        values["journey_name"] = spec["journey_name"]
    sets: dict = {}
    unknown = []
    for kname, raw in (spec.get("knobs") or {}).items():
        knob = recipe.knobs.get(kname)
        if not knob:
            unknown.append(kname)
            continue
        sets.setdefault(knob.activity, {})[knob.path] = conv(knob.unit, raw)
        # Fan the same logical value out to every duplicate copy of it.
        for target in knob.also:
            act, path = target[0], target[1]
            unit = target[2] if len(target) > 2 else knob.unit
            sets.setdefault(act, {})[path] = conv(unit, raw)
    values["set"] = sets
    return values, unknown


# Sentinel markers a planner emits when it cannot resolve a value. A spec
# carrying any of these is a PLAN WITH A HOLE — the composer refuses it rather
# than papering over it with a default (assembler discipline: never guess).
BLOCKER_MARKERS = ("⛔", "RESOLVE_AT_BUILD_TIME", "UNCAPTURED")


class SpecError(ValueError):
    """A spec the composer refuses to build (unknown recipe or a ⛔ blocker)."""


def _find_blockers(obj, prefix: str = "") -> list[str]:
    """Recursively collect dotted paths whose string value carries a blocker."""
    hits: list[str] = []
    if isinstance(obj, str):
        if any(m in obj for m in BLOCKER_MARKERS):
            hits.append(f"{prefix or '<root>'} = {obj!r}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            hits += _find_blockers(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _find_blockers(v, f"{prefix}[{i}]")
    return hits


def _extract_json(raw: str) -> dict:
    """Parse a spec out of whatever the planner actually produced.

    An LLM asked for "ONLY a JSON object" still wraps it in a ```json fence or
    prefixes "Here is the spec:" a good fraction of the time — observed on this
    deployment in a single session. A bare json.load() turns that into a raw
    JSONDecodeError traceback, which is why the spec path could not be driven
    programmatically. Try, in order: the whole string, the last fenced block,
    then the first balanced {...}. Raises SpecError so the caller's existing
    refusal handling applies."""
    text = (raw or "").strip()
    candidates = [text]
    fences = re.findall(r"```(?:json|JSON)?\s*(.*?)```", text, re.S)
    candidates.extend(reversed([f.strip() for f in fences]))
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:i + 1])
                break
    for cand in candidates:
        if not cand:
            continue
        try:
            parsed = json.loads(cand)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise SpecError(
        "could not parse a JSON object from the input. The planner's reply must "
        "contain one spec object; fenced blocks and surrounding prose are "
        "tolerated, but nothing parseable was found.")


# Fields whose value MUST come from the games registry, never from the model's
# sense of what a game id looks like. The prompt shows 106 examples of the very
# regular `pragmatic-<slug>` / `vs20<abbrev>` shape, so a plausible fabrication
# is exactly the failure mode to expect.
GAME_FIELDS = ("provider", "lobbyGameId", "walletGameId", "externalGameId")
GAMES_FILE = HERE / "library" / "games.json"


def _check_ranges(recipe: Recipe, knobs: dict) -> None:
    """Refuse values outside a knob's plausible range, and non-numeric values on
    numeric knobs.

    Two real failures this catches. (1) The unit mix-up: the prompt says amounts
    are major CLP, the model sends minor, and the x100 conversion silently
    inflates the value 100-fold — reproduced live with a "100 CLP per spin"
    brief that shipped a 10,000 CLP spin. (2) A quoted amount ("200") used to
    reach `int(round(raw * 100))` and raise an uncaught TypeError that escaped
    the SpecError handler entirely."""
    bad = []
    for kname, raw in knobs.items():
        knob = recipe.knobs.get(kname)
        if knob is None:
            continue
        numeric = knob.unit == "minor" or knob.min_major is not None or knob.max_major is not None
        if numeric and isinstance(raw, bool):
            bad.append(f"{kname} = {raw!r} is a boolean, expected a number")
            continue
        if numeric and not isinstance(raw, (int, float)):
            bad.append(f"{kname} = {raw!r} is {type(raw).__name__}, expected a number "
                       f"(send 2500, not \"2500\" or \"$2.500\")")
            continue
        if knob.min_major is not None and raw < knob.min_major:
            bad.append(f"{kname} = {raw} is below the plausible minimum "
                       f"{knob.min_major:g}")
        if knob.max_major is not None and raw > knob.max_major:
            # If dividing by 100 lands the value neatly back in range, the model
            # almost certainly sent minor units. Say so explicitly — that is the
            # single most common spec error and the fix is obvious once named.
            lo = knob.min_major if knob.min_major is not None else 0
            unit_hint = ""
            if knob.unit == "minor" and lo <= raw / 100 <= knob.max_major:
                unit_hint = (f" — {raw:g} looks like MINOR units; send major CLP "
                             f"({raw / 100:g}) and the composer converts")
            bad.append(f"{kname} = {raw} exceeds the plausible maximum "
                       f"{knob.max_major:g}{unit_hint}")
    if bad:
        joined = "\n    ".join(bad)
        raise SpecError(
            f"spec has {len(bad)} implausible value(s) — refusing to build a "
            f"journey with amounts nobody meant:\n    {joined}")


def _games_registry() -> dict:
    """{lobbyGameId: entry} from library/games.json. Empty dict if absent —
    grounding then degrades to a no-op rather than blocking every build."""
    if not hasattr(_games_registry, "_cache"):
        try:
            _games_registry._cache = json.loads(
                GAMES_FILE.read_text(encoding="utf-8")).get("games") or {}
        except (OSError, ValueError):
            _games_registry._cache = {}
    return _games_registry._cache


def _check_games(recipe: Recipe, knobs: dict) -> None:
    """Refuse a spec whose game ids are not in the registry, or that mixes ids
    from different games. `never guessed` in the knob descriptions was a request;
    this makes it an invariant."""
    games = _games_registry()
    if not games:
        return
    # knob name -> which game field it lands on
    fields = {k: kb.path.rsplit(".", 1)[-1] for k, kb in recipe.knobs.items()
              if kb.path.rsplit(".", 1)[-1] in GAME_FIELDS}
    given = {k: v for k, v in knobs.items() if k in fields}
    if not given:
        return
    import difflib
    valid = {f: {e.get(f) for e in games.values() if e.get(f)} for f in GAME_FIELDS}
    bad = []
    for kname, value in given.items():
        field_name = fields[kname]
        if value not in valid[field_name]:
            near = difflib.get_close_matches(str(value), sorted(map(str, valid[field_name])), n=3, cutoff=0.5)
            bad.append(f"{kname} = {value!r} is not a known {field_name}"
                       + (f" — did you mean {near}?" if near else ""))
    if bad:
        joined = "\n    ".join(bad)
        raise SpecError(
            f"spec carries {len(bad)} game id(s) absent from the games registry "
            f"({GAMES_FILE.name}, {len(games)} games) — refusing to build a "
            f"journey that awards spins on a game that may not exist:\n    {joined}\n"
            f"  Resolve each from the GAMES REGISTRY, or emit "
            f"'⛔ RESOLVE_AT_BUILD_TIME' so the blocker stays visible.")
    # All ids resolve individually — now make sure they describe the SAME game.
    lobby_knob = next((k for k, f in fields.items() if f == "lobbyGameId"), None)
    lobby = given.get(lobby_knob)
    entry = games.get(lobby) if lobby else None
    if entry:
        mixed = [f"{k} = {v!r} belongs to a different game (expected "
                 f"{entry.get(fields[k])!r})"
                 for k, v in given.items()
                 if fields[k] != "lobbyGameId" and v != entry.get(fields[k])]
        if mixed:
            joined = "\n    ".join(mixed)
            raise SpecError(
                f"spec mixes ids from different games — every game field must "
                f"come from the {lobby!r} row of the registry:\n    {joined}")


def validate_spec(spec: dict) -> Recipe:
    """Refuse a spec the composer must not build. Five hard gates:
      1. `recipe` must be one of the PROVEN recipes — no remap to the nearest.
      2. NO ⛔ / RESOLVE_AT_BUILD_TIME / UNCAPTURED blocker anywhere in the spec.
      3. Every knob name must exist on that recipe. An invented name is a plan
         with a hole: it used to be dropped with a warning, which shipped the
         reference template's own value under a green build.
      4. Every `required` knob must be present, for the same reason.
      5. Every game id must exist in the games registry, and all game fields
         must describe the SAME game.
    Returns the resolved Recipe on success, else raises SpecError with the why."""
    key = spec.get("recipe")
    recipe = RECIPES.get(key)
    if not recipe:
        raise SpecError(
            f"unknown recipe {key!r}. The composer only builds proven recipes: "
            f"{list(RECIPES)}. If none fits, the campaign is ⛔ UNCAPTURED — "
            f"capture a template first; do not remap to the nearest recipe.")
    blockers = _find_blockers(spec)
    if blockers:
        joined = "\n    ".join(blockers)
        raise SpecError(
            f"spec carries {len(blockers)} unresolved blocker(s) — refusing to "
            f"build (a ⛔ value would ship as a literal string):\n    {joined}\n"
            f"  Resolve each (e.g. a real lobbyGameId from the games registry) "
            f"and re-emit the spec.")
    knobs = spec.get("knobs") or {}
    unknown = [k for k in knobs if k not in recipe.knobs]
    if unknown:
        raise SpecError(
            f"spec uses {len(unknown)} knob name(s) that recipe {recipe.key!r} "
            f"does not define: {unknown}. Dropping them would silently ship "
            f"{recipe.reference}'s own values. Valid knobs: "
            f"{sorted(recipe.knobs)}.")
    missing = [k for k, v in recipe.knobs.items() if v.required and k not in knobs]
    if missing:
        raise SpecError(
            f"spec omits {len(missing)} required knob(s) for recipe "
            f"{recipe.key!r}: {missing}. Without them the journey ships "
            f"{recipe.reference}'s own values (real production content). "
            f"Resolve each from the games registry and re-emit the spec.")
    _check_ranges(recipe, knobs)
    _check_games(recipe, knobs)
    return recipe


def compose_from_spec(spec: dict) -> tuple[Recipe, dict, str, list[str]]:
    recipe = validate_spec(spec)
    values, unknown = spec_to_values(recipe, spec)
    body, name, _ = compose(recipe, values)
    return recipe, body, name, unknown


def compose_from_graph(spec: dict) -> tuple[Recipe, dict, str, list[str]]:
    """Build a journey from an INLINE activity graph — no pre-registered recipe.

    This is the programmatic "define activities and connect them" entry point an
    AI/agent can emit. It's an ad-hoc recipe: still LINEAR and still sourced from
    ONE reference journey that renders (the same safety guarantees as a recipe —
    see COMPOSER_RULES.md), just defined per-call instead of in the RECIPES dict.

    Spec shape:
      {
        "reference": "casino/instfs.json",      # a template that RENDERS; every
                                                 # chain activity is sourced from it
        "journey_name": "JBCL | ...",            # optional
        "terminal": "end_of_journey",            # optional (default)
        "chain": [                               # ordered; each wired to the next
          {"activity": "external_system_source", "primary": "PlayerAdded"},
          {"activity": "promotion",  "primary": "PromotionAccepted"},
          {"activity": "freespin_bonus", "primary": "FreespinBonusCollectingFinished",
           "display": "Instant free spins"}
        ],
        "set": {                                 # optional knob overrides, applied
          "freespin_bonus": {                    # into BOTH storage copies
            "initializationData.freespinActivity.spins": 5
          }
        }
      }
    Refuses ⛔ blockers and a missing/uncaptured reference, exactly like a spec.
    """
    ref = spec.get("reference")
    if not ref or not (TEMPLATES / ref).exists():
        raise SpecError(
            f"reference {ref!r} not found under templates/. A graph must be sourced "
            f"from ONE captured journey that renders (no schema mixing).")
    chain_spec = spec.get("chain") or []
    if not chain_spec:
        raise SpecError("graph spec needs a non-empty 'chain' of activities.")
    for i, c in enumerate(chain_spec):
        if not c.get("activity") or not c.get("primary"):
            raise SpecError(
                f"chain[{i}] needs both 'activity' and 'primary' (the forward "
                f"event that wires it to the next node).")
    blockers = _find_blockers(spec)
    if blockers:
        joined = "\n    ".join(blockers)
        raise SpecError(
            f"graph carries {len(blockers)} unresolved blocker(s) — refusing to "
            f"build:\n    {joined}")

    chain = [Node(c["activity"], c["primary"], c.get("display")) for c in chain_spec]
    recipe = Recipe(
        key=spec.get("key") or "graph",
        reference=ref,
        chain=chain,
        terminal=spec.get("terminal", "end_of_journey"),
    )
    values: dict = {}
    if spec.get("journey_name"):
        values["journey_name"] = spec["journey_name"]
    if spec.get("set"):
        values["set"] = spec["set"]
    # compose() raises ValueError if the reference can't supply an activity/event;
    # surface that as a SpecError so the CLI/API reports it cleanly.
    try:
        body, name, _ = compose(recipe, values)
    except ValueError as exc:
        raise SpecError(str(exc)) from exc
    return recipe, body, name, []


def _reference_index() -> dict:
    """List every template journey and the activities it can supply — so the
    planner knows which reference a MODE 4 graph can be sourced from. Only
    references used by a recipe (proven to render) are listed; each maps to the
    distinct activityNames that have a canvas node in it."""
    refs: dict = {}
    for r in RECIPES.values():
        if r.reference in refs:
            continue
        try:
            ref = _load(r.reference)
        except Exception:  # noqa: BLE001
            continue
        node_ids = {e["id"] for e in ref["rawJourneyData"]["elements"]
                    if e.get("type") in NODE_TYPES}
        acts = sorted({a["activityName"] for a in ref["activities"]
                       if a["activityId"] in node_ids})
        refs[r.reference] = acts
    return refs


def _chain_palette() -> dict:
    """The chain composer's palette, compacted for the prompt.

    RECIPES cover four fixed shapes. Anything else — a repeated activity, a
    choosable flow, a branch — needs journey_composer.py, which assembles an
    arbitrary chain from captured nodes. Publishing its palette here is what
    lets the planner emit a chain spec at all; without it the model only ever
    sees the four recipes and answers '⛔ UNCAPTURED' to everything else.

    Deliberately drops the full per-activity event lists and game table (~30KB)
    — the events are implied by `follow`, and games_index.md is already injected
    separately. Degrades to {} if journey_composer is unavailable.
    """
    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import journey_composer as jc
        opts = jc.options()
    except Exception:
        return {}
    return {
        "_doc": "For journeys no recipe covers. Emit a chain spec and build it with "
                "`python journey-cloner/journey_composer.py compose <file> --script`. "
                "Activities may repeat. `game` accepts any name/id/alias from the "
                "games registry; unknown names are REFUSED, never guessed.",
        "sources": opts.get("sources", {}),
        "activities": {
            k: {"aliases": v.get("aliases", []),
                "follow": v.get("default_follow"),
                "settings": sorted(v.get("settings", {}))}
            for k, v in (opts.get("chain_types") or {}).items()
        },
        "spec_shape": opts.get("spec_shape", {}),
    }


def _knob_doc(k: Knob) -> dict:
    """One knob as the planner sees it. `range` is the accepted span of the value
    AS SENT, so the model can self-check before emitting rather than discovering
    the bound via a refusal."""
    doc: dict = {"wire_unit": k.unit, "desc": k.desc}
    if k.required:
        doc["required"] = True
    if k.min_major is not None or k.max_major is not None:
        doc["range"] = [k.min_major, k.max_major]
    return doc


def catalog() -> dict:
    """Machine-readable recipe catalog for the planner LLM to emit specs against.
    Includes a `references` index for MODE 4 graphs (which reference journey can
    supply which activities)."""
    return {
        "_legend": {
            "wire_unit": "Unit of the DESTINATION field on the platform, NOT the "
                         "unit you send. ALWAYS send amounts in major CLP — the "
                         "composer converts where wire_unit is 'minor'. Sending "
                         "minor units yields a 100x value.",
            "required": "A spec that omits this knob is REFUSED, because omitting "
                        "it would silently ship the reference template's own value.",
            "range": "[min, max] for the value AS SENT (major CLP). Outside it the "
                     "spec is REFUSED. Worked example: a 100 CLP per-spin bet is "
                     "spin_bet_clp: 100 — NOT 10000.",
        },
        "recipes": {
            k: {
                "reference": r.reference,
                "chain": [n.activity for n in r.chain] + [r.terminal],
                "knobs": {kn: _knob_doc(v) for kn, v in r.knobs.items()},
            } for k, r in RECIPES.items()
        },
        "references": _reference_index(),
        "chain_composer": _chain_palette(),
    }


def fix_dates(body: dict) -> list[str]:
    """Find and correct invalid ISO-8601 dates in the journey (stopAt, startAt, etc.).
    Dates in the past or invalid sequences are corrected to sensible defaults.
    Returns a log of corrections made."""
    log = []
    now = datetime.datetime.now(datetime.timezone.utc)

    def check_date(path, val):
        if not isinstance(val, str) or 'T' not in val:
            return None, None
        try:
            if val.endswith('Z'):
                dt = datetime.datetime.fromisoformat(val[:-1] + '+00:00')
            else:
                dt = datetime.datetime.fromisoformat(val)
            return dt, dt.astimezone(datetime.timezone.utc) if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
        except (ValueError, TypeError):
            return None, None

    def to_iso_z(dt):
        """Convert timezone-aware datetime to ISO-8601Z format (no +HH:MM)."""
        utc = dt.astimezone(datetime.timezone.utc) if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
        return utc.replace(tzinfo=None).isoformat() + "Z"

    def walk(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_prefix = f"{prefix}.{k}" if prefix else k
                # Check date fields
                if k in ("stopAt", "startAt") and isinstance(v, str):
                    orig_dt, utc_dt = check_date(new_prefix, v)
                    if utc_dt and utc_dt < now and k == "stopAt":
                        # stopAt in the past — set to 7 days from now
                        new_dt = (now + datetime.timedelta(days=7)).replace(microsecond=0)
                        new_val = to_iso_z(new_dt)
                        obj[k] = new_val
                        log.append(f"fix {new_prefix}: past date -> {new_val}")
                    elif utc_dt and utc_dt < now and k == "startAt":
                        # startAt in the past — set to now
                        new_dt = now.replace(microsecond=0)
                        new_val = to_iso_z(new_dt)
                        obj[k] = new_val
                        log.append(f"fix {new_prefix}: past date -> {new_val}")
                elif k in ("stopAt", "startAt"):
                    walk(v, new_prefix)
                elif isinstance(v, (dict, list)):
                    walk(v, new_prefix)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{prefix}[{i}]")

    walk(body)
    return log


def apply_values(body: dict, values: dict) -> list[str]:
    """Generic override layer. values["set"] = {"<activityName>": {"<dotted.path>": v}}
    applies into that activity's object. Returns a log. (Full knob schemas = #3.)"""
    log = []
    sets = (values or {}).get("set") or {}
    by_name = {}
    for a in body["activities"]:
        by_name.setdefault(a["activityName"], a)
    # editor mirror, keyed by activityId; the equivalent of an activity's
    # `initializationData.X` path is `data.X` inside its config here.
    mirror = (body.get("rawJourneyData") or {}).get("activitiesConfiguration") or {}
    for aname, overrides in sets.items():
        act = by_name.get(aname)
        if not act:
            log.append(f"skip {aname}: not in journey")
            continue
        mcfg = mirror.get(act.get("activityId"))
        for path, v in overrides.items():
            ok = _dotted_set(act, path, v)
            log.append(f"{'set' if ok else 'MISS'} {aname}.{path} = {v!r}")
            # Keep the rawJourneyData editor mirror in sync (dual-storage rule):
            # a stale mirror ships an inconsistent journey. The mirror nests an
            # activity's config under `data.` for most activity types but under
            # `properties.` for some (a promotion's `placements`, for one), so
            # try both before calling it a MISS.
            if mcfg is not None and path.startswith("initializationData."):
                rest = path[len("initializationData."):]
                mok, mpath = False, "data." + rest
                for prefix in ("data.", "properties."):
                    if _dotted_set(mcfg, prefix + rest, v):
                        mok, mpath = True, prefix + rest
                        break
                log.append(f"{'set' if mok else 'MISS'} mirror {aname}.{mpath} = {v!r}")
    return log


# ─────────────────────────── verify ───────────────────────────
def verify(body: dict) -> list[tuple[bool, str]]:
    acts = body["activities"]
    rjd = body["rawJourneyData"]
    ids = {a["activityId"] for a in acts}
    els = rjd["elements"]
    node_ids = {e["id"] for e in els if e.get("type") in NODE_TYPES}
    ports = {e["id"]: {p["id"] for p in (e.get("data") or {}).get("ports", [])}
             for e in els if e.get("type") in NODE_TYPES}
    checks = []

    dangling = [ev.get("nextActivityId") for a in acts for ev in a.get("events", []) or []
                if ev.get("nextActivityId") and ev["nextActivityId"] not in ids]
    checks.append((not dangling, f"nextActivityId all resolve ({len(dangling)} dangling)"))

    miss_node = [a["activityName"] for a in acts if a["activityId"] not in node_ids]
    checks.append((not miss_node, f"every activity has a canvas node ({miss_node or 'none'})"))

    orphan = [k for k in rjd["activitiesConfiguration"] if k not in ids]
    checks.append((not orphan, f"config keys all map to activities ({len(orphan)} orphan)"))

    bad_edge, bad_handle = [], []
    for e in els:
        if e.get("type") in ("default", "emptyEdge"):
            if e.get("source") not in node_ids or e.get("target") not in node_ids:
                bad_edge.append(e.get("id"))
            elif (e.get("sourceHandle") not in ports.get(e["source"], set()) or
                  e.get("targetHandle") not in ports.get(e["target"], set())):
                bad_handle.append(e["data"].get("eventName"))
    checks.append((not bad_edge, f"edges connect real nodes ({len(bad_edge)} bad)"))
    checks.append((not bad_handle, f"edge handles match node ports ({bad_handle or 'none'})"))

    bad_pos = [f"{(e.get('data') or {}).get('name')}::{k}"
               for e in els if e.get("type") in NODE_TYPES
               for k in ("position", "positionAbsolute")
               if not isinstance(e.get(k), dict) or "x" not in (e.get(k) or {})]
    checks.append((not bad_pos, f"every node has position+positionAbsolute ({bad_pos or 'none'})"))

    checks.append((any(a["activityName"] == "end_of_journey" for a in acts),
                   "has an end_of_journey terminal"))
    return checks


# ─────────────────────────── emit ───────────────────────────
JS_TEMPLATE = r'''// Composed journey — generated @GENERATED_AT@
// Recipe: @RECIPE@   Journey: @NAME@
//
// Paste into a logged-in Journey Builder backoffice console (F12). It captures
// the token, reserves a JRN id, freshens ids, and POSTs one draft.
(async () => {
  const BASE = @BASE@;
  const BRAND = @BRAND@;
  const BODY = @BODY@;

  function decodeJwt(t){ try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch(e){ return null; } }
  function usableAuth(v){ if(!v || !/^Bearer\s+\S+/i.test(v)) return null; const p=decodeJwt(v.replace(/^Bearer\s+/i,'')); if(!p||p.typ!=='Bearer') return null; return 'Bearer '+v.replace(/^Bearer\s+/i,''); }
  function obtainAuth(){ return new Promise((resolve,reject)=>{
    let settled=false; const of=window.fetch; const os=XMLHttpRequest.prototype.setRequestHeader;
    const cleanup=()=>{ window.fetch=of; XMLHttpRequest.prototype.setRequestHeader=os; };
    const consider=(v)=>{ const a=usableAuth(v); if(a&&!settled){ settled=true; cleanup(); clearTimeout(t); console.log('%cToken captured.','color:#22c55e;font-weight:bold'); resolve(a); } };
    window.fetch=function(input,init){ try{ const h=(init&&init.headers)||(input&&input.headers); if(h){ if(typeof h.get==='function') consider(h.get('authorization')); else consider(h.authorization||h.Authorization); } }catch(e){} return of.apply(this,arguments); };
    XMLHttpRequest.prototype.setRequestHeader=function(n,v){ try{ if(/^authorization$/i.test(n)) consider(v); }catch(e){} return os.apply(this,arguments); };
    const t=setTimeout(()=>{ if(!settled){ settled=true; cleanup(); reject(new Error('No token in 3 min. Click around and re-run.')); } },180000);
    console.log('%cWaiting for a token — click anything in the backoffice UI.','color:#eab308;font-weight:bold');
  }); }

  const auth = await obtainAuth();
  const headers=(ct)=>({ accept:'application/json, text/plain, */*', authorization:auth, 'content-type':ct, 'x-brand':BRAND });
  const newUuid=()=> (crypto&&crypto.randomUUID)? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,(c)=>{ const r=(Math.random()*16)|0; return (c==='x'?r:(r&0x3)|0x8).toString(16); });
  const UUID_RE=/"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  const regen=(txt)=>{ const olds=new Set(); let m; UUID_RE.lastIndex=0; while((m=UUID_RE.exec(txt))!==null) olds.add(m[1]); let t=txt; for(const o of olds) t=t.split(o).join(newUuid()); return t; };

  async function reserveId(){
    const r=await fetch(BASE+'/journeys/identifier',{ method:'POST', headers:headers('application/x-www-form-urlencoded'), credentials:'include' });
    const raw=(await r.text()).trim(); let id=raw.replace(/^"+|"+$/g,'');
    try{ const d=JSON.parse(raw); if(typeof d==='string') id=d.trim(); else if(d&&typeof d==='object') id=String(d.identifier||d.journeyId||d.id||d.value||'').trim(); }catch(e){}
    if(!r.ok||!id.startsWith('JRN-')) throw new Error('reserve failed HTTP '+r.status+' '+raw);
    return id;
  }

  console.log('Reserving journey id...');
  const rid = await reserveId();
  console.log('  reserved', rid);
  let text = JSON.stringify(BODY).split('DRY-RUN-JOURNEY').join(rid);
  text = regen(text);
  const body = JSON.parse(text);
  console.log('Creating draft', rid, ':', body.journeyName);
  const r = await fetch(BASE+'/journey-drafts',{ method:'POST', headers:headers('application/json'), credentials:'include', body:JSON.stringify(body) });
  const respText = await r.text();
  if(!r.ok){ console.error('%cFAILED HTTP '+r.status,'color:#ef4444;font-weight:bold', respText); return; }
  console.log('%cDRAFT CREATED: '+rid,'color:#22c55e;font-weight:bold');
  console.log('Open it in the editor and check the nodes are wired. Response:', respText);
})();
'''


def emit(recipe: Recipe, body: dict, name: str) -> Path:
    js = (JS_TEMPLATE
          .replace("@GENERATED_AT@", datetime.datetime.utcnow().isoformat() + "Z")
          .replace("@RECIPE@", recipe.key)
          .replace("@NAME@", name)
          .replace("@BASE@", json.dumps(BASE_URL))
          .replace("@BRAND@", json.dumps(recipe.brand))
          .replace("@BODY@", json.dumps(body, ensure_ascii=False)))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"composed_{recipe.key}_console.js"
    out.write_text(js, encoding="utf-8")
    return out


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-l", "--list"):
        print("Recipes:")
        for k, r in RECIPES.items():
            chain = " -> ".join(n.activity for n in r.chain) + f" -> {r.terminal}"
            print(f"  {k:24s} [{r.reference}]  {chain}")
            if r.knobs:
                print(f"      knobs: {', '.join(r.knobs)}")
        print("\nUsage: python compose.py <recipe>            (compose with defaults)")
        print("       python compose.py --spec spec.json     (compose from an LLM recipe-spec)")
        print("       python compose.py --graph graph.json   (compose from an inline activity graph)")
        print("       python compose.py --catalog            (write recipes_catalog.json)")
        return 0

    if args[0] == "--catalog":
        out = HERE / "recipes_catalog.json"
        out.write_text(json.dumps(catalog(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out}")
        return 0

    unknown_knobs = []
    if args[0] in ("--spec", "--graph"):
        raw = (Path(args[1]).read_text(encoding="utf-8") if len(args) > 1
               else sys.stdin.read())
        builder = compose_from_spec if args[0] == "--spec" else compose_from_graph
        try:
            recipe, body, name, unknown_knobs = builder(_extract_json(raw))
        except SpecError as exc:
            print(f"⛔ REFUSED — {exc}")
            return 3
    else:
        key = args[0]
        if key not in RECIPES:
            print(f"unknown recipe {key!r}; run with no args to list")
            return 2
        recipe = RECIPES[key]
        body, name, _ = compose(recipe)

    if unknown_knobs:
        print(f"  ⚠ ignored unknown knobs (not in recipe {recipe.key}): {unknown_knobs}")
    print(f"Composed: {name}")
    print(f"  activities: {len(body['activities'])}  "
          f"elements: {len(body['rawJourneyData']['elements'])}")
    ok = True
    for good, msg in verify(body):
        print(f"  [{'OK' if good else 'FAIL'}] {msg}")
        ok = ok and good
    if not ok:
        print("\nVerification FAILED — not emitting.")
        return 1
    out = emit(recipe, body, name)
    print(f"\nAll checks passed. Console script: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
