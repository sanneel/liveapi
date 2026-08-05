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
    # A comms journey is NEVER a row of sends. The unit is send -> wait -> split
    # -> send: after a channel fires you wait, then branch on how the player
    # engaged, and only the branch that still needs chasing gets the next
    # channel. This chain used to be dwh_source -> nc -> nc -> sms -> email,
    # which stripped every wait and split out of its OWN reference (gow_comms
    # has 3 waits, 2 NC engagement splits, 1 email split) and fired all four
    # channels at once at everybody. The order below mirrors gow_comms Flow 1.
    "comms": Recipe(
        key="comms",
        reference="casino/gow_comms.json",
        chain=[
            Node("dwh_source", "PlayerAdded", "Segment — comms"),
            Node("notification_center", "NotificationSent", "On-site notification"),
            Node("wait_interval", "WaitTimeCompleted", "Wait — let it land"),
            Node("notification_center_engagement_split",
                 "NCEngagementSplitPassedPath02", "Did they engage?"),
            Node("notification_center", "NotificationSent", "On-site reminder"),
            Node("wait_interval", "WaitTimeCompleted", "Wait — before email"),
            Node("dextra_email", "SuccessEmailSend", "Email"),
            Node("wait_interval", "WaitTimeCompleted", "Wait — before SMS"),
            Node("email_engagement_split", "Path2", "Did they open it?"),
            Node("dextra_sms", "SuccessSmsSend", "SMS — last resort"),
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
        # promotion -> deposit, never the reverse (see the same fix on
        # casino_deposit_freespins). This recipe also had it backwards. Its own
        # reference wires registration -> split -> promotion --PromotionAccepted-->
        # deposit --DepositConditionSatisfied--> freebet; the split is flattened
        # away here but the promotion/deposit order is not ours to change.
        chain=[
            Node("registration", "PlayerAdded", "Entry"),
            Node("promotion", "PromotionAccepted", "Offer"),
            Node("deposit", "DepositConditionSatisfied", "Deposit gate"),
            Node("freebet", "PlayerFreebetUsed", "Free bet"),
        ],
        # Named knobs → real paths in THIS recipe's reference (udch/two_hours).
        knobs={
            "deposit_min_clp": Knob(
                "deposit", "initializationData.depositConditions.minDepositAmounts.0.amount",
                "minor", "minimum deposit to unlock the offer, in CLP",
                min_major=0, max_major=1_000_000),
            "freebet_amount_clp": Knob(
                "freebet", "initializationData.properties.freeBetAmount.CLP",
                "minor", "free-bet value in CLP",
                min_major=100, max_major=100_000),
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
        # ORDER IS promotion -> deposit, NEVER the reverse. This recipe had it
        # backwards (deposit -> promotion) and so built every draft with the
        # gate ahead of the offer, contradicting its OWN reference: across the
        # five captures that carry both nodes (gow, spinladder, pmcl_betandget,
        # two_hours, followup) there are 13 promotion -> deposit edges, all on
        # PromotionAccepted, and zero deposit -> promotion. The player has to
        # ACCEPT the offer before a condition can gate its reward; a deposit
        # gate placed first has nothing to gate.
        chain=[
            Node("external_system_source", "PlayerAdded", "Entry"),
            Node("promotion", "PromotionAccepted", "Offer"),
            Node("deposit", "DepositConditionSatisfied", "Deposit gate"),
            Node("freespin_bonus", "FreespinBonusCollectingFinished", "Free spins"),
            Node("casino_bonus_v2", "WageringBonusFinished", "Wagering bonus"),
        ],
        knobs={
            "deposit_min_clp": Knob(
                "deposit", "initializationData.depositConditions.minDepositAmounts.0.amount",
                "minor", "minimum deposit to unlock, in CLP",
                min_major=0, max_major=1_000_000),
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
                min_major=0, max_major=1_000),
            "wagering_x": Knob(
                "casino_bonus_v2", "initializationData.wageringRequirement",
                "raw", "wagering multiplier (e.g. 30 = x30)",
                min_major=0, max_major=100),
            "bonus_expiry_ms": Knob(
                "casino_bonus_v2", "initializationData.bonusExpirationTime",
                "raw", "bonus validity in milliseconds (172800000 = 48h)"),
            "release_limit_x": Knob(
                "casino_bonus_v2", "initializationData.releaseLimitMultiplier",
                "raw", "max cashout as a multiple of the bonus",
                min_major=0, max_major=100),
            # Same silent-cap trap as the instant recipe: unset means gow.json's
            # own maxBonusAmount ships instead of the brief's.
            "spin_max_bonus_clp": Knob(
                "freespin_bonus",
                "initializationData.freespinActivity.currenciesConfig.CLP.maxBonusAmount",
                "minor", "cap on winnings from the spins, in CLP",
                min_major=0, max_major=100_000_000,
                also=(("freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.maxBonusAmount_majorUnits", "raw"),)),
            "spin_min_bonus_clp": Knob(
                "freespin_bonus",
                "initializationData.freespinActivity.currenciesConfig.CLP.minBonusAmount",
                "minor", "minimum winnings paid from the spins, in CLP",
                min_major=0, max_major=100_000_000,
                also=(("freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.minBonusAmount_majorUnits", "raw"),)),
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
                also=(("promotion", PROMO_FS + "provider"),)),
            "spin_game_lobby": Knob(
                "freespin_bonus", "initializationData.freespinActivity.lobbyGameId",
                "raw", "lobbyGameId — from games registry, never guessed",
                required=True, also=(("promotion", PROMO_FS + "lobbyGameId"),)),
            "spin_game_wallet": Knob(
                "freespin_bonus", "initializationData.freespinActivity.walletGameId",
                "raw", "walletGameId — from games registry", also=(("promotion", PROMO_FS + "walletGameId"),)),
            "spin_game_external": Knob(
                "freespin_bonus", "initializationData.freespinActivity.externalGameId",
                "raw", "externalGameId — from games registry", also=(("promotion", PROMO_FS + "externalGameId"),)),
            # Without these the journey silently keeps instfs.json's own caps —
            # a brief asking for "Max bonus 200k" shipped 50k and the operator
            # only saw it by opening the activity in the backoffice.
            "spin_max_bonus_clp": Knob(
                "freespin_bonus",
                "initializationData.freespinActivity.currenciesConfig.CLP.maxBonusAmount",
                "minor", "cap on winnings from the spins, in CLP",
                min_major=0, max_major=100_000_000,
                also=(
                    ("freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.maxBonusAmount_majorUnits", "raw"),
                    ("promotion", PROMO_FS + "currenciesConfig.CLP.maxBonusAmount", "minor"),
                    ("promotion", PROMO_FS + "currenciesConfig.CLP.maxBonusAmount_majorUnits", "raw"),
                )),
            "spin_min_bonus_clp": Knob(
                "freespin_bonus",
                "initializationData.freespinActivity.currenciesConfig.CLP.minBonusAmount",
                "minor", "minimum winnings paid from the spins, in CLP",
                min_major=0, max_major=100_000_000,
                also=(
                    ("freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.minBonusAmount_majorUnits", "raw"),
                    ("promotion", PROMO_FS + "currenciesConfig.CLP.minBonusAmount", "minor"),
                    ("promotion", PROMO_FS + "currenciesConfig.CLP.minBonusAmount_majorUnits", "raw"),
                )),
            # "Provider's campaign end date" in the backoffice. Left unset, the
            # reference's date is in the past and fix_dates pushes it to +7 days
            # from the build — a date nobody chose. Send the campaign's own end.
            "spin_campaign_end": Knob(
                "freespin_bonus", "initializationData.freespinActivity.stopAt",
                "raw", "provider campaign end, ISO-8601 Z (e.g. 2026-03-15T23:59:59Z)",
                also=(("promotion", PROMO_FS + "stopAt"),)),
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
    node_els = {e["id"]: e for e in elements if "source" not in e}
    for frm, event, etype, aname, to in edge_specs:
        e = copy.deepcopy(edge_tpl)
        e["id"] = _nid()
        e["source"], e["target"] = frm, to
        e["sourceHandle"] = f"{event}-{frm}"
        e["targetHandle"] = f"input-{to}"
        # A SPLIT names its handles path1..pathN / other, NOT after the event the
        # way every other node does, and the captured fragment only kept the
        # ports it had wired (input, path1, other). So an edge off any path but
        # the first addressed a handle the node did not expose and the canvas
        # dropped it — which is why a comms chain could previously only branch on
        # path 1, never the path the captures actually take.
        handle = _split_handle(aname, event)
        if handle:
            e["sourceHandle"] = f"{handle}-{frm}"
            node = node_els.get(frm)
            if node is not None:
                ports = node.setdefault("data", {}).setdefault("ports", [])
                if not any(p.get("id") == e["sourceHandle"] for p in ports):
                    ports.append({"id": e["sourceHandle"]})
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
    # A rewritten date is a value the operator did not choose (a campaign whose
    # window has already passed gets pushed to +7 days), so it is announced
    # rather than swallowed — this silently shipped an August end date on a March
    # campaign and only turned up when someone opened the draft.
    # ONE line, not one per field: a 20-journey batch printed five of these per
    # journey and the ~100 lines buried the refusals underneath them.
    rewritten = fix_dates(shell)
    if rewritten:
        when = re.search(r"-> (\S+)", rewritten[0])
        print(f"  ⚠ {len(rewritten)} stale template date(s) rewritten"
              f"{' to ' + when.group(1) if when else ''}"
              f" — set `spin_campaign_end` to choose it yourself")
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


def _extract_json_any(raw: str):
    """Like _extract_json but also accepts a top-level ARRAY, and stitches
    several separate fenced objects into one list — which is how the planner
    actually answers "give me the spec for every journey"."""
    text = (raw or "").strip()
    fences = [f.strip() for f in re.findall(r"```(?:json|JSON)?\s*(.*?)```", text, re.S)]
    objs = []
    for fence in fences:
        try:
            parsed = json.loads(fence)
        except ValueError:
            continue
        objs.extend(parsed if isinstance(parsed, list) else [parsed])
    if len(objs) > 1:
        return objs
    for candidate in ([text] + fences):
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, (list, dict)):
            return parsed
    if objs:
        return objs
    return _extract_json(text)          # raises SpecError with the usual message


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


# Fields that identify WHOSE campaign a journey is. A composed journey that
# still carries the reference's values here is not a new campaign — it is the
# old one wearing a new name, and it will message real players with the old
# copy and the old links.
CONTENT_KEYS = (
    "messageText", "localizedMessageTexts",     # SMS body
    "emailSettings",                            # email template id
    "promocodeSettings",                        # entry promocode
    "objectForSend", "localizedLanguagesTab",   # notification-centre copy + links
)
# Values that legitimately repeat across campaigns — matching these is not a leak.
_CONTENT_NOISE = {"", "link", "regular", "1", "True", "%icon%", "%deeplink%"}


def _split_handle(activity_name: str, event: str) -> str | None:
    """Canvas handle for an edge leaving a SPLIT node, or None for other nodes.

    Splits are the one family whose handles are not named after the event:
    `NCEngagementSplitPassedPath02` leaves through the port `path2`, a
    `...RemainderPath` through `other`. Everything else uses `<event>-<id>`.
    """
    if "split" not in str(activity_name or "").lower():
        return None
    if not event:
        return None
    if re.search(r"remainder", event, re.I):
        return "other"
    m = re.search(r"(?:path)0*(\d+)$", event, re.I)
    return f"path{int(m.group(1))}" if m else None


def _collect_content(obj, out: list, path: str = "") -> None:
    """Every campaign-identifying string in a journey body, with its path."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}" if path else key
            if key in CONTENT_KEYS:
                flat: list = []
                _flatten_strings(value, flat)
                for s in flat:
                    out.append((here, s))
            else:
                _collect_content(value, out, here)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _collect_content(value, out, f"{path}[{i}]")


def _is_content(s: str) -> bool:
    """Player-visible copy or a campaign-specific identifier, as opposed to the
    structural vocabulary these blobs are full of (variable names like 'group',
    'title', 'layout', which repeat across every campaign and mean nothing)."""
    s = s.strip()
    if len(s) < 8 or s in _CONTENT_NOISE:
        return False
    # Template placeholders (%link-es%, %$utm_tags%) are plumbing that every
    # campaign shares — they are how the platform substitutes values, not the
    # values themselves.
    if "%" in s or "{{" in s:
        return False
    if "://" in s:                      # a real link
        return True
    if " " in s:                        # a sentence of player-visible copy
        return True
    # Campaign-specific identifiers: CSE-0-14458, promocodes, template ids.
    # Deliberately NOT "any long string" — snake_case field names like
    # buttons_1_highlighted are structural vocabulary, not content.
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{7,}", s))


def _flatten_strings(obj, out: list) -> None:
    if isinstance(obj, str):
        if _is_content(obj):
            out.append(obj.strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _flatten_strings(v, out)


def audit_inherited_content(body: dict, reference: dict, *,
                            allowed=()) -> list[str]:
    """Campaign content the composed journey still shares with its reference.

    This is the generalisable version of the failures that actually shipped: a
    "Physical Prize" journey carrying the Game of the Week SMS, email template
    and promo link, and a wheel-prize freebet carrying promocode VAMOSBULLA.
    Every value-level gate passed those, because the spec was well-formed — the
    journey was simply still the old campaign underneath.

    Returns one line per distinct leaked value. Empty list means the composed
    journey shares no message copy, template id, promocode or link with the
    journey it was cloned from.

    ``allowed`` is a set of strings that the caller *knows* were chosen by the
    operator this run (typically the pasted sheet's copy). A value on the
    allow-list is not flagged even if it happens to equal the capture's — the
    operator wrote "Join the tournament" because that is what they want to
    ship, not because it leaked from the template.
    """
    ref_content: list = []
    _collect_content(reference, ref_content)
    ref_values = {s for _, s in ref_content}
    if not ref_values:
        return []
    allow_set = {s.strip() for s in allowed if isinstance(s, str) and s.strip()}
    new_content: list = []
    _collect_content(body, new_content)
    leaked: dict[str, str] = {}
    for path, value in new_content:
        if value in ref_values and value.strip() not in allow_set:
            leaked.setdefault(value, path)
    return [f"{path} still carries {value[:88]!r}"
            for value, path in sorted(leaked.items(), key=lambda kv: kv[1])]


def _check_recipe_fit(recipe: Recipe, knobs: dict) -> None:
    """Refuse a recipe that cannot express the journey being asked for.

    The gates below check VALUES. This one checks SHAPE, because the expensive
    failures are recipes force-fitted onto a different flow — the spec is
    structurally perfect and the journey is still wrong. Both cases here were
    produced by a real brief:

      * `comms` has no knobs at all, so it can only ever ship its reference
        journey verbatim. A "Physical Prize — notify the winner" journey built
        as `comms` shipped the Game of the Week segment, its two on-site
        messages, its SMS and its email, with live production copy.
      * a recipe whose chain contains a deposit gate, given a minimum of 0, is
        the wrong recipe: the journey wanted has no deposit step. A wheel-prize
        freebet built as `sport_deposit_freebet` shipped a pointless deposit
        node AND the reference's registration entry, promocode and all.
    """
    if not recipe.knobs:
        raise SpecError(
            f"recipe {recipe.key!r} defines no knobs, so it can only reproduce "
            f"{recipe.reference} EXACTLY — including its segment, its message "
            f"copy and its promo links. Building a different campaign with it "
            f"ships that campaign's content under your journey's name.\n"
            f"  Use a MODE 5 chain spec instead, where each activity's content "
            f"is set explicitly.")
    chain = [n.activity for n in recipe.chain]
    if "deposit" in chain and knobs.get("deposit_min_clp") == 0:
        raise SpecError(
            f"recipe {recipe.key!r} is deposit-gated (chain: "
            f"{' -> '.join(chain)}) but the spec sets deposit_min_clp to 0. "
            f"A zero gate means the journey has no deposit step, so this is the "
            f"wrong recipe — it would still build the deposit node, and the "
            f"reference's entry activity with it.\n"
            f"  Use a MODE 5 chain spec with only the activities you want.")


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
        # null is not "leave it alone" — apply_values would write None into the
        # journey. A planner emitting `"promocode": null` meant "no promocode",
        # but the result is a null promocode field, and the reference's own
        # promocode survives everywhere it is duplicated.
        if raw is None:
            bad.append(f"{kname} = null. Omit the knob entirely if it does not "
                       f"apply; null is written into the journey as-is")
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


def _norm_name(s) -> str:
    """Loose key for game-name matching: 'Big Bass Bonanza 1000' -> 'bigbassbonanza1000'."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _games_by_name() -> dict:
    """Every way a brief might name a game -> its lobbyGameId.

    Indexes the id itself, the display name and every alias. This is what lets a
    spec say "Big Bass Bonanza 1000" instead of an opaque id: with ~4,900 games
    the registry can no longer be inlined into the prompt, so the model names the
    game in plain language and the composer does the lookup."""
    if not hasattr(_games_by_name, "_cache"):
        idx: dict[str, str] = {}
        for lobby_id, entry in _games_registry().items():
            for key in (lobby_id, entry.get("gameTranslationKey"), *(entry.get("aliases") or [])):
                if key:
                    idx.setdefault(_norm_name(key), lobby_id)
        _games_by_name._cache = idx
    return _games_by_name._cache


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
    # A game may be named rather than identified. Resolve the lobby knob first —
    # every other game field is then derived from that registry row below, so a
    # spec only ever has to get ONE of them right.
    lobby_knob_early = next((k for k, f in fields.items() if f == "lobbyGameId"), None)
    if lobby_knob_early and lobby_knob_early in given:
        raw_value = given[lobby_knob_early]
        if raw_value not in games:
            resolved = _games_by_name().get(_norm_name(raw_value))
            if resolved:
                knobs[lobby_knob_early] = resolved
                given[lobby_knob_early] = resolved

    valid = {f: {e.get(f) for e in games.values() if e.get(f)} for f in GAME_FIELDS}
    bad = []
    for kname, value in given.items():
        field_name = fields[kname]
        # Non-lobby fields are coerced from the lobby row further down, so a
        # mismatch there is not an error worth reporting.
        if field_name != "lobbyGameId" and lobby_knob_early in given and given[lobby_knob_early] in games:
            continue
        if value not in valid[field_name]:
            if field_name == "lobbyGameId":
                # Suggest by display NAME, which is what a brief actually says.
                names = {e.get("gameTranslationKey") or k: k for k, e in games.items()}
                near = difflib.get_close_matches(str(value), sorted(names), n=3, cutoff=0.5)
                if not near and len(str(value)) >= 4:
                    q = _norm_name(value)
                    near = [n for n in sorted(names) if q in _norm_name(n)][:3]
            else:
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
    # lobbyGameId is the registry's primary key, so when the other fields
    # disagree with it the spec is COERCED to that row rather than refused: a
    # mixed tuple is never intentional (it comes from the model pattern-matching
    # two similarly-named titles), and the registry is the authoritative answer
    # for what the rest of the tuple must be. Refusing here just bounced a spec
    # whose correct form was already fully determined.
    lobby_knob = next((k for k, f in fields.items() if f == "lobbyGameId"), None)
    lobby = given.get(lobby_knob)
    entry = games.get(lobby) if lobby else None
    if entry:
        # Fill EVERY game field from the lobby row, whether or not the spec sent
        # it. Only correcting supplied values left the omitted ones at the
        # reference template's game — a spec naming a 3oaks title shipped its
        # lobby id beside Sweet Bonanza's wallet id and provider.
        for kname, field_name in fields.items():
            if field_name == "lobbyGameId":
                continue
            correct = entry.get(field_name)
            if correct and knobs.get(kname) != correct:
                knobs[kname] = correct


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
            f"{sorted(recipe.knobs) or '(none — this recipe takes no values)'}.\n"
            f"  Wanting a knob this recipe lacks means the recipe does not fit "
            f"the brief. Re-emit as a MODE 5 chain spec, which can set these on "
            f"the individual activities.")
    missing = [k for k, v in recipe.knobs.items() if v.required and k not in knobs]
    if missing:
        raise SpecError(
            f"spec omits {len(missing)} required knob(s) for recipe "
            f"{recipe.key!r}: {missing}. Without them the journey ships "
            f"{recipe.reference}'s own values (real production content). "
            f"Resolve each from the games registry and re-emit the spec.")
    _check_recipe_fit(recipe, knobs)
    _check_ranges(recipe, knobs)
    _check_games(recipe, knobs)
    return recipe


# The ids that IDENTIFY a promotion and its promo-page content tree. Sharing one
# with the reference is a different, worse failure than sharing copy: the two
# campaigns become the same object server-side, so editing this draft's artwork
# or terms rewrites the CAPTURED campaign — which is a live weekly promo. This is
# the same class as the Sport WOF bug, where every wheel shared one contentId and
# editing this week's rewrote every published one.
#
# They are missed by audit_inherited_content because _is_content() only accepts
# uppercase-leading tokens (built for copy and CSE-* ids), so a lowercase uuid
# sails straight through it.
IDENTITY_KEYS = ("ContentId", "FrontId", "campaignId",
                 "promotionId", "promotionLinkId",
                 # The editor mirror repeats the content pair under
                 # config.metadata in camelCase. Missing these left the minted
                 # draft still pointing at the captured campaign's tree through
                 # the mirror, which is the copy the builder reads.
                 "contentId", "frontId")


def audit_shared_promotion_identity(body: dict, reference: dict) -> list[str]:
    """Promotion/content ids the composed journey still SHARES with its reference.

    Returns one line per shared id. Empty means this draft owns its own
    promotion and content tree.
    """
    def collect(obj, out: dict, path: str = "") -> dict:
        if isinstance(obj, dict):
            for k, v in obj.items():
                here = f"{path}.{k}" if path else k
                if k in IDENTITY_KEYS and isinstance(v, str) and v.strip():
                    out.setdefault((k, v), here)
                else:
                    collect(v, out, here)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                collect(v, out, f"{path}[{i}]")
        return out

    ref_ids = {kv[0] + "\x00" + kv[1] for kv in collect(reference, {})}
    if not ref_ids:
        return []
    leaks: list[str] = []
    for (key, val), where in sorted(collect(body, {}).items(), key=lambda kv: kv[1]):
        if key + "\x00" + val in ref_ids:
            leaks.append(f"{where} = {key} {val} (same object as the reference)")
    return leaks


def refresh_promotion_identity(body: dict, reference: dict) -> list[str]:
    """Give this draft its OWN promotion + content ids instead of the capture's.

    A cloned promotion node arrives carrying the captured campaign's
    promotionId / promotionLinkId / campaignId and its promo-page
    ContentId+FrontId. Those are not copies, they are the SAME server-side
    objects: the draft hangs off the captured campaign's promotion, and editing
    its promo-page content rewrites that live campaign's page. This is the Sport
    WOF bug — every wheel shared one contentId, so editing this week's artwork
    rewrote every published wheel — and the fix there is the fix here: mint a
    fresh uuid per draft.

    Rewrites consistently: one old id maps to ONE new id everywhere it appears,
    so the compiled activities and the rawJourneyData mirror keep agreeing
    (disagreement is a blank canvas).

    Only ids the draft SHARES with its reference are touched — an id the
    operator supplied is theirs and is left alone. Returns a report line per id.
    """
    shared: set[str] = set()

    def collect(obj, out: set) -> set:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in IDENTITY_KEYS and isinstance(v, str) and v.strip():
                    out.add(v)
                else:
                    collect(v, out)
        elif isinstance(obj, list):
            for v in obj:
                collect(v, out)
        return out

    ref_ids = collect(reference, set())
    body_ids = collect(body, set())
    shared = body_ids & ref_ids
    if not shared:
        return []
    mapping = {old: str(uuid.uuid4()) for old in sorted(shared)}
    text = json.dumps(body)
    for old, new in mapping.items():
        text = text.replace(old, new)
    body.clear()
    body.update(json.loads(text))
    lines = [f"promotion identity {old} -> {new} (was the reference's own object)"
             for old, new in mapping.items()]
    # A minted ContentId/FrontId owns no content tree, so the offer card renders
    # empty. That must not be a quiet line in a long report — it is the
    # difference between a shippable journey and one the player sees nothing in.
    content_minted = [new for old, new in mapping.items()
                      if _id_key_of(reference, old) in ("ContentId", "FrontId")]
    if content_minted:
        lines.append(
            "INCOMPLETE — the promo page: this draft now owns fresh "
            "ContentId/FrontId, which removes the damage of sharing the "
            "captured campaign's page, but a fresh id has NO content tree "
            "behind it, so the offer card will render EMPTY. Build the promo "
            "page with gow_campaign.py (Optimization > GOW), then pass its ids "
            "as the promotion node's content_id / front_id so this journey "
            "points at real content instead of a minted blank.")
    return lines


def _id_key_of(reference: dict, value: str) -> str:
    """Which IDENTITY_KEYS field held `value` in the reference."""
    found = ""

    def walk(o):
        nonlocal found
        if found:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                if k in IDENTITY_KEYS and v == value:
                    found = k
                    return
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(reference)
    return found


def _refuse_inherited(body: dict, reference: str) -> None:
    """Refuse a spec-built journey that still carries its reference's campaign.

    Deliberately NOT applied to `python compose.py <recipe>` with no spec —
    that path exists to clone a reference as-is. A spec, by contrast, describes
    a NEW campaign, and a new campaign that shares the old one's SMS body,
    email template or promo link is the failure this whole gate exists for.
    """
    ref_body = _load(reference)
    shared_ids = audit_shared_promotion_identity(body, ref_body)
    if shared_ids:
        shown = "\n    ".join(shared_ids[:8])
        more = (f"\n    ...and {len(shared_ids) - 8} more"
                if len(shared_ids) > 8 else "")
        raise SpecError(
            f"the composed journey SHARES {len(shared_ids)} promotion/content id(s) "
            f"with {reference} — refusing to build:\n    {shown}{more}\n"
            f"  These are not copies, they are the SAME server-side objects. The "
            f"draft would hang off the captured campaign's promotion, and editing "
            f"its promo-page content would rewrite that live campaign's page.\n"
            f"  A new campaign needs its own promotion + content tree. If reusing "
            f"that exact captured campaign really is the intent, run the recipe "
            f"with no --spec — the bare-clone path is allowed to share, because "
            f"cloning is what it is for.")
    leaks = audit_inherited_content(body, ref_body)
    if not leaks:
        return
    shown = "\n    ".join(leaks[:8])
    more = f"\n    ...and {len(leaks) - 8} more" if len(leaks) > 8 else ""
    raise SpecError(
        f"the composed journey still carries {len(leaks)} piece(s) of "
        f"{reference}'s own campaign content — it would message real players "
        f"with the wrong copy and the wrong links:\n    {shown}{more}\n"
        f"  Set this content explicitly, or build a chain (MODE 5) containing "
        f"only the activities you actually want.")


def sync_game_labels(body: dict) -> list[str]:
    """Make the human-facing game labels match the game actually being granted.

    `gameTranslationKey` / `providerTranslationKey` are display-only, so nothing
    validated them and no knob wrote them: a journey granting spins on La Gran
    Copa went out advertising the reference template's "Sweet Bonanza Super
    Scatter / Pragmatic Play" on the activity card and the promo-lobby card. The
    ids were right, the labels lied — which is exactly what an operator reviewing
    the draft reads. The registry row for the lobby id is the authority.
    """
    games = _games_registry()
    if not games:
        return []
    log: list[str] = []

    def pretty(provider_id: str) -> str:
        return " ".join(w.capitalize() for w in re.split(r"[-_]+", provider_id or "") if w)

    def walk(obj):
        if isinstance(obj, dict):
            lobby = obj.get("lobbyGameId")
            entry = games.get(lobby) if isinstance(lobby, str) else None
            if entry:
                game_name = entry.get("gameTranslationKey")
                provider_name = (entry.get("providerTranslationKey")
                                 or pretty(entry.get("provider", "")))
                if game_name and obj.get("gameTranslationKey") != game_name:
                    log.append(f"label: gameTranslationKey {obj.get('gameTranslationKey')!r} "
                               f"-> {game_name!r}")
                    obj["gameTranslationKey"] = game_name
                if provider_name and obj.get("providerTranslationKey") != provider_name:
                    obj["providerTranslationKey"] = provider_name
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(body)

    # The activity card title is a separate label ("<provider> | <game>") that is
    # not derived from the wire fields, so it needs the same treatment.
    freespin_ids = {a.get("activityId") for a in body.get("activities", [])
                    if a.get("activityName") == "freespin_bonus"}
    label = None
    for activity in body.get("activities", []):
        if activity.get("activityId") not in freespin_ids:
            continue
        fa = (activity.get("initializationData") or {}).get("freespinActivity") or {}
        if fa.get("gameTranslationKey"):
            label = f"{fa.get('providerTranslationKey') or ''} | {fa['gameTranslationKey']}".strip(" |")
            activity["activityDisplayName"] = label
    if label:
        config = (body.get("rawJourneyData") or {}).get("activitiesConfiguration") or {}
        for activity_id, cfg in config.items():
            if activity_id in freespin_ids and isinstance(cfg, dict) and "displayName" in cfg:
                cfg["displayName"] = label
        log.append(f"label: freespin activity card -> {label!r}")
    return log


def compose_from_spec(spec: dict) -> tuple[Recipe, dict, str, list[str]]:
    recipe = validate_spec(spec)
    values, unknown = spec_to_values(recipe, spec)
    body, name, _ = compose(recipe, values)
    sync_game_labels(body)
    # Give the draft its own promotion + content ids BEFORE auditing, so a new
    # campaign never hangs off the captured one's promotion. _refuse_inherited
    # stays as the backstop for anything this does not reach.
    refresh_promotion_identity(body, _load(recipe.reference))
    _refuse_inherited(body, recipe.reference)
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
    # A graph describes a NEW campaign too, so it must not hang off the
    # reference's promotion either.
    refresh_promotion_identity(body, _load(ref))
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
        "_doc": "For journeys no recipe covers. Activities may repeat, branch, or "
                "use a choosable flow. `inline_keys` lists the keys that go "
                "DIRECTLY on the node object — {\"type\": \"freespins\", "
                "\"spins\": 30} — never wrapped in a nested \"settings\" object. "
                "`game` accepts any name/id/alias from the games registry and "
                "sets the whole id tuple; unknown names are REFUSED, never "
                "guessed. Build with `journey_composer.py compose <file> --script`.",
        "sources": opts.get("sources", {}),
        # Named `inline_keys`, not `settings`: a key called "settings" primes the
        # model to emit {"type": x, "settings": {...}}, which the composer
        # refuses. Observed repeatedly in live runs and not fixed by prompt
        # instruction — the field name itself was the cue.
        "activities": {
            k: {"aliases": v.get("aliases", []),
                "follow": v.get("default_follow"),
                "inline_keys": sorted(v.get("settings", {}))}
            for k, v in (opts.get("chain_types") or {}).items()
        },
        "spec_shape": opts.get("spec_shape", {}),
    }


def _randomizer_palette() -> dict:
    """The randomizer builder's palette, for the prompt.

    Wheels and scratch cards are NOT journeys — randomizer_campaign.py builds
    them against captured templates. The planner had no idea it existed, so any
    brief with a wheel dead-ended at "⛔ build it in the UI" even though weights
    and prize routing are both overridable. Prize COUNT is fixed per template
    (the slices come from the capture), which is why the count is published:
    a spec must supply exactly that many weights and journeys, in order.
    """
    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import randomizer_campaign as rc
    except Exception:
        return {}
    kinds: dict = {}
    for key, cfg in (getattr(rc, "KINDS", {}) or {}).items():
        entry = {"label": cfg.get("label"), "days_default": cfg.get("days_default")}
        tpl = cfg.get("template")
        try:
            prizes = json.loads(Path(tpl).read_text(encoding="utf-8")).get("prizes") or []
            entry["prize_count"] = len(prizes)
            entry["template_weights"] = [p.get("weight") for p in prizes]
        except Exception:
            entry["prize_count"] = None
        kinds[key] = entry
    if not kinds:
        return {}
    return {
        "_doc": "Fortune wheels and scratch cards. NOT journeys — build with "
                "`python journey-cloner/randomizer_campaign.py --kind <kind> "
                "--date <YYYY-MM-DD> [--weights ...] [--journeys ...]`. "
                "The prize SLICES come from the captured template and cannot be "
                "added or removed, so `weights` and `journeys` must each have "
                "exactly prize_count entries, in template order. Weights must "
                "sum to 100. Each prize routes a winner to a journey, so build "
                "the journeys FIRST and pass their JRN ids.",
        "kinds": kinds,
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
        # Only recipes a spec can legitimately build are advertised. A recipe
        # with no knobs can ONLY reproduce its reference verbatim, so every
        # spec-driven use of it ships another campaign's content — validate_spec
        # refuses them, and listing them anyway just invites the model to pick
        # one and get refused. Telling it "do not use comms" in prose did not
        # work; not offering comms does.
        "recipes": {
            k: {
                "reference": r.reference,
                "chain": [n.activity for n in r.chain] + [r.terminal],
                "knobs": {kn: _knob_doc(v) for kn, v in r.knobs.items()},
            } for k, r in RECIPES.items() if r.knobs
        },
        "references": _reference_index(),
        "chain_composer": _chain_palette(),
        "randomizer": _randomizer_palette(),
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


BATCH_JS_TEMPLATE = r'''// Composed CAMPAIGN — @COUNT@ journeys, generated @GENERATED_AT@
@MANIFEST@//
// Paste ONCE into a logged-in Journey Builder backoffice console (F12). It
// captures the token once, then reserves an id and POSTs a draft for each
// journey in order, pausing between them. A failure stops the run and reports
// which journeys were already created, so a re-run can start from there.
(async () => {
  const BASE = @BASE@;
  const BRAND = @BRAND@;
  const BODIES = @BODIES@;          // [{name, body}, ...] in creation order
  const PAUSE_MS = 600;             // be kind to the backoffice between POSTs

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
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const newUuid=()=> (crypto&&crypto.randomUUID)? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,(c)=>{ const r=(Math.random()*16)|0; return (c==='x'?r:(r&0x3)|0x8).toString(16); });
  const UUID_RE=/"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  // Regenerated PER JOURNEY: two drafts sharing an activityId would collide.
  const regen=(txt)=>{ const olds=new Set(); let m; UUID_RE.lastIndex=0; while((m=UUID_RE.exec(txt))!==null) olds.add(m[1]); let t=txt; for(const o of olds) t=t.split(o).join(newUuid()); return t; };

  async function reserveId(){
    const r=await fetch(BASE+'/journeys/identifier',{ method:'POST', headers:headers('application/x-www-form-urlencoded'), credentials:'include' });
    const raw=(await r.text()).trim(); let id=raw.replace(/^"+|"+$/g,'');
    try{ const d=JSON.parse(raw); if(typeof d==='string') id=d.trim(); else if(d&&typeof d==='object') id=String(d.identifier||d.journeyId||d.id||d.value||'').trim(); }catch(e){}
    if(!r.ok||!id.startsWith('JRN-')) throw new Error('reserve failed HTTP '+r.status+' '+raw);
    return id;
  }

  const created = [];
  console.log('%cCreating '+BODIES.length+' journeys...','color:#60a5fa;font-weight:bold');
  for (let i = 0; i < BODIES.length; i++) {
    const item = BODIES[i];
    const label = `[${i+1}/${BODIES.length}] ${item.name}`;
    try {
      const rid = await reserveId();
      let text = JSON.stringify(item.body).split('DRY-RUN-JOURNEY').join(rid);
      text = regen(text);
      const body = JSON.parse(text);
      const r = await fetch(BASE+'/journey-drafts',{ method:'POST', headers:headers('application/json'), credentials:'include', body:JSON.stringify(body) });
      const respText = await r.text();
      if(!r.ok){
        console.error('%c'+label+' FAILED HTTP '+r.status,'color:#ef4444;font-weight:bold', respText);
        console.log('%cStopped. Already created: '+(created.map(c=>c.id).join(', ')||'none'),'color:#eab308');
        console.log('Fix the cause, then re-run with the first '+created.length+' entries removed from BODIES.');
        window.__createdJourneys = created;
        return;
      }
      created.push({ id: rid, name: item.name });
      console.log('%c'+label+' -> '+rid,'color:#22c55e');
    } catch (e) {
      console.error('%c'+label+' ERROR','color:#ef4444;font-weight:bold', e.message);
      console.log('%cStopped. Already created: '+(created.map(c=>c.id).join(', ')||'none'),'color:#eab308');
      window.__createdJourneys = created;
      return;
    }
    if (i < BODIES.length - 1) await sleep(PAUSE_MS);
  }
  console.log('%cALL '+created.length+' DRAFTS CREATED','color:#22c55e;font-weight:bold');
  console.table(created);
  // Wheel prizes route to journeys by id, so this mapping is what you feed the
  // randomizer spec's `journeys` list.
  console.log('journeyIds in order:', created.map(c=>c.id));
  window.__createdJourneys = created;

  // ── the wheel / scratch card ──────────────────────────────────────────────
  // A promotion is the journeys AND the object that routes players into them.
  // The routing needs ids that only exist once the journeys are created, which
  // is why this runs here rather than in a second paste: each prize names the
  // journey it routes to and that name is resolved against what was just made.
  const RANDOMIZERS = @RANDOMIZERS@;   // [] when the campaign has no wheel
  if (RANDOMIZERS.length) {
    const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');
    const byName = new Map(created.map(c => [c.name, c.id]));
    const rok = [], rfail = [];
    console.log('%cCreating '+RANDOMIZERS.length+' randomizer(s)...','color:#60a5fa;font-weight:bold');
    for (const R of RANDOMIZERS) {
      try {
        // Each prize routes to a journey by NAME (created above) or by a literal
        // JRN id (a wheel pointing at journeys that already exist).
        const unresolved = [];
        const ids = (R.prizeJourneys || []).map((ref) => {
          if (/^JRN-/.test(String(ref))) return ref;
          const hit = byName.get(ref);
          if (!hit) unresolved.push(ref);
          return hit;
        });
        if (unresolved.length) throw new Error('prize routes to journeys not created here: '+unresolved.join(', '));
        const payload = JSON.parse(JSON.stringify(R.body));
        const prizes = payload.prizes || [];
        if (ids.length && ids.length !== prizes.length) throw new Error('template has '+prizes.length+' prize slices but '+ids.length+' journeys were given');
        ids.forEach((jid, i) => { (prizes[i].journeyPrizeSettings = prizes[i].journeyPrizeSettings || {}).journeyId = jid; });

        let r = await fetch(CRM_BASE+'/promo/v2/promo-drafts/randomizer',{ method:'POST', headers:headers('application/json'), credentials:'include', body:JSON.stringify(payload) });
        let resp = await r.text();
        if(!r.ok) throw new Error('create HTTP '+r.status+' '+resp);
        let cr = {}; try { cr = JSON.parse(resp); } catch(e){}
        const rid = cr.id || cr.draftId || cr.promotionDraftId || (cr.data && cr.data.id);
        if(!rid) throw new Error('no draft id in create response: '+resp);
        // Fill the draft — same two-step the standalone randomizer script uses.
        if (R.flow === 'create_put') {
          r = await fetch(CRM_BASE+'/promo/v2/randomizer/'+encodeURIComponent(rid),{ method:'PUT', headers:headers('application/json'), credentials:'include', body:JSON.stringify({ ...payload, id:String(rid) }) });
        } else {
          r = await fetch(CRM_BASE+'/promo/v2/randomizer?draftId='+encodeURIComponent(rid),{ method:'POST', headers:headers('application/json'), credentials:'include', body:JSON.stringify(payload) });
        }
        resp = await r.text();
        if(!r.ok) throw new Error('draft '+rid+' created but fill failed HTTP '+r.status+' '+resp);
        rok.push({ name: R.internalName, id: rid });
        console.log('%c  ✓ '+R.internalName+' -> '+rid,'color:#22c55e');
      } catch (e) {
        const msg = String((e && e.message) || e);
        rfail.push({ name: R.internalName, err: msg });
        console.error('  ✗ '+R.internalName+' — '+msg);
      }
      await sleep(PAUSE_MS);
    }
    console.log('%cRANDOMIZERS — '+rok.length+' created, '+rfail.length+' failed.',
                'color:'+(rfail.length?'#f59e0b':'#22c55e')+';font-weight:bold');
    window.__createdRandomizers = rok;
  }
  console.log('%cCAMPAIGN DONE','color:#22c55e;font-weight:bold;font-size:14px');
})();
'''


def prepare_randomizers(spec: dict) -> list[dict]:
    """A MODE 6 randomizer spec -> payload(s) the campaign script can create.

    The prize->journey routing is deliberately NOT baked in here: the journeys do
    not exist yet. Each prize carries the NAME of the journey it routes to and
    the script resolves it against what it just created (a literal JRN id passes
    through, for a wheel pointed at journeys that already exist).
    """
    try:
        import randomizer_campaign as RC          # same directory
    except ImportError as exc:                    # pragma: no cover
        raise SpecError(f"randomizer builder unavailable: {exc}")

    kind = str(spec.get("kind") or "").strip()
    if kind not in RC.KINDS:
        raise SpecError(f"unknown randomizer kind {kind!r} — known: {list(RC.KINDS)}")
    dates = spec.get("dates") or ([spec["date"]] if spec.get("date") else [])
    if not dates:
        raise SpecError("randomizer spec needs `date` or `dates`")

    routes = [str(j).strip() for j in (spec.get("journeys") or []) if str(j).strip()]
    if not routes:
        raise SpecError(
            "randomizer spec has no `journeys` — every prize must name the journey "
            "it routes to (by journey_name, or a literal JRN id). Without it the "
            "wheel would keep the captured template's own prize routing.")
    if any("XXXX" in r or "⛔" in r for r in routes):
        raise SpecError(
            f"randomizer `journeys` still contains placeholders ({routes}) — use the "
            f"journey_name of each prize's journey; the script fills in the real id.")

    weights = [str(w) for w in (spec.get("weights") or [])] or None

    # Check the slice count HERE: prepare() raises about "--weights", a CLI flag
    # that means nothing to someone who pressed a button in the chat.
    def slices_of(k: str) -> int:
        try:
            return len(json.loads(RC.KINDS[k]["template"].read_text(encoding="utf-8"))
                       .get("prizes") or [])
        except (OSError, ValueError):
            return 0

    slices = slices_of(kind)
    for label, given in (("weights", weights), ("journeys", routes)):
        if given and slices and len(given) != slices:
            kinds = ", ".join(f"{k} ({slices_of(k)} slices)" for k in RC.KINDS)
            raise SpecError(
                f"{kind} is a captured wheel with {slices} prize slices, but "
                f"`{label}` lists {len(given)} — slices cannot be added or removed. "
                f"Plan {slices} prizes (including the empty one), or capture a "
                f"{len(given)}-slice wheel first. Available: {kinds}.")
    out = []
    for date_str in dates:
        try:
            body, _report = RC.prepare(
                kind, str(date_str), days=spec.get("days"),
                internal_name=str(spec.get("internal_name") or ""),
                url_short=str(spec.get("url_short") or ""),
                weights=weights, journeys=None)   # routing wired at run time
        except SystemExit as exc:                 # prepare() exits on bad counts
            raise SpecError(str(exc))
        prizes = body.get("prizes") or []
        if len(routes) != len(prizes):
            raise SpecError(
                f"{kind} has {len(prizes)} prize slices but `journeys` lists "
                f"{len(routes)} — the slices come from the captured template and "
                f"cannot be added or removed.")
        out.append({"internalName": body.get("internalName"),
                    "flow": RC.KINDS[kind]["flow"],
                    "body": body, "prizeJourneys": routes})
    return out


def emit_batch(items: list[tuple[str, dict]], basename: str,
               brand: str = DEFAULT_BRAND,
               randomizers: list[dict] | None = None) -> Path:
    """One console script that creates MANY journeys from a single paste.

    A campaign is a dozen-plus journeys, and one script per journey means one
    token capture and one paste each. This captures once and loops, stopping at
    the first failure with the ids already created so a re-run can resume. It
    also prints the created ids in order, which is exactly the list a wheel's
    `journeys` routing needs.

    `randomizers` makes it the WHOLE promotion in one paste: each entry is
    {internalName, flow, body, prizeJourneys}, where prizeJourneys names the
    journey each prize slice routes to. Those names are resolved to the ids
    created moments earlier in the same run — the reason this cannot simply be a
    second script is that the ids do not exist until the first one has run.
    """
    manifest = "".join(f"//   {i + 1}. {name}\n" for i, (name, _) in enumerate(items))
    for r in randomizers or []:
        manifest += f"//   + randomizer: {r.get('internalName', '?')}\n"
    js = (BATCH_JS_TEMPLATE
          .replace("@GENERATED_AT@", datetime.datetime.utcnow().isoformat() + "Z")
          .replace("@COUNT@", str(len(items)))
          .replace("@MANIFEST@", manifest)
          .replace("@BASE@", json.dumps(BASE_URL))
          .replace("@BRAND@", json.dumps(brand))
          .replace("@RANDOMIZERS@", json.dumps(randomizers or [], ensure_ascii=False))
          .replace("@BODIES@", json.dumps(
              [{"name": n, "body": b} for n, b in items], ensure_ascii=False)))
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{basename}_console.js"
    out.write_text(js, encoding="utf-8")
    return out


def emit(recipe: Recipe, body: dict, name: str, basename: str | None = None) -> Path:
    js = (JS_TEMPLATE
          .replace("@GENERATED_AT@", datetime.datetime.utcnow().isoformat() + "Z")
          .replace("@RECIPE@", recipe.key)
          .replace("@NAME@", name)
          .replace("@BASE@", json.dumps(BASE_URL))
          .replace("@BRAND@", json.dumps(recipe.brand))
          .replace("@BODY@", json.dumps(body, ensure_ascii=False)))
    OUT.mkdir(parents=True, exist_ok=True)
    # Default filename is per-recipe, so two runs of the same recipe overwrite
    # each other. Callers that need a stable, unique artifact (the backoffice
    # runner, which looks for "<basename>_console.js") pass their own basename.
    stem = basename or f"composed_{recipe.key}"
    out = OUT / f"{stem}_console.js"
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

    # --name <basename>: control the emitted filename. The backoffice runner
    # needs a unique, predictable artifact per run; the default per-recipe name
    # would have concurrent runs overwriting each other.
    basename = None
    if "--name" in args:
        i = args.index("--name")
        if i + 1 >= len(args):
            print("--name needs a value")
            return 2
        basename = args[i + 1]
        args = args[:i] + args[i + 2:]

    # --batch: many specs -> ONE console script. A campaign is a dozen journeys,
    # and one script each means one token capture and one paste each. With a
    # `randomizer` alongside them it is the WHOLE promotion in one paste.
    if args[0] == "--batch":
        raw = (Path(args[1]).read_text(encoding="utf-8") if len(args) > 1
               else sys.stdin.read())
        try:
            payload = _extract_json_any(raw)
        except SpecError as exc:
            print(f"⛔ REFUSED — {exc}")
            return 3
        specs = payload if isinstance(payload, list) else (
            payload.get("journeys") or payload.get("specs") or [payload])
        if not isinstance(specs, list) or not specs:
            print("⛔ REFUSED — --batch wants a JSON array of specs, or "
                  "{\"journeys\": [ ... ]}.")
            return 3
        items, failures = [], []
        for i, spec in enumerate(specs, 1):
            label = (spec or {}).get("journey_name") or f"object {i}"
            try:
                recipe, body, name, _ = compose_from_spec(spec)
            except SpecError as exc:
                failures.append(f"{i}. {label}: {str(exc).splitlines()[0]}")
                continue
            bad = [m for good, m in verify(body) if not good]
            if bad:
                failures.append(f"{i}. {label}: verification failed — {'; '.join(bad)}")
                continue
            items.append((name, body))
            print(f"  [{i}/{len(specs)}] {name}: {len(body['activities'])} activities OK")
        if not items:
            for f in failures:
                print(f"  ⛔ {f}")
            print("\nNothing composed — not emitting.")
            return 3

        # The wheel/scratch card that routes players into those journeys. It goes
        # in the SAME script because its prize routing needs ids that only exist
        # after the journeys above have been created.
        randomizers = []
        rspec = payload.get("randomizer") if isinstance(payload, dict) else None
        if isinstance(rspec, dict):
            try:
                randomizers = prepare_randomizers(rspec)
                for r in randomizers:
                    print(f"  + randomizer {r['internalName']}: "
                          f"{len(r['body'].get('prizes') or [])} prize slice(s) -> "
                          f"{', '.join(r['prizeJourneys'])}")
            except SpecError as exc:
                failures.append(f"randomizer: {exc}")
                print(f"  ⛔ randomizer: {exc}")

        out = emit_batch(items, basename or "composed_campaign", randomizers=randomizers)

        # The summary goes LAST because that is what a reader sees first when a
        # long build scrolls past: exactly what the script will create, and
        # exactly what it will not.
        extra = f" + {len(randomizers)} randomizer(s)" if randomizers else ""
        print(f"\n══ IN THE SCRIPT: {len(items)} journey(s){extra} ══")
        for name, _ in items:
            print(f"  ✓ {name}")
        for r in randomizers:
            print(f"  ✓ randomizer {r['internalName']}")
        if failures:
            print(f"\n══ NOT BUILT: {len(failures)} ══")
            for f in failures:
                print(f"  ⛔ {f}")
        print(f"\n{len(items)}/{len(specs)} composed{extra}. Console script: {out}")
        # Exit 4 = partial, so a caller can tell "all good" from "some missing".
        return 0 if not failures else 4

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
    out = emit(recipe, body, name, basename)
    print(f"\nAll checks passed. Console script: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
