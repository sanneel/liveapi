#!/usr/bin/env python3
"""Phase 3 — the campaign planner's gatekeeper.

Takes a compact, human-reviewable flow plan (a tiny text DSL the LLM emits) and
validates it against catalog.json BEFORE anyone approves it or a script is
generated. It catches the bugs an LLM would otherwise hallucinate: unknown
activity types, events an activity can't emit, transitions never seen in a real
journey, dangling/unreachable nodes, missing terminals, channels with no copy.

It does NOT build journey JSON — it only judges a plan. On approval, the
deterministic compilers (gow_*.py) do the building.

DSL (one statement per line; '#' comments and blank lines ignored):

    campaign: Win-back 50 free spins
    source: segment[301]                 # or  api[PromoPage]
    source.PlayerAdded -> deposit
    deposit.DepositConditionSatisfied -> promotion
    promotion.PromotionAccepted -> freespin_bonus(spins=50, game="Gates of Olympus")
    freespin_bonus.FreespinBonusCollectingFinished -> casino_bonus_v2(wager=30)
    NC1.NotificationSent -> SMS(text="...")
    SMS.SuccessSmsSend -> end

Friendly aliases: source, api, segment, NC1/notification, NC5/popup, SMS, EMAIL,
push, wait, deposit, promotion, freespin/freespin_bonus, bonus/casino_bonus_v2,
end/end_of_journey, endpath/end_of_path.

Run:  python plan_lint.py plan.flow      (or pipe the plan on stdin)
Exit code 0 = no errors (warnings allowed); 1 = errors / not approvable.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "catalog.json"

ALIASES = {
    "source": None,  # resolved from source: line
    "api": "external_system_source",
    "external_system_source": "external_system_source",
    "segment": "dwh_source",
    "dwh_source": "dwh_source",
    "nc1": "notification_center#contract1", "notification": "notification_center#contract1",
    "nc": "notification_center#contract1",
    "nc5": "notification_center#contract5", "popup": "notification_center#contract5",
    "sms": "dextra_sms", "dextra_sms": "dextra_sms",
    "email": "dextra_email", "dextra_email": "dextra_email",
    "push": "native_push", "native_push": "native_push",
    "wait": "wait_interval", "wait_interval": "wait_interval",
    "deposit": "deposit",
    "promotion": "promotion",
    "freespin": "freespin_bonus", "freespin_bonus": "freespin_bonus",
    "bonus": "casino_bonus_v2", "casino_bonus_v2": "casino_bonus_v2",
    "drip": "multipurpose_promotion", "multipurpose_promotion": "multipurpose_promotion",
    "end": "end_of_journey", "end_of_journey": "end_of_journey",
    "endpath": "end_of_path", "end_of_path": "end_of_path",
    "ncsplit": "notification_center_engagement_split",
    "emailsplit": "email_engagement_split",
    "event": "event_detector", "event_detector": "event_detector",
}
SOURCE_TYPES = {"dwh_source", "external_system_source"}
TERMINALS = {"end_of_journey", "end_of_path"}
CHANNELS = {"notification_center#contract1", "notification_center#contract5",
            "dextra_sms", "dextra_email", "native_push"}


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def resolve(tok: str, source_key: str | None) -> str | None:
    t = tok.strip().lower()
    if t == "source":
        return source_key
    return ALIASES.get(t, ALIASES.get(t, None)) or (tok if tok in _known_keys else None)


_known_keys: set = set()


def parse(text: str):
    name, source_key, edges, nodes = "", None, [], {}
    errors = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower().startswith("campaign:"):
            name = line.split(":", 1)[1].strip(); continue
        if line.lower().startswith("source:"):
            val = line.split(":", 1)[1].strip()
            m = re.match(r"(\w+)\[(.+)\]", val) or re.match(r"(\w+)", val)
            kind = (m.group(1).lower() if m else "")
            source_key = "dwh_source" if kind == "segment" else ("external_system_source" if kind in ("api", "external", "external_system_source") else None)
            if source_key is None:
                errors.append(f"unrecognized source kind {val!r} (use segment[...] or api[...])")
            nodes.setdefault(source_key, {})
            continue
        if "->" not in line:
            errors.append(f"cannot parse line: {raw.strip()!r}"); continue
        lhs, rhs = [s.strip() for s in line.split("->", 1)]
        # LHS = node[.Event]
        if "." in lhs:
            ln, ev = lhs.split(".", 1)
        else:
            ln, ev = lhs, ""
        # RHS = node[(knobs)]
        m = re.match(r"([\w#]+)\s*(?:\((.*)\))?$", rhs)
        if not m:
            errors.append(f"cannot parse target: {rhs!r}"); continue
        rn, knobstr = m.group(1), (m.group(2) or "")
        edges.append({"from_tok": ln, "event": ev.strip(), "to_tok": rn, "knobs": knobstr.strip(), "raw": raw.strip()})
        for tok in (ln, rn):
            nodes.setdefault(tok, {})
    return name, source_key, edges, nodes, errors


def lint(text: str) -> int:
    cat = load_catalog()
    global _known_keys
    acts = {a["key"]: a for a in cat["activities"]}
    _known_keys = set(acts)
    emits = {k: {re.sub(r"\s*\(.*\)$", "", e) for e in a["emits_events"]} for k, a in acts.items()}
    grammar = {(t["from"], t["on_event"], t["to"]) for t in cat["transitions_observed"]}

    name, source_key, edges, nodes, perrors = parse(text)
    errors, warns, oks = list(perrors), [], []

    if source_key is None:
        errors.append("no valid `source:` line (segment[...] or api[...])")

    targets = set()
    for e in edges:
        f = resolve(e["from_tok"], source_key)
        t = resolve(e["to_tok"], source_key)
        if f is None:
            errors.append(f"unknown activity {e['from_tok']!r}  [{e['raw']}]"); continue
        if t is None:
            errors.append(f"unknown activity {e['to_tok']!r}  [{e['raw']}]"); continue
        targets.add(t)
        ev = e["event"]
        # source activation event default
        if f in SOURCE_TYPES and not ev:
            ev = "PlayerAdded"
        if ev and ev not in emits.get(f, set()):
            errors.append(f"{f} does not emit event {ev!r} (emits: {sorted(emits.get(f,[]))})  [{e['raw']}]")
            continue
        if ev and (f, ev, t) not in grammar:
            warns.append(f"transition {f} --{ev}--> {t} never seen in a captured journey — verify it's legal  [{e['raw']}]")
        else:
            oks.append(f"{f} --{ev or '(activation)'}--> {t}")
        # channel copy knobs
        if t in CHANNELS and not e["knobs"]:
            warns.append(f"channel {t} has no copy knobs in the plan (title/text/etc.)  [{e['raw']}]")

    # reachability + terminals
    node_keys = {resolve(n, source_key) for n in nodes}
    node_keys.discard(None)
    for nk in node_keys:
        if nk in SOURCE_TYPES:
            continue
        if nk not in targets:
            warns.append(f"{nk} is never a target of any edge (unreachable / dangling)")
    if not (node_keys & TERMINALS):
        warns.append("no terminal node (end / end_of_path) in the plan")

    print(f"Plan: {name or '(unnamed)'}    source={source_key}    edges={len(edges)}")
    for m in oks:
        print(f"  OK    {m}")
    for m in warns:
        print(f"  WARN  {m}")
    for m in errors:
        print(f"  ERROR {m}")
    print(f"\n{'APPROVABLE (no errors)' if not errors else 'NOT APPROVABLE — fix errors above'}"
          f"  [{len(oks)} ok, {len(warns)} warn, {len(errors)} error]")
    return 1 if errors else 0


def main() -> int:
    text = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else sys.stdin.read()
    return lint(text)


if __name__ == "__main__":
    raise SystemExit(main())
