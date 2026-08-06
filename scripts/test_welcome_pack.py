#!/usr/bin/env python3
"""Contract tests for the Welcome Pack generator (journey-cloner/welcome_pack_campaign.py).

That generator does not ship a stored template: the console script it emits GETs
the four source drafts at paste time, swaps the promocode and posts the clone. So
the thing to test is the emitted JavaScript, not a Python transform — and the
property that matters is the one the runbook names: only the fields we meant to
change may differ from the source.

The script is run under node against a stubbed backoffice: fake token, synthetic
source drafts shaped like the captured ones, and a fetch that records the POST
bodies instead of sending them. Then this file asserts on those bodies.

Covered, each one a failure that reached a real draft in this repo's history or
would have here:

  1. the promocode is replaced in BOTH storages and in the journey name;
  2. a new code that CONTAINS an old one (JUGATW -> JUGATW2) is not corrupted;
  3. every activity id is regenerated, ports/edges/flowIds stay consistent, and
     two drafts made in one run never share an id;
  4. only POST_KEYS are sent — a GET returns more than a POST accepts;
  5. the two storages agree on the journey name;
  6. promotions are NOT rewritten (the known limitation), so the test pins it
     rather than letting it drift silently.

No network, no key, fast. Needs node. Run: python scripts/test_welcome_pack.py
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "journey-cloner"))

import welcome_pack_campaign as wp  # noqa: E402

FAILURES: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    if not ok:
        FAILURES.append(label)


def _uuid(n: int) -> str:
    h = f"{n:012x}"
    return f"aaaaaaaa-bbbb-4ccc-8ddd-{h}"


def source_draft(*, draft_id: int, brand: str, name: str, info_name: str,
                 codes: list[str], base: int) -> dict:
    """A synthetic source draft with the structure the real ones have."""
    reg, promo, sms, flow = _uuid(base), _uuid(base + 1), _uuid(base + 2), _uuid(base + 3)
    joined = ", ".join(codes)
    link = "0865ae2a-450e-47bc-b705-588d2f6fa33b"
    return {
        # GET-only fields the POST must not carry.
        "id": draft_id,
        "status": "Draft",
        "createdAt": "2026-08-01T00:00:00Z",

        "journeyName": name,
        "brand": brand,
        "currencyCodes": ["CLP"],
        "activities": [
            {
                "activityId": reg,
                "activityName": "registration",
                "activityDisplayName": "Reference codes",
                "events": [{
                    "eventName": "PlayerAdded", "eventType": "Activation",
                    "split": {"paths": [
                        {"pathId": 2, "pathName": "Flow 1", "flowId": flow,
                         "nextActivityId": promo}]},
                }],
                "dependencies": [], "dataDependencies": [],
                "initializationData": {
                    "version": "v2", "placements": [],
                    "displayData": [f"Promo codes: {joined}"],
                    "refCodeTypes": ["Promocode"],
                    "promocodeSettings": {"values": list(codes), "purpose": "Affiliate",
                                          "availability": ["NewUser"]},
                },
            },
            {
                "activityId": promo,
                "activityName": "multipurpose_promotion",
                "activityDisplayName": "1st (150% Bonus)",
                "events": [], "dataDependencies": [],
                "dependencies": [{"journeyActivityId": reg, "key": "CurrencyCode"}],
                "initializationData": {
                    "placements": [{"data": {"FrontId": _uuid(base + 10),
                                             "ContentId": _uuid(base + 11)}}],
                    "promotionId": _uuid(base + 12),
                    "promotionLinkId": link,
                    "promotionDisplayId": "771151",
                },
            },
            {
                "activityId": sms,
                "activityName": "dextra_sms",
                "events": [], "dependencies": [], "dataDependencies": [],
                "initializationData": {"displayData": [
                    f"Parimatch | {codes[0]} https://pmcl.bet/services/promo/promotion/{link}?seq=last"]},
            },
        ],
        "metadata": {"priority": 2, "category": "Marketing", "purpose": "Welcome",
                     "productType": "Sport"},
        "reEntryRule": {"reEntryMode": "Prohibited"},
        "timeZoneId": "Chile/Continental",
        "testControlGroupParameters": {"playersAddingStrategy": "IncludeAll", "isEnabled": False},
        "activityEventConversionMetrics": [],
        "reservedJourneyId": "JRN-0-000000",
        "journeySource": "UBO",
        "isArchived": False,
        "isUnlimited": True,
        "isImmediatelyAfterPublish": True,
        "rawJourneyData": {
            "elements": [
                {"id": reg, "type": "source",
                 "data": {"name": "registration", "ports": [{"id": f"PlayerAdded-{reg}"}]}},
                {"id": flow, "type": "flowEntry",
                 "data": {"name": "flowEntry", "order": 1,
                          "contentId": "5b8d93c6-6bf0-45a0-b0ab-d4ee30c21d45"}},
                {"id": promo, "type": "action",
                 "data": {"name": "multipurpose_promotion", "ports": [{"id": f"input-{promo}"}]}},
                {"id": _uuid(base + 20), "type": "default", "source": reg, "target": promo,
                 "sourceHandle": f"PlayerAdded-{reg}", "targetHandle": f"input-{promo}"},
            ],
            "infoValues": {"brand": brand, "journeyName": info_name, "isUnlimited": True,
                           "stopAt": "Unlimited"},
            "activitiesConfiguration": {
                reg: {"data": {"version": "v2",
                               "promocodeSettings": {"values": list(codes)}},
                      "error": False,
                      "displayData": [f"Promo codes: {joined}"],
                      "displayName": "Reference codes"},
            },
            "boundaryConfiguration": {
                promo: {"error": False, "elements": [
                    {"id": sms, "data": {"ports": [{"id": f"input-{sms}"}]}}]},
            },
            # Stable template uuids used as object KEYS — the real bodies keep
            # these identical across copies, so they must not be regenerated.
            "pathesConfiguration": {"0c1e0f15-3c7e-4fcb-940d-6cf18de7076b": [{"pathId": "path1"}]},
        },
        "duplicatedFromId": 626354,
    }


def fake_jwt() -> str:
    def seg(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg({'typ': 'Bearer', 'exp': int(time.time()) + 3600})}.sig"


HARNESS = r"""
const fs = require('fs');
const SOURCES = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const OUT = process.argv[3];
const posted = [];
let reserved = 0;

global.fetch = async (url, opts = {}) => {
  const method = (opts.method || 'GET').toUpperCase();
  if (url.endsWith('/journeys/identifier') && method === 'POST') {
    reserved += 1;
    return { ok: true, status: 200, text: async () => `"JRN-0-TEST${reserved}"` };
  }
  const m = url.match(/\/journey-drafts\/(\d+)$/);
  if (m && method === 'GET') {
    const draft = SOURCES[m[1]];
    if (!draft) return { ok: false, status: 404, text: async () => 'no such source' };
    return { ok: true, status: 200, text: async () => JSON.stringify(draft) };
  }
  if (url.endsWith('/journey-drafts') && method === 'POST') {
    posted.push(JSON.parse(opts.body));
    return { ok: true, status: 200, text: async () => '{"ok":true}' };
  }
  throw new Error('unexpected request: ' + method + ' ' + url);
};

const quiet = () => {};
console.log = quiet; console.table = quiet;
// console.error is left alone: when the script refuses, its reasons are the
// only useful output this harness can surface.
console.error = (...a) => process.stderr.write(a.join(' ') + '\n');

process.on('exit', () => fs.writeFileSync(OUT, JSON.stringify(posted)));
"""


def run_script(js: str, sources: dict[int, dict], tmp: Path) -> list[dict]:
    """Run the emitted console script under node against stubbed sources."""
    js = js.replace("const MANUAL_TOKEN = '';", f"const MANUAL_TOKEN = '{fake_jwt()}';")
    src_path = tmp / "sources.json"
    src_path.write_text(json.dumps({str(k): v for k, v in sources.items()}), encoding="utf-8")
    out_path = tmp / "posted.json"
    runner = tmp / "run.js"
    runner.write_text(HARNESS + "\n" + js, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(runner), str(src_path), str(out_path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"node failed: {proc.stderr.strip()[:2000]}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def collect_ids(obj, out: set) -> set:
    """Every activityId / element id in a body."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("activityId", "id") and isinstance(v, str) and len(v) == 36:
                out.add(v)
            collect_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_ids(v, out)
    return out


def check_admin_wiring() -> None:
    """The Optimization tab: route, tab id, registry entry, template, and the
    runner actually producing a script. A tab that 404s or renders an empty
    panel is the kind of drift nothing else here would catch.

    Unauthenticated GET /admin/* returns 404 by design (app/auth/dependencies.py),
    so this pokes the pieces directly rather than over HTTP.
    """
    print("scenario: admin tab wiring")
    sys.path.insert(0, str(REPO))
    from app.routes import admin_views
    from app.services import promotions_catalog as pc
    from app.services import journey_cloner_runner as runner

    paths = {getattr(r, "path", "") for r in admin_views.router.routes}
    check("/admin/promotions/welcome-pack" in paths, "POST route is registered")
    check("welcome_pack" in admin_views._PROMO_TABS, "welcome_pack is an allowed tab")
    check(set(admin_views._wp_ns()["form"]) == {"code", "brand", "mode"},
          "form namespace exposes code/brand/mode")

    entry = next((g for g in pc.generators() if g["key"] == "welcome_pack"), None)
    check(entry is not None, "registry has the welcome_pack generator")
    if entry:
        check(entry["tab"] == "welcome_pack", f"registry points at the tab (got {entry['tab']!r})")
        check(bool(entry["file"]), "registry resolves welcome_pack_campaign.py on disk")
    check("welcome_pack_campaign.py" not in pc.unlisted_generators(),
          "generator is not reported as unlisted")

    tpl = (REPO / "app" / "templates" / "promotions.html").read_text(encoding="utf-8")
    check('data-tab="welcome_pack"' in tpl, "tab button present")
    check('data-panel="welcome_pack"' in tpl, "tab panel present")
    check('action="/admin/promotions/welcome-pack"' in tpl, "form posts to the route")
    check("BEFORE PUBLISHING" in tpl, "panel warns about the inherited promotions")
    # Render it. A panel that parses but comes out empty — a renamed context key,
    # a dropped namespace — would otherwise pass every check above.
    import types
    user = types.SimpleNamespace(username="tester", role="editor", is_admin=True)
    ctx = admin_views._promotions_context(
        user=user, active_tab="welcome_pack",
        wp=admin_views._wp_ns(
            form={"code": "JUGAWELCOME", "brand": "jbcl", "mode": "boosted"},
            console_script={"name": "wp_console.js", "text": "// script body"},
            result={"exit_code": 0, "output": "ran", "command": "cmd", "ok": True}))
    ctx.pop("request", None)
    html = admin_views.templates.get_template("promotions.html").render(
        request=types.SimpleNamespace(url=types.SimpleNamespace(path="/admin/promotions")), **ctx)
    panel = html.split('data-panel="welcome_pack"', 1)[-1].split('data-panel="nc_discount"', 1)[0]
    for probe, label in (
        ('name="code"', "promo code field"),
        ('value="JUGAWELCOME"', "the submitted code is kept in the form"),
        ('name="brand"', "brand dropdown"),
        ('name="mode"', "mode dropdown"),
        ("selected>JBCL (JugaBet)", "the chosen brand stays selected"),
        ('action="/admin/promotions/welcome-pack"', "form action"),
        ("wp_console.js", "generated script name"),
        ("// script body", "generated script body"),
        ("BEFORE PUBLISHING", "inherited-promotion warning"),
    ):
        check(probe in panel, f"panel renders: {label}")

    # End to end: the runner shells out to the generator and reads the script back.
    code, output, display_cmd, js_text, js_name = runner.generate_welcome_pack_console_script(
        code="wiringtest", brand="jbcl", mode="boosted")
    check(code == 0, f"runner exited 0 (got {code}: {output.strip()[-200:]})")
    check(js_text is not None, "runner returned the emitted script")
    if js_text:
        check("WIRINGTEST" in js_text, "the code was upper-cased and baked in")
        check('"sourceId": 657230' in js_text, "jbcl/boosted resolves to source draft 657230")
        check("657226" not in js_text, "the unselected sources are absent")
    (REPO / "journey-cloner" / "console_scripts" / js_name).unlink(missing_ok=True)

    # "both" is gone, and gone means refused — not silently treated as a brand.
    # It used to build up to four drafts per paste, which left four separate
    # inherited promotions to re-point, and a defaulted brand is how a Fortunazo
    # operator ends up holding a JugaBet draft.
    import subprocess as _sp
    for args, label in (
        (["--code", "JUGAWELCOME", "--brand", "both", "--mode", "normal"], "--brand both"),
        (["--code", "JUGAWELCOME", "--brand", "jbcl", "--mode", "both"], "--mode both"),
        (["--code", "JUGAWELCOME"], "no --brand/--mode at all"),
    ):
        rc = _sp.run([sys.executable, str(REPO / "journey-cloner" / "welcome_pack_campaign.py")] + args,
                     capture_output=True, text=True, cwd=REPO / "journey-cloner")
        check(rc.returncode != 0, f"{label} is refused by the CLI")
    for brand, mode in (("both", "normal"), ("jbcl", "both"), ("", "normal"), ("jbcl", "")):
        r = admin_views.promotions_welcome_pack(
            request=None, code="JUGAWELCOME", brand=brand, mode=mode,
            user=types.SimpleNamespace(username="tester", role="editor", is_admin=True))
        body = r.body.decode()
        check("Pick a brand and a mode" in body,
              f"the route refuses brand={brand!r} mode={mode!r}")
        check("Console Script Ready" not in body,
              f"no script for brand={brand!r} mode={mode!r}")

    # A malformed code must come back as a refusal, not a script.
    bad_code, bad_output, _, bad_js, bad_name = runner.generate_welcome_pack_console_script(
        code="no good!", brand="jbcl", mode="normal")
    check(bad_code != 0 and bad_js is None, "a malformed promo code is refused, no script emitted")
    check("Refusing to emit" in bad_output, "the refusal reason reaches the run output")
    (REPO / "journey-cloner" / "console_scripts" / bad_name).unlink(missing_ok=True)


def main() -> int:
    if not shutil.which("node"):
        print("node is not installed; cannot run the emitted script", file=sys.stderr)
        return 1

    jbcl = source_draft(
        draft_id=657230, brand="JBCL", base=0x100,
        name="Copy of JBCL | SP | Welcome Pack - 1st Deposit / Aff / TIPSTERMAGO, JUGATW",
        info_name="JBCL | SP | Welcome Pack - 1st Deposit / Aff / TIPSTERMAGO, JUGATW",
        codes=["TIPSTERMAGO", "JUGATW"])
    pmcl = source_draft(
        draft_id=657226, brand="PMCL", base=0x200,
        name="Copy of Copy of  FTCL | SP | Welcome Pack - 1st Deposit / Aff | COMSPORTS",
        info_name=" FTCL | SP | Welcome Pack - 1st Deposit / Aff | COMSPORTS",
        codes=["COMSPORTS"])
    sources = {657230: jbcl, 657226: pmcl}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # --- scenario 1: one new code that contains an old one (JUGATW -> JUGATW2)
        print("scenario: single new code, JBCL(2 codes) + PMCL(1 code)")
        plan, _ = wp.prepare(["JUGATW2"], ["JBCL"], ["boosted"])
        plan2, _ = wp.prepare(["JUGATW2"], ["PMCL"], ["normal"])
        plan["targets"] += plan2["targets"]
        posted = run_script(wp._render_js(plan), sources, tmp)

        check(len(posted) == 2, f"two drafts posted (got {len(posted)})")
        if len(posted) != 2:
            return 1
        by_source = {p["duplicatedFromId"]: p for p in posted}
        check(set(by_source) == {657230, 657226}, "duplicatedFromId points at each source")

        j, p = by_source[657230], by_source[657226]

        # 1 + 2: the code is swapped everywhere, and not corrupted
        for label, body, old in (("jbcl", j, ["TIPSTERMAGO", "JUGATW"]),
                                 ("pmcl", p, ["COMSPORTS"])):
            text = json.dumps(body)
            leaked = [c for c in old if f'"{c}"' in text or f" {c} " in text or f"{c} https" in text]
            check(not leaked, f"{label}: no old promocode survives ({leaked or 'none'})")
            check("JUGATW2" in text, f"{label}: new promocode present")
            reg = next(a for a in body["activities"] if a["activityName"] == "registration")
            vals = reg["initializationData"]["promocodeSettings"]["values"]
            check(vals == ["JUGATW2"], f"{label}: promocodeSettings.values == ['JUGATW2'] (got {vals})")
            check(reg["initializationData"]["displayData"] == ["Promo codes: JUGATW2"],
                  f"{label}: displayData rewritten")
            mirror = body["rawJourneyData"]["activitiesConfiguration"][reg["activityId"]]
            check(mirror["data"]["promocodeSettings"]["values"] == ["JUGATW2"],
                  f"{label}: editor mirror carries the same promocode")
            check(mirror["displayData"] == ["Promo codes: JUGATW2"],
                  f"{label}: editor mirror displayData rewritten")

        # 5: names cleaned and identical across both storages
        check(j["journeyName"] == "JBCL | SP | Welcome Pack - 1st Deposit / Aff / JUGATW2",
              f"jbcl: name cleaned + substituted (got {j['journeyName']!r})")
        check(p["journeyName"] == "FTCL | SP | Welcome Pack - 1st Deposit / Aff | JUGATW2",
              f"pmcl: 'Copy of Copy of' and leading space stripped (got {p['journeyName']!r})")
        for label, body in (("jbcl", j), ("pmcl", p)):
            check(body["journeyName"] == body["rawJourneyData"]["infoValues"]["journeyName"],
                  f"{label}: both storages agree on journeyName")

        # 3: ids regenerated, consistently, without collisions
        for label, body, src in (("jbcl", j, jbcl), ("pmcl", p, pmcl)):
            old_ids = collect_ids(src, set())
            new_ids = collect_ids(body, set())
            check(not (old_ids & new_ids), f"{label}: no source activity/node id reused")
            reg = next(a for a in body["activities"] if a["activityName"] == "registration")
            promo = next(a for a in body["activities"]
                         if a["activityName"] == "multipurpose_promotion")
            elem_ids = {e["id"] for e in body["rawJourneyData"]["elements"]}
            check(reg["activityId"] in elem_ids and promo["activityId"] in elem_ids,
                  f"{label}: activities[] ids match the editor mirror's nodes")
            flow = reg["events"][0]["split"]["paths"][0]["flowId"]
            check(flow in elem_ids, f"{label}: flowId still names a flowEntry node")
            reg_node = next(e for e in body["rawJourneyData"]["elements"]
                            if e["id"] == reg["activityId"])
            check(reg_node["data"]["ports"][0]["id"] == f"PlayerAdded-{reg['activityId']}",
                  f"{label}: port ids follow the regenerated node id")
            edge = next(e for e in body["rawJourneyData"]["elements"] if e.get("source"))
            check(edge["source"] == reg["activityId"] and edge["target"] == promo["activityId"],
                  f"{label}: edge endpoints follow the regenerated ids")
            check(promo["activityId"] in body["rawJourneyData"]["boundaryConfiguration"],
                  f"{label}: boundaryConfiguration key follows the regenerated id")
            check(list(body["rawJourneyData"]["pathesConfiguration"]) ==
                  ["0c1e0f15-3c7e-4fcb-940d-6cf18de7076b"],
                  f"{label}: stable pathesConfiguration keys left alone")

        jbcl_ids = collect_ids(j, set())
        pmcl_ids = collect_ids(p, set())
        check(not (jbcl_ids & pmcl_ids), "the two drafts share no activity id")

        # 4: only the keys the backoffice itself posts
        for label, body in (("jbcl", j), ("pmcl", p)):
            extra = sorted(set(body) - set(wp.POST_KEYS))
            check(not extra, f"{label}: no keys beyond POST_KEYS ({extra or 'none'})")
            for gone in ("id", "status", "createdAt"):
                check(gone not in body, f"{label}: GET-only field {gone!r} dropped")
            check(body["reservedJourneyId"].startswith("JRN-0-TEST"),
                  f"{label}: a fresh journey id was reserved")
        check(j["brand"] == "JBCL" and p["brand"] == "PMCL", "brand set per target")

        # 6: pin the known limitation rather than let it drift
        for label, body, src in (("jbcl", j, jbcl), ("pmcl", p, pmcl)):
            got = next(a for a in body["activities"]
                       if a["activityName"] == "multipurpose_promotion")
            want = next(a for a in src["activities"]
                        if a["activityName"] == "multipurpose_promotion")
            check(got["initializationData"]["promotionLinkId"]
                  == want["initializationData"]["promotionLinkId"],
                  f"{label}: promotion is still the source's (known limitation, printed by the script)")

        # --- scenario 2: two new codes, joined form must win over the singles
        print("scenario: two new codes")
        plan3, _ = wp.prepare(["TIPSTERX", "JUGATW2"], ["JBCL"], ["boosted"])
        posted2 = run_script(wp._render_js(plan3), sources, tmp)
        check(len(posted2) == 1, f"one draft posted (got {len(posted2)})")
        if posted2:
            b = posted2[0]
            check(b["journeyName"] ==
                  "JBCL | SP | Welcome Pack - 1st Deposit / Aff / TIPSTERX, JUGATW2",
                  f"both codes in the name (got {b['journeyName']!r})")
            reg = next(a for a in b["activities"] if a["activityName"] == "registration")
            check(reg["initializationData"]["promocodeSettings"]["values"]
                  == ["TIPSTERX", "JUGATW2"], "both codes in promocodeSettings.values")
            check(reg["initializationData"]["displayData"]
                  == ["Promo codes: TIPSTERX, JUGATW2"], "both codes in displayData")

    check_admin_wiring()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:", file=sys.stderr)
        for f in FAILURES:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
