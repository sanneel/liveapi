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
import re
import sys
import uuid
from dataclasses import dataclass, field
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

TEMPLATE_TYPES = ("followup", "bfr", "two_hours", "aft")

# Creation order matters: the 2H campaign connector must point at the FollowUp
# journey created in the same run, so followup is always processed first.
TYPE_ORDER = ["followup", "bfr", "two_hours", "aft"]

# Journeys that start "immediately after publish" (startAt = now). Two of them
# created in the same run must not share the exact same startAt, so each is
# staggered by a minute. Match-relative types (two_hours, aft) are unaffected.
IMMEDIATE_TYPES = {"followup", "bfr"}


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class Team:
    """A club the cloner can build drafts for.

    A team either has its own captured template set in templates/<key>/ or
    inherits another team's via ``base_team`` (per-type files in its own folder
    still take precedence). This lets a club that is identical to another except
    for one visual asset reuse the base templates and only declare the swap in
    ``asset_overrides`` (old_url -> new_url), instead of duplicating big files.

    ``old_codes`` / ``old_match_texts`` / ``old_date_labels`` are curated hints
    for literal strings baked into the templates where the text differs from the
    journey name (truncated club names, stray notification metadata, secondary
    dates). Code/match/date are also derived from each template at runtime, so
    these lists only need the extra variants.
    """

    key: str
    label: str
    base_team: str | None = None
    asset_overrides: dict[str, str] = field(default_factory=dict)
    old_codes: tuple[str, ...] = ()
    old_match_texts: tuple[str, ...] = ()
    old_date_labels: tuple[str, ...] = ()


# UDCH visual assets, kept here as the keys a sibling club would override.
UDCH_CATFISH_BANNER = (
    "https://static.contentin.cloud/"
    "c93ad623-44ae-40f6-9aa5-b1aef7fd931a/f7f203d3-90d0-4251-ae68-8e3566625fbf.png"
)
UDCH_NOTIFICATION_ICON = (
    "https://static.contentin.cloud/"
    "c93ad623-44ae-40f6-9aa5-b1aef7fd931a/70dec629-9e67-4e52-9504-fec23989a565.png"
)


TEAMS: dict[str, Team] = {
    "udch": Team(
        key="udch",
        label="UDCH",
        old_codes=(
            "VAMOSBULLA",
            "XQTANTEMPRANO",  # stray promo in some AFT notification metadata
        ),
        old_match_texts=(
            "UDCH vs O'higgins",
            "UDCH vs O'higgin",
            "UDCH vs O\u2019Higgins",
            "UDCH vs O\u2019Higgin",
            "UDCH vs Audax",
        ),
        old_date_labels=(
            "10.06",
            "07.06",
            "23.11",
            "13.09",
        ),
    ),
    # Colo Colo is "the same journey as UDCH, one visual asset differs". It
    # inherits the UDCH templates (no duplication) and only needs the single
    # changed image declared below. To set it: put the Colo Colo image URL as
    # the value for the asset that differs (the catfish banner is the usual
    # one). Leave empty and Colo Colo clones render with the UDCH asset.
    # To instead use a fully separate Colo Colo design, drop captured files in
    # templates/colocolo/ and they take precedence over the inherited ones.
    "colocolo": Team(
        key="colocolo",
        label="Colo Colo",
        base_team="udch",
        asset_overrides={
            # UDCH_CATFISH_BANNER: "https://static.contentin.cloud/<colocolo>.png",
            # UDCH_NOTIFICATION_ICON: "https://static.contentin.cloud/<colocolo>.png",
        },
    ),
}

DEFAULT_TEAM = "udch"


def resolve_team(team_key: str) -> Team:
    key = (team_key or DEFAULT_TEAM).strip().lower()
    if key not in TEAMS:
        raise JourneyCloneError(
            f"Unknown team {team_key!r}. Known teams: {', '.join(sorted(TEAMS))}"
        )
    return TEAMS[key]


def template_path(team_key: str, journey_type: str) -> str:
    """Resolve a draft template, preferring the team's own file then its base."""
    team = resolve_team(team_key)
    own = TEMPLATES_DIR / team.key / f"{journey_type}.json"
    if own.exists() or not team.base_team:
        return str(own)
    base = TEMPLATES_DIR / team.base_team / f"{journey_type}.json"
    return str(base if base.exists() else own)


def template_files(team_key: str) -> dict[str, str]:
    """Resolved template path per draft type for a team."""
    return {t: template_path(team_key, t) for t in TEMPLATE_TYPES}


# Back-compat default so existing callers/imports keep working.
TEMPLATE_FILES = template_files(DEFAULT_TEAM)


@dataclass(frozen=True)
class OldValues:
    """Literal strings to replace in a template before re-posting it."""

    codes: tuple[str, ...]
    match_texts: tuple[str, ...]
    date_labels: tuple[str, ...]

    def all_values(self) -> list[str]:
        return [*self.codes, *self.match_texts, *self.date_labels]


def _journey_name_parts(name: str) -> list[str]:
    return [p.strip() for p in (name or "").split("|") if p.strip()]


def _derive_from_name(name: str) -> tuple[str | None, str | None, str | None]:
    """Best-effort (code, match, date) parse from a captured journey name.

    Names look like: "[Copy of] JBCL | SP | <match> | <code-part> | <type> | DD.MM"
    where <code-part> is e.g. "PrmCode-VAMOSBULLA", "Promocode - VAMOSBULLA" or
    "PromoCode COLOCOLO2026".
    """
    parts = _journey_name_parts(name)
    match = code = date = None

    for i, part in enumerate(parts):
        if part.upper() == "SP" and i + 1 < len(parts):
            match = parts[i + 1] or None
            break

    code_match = re.search(r"(?:Prm|Promo)Code\s*-?\s*([A-Za-z0-9]+)", name or "", re.I)
    if code_match:
        code = code_match.group(1)

    date_match = re.findall(r"\b(\d{1,2}\.\d{1,2})\b", name or "")
    if date_match:
        date = date_match[-1]

    return code, match, date


def _template_promocodes(template: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for d in walk_dicts(template):
        settings = d.get("promocodeSettings")
        if isinstance(settings, dict):
            for value in settings.get("values") or []:
                if isinstance(value, str) and value.strip():
                    codes.append(value.strip())
    return codes


def collect_old_values(template: dict[str, Any], team: Team) -> OldValues:
    """Curated team hints plus values derived from the template itself."""
    codes = list(team.old_codes)
    matches = list(team.old_match_texts)
    dates = list(team.old_date_labels)

    codes.extend(_template_promocodes(template))
    name = template.get("journeyName") or ""
    derived_code, derived_match, derived_date = _derive_from_name(name)
    if derived_code:
        codes.append(derived_code)
    if derived_match:
        matches.append(derived_match)
    if derived_date:
        dates.append(derived_date)

    def dedup(values: list[str]) -> tuple[str, ...]:
        # Longest first so overlapping variants ("O'higgins" vs "O'higgin")
        # replace the longer match before its prefix.
        seen: dict[str, None] = {}
        for v in sorted((x for x in values if x), key=len, reverse=True):
            seen.setdefault(v, None)
        return tuple(seen)

    return OldValues(dedup(codes), dedup(matches), dedup(dates))


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


def now_utc_api(dotnet_fraction: bool = False, offset_minutes: int = 0) -> str:
    # offset_minutes staggers "start now" journeys so two created in the same
    # run don't share an identical startAt (the backoffice rejects the second
    # with "the journey with the same identifier already exists").
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=offset_minutes)
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
            f"Failed to create draft\n"
            f"  reservedJourneyId: {body.get('reservedJourneyId')}\n"
            f"  journeyName:       {body.get('journeyName')!r}\n"
            f"  HTTP {response.status_code}\n"
            f"  response: {response.text}"
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


_UUID_RE = re.compile(
    r'"(?:activityId|id)"\s*:\s*"'
    r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"'
)


def regenerate_internal_ids(body: dict[str, Any]) -> int:
    """Give every internal activity/node/edge id a fresh UUID, consistently.

    A captured template reuses the source journey's activity UUIDs. Re-posting
    them creates a journey that claims ids already owned by the live source
    journey, which the backoffice rejects ("the same identifier used across
    campaigns"). The backoffice's own duplicate action regenerates these ids;
    we do the same here.

    Only structural ids (``activityId`` and ``id`` values) are remapped. External
    references (ContentId, promotionId, promotionLinkId, FrontId, ...) live under
    different keys and are left untouched so the draft keeps pointing at the
    right promotions/content. Handles, ports, edges and config keys embed the
    activity id as a substring, so a global string replace keeps them in sync.
    """
    text = json.dumps(body, ensure_ascii=False)
    old_ids = set(_UUID_RE.findall(text))
    if not old_ids:
        return 0
    mapping = {old: str(uuid.uuid4()) for old in old_ids}
    # Replace longest-first is unnecessary (all ids are the same length and
    # mutually non-overlapping), but guard against a fresh id colliding with a
    # not-yet-replaced old id by replacing on the original text positions.
    for old, new in mapping.items():
        text = text.replace(old, new)
    new_body = json.loads(text)
    body.clear()
    body.update(new_body)
    return len(mapping)


def clear_stale_campaign_connector_ids(body: dict[str, Any]) -> int:
    """Blank out stale campaignId values left over from the captured template.

    A captured template's campaign connector activity still carries the
    campaignId of the original "Campaign" object created when that connector
    was first linked (in rawJourneyData's mirror of the same activity this
    field is already blank, which is the unlinked state). Every clone made
    from the template reuses this same campaignId byte-for-byte regardless
    of match/code/date — re-posting it tells the backoffice this connector
    belongs to a campaign that already exists, which is the real cause of
    "the journey with the same identifier already exists", not the journey
    name or reservedJourneyId. Blanking it lets the backoffice mint a fresh
    campaign binding, same as the UI does for a not-yet-linked connector.
    """
    count = 0
    for d in walk_dicts(body):
        conditions = d.get("campaignConnectorConditions")
        if isinstance(conditions, dict) and conditions.get("campaignId"):
            conditions["campaignId"] = ""
            count += 1
    return count


def strip_promotion_display_ids(body: dict[str, Any]) -> int:
    """Remove stale promotionDisplayId values left over from the captured template.

    Every promotion / multipurpose_promotion activity carries a
    ``promotionDisplayId`` that the backoffice mints server-side when the
    promotion is first placed (it appears both in ``activities[].
    initializationData`` and in the ``rawJourneyData`` mirror of the same
    activity). A captured template still holds the source journey's display
    ids, so re-posting them makes the backoffice reject the draft with
    "Promotion activity with PromotionDisplayId: 'NNN' already exists" (HTTP
    422). These ids are not referenced anywhere else in the payload — every
    internal link uses promotionId / promotionLinkId / journeyActivityId — so
    dropping them is safe and lets the backoffice assign fresh display ids,
    exactly as it does for a promotion added in the UI. Returns the count
    removed.
    """
    count = 0
    for d in walk_dicts(body):
        if "promotionDisplayId" in d:
            d.pop("promotionDisplayId")
            count += 1
    return count


def strip_duplicate_lineage(body: dict[str, Any]) -> list[str]:
    """Drop "copied from journey X" markers so the draft is created standalone.

    A captured template still carries duplicatedFromId/Version pointing at the
    journey it was copied from. Re-posting that tells the backoffice the new
    draft is another copy of that source, which fails with "the journey with
    the same identifier already exists" when a draft from that source already
    exists. We always reserve a fresh reservedJourneyId, so this lineage is just
    stale metadata. Returns a log of what was removed.
    """
    removed: list[str] = []
    for key in ("duplicatedFromId", "duplicatedFromVersion"):
        if key in body:
            body.pop(key)
            removed.append(key)
    return removed


def set_raw_info(body: dict[str, Any], key: str, value: Any) -> None:
    raw = body.setdefault("rawJourneyData", {})
    info = raw.setdefault("infoValues", {})
    info[key] = value


def set_dates(
    body: dict[str, Any],
    journey_type: str,
    match_dt: datetime,
    now_offset_minutes: int = 0,
) -> None:
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
        start_top = now_utc_api(dotnet_fraction=True, offset_minutes=now_offset_minutes)
        stop_top = utc_api(bfr_stop, dotnet_fraction=True)
        start_info = now_utc_api(offset_minutes=now_offset_minutes)
        stop_info = utc_api(bfr_stop)
        immediate = True
    elif journey_type == "aft":
        start_top = utc_api(aft_start, dotnet_fraction=True)
        stop_top = utc_api(next_day_midnight, dotnet_fraction=True)
        start_info = utc_api(aft_start)
        stop_info = utc_api(next_day_midnight)
        immediate = False
    elif journey_type == "followup":
        start_top = now_utc_api(dotnet_fraction=True, offset_minutes=now_offset_minutes)
        stop_top = utc_api(followup_stop, dotnet_fraction=True)
        start_info = now_utc_api(offset_minutes=now_offset_minutes)
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
    old_values: OldValues,
    followup_id: str | None = None,
    asset_overrides: dict[str, str] | None = None,
    now_offset_minutes: int = 0,
    name_suffix: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Returns the prepared body plus a log of every setting that was changed."""
    body = copy.deepcopy(template)
    date_label = match_dt.strftime("%d.%m")
    clean_name = build_journey_name(journey_type, match_name, code, date_label)
    if name_suffix:
        # Keeps the journey name unique per run so re-creating the same campaign
        # doesn't trip the backoffice's "same identifier already exists" check.
        clean_name = f"{clean_name} #{name_suffix}"
    report: list[str] = []

    replacements: dict[str, str] = {}
    for old_code in old_values.codes:
        replacements[old_code] = code
    for old_match in old_values.match_texts:
        replacements[old_match] = match_name
    for old_date in old_values.date_labels:
        replacements[old_date] = date_label
    # Team visual-asset swaps (old URL -> club URL). Applied as plain string
    # replacements like everything else.
    for old_asset, new_asset in (asset_overrides or {}).items():
        if old_asset and new_asset:
            replacements[old_asset] = new_asset

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

    removed_lineage = strip_duplicate_lineage(body)
    if removed_lineage:
        report.append(f"removed {', '.join(removed_lineage)} (create as standalone draft)")

    cleared_campaign_ids = clear_stale_campaign_connector_ids(body)
    if cleared_campaign_ids:
        report.append(
            f"cleared stale campaignId in {cleared_campaign_ids} campaign connector(s) "
            "(let backoffice mint a fresh campaign binding)"
        )

    removed_display_ids = strip_promotion_display_ids(body)
    if removed_display_ids:
        report.append(
            f"removed {removed_display_ids} stale promotionDisplayId(s) "
            "(let backoffice mint fresh promotion display ids)"
        )

    id_count = regenerate_internal_ids(body)
    if id_count:
        report.append(f"regenerated {id_count} internal activity ids (unique per campaign)")

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

    set_dates(body, journey_type, match_dt, now_offset_minutes=now_offset_minutes)
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
    old_values: OldValues,
    name_suffix: str = "",
) -> list[tuple[bool, str]]:
    """Run sanity checks on a generated payload. Returns (ok, message) pairs."""
    checks: list[tuple[bool, str]] = []
    serialized = json.dumps(body, ensure_ascii=False)
    date_label = match_dt.strftime("%d.%m")
    expected_name = build_journey_name(journey_type, match_name, code, date_label)
    if name_suffix:
        expected_name = f"{expected_name} #{name_suffix}"

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

    # A new value that equals (or contains, e.g. VAMOSBULLA -> VAMOSBULLANGUEROS)
    # one of the old values is not a leftover — strip every occurrence of the
    # new values out of the serialized body before looking for old ones, so an
    # old value that only survives as a substring of its own replacement isn't
    # flagged as a false positive.
    new_values = {code, match_name, date_label}
    scrubbed = serialized
    for new in new_values:
        if new:
            scrubbed = scrubbed.replace(new, "")
    leftovers = [
        old for old in old_values.all_values()
        if old not in new_values and old in scrubbed
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

    stale_campaign_ids = [
        d["campaignConnectorConditions"]["campaignId"]
        for d in walk_dicts(body)
        if isinstance(d.get("campaignConnectorConditions"), dict)
        and d["campaignConnectorConditions"].get("campaignId")
    ]
    checks.append((
        not stale_campaign_ids,
        "no stale campaignId in campaign connector(s)"
        if not stale_campaign_ids
        else f"stale campaignId still present in campaign connector(s): {stale_campaign_ids}",
    ))

    leftover_display_ids = [
        d["promotionDisplayId"]
        for d in walk_dicts(body)
        if d.get("promotionDisplayId")
    ]
    checks.append((
        not leftover_display_ids,
        "no stale promotionDisplayId in payload"
        if not leftover_display_ids
        else f"stale promotionDisplayId still present: {leftover_display_ids}",
    ))

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
    parser.add_argument(
        "--team",
        choices=sorted(TEAMS),
        default=DEFAULT_TEAM,
        help=f"Template set / club to clone (default: {DEFAULT_TEAM}).",
    )
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
    parser.add_argument(
        "--no-unique-name",
        action="store_true",
        help="Do NOT append a per-run uniqueness tag to the journey name. By "
        "default a short tag is added so re-creating the same campaign does not "
        'collide with "the journey with the same identifier already exists".',
    )
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

        team = resolve_team(args.team)
        team_templates = template_files(team.key)
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
        print(f"  Team:  {team.label}")
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
        immediate_offset = 0  # stagger "start now" journeys by a minute each
        # Per-run uniqueness tag for the journey name (on unless --no-unique-name).
        name_suffix = "" if args.no_unique_name else datetime.now(LOCAL_TZ).strftime("%d%m-%H%M%S")
        if name_suffix:
            print(f"  Name tag: #{name_suffix}  (use --no-unique-name to disable)")
        # Diagnostic: if the platform ever hands back a reserved id we've already
        # used this run, the reserve endpoint — not the name — is the collision.
        seen_reserved: set[str] = set()

        for journey_type in ordered_types:
            print(f"\n[{journey_type}] Loading template...")
            template = load_template(team_templates[journey_type])
            old_values = collect_old_values(template, team)

            now_offset_minutes = 0
            if journey_type in IMMEDIATE_TYPES:
                now_offset_minutes = immediate_offset
                immediate_offset += 1

            if args.dry_run:
                reserved_id = f"DRY-RUN-{journey_type.upper()}"
                print(f"[{journey_type}] Dry run enabled, using placeholder ID: {reserved_id}")
            else:
                print(f"[{journey_type}] Reserving new journey ID...")
                reserved_id = reserve_journey_id(session)
                print(f"[{journey_type}] Reserved ID: {reserved_id}")
                if reserved_id in seen_reserved:
                    print(
                        f"[{journey_type}] !! DUPLICATE reserved id {reserved_id} — the "
                        "platform is NOT issuing fresh ids for drafts. THIS is the "
                        "'same identifier already exists' cause, not the journey name."
                    )
                seen_reserved.add(reserved_id)

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
                old_values, followup_id=followup_id,
                asset_overrides=team.asset_overrides,
                now_offset_minutes=now_offset_minutes,
                name_suffix=name_suffix,
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
                body, journey_type, match_name, code, match_dt, reserved_id,
                followup_id, old_values, name_suffix=name_suffix,
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
