#!/usr/bin/env python3
"""Build the console script for a Randomizer promo — Sport Wheel of Fortune,
Casino Wheel of Fortune, or Raspa y Gana (Scratch Card).

A randomizer is a weighted set of prize slices; each slice routes a winning
player to a journey (journeyId + activityId). We keep the captured prize table,
segment (filterConditions) and visual bundle (contentId/frontId) from the
template and only re-date + re-name the promo for a new run. Prize weights and
the routed journeys can be overridden.

Two creation flows are used by the backoffice (captured in each template's
_meta.endpoint):

  * casino_wof / casino_scratch:  POST /promo/v2/promo-drafts/randomizer  (create
    the draft, returns its id)  →  PUT /promo/v2/randomizer/<id>  (save details).
  * sport_wof:  POST /promo/v2/promo-drafts/randomizer  (create draft) →
    POST /promo/v2/randomizer?draftId=<id>  (fill it).

The generated script creates the draft, then fills it — heavy logging, stops at
the first error. Randomizer drafts are drafts (not published), so a wrong call
just 404s and creates nothing to clean up. Set PREVIEW=true at the top of the
script to log the two request bodies without sending them.

Many dates at once: pass --dates to create one draft per date in a single
console paste (same prizes/segment/visual, per-date name + window).

Usage:
  python randomizer_campaign.py --kind sport_wof     --date 2026-07-06
  python randomizer_campaign.py --kind sport_wof     --dates 2026-07-06 2026-07-13 2026-07-20
  python randomizer_campaign.py --kind casino_wof    --date 2026-07-06
  python randomizer_campaign.py --kind casino_scratch --date 2026-07-06 --days 2

  # override weights (in prize order) and/or the routed journeys:
  python randomizer_campaign.py --kind casino_wof --date 2026-07-06 \
      --weights 55 42 2.7 0.3 --journeys JRN-0-572381 JRN-0-572307 ...

  --dry-run writes the prepared body to out/ instead of a console script.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from casino_journey import DEFAULT_BASE_URL, utc_dotnet

UTC = timezone.utc
HERE = Path(__file__).resolve().parent

# Per-kind configuration. date_offsets give (day_delta, "HH:MM") for the four
# promo dates, reproducing each capture's exact minute offsets. name_prefix and
# name_fmt build internalName; url_short builds urlShortName. days_default is the
# window length (end/hide land day+days).
KINDS: dict[str, dict] = {
    "sport_wof": {
        "label": "Sport Wheel of Fortune",
        "template": HERE / "templates" / "sport" / "sport_wof_randomizer.json",
        "flow": "draftid_post",   # POST /promo/v2/randomizer?draftId=<id>
        "name_prefix": "JBCL|SP|WOF|",
        "name_fmt": "%d.%m.%y",
        "days_default": 1,
        "date_offsets": {"show": (0, "04:00"), "start": (0, "04:01"),
                         "end": ("+days", "03:59"), "hide": ("+days", "04:00")},
        "url_short": lambda promo, end: f"sport-{promo.day:02d}-{promo.month:02d}-{promo.year}",
    },
    "casino_wof": {
        "label": "Casino Wheel of Fortune",
        "template": HERE / "templates" / "casino" / "casino_wof_randomizer.json",
        "flow": "create_put",     # PUT /promo/v2/randomizer/<id>
        "name_prefix": "JBCL|CS|WOF|",
        "name_fmt": "%d.%m.%y",
        "days_default": 1,
        "date_offsets": {"show": (0, "04:01"), "start": (0, "04:02"),
                         "end": ("+days", "03:58"), "hide": ("+days", "03:59")},
        "url_short": lambda promo, end: end.strftime("%d-%m-%y"),
    },
    "casino_scratch": {
        "label": "Raspa y Gana (Scratch Card)",
        "template": HERE / "templates" / "casino" / "raspaygana_scratchcard.json",
        "flow": "create_put",
        "name_prefix": "FTCL|CS|FDSC|",
        "name_fmt": "%d.%m",
        "days_default": 2,
        "date_offsets": {"show": (0, "04:00"), "start": (0, "04:01"),
                         "end": ("+days", "03:59"), "hide": ("+days", "04:00")},
        "url_short": lambda promo, end: end.strftime("%d-%m-%y"),
    },
}


def _dt(promo: datetime, offset, days: int) -> datetime:
    day_delta, hhmm = offset
    d = days if day_delta == "+days" else day_delta
    h, m = (int(x) for x in hhmm.split(":"))
    return (promo + timedelta(days=d)).replace(hour=h, minute=m, second=0, microsecond=0)


def load_template(kind: str) -> dict:
    body = json.loads(KINDS[kind]["template"].read_text(encoding="utf-8"))
    body.pop("_meta", None)
    return body


def prepare(kind: str, date_str: str, *, days: int | None = None,
            internal_name: str = "", url_short: str = "",
            weights: list[str] | None = None, journeys: list[str] | None = None) -> tuple[dict, list[str]]:
    cfg = KINDS[kind]
    days = cfg["days_default"] if days is None else days
    promo = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)

    body = load_template(kind)
    report: list[str] = []

    off = cfg["date_offsets"]
    show = _dt(promo, off["show"], days)
    start = _dt(promo, off["start"], days)
    end = _dt(promo, off["end"], days)
    hide = _dt(promo, off["hide"], days)
    body["showDate"], body["startDate"] = utc_dotnet(show), utc_dotnet(start)
    body["endDate"], body["hideDate"] = utc_dotnet(end), utc_dotnet(hide)
    report.append(f"window {show:%Y-%m-%d %H:%MZ} → {end:%Y-%m-%d %H:%MZ} (hide {hide:%d %H:%MZ}), {days}d")

    body["internalName"] = internal_name or (cfg["name_prefix"] + promo.strftime(cfg["name_fmt"]))
    body["urlShortName"] = url_short or cfg["url_short"](promo, end)
    report.append(f"internalName = {body['internalName']!r}")
    report.append(f"urlShortName = {body['urlShortName']!r}")

    # sport template ships tokenised initial dates — anchor them to this run too.
    if "initialShowDate" in body:
        body["initialShowDate"], body["initialEndDate"] = utc_dotnet(show), utc_dotnet(end)

    prizes = body.get("prizes", [])
    if weights is not None:
        if len(weights) != len(prizes):
            raise SystemExit(f"--weights has {len(weights)} values but the template has {len(prizes)} prizes.")
        for p, w in zip(prizes, weights):
            p["weight"] = w
        report.append(f"weights overridden = {weights}")
    if journeys is not None:
        if len(journeys) != len(prizes):
            raise SystemExit(f"--journeys has {len(journeys)} values but the template has {len(prizes)} prizes.")
        for p, jid in zip(prizes, journeys):
            p.setdefault("journeyPrizeSettings", {})["journeyId"] = jid
        report.append(f"journeys overridden = {journeys}")
    report.append(f"{len(prizes)} prize slice(s), weights = {[p.get('weight') for p in prizes]}")

    brand = (body.get("currencies") or [{}])[0].get("brand", "JBCL")
    report.append(f"brand (x-brand) = {brand}, visual contentId {body.get('contentId')}")
    return body, report


def verify(body: dict) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    prizes = body.get("prizes", [])
    out.append((bool(prizes), f"{len(prizes)} prize slice(s) present"))
    numeric = all(re.fullmatch(r"-?\d+(\.\d+)?", str(p.get("weight"))) for p in prizes)
    out.append((numeric, "all prize weights are numeric"))
    routed = all((p.get("journeyPrizeSettings") or {}).get("journeyId") for p in prizes)
    out.append((routed, "every prize routes to a journeyId"))
    dates = [body.get(k) for k in ("showDate", "startDate", "endDate", "hideDate")]
    out.append((all(dates) and dates == sorted(dates), "dates ordered show ≤ start ≤ end ≤ hide"))
    out.append((bool(body.get("internalName")), "internalName set"))
    out.append((bool(body.get("urlShortName")), "urlShortName set"))
    out.append((bool(body.get("contentId") and body.get("frontId")), "visual contentId + frontId present"))
    return out


JS_TEMPLATE = r"""// Randomizer console script — @LABEL@ — generated @GENERATED_AT@
// randomizers: @INTERNAL_NAME@
//
// Paste into the DevTools console on a logged-in backoffice tab. It:
//   1. captures the auth token from the page's own requests,
//   2. for EACH randomizer in the batch: creates a draft
//      (POST /promo/v2/promo-drafts/randomizer) then fills it (@FLOW_DESC@).
// One bad one doesn't stop the rest; a summary prints at the end.
// Set PREVIEW=true to log the request bodies WITHOUT sending them.
(async () => {
  'use strict';
  const PREVIEW = false;
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const FLOW = @FLOW@;             // 'create_put' | 'draftid_post'
  const PAYLOADS = @PAYLOADS@;     // one randomizer body per date
  const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');

  const decodeJwt = (t) => { try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch (e) { return null; } };
  const usableAuth = (v) => {
    if (!v || !/^Bearer\s+\S+/i.test(v)) return null;
    const p = decodeJwt(v.replace(/^Bearer\s+/i, ''));
    if (!p || p.typ !== 'Bearer' || p.exp - Date.now()/1000 < 30) return null;
    return 'Bearer ' + v.replace(/^Bearer\s+/i, '');
  };
  async function obtainAuth() {
    if (MANUAL_TOKEN.trim()) { const a = usableAuth('Bearer ' + MANUAL_TOKEN.trim()); if (!a) throw new Error('MANUAL_TOKEN invalid'); return a; }
    return new Promise((resolve, reject) => {
      let done = false; const of = window.fetch, oh = XMLHttpRequest.prototype.setRequestHeader;
      const clean = () => { window.fetch = of; XMLHttpRequest.prototype.setRequestHeader = oh; };
      const take = (v) => { const a = usableAuth(v); if (a && !done) { done = true; clean(); clearTimeout(t); console.log('%cToken captured.', 'color:#22c55e'); resolve(a); } };
      window.fetch = function (i, n) { try { const h = (n && n.headers) || (i && i.headers); if (h) { if (typeof h.get === 'function') take(h.get('authorization')); else take(h.authorization || h.Authorization); } } catch (e) {} return of.apply(this, arguments); };
      XMLHttpRequest.prototype.setRequestHeader = function (k, v) { try { if (/^authorization$/i.test(k)) take(v); } catch (e) {} return oh.apply(this, arguments); };
      const t = setTimeout(() => { if (!done) { done = true; clean(); reject(new Error('No token in 3 min. Click around the UI and rerun.')); } }, 180000);
      console.log('%cWaiting for a token — click anything in the backoffice UI.', 'color:#eab308');
    });
  }

  const auth = await obtainAuth();
  const headers = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'content-type': 'application/json', 'x-brand': BRAND });

  if (PREVIEW) {
    console.log('%cPREVIEW — not sending. ' + PAYLOADS.length + ' randomizer(s):', 'color:#eab308;font-weight:bold');
    PAYLOADS.forEach((P) => console.log(P.internalName + '  (' + P.showDate + ')', P));
    return;
  }

  // create one draft then fill it; returns the new draft id
  async function createOne(P) {
    let r = await fetch(CRM_BASE + '/promo/v2/promo-drafts/randomizer', { method: 'POST', headers: headers(), credentials: 'include', body: JSON.stringify(P) });
    let resp = await r.text();
    if (!r.ok) throw new Error('create HTTP ' + r.status + ' ' + resp);
    let created = {}; try { created = JSON.parse(resp); } catch (e) {}
    const id = created.id || created.draftId || created.promotionDraftId || (created.data && created.data.id);
    if (!id) throw new Error('no draft id in create response: ' + resp);
    if (FLOW === 'draftid_post') {
      r = await fetch(CRM_BASE + '/promo/v2/randomizer?draftId=' + encodeURIComponent(id), { method: 'POST', headers: headers(), credentials: 'include', body: JSON.stringify(P) });
    } else {
      // the fill model wants id as a STRING (a numeric id 400s with
      // "$.id could not be converted to System.String").
      r = await fetch(CRM_BASE + '/promo/v2/randomizer/' + encodeURIComponent(id), { method: 'PUT', headers: headers(), credentials: 'include', body: JSON.stringify({ ...P, id: String(id) }) });
    }
    resp = await r.text();
    if (!r.ok) throw new Error('draft ' + id + ' created but fill failed HTTP ' + r.status + ' ' + resp);
    return id;
  }

  console.log('Creating ' + PAYLOADS.length + ' randomizer draft(s)...');
  const ok = [], fail = [];
  for (const P of PAYLOADS) {
    console.log('  ' + P.internalName + ' ...');
    try { const id = await createOne(P); ok.push({ name: P.internalName, id }); console.log('%c    ✓ ' + id, 'color:#22c55e'); }
    catch (e) { const msg = String((e && e.message) || e); fail.push({ name: P.internalName, err: msg }); console.error('    ✗ ' + P.internalName + ' — ' + msg); }
  }

  console.log('%cDONE — ' + ok.length + ' created, ' + fail.length + ' failed.',
              'color:' + (fail.length ? '#f59e0b' : '#22c55e') + ';font-weight:bold;font-size:14px');
  ok.forEach((o) => console.log('  ✓ ' + o.id + '  (' + o.name + ')'));
  fail.forEach((f) => console.log('  ✗ ' + f.name + ' — ' + f.err));
})();
"""

FLOW_DESC = {
    "create_put": "PUT /promo/v2/randomizer/<id>",
    "draftid_post": "POST /promo/v2/randomizer?draftId=<id>",
}


def build_js(kind: str, bodies: list[dict]) -> str:
    cfg = KINDS[kind]
    brand = (bodies[0].get("currencies") or [{}])[0].get("brand", "JBCL")
    names = ", ".join(str(b.get("internalName", "")) for b in bodies)
    header = f"{len(bodies)}: {names}"
    js = JS_TEMPLATE
    js = js.replace("@LABEL@", cfg["label"])
    js = js.replace("@GENERATED_AT@", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"))
    js = js.replace("@INTERNAL_NAME@", header)
    js = js.replace("@FLOW_DESC@", FLOW_DESC[cfg["flow"]])
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(brand))
    js = js.replace("@FLOW@", json.dumps(cfg["flow"]))
    js = js.replace("@PAYLOADS@", json.dumps(bodies, ensure_ascii=False))
    return js


def _split_dates(raw: list[str]) -> list[str]:
    """Flatten dates given as repeated args and/or comma/space/newline lists."""
    out: list[str] = []
    for chunk in raw:
        for tok in re.split(r"[\s,;]+", chunk.strip()):
            if tok:
                out.append(tok)
    # de-dupe, keep order
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d); uniq.append(d)
    return uniq


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kind", required=True, choices=sorted(KINDS), help="which randomizer to build")
    p.add_argument("--date", help="single promo date YYYY-MM-DD (UTC promo day)")
    p.add_argument("--dates", nargs="+", help="MANY promo dates -> one draft each, created in one script "
                                              "(space/comma/newline separated, e.g. 2026-07-22 2026-07-29)")
    p.add_argument("--days", type=int, help="window length in days (default per kind)")
    p.add_argument("--internal-name", default="", help="override internalName (single date only)")
    p.add_argument("--url-short", default="", help="override urlShortName (single date only)")
    p.add_argument("--weights", nargs="+", help="prize weights, in template prize order (applied to every date)")
    p.add_argument("--journeys", nargs="+", help="routed journeyIds, in template prize order (applied to every date)")
    p.add_argument("--name", default="", help="output basename (default: <kind>)")
    p.add_argument("--dry-run", action="store_true", help="write the prepared bodies to out/ instead of a script")
    args = p.parse_args()

    dates = _split_dates(args.dates) if args.dates else ([args.date] if args.date else [])
    if not dates:
        print("Pass --date YYYY-MM-DD, or --dates D1 D2 ... for a batch.", file=sys.stderr)
        return 1
    if len(dates) > 1 and (args.internal_name or args.url_short):
        print("--internal-name/--url-short only make sense with a single date "
              "(each date is auto-named); drop them for a batch.", file=sys.stderr)
        return 1

    bodies: list[dict] = []
    print(f"{KINDS[args.kind]['label']} — {len(dates)} randomizer(s):")
    for d in dates:
        body, report = prepare(
            args.kind, d, days=args.days,
            internal_name=args.internal_name, url_short=args.url_short,
            weights=args.weights, journeys=args.journeys,
        )
        bodies.append(body)
        print(f"  • {d}:")
        for line in report:
            print("      " + line)

    print("Verification:")
    all_ok = True
    for body in bodies:
        for ok, msg in verify(body):
            if not ok:
                print(f"  FAIL [{body.get('internalName')}] {msg}")
            all_ok = all_ok and ok
    print(f"  {'OK  ' if all_ok else 'FAIL'} {len(bodies)} body(ies) verified")
    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    basename = args.name or args.kind
    if args.dry_run:
        out = Path("out"); out.mkdir(exist_ok=True)
        path = out / f"{basename}_randomizer.json"
        payload = bodies[0] if len(bodies) == 1 else bodies
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — {len(bodies)} body(ies) written: {path}")
        return 0

    js = build_js(args.kind, bodies)
    out = Path("console_scripts"); out.mkdir(exist_ok=True)
    path = out / f"{basename}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(bodies)} randomizer(s) in one paste)")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    print("Tip: set PREVIEW=true at the top of the script to inspect the request bodies first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
