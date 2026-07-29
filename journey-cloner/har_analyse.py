#!/usr/bin/env python3
"""Read a HAR of one manual backoffice run and report the automation in it.

This is the first step of HAR_TO_AUTOMATION.md: it turns "here is a 5 MB
recording of me doing the promo by hand" into the few facts a generator needs —
which calls create things, in what order, which ids flow from one response into
the next request, and which values look like per-run inputs.

    python har_analyse.py raw_fetches/journey.har
    python har_analyse.py run.har --json report.json
    python har_analyse.py run.har --write-template templates/casino/new.json

Why a HAR and not "Copy as fetch": a fetch gives one request with no ordering and
no dependencies, which is why every generator here was hand-built. The flow is
the missing information and the HAR has it.

SECURITY: a HAR is a credential dump — cookies, bearer tokens, sometimes player
PII. Everything is scrubbed in memory on load; the raw file is never rewritten
and no header value ever reaches the report. What was dropped is counted so
nobody assumes a token survived.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Reuse the knob classifier rather than write a second one: it already splits a
# captured body's leaves into operator-tunable, external-reference and
# boilerplate, which is exactly the "what inputs do I need" question.
from extract_knobs import _flatten, _is_ext, _is_primary, _typename  # noqa: E402

# Hosts that are never part of the automation.
NOISE_HOSTS = ("sentry", "datadog", "google-analytics", "googletagmanager",
               "hotjar", "mixpanel", "segment.io", "newrelic", "bugsnag")
NOISE_PATHS = ("/envelope/", "/collect", "/beacon", "/telemetry", "/metrics")
STATIC_SUFFIX = (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".woff",
                 ".woff2", ".ico", ".gif", ".map", ".webp")
# Header names dropped on load — the report must never carry a credential.
SECRET_HEADERS = ("authorization", "cookie", "set-cookie", "x-csrf-token",
                  "x-xsrf-token", "proxy-authorization", "x-api-key")
SECRET_FIELDS = ("password", "token", "secret", "authorization", "apikey")
# What counts as an id worth chaining between steps. A loose "long string" test
# matched words like "source" and filenames like "content-en.json", which buried
# the real chain (JRN-0-575389 -> the draft POST) under dozens of false links.
ID_PATTERNS = (
    re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
               r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),   # uuid
    re.compile(r"^[A-Z]{2,5}-\d+-\d+$"),               # JRN-0-575389, CSE-0-14458
    re.compile(r"^[A-Za-z0-9_-]{20,}$"),               # opaque token / long id
    re.compile(r"^\d{6,}$"),                            # numeric id
)


def id_like(value) -> bool:
    if not isinstance(value, str) or "/" in value or " " in value or "." in value:
        return False
    return any(p.match(value) for p in ID_PATTERNS)


def load(path: Path) -> tuple[list[dict], dict]:
    """Scrubbed entries + a note on what was removed."""
    raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    entries = raw.get("log", {}).get("entries", [])
    dropped = Counter()
    clean = []
    for e in entries:
        req, resp = e.get("request", {}) or {}, e.get("response", {}) or {}
        for holder in (req, resp):
            for key in ("headers", "cookies"):
                items = holder.get(key) or []
                if key == "cookies" and items:
                    dropped["cookies"] += len(items)
                    holder[key] = []
                    continue
                kept = []
                for h in items:
                    if (h.get("name") or "").lower() in SECRET_HEADERS:
                        dropped[(h.get("name") or "?").lower()] += 1
                        continue
                    kept.append(h)
                holder[key] = kept
        clean.append({
            "method": (req.get("method") or "").upper(),
            "url": req.get("url") or "",
            "status": (resp.get("status") or 0),
            "req_body": ((req.get("postData") or {}).get("text") or ""),
            "resp_body": ((resp.get("content") or {}).get("text") or ""),
            "started": e.get("startedDateTime") or "",
        })
    return clean, dict(dropped)


def is_noise(entry: dict) -> str | None:
    url = entry["url"].lower()
    if any(h in url for h in NOISE_HOSTS):
        return "analytics host"
    if any(p in url for p in NOISE_PATHS):
        return "telemetry path"
    if url.split("?")[0].endswith(STATIC_SUFFIX):
        return "static asset"
    return None


def endpoint(url: str) -> str:
    """A comparable shape for a URL: ids collapsed, query dropped."""
    path = url.split("?")[0]
    path = path.split("/api/")[-1] if "/api/" in path else path
    path = re.sub(r"/[0-9a-fA-F-]{8,}", "/<id>", path)
    path = re.sub(r"/\d{3,}", "/<n>", path)
    return path


def json_body(text: str):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def ids_in(text: str) -> set[str]:
    """Values in a response that a later request could depend on."""
    data = json_body(text)
    out: set[str] = set()
    if data is None:
        # not JSON: identifier endpoints answer with a bare quoted id
        bare = (text or "").strip().strip('"')
        if id_like(bare):
            out.add(bare)
        return out
    for _path, value in _flatten(data):
        if id_like(value):
            out.add(value)
    return out


def analyse(entries: list[dict]) -> dict:
    total = len(entries)
    noise = [e for e in entries if is_noise(e)]
    useful = [e for e in entries if not is_noise(e)]
    reads = [e for e in useful if e["method"] == "GET"]
    writes = [e for e in useful if e["method"] in ("POST", "PUT", "PATCH", "DELETE")]
    ok_writes = [e for e in writes if 200 <= e["status"] < 300]
    failed = [e for e in writes if not (200 <= e["status"] < 300)]

    # Repeated endpoint = a loop in the flow (48x "copy content" is one step,
    # not 48 steps).
    groups: "OrderedDict[str, list]" = OrderedDict()
    for e in ok_writes:
        groups.setdefault(f"{e['method']} {endpoint(e['url'])}", []).append(e)

    steps = []
    for label, calls in groups.items():
        bodies = [json_body(c["req_body"]) for c in calls]
        sizes = [len(c["req_body"] or "") for c in calls]
        varies = []
        if len(calls) > 1 and all(isinstance(b, dict) for b in bodies):
            keys = set().union(*(set(b) for b in bodies))
            for k in sorted(keys):
                seen = {json.dumps(b.get(k), sort_keys=True, ensure_ascii=False)
                        for b in bodies}
                if len(seen) > 1:
                    varies.append(k)
        steps.append({"step": label, "calls": len(calls),
                      "biggest_body": max(sizes) if sizes else 0,
                      "loop": len(calls) > 1,
                      "varies_by": varies[:6]})

    # The payload: the largest successful JSON write body. In the reference HAR
    # that is the single journey-drafts POST among 61 mutating calls.
    payload = max(ok_writes, key=lambda e: len(e["req_body"] or ""), default=None)

    # Dependencies: a value in request N that appeared in an earlier response.
    seen_ids: dict[str, int] = {}
    for i, e in enumerate(entries):
        for v in ids_in(e["resp_body"]):
            seen_ids.setdefault(v, i)
    # Collapse to one entry per (producing step -> consuming step): the 48-call
    # loop reuses the same handful of ids, which is one dependency, not 96.
    pairs: "OrderedDict[tuple, set]" = OrderedDict()
    for e in ok_writes:
        i = entries.index(e)
        body = e["req_body"] or ""
        into = f"{e['method']} {endpoint(e['url'])}"
        for v, first in seen_ids.items():
            if first < i and v in body:
                src = f"{entries[first]['method']} {endpoint(entries[first]['url'])}"
                pairs.setdefault((src, into), set()).add(v)
    deps = [{"from": src, "into": into,
             "values": sorted(vals, key=len, reverse=True)[:3], "count": len(vals)}
            for (src, into), vals in pairs.items()]

    return {"total": total, "noise": len(noise), "reads": len(reads),
            "writes": len(writes), "ok_writes": len(ok_writes),
            "failed_writes": [f"{e['method']} {endpoint(e['url'])} -> {e['status']}"
                              for e in failed],
            "steps": steps, "dependencies": deps,
            "payload": ({"call": f"{payload['method']} {endpoint(payload['url'])}",
                         "bytes": len(payload["req_body"])} if payload else None),
            "_payload_body": json_body(payload["req_body"]) if payload else None}


def candidate_inputs(body) -> dict:
    """Split the payload's leaves into what an operator sets, what is an external
    reference, and the rest. Same classifier the recipes use."""
    if body is None:
        return {"inputs": [], "external_refs": [], "leaves": 0}
    inputs, ext = [], []
    leaves = _flatten(body)
    for path, value in leaves:
        if _is_ext(path, value):
            ext.append({"path": path, "example": value})
        elif _is_primary(path, value):
            inputs.append({"path": path, "example": value, "type": _typename(value)})
    # Dates are per-run by definition and the keyword list does not catch them.
    for path, value in leaves:
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
            if not any(i["path"] == path for i in inputs):
                inputs.append({"path": path, "example": value, "type": "date"})
    return {"inputs": inputs, "external_refs": ext, "leaves": len(leaves)}


def report(res: dict, cands: dict, dropped: dict, path: Path) -> str:
    L = [f"HAR: {path.name}",
         f"  {res['total']} entries — {res['reads']} reads, {res['writes']} writes "
         f"({res['ok_writes']} succeeded), {res['noise']} noise",
         f"  scrubbed on load: " + (", ".join(f"{k}×{v}" for k, v in dropped.items())
                                    if dropped else "nothing found")]
    if res["failed_writes"]:
        L.append("  FAILED writes (a flow that errored is not a flow to automate):")
        L += [f"     {f}" for f in res["failed_writes"][:5]]

    L.append("\nFLOW — the steps to reproduce, in order:")
    for i, s in enumerate(res["steps"], 1):
        loop = f"  ×{s['calls']} (loop)" if s["loop"] else ""
        L.append(f"  {i}. {s['step']}{loop}   body {s['biggest_body']}b")
        if s["varies_by"]:
            L.append(f"       varies by: {', '.join(s['varies_by'])}")

    if res["payload"]:
        L.append(f"\nPAYLOAD — the call that carries the object:\n"
                 f"  {res['payload']['call']}  ({res['payload']['bytes']} bytes)"
                 f"\n  -> save this body as the template")

    if res["dependencies"]:
        L.append("\nDEPENDENCIES — ids that must flow between steps:")
        for d in res["dependencies"]:
            more = (f" +{d['count'] - len(d['values'])} more"
                    if d["count"] > len(d["values"]) else "")
            L.append(f"  {d['from']}  ->  {d['into']}")
            L.append(f"        via {', '.join(v[:40] for v in d['values'])}{more}")

    L.append(f"\nCANDIDATE INPUTS — {len(cands['inputs'])} of {cands['leaves']} "
             f"leaves look per-run:")
    for c in cands["inputs"][:25]:
        L.append(f"  {c['path'][:70]:72} = {str(c['example'])[:28]!r} ({c['type']})")
    if len(cands["inputs"]) > 25:
        L.append(f"  … and {len(cands['inputs']) - 25} more (use --json for all)")
    L.append(f"\nEXTERNAL REFS — {len(cands['external_refs'])} ids to keep or re-copy, "
             f"not to invent")

    L.append("\nNEXT: HAR_TO_AUTOMATION.md step 3 — confirm the flow above with the "
             "operator,\n      then write the template and the generator.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("har", help="path to the .har file")
    ap.add_argument("--json", metavar="OUT", help="write the full report as JSON")
    ap.add_argument("--write-template", metavar="OUT",
                    help="save the payload body as a template JSON")
    args = ap.parse_args()

    path = Path(args.har)
    if not path.is_file():
        print(f"no such file: {path}")
        return 2
    entries, dropped = load(path)
    res = analyse(entries)
    cands = candidate_inputs(res["_payload_body"])
    print(report(res, cands, dropped, path))

    if args.write_template:
        if res["_payload_body"] is None:
            print("\nno JSON payload found — nothing to write")
            return 3
        out = Path(args.write_template)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res["_payload_body"], ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"\ntemplate written: {out}")
    if args.json:
        payload = {k: v for k, v in res.items() if k != "_payload_body"}
        payload["candidate_inputs"] = cands
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        print(f"report written: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
