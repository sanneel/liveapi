#!/usr/bin/env python3
"""Mine the RULES and CONFIGS out of every captured journey template.

Reads every templates/**/*.json and, per journey, reconstructs the activity
graph from events[].nextActivityId, then emits:

  configs   — every activity type seen, its emitted events, and which templates
              contain it (the "what activities do we have" library)
  flows     — each journey's real flow pattern in first-visit order, e.g.
              external_system_source -> deposit -> promotion -> freespin_bonus
              (the "what wiring have we proven" rules library)
  transitions — deduped {from, on_event, to} edges (the connection rules)

Output: library/mined_catalog.json  (+ a printed summary)

This is pure extraction from files already on disk — no API, no capture.
"""
from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "library" / "mined_catalog.json"

SOURCE_TYPES = {
    "external_system_source", "dwh_source", "registration",
    "reference_code_source", "csv_source", "events_source",
}


def _body(t: dict) -> dict:
    return t.get("body", t)


def _index(acts: list) -> dict:
    return {a.get("activityId"): a for a in acts if a.get("activityId")}


def _entry(acts: list, by_id: dict) -> dict | None:
    """The entry node: a known source type, else any activity nobody points at."""
    targeted = set()
    for a in acts:
        for ev in a.get("events", []) or []:
            nx = ev.get("nextActivityId")
            if nx:
                targeted.add(nx)
    for a in acts:
        if a.get("activityName") in SOURCE_TYPES:
            return a
    for a in acts:
        if a.get("activityId") not in targeted:
            return a
    return acts[0] if acts else None


def _walk(entry: dict, by_id: dict) -> list[str]:
    """Activity-type sequence in first-visit order (BFS over Completion edges)."""
    order, seen, queue = [], set(), [entry.get("activityId")]
    while queue:
        aid = queue.pop(0)
        if not aid or aid in seen:
            continue
        seen.add(aid)
        a = by_id.get(aid)
        if not a:
            continue
        order.append(a.get("activityName", "?"))
        for ev in a.get("events", []) or []:
            nx = ev.get("nextActivityId")
            if nx and nx not in seen:
                queue.append(nx)
    return order


def mine() -> dict:
    configs: dict = defaultdict(lambda: {"count": 0, "templates": set(), "events": set()})
    flows: list = []
    transitions: set = set()

    for f in sorted(glob.glob(str(HERE / "templates" / "**" / "*.json"), recursive=True)):
        try:
            body = _body(json.load(open(f, encoding="utf-8")))
        except Exception:
            continue
        acts = body.get("activities") or []
        if not acts:
            continue
        by_id = _index(acts)
        rel = f.split("templates/")[-1]

        for a in acts:
            n = a.get("activityName")
            if not n:
                continue
            c = configs[n]
            c["count"] += 1
            c["templates"].add(rel)
            for ev in a.get("events", []) or []:
                en, et = ev.get("eventName"), ev.get("eventType", "")
                if en:
                    c["events"].add(f"{en} ({et})")
                nx = by_id.get(ev.get("nextActivityId"))
                if nx and en:
                    transitions.add((n, en, nx.get("activityName", "?")))

        entry = _entry(acts, by_id)
        flows.append({
            "template": rel,
            "journeyName": body.get("journeyName", ""),
            "entry": entry.get("activityName") if entry else None,
            "activity_count": len(acts),
            "flow": _walk(entry, by_id) if entry else [],
            "types": sorted({a.get("activityName") for a in acts if a.get("activityName")}),
        })

    return {
        "configs": {
            k: {"count": v["count"],
                "templates": sorted(v["templates"]),
                "emits_events": sorted(v["events"])}
            for k, v in sorted(configs.items())
        },
        "flows": flows,
        "transitions": sorted([{"from": a, "on_event": e, "to": b} for a, e, b in transitions],
                              key=lambda t: (t["from"], t["on_event"], t["to"])),
    }


def main() -> int:
    cat = mine()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cat, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  configs (activity types): {len(cat['configs'])}")
    print(f"  flows (journeys mined):   {len(cat['flows'])}")
    print(f"  transitions (edges):      {len(cat['transitions'])}")
    print("\n  distinct flow patterns:")
    seen = set()
    for fl in cat["flows"]:
        pat = " -> ".join(fl["flow"][:8]) + (" ..." if len(fl["flow"]) > 8 else "")
        if pat in seen:
            continue
        seen.add(pat)
        print(f"    [{fl['template']}] {pat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
