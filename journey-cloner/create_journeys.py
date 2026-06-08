#!/usr/bin/env python3
"""
Create 4 Journey Builder draft clones for a promocode match campaign.

Input example:
  Match: UDCH vs O'Higgins
  Date: 2026-06-10
  Time Chile: 20:00
  Code: VAMOSBULLA

Creates drafts:
  FollowUp, BFR, 2H, AFT

Before running:
  1. Put template JSON bodies in templates/*.json
  2. Put a fresh AUTH_TOKEN in .env
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


load_dotenv()

BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
BRAND = os.getenv("BRAND", "JBCL")
LOCAL_TZ_NAME = os.getenv("TIMEZONE", "America/Santiago")
COOKIE = os.getenv("COOKIE", "").strip()

LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)
UTC = ZoneInfo("UTC")

TEMPLATE_FILES = {
    "followup": "templates/followup.json",
    "bfr": "templates/bfr.json",
    "two_hours": "templates/two_hours.json",
    "aft": "templates/aft.json",
}

# Old values from the VAMOSBULLA template set.
OLD_CODES = [
    "VAMOSBULLA",
    "XQTANTEMPRANO",  # appears in some notification metadata of the captured AFT body
]

OLD_MATCH_TEXTS = [
    "UDCH vs O'higgins",
    "UDCH vs O'higgin",
    "UDCH vs O\u2019Higgins",
    "UDCH vs O\u2019Higgin",
    "UDCH vs Audax",
]

OLD_DATE_LABELS = [
    "10.06",
    "07.06",
    "23.11",
    "13.09",
]


class JourneyCloneError(RuntimeError):
    pass


def load_template(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing template file: {path}")
    return json.loads(p.read_text(encoding="utf-8-sig"))


def utc_api(dt_local: datetime, dotnet_fraction: bool = False) -> str:
    dt_utc = dt_local.astimezone(UTC)
    if dotnet_fraction:
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc_api(dotnet_fraction: bool = False) -> str:
    now = datetime.now(UTC).replace(microsecond=0)
    if dotnet_fraction:
        return now.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def deep_replace(obj: Any, replacements: dict[str, str]) -> Any:
    if isinstance(obj, dict):
        return {k: deep_replace(v, replacements) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_replace(v, replacements) for v in obj]
    if isinstance(obj, str):
        value = obj
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return obj


def walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_dicts(item)


def headers(content_type: str) -> dict[str, str]:
    h = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {AUTH_TOKEN}",
        "content-type": content_type,
        "x-brand": BRAND,
    }
    if COOKIE:
        h["cookie"] = COOKIE
    return h


def parse_identifier_response(response: requests.Response) -> str:
    text = response.text.strip().strip('"')
    try:
        data = response.json()
    except Exception:
        return text

    if isinstance(data, str):
        return data.strip()

    if isinstance(data, dict):
        for key in ("identifier", "journeyId", "id", "value"):
            if data.get(key):
                return str(data[key]).strip()

    return text


def reserve_journey_id(session: requests.Session) -> str:
    url = f"{BASE_URL}/journeys/identifier"
    response = session.post(
        url,
        headers=headers("application/x-www-form-urlencoded"),
        timeout=30,
    )

    if not response.ok:
        raise JourneyCloneError(
            f"Failed to reserve journey ID: {response.status_code}\n{response.text}"
        )

    reserved_id = parse_identifier_response(response)
    if not reserved_id.startswith("JRN-"):
        raise JourneyCloneError(
            f"Unexpected identifier response: {response.text!r}. Parsed: {reserved_id!r}"
        )
    return reserved_id


def create_draft(session: requests.Session, body: dict[str, Any]) -> Any:
    url = f"{BASE_URL}/journey-drafts"
    response = session.post(
        url,
        headers=headers("application/json"),
        json=body,
        timeout=90,
    )

    if not response.ok:
        raise JourneyCloneError(
            f"Failed to create draft {body.get('reservedJourneyId')}: {response.status_code}\n{response.text}"
        )

    try:
        return response.json()
    except Exception:
        return response.text


def build_journey_name(journey_type: str, match_name: str, code: str, date_label: str) -> str:
    if journey_type == "followup":
        return f"JBCL|SP|{match_name}|PrmCode-{code}|FollowUp | {date_label}"
    if journey_type == "bfr":
        return f"JBCL | SP | {match_name} | Promocode -{code} | BFR | {date_label}"
    if journey_type == "two_hours":
        return f"JBCL | SP | {match_name} | Promocode -{code} | 2H | {date_label}"
    if journey_type == "aft":
        return f"JBCL | SP | {match_name} | Promocode - {code} | AFT | {date_label}"
    raise ValueError(f"Unknown journey type: {journey_type}")


def set_promocode_everywhere(body: dict[str, Any], code: str) -> None:
    for d in walk_dicts(body):
        if "promocodeSettings" in d and isinstance(d["promocodeSettings"], dict):
            d["promocodeSettings"]["values"] = [code]
        if d.get("refCodeTypes") == ["Promocode"] and "displayData" in d:
            d["displayData"] = [f"Promo codes: {code}"]
        if d.get("displayName") == "Reference codes" and "displayData" in d:
            d["displayData"] = [f"Promo codes: {code}"]


def set_notification_metadata_journey_name(body: dict[str, Any], clean_name: str) -> None:
    for d in walk_dicts(body):
        metadata = d.get("metadata")
        if isinstance(metadata, dict) and "journeyName" in metadata:
            metadata["journeyName"] = clean_name


def set_raw_info(body: dict[str, Any], key: str, value: Any) -> None:
    raw = body.setdefault("rawJourneyData", {})
    info = raw.setdefault("infoValues", {})
    info[key] = value


def set_dates(body: dict[str, Any], journey_type: str, match_dt: datetime) -> None:
    two_hours_start = match_dt - timedelta(hours=2)
    bfr_stop = two_hours_start - timedelta(minutes=1)
    aft_start = match_dt + timedelta(minutes=1)

    next_day_midnight = datetime.combine(
        (match_dt + timedelta(days=1)).date(),
        time(0, 0),
        tzinfo=LOCAL_TZ,
    )
    followup_stop = datetime.combine(
        (match_dt + timedelta(days=2)).date(),
        time(0, 0),
        tzinfo=LOCAL_TZ,
    )

    if journey_type == "two_hours":
        start_top = utc_api(two_hours_start, dotnet_fraction=True)
        stop_top = utc_api(match_dt, dotnet_fraction=True)
        start_info = utc_api(two_hours_start)
        stop_info = utc_api(match_dt)
        immediate = False
    elif journey_type == "bfr":
        start_top = now_utc_api(dotnet_fraction=True)
        stop_top = utc_api(bfr_stop, dotnet_fraction=True)
        start_info = now_utc_api()
        stop_info = utc_api(bfr_stop)
        immediate = True
    elif journey_type == "aft":
        start_top = utc_api(aft_start, dotnet_fraction=True)
        stop_top = utc_api(next_day_midnight, dotnet_fraction=True)
        start_info = utc_api(aft_start)
        stop_info = utc_api(next_day_midnight)
        immediate = False
    elif journey_type == "followup":
        start_top = now_utc_api(dotnet_fraction=True)
        stop_top = utc_api(followup_stop, dotnet_fraction=True)
        start_info = now_utc_api()
        stop_info = utc_api(followup_stop)
        immediate = True
    else:
        raise ValueError(f"Unknown journey type: {journey_type}")

    body["startAt"] = start_top
    body["stopAt"] = stop_top
    body["isImmediatelyAfterPublish"] = immediate
    body["timeZoneId"] = "Chile/Continental"

    set_raw_info(body, "startAt", start_info)
    set_raw_info(body, "stopAt", stop_info)
    set_raw_info(body, "isImmediatelyAfterPublish", immediate)
    set_raw_info(body, "timeZoneId", "Chile/Continental")


def prepare_body(
    template: dict[str, Any],
    journey_type: str,
    match_name: str,
    code: str,
    match_dt: datetime,
    reserved_id: str,
) -> dict[str, Any]:
    body = copy.deepcopy(template)
    date_label = match_dt.strftime("%d.%m")
    clean_name = build_journey_name(journey_type, match_name, code, date_label)

    replacements: dict[str, str] = {}
    for old_code in OLD_CODES:
        replacements[old_code] = code
    for old_match in OLD_MATCH_TEXTS:
        replacements[old_match] = match_name
    for old_date in OLD_DATE_LABELS:
        replacements[old_date] = date_label

    body = deep_replace(body, replacements)

    body["journeyName"] = f"Copy of {clean_name}"
    body["reservedJourneyId"] = reserved_id
    set_raw_info(body, "journeyName", clean_name)

    set_promocode_everywhere(body, code)
    set_notification_metadata_journey_name(body, clean_name)
    set_dates(body, journey_type, match_dt)

    return body


def prompt_missing(args: argparse.Namespace) -> argparse.Namespace:
    if not args.match:
        home = input("Home/team, example UDCH or Colo Colo: ").strip()
        opponent = input("Opponent, example O'Higgins: ").strip()
        args.match = f"{home} vs {opponent}"
    if not args.code:
        args.code = input("Promocode, example VAMOSBULLA: ").strip().upper()
    if not args.date:
        args.date = input("Match date YYYY-MM-DD, example 2026-06-10: ").strip()
    if not args.time:
        args.time = input("Match time Chile HH:MM, example 20:00: ").strip()
    return args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create 4 Journey Builder draft clones.")
    parser.add_argument("--match", help='Full match name, example: "UDCH vs O\'Higgins"')
    parser.add_argument("--code", help="Promocode, example: VAMOSBULLA")
    parser.add_argument("--date", help="Match date YYYY-MM-DD, example: 2026-06-10")
    parser.add_argument("--time", help="Match time in Chile timezone HH:MM, example: 20:00")
    parser.add_argument(
        "--types",
        nargs="+",
        choices=["followup", "bfr", "two_hours", "aft"],
        default=["followup", "bfr", "two_hours", "aft"],
        help="Use this to test only one type first, example: --types aft",
    )
    parser.add_argument("--dry-run", action="store_true", help="Write output JSON files but do not call POST /journey-drafts")
    parser.add_argument("--yes", action="store_true", help="Do not ask for final confirmation")
    return prompt_missing(parser.parse_args())


def validate_env(require_api: bool = True) -> None:
    missing = []
    if require_api and not BASE_URL:
        missing.append("BASE_URL")
    if require_api and (
        not AUTH_TOKEN or AUTH_TOKEN == "PASTE_FRESH_BEARER_TOKEN_HERE"
    ):
        missing.append("AUTH_TOKEN")
    if missing:
        raise JourneyCloneError(f"Missing/invalid values in .env: {', '.join(missing)}")


def main() -> int:
    try:
        args = parse_args()
        validate_env(require_api=not args.dry_run)

        match_dt = datetime.strptime(f"{args.date} {args.time}", "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
        code = args.code.strip().upper()
        match_name = args.match.strip()
        date_label = match_dt.strftime("%d.%m")

        print("\nCampaign")
        print(f"  Match: {match_name}")
        print(f"  Code:  {code}")
        print(f"  Date:  {date_label}")
        print(f"  Time:  {match_dt.strftime('%Y-%m-%d %H:%M')} {LOCAL_TZ_NAME}")
        print("\nWill create:")
        for t in args.types:
            print(f"  - {build_journey_name(t, match_name, code, date_label)}")

        if not args.yes:
            confirm = input("\nContinue? Type YES: ").strip()
            if confirm != "YES":
                print("Cancelled.")
                return 0

        session = requests.Session()
        out_dir = Path("out")
        out_dir.mkdir(exist_ok=True)

        for journey_type in args.types:
            print(f"\n[{journey_type}] Loading template...")
            template = load_template(TEMPLATE_FILES[journey_type])

            if args.dry_run:
                reserved_id = f"DRY-RUN-{journey_type.upper()}"
                print(f"[{journey_type}] Dry run enabled, using placeholder ID: {reserved_id}")
            else:
                print(f"[{journey_type}] Reserving new journey ID...")
                reserved_id = reserve_journey_id(session)
                print(f"[{journey_type}] Reserved ID: {reserved_id}")

            body = prepare_body(template, journey_type, match_name, code, match_dt, reserved_id)
            out_path = out_dir / f"{reserved_id}_{journey_type}.json"
            out_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{journey_type}] Wrote payload: {out_path}")
            print(f"[{journey_type}] Name: {body['journeyName']}")

            if args.dry_run:
                print(f"[{journey_type}] Dry run enabled, not posting draft.")
                continue

            print(f"[{journey_type}] Creating draft...")
            result = create_draft(session, body)
            print(f"[{journey_type}] Created draft. Response: {result}")

        print("\nDone.")
        return 0

    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
