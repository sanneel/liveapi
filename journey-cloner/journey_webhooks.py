#!/usr/bin/env python3
"""List the API (webhook) entry of a set of journeys: amount, rollover, URL.

Read-only. Give it the JRN ids the journey list prints and it emits a console
script that fetches each journey, finds its external_system_source activity and
writes the table the gamification prizes need handed to Smartico:

    10 000    5x            https://…/<webhookId>
    15 000    5x            https://…/<webhookId>
    90 000    money bonus   https://…/<webhookId>

The amount and the rollover are read out of the journey's own bonus activity,
not parsed from its name, so a journey whose name and payload disagree shows
what it actually grants.

THE URL
-------
A journey carries the webhookId; the full URL is composed by the backoffice and
was not in any capture here. The script therefore tries, in order: a webhookUrl
already on the activity, then the backoffice's own external-system-source
endpoint, and falls back to printing the id with the raw response of that
endpoint so the pattern can be baked in. Copy one URL out of an API node in the
UI and it becomes a one-line change.

Usage:
  python journey_webhooks.py --ids JRN-0-685173,JRN-0-685175
  python journey_webhooks.py --ids-file ids.txt --name gamif_webhooks
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from create_journeys import LOCAL_TZ
from console_js import inject

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "console_scripts"

BRAND = "JBCL"
BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"

JRN_RE = re.compile(r"^JRN-\d+-\d+$", re.IGNORECASE)


def parse_ids(raw: str) -> tuple[list[str], list[str]]:
    """Ids from a comma, space or newline separated blob, in the order given."""
    ids: list[str] = []
    problems: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\s,]+", raw or ""):
        t = token.strip()
        if not t:
            continue
        if not JRN_RE.match(t):
            problems.append(f"{t!r} is not a JRN id")
            continue
        key = t.upper()
        if key in seen:
            problems.append(f"{t} listed twice")
            continue
        seen.add(key)
        ids.append(t)
    return ids, problems


def verify(ids: list[str]) -> list[tuple[bool, str]]:
    return [
        (bool(ids), "at least one journey id"),
        (all(JRN_RE.match(i) for i in ids), "every id is a JRN id"),
        (len({i.upper() for i in ids}) == len(ids), "no id listed twice"),
    ]


JS_TEMPLATE = r"""// Webhook URLs for @COUNT@ journey(s) — generated @GENERATED_AT@
// Read-only: it fetches each journey, reads its API node and its bonus, and
// prints the amount / rollover / webhook table. Nothing is created or changed.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
@API_BASE_JS@
  const BASE = apiBase(@BASE_URL@);
  const BRAND = @BRAND@;
  const IDS = @IDS@;
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
  const H = (ct) => { const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND }; if (ct) h['content-type'] = ct; return h; };
@JSON_GUARD_JS@
  const walk = (o, fn) => {
    if (Array.isArray(o)) { o.forEach((v) => walk(v, fn)); return; }
    if (o && typeof o === 'object') { fn(o); Object.values(o).forEach((v) => walk(v, fn)); }
  };
  const spaced = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

  async function getJourney(id) {
    const r = await fetch(BASE + '/journeys/' + id, { headers: H(), credentials: 'include' });
    const t = await r.text();
    if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + t.slice(0, 160));
    return parseJsonText(t, 'journey ' + id, r.status);
  }

  // The URL is composed by the backoffice, not stored on the activity, so it is
  // asked for once and reused. Whatever this endpoint answers is printed raw the
  // first time, which is how the shape gets pinned down for good.
  let urlTemplate = null, configShown = false;
  async function webhookUrlFor(id, activity) {
    const direct = activity.initializationData && (activity.initializationData.webhookUrl || activity.initializationData.url);
    if (direct) return direct;
    if (urlTemplate === null) {
      urlTemplate = '';
      try {
        const r = await fetch(BASE + '/journey-activities/external-system-source', { headers: H(), credentials: 'include' });
        const t = await r.text();
        if (r.ok) {
          if (!configShown) { console.log('    external-system-source config:', t.slice(0, 400)); configShown = true; }
          const m = t.match(/https?:\/\/[^"'\s]+/);
          if (m) urlTemplate = m[0];
        }
      } catch (e) {}
    }
    if (!urlTemplate) return '';
    const wid = activity.initializationData.webhookId;
    return urlTemplate.includes('{') ? urlTemplate.replace(/\{[^}]*\}/, wid)
         : urlTemplate.replace(/\/+$/, '') + '/' + wid;
  }

  // What the journey actually grants, read from the mechanic rather than from
  // the name: a money bonus keeps major units, a casino bonus minor units with
  // a _majorUnits twin, and the rollover is the casino bonus's own.
  function prizeOf(j) {
    let major = null, rollover = null, kind = '';
    walk(j, (o) => {
      if ('fixedBonusAmount_majorUnits' in o) { major = o.fixedBonusAmount_majorUnits; kind = 'casino bonus'; }
      if (Array.isArray(o.currencyAmounts)) for (const c of o.currencyAmounts) if (typeof c.amount === 'number') { major = c.amount; kind = 'money bonus'; }
      if (typeof o.wageringRequirement === 'number') rollover = o.wageringRequirement;
    });
    return { major: major, rollover: kind === 'casino bonus' ? rollover : null, kind: kind };
  }

  console.log('%cWebhook URLs — ' + IDS.length + ' journey(s)', 'color:#3b82f6;font-weight:bold;font-size:14px');
  const rows = [], missing = [];
  for (const id of IDS) {
    try {
      const j = await getJourney(id);
      const api = (j.activities || []).find((a) => a.activityName === 'external_system_source');
      if (!api) { missing.push({ id: id, name: j.journeyName, why: 'does not start at an API node' }); continue; }
      const wid = (api.initializationData || {}).webhookId || '';
      if (!wid) { missing.push({ id: id, name: j.journeyName, why: 'the API node carries no webhookId' }); continue; }
      const p = prizeOf(j);
      rows.push({
        id: id,
        name: (j.journeyName || '').trim(),
        amount: p.major === null ? '?' : spaced(p.major),
        prize: p.rollover ? p.rollover + 'x' : (p.kind || '?'),
        webhookId: wid,
        url: await webhookUrlFor(id, api),
      });
      console.log('    ' + id + '  ' + (j.journeyName || '').trim());
    } catch (e) {
      missing.push({ id: id, why: String((e && e.message) || e) });
      console.error('    ✗ ' + id + ' — ' + String((e && e.message) || e));
    }
  }

  console.log('%c' + rows.length + ' of ' + IDS.length + ' read.', 'color:' + (rows.length === IDS.length ? '#22c55e' : '#f59e0b') + ';font-weight:bold;font-size:14px');
  if (rows.length) console.table(rows);
  if (missing.length) { console.log('%cNot listed:', 'color:#f59e0b;font-weight:bold'); console.table(missing); }

  const pad = (s, n) => String(s).padEnd(n);
  const text = rows.map((r) => pad(r.amount, 10) + pad(r.prize, 14) + (r.url || r.webhookId)).join('\n');
  console.log('%cThe table, ready to copy:', 'color:#3b82f6;font-weight:bold');
  console.log(text);
  const tsv = rows.map((r) => [r.amount, r.prize, r.url || r.webhookId, r.id, r.name].join('\t')).join('\n');
  window.__webhookRows = rows;
  window.__webhookTsv = tsv;
  try { await navigator.clipboard.writeText(text); console.log('%cCopied to the clipboard.', 'color:#22c55e'); }
  catch (e) { console.log('Clipboard blocked; copy the block above, or copy(window.__webhookTsv) for a spreadsheet.'); }
  if (rows.some((r) => !r.url)) {
    console.log('%cNo URL came back for ' + rows.filter((r) => !r.url).length + ' of them, so the ids are shown instead.', 'color:#eab308;font-weight:bold');
    console.log('Open one journey\'s API node, copy its Webhook URL, and send it — the pattern then fills in for every row.');
  }
})();
"""

JS_TEMPLATE = inject(JS_TEMPLATE)


def build_js(ids: list[str]) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@COUNT@", str(len(ids)))
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@IDS@", json.dumps(ids))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ids", default="", help="JRN ids, comma or space separated")
    p.add_argument("--ids-file", default="", help="file of JRN ids, or '-' for stdin")
    p.add_argument("--name", default="journey_webhooks", help="output basename")
    args = p.parse_args()

    raw = args.ids
    if args.ids_file:
        raw += "\n" + (sys.stdin.read() if args.ids_file == "-" else Path(args.ids_file).read_text(encoding="utf-8"))
    ids, problems = parse_ids(raw)
    for w in problems:
        print(f"  WARN  {w}", file=sys.stderr)
    for good, label in verify(ids):
        print(f"  {'ok  ' if good else 'FAIL'}   {label}")
    if not all(good for good, _ in verify(ids)):
        print("\nnothing written.", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{args.name}_console.js"
    path.write_text(build_js(ids), encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(ids)} journey(s))")
    print("Paste it into the DevTools console on a logged-in backoffice tab. It only reads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
