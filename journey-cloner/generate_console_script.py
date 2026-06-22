#!/usr/bin/env python3
"""
Generate a browser-console script that creates the 4 journey drafts.

Use this when the machine that can reach the Journey Builder API (work
laptop on the office VPN) cannot run Python. The payloads are prepared
and verified here, embedded into a single JS file, and the JS does only
the API calls: capture the auth token from the page's own requests,
reserve real JRN ids, link the 2H campaign connector to the new
FollowUp, recompute "start now" times, POST the drafts.

Usage:
  python generate_console_script.py --match "UDCH vs Calera" --code DALELEON \
      --date 2026-06-14 --time 15:00

Then paste the generated console_scripts/<CODE>_console.js into Chrome
DevTools console on a logged-in backoffice tab. No token copying needed:
the script captures it automatically from the page's next API request.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from create_journeys import (
    BASE_URL,
    BRAND,
    DEFAULT_TEAM,
    LOCAL_TZ,
    TEAMS,
    TYPE_ORDER,
    collect_old_values,
    load_template,
    prepare_body,
    print_checks,
    resolve_team,
    template_files,
    verify_body,
)

DEFAULT_BASE_URL = (
    "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
)

# Markers are replaced with json.dumps()-encoded values; %-formatting is not
# used because the JS contains literal % characters (console styling).
JS_TEMPLATE = """\
// Journey Cloner console script — generated @GENERATED_AT@
// Campaign: @CAMPAIGN@
//
// HOW TO RUN (work laptop, on the office VPN):
//   1. Open the Journey Builder backoffice in Chrome, logged in.
//   2. F12 -> Console tab (if Chrome warns, type: allow pasting).
//   3. Paste this whole script and press Enter.
//   4. If it says "Waiting for a token", click anything in the backoffice
//      UI (e.g. refresh the journeys list) so the page makes a request.
//   5. Wait for "DONE" with the created JRN ids.
//
(async () => {
  'use strict';
  // Optional: paste an access token here to skip auto-capture.
  const MANUAL_TOKEN = '';

  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const ORDER = @ORDER@;
  // Journeys that start "immediately after publish": startAt is recomputed
  // to the moment this script runs, not the moment the file was generated.
  const IMMEDIATE = @IMMEDIATE@;

  const decodeJwt = (token) => {
    try {
      return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    } catch (e) {
      return null;
    }
  };
  const usableAuth = (value) => {
    if (!value || !/^Bearer\\s+\\S+/i.test(value)) return null;
    const payload = decodeJwt(value.replace(/^Bearer\\s+/i, ''));
    if (!payload || payload.typ !== 'Bearer') return null;
    if (payload.exp - Date.now() / 1000 < 30) return null;
    return 'Bearer ' + value.replace(/^Bearer\\s+/i, '');
  };

  async function obtainAuth() {
    if (MANUAL_TOKEN.trim()) {
      const auth = usableAuth('Bearer ' + MANUAL_TOKEN.trim().replace(/^Bearer\\s+/i, ''));
      if (!auth) throw new Error('MANUAL_TOKEN is not a valid unexpired access token (typ must be "Bearer").');
      return auth;
    }
    return new Promise((resolve, reject) => {
      let settled = false;
      const origFetch = window.fetch;
      const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
      const cleanup = () => {
        window.fetch = origFetch;
        XMLHttpRequest.prototype.setRequestHeader = origSetHeader;
      };
      const consider = (value) => {
        const auth = usableAuth(value);
        if (auth && !settled) {
          settled = true;
          cleanup();
          clearTimeout(timer);
          console.log('%cToken captured from the page.', 'color:#22c55e;font-weight:bold');
          resolve(auth);
        }
      };
      window.fetch = function (input, init) {
        try {
          const h = (init && init.headers) || (input && input.headers);
          if (h) {
            if (typeof h.get === 'function') consider(h.get('authorization'));
            else consider(h.authorization || h.Authorization);
          }
        } catch (e) { /* never break the page's own requests */ }
        return origFetch.apply(this, arguments);
      };
      XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
        try {
          if (/^authorization$/i.test(name)) consider(value);
        } catch (e) { /* never break the page's own requests */ }
        return origSetHeader.apply(this, arguments);
      };
      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          cleanup();
          reject(new Error('No token captured in 3 minutes. Click around in the backoffice UI and run the script again.'));
        }
      }, 180000);
      console.log('%cWaiting for a token... refresh the journeys list or click anything in the backoffice UI.', 'color:#eab308;font-weight:bold');
    });
  }

  const auth = await obtainAuth();
  const headers = (contentType) => ({
    accept: 'application/json, text/plain, */*',
    authorization: auth,
    'content-type': contentType,
    'x-brand': BRAND,
  });

  const pad = (n) => String(n).padStart(2, '0');
  const nowUtc = () => {
    const d = new Date();
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
      `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  };

  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', {
      method: 'POST',
      headers: headers('application/x-www-form-urlencoded'),
      credentials: 'include',
    });
    const raw = (await r.text()).trim();
    // Response may be a bare string ("JRN-...") or an object like
    // {"journeyId":"JRN-..."} — mirror parse_identifier_response in Python.
    let id = raw.replace(/^"+|"+$/g, '');
    try {
      const data = JSON.parse(raw);
      if (typeof data === 'string') {
        id = data.trim();
      } else if (data && typeof data === 'object') {
        id = String(data.identifier || data.journeyId || data.id || data.value || '').trim();
      }
    } catch (e) { /* keep the raw text */ }
    if (!r.ok || !id.startsWith('JRN-')) {
      throw new Error('Failed to reserve journey ID: HTTP ' + r.status + ' ' + raw);
    }
    return id;
  }

  const PAYLOADS = @PAYLOADS@;

  console.log('Will create:');
  for (const type of ORDER) console.log(`  [${type}] ${PAYLOADS[type].journeyName}`);

  console.log('Reserving real journey IDs...');
  const realIds = {};
  for (const type of ORDER) {
    realIds[type] = await reserveId();
    console.log(`  [${type}] ${realIds[type]}`);
  }

  for (const type of ORDER) {
    // Swap every DRY-RUN placeholder for the real id reserved above. For
    // two_hours this also repoints the campaign connector at the new
    // FollowUp, because its payload references DRY-RUN-FOLLOWUP.
    let text = JSON.stringify(PAYLOADS[type]);
    for (const [t, rid] of Object.entries(realIds)) {
      text = text.split('DRY-RUN-' + t.toUpperCase()).join(rid);
    }
    const body = JSON.parse(text);

    if (IMMEDIATE[type]) {
      const now = nowUtc();
      body.startAt = now + '.0000000Z';
      if (body.rawJourneyData && body.rawJourneyData.infoValues) {
        body.rawJourneyData.infoValues.startAt = now + 'Z';
      }
    }

    console.log(`[${type}] Creating draft ${body.reservedJourneyId}: ${body.journeyName}`);
    const r = await fetch(BASE + '/journey-drafts', {
      method: 'POST',
      headers: headers('application/json'),
      credentials: 'include',
      body: JSON.stringify(body),
    });
    const respText = await r.text();
    if (!r.ok) {
      console.error(`[${type}] FAILED: HTTP ${r.status}`, respText);
      throw new Error(`Stopped at ${type}; later drafts were NOT created.`);
    }
    console.log(`%c[${type}] Created.`, 'color:#22c55e', respText);
  }

  console.log('%cDONE. Created journey IDs:', 'color:#22c55e;font-weight:bold', realIds);
  console.log('Open the 2H draft and confirm its campaign connector shows', realIds.followup || '(followup id)');
})();
"""


def build_console_js(
    match_name: str,
    code: str,
    match_dt: datetime,
    ordered_types: list[str],
    team_key: str = DEFAULT_TEAM,
) -> tuple[bool, str]:
    """Prepare + verify payloads and render the console JS.

    Returns (all_checks_ok, js_text). Verification results are printed.
    """
    team = resolve_team(team_key)
    team_templates = template_files(team.key)
    payloads: dict[str, dict] = {}
    all_ok = True
    for journey_type in ordered_types:
        template = load_template(team_templates[journey_type])
        old_values = collect_old_values(template, team)
        reserved_id = f"DRY-RUN-{journey_type.upper()}"
        followup_id = "DRY-RUN-FOLLOWUP" if journey_type == "two_hours" else None
        body, report = prepare_body(
            template, journey_type, match_name, code, match_dt, reserved_id,
            old_values, followup_id=followup_id,
        )
        print(f"\n[{journey_type}] Applied settings:")
        for line in report:
            print(f"  {line}")
        checks = verify_body(
            body, journey_type, match_name, code, match_dt, reserved_id,
            followup_id, old_values,
        )
        all_ok = print_checks(journey_type, checks) and all_ok
        payloads[journey_type] = body

    campaign = (
        f"{match_name} | {code} | {match_dt.strftime('%Y-%m-%d %H:%M')} Chile"
    )
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@CAMPAIGN@", campaign)
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL or DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@ORDER@", json.dumps(ordered_types))
    js = js.replace(
        "@IMMEDIATE@",
        json.dumps({t: t in ("followup", "bfr") for t in ordered_types}),
    )
    # Payloads go last so marker-like text inside them can never be replaced.
    js = js.replace("@PAYLOADS@", json.dumps(payloads, ensure_ascii=False))
    return all_ok, js


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--team",
        choices=sorted(TEAMS),
        default=DEFAULT_TEAM,
        help=f"Template set / club to clone (default: {DEFAULT_TEAM}).",
    )
    parser.add_argument("--match", required=True, help='Example: "UDCH vs Calera"')
    parser.add_argument("--code", required=True, help="Example: DALELEON")
    parser.add_argument("--date", required=True, help="Match date YYYY-MM-DD")
    parser.add_argument("--time", required=True, help="Match time Chile HH:MM")
    parser.add_argument(
        "--types",
        nargs="+",
        choices=list(TYPE_ORDER),
        default=list(TYPE_ORDER),
    )
    args = parser.parse_args()

    match_dt = datetime.strptime(
        f"{args.date} {args.time}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=LOCAL_TZ)
    code = args.code.strip().upper()
    match_name = args.match.strip()
    ordered_types = [t for t in TYPE_ORDER if t in args.types]

    all_ok, js = build_console_js(match_name, code, match_dt, ordered_types, args.team)
    if not all_ok:
        print("\nVERIFICATION FAILED — console script NOT generated.", file=sys.stderr)
        return 1

    out_dir = Path("console_scripts")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{code}_console.js"
    out_path.write_text(js, encoding="utf-8")
    print(f"\nAll checks passed. Console script written: {out_path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab. "
          "It captures the auth token automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
