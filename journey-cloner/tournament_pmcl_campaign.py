#!/usr/bin/env python3
"""
Build the PMCL (Fortunazo) "Tournament" communications Journey Builder draft:
Notification (NC) + Pop-up (Cat-fish) + SMS, all wired to the Smartico
tournament deeplink (``#_smartico_dp=dp:<slug>&id=<tournament id>``) the
player lands on — exactly the same paste-a-sheet → get-a-console-script flow
as the GOW comms generator (comms_campaign.py), but for the tournament promo
on the PMCL brand instead of a Game-of-the-Week promo page.

Email is left untouched — the captured template already points at its email
content; fill/adjust it by hand in the backoffice afterwards (same policy as
GOW comms).

This wraps templates/casino/tournament_pmcl_comms.json (a captured tournament
comms journey draft) and:
  * sets the journey's dates + name for this run,
  * rewrites the Notification (contract 1) and Pop-up (contract 5) title /
    description / caption for both languages,
  * rewrites the SMS body for both languages, with the "Fortunazo | " prefix,
  * points every channel's link/deeplink at the tournament (optionally swapping
    in a new --tournament-id), and
  * leaves two placeholder tokens for the photos (NC icon, Pop-up background)
    that the console script fills in at paste time — but ONLY when a PMCL
    media-library --folder-id is given. Without a folder id the captured
    template's existing image URLs are kept (no file pickers).

The entry window is fixed to the same day as --date, 12:00 -> 19:00 Chile
time (identical to GOW comms).

Usage:
  python tournament_pmcl_campaign.py --date 2026-06-29 --spec spec.txt \
      --tournament-id 5431

  # or pipe the pasted spreadsheet block straight in:
  pbpaste | python tournament_pmcl_campaign.py --date 2026-06-29 --spec -

Then paste console_scripts/<name>_console.js into the DevTools console on a
logged-in PMCL backoffice tab. Use --dry-run to write the prepared payload to
out/ without generating a script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from create_journeys import (
    LOCAL_TZ,
    clear_stale_campaign_connector_ids,
    set_notification_metadata_journey_name,
    strip_duplicate_lineage,
    strip_promotion_display_ids,
)
from casino_journey import chile_same_day_window, set_dates
from spec_parser import ChannelCopy, SmsCopy, parse_spec
from tournament_pmcl_email import EMAIL_CONTENT_ID_TOKEN, email_name, prepare_email_content

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "casino" / "tournament_pmcl_comms.json"

# PMCL (Fortunazo) backoffice — same host/brand the NC-For-Discount PMCL
# generator uses (see nc_discount_pmcl_campaign.py).
BASE_URL = "https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0"
BRAND = "PMCL"

# Paste-time placeholders, swapped for the real upload's absolute_link once the
# console script has uploaded the chosen photo for that slot (only when a
# --folder-id is given; otherwise the template's existing URLs are kept).
NC_ICON_TOKEN = "@@NC_ICON_URL@@"
POPUP_BG_TOKEN = "@@POPUP_BG_URL@@"
EMAIL_HERO_TOKEN = "@@EMAIL_HERO_URL@@"
RESERVED_ID_TOKEN = "DRY-RUN-TOURNAMENT-PMCL"

# The tournament comms entry window is always same-day 12:00 -> 19:00 Chile
# time (matches the captured draft and the GOW comms window).
COMMS_START_HOUR = 12
COMMS_END_HOUR = 19

SMS_PREFIX = "Fortunazo | "

# The Smartico deeplink baked into the notification/pop-up/SMS links, e.g.
# https://%#BrandDomain%?%$utm_tags%#_smartico_dp=dp:gf_tournaments&id=5431
_LINK_RE = re.compile(r"#_smartico_dp=dp:(?P<slug>[A-Za-z0-9_]+)&id=(?P<id>\d+)")
DEFAULT_TOURNAMENT_SLUG = "gf_tournaments"


def nc_dict_from_spec(nc: ChannelCopy) -> dict[str, str]:
    return {
        "title_en": nc.title_en, "title_es": nc.title_es,
        "desc_en": nc.desc_en, "desc_es": nc.desc_es,
        "caption_en": nc.caption_en, "caption_es": nc.caption_es,
    }


def popup_dict_from_spec(popup: ChannelCopy) -> dict[str, str]:
    return nc_dict_from_spec(popup)


def sms_dict_from_spec(sms: SmsCopy) -> dict[str, str]:
    return {"text_en": sms.text_en, "text_es": sms.text_es}


def email_dict_from_spec(spec) -> dict[str, str] | None:
    """Email content inputs, or None when the spec has no email copy — in which
    case the journey's email activity is left untouched.

    Unlike GOW's sheet, the tournament sheet's channel rows carry no TRUE/FALSE
    flag (every channel is always sent), so the presence of the Email subject +
    pre-header is what drives building the email — not an enabled flag."""
    email = spec.email
    if not (email.subject_es and email.preheader_es):
        return None
    return {
        "subject_es": email.subject_es,
        "preheader_es": email.preheader_es,
        "desc_es": email.desc_es,
    }


def find_notification(body: dict, contract: int) -> dict:
    for a in body.get("activities", []):
        init = a.get("initializationData") or {}
        if a.get("activityName") == "notification_center" and init.get("contract") == contract:
            return a
    raise ValueError(f"notification_center activity with contract={contract} not found in template")


def find_sms(body: dict) -> dict:
    for a in body.get("activities", []):
        if a.get("activityName") == "dextra_sms":
            return a
    raise ValueError("dextra_sms activity not found in template")


def find_email(body: dict) -> dict:
    for a in body.get("activities", []):
        if a.get("activityName") == "dextra_email":
            return a
    raise ValueError("dextra_email activity not found in template")


def update_email_activity(activity: dict, content_name: str) -> None:
    """Point the journey's email activity at the about-to-be-created content.

    The real content id is only known once the console script creates it at
    paste time, so leave EMAIL_CONTENT_ID_TOKEN here and let the script swap
    it in (same mechanic as the reserved journey id)."""
    init = activity["initializationData"]
    settings = init["emailSettings"]
    settings["template"] = {"id": EMAIL_CONTENT_ID_TOKEN}
    settings["emailSource"] = "Template"
    init["displayData"] = [f"{EMAIL_CONTENT_ID_TOKEN} {content_name}"]


def find_wait_date_activities(body: dict) -> list[dict]:
    """Find all wait_date activities in the journey."""
    return [a for a in body.get("activities", []) if a.get("activityName") == "wait_date"]


def calc_tournament_days(start_date: str, end_date: str) -> int:
    """Calculate days between start and end dates (YYYY-MM-DD format).
    Includes both start and end dates (e.g., July 20-26 = 7 days)."""
    from datetime import datetime
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    delta = (end - start).days
    return delta + 1  # Include both endpoints


def update_wait_date(activity: dict, wait_until_iso: str) -> None:
    """Update a wait_date activity to wait until a specific date (ISO 8601).
    Assumes wait until start of day (00:00 UTC)."""
    init = activity["initializationData"]
    # Parse the ISO date and set waitTo to that date at 16:00 UTC (12:00 Chile)
    date_part = wait_until_iso.split("T")[0]
    init["waitTo"] = f"{date_part}T16:00:00Z"
    # Update display data (DD.MM.YY format)
    parts = date_part.split("-")
    if len(parts) == 3:
        year = parts[0][2:]  # Last 2 digits of year
        init["displayData"] = [f"{parts[2]}.{parts[1]}.{year}"]


def update_notification_revoke(activity: dict, days: int) -> None:
    """Update notification revoke period (expire_after) based on tournament days."""
    init = activity["initializationData"]
    obj = init.get("objectForSend", {})
    if obj:
        # Format: "D.HH:MM:SS.mmm"
        obj["expire_after"] = f"{days}.00:00:00.000"


def template_link(body: dict) -> tuple[str, str]:
    """Read the (slug, id) of the Smartico tournament deeplink baked in the
    template so a run that doesn't override --tournament-id keeps them."""
    m = _LINK_RE.search(json.dumps(body, ensure_ascii=False))
    if m:
        return m.group("slug"), m.group("id")
    return DEFAULT_TOURNAMENT_SLUG, ""


def notif_link(slug: str, tournament_id: str) -> str:
    return f"https://%#BrandDomain%?%$utm_tags%#_smartico_dp=dp:{slug}&id={tournament_id}"


def sms_link(slug: str, tournament_id: str) -> str:
    return "https://{{BrandDomain}}?%$utm_tags%#_smartico_dp=dp:" + f"{slug}&id={tournament_id}"


def set_var(variables: list[dict], name: str, value: str) -> int:
    n = 0
    for v in variables:
        if v.get("name") == name:
            v["value"] = value
            n += 1
    return n


def update_notification(
    activity: dict,
    *,
    title_en: str,
    title_es: str,
    desc_en: str,
    desc_es: str,
    caption_en: str,
    caption_es: str,
    link: str,
    deeplink: str,
    icon: str | None,
) -> None:
    """Notification (contract 1). Its variables are hyphenated (title-en,
    description-en, caption-en) and the link/deeplink/icon-src live once each
    in the common tab — unlike GOW's notification, so this is PMCL-specific."""
    init = activity["initializationData"]
    variables = init["objectForSend"]["variables"]
    set_var(variables, "title-en", title_en)
    set_var(variables, "title-es", title_es)
    set_var(variables, "description-en", desc_en)
    set_var(variables, "description-es", desc_es)
    set_var(variables, "caption-en", caption_en)
    set_var(variables, "caption-es", caption_es)
    set_var(variables, "link", link)
    set_var(variables, "deeplink", deeplink)
    if icon is not None:
        set_var(variables, "icon-src", icon)

    tabs = init["singleChannel"]["localizedLanguagesTab"]
    tabs["en"]["title-en"] = title_en
    tabs["en"]["description-en"] = desc_en
    tabs["en"]["caption-en"] = caption_en
    tabs["es"]["title-es"] = title_es
    tabs["es"]["description-es"] = desc_es
    tabs["es"]["caption-es"] = caption_es
    tabs["common"]["link"] = link
    tabs["common"]["deeplink"] = deeplink
    if icon is not None:
        tabs["common"]["icon-src"] = icon


def update_popup(
    activity: dict,
    *,
    title_en: str,
    title_es: str,
    desc_en: str,
    desc_es: str,
    caption_en: str,
    caption_es: str,
    link: str,
    deeplink: str,
    bg: str | None,
) -> None:
    """Pop-up (Cat-fish, contract 5). Underscored variables (title_en,
    description_en, caption_en) with link/deeplink/background_image_src in the
    common tab."""
    init = activity["initializationData"]
    variables = init["objectForSend"]["variables"]
    set_var(variables, "title_en", title_en)
    set_var(variables, "title_es", title_es)
    set_var(variables, "description_en", desc_en)
    set_var(variables, "description_es", desc_es)
    set_var(variables, "caption_en", caption_en)
    set_var(variables, "caption_es", caption_es)
    set_var(variables, "link", link)
    set_var(variables, "deeplink", deeplink)
    if bg is not None:
        set_var(variables, "background_image_src", bg)

    tabs = init["singleChannel"]["localizedLanguagesTab"]
    tabs["en"]["title_en"] = title_en
    tabs["en"]["description_en"] = desc_en
    tabs["en"]["caption_en"] = caption_en
    tabs["es"]["title_es"] = title_es
    tabs["es"]["description_es"] = desc_es
    tabs["es"]["caption_es"] = caption_es
    tabs["common"]["link"] = link
    tabs["common"]["deeplink"] = deeplink
    if bg is not None:
        tabs["common"]["background_image_src"] = bg


_SMS_PREFIX_RE = re.compile(r"^\s*[^|\n]{1,20}\|")


def sms_text(body_text: str) -> str:
    """Always prepend 'Fortunazo |' to the SMS text, stripping any existing
    'Brand |' prefix first (the copy from the sheet is used verbatim after
    applying the required prefix)."""
    body_text = (body_text or "").strip()
    # Remove any existing "Brand |" prefix
    body_text = _SMS_PREFIX_RE.sub("", body_text).lstrip()
    if not body_text.lower().startswith(SMS_PREFIX.lower()):
        body_text = SMS_PREFIX + body_text
    return body_text


def update_sms(activity: dict, *, text_en: str, text_es: str, link: str) -> None:
    body_es = sms_text(text_es)
    body_en = sms_text(text_en)

    init = activity["initializationData"]
    brand_var = _first_brand_var(init)

    raw = init["rawValues"]
    raw["languageCode"] = "es"
    raw["variables"] = [dict(brand_var)]
    raw["messageText"] = f"{body_es}\n{link}"
    raw["localizedMessageTexts"] = {
        "es": {"variables": [dict(brand_var)], "messageText": f"{body_es} {link}", "languageCode": "es"},
        "en": {"variables": [dict(brand_var)], "messageText": f"{body_en} {link}", "languageCode": "en"},
    }

    flattened_es = f"{body_es} {link}"
    flattened_en = f"{body_en} {link}"
    settings = init["smsSettings"]
    settings["languageCode"] = "es"
    settings["variables"] = [dict(brand_var)]
    settings["messageText"] = flattened_es
    settings["localizedMessageTexts"] = [
        {"variables": [dict(brand_var)], "messageText": flattened_es, "languageCode": "es"},
        {"variables": [dict(brand_var)], "messageText": flattened_en, "languageCode": "en"},
    ]
    init["displayData"] = [flattened_es]
    init["listOfUsedVariables"] = ["BrandDomain"]


def _first_brand_var(init: dict) -> dict:
    """Reuse the template's BrandDomain variable definition verbatim."""
    for src in (init.get("rawValues"), init.get("smsSettings")):
        for v in (src or {}).get("variables", []) or []:
            if v.get("name") == "BrandDomain":
                return v
    return {"name": "BrandDomain", "activityId": "", "dataSource": "dwh_source", "isRequired": True, "defaultValue": ""}


def mirror_into_raw_journey_data(body: dict, activity: dict) -> bool:
    """Sync an activity's editor-side copy (rawJourneyData) from the compiled
    one just edited. Identical mechanics to comms_campaign.py."""
    import copy

    raw = body.get("rawJourneyData")
    if not isinstance(raw, dict):
        return False
    ac = raw.get("activitiesConfiguration")
    if not isinstance(ac, dict):
        return False
    cfg = ac.get(activity.get("activityId"))
    if not isinstance(cfg, dict):
        return False
    data = copy.deepcopy(activity["initializationData"])
    display = data.pop("displayData", None)
    cfg["data"] = data
    if display is not None and "displayData" in cfg:
        cfg["displayData"] = copy.deepcopy(display)
    return True


def set_comms_name(body: dict, start_local: datetime, name_override: str = "") -> str:
    if name_override.strip():
        new_name = name_override.strip()
    else:
        name = re.sub(r"^(Copy of )+", "", body.get("journeyName", ""))
        new_name = name
    body["journeyName"] = new_name
    raw = body.get("rawJourneyData")
    if isinstance(raw, dict):
        info = raw.get("infoValues")
        if isinstance(info, dict):
            info["journeyName"] = new_name
    set_notification_metadata_journey_name(body, new_name)
    return new_name


def prepare_comms(
    *,
    date_str: str,
    journey_name: str,
    tournament_id: str,
    nc: dict[str, str],
    popup: dict[str, str],
    sms: dict[str, str],
    upload_photos: bool,
    tournament_start_date: str = "",
    tournament_end_date: str = "",
    email: dict[str, str] | None = None,
) -> tuple[dict, list[str], datetime, datetime, dict | None]:
    body = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8-sig"))
    report: list[str] = []

    slug, tpl_id = template_link(body)
    tid = (tournament_id or "").strip() or tpl_id
    if not tid:
        raise ValueError("No tournament id in the template — pass --tournament-id.")
    notif = notif_link(slug, tid)
    sms_url = sms_link(slug, tid)
    report.append(f"tournament link: dp:{slug}&id={tid}")

    start_local, stop_local = chile_same_day_window(date_str, COMMS_START_HOUR, COMMS_END_HOUR)
    set_dates(body, start_local, stop_local)
    report.append(
        f"startAt {body['startAt']} ({start_local:%Y-%m-%d %H:%M} Chile) -> "
        f"stopAt {body['stopAt']} ({stop_local:%Y-%m-%d %H:%M} Chile)"
    )

    new_name = set_comms_name(body, start_local, journey_name)
    report.append(f"journeyName = {new_name!r}")

    removed = strip_duplicate_lineage(body)
    if removed:
        report.append(f"removed {', '.join(removed)}")
    cc = clear_stale_campaign_connector_ids(body)
    if cc:
        report.append(f"cleared {cc} stale campaignId(s)")
    dd = strip_promotion_display_ids(body)
    if dd:
        report.append(f"removed {dd} stale promotionDisplayId(s)")

    icon = NC_ICON_TOKEN if upload_photos else None
    bg = POPUP_BG_TOKEN if upload_photos else None

    notif_act = find_notification(body, contract=1)
    update_notification(
        notif_act,
        title_en=nc["title_en"], title_es=nc["title_es"],
        desc_en=nc["desc_en"], desc_es=nc["desc_es"],
        caption_en=nc["caption_en"], caption_es=nc["caption_es"],
        link=notif, deeplink=notif, icon=icon,
    )
    mirror_into_raw_journey_data(body, notif_act)
    report.append("Notification (contract 1): title/description/caption/link set"
                  + (", icon pending photo upload" if upload_photos else ", icon kept from template"))

    popup_act = find_notification(body, contract=5)
    update_popup(
        popup_act,
        title_en=popup["title_en"], title_es=popup["title_es"],
        desc_en=popup["desc_en"], desc_es=popup["desc_es"],
        caption_en=popup["caption_en"], caption_es=popup["caption_es"],
        link=notif, deeplink=notif, bg=bg,
    )
    mirror_into_raw_journey_data(body, popup_act)
    report.append("Pop-up (contract 5): title/description/caption/link set"
                  + (", background pending photo upload" if upload_photos else ", background kept from template"))

    sms_act = find_sms(body)
    update_sms(sms_act, text_en=sms["text_en"], text_es=sms["text_es"], link=sms_url)
    mirror_into_raw_journey_data(body, sms_act)
    report.append("SMS: body + tournament link set for EN/ES")

    # Update wait_date activities and notification revoke period if tournament dates provided
    if tournament_start_date and tournament_end_date:
        wait_acts = find_wait_date_activities(body)
        if len(wait_acts) >= 2:
            update_wait_date(wait_acts[0], tournament_start_date)
            update_wait_date(wait_acts[1], tournament_end_date)
            report.append(f"Wait/Date activities: updated to tournament window {tournament_start_date} → {tournament_end_date}")

        # Update notification revoke period based on tournament duration
        tournament_days = calc_tournament_days(tournament_start_date, tournament_end_date)
        update_notification_revoke(notif_act, tournament_days)
        report.append(f"Notification revoke: set to {tournament_days} days (tournament duration)")
    else:
        report.append("⚠ Tournament start/end dates not provided — Wait/Date activities and notification revoke use template defaults")

    email_content = None
    if email:
        content_name = email_name(date_str)
        email_content = prepare_email_content(
            date_str=date_str,
            subject_es=email["subject_es"],
            preheader_es=email["preheader_es"],
            desc_es=email.get("desc_es", ""),
            tournament_id=tid,
        )
        email_act = find_email(body)
        update_email_activity(email_act, content_name)
        mirror_into_raw_journey_data(body, email_act)
        report.append(
            f"Email: content {content_name!r} prepared (subject/pre-header/body/link set); "
            "journey email activity repointed to the new content"
        )
    else:
        report.append("Email left untouched (edit it by hand in the backoffice)")

    body["reservedJourneyId"] = RESERVED_ID_TOKEN
    report.append(f"reservedJourneyId = {RESERVED_ID_TOKEN}")
    return body, report, start_local, stop_local, email_content


def verify(body: dict, tournament_id: str, upload_photos: bool) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    serialized = json.dumps(body, ensure_ascii=False)

    checks.append((bool(body.get("journeyName")), f"journeyName is {body.get('journeyName')!r}"))
    checks.append((body.get("reservedJourneyId") == RESERVED_ID_TOKEN, f"reservedJourneyId is {body.get('reservedJourneyId')!r}"))
    checks.append((body.get("brand") == BRAND, f"brand is {body.get('brand')!r}"))

    slug, tpl_id = template_link(body)
    tid = (tournament_id or "").strip() or tpl_id
    checks.append((f"&id={tid}" in serialized, f"tournament id {tid!r} present in links"))

    raw = body.get("rawJourneyData") or {}
    raw_serialized = json.dumps(raw, ensure_ascii=False)
    checks.append((f"&id={tid}" in raw_serialized, "tournament link present in editor copy (rawJourneyData)"))
    checks.append((_editor_copies_in_sync(body), "editor copy (rawJourneyData) matches the edited activities"))

    if upload_photos:
        checks.append((NC_ICON_TOKEN in serialized, "NC icon placeholder present (filled at paste time)"))
        checks.append((POPUP_BG_TOKEN in serialized, "Pop-up background placeholder present (filled at paste time)"))
    else:
        checks.append((NC_ICON_TOKEN not in serialized and POPUP_BG_TOKEN not in serialized,
                       "no photo placeholders (template image URLs kept)"))
    sms_act = next((a for a in body.get("activities", []) if a.get("activityName") == "dextra_sms"), None)
    sms_body = ((sms_act or {}).get("initializationData") or {}).get("smsSettings", {}).get("messageText", "")
    checks.append((sms_body.lower().startswith(SMS_PREFIX.lower()), f"SMS text starts with 'Fortunazo |' ({sms_body[:22]!r}...)"))
    checks.append(("duplicatedFromId" not in body, "no stale duplicatedFromId"))
    checks.append(("duplicatedFromVersion" not in body, "no stale duplicatedFromVersion"))

    promo_display_ids = [d["promotionDisplayId"] for d in _walk_dicts(body) if "promotionDisplayId" in d]
    checks.append((not promo_display_ids, "no stale promotionDisplayId in payload" if not promo_display_ids else f"stale promotionDisplayId(s): {promo_display_ids}"))

    # When the email is driven by the spec, the email activity must point at the
    # to-be-created content (token), not the stale captured CSE id.
    email_act = next((a for a in body.get("activities", []) if a.get("activityName") == "dextra_email"), None)
    if email_act is not None:
        tmpl_id = ((email_act.get("initializationData") or {}).get("emailSettings") or {}).get("template", {}).get("id")
        if tmpl_id == EMAIL_CONTENT_ID_TOKEN:
            checks.append((EMAIL_CONTENT_ID_TOKEN in raw_serialized, "email activity repoint mirrored into editor copy"))
    return checks


def _editor_copies_in_sync(body: dict) -> bool:
    import copy

    ac = (body.get("rawJourneyData") or {}).get("activitiesConfiguration") or {}
    for a in body.get("activities", []):
        name = a.get("activityName")
        init = a.get("initializationData") or {}
        if name == "notification_center" and init.get("contract") in (1, 5):
            pass
        elif name == "dextra_sms":
            pass
        elif name == "dextra_email" and (
            (init.get("emailSettings") or {}).get("template", {}).get("id") == EMAIL_CONTENT_ID_TOKEN
        ):
            # Only the email we actually repointed needs mirroring; an untouched
            # captured email activity is left exactly as it was.
            pass
        else:
            continue
        cfg = ac.get(a.get("activityId"))
        if not isinstance(cfg, dict):
            return False
        expected = copy.deepcopy(init)
        expected_display = expected.pop("displayData", None)
        if cfg.get("data") != expected:
            return False
        if expected_display is not None and cfg.get("displayData") != expected_display:
            return False
    return True


def _walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


JS_TEMPLATE = r"""// PMCL Tournament Communications console script — generated @GENERATED_AT@
// Journey: @JOURNEY_NAME@
//
// Paste into the DevTools console on a logged-in PMCL backoffice tab. It will:
//   1. capture the auth token from the page's own requests,
//   2. (only when a media-library FOLDER_ID is baked in) pop a file picker for
//      the NC icon, then another for the Pop-up background — each photo is
//      uploaded to the media library and its URL written into the right slot,
//   3. reserve a journey id and create the comms journey draft
//      (Notification + Pop-up + SMS — email is untouched, fill it by hand).
// Heavy logging throughout; it stops at the first error.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const PAYLOAD = @PAYLOAD@;
  const FOLDER_ID = @FOLDER_ID@;              // '' -> no photo upload, keep template images
  const NC_ICON_TOKEN = @NC_ICON_TOKEN@;
  const POPUP_BG_TOKEN = @POPUP_BG_TOKEN@;
  const RESERVED_ID_TOKEN = @RESERVED_ID_TOKEN@;
  const EMAIL_CONTENT = @EMAIL_CONTENT@;            // null when email is left untouched
  const EMAIL_CONTENT_ID_TOKEN = @EMAIL_CONTENT_ID_TOKEN@;

  const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');
  const CONTENT_BASE = CRM_BASE + '/content-studio/v0/eb-backoffice/email/contents';

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

  function pickFile(label) {
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      Object.assign(input.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999, background: '#fff', padding: '8px', border: '3px solid #22c55e', borderRadius: '6px' });
      document.body.appendChild(input);
      console.log('%cSelect the ' + label + ' photo in the file picker (top-left of the page).', 'color:#eab308;font-weight:bold');
      input.addEventListener('change', () => {
        const f = input.files && input.files[0];
        input.remove();
        if (!f) { reject(new Error('No file selected.')); return; }
        console.log('Photo selected for ' + label + ':', f.name, '(' + f.size + ' bytes)');
        resolve(f);
      });
    });
  }

  function imageDims(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve({ width: img.naturalWidth, height: img.naturalHeight }); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read image dimensions for ' + file.name)); };
      img.src = url;
    });
  }

  const auth = await obtainAuth();
  const headers = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND });

  async function uploadAsset(file, label) {
    const dims = await imageDims(file);
    const baseName = (file.name || 'photo').replace(/\.[^./]+$/, '');
    const url = CRM_BASE + '/media-library/v0/folder/' + FOLDER_ID + '/upload/'
      + encodeURIComponent(baseName) + '.png?height=' + dims.height + '&width=' + dims.width;
    const fd = new FormData();
    fd.append('file', file, file.name);
    const r = await fetch(url, { method: 'PUT', headers: headers(), credentials: 'include', body: fd });
    const resp = await r.text();
    if (!r.ok) throw new Error(label + ' upload failed: HTTP ' + r.status + ' ' + resp);
    const asset = JSON.parse(resp);
    console.log('  [' + label + '] uploaded asset', asset.id, '->', asset.absolute_link);
    const thumbFd = new FormData();
    thumbFd.append('file', file, file.name);
    const tr = await fetch(CRM_BASE + '/media-library/v0/asset/thumb/' + asset.id + '.png', { method: 'PUT', headers: headers(), credentials: 'include', body: thumbFd });
    if (!tr.ok) console.warn('  [' + label + '] thumbnail upload failed (non-fatal): HTTP ' + tr.status, await tr.text());
    return asset;
  }

  // Creates the marketing-email content (create -> save -> publish), pointing
  // the journey's email activity at the new content id. The copy + link are
  // already baked into EMAIL_CONTENT server-side; the images are kept from the
  // template, so there is no photo upload here.
  async function buildAndPublishEmail() {
    const content = EMAIL_CONTENT;
    let r = await fetch(CONTENT_BASE, { method: 'POST', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(content) });
    let resp = await r.text();
    if (!r.ok) throw new Error('Email content create failed: HTTP ' + r.status + ' ' + resp);
    const cseId = JSON.parse(resp).id;
    console.log('  created email content', cseId);

    r = await fetch(CONTENT_BASE + '/' + cseId, { method: 'POST', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(content) });
    resp = await r.text();
    if (!r.ok) throw new Error('Email content save failed: HTTP ' + r.status + ' ' + resp);

    r = await fetch(CONTENT_BASE + '/' + cseId + '/publish', { method: 'PATCH', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: '{}' });
    if (!r.ok) throw new Error('Email content publish failed: HTTP ' + r.status + ' ' + await r.text());
    console.log('  published email content', cseId);
    return cseId;
  }

  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', { method: 'POST', headers: { ...headers(), 'content-type': 'application/x-www-form-urlencoded' }, credentials: 'include' });
    const raw = (await r.text()).trim(); let id = raw.replace(/^"+|"+$/g, '');
    try { const d = JSON.parse(raw); if (typeof d === 'string') id = d.trim(); else if (d && typeof d === 'object') id = String(d.identifier || d.journeyId || d.id || d.value || '').trim(); } catch (e) {}
    if (!r.ok || !id.startsWith('JRN-')) throw new Error('Reserve failed: HTTP ' + r.status + ' ' + raw);
    return id;
  }

  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  const UUID_RE = /"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  function regen(txt) {
    const old = new Set(); let m; UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(txt)) !== null) old.add(m[1]);
    let t = txt;
    for (const o of old) t = t.split(o).join(newUuid());
    return t;
  }

  let ncIconUrl = null, popupBgUrl = null;
  if (FOLDER_ID) {
    console.log('Uploading photos...');
    const ncIconFile = await pickFile('NC ICON');
    ncIconUrl = (await uploadAsset(ncIconFile, 'NC ICON')).absolute_link;
    const popupBgFile = await pickFile('POP-UP BACKGROUND');
    popupBgUrl = (await uploadAsset(popupBgFile, 'POP-UP BACKGROUND')).absolute_link;
  } else {
    console.log('%cNo FOLDER_ID — keeping the template image URLs (no file pickers).', 'color:#eab308');
  }

  let emailContentId = null;
  if (EMAIL_CONTENT) {
    console.log('Creating + publishing email content...');
    emailContentId = await buildAndPublishEmail();
  }

  console.log('Reserving journey id...');
  const realId = await reserveId();
  console.log('  reserved', realId);

  let text = JSON.stringify(PAYLOAD);
  text = text.split(RESERVED_ID_TOKEN).join(realId);
  if (ncIconUrl) text = text.split(NC_ICON_TOKEN).join(ncIconUrl);
  if (popupBgUrl) text = text.split(POPUP_BG_TOKEN).join(popupBgUrl);
  if (emailContentId) text = text.split(EMAIL_CONTENT_ID_TOKEN).join(emailContentId);
  text = regen(text);
  const body = JSON.parse(text);

  console.log('Creating tournament comms journey draft', realId, ':', body.journeyName);
  const r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(body) });
  const resp = await r.text();
  if (!r.ok) { console.error('FAILED HTTP ' + r.status, resp); throw new Error('Tournament comms journey draft not created.'); }

  console.log('%cDONE.', 'color:#22c55e;font-weight:bold;font-size:14px');
  console.log('  Tournament comms journey draft: ' + realId);
  if (emailContentId) console.log('  Email content created + published: ' + emailContentId);
  else console.log('  Email activity left untouched — edit it by hand in the backoffice.');
})();
"""


def build_js(body: dict, folder_id: str = "", email_content: dict | None = None) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY_NAME@", str(body.get("journeyName", "")))
    js = js.replace("@BASE_URL@", json.dumps(BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@PAYLOAD@", json.dumps(body, ensure_ascii=False))
    js = js.replace("@FOLDER_ID@", json.dumps(folder_id or ""))
    js = js.replace("@NC_ICON_TOKEN@", json.dumps(NC_ICON_TOKEN))
    js = js.replace("@POPUP_BG_TOKEN@", json.dumps(POPUP_BG_TOKEN))
    js = js.replace("@RESERVED_ID_TOKEN@", json.dumps(RESERVED_ID_TOKEN))
    js = js.replace("@EMAIL_CONTENT@", json.dumps(email_content, ensure_ascii=False))
    js = js.replace("@EMAIL_CONTENT_ID_TOKEN@", json.dumps(EMAIL_CONTENT_ID_TOKEN))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="Comms send date YYYY-MM-DD (Chile); window is always 12:00->19:00 that day")
    p.add_argument("--spec", required=True, help="Path to the pasted spec blob, or '-' to read it from stdin")
    p.add_argument("--tournament-id", default="", help="Smartico tournament id for the deeplink (default: keep the template's)")
    p.add_argument("--journey-name", default="", help="Override the journey name (default: reuse template name, minus 'Copy of ')")
    p.add_argument("--folder-id", default="", help="PMCL media-library folder UUID. When set, the script uploads the NC icon + Pop-up background; when blank the template's existing images are kept.")
    p.add_argument("--name", default="tournament_pmcl", help="Output file basename (default: tournament_pmcl)")
    p.add_argument("--dry-run", action="store_true", help="Write prepared payload to out/ instead of a console script")
    args = p.parse_args()

    spec_text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
    spec = parse_spec(spec_text)
    for w in spec.warnings:
        print(f"  WARN  {w}", file=sys.stderr)
    if not spec.nc.title_en or not spec.popup.title_en or not spec.sms.text_en:
        print("\nspec is missing Notification/Pop-up/Sms copy — nothing written.", file=sys.stderr)
        return 1

    upload_photos = bool(args.folder_id.strip())
    body, report, start_local, stop_local, email_content = prepare_comms(
        date_str=args.date,
        journey_name=args.journey_name,
        tournament_id=args.tournament_id,
        nc=nc_dict_from_spec(spec.nc),
        popup=popup_dict_from_spec(spec.popup),
        sms=sms_dict_from_spec(spec.sms),
        upload_photos=upload_photos,
        tournament_start_date=spec.tournament_start_date,
        tournament_end_date=spec.tournament_end_date,
        email=email_dict_from_spec(spec),
    )

    print("Applied:")
    for line in report:
        print("  " + line)

    print("Verification:")
    all_ok = True
    for ok, msg in verify(body, args.tournament_id, upload_photos):
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
        all_ok = all_ok and ok
    if not all_ok:
        print("\nVERIFICATION FAILED — not writing output.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = Path("out")
        out.mkdir(exist_ok=True)
        path = out / f"{args.name}_journey.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — journey payload written: {path}")
        if email_content is not None:
            epath = out / f"{args.name}_email.json"
            epath.write_text(json.dumps(email_content, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Dry run — email content written: {epath}")
        return 0

    js = build_js(body, folder_id=args.folder_id.strip(), email_content=email_content)
    out = Path("console_scripts")
    out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in PMCL backoffice tab.")
    if upload_photos:
        print("Two file pickers will pop up in turn — NC icon first, then the Pop-up background.")
    else:
        print("No folder id given — the template's existing images are kept (no file pickers).")
    if email_content is not None:
        print("Email content will be created + published from the spec, and the journey's email activity repointed to it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
