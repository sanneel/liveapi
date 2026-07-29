#!/usr/bin/env python3
"""Contract tests for the HAR analyser (journey-cloner/har_analyse.py).

The analyser is the first step of HAR_TO_AUTOMATION.md: a Claude session is meant
to run it on a HAR the operator drops in and trust its report. Two properties have
to hold for that to be safe.

  1. NOTHING SECRET SURVIVES. A HAR is a credential dump — the one in this repo
     carries cookies, and a normal export carries the bearer token and player
     data. If a token reached the report it would land in a chat log, a commit or
     a pasted snippet. Tested by feeding it a HAR that contains a token, a
     session cookie and a Set-Cookie, then asserting none of those strings can be
     found anywhere in the report or the parsed analysis.

  2. THE FLOW IS READ CORRECTLY. The report is only useful if the steps, the
     payload, the id chain and the candidate inputs are right — a plausible-but-
     wrong report is worse than no report, because it gets believed.

No network, no key, fast. Run: python scripts/test_har_analyse.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "journey-cloner"))

import har_analyse as H  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  [OK]   {label}")
    else:
        FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label} — {detail}")


# A HAR shaped like a real backoffice run: reserve an id, loop a content copy,
# POST the draft — carrying the secrets a real export carries.
SECRETS = {
    "token": "Bearer eyJhbGciOiJSUzI1NiJ9.PAYLOAD_SECRET.signature",
    "cookie": "session=s3cr3t-value",
    "setcookie": "auth=leaked-cookie; HttpOnly",
    "password": "hunter2",
}
DRAFT_BODY = {
    "reservedJourneyId": "JRN-0-999001",
    "journeyName": "JBCL | Test | Draft",
    "startAt": "2026-08-01T00:00:00Z",
    "activities": [
        {"activityName": "freespin_bonus",
         "initializationData": {"freespinActivity": {
             "spins": 30,
             "lobbyGameId": "pragmatic-sweet-bonanza-super-scatter",
             "contentId": "c93ad623-44ae-40f6-9aa5-b1aef7fd931a",
             "currenciesConfig": {"CLP": {"betAmount": 10000}}}}},
    ],
}


def har_with(entries: list) -> Path:
    path = Path(tempfile.mkdtemp()) / "run.har"
    path.write_text(json.dumps({"log": {"entries": entries}}), encoding="utf-8")
    return path


def entry(method, url, status=200, req=None, resp=None, secret=True):
    headers = [{"name": "Content-Type", "value": "application/json"}]
    if secret:
        headers.append({"name": "Authorization", "value": SECRETS["token"]})
    return {
        "startedDateTime": "2026-07-29T10:00:00Z",
        "request": {"method": method, "url": url, "headers": headers,
                    "cookies": ([{"name": "session", "value": SECRETS["cookie"]}]
                                if secret else []),
                    "postData": {"text": json.dumps(req) if req is not None else ""}},
        "response": {"status": status,
                     "headers": ([{"name": "Set-Cookie", "value": SECRETS["setcookie"]}]
                                 if secret else []),
                     "cookies": [], "content": {"text": resp if resp is not None else "{}"}},
    }


BASE = "https://x.gr8.tech/api/ubo/api/v0/crm"
ENTRIES = [
    entry("GET", f"{BASE}/journeys?page=1", resp='{"items":[]}'),
    entry("POST", "https://o123.ingest.sentry.io/api/17/envelope/", req={"noise": 1}),
    entry("GET", "https://cdn.x.gr8.tech/static/app.js", resp="//js"),
    entry("POST", f"{BASE}/journey-builder/v0/journeys/identifier", resp='"JRN-0-999001"'),
    entry("POST", f"{BASE}/contents/v1/copy", req={"sourcePath": "a/1", "destinationPath": "b/1"}),
    entry("POST", f"{BASE}/contents/v1/copy", req={"sourcePath": "a/2", "destinationPath": "b/2"}),
    entry("POST", f"{BASE}/contents/v1/copy", req={"sourcePath": "a/3", "destinationPath": "b/3"}),
    entry("POST", f"{BASE}/journey-builder/v0/journey-drafts", req=DRAFT_BODY),
    entry("POST", f"{BASE}/journey-builder/v0/publish", status=422, req={"bad": True}),
]

path = har_with(ENTRIES)
entries, dropped = H.load(path)
res = H.analyse(entries)
cands = H.candidate_inputs(res["_payload_body"])
report = H.report(res, cands, dropped, path)
# Everything the analyser could hand onward, in one blob.
surface = report + json.dumps(res, ensure_ascii=False) + json.dumps(cands, ensure_ascii=False)

print("── secrets never survive the load")
for name, value in SECRETS.items():
    check(f"{name} scrubbed", value not in surface, "PRESENT IN OUTPUT")
check("token fragment gone", "PAYLOAD_SECRET" not in surface, "found")
check("scrub is reported", bool(dropped), "nothing reported dropped")

print("\n── the flow is read correctly")
steps = [s["step"] for s in res["steps"]]
check("noise dropped", res["noise"] == 2, f"noise={res['noise']} (sentry + static)")
check("reads not counted as steps", res["reads"] == 1, f"reads={res['reads']}")
check("failed write reported", any("422" in f for f in res["failed_writes"]),
      f"{res['failed_writes']}")
check("failed write excluded from steps",
      not any("publish" in s for s in steps), f"{steps}")
check("id reservation is a step", any("identifier" in s for s in steps), f"{steps}")
check("repeat calls collapse to one loop step",
      sum(1 for s in res["steps"] if "contents/v1/copy" in s["step"]) == 1, f"{steps}")
loop = next(s for s in res["steps"] if "contents/v1/copy" in s["step"])
check("loop counted", loop["calls"] == 3 and loop["loop"], f"{loop}")
check("loop's varying fields named",
      set(loop["varies_by"]) == {"destinationPath", "sourcePath"}, f"{loop['varies_by']}")
check("payload is the draft POST", "journey-drafts" in (res["payload"] or {}).get("call", ""),
      f"{res['payload']}")

print("\n── the id chain is found")
chain = [(d["from"], d["into"], d["values"]) for d in res["dependencies"]]
check("reserved id chained into the draft",
      any("identifier" in f and "journey-drafts" in i and "JRN-0-999001" in v
          for f, i, v in chain), f"{chain}")
check("chain is one row per step pair", len(chain) == 1, f"{len(chain)} rows: {chain}")

print("\n── candidate inputs")
paths = {c["path"] for c in cands["inputs"]}
check("spins proposed", any(p.endswith("spins") for p in paths), f"{sorted(paths)}")
check("bet amount proposed", any("betAmount" in p for p in paths), f"{sorted(paths)}")
check("date proposed", any(p == "startAt" for p in paths), f"{sorted(paths)}")
ext = {c["path"] for c in cands["external_refs"]}
check("contentId kept as external ref, not an input",
      any("contentId" in p for p in ext) and not any("contentId" in p for p in paths),
      f"ext={sorted(ext)}")

print("\n── a HAR with no usable payload fails cleanly")
empty = har_with([entry("GET", f"{BASE}/journeys", resp="{}")])
e2, _ = H.load(empty)
r2 = H.analyse(e2)
check("no payload reported", r2["payload"] is None, f"{r2['payload']}")
check("still renders a report", isinstance(
    H.report(r2, H.candidate_inputs(None), {}, empty), str), "raised")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All HAR analyser checks passed.")
