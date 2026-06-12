#!/usr/bin/env python3
"""
Generate a browser-console script that creates the 4 journey drafts.

Use this when the machine that can reach the Journey Builder API (work
laptop on the office VPN) cannot run Python. The payloads are prepared
and verified here, embedded into a single JS file, and the JS does only
the API calls: reserve real JRN ids, link the 2H campaign connector to
the new FollowUp, recompute "start now" times, POST the drafts.

Usage:
  python generate_console_script.py --match "UDCH vs Calera" --code DALELEON \
      --date 2026-06-14 --time 15:00

Then paste the generated console_scripts/<CODE>_console.js into Chrome
DevTools console on a logged-in backoffice tab, set TOKEN at the top.
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
    LOCAL_TZ,
    TEMPLATE_FILES,
    TYPE_ORDER,
    load_template,
    prepare_body,
    print_checks,
    verify_body,
)

DEFAULT_BASE_URL = (
    "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
)

JS_TEMPLATE = """\
// Journey Cloner console script — generated %(generated_at)s
// Campaign: %(match)s | %(code)s | %(match_local)s Chile
//
// HOW TO RUN (work laptop, on the office VPN):
//   1. Open the Journey Builder backoffice in Chrome, logged in.
//   2. F12 -> Console tab (if Chrome warns, type: allow pasting).
//   3. Replace TOKEN below with a fresh bearer token: F12 -> Network tab,
//      click any backoffice request -> Headers -> "authorization".
//   4. Paste the whole script and press Enter.
//
(async () => {
  'use strict';
  const TOKEN = 'PASTE_FRESH_BEARER_TOKEN_HERE';

  const BASE = %(base_url)s;
  const BRAND = %(brand)s;
  const ORDER = %(order)s;
  // Journeys that start "immediately after publish": startAt is recomputed
  // to the moment this script runs, not the moment the file was generated.
  const IMMEDIATE = %(immediate)s;
  const PAYLOADS = %(payloads)s;

  if (TOKEN.includes('PASTE')) {
    console.error('Set TOKEN first (copy the authorization header from any backoffice request in the Network tab).');
    return;
  }
  const auth = TOKEN.startsWith('Bearer ') ? TOKEN : 'Bearer ' + TOKEN;
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
    const text = (await r.text()).trim().replace(/^"+|"+$/g, '');
    if (!r.ok || !text.startsWith('JRN-')) {
      throw new Error('Failed to reserve journey ID: HTTP ' + r.status + ' ' + text);
    }
    return text;
  }

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
    console.log(`[${type}] Created. Response:`, respText);
  }

  console.log('DONE. Created journey IDs:', realIds);
  console.log('Open the 2H draft and confirm its campaign connector shows', realIds.followup || '(followup id)');
})();
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match", required=True, help='Example: "UDCH vs Calera"')
    parser.add_argument("--code", required=True, help="Example: DALELEON")
    parser.add_argument("--date", required=True, help="Match date YYYY-MM-DD")
    parser.add_argument("--time", required=True, help="Match time Chile HH:MM")
    parser.add_argument(
        "--types",
        nargs="+",
        choices=list(TEMPLATE_FILES),
        default=list(TYPE_ORDER),
    )
    args = parser.parse_args()

    match_dt = datetime.strptime(
        f"{args.date} {args.time}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=LOCAL_TZ)
    code = args.code.strip().upper()
    match_name = args.match.strip()
    ordered_types = [t for t in TYPE_ORDER if t in args.types]

    payloads: dict[str, dict] = {}
    all_ok = True
    for journey_type in ordered_types:
        template = load_template(TEMPLATE_FILES[journey_type])
        reserved_id = f"DRY-RUN-{journey_type.upper()}"
        followup_id = "DRY-RUN-FOLLOWUP" if journey_type == "two_hours" else None
        body, report = prepare_body(
            template, journey_type, match_name, code, match_dt, reserved_id,
            followup_id=followup_id,
        )
        print(f"\n[{journey_type}] Applied settings:")
        for line in report:
            print(f"  {line}")
        checks = verify_body(
            body, journey_type, match_name, code, match_dt, reserved_id, followup_id
        )
        all_ok = print_checks(journey_type, checks) and all_ok
        payloads[journey_type] = body

    if not all_ok:
        print("\nVERIFICATION FAILED — console script NOT generated.", file=sys.stderr)
        return 1

    js = JS_TEMPLATE % {
        "generated_at": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"),
        "match": match_name,
        "code": code,
        "match_local": match_dt.strftime("%Y-%m-%d %H:%M"),
        "base_url": json.dumps(BASE_URL or DEFAULT_BASE_URL),
        "brand": json.dumps(BRAND),
        "order": json.dumps(ordered_types),
        "immediate": json.dumps({t: t in ("followup", "bfr") for t in ordered_types}),
        "payloads": json.dumps(payloads, ensure_ascii=False),
    }

    out_dir = Path("console_scripts")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{code}_console.js"
    out_path.write_text(js, encoding="utf-8")
    print(f"\nAll checks passed. Console script written: {out_path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab "
          "(set TOKEN at the top first).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
