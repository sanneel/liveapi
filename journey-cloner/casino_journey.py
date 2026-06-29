#!/usr/bin/env python3
"""
Clone the casino "Game of the Week" journey: set the free-spin game / provider /
per-tier bets and the campaign dates (Chile time), then emit a browser-console
script that creates the draft (same paste-into-DevTools flow as the sport
journeys in generate_console_script.py).

What it changes on the captured template (templates/casino/gow.json):
  * free-spin game + provider on all freespin_bonus activities,
  * per-tier free-spin bet (mapped to each tier by its deposit minimum,
    ascending — small dep gets the first --bets value, etc.),
  * optional spins count,
  * journey + free-spin start/stop dates in Chile time: a campaign "on DATE"
    runs DATE 00:00 → DATE+days 00:00 (America/Santiago), written to the API in
    UTC,
  * strips server-minted ids (promotionDisplayId, campaignId), drops
    duplicate-lineage, and regenerates internal activity ids (at paste time, in
    the browser) so re-running never collides.

Usage:
  python casino_journey.py --date 2026-07-01 \
      --game lagrancopa --bets 120 200 400 800

  # or specify a game not in the registry explicitly:
  python casino_journey.py --date 2026-07-01 \
      --lobby-game-id pragmatic-spin-score --wallet-game-id pp_spin_score \
      --external-game-id pp_spin_score --provider pragmatic \
      --game-name "Spin & Score Megaways" --provider-name "Pragmatic Play" \
      --bets 120 200 400 800

Then paste console_scripts/<name>_console.js into the DevTools console on a
logged-in backoffice tab. Use --dry-run to write the prepared payload to out/
without generating a script.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

from create_journeys import (
    BASE_URL,
    BRAND,
    LOCAL_TZ,
    UTC,
    clear_stale_campaign_connector_ids,
    regenerate_internal_ids,
    strip_duplicate_lineage,
    strip_promotion_display_ids,
    walk_dicts,
)

DEFAULT_BASE_URL = (
    "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
)

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "casino" / "gow.json"

# Known free-spin games. Keys are the --game shorthand. Extend as needed; or
# pass every field explicitly with the --lobby-game-id/... flags (which override
# the registry entry).
GAMES: dict[str, dict[str, str]] = {
    "lagrancopa": {
        "lobby_game_id": "jugabet-games-la-gran-copa-jugabet",
        "wallet_game_id": "gg_la_gran_copa_jugabet",
        "external_game_id": "gg_la_gran_copa_jugabet",
        "provider": "jugabet-games",
        "game_name": "La Gran Copa Jugabet",
        "provider_name": "Jugabet Games",
    },
}


def utc_dotnet(dt_local: datetime) -> str:
    return dt_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def utc_plain(dt_local: datetime) -> str:
    return dt_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def chile_window(date_str: str, days: int) -> tuple[datetime, datetime]:
    """DATE 00:00 → DATE+days 00:00 in America/Santiago."""
    start = datetime.combine(
        datetime.strptime(date_str, "%Y-%m-%d").date(), time(0, 0), tzinfo=LOCAL_TZ
    )
    return start, start + timedelta(days=days)


def freespin_activities(body: dict) -> list[dict]:
    """Every freespinActivity config dict, in activities[] order."""
    return [
        d["freespinActivity"]
        for d in walk_dicts(body)
        if isinstance(d.get("freespinActivity"), dict)
    ]


def distinct_bet_tiers(body: dict, currency: str = "CLP") -> list[int]:
    """Distinct current free-spin betAmounts, ascending = the per-tier values.

    The captured journey scales the bet with the deposit tier (10k→12000,
    20k→20000, 30k→40000, 50k→80000), and each value is mirrored in several
    places (promotion placements, the freespin activity, the rawJourneyData
    config). The distinct ascending values are exactly the tiers.
    """
    vals = {
        fa.get("currenciesConfig", {}).get(currency, {}).get("betAmount")
        for fa in freespin_activities(body)
    }
    return sorted(v for v in vals if v is not None)


def set_game(body: dict, game: dict[str, str], spins: int | None) -> int:
    count = 0
    for fa in freespin_activities(body):
        fa["lobbyGameId"] = game["lobby_game_id"]
        fa["walletGameId"] = game["wallet_game_id"]
        fa["externalGameId"] = game["external_game_id"]
        fa["provider"] = game["provider"]
        fa["gameTranslationKey"] = game["game_name"]
        fa["providerTranslationKey"] = game["provider_name"]
        if spins is not None:
            fa["spins"] = spins
        count += 1
    return count


def set_bets(body: dict, bets_major: list[int], currency: str = "CLP") -> list[str]:
    """Set per-tier free-spin bets. --bets values are in tier order, ascending by
    deposit tier (smallest deposit first); major units (e.g. 120 → minor 12000).

    Remaps by current tier value so every mirror (promotion placements, freespin
    activities, rawJourneyData config) stays consistent.
    """
    tiers = distinct_bet_tiers(body, currency)
    if len(bets_major) != len(tiers):
        raise ValueError(
            f"--bets expects {len(tiers)} values (one per tier, ascending), got {len(bets_major)}"
        )
    # old tier minor value -> (new minor, new major)
    mapping = {old: (bets_major[i] * 100, bets_major[i]) for i, old in enumerate(tiers)}
    for fa in freespin_activities(body):
        cc = fa.get("currenciesConfig", {}).get(currency)
        if not cc:
            continue
        old = cc.get("betAmount")
        if old in mapping:
            cc["betAmount"], cc["betAmount_majorUnits"] = mapping[old]
    return [
        f"tier {i + 1} (was {old}) → bet {currency} {bets_major[i]} (minor {bets_major[i] * 100})"
        for i, old in enumerate(tiers)
    ]


def set_dates(body: dict, start_local: datetime, stop_local: datetime) -> None:
    body["startAt"] = utc_dotnet(start_local)
    body["stopAt"] = utc_dotnet(stop_local)
    body["isImmediatelyAfterPublish"] = False
    body["timeZoneId"] = "Chile/Continental"

    raw = body.get("rawJourneyData")
    if isinstance(raw, dict):
        info = raw.setdefault("infoValues", {})
        info["startAt"] = utc_plain(start_local)
        info["stopAt"] = utc_plain(stop_local)
        info["isImmediatelyAfterPublish"] = False
        info["timeZoneId"] = "Chile/Continental"

    # Free-spin validity window = the campaign window.
    for fa in freespin_activities(body):
        fa["startAt"] = utc_plain(start_local)
        fa["stopAt"] = utc_plain(stop_local)


def prepare(
    *,
    date_str: str,
    days: int,
    game: dict[str, str],
    bets_major: list[int],
    spins: int | None,
    reserved_id: str,
) -> tuple[dict, list[str]]:
    body = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8-sig"))
    report: list[str] = []

    n = set_game(body, game, spins)
    report.append(
        f"set game {game['game_name']!r} ({game['lobby_game_id']}) on {n} free-spin activities"
        + (f", spins={spins}" if spins is not None else "")
    )
    report.extend(set_bets(body, bets_major))

    start_local, stop_local = chile_window(date_str, days)
    set_dates(body, start_local, stop_local)
    report.append(
        f"startAt {body['startAt']} ({start_local:%Y-%m-%d %H:%M} Chile) → "
        f"stopAt {body['stopAt']} ({stop_local:%Y-%m-%d %H:%M} Chile)"
    )

    removed = strip_duplicate_lineage(body)
    if removed:
        report.append(f"removed {', '.join(removed)}")
    cc = clear_stale_campaign_connector_ids(body)
    if cc:
        report.append(f"cleared {cc} stale campaignId(s)")
    dd = strip_promotion_display_ids(body)
    if dd:
        report.append(f"removed {dd} stale promotionDisplayId(s)")

    body["reservedJourneyId"] = reserved_id
    report.append(f"reservedJourneyId = {reserved_id}")
    return body, report


def verify(body: dict, game: dict[str, str], bets_major: list[int]) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    fas = freespin_activities(body)
    checks.append((bool(fas), f"{len(fas)} free-spin activities present"))
    checks.append((
        all(fa.get("lobbyGameId") == game["lobby_game_id"] for fa in fas),
        f"all free-spins use lobbyGameId {game['lobby_game_id']}",
    ))
    bet_tiers = distinct_bet_tiers(body)
    checks.append((
        bet_tiers == sorted(b * 100 for b in bets_major),
        f"free-spin bet tiers (minor) = {bet_tiers}",
    ))
    leftovers = [d["promotionDisplayId"] for d in walk_dicts(body) if d.get("promotionDisplayId")]
    checks.append((not leftovers, "no stale promotionDisplayId" if not leftovers else f"leftover: {leftovers}"))
    try:
        s = datetime.strptime(body["startAt"][:19], "%Y-%m-%dT%H:%M:%S")
        e = datetime.strptime(body["stopAt"][:19], "%Y-%m-%dT%H:%M:%S")
        checks.append((s < e, f"startAt < stopAt ({body['startAt']} < {body['stopAt']})"))
    except (KeyError, ValueError) as exc:
        checks.append((False, f"date parse failed: {exc}"))
    return checks


JS_TEMPLATE = """\
// Casino journey console script — generated @GENERATED_AT@
// Journey: @JOURNEY_NAME@
// Paste into the DevTools console on a logged-in backoffice tab. It captures the
// auth token from the page's own requests, reserves a real JRN id, regenerates
// internal activity ids, and POSTs the draft.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const PAYLOAD = @PAYLOAD@;

  const decodeJwt = (t) => { try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch (e) { return null; } };
  const usableAuth = (v) => {
    if (!v || !/^Bearer\\s+\\S+/i.test(v)) return null;
    const p = decodeJwt(v.replace(/^Bearer\\s+/i, ''));
    if (!p || p.typ !== 'Bearer' || p.exp - Date.now()/1000 < 30) return null;
    return 'Bearer ' + v.replace(/^Bearer\\s+/i, '');
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
  const headers = (ct) => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'content-type': ct, 'x-brand': BRAND });

  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  const UUID_RE = /"(?:activityId|id)"\\s*:\\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  const regen = (txt) => { const old = new Set(); let m; UUID_RE.lastIndex = 0; while ((m = UUID_RE.exec(txt)) !== null) old.add(m[1]); let t = txt; for (const o of old) t = t.split(o).join(newUuid()); return t; };

  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', { method: 'POST', headers: headers('application/x-www-form-urlencoded'), credentials: 'include' });
    const raw = (await r.text()).trim(); let id = raw.replace(/^"+|"+$/g, '');
    try { const d = JSON.parse(raw); if (typeof d === 'string') id = d.trim(); else if (d && typeof d === 'object') id = String(d.identifier || d.journeyId || d.id || d.value || '').trim(); } catch (e) {}
    if (!r.ok || !id.startsWith('JRN-')) throw new Error('Reserve failed: HTTP ' + r.status + ' ' + raw);
    return id;
  }

  console.log('Reserving journey id...');
  const realId = await reserveId();
  console.log('  reserved', realId);
  let text = JSON.stringify(PAYLOAD).split('DRY-RUN-CASINO').join(realId);
  text = regen(text);                          // fresh activity ids per run
  const body = JSON.parse(text);

  console.log('Creating draft', realId, ':', body.journeyName);
  const r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(body) });
  const resp = await r.text();
  if (!r.ok) { console.error('FAILED HTTP ' + r.status, resp); throw new Error('Draft not created.'); }
  console.log('%cDONE. Created ' + realId, 'color:#22c55e;font-weight:bold', resp);
})();
"""


def build_js(body: dict) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY_NAME@", str(body.get("journeyName", "")))
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL or DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@PAYLOAD@", json.dumps(body, ensure_ascii=False))
    return js


def resolve_game(args: argparse.Namespace) -> dict[str, str]:
    if args.game:
        if args.game not in GAMES:
            raise SystemExit(f"Unknown --game {args.game!r}. Known: {', '.join(GAMES)}")
        game = dict(GAMES[args.game])
    else:
        game = {}
    overrides = {
        "lobby_game_id": args.lobby_game_id,
        "wallet_game_id": args.wallet_game_id,
        "external_game_id": args.external_game_id,
        "provider": args.provider,
        "game_name": args.game_name,
        "provider_name": args.provider_name,
    }
    for k, v in overrides.items():
        if v:
            game[k] = v
    missing = [k for k in ("lobby_game_id", "wallet_game_id", "external_game_id",
                           "provider", "game_name", "provider_name") if not game.get(k)]
    if missing:
        raise SystemExit(
            "Game not fully specified. Use --game <known> or pass: "
            + ", ".join("--" + m.replace("_", "-") for m in missing)
        )
    return game


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="Campaign start date YYYY-MM-DD (Chile)")
    p.add_argument("--days", type=int, default=1, help="Duration in days (default 1 → next-day 00:00 stop)")
    p.add_argument("--bets", type=int, nargs="+", required=True, help="Per-tier bet (major units, ascending by deposit tier), e.g. 120 200 400 800")
    p.add_argument("--spins", type=int, help="Free-spin count (default: keep template value)")
    p.add_argument("--game", help="Known game shorthand: " + ", ".join(GAMES))
    p.add_argument("--lobby-game-id")
    p.add_argument("--wallet-game-id")
    p.add_argument("--external-game-id")
    p.add_argument("--provider")
    p.add_argument("--game-name")
    p.add_argument("--provider-name")
    p.add_argument("--name", default="casino", help="Output file basename (default: casino)")
    p.add_argument("--dry-run", action="store_true", help="Write prepared payload to out/ instead of a console script")
    args = p.parse_args()

    game = resolve_game(args)
    reserved_id = "DRY-RUN-CASINO"
    body, report = prepare(
        date_str=args.date, days=args.days, game=game,
        bets_major=args.bets, spins=args.spins, reserved_id=reserved_id,
    )

    print("Applied:")
    for line in report:
        print("  " + line)

    print("Verification:")
    all_ok = True
    for ok, msg in verify(body, game, args.bets):
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
        all_ok = all_ok and ok
    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = Path("out")
        out.mkdir(exist_ok=True)
        path = out / f"{args.name}_casino.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — payload written: {path}")
        return 0

    out = Path("console_scripts")
    out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(build_js(body), encoding="utf-8")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
