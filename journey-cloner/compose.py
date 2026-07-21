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
    """A named, LLM-facing value → a real dotted path on one activity. Paths are
    validated against the recipe's OWN reference journey (they vary per journey)."""
    activity: str
    path: str
    unit: str = "raw"                 # raw | minor  (minor: major CLP × 100)
    desc: str = ""


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
                "minor", "minimum deposit to unlock the offer, in CLP"),
            "freebet_amount_clp": Knob(
                "freebet", "initializationData.properties.freeBetAmount.CLP",
                "minor", "free-bet value in CLP"),
            "freebet_expire_days": Knob(
                "freebet", "initializationData.properties.expireInDays",
                "raw", "days the free bet stays valid"),
            "freebet_max_odd": Knob(
                "freebet", "initializationData.properties.maxOdd",
                "raw", "maximum odds the free bet can be used at"),
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
                "minor", "minimum deposit to unlock, in CLP"),
            "spins": Knob(
                "freespin_bonus", "initializationData.freespinActivity.spins",
                "raw", "number of free spins granted"),
            "spin_bet_clp": Knob(
                "freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.betAmount",
                "minor", "bet value per spin, in CLP"),
            "bonus_percent": Knob(
                "casino_bonus_v2", "initializationData.bonusPercent",
                "raw", "deposit-match percent (100 = 100%)"),
            "wagering_x": Knob(
                "casino_bonus_v2", "initializationData.wageringRequirement",
                "raw", "wagering multiplier (e.g. 30 = x30)"),
            "bonus_expiry_ms": Knob(
                "casino_bonus_v2", "initializationData.bonusExpirationTime",
                "raw", "bonus validity in milliseconds (172800000 = 48h)"),
            "release_limit_x": Knob(
                "casino_bonus_v2", "initializationData.releaseLimitMultiplier",
                "raw", "max cashout as a multiple of the bonus"),
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
    apply_values(shell, values)
    fix_dates(shell)
    return shell, name, chain_ids


def spec_to_values(recipe: Recipe, spec: dict) -> tuple[dict, list[str]]:
    """Translate an LLM spec {recipe, journey_name, knobs:{name:value}} into the
    generic values dict compose() takes. Returns (values, unknown_knob_names).
    Unit-converts CLP majors to minor units. Unknown knobs are refused, not
    guessed (assembler discipline)."""
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
        val = int(round(raw * 100)) if knob.unit == "minor" else raw
        sets.setdefault(knob.activity, {})[knob.path] = val
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


def validate_spec(spec: dict) -> Recipe:
    """Refuse a spec the composer must not build. Two hard gates:
      1. `recipe` must be one of the PROVEN recipes — no remap to the nearest.
      2. NO ⛔ / RESOLVE_AT_BUILD_TIME / UNCAPTURED blocker anywhere in the spec.
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
    return recipe


def compose_from_spec(spec: dict) -> tuple[Recipe, dict, str, list[str]]:
    recipe = validate_spec(spec)
    values, unknown = spec_to_values(recipe, spec)
    body, name, _ = compose(recipe, values)
    return recipe, body, name, unknown


def catalog() -> dict:
    """Machine-readable recipe catalog for the planner LLM to emit specs against."""
    return {
        "recipes": {
            k: {
                "reference": r.reference,
                "chain": [n.activity for n in r.chain] + [r.terminal],
                "knobs": {kn: {"unit": v.unit, "desc": v.desc}
                          for kn, v in r.knobs.items()},
            } for k, r in RECIPES.items()
        }
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
    for aname, overrides in sets.items():
        act = by_name.get(aname)
        if not act:
            log.append(f"skip {aname}: not in journey")
            continue
        for path, v in overrides.items():
            ok = _dotted_set(act, path, v)
            log.append(f"{'set' if ok else 'MISS'} {aname}.{path} = {v!r}")
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
        print("       python compose.py --spec spec.json     (compose from an LLM spec)")
        print("       python compose.py --catalog            (write recipes_catalog.json)")
        return 0

    if args[0] == "--catalog":
        out = HERE / "recipes_catalog.json"
        out.write_text(json.dumps(catalog(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out}")
        return 0

    unknown_knobs = []
    if args[0] == "--spec":
        spec = json.load(open(args[1], encoding="utf-8")) if len(args) > 1 else json.load(sys.stdin)
        try:
            recipe, body, name, unknown_knobs = compose_from_spec(spec)
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
