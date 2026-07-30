#!/usr/bin/env python3
"""Build the console script for a Randomizer promo — Sport Wheel of Fortune,
Casino Wheel of Fortune, or Raspa y Gana (Scratch Card).

A randomizer is a weighted set of prize slices; each slice routes a winning
player to a journey (journeyId + activityId). We keep the captured prize table,
segment (filterConditions) and visual bundle (contentId/frontId) from the
template and only re-date + re-name the promo for a new run. Prize weights and
the routed journeys can be overridden.

Creation flow (all three kinds, matching the Sport WOF console script):

  POST /promo/v2/promo-drafts/randomizer   -> create the draft, returns a
                                              numeric draft id
  POST /promo/v2/randomizer?draftId=<id>   -> fill that draft with the body

(The PUT /promo/v2/randomizer/<id> variant expects a different randomization
GUID and 422s "Invalid Randomization identifier" on the numeric draft id, so we
use the query-param fill the working Sport WOF script uses.)

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
        # Rebuilt from 45a1240c-wheeloffort_new.har, which captured the WHOLE
        # flow the earlier HAR had missed: the wheel's visual content tree is
        # CLONED to a fresh pair of ids per draft, then overwritten. Without it
        # every wheel ever generated shared one contentId/frontId, so editing
        # this week's artwork rewrote every past and published wheel.
        "flow": "visual_clone",
        "save_template": HERE / "templates" / "sport" / "sport_wof_save.json",
        "visual": HERE / "templates" / "sport" / "wof_visual" / "uploads.json",
        # The master tree each draft's content is copied FROM. Read-only: the
        # copy's destination is a fresh uuid minted per draft at paste time.
        "master_content": "75f9a86c-3b6a-42da-b631-cc726b8b1515",
        "master_front": "a3d6d412-f4a1-41b2-8742-fde6dd223c20",
        # The wheel background lives outside the per-wheel tree, in a shared
        # folder, so it is kept unless the operator picks a new one.
        "background": "mf/v1/background/3678a524-8573-4600-8b04-f7fa2cfaea2a.png",
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
        # Same fill as Sport WOF: POST /promo/v2/randomizer?draftId=<numeric draft
        # id>. The PUT /randomizer/<id> variant wants a different randomization
        # GUID and 422s "Invalid Randomization identifier" on the draft id.
        "flow": "draftid_post",
        "name_prefix": "JBCL|CS|WOF|",
        "name_fmt": "%d.%m.%y",
        "days_default": 1,
        "date_offsets": {"show": (0, "04:01"), "start": (0, "04:02"),
                         "end": ("+days", "03:58"), "hide": ("+days", "03:59")},
        # urlShortName must be globally unique (a bare date 409s
        # "UrlShortNameAlreadyUsed"); prefix it per type like Sport WOF.
        "url_short": lambda promo, end: f"casino-wof-{promo.day:02d}-{promo.month:02d}-{promo.year}",
    },
    "casino_scratch": {
        "label": "Raspa y Gana (Scratch Card)",
        "template": HERE / "templates" / "casino" / "raspaygana_scratchcard.json",
        "flow": "draftid_post",   # same query-param fill as Sport WOF
        "name_prefix": "FTCL|CS|FDSC|",
        "name_fmt": "%d.%m",
        "days_default": 2,
        "date_offsets": {"show": (0, "04:00"), "start": (0, "04:01"),
                         "end": ("+days", "03:59"), "hide": ("+days", "04:00")},
        "url_short": lambda promo, end: f"raspa-{promo.day:02d}-{promo.month:02d}-{promo.year}",
    },
}


# The capture shipped four of its seven slices showing the operator's INTERNAL
# journey name to players ("JBCL | SP | RB - Wheel of fortune | Free | Bonuses")
# because whoever built it never replaced the placeholder the wheel editor
# pre-fills with. Player-facing copy never looks like this, so it is refused
# rather than warned about — the whole point of this generator is that the
# captured campaign's leftovers cannot ship.
INTERNAL_COPY_RE = re.compile(r"\b[A-Z]{4}\s*\|\s*[A-Z]{2}\s*\|", re.I)

CONTENT_ID_TOKEN = "%%CONTENT_ID%%"
FRONT_ID_TOKEN = "%%FRONT_ID%%"


def strip_html(text: str) -> str:
    """The bare words of a prizeTextKey, for comparing against an internal name."""
    return re.sub(r"<[^>]+>", " ", text or "").replace("&nbsp;", " ").strip()


def live_prize_ids(body: dict) -> list[str]:
    """The activityId of every prize the draft actually routes to, in order."""
    return [(p.get("journeyPrizeSettings") or {}).get("activityId") or ""
            for p in body.get("prizes", [])]


def set_prize_text(uploads: list, activity_id: str, en: str, es: str) -> int:
    """Write one slice's player-facing copy into all four content files.

    A wheel's copy lives four times — spa and widget, each EN and ES — keyed by
    `prize_<activityId>.prizeTextKey`. Writing one and not the others shows the
    right text on the wheel and the wrong text in the widget beside it.
    """
    key = f"prize_{activity_id}.prizeTextKey"
    writes = 0
    for f in uploads:
        data = f.get("data")
        if not isinstance(data, dict) or key not in data:
            continue
        data[key] = es if "-es-" in f["rel"] else en
        writes += 1
    return writes


def prune_dead_prize_keys(uploads: list, keep: set) -> list:
    """Drop prize copy for slices this wheel no longer has.

    The capture carried copy for three removed slices plus four numeric orphans
    (`prize_1`, `prize_2`, ...) left by earlier edits. They are content still
    shared with the captured campaign, so they go.
    """
    dropped = []
    for f in uploads:
        data = f.get("data")
        if not isinstance(data, dict):
            continue
        for key in [k for k in data if k.startswith("prize_") and k.endswith(".prizeTextKey")]:
            who = key[len("prize_"):-len(".prizeTextKey")]
            if who not in keep:
                data.pop(key)
                dropped.append(who)
    return sorted(set(dropped))


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


# ── the visual-clone flow (Sport WOF) ───────────────────────────────────────
def parse_prize_text(text: str) -> list[tuple[str, str]]:
    """EN/ES prize copy, one tab-separated line per slice, in template order."""
    rows = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = [c.strip() for c in line.split("\t")]
        en = parts[0] if parts else ""
        es = parts[1] if len(parts) > 1 and parts[1] else en
        rows.append((en, es))
    return rows


def prepare_visual(kind: str, date_str: str, *, days: int | None = None,
                   internal_name: str = "", url_short: str = "",
                   weights: list[str] | None = None, journeys: list[str] | None = None,
                   prize_text: str = "") -> tuple[dict, list[str]]:
    """A Sport WOF draft plus its own freshly-cloned visual content tree."""
    cfg = KINDS[kind]
    create, report = prepare(kind, date_str, days=days, internal_name=internal_name,
                             url_short=url_short, weights=weights, journeys=journeys)
    save = json.loads(cfg["save_template"].read_text(encoding="utf-8"))
    uploads = json.loads(cfg["visual"].read_text(encoding="utf-8"))

    # the save body mirrors the create body's per-run values
    for key in ("showDate", "startDate", "endDate", "hideDate",
                "internalName", "urlShortName", "prizes"):
        save[key] = json.loads(json.dumps(create[key]))
    for prize in save.get("prizes", []):
        prize["id"] = None                      # the save posts prizes without ids
    save["initialShowDate"], save["initialEndDate"] = create["showDate"], create["endDate"]

    ids = live_prize_ids(create)
    if not all(ids):
        raise SystemExit("a prize slice has no activityId — the template changed shape.")
    dropped = prune_dead_prize_keys(uploads, set(ids))
    if dropped:
        report.append(f"dropped copy for {len(dropped)} slice(s) this wheel no longer has")

    rows = parse_prize_text(prize_text)
    if rows:
        if len(rows) != len(ids):
            raise SystemExit(f"--prize-text has {len(rows)} line(s) but the wheel has "
                             f"{len(ids)} prize slice(s), one line each (EN<TAB>ES).")
        for activity_id, (en, es) in zip(ids, rows):
            if not set_prize_text(uploads, activity_id, en, es):
                raise SystemExit(f"prize {activity_id} has no copy slot in the visual "
                                 f"content — the template changed shape.")
        report.append(f"prize copy written for {len(rows)} slice(s)")

    # refuse rather than warn: a slice still wearing its journey's internal name
    internal = []
    for activity_id, prize in zip(ids, create.get("prizes", [])):
        key = f"prize_{activity_id}.prizeTextKey"
        for f in uploads:
            data = f.get("data") or {}
            if key in data and INTERNAL_COPY_RE.search(strip_html(data[key])):
                label = (prize.get("journeyPrizeSettings") or {}).get("activityDescription", "")
                internal.append(f"{activity_id} ({label.strip()[:40]}): {strip_html(data[key])[:44]!r}")
                break
    if internal:
        raise SystemExit(
            "these prize slices would show your INTERNAL journey name to players:\n  - "
            + "\n  - ".join(internal)
            + "\n\nGive player-facing copy for every slice with --prize-text "
              "(one line per slice, in wheel order, EN<TAB>ES)."
        )

    bundle = {"kind": kind, "create": create, "save": save, "uploads": uploads,
              "prize_ids": ids, "background": cfg["background"],
              "master_content": cfg["master_content"], "master_front": cfg["master_front"]}
    report.append(f"visual: {len(uploads)} file(s) uploaded into a freshly cloned tree")
    return bundle, report


def verify_visual(bundle: dict) -> list[tuple[bool, str]]:
    create, save, uploads = bundle["create"], bundle["save"], bundle["uploads"]
    blob = json.dumps(create) + json.dumps(save) + json.dumps(uploads, ensure_ascii=False)
    cfg = KINDS[bundle["kind"]]
    ids = bundle["prize_ids"]

    out = list(verify(create))
    weights = [float(p.get("weight")) for p in create.get("prizes", [])]
    out.append((abs(sum(weights) - 100.0) < 0.01,
                f"prize weights sum to 100 ({sum(weights):g})"))
    out.append((create.get("contentId") == CONTENT_ID_TOKEN
                and create.get("frontId") == FRONT_ID_TOKEN,
                "contentId + frontId are per-draft placeholders, not the captured pair"))
    out.append((cfg["master_content"] not in blob and cfg["master_front"] not in blob,
                "the master content tree is only a copy SOURCE, never a destination"))
    stale = [k for f in uploads if isinstance(f.get("data"), dict)
             for k in f["data"] if k.startswith("prize_") and k.endswith(".prizeTextKey")
             and k[len("prize_"):-len(".prizeTextKey")] not in set(ids)]
    out.append((not stale, "no copy left for slices this wheel does not have"
                + (f" (STALE: {stale[:2]})" if stale else "")))
    missing = [i for i in ids
               if not any(f"prize_{i}.prizeTextKey" in (f.get("data") or {}) for f in uploads)]
    out.append((not missing, "every prize slice has copy"
                + (f" (MISSING: {missing[:2]})" if missing else "")))
    internal = [k for f in uploads if isinstance(f.get("data"), dict)
                for k, v in f["data"].items()
                if k.endswith(".prizeTextKey") and INTERNAL_COPY_RE.search(strip_html(v))]
    out.append((not internal, "no slice shows an internal journey name to players"
                + (f" (INTERNAL: {internal[:2]})" if internal else "")))
    out.append((create["showDate"] == save["initialShowDate"]
                and create["endDate"] == save["initialEndDate"],
                "create and save agree on the wheel's window"))
    out.append((create["internalName"] == save["internalName"]
                and create["urlShortName"] == save["urlShortName"],
                "create and save agree on the name"))
    return out



JS_VISUAL_TEMPLATE = r"""// Sport Wheel of Fortune — @INTERNAL_NAME@ — generated @GENERATED_AT@
//
// Paste into the DevTools console on a logged-in backoffice tab. Per wheel it:
//   1. mints a FRESH contentId + frontId (so this wheel owns its own visual —
//      sharing one pair across wheels meant editing today's artwork rewrote
//      every past and published wheel),
//   2. clones the master content tree into that pair (POST /contents/v1/copy),
//   3. creates the draft (POST /promo/v2/promo-drafts/randomizer),
//   4. uploads the 8 visual files into the new tree (POST /promo/v2/s3/upload),
//   5. saves the draft (PUT /promo/v2/promo-drafts/randomizer/<id>?draftId=<id>).
// Drafts only — nothing is published. One bad wheel does not stop the rest.
// Set PREVIEW=true to log every request WITHOUT sending it.
(async () => {
  'use strict';
  const PREVIEW = false;
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const WHEELS = @WHEELS@;              // one {create, save, uploads} per date
  const MASTER_CONTENT = @MASTER_CONTENT@;
  const MASTER_FRONT = @MASTER_FRONT@;
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
  const H = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'content-type': 'application/json', 'x-brand': BRAND });
  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });

  async function send(method, url, body) {
    const r = await fetch(url, { method, headers: H(), credentials: 'include', body: body === undefined ? undefined : JSON.stringify(body) });
    const t = await r.text();
    if (!r.ok) throw new Error(method + ' ' + url.split('/crm/')[1] + ' HTTP ' + r.status + ' ' + t.slice(0, 300));
    try { return JSON.parse(t); } catch (e) { return {}; }
  }

  async function buildOne(W) {
    const contentId = newUuid(), frontId = newUuid();
    const fill = (o) => JSON.parse(JSON.stringify(o).split('%%CONTENT_ID%%').join(contentId).split('%%FRONT_ID%%').join(frontId));
    const create = fill(W.create), save = fill(W.save), uploads = fill(W.uploads);

    if (PREVIEW) {
      console.log('  would clone ' + MASTER_CONTENT + ' -> ' + contentId + ', ' + MASTER_FRONT + ' -> ' + frontId);
      console.log('  create:', create); console.log('  uploads:', uploads.map((u) => u.rel)); console.log('  save:', save);
      return 'PREVIEW';
    }

    // 1. the wheel's own visual tree, cloned from the master
    await send('POST', CRM_BASE + '/contents/v1/copy', { sourcePath: 'mf/v1/' + MASTER_CONTENT, destinationPath: 'mf/v1/' + contentId });
    await send('POST', CRM_BASE + '/contents/v1/copy', { sourcePath: 'mf/v1/' + MASTER_FRONT, destinationPath: 'mf/v1/' + frontId });

    // 2. the draft
    const created = await send('POST', CRM_BASE + '/promo/v2/promo-drafts/randomizer', create);
    const id = created.id || created.draftId || created.promotionDraftId;
    if (!id) throw new Error('no draft id in create response: ' + JSON.stringify(created).slice(0, 200));

    // 3. the visual files, into the NEW tree
    for (const u of uploads) {
      const base = u.target === 'front' ? frontId : contentId;
      await send('POST', CRM_BASE + '/promo/v2/s3/upload', { path: 'mf/v1/' + base + '/' + u.rel, data: u.data });
    }

    // 4. save
    await send('PUT', CRM_BASE + '/promo/v2/promo-drafts/randomizer/' + id + '?draftId=' + id, { ...save, id: String(id) });
    return id;
  }

  console.log('%cSport Wheel of Fortune — ' + WHEELS.length + ' wheel(s)', 'color:#3b82f6;font-weight:bold;font-size:14px');
  const ok = [], fail = [];
  for (const W of WHEELS) {
    console.log('  ' + W.create.internalName + ' ...');
    try { const id = await buildOne(W); ok.push({ name: W.create.internalName, id }); console.log('%c    ✓ draft ' + id, 'color:#22c55e'); }
    catch (e) { const msg = String((e && e.message) || e); fail.push({ name: W.create.internalName, err: msg }); console.error('    ✗ ' + msg); }
  }
  console.log('%cDONE — ' + ok.length + ' created, ' + fail.length + ' failed.',
              'color:' + (fail.length ? '#f59e0b' : '#22c55e') + ';font-weight:bold;font-size:14px');
  ok.forEach((o) => console.log('  ✓ ' + o.id + '  (' + o.name + ')'));
  fail.forEach((f) => console.log('  ✗ ' + f.name + ' — ' + f.err));
  if (!PREVIEW) console.log('Drafts are unpublished — open each in the Promo UI, check the wheel, then publish.');
})();
"""


def build_visual_js(bundles: list) -> str:
    js = JS_VISUAL_TEMPLATE
    first = bundles[0]
    js = js.replace("@GENERATED_AT@", datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"))
    js = js.replace("@INTERNAL_NAME@", ", ".join(b["create"]["internalName"] for b in bundles))
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps((first["create"].get("currencies") or [{}])[0].get("brand", "JBCL")))
    js = js.replace("@MASTER_CONTENT@", json.dumps(first["master_content"]))
    js = js.replace("@MASTER_FRONT@", json.dumps(first["master_front"]))
    js = js.replace("@WHEELS@", json.dumps(
        [{"create": b["create"], "save": b["save"], "uploads": b["uploads"]} for b in bundles],
        ensure_ascii=False))
    return js


JS_TEMPLATE = r"""// Randomizer console script — @LABEL@ — generated @GENERATED_AT@
// randomizers: @INTERNAL_NAME@
//
// Paste into the DevTools console on a logged-in backoffice tab. It:
//   1. captures the auth token from the page's own requests,
//   2. for EACH randomizer in the batch: creates a draft
//      (POST /promo/v2/promo-drafts/randomizer) then fills it (@FLOW_DESC@).
// One bad one doesn't stop the rest; a summary prints at the end.
// Set PREVIEW=true to log the request bodies WITHOUT sending them.
// Set DEBUG=true to create ONE draft and print the create response (to find
// the right fill identifier) without attempting the fill.
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

  // While the exact fill identifier is being confirmed, DEBUG=true creates ONE
  // draft, logs the full create response (so we can see which field is the
  // randomization id), and does NOT attempt the fill — avoids piling up orphans.
  const DEBUG = @DEBUG@;

  // create one draft then fill it; returns the new draft id
  async function createOne(P) {
    let r = await fetch(CRM_BASE + '/promo/v2/promo-drafts/randomizer', { method: 'POST', headers: headers(), credentials: 'include', body: JSON.stringify(P) });
    let resp = await r.text();
    if (!r.ok) throw new Error('create HTTP ' + r.status + ' ' + resp);
    let created = {}; try { created = JSON.parse(resp); } catch (e) {}
    if (DEBUG) {
      console.log('%cCREATE RESPONSE (copy this whole object to share):', 'color:#eab308;font-weight:bold');
      console.log(JSON.stringify(created, null, 2));
      console.log('%ctop-level keys: ' + Object.keys(created).join(', '), 'color:#eab308');
      throw new Error('DEBUG mode — stopped before fill so nothing else is created. See CREATE RESPONSE above.');
    }
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

  const QUEUE = DEBUG ? PAYLOADS.slice(0, 1) : PAYLOADS;
  console.log('Creating ' + QUEUE.length + ' randomizer draft(s)...' + (DEBUG ? ' (DEBUG: 1 only, no fill)' : ''));
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


def build_js(kind: str, bodies: list[dict], debug: bool = False) -> str:
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
    js = js.replace("@DEBUG@", "true" if debug else "false")
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
    p.add_argument("--prize-text", default=None, type=Path,
                   help="Sport WOF: player-facing prize copy, one line per slice in wheel "
                        "order, EN<TAB>ES. '-' reads stdin. Required whenever a slice still "
                        "carries its journey's internal name.")
    p.add_argument("--name", default="", help="output basename (default: <kind>)")
    p.add_argument("--dry-run", action="store_true", help="write the prepared bodies to out/ instead of a script")
    p.add_argument("--debug", action="store_true", help="emit a script that creates ONE draft and logs the create "
                                                        "response without filling (to inspect the id fields)")
    args = p.parse_args()

    dates = _split_dates(args.dates) if args.dates else ([args.date] if args.date else [])
    if not dates:
        print("Pass --date YYYY-MM-DD, or --dates D1 D2 ... for a batch.", file=sys.stderr)
        return 1
    if len(dates) > 1 and (args.internal_name or args.url_short):
        print("--internal-name/--url-short only make sense with a single date "
              "(each date is auto-named); drop them for a batch.", file=sys.stderr)
        return 1

    visual = KINDS[args.kind].get("flow") == "visual_clone"
    prize_text = ""
    if args.prize_text:
        prize_text = (sys.stdin.read() if str(args.prize_text) == "-"
                      else Path(args.prize_text).read_text(encoding="utf-8"))

    bodies: list[dict] = []
    print(f"{KINDS[args.kind]['label']} — {len(dates)} randomizer(s):")
    for d in dates:
        if visual:
            item, report = prepare_visual(
                args.kind, d, days=args.days,
                internal_name=args.internal_name, url_short=args.url_short,
                weights=args.weights, journeys=args.journeys, prize_text=prize_text,
            )
        else:
            item, report = prepare(
                args.kind, d, days=args.days,
                internal_name=args.internal_name, url_short=args.url_short,
                weights=args.weights, journeys=args.journeys,
            )
        bodies.append(item)
        print(f"  • {d}:")
        for line in report:
            print("      " + line)

    print("Verification:")
    all_ok = True
    seen_urls: set = set()
    for item in bodies:
        body = item["create"] if visual else item
        for ok, msg in (verify_visual(item) if visual else verify(body)):
            if not ok:
                print(f"  FAIL [{body.get('internalName')}] {msg}")
            all_ok = all_ok and ok
        # urlShortName is unique server-side; a batch that repeats one 409s on
        # the second wheel, after the first has already been created.
        url = body.get("urlShortName")
        if url in seen_urls:
            print(f"  FAIL two wheels in this batch share urlShortName {url!r}")
            all_ok = False
        seen_urls.add(url)
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

    js = build_visual_js(bodies) if visual else build_js(args.kind, bodies, debug=args.debug)
    out = Path("console_scripts"); out.mkdir(exist_ok=True)
    path = out / f"{basename}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(bodies)} randomizer(s) in one paste)")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    print("Tip: set PREVIEW=true at the top of the script to inspect the request bodies first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
