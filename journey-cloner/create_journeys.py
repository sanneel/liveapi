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
OUT_DIR = os.getenv("JOURNEY_CLONER_OUT_DIR", "out")

LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)
UTC = ZoneInfo("UTC")

TEMPLATE_FILES = {
    "followup": "templates/followup.json",
    "bfr": "templates/bfr.json",
    "two_hours": "templates/two_hours.json",
    "aft": "templates/aft.json",
}

# Creation order matters: the 2H campaign connector must point at the FollowUp
# journey created in the same run, so followup is always processed first.
TYPE_ORDER = ["followup", "bfr", "two_hours", "aft"]

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


def set_promocode_everywhere(body: dict[str, Any], code: str) -> tuple[int, int]:
    """Returns (promocodeSettings blocks updated, displayData lines updated)."""
    settings_count = 0
    display_count = 0
    for d in walk_dicts(body):
        if "promocodeSettings" in d and isinstance(d["promocodeSettings"], dict):
            d["promocodeSettings"]["values"] = [code]
            settings_count += 1
        if d.get("refCodeTypes") == ["Promocode"] and "displayData" in d:
            d["displayData"] = [f"Promo codes: {code}"]
            display_count += 1
        if d.get("displayName") == "Reference codes" and "displayData" in d:
            d["displayData"] = [f"Promo codes: {code}"]
            display_count += 1
    return settings_count, display_count


def set_notification_metadata_journey_name(body: dict[str, Any], clean_name: str) -> int:
    count = 0
    for d in walk_dicts(body):
        metadata = d.get("metadata")
        if isinstance(metadata, dict) and "journeyName" in metadata:
            metadata["journeyName"] = clean_name
            count += 1
    return count


def find_connector_host_ids(body: dict[str, Any]) -> set[str]:
    """Collect HostJourneyId values from campaign connector activities."""
    host_ids: set[str] = set()
    for d in walk_dicts(body):
        conditions = d.get("campaignConnectorConditions")
        if not isinstance(conditions, dict):
            continue
        activity_data = conditions.get("activityData")
        if isinstance(activity_data, dict):
            host_id = activity_data.get("HostJourneyId")
            if isinstance(host_id, str) and host_id:
                host_ids.add(host_id)
    return host_ids


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
    followup_id: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Returns the prepared body plus a log of every setting that was changed."""
    body = copy.deepcopy(template)
    date_label = match_dt.strftime("%d.%m")
    clean_name = build_journey_name(journey_type, match_name, code, date_label)
    report: list[str] = []

    replacements: dict[str, str] = {}
    for old_code in OLD_CODES:
        replacements[old_code] = code
    for old_match in OLD_MATCH_TEXTS:
        replacements[old_match] = match_name
    for old_date in OLD_DATE_LABELS:
        replacements[old_date] = date_label

    if followup_id:
        # Repoint the campaign connector at the FollowUp journey from this run.
        # Replacing the old id as a plain string also fixes the connector's
        # displayData line ("JRN-... — <followup name>").
        for old_host_id in find_connector_host_ids(body):
            replacements[old_host_id] = followup_id

    # Count occurrences in the same sequential order deep_replace applies them,
    # so overlapping old values (e.g. "O'higgins" vs "O'higgin") aren't double-counted.
    counting_text = json.dumps(body, ensure_ascii=False)
    for old, new in replacements.items():
        count = counting_text.count(old)
        if count:
            report.append(f"replaced {old!r} -> {new!r} ({count}x in template)")
            counting_text = counting_text.replace(old, new)

    body = deep_replace(body, replacements)

    body["journeyName"] = clean_name
    body["reservedJourneyId"] = reserved_id
    set_raw_info(body, "journeyName", clean_name)
    report.append(f"journeyName = {clean_name!r}")
    report.append(f"reservedJourneyId = {reserved_id!r}")

    settings_count, display_count = set_promocode_everywhere(body, code)
    if settings_count or display_count:
        report.append(
            f"promocode = {code!r} in {settings_count} promocodeSettings "
            f"+ {display_count} displayData lines"
        )
    metadata_count = set_notification_metadata_journey_name(body, clean_name)
    if metadata_count:
        report.append(f"notification metadata journeyName updated in {metadata_count} places")

    set_dates(body, journey_type, match_dt)
    start_local = parse_api_dt(body["startAt"]).astimezone(LOCAL_TZ)
    stop_local = parse_api_dt(body["stopAt"]).astimezone(LOCAL_TZ)
    report.append(
        f"startAt = {body['startAt']} ({start_local.strftime('%Y-%m-%d %H:%M')} Chile)"
    )
    report.append(
        f"stopAt = {body['stopAt']} ({stop_local.strftime('%Y-%m-%d %H:%M')} Chile)"
    )
    report.append(f"isImmediatelyAfterPublish = {body['isImmediatelyAfterPublish']}")
    report.append(f"timeZoneId = {body['timeZoneId']!r}")

    return body, report


def parse_api_dt(value: str) -> datetime:
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)


def verify_body(
    body: dict[str, Any],
    journey_type: str,
    match_name: str,
    code: str,
    match_dt: datetime,
    reserved_id: str,
    followup_id: str | None,
) -> list[tuple[bool, str]]:
    """Run sanity checks on a generated payload. Returns (ok, message) pairs."""
    checks: list[tuple[bool, str]] = []
    serialized = json.dumps(body, ensure_ascii=False)
    date_label = match_dt.strftime("%d.%m")
    expected_name = build_journey_name(journey_type, match_name, code, date_label)

    checks.append((
        body.get("journeyName") == expected_name,
        f"journeyName is {body.get('journeyName')!r}",
    ))
    raw_name = body.get("rawJourneyData", {}).get("infoValues", {}).get("journeyName")
    checks.append((
        raw_name == expected_name,
        f"rawJourneyData journeyName is {raw_name!r}",
    ))
    checks.append((
        body.get("reservedJourneyId") == reserved_id,
        f"reservedJourneyId is {body.get('reservedJourneyId')!r}",
    ))

    leftovers = [
        old for old in (OLD_CODES + OLD_MATCH_TEXTS + OLD_DATE_LABELS)
        if old in serialized
    ]
    checks.append((
        not leftovers,
        "no leftover old campaign values"
        if not leftovers
        else f"old campaign values still present: {leftovers}",
    ))

    promo_values: list[Any] = []
    for d in walk_dicts(body):
        settings = d.get("promocodeSettings")
        if isinstance(settings, dict):
            promo_values.append(settings.get("values"))
    if not promo_values:
        # The captured FollowUp journey has no promocode segmentation; the
        # code only appears in its name. The other types must have it.
        checks.append((
            journey_type == "followup",
            "no promocodeSettings in template"
            + ("" if journey_type == "followup" else " (expected at least one)"),
        ))
    else:
        promo_ok = all(v == [code] for v in promo_values)
        checks.append((
            promo_ok,
            f"promocode is [{code}] in all {len(promo_values)} promocodeSettings"
            if promo_ok
            else f"promocodeSettings wrong: {promo_values}",
        ))

    try:
        start_at = parse_api_dt(body["startAt"])
        stop_at = parse_api_dt(body["stopAt"])
        checks.append((
            start_at < stop_at,
            f"startAt {body['startAt']} is before stopAt {body['stopAt']}",
        ))
        checks.append((
            stop_at > datetime.now(UTC),
            f"stopAt {body['stopAt']} is in the future",
        ))
    except (KeyError, ValueError) as exc:
        checks.append((False, f"could not parse startAt/stopAt: {exc}"))

    if journey_type == "two_hours":
        hosts = find_connector_host_ids(body)
        if not hosts:
            checks.append((False, "no campaign connector (HostJourneyId) found in payload"))
        elif followup_id:
            checks.append((
                hosts == {followup_id},
                f"campaign connector HostJourneyId is {sorted(hosts)} "
                f"(expected {followup_id})",
            ))
        else:
            checks.append((
                False,
                f"campaign connector still points at old journey: {sorted(hosts)}",
            ))

    return checks


def print_checks(journey_type: str, checks: list[tuple[bool, str]]) -> bool:
    print(f"[{journey_type}] Verification:")
    all_ok = True
    for ok, message in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {message}")
        all_ok = all_ok and ok
    return all_ok


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
    parser.add_argument(
        "--followup-id",
        help="Existing FollowUp journey ID (JRN-...) for the 2H campaign connector. "
        "Only needed when creating two_hours without followup in the same run.",
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

        ordered_types = [t for t in TYPE_ORDER if t in args.types]
        followup_id_override = (args.followup_id or "").strip()
        if followup_id_override and not followup_id_override.startswith("JRN-"):
            raise JourneyCloneError(
                f"--followup-id must look like JRN-..., got: {followup_id_override!r}"
            )

        needs_followup_link = (
            "two_hours" in ordered_types
            and "followup" not in ordered_types
            and not followup_id_override
        )
        if needs_followup_link and not args.dry_run:
            raise JourneyCloneError(
                "two_hours needs a FollowUp journey for its campaign connector. "
                "Include followup in --types or pass --followup-id JRN-..."
            )

        print("\nCampaign")
        print(f"  Match: {match_name}")
        print(f"  Code:  {code}")
        print(f"  Date:  {date_label}")
        print(f"  Time:  {match_dt.strftime('%Y-%m-%d %H:%M')} {LOCAL_TZ_NAME}")
        print("\nWill create:")
        for t in ordered_types:
            print(f"  - {build_journey_name(t, match_name, code, date_label)}")

        if not args.yes:
            confirm = input("\nContinue? Type YES: ").strip()
            if confirm != "YES":
                print("Cancelled.")
                return 0

        session = requests.Session()
        out_dir = Path(OUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        created_ids: dict[str, str] = {}
        failed_types: list[str] = []

        for journey_type in ordered_types:
            print(f"\n[{journey_type}] Loading template...")
            template = load_template(TEMPLATE_FILES[journey_type])

            if args.dry_run:
                reserved_id = f"DRY-RUN-{journey_type.upper()}"
                print(f"[{journey_type}] Dry run enabled, using placeholder ID: {reserved_id}")
            else:
                print(f"[{journey_type}] Reserving new journey ID...")
                reserved_id = reserve_journey_id(session)
                print(f"[{journey_type}] Reserved ID: {reserved_id}")

            followup_id = None
            if journey_type == "two_hours":
                followup_id = followup_id_override or created_ids.get("followup")
                if followup_id:
                    print(f"[{journey_type}] Campaign connector -> FollowUp journey: {followup_id}")
                else:
                    print(
                        f"[{journey_type}] WARNING: no FollowUp ID available, "
                        "campaign connector keeps the template's old journey ID."
                    )

            body, settings_report = prepare_body(
                template, journey_type, match_name, code, match_dt, reserved_id,
                followup_id=followup_id,
            )
            created_ids[journey_type] = reserved_id

            print(f"[{journey_type}] Applied settings:")
            for line in settings_report:
                print(f"  {line}")
            out_path = out_dir / f"{reserved_id}_{journey_type}.json"
            out_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{journey_type}] Wrote payload: {out_path}")
            print(f"[{journey_type}] Name: {body['journeyName']}")

            checks = verify_body(
                body, journey_type, match_name, code, match_dt, reserved_id, followup_id
            )
            checks_ok = print_checks(journey_type, checks)
            if not checks_ok:
                failed_types.append(journey_type)

            if args.dry_run:
                print(f"[{journey_type}] Dry run enabled, not posting draft.")
                continue

            if not checks_ok:
                raise JourneyCloneError(
                    f"Verification failed for {journey_type}, draft NOT posted. "
                    f"Inspect {out_path} and fix before retrying."
                )

            print(f"[{journey_type}] Creating draft...")
            result = create_draft(session, body)
            print(f"[{journey_type}] Created draft. Response: {result}")

        if failed_types:
            print(f"\nVERIFICATION FAILED for: {', '.join(failed_types)}")
            return 1
        print(f"\nAll checks passed for: {', '.join(ordered_types)}")
        print("Done.")
        return 0

    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
