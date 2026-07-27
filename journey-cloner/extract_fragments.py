#!/usr/bin/env python3
"""Extract a reusable FRAGMENT for every activity type from the templates.

A journey is stored twice (compiled activities[] + the rawJourneyData editor
mirror), and the canvas is regular:
  * node element:  id == activityId, type in {source, action, exit, ...},
                   data = { name, ports, events, activityType, ... }
  * edge element:  source/target == the two activityIds, data.eventName == event

So a fragment = the three coordinated pieces the composer needs to drop one
activity onto a canvas and wire it:

  library/fragments/<activityName>.json
    ├─ activity   activities[] object            (runtime)
    ├─ config     activitiesConfiguration[id]     (editor mirror)
    └─ node       elements[] node (type, ports, data)   (canvas)

Plus library/fragments/_edge.json — the generic edge element the composer
stamps per connection with {source, target, eventName, eventType, activityName}.

Ids are kept real here; the composer regenerates them on assembly (the repo
already does consistent activityId/handle regeneration). Pure extraction from
files on disk — no API.
"""
from __future__ import annotations

import copy
import glob
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "library" / "fragments"

# When several templates contain a type, prefer the smallest journey (cleanest,
# least surrounding noise) as the fragment source.
PREFER_SMALLEST = True


def _body(t: dict) -> dict:
    return t.get("body", t)


def _load_all() -> list[tuple[str, dict]]:
    out = []
    for f in sorted(glob.glob(str(HERE / "templates" / "**" / "*.json"), recursive=True)):
        try:
            out.append((f.split("templates/")[-1], _body(json.load(open(f, encoding="utf-8")))))
        except Exception:
            pass
    return out


def extract() -> tuple[dict, dict]:
    bodies = _load_all()
    fragments: dict[str, dict] = {}
    edge_template = None

    for rel, body in bodies:
        acts = body.get("activities") or []
        rjd = body.get("rawJourneyData") or {}
        cfg = rjd.get("activitiesConfiguration") or {}
        els = rjd.get("elements") or []
        node_by_id = {e.get("id"): e for e in els if e.get("type") in
                      ("source", "action", "exit", "flowEntry", "parallelFlow", "choosableFlow")}

        # grab a generic edge element once
        if edge_template is None:
            for e in els:
                if e.get("type") in ("default", "emptyEdge") and e.get("source") and e.get("target"):
                    edge_template = copy.deepcopy(e)
                    break

        for a in acts:
            name = a.get("activityName")
            aid = a.get("activityId")
            if not name or not aid:
                continue
            candidate = {
                "activityName": name,
                "source_template": rel,
                "journey_size": len(acts),
                "activity": copy.deepcopy(a),
                "config": copy.deepcopy(cfg.get(aid)),
                "node": copy.deepcopy(node_by_id.get(aid)),
                "has_config": aid in cfg,
                "has_node": aid in node_by_id,
            }
            prev = fragments.get(name)
            # keep the most COMPLETE fragment; break ties by smallest journey
            better = (
                prev is None
                or (candidate["has_config"] and candidate["has_node"]) >
                   (prev["has_config"] and prev["has_node"])
                or (PREFER_SMALLEST
                    and candidate["has_config"] and candidate["has_node"]
                    and prev["has_config"] and prev["has_node"]
                    and candidate["journey_size"] < prev["journey_size"])
            )
            if better:
                fragments[name] = candidate

    return fragments, edge_template


def main() -> int:
    fragments, edge_template = extract()
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for name, frag in sorted(fragments.items()):
        (OUT / f"{name}.json").write_text(
            json.dumps(frag, indent=2, ensure_ascii=False), encoding="utf-8")
        ports = ((frag.get("node") or {}).get("data") or {}).get("ports")
        index.append({
            "activityName": name,
            "source_template": frag["source_template"],
            "has_config": frag["has_config"],
            "has_node": frag["has_node"],
            "port_count": len(ports) if isinstance(ports, list) else (
                len(ports) if isinstance(ports, dict) else 0),
        })
    if edge_template is not None:
        (OUT / "_edge.json").write_text(
            json.dumps(edge_template, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "_index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {len(fragments)} fragments to {OUT}")
    miss_cfg = [i["activityName"] for i in index if not i["has_config"]]
    miss_node = [i["activityName"] for i in index if not i["has_node"]]
    print(f"  edge template: {'yes' if edge_template is not None else 'MISSING'}")
    print(f"  fragments missing config mirror: {miss_cfg or 'none'}")
    print(f"  fragments missing canvas node:   {miss_node or 'none'}")
    print("\n  type                              cfg node ports  source")
    for i in index:
        print(f"    {i['activityName']:32s} {'Y' if i['has_config'] else '-'}   "
              f"{'Y' if i['has_node'] else '-'}   {i['port_count']:<4d}  {i['source_template']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
