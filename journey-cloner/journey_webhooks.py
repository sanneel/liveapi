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
A journey stores only the webhookId. The URL around it is
https://webhooks.flw.rest/<webhookId>/, read off an API node in the UI, and
--url-template changes it in one place if that ever moves.

It prints the table twice: aligned for reading, and tab separated for a
spreadsheet. The tab-separated block pastes straight into Google Sheets, and
the CSV written next to the script imports there through File > Import.

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

# The URL the integration is given. The journey only stores the id; this is the
# shape the backoffice shows next to it, taken from an API node in the UI.
# --url-template overrides it if it ever changes.
WEBHOOK_URL_TEMPLATE = "https://webhooks.flw.rest/{id}/"


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
  const URL_TEMPLATE = @URL_TEMPLATE@;
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
  function webhookUrlFor(activity) {
    const init = activity.initializationData || {};
    const direct = init.webhookUrl || init.url;          // if a read ever carries it
    if (direct) return direct;
    if (!init.webhookId) return '';
    return URL_TEMPLATE.includes('{') ? URL_TEMPLATE.replace(/\{[^}]*\}/, init.webhookId)
         : URL_TEMPLATE.replace(/\/+$/, '') + '/' + init.webhookId + '/';
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
        url: webhookUrlFor(api),
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
  console.log('%cThe table:', 'color:#3b82f6;font-weight:bold');
  console.log(text);

  const HEAD = ['Amount (CLP)', 'Prize', 'Webhook URL', 'Journey ID', 'Webhook ID'];
  const cells = rows.map((r) => [r.amount, r.prize, r.url || r.webhookId, r.id, r.webhookId]);
  const tsv = [HEAD, ...cells].map((r) => r.join('\t')).join('\n');
  const csv = [HEAD, ...cells].map((r) => r.map((c) => /[",\n]/.test(c) ? '"' + String(c).replace(/"/g, '""') + '"' : c).join(',')).join('\n');
  console.log('%cFor Google Sheets — select this block and paste into A1:', 'color:#3b82f6;font-weight:bold');
  console.log(tsv);
  window.__webhookRows = rows;
  window.__webhookTsv = tsv;
  window.__webhookCsv = csv;
  console.log('copy(window.__webhookTsv) puts the sheet block on the clipboard; copy(window.__webhookCsv) gives a CSV.');
  try { await navigator.clipboard.writeText(tsv); console.log('%cThe sheet block is on your clipboard: paste into A1.', 'color:#22c55e'); }
  catch (e) { console.log('Clipboard blocked — run copy(window.__webhookTsv) and paste into A1.'); }
  if (rows.some((r) => !r.url)) {
    console.log('%c' + rows.filter((r) => !r.url).length + ' journey(s) had no webhookId, so their id column is empty.', 'color:#eab308;font-weight:bold');
  }
})();
"""

JS_TEMPLATE = inject(JS_TEMPLATE)


def build_js(ids: list[str], url_template: str = WEBHOOK_URL_TEMPLATE) -> str:
    js = JS_TEMPLATE
    js = js.replace("@URL_TEMPLATE@", json.dumps(url_template))
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
    p.add_argument("--url-template", default=WEBHOOK_URL_TEMPLATE,
                   help=f"the URL around a webhook id (default: {WEBHOOK_URL_TEMPLATE})")
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
    path.write_text(build_js(ids, args.url_template), encoding="utf-8")
    print(f"\nConsole script written: {path}  ({len(ids)} journey(s))")
    print("Paste it into the DevTools console on a logged-in backoffice tab. It only reads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
