#!/usr/bin/env python3
"""
Build the "Game of the Week" communications Journey Builder draft:
Notification (NC) + Pop-up (Cat-fish) + SMS, all wired to the promo-page
link produced by gow_campaign.py's run (so every channel's link/deeplink is
the same `/promo/offers/promoPage/<id>` the player actually lands on,
instead of a hand-typed vanity URL that drifts from campaign to campaign).

Email is intentionally left untouched — fill it in by hand in the backoffice
afterwards (per the spec: NC + Pop-up + SMS are scripted, email is manual).

This wraps templates/casino/gow_comms.json (a captured comms journey draft,
see REA_BACKOFFICE_AND_JOURNEYS.md for how its variables/links/photo slots
were mapped) and:
  * sets the journey's dates + name for this run,
  * rewrites the Notification (template 1935) and Pop-up (template 20678)
    text + links for both languages,
  * rewrites the SMS body for both languages, with the "JugaBet | " prefix
    the spec requires,
  * leaves two placeholder tokens for the photos (NC icon, Pop-up
    background) that the console script fills in at paste time after
    uploading whichever photo you pick for each slot via the media-library
    upload API (same one the backoffice's own picker uses) — nothing is
    embedded in the script itself.

The entry window (when the Notification/Pop-up/SMS go out) is fixed to the
same day as --date, 12:00 -> 19:00 Chile time — separate from (and shorter
than) the GOW free-spin journey's own activation window.

Usage:
  python comms_campaign.py --date 2026-07-01 --promo-page-id <uuid> \
      --spec spec.txt

  # or pipe the pasted spreadsheet block straight in:
  pbpaste | python comms_campaign.py --date 2026-07-01 --promo-page-id <uuid> --spec -

Then paste console_scripts/<name>_console.js into the DevTools console on a
logged-in backoffice tab. Two file pickers will pop up in turn — pick the NC
icon first, then the Pop-up background. Use --dry-run to write the prepared
payload to out/ without generating a script.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from create_journeys import (
    BRAND,
    LOCAL_TZ,
    clear_stale_campaign_connector_ids,
    set_notification_metadata_journey_name,
    strip_duplicate_lineage,
    strip_promotion_display_ids,
)
from casino_journey import DEFAULT_BASE_URL, chile_same_day_window, set_dates, utc_dotnet
from spec_parser import ChannelCopy, EmailCopy, SmsCopy, parse_spec
from email_content import (
    EMAIL_CONTENT_ID_TOKEN,
    EMAIL_HERO_TOKEN,
    PROMO_PAGE_ID_TOKEN as EMAIL_PROMO_TOKEN,
    email_name,
    prepare_email_content,
)

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "casino" / "gow_comms.json"

# The media-library folder the backoffice's own photo picker uploads into
# (see REA_BACKOFFICE_AND_JOURNEYS.md for how this was captured).
DEFAULT_FOLDER_ID = "c5c7c614-5169-4346-b90b-8225836a1c63"
# The public site domain SMS links resolve to (the {{BrandDomain}} dwh
# variable in the SMS template, flattened here since SMS text is static).
DEFAULT_PUBLIC_DOMAIN = "win.jugabet.cl"

# Paste-time placeholders, swapped for the real upload's absolute_link once
# the console script has uploaded the chosen photo for that slot.
NC_ICON_TOKEN = "@@NC_ICON_URL@@"
POPUP_BG_TOKEN = "@@POPUP_BG_URL@@"
RESERVED_ID_TOKEN = "DRY-RUN-COMMS"

SMS_PREFIX = "JugaBet | "

# The SMS promo link now uses the {{BrandDomain}} dwh variable for the host
# and the /services/promo/... path (no utm tags), and the BrandDomain variable
# is declared ("ticked") on the activity. Captured from the updcoms HAR — the
# leading // after the host is reproduced exactly as the marketing team saved
# it. BrandDomain resolves to the public site host at send time.
SMS_BRAND_VAR = {
    "name": "BrandDomain",
    "activityId": "",
    "dataSource": "dwh_source",
    "isRequired": True,
    "defaultValue": "",
}


def sms_brand_link(promo_page_id: str) -> str:
    return "https://{{BrandDomain}}//services/promo/offers/promoPage/" + promo_page_id

# The comms entry window is always same-day 12:00 -> 19:00 Chile time,
# independent of the GOW journey's own (possibly multi-day) activation
# window — this is the channel send window, not the offer's validity.
COMMS_START_HOUR = 12
COMMS_END_HOUR = 19


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
    """Email content inputs, or None when the spec doesn't drive the email
    (Email row not ticked TRUE, or subject/pre-header missing) — in which case
    the journey's email activity is left untouched."""
    email = spec.email
    if not (email.enabled and email.subject_es and email.preheader_es):
        return None
    return {
        "subject_es": email.subject_es,
        "preheader_es": email.preheader_es,
        "game_name": spec.game_name,
        "provider_name": spec.provider_name,
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
    it in (the same way RESERVED_ID_TOKEN is handled for the journey id).
    """
    init = activity["initializationData"]
    settings = init["emailSettings"]
    settings["template"] = {"id": EMAIL_CONTENT_ID_TOKEN}
    settings["emailSource"] = "Template"
    init["displayData"] = [f"{EMAIL_CONTENT_ID_TOKEN} {content_name}"]


def mirror_into_raw_journey_data(body: dict, activity: dict) -> bool:
    """Sync an activity's editor-side copy from the compiled one we just edited.

    Every activity is stored twice: once compiled in body["activities"] (the
    runtime form) and once in body["rawJourneyData"].activitiesConfiguration
    [activityId] (the editor's working copy). The Journey Builder UI renders
    the activity from the editor copy, so if only the compiled copy is updated
    the created draft still shows the old template text in the editor. The two
    are separate objects, so the edit has to be applied to both.

    The editor copy keeps initializationData's fields under ["data"] but holds
    "displayData" one level up (at the config level, not inside ["data"]), so
    split it back out to match the captured structure exactly.
    """
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


def promo_link_relative(promo_page_id: str) -> str:
    return f"/promo/offers/promoPage/{promo_page_id}?%$utm_tags%"


def promo_link_absolute(promo_page_id: str, domain: str) -> str:
    return f"https://{domain}/promo/offers/promoPage/{promo_page_id}?%$utm_tags%"


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
    icon_token: str,
) -> None:
    init = activity["initializationData"]
    variables = init["objectForSend"]["variables"]
    set_var(variables, "title-en", title_en)
    set_var(variables, "title-es", title_es)
    set_var(variables, "des-en", desc_en)
    set_var(variables, "des-es", desc_es)
    set_var(variables, "caption-en", caption_en)
    set_var(variables, "caption-es", caption_es)
    set_var(variables, "link-en", link)
    set_var(variables, "link-es", link)
    set_var(variables, "deeplink", deeplink)
    set_var(variables, "icon", icon_token)

    tabs = init["singleChannel"]["localizedLanguagesTab"]
    tabs["en"]["title-en"] = title_en
    tabs["en"]["des-en"] = desc_en
    tabs["en"]["caption-en"] = caption_en
    tabs["en"]["link-en"] = link
    tabs["es"]["title-es"] = title_es
    tabs["es"]["des-es"] = desc_es
    tabs["es"]["caption-es"] = caption_es
    tabs["es"]["link-es"] = link
    tabs["common"]["icon"] = icon_token
    tabs["common"]["deeplink"] = deeplink


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
    bg_token: str,
) -> None:
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
    set_var(variables, "background_image_src", bg_token)

    tabs = init["singleChannel"]["localizedLanguagesTab"]
    tabs["en"]["title_en"] = title_en
    tabs["en"]["description_en"] = desc_en
    tabs["en"]["caption_en"] = caption_en
    tabs["es"]["title_es"] = title_es
    tabs["es"]["description_es"] = desc_es
    tabs["es"]["caption_es"] = caption_es
    tabs["common"]["link"] = link
    tabs["common"]["deeplink"] = deeplink
    tabs["common"]["background_image_src"] = bg_token


def sms_text(body_text: str) -> str:
    body_text = (body_text or "").strip()
    if not body_text.lower().startswith("jugabet |"):
        body_text = SMS_PREFIX + body_text
    return body_text


def update_sms(
    activity: dict,
    *,
    text_en: str,
    text_es: str,
    promo_page_id: str,
    public_domain: str,
) -> None:
    body_es = sms_text(text_es)
    body_en = sms_text(text_en)
    brand_link = sms_brand_link(promo_page_id)

    init = activity["initializationData"]
    raw = init["rawValues"]
    raw["languageCode"] = "es"
    raw["variables"] = []
    raw["messageText"] = f"{body_es}\n{brand_link}"
    # Both an "es" and an "en" entry, each declaring the BrandDomain variable
    # so the editor's per-language tabs show it ticked and resolve {{BrandDomain}}.
    raw["localizedMessageTexts"] = {
        "es": {"variables": [dict(SMS_BRAND_VAR)], "messageText": f"{body_es}\n{brand_link}", "languageCode": "es"},
        "en": {"variables": [dict(SMS_BRAND_VAR)], "messageText": f"{body_en}\n{brand_link}", "languageCode": "en"},
    }

    flattened_es = f"{body_es} {brand_link}"
    flattened_en = f"{body_en} {brand_link}"
    settings = init["smsSettings"]
    settings["languageCode"] = "es"
    settings["variables"] = [dict(SMS_BRAND_VAR)]
    settings["messageText"] = flattened_es
    settings["localizedMessageTexts"] = [
        {"variables": [dict(SMS_BRAND_VAR)], "messageText": flattened_es, "languageCode": "es"},
        {"variables": [dict(SMS_BRAND_VAR)], "messageText": flattened_en, "languageCode": "en"},
    ]
    init["displayData"] = [flattened_es]
    init["listOfUsedVariables"] = ["BrandDomain"]


def set_comms_name(body: dict, start_local: datetime, name_override: str = "") -> str:
    if name_override.strip():
        new_name = name_override.strip()
    else:
        name = re.sub(r"^(Copy of )+", "", body.get("journeyName", ""))
        date_label = start_local.strftime("%d.%m.%y")
        if re.search(r"\d{2}\.\d{2}\.\d{2}", name):
            new_name = re.sub(r"\d{2}\.\d{2}\.\d{2}", date_label, name, count=1)
        else:
            new_name = f"{name} | {date_label}"
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
    promo_page_id: str,
    public_domain: str,
    journey_name: str,
    nc: dict[str, str],
    popup: dict[str, str],
    sms: dict[str, str],
    email: dict[str, str] | None = None,
) -> tuple[dict, list[str], datetime, datetime, dict | None]:
    body = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8-sig"))
    report: list[str] = []

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

    link = promo_link_relative(promo_page_id)
    # The Notification/Pop-up deeplink uses the same relative promo-page path as
    # the link (e.g. /promo/offers/promoPage/<id>?%$utm_tags%), not the absolute
    # win.jugabet.cl form.
    deeplink = link

    notif = find_notification(body, contract=1)
    update_notification(
        notif,
        title_en=nc["title_en"], title_es=nc["title_es"],
        desc_en=nc["desc_en"], desc_es=nc["desc_es"],
        caption_en=nc["caption_en"], caption_es=nc["caption_es"],
        link=link, deeplink=deeplink, icon_token=NC_ICON_TOKEN,
    )
    mirror_into_raw_journey_data(body, notif)
    report.append("Notification (template 1935): title/description/caption/link set, icon pending photo upload")

    popup_act = find_notification(body, contract=5)
    update_popup(
        popup_act,
        title_en=popup["title_en"], title_es=popup["title_es"],
        desc_en=popup["desc_en"], desc_es=popup["desc_es"],
        caption_en=popup["caption_en"], caption_es=popup["caption_es"],
        link=link, deeplink=deeplink, bg_token=POPUP_BG_TOKEN,
    )
    mirror_into_raw_journey_data(body, popup_act)
    report.append("Pop-up (template 20678): title/description/caption/link set, background pending photo upload")

    sms_act = find_sms(body)
    update_sms(
        sms_act,
        text_en=sms["text_en"], text_es=sms["text_es"],
        promo_page_id=promo_page_id, public_domain=public_domain,
    )
    mirror_into_raw_journey_data(body, sms_act)
    report.append("SMS: body + promo-page link set for EN/ES")

    email_content = None
    if email:
        content_name = email_name(date_str)
        email_content = prepare_email_content(
            date_str=date_str,
            game_name=email["game_name"], provider_name=email["provider_name"],
            subject_es=email["subject_es"], preheader_es=email["preheader_es"],
            promo_page_id=promo_page_id,
        )
        email_act = find_email(body)
        update_email_activity(email_act, content_name)
        mirror_into_raw_journey_data(body, email_act)
        report.append(
            f"Email: content {content_name!r} prepared (subject/pre-header/heading/promo "
            "set, hero pending photo upload); journey email activity repointed to new content"
        )
    else:
        report.append("Email left untouched (edit it by hand in the backoffice)")

    body["reservedJourneyId"] = RESERVED_ID_TOKEN
    report.append(f"reservedJourneyId = {RESERVED_ID_TOKEN}")
    return body, report, start_local, stop_local, email_content


def verify(body: dict, promo_page_id: str) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    serialized = json.dumps(body, ensure_ascii=False)

    checks.append((bool(body.get("journeyName")), f"journeyName is {body.get('journeyName')!r}"))
    checks.append((body.get("reservedJourneyId") == RESERVED_ID_TOKEN, f"reservedJourneyId is {body.get('reservedJourneyId')!r}"))

    link = promo_link_relative(promo_page_id)
    checks.append((link in serialized, f"promo-page link {link!r} present"))

    # The editor-side copy (rawJourneyData) must carry the edits too, or the
    # created draft shows the old template copy in the Journey Builder UI.
    raw = body.get("rawJourneyData") or {}
    raw_serialized = json.dumps(raw, ensure_ascii=False)
    checks.append((link in raw_serialized, f"promo-page link present in editor copy (rawJourneyData)"))
    checks.append((_editor_copies_in_sync(body), "editor copy (rawJourneyData) matches the edited activities"))

    checks.append((NC_ICON_TOKEN in serialized, "NC icon placeholder present (filled at paste time)"))
    checks.append((POPUP_BG_TOKEN in serialized, "Pop-up background placeholder present (filled at paste time)"))
    checks.append(("JugaBet |" in serialized, "SMS text carries the required 'JugaBet |' prefix"))
    checks.append((sms_brand_link(promo_page_id) in serialized, "SMS uses the {{BrandDomain}}//services promo link"))
    sms_act = next((a for a in body.get("activities", []) if a.get("activityName") == "dextra_sms"), None)
    if sms_act is not None:
        luv = (sms_act.get("initializationData") or {}).get("listOfUsedVariables") or []
        checks.append(("BrandDomain" in luv, "SMS declares the BrandDomain variable (ticked)"))
    checks.append(("duplicatedFromId" not in body, "no stale duplicatedFromId"))
    checks.append(("duplicatedFromVersion" not in body, "no stale duplicatedFromVersion"))

    promo_display_ids = [d["promotionDisplayId"] for d in _walk_dicts(body) if "promotionDisplayId" in d]
    checks.append((not promo_display_ids, "no stale promotionDisplayId in payload" if not promo_display_ids else f"stale promotionDisplayId(s): {promo_display_ids}"))

    # When the email is driven by the spec, the email activity must point at
    # the to-be-created content (token), not the stale captured CSE id.
    email_act = next((a for a in body.get("activities", []) if a.get("activityName") == "dextra_email"), None)
    if email_act is not None:
        tmpl_id = ((email_act.get("initializationData") or {}).get("emailSettings") or {}).get("template", {}).get("id")
        if tmpl_id == EMAIL_CONTENT_ID_TOKEN:
            checks.append((EMAIL_CONTENT_ID_TOKEN in raw_serialized, "email activity repoint mirrored into editor copy"))
    return checks


def _editor_copies_in_sync(body: dict) -> bool:
    """True if every edited activity's editor copy matches its compiled copy.

    Guards the rawJourneyData mirroring: the data under
    rawJourneyData.activitiesConfiguration[id] must equal the activity's
    initializationData (with displayData split back out to the config level).
    """
    ac = (body.get("rawJourneyData") or {}).get("activitiesConfiguration") or {}
    for a in body.get("activities", []):
        name = a.get("activityName")
        init = a.get("initializationData") or {}
        if name == "notification_center" and init.get("contract") in (1, 5):
            pass
        elif name == "dextra_sms":
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


JS_TEMPLATE = r"""// GOW Communications console script — generated @GENERATED_AT@
// Journey: @JOURNEY_NAME@
//
// Paste into the DevTools console on a logged-in backoffice tab. It will:
//   1. capture the auth token from the page's own requests,
//   2. pop up a file picker for the NC icon, then another for the Pop-up
//      background — each photo is uploaded to the media library and its
//      resulting URL written into the right slot,
//   3. reserve a journey id and create the comms journey draft
//      (Notification + Pop-up + SMS — email is untouched, fill it by hand).
// Heavy logging throughout; it stops at the first error.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const PAYLOAD = @PAYLOAD@;
  const FOLDER_ID = @FOLDER_ID@;
  const NC_ICON_TOKEN = @NC_ICON_TOKEN@;
  const POPUP_BG_TOKEN = @POPUP_BG_TOKEN@;
  const RESERVED_ID_TOKEN = @RESERVED_ID_TOKEN@;
  const EMAIL_CONTENT = @EMAIL_CONTENT@;            // null when email is left untouched
  const EMAIL_HERO_TOKEN = @EMAIL_HERO_TOKEN@;
  const EMAIL_PROMO_TOKEN = @EMAIL_PROMO_TOKEN@;
  const EMAIL_CONTENT_ID_TOKEN = @EMAIL_CONTENT_ID_TOKEN@;
  const EMAIL_PROMO_PAGE_ID = @EMAIL_PROMO_PAGE_ID@; // '' for comms (link already baked)

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

  // Uploads a photo into the media library (the same folder + endpoint the
  // backoffice's own photo picker uses) and returns its public URL.
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

  // Creates the marketing-email content (create -> save -> publish), wiring in
  // the uploaded hero photo and the promo-page link, and returns its CSE id so
  // the journey's email activity can be pointed at it.
  async function buildAndPublishEmail(promoPageId) {
    const heroFile = await pickFile('EMAIL HERO');
    const heroAsset = await uploadAsset(heroFile, 'EMAIL HERO');
    let cText = JSON.stringify(EMAIL_CONTENT);
    // The email body references images as https://{{cdn_hostname}}<relative>.
    cText = cText.split(EMAIL_HERO_TOKEN).join('https://{{cdn_hostname}}' + heroAsset.relative_link);
    if (promoPageId) cText = cText.split(EMAIL_PROMO_TOKEN).join(promoPageId);
    const content = JSON.parse(cText);

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

  console.log('Uploading photos...');
  const ncIconFile = await pickFile('NC ICON');
  const ncIconUrl = (await uploadAsset(ncIconFile, 'NC ICON')).absolute_link;
  const popupBgFile = await pickFile('POP-UP BACKGROUND');
  const popupBgUrl = (await uploadAsset(popupBgFile, 'POP-UP BACKGROUND')).absolute_link;

  let emailContentId = null;
  if (EMAIL_CONTENT) {
    console.log('Creating + publishing email content...');
    emailContentId = await buildAndPublishEmail(EMAIL_PROMO_PAGE_ID);
  }

  console.log('Reserving journey id...');
  const realId = await reserveId();
  console.log('  reserved', realId);

  let text = JSON.stringify(PAYLOAD);
  text = text.split(RESERVED_ID_TOKEN).join(realId);
  text = text.split(NC_ICON_TOKEN).join(ncIconUrl);
  text = text.split(POPUP_BG_TOKEN).join(popupBgUrl);
  if (emailContentId) text = text.split(EMAIL_CONTENT_ID_TOKEN).join(emailContentId);
  text = regen(text);
  const body = JSON.parse(text);

  console.log('Creating comms journey draft', realId, ':', body.journeyName);
  const r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: { ...headers(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(body) });
  const resp = await r.text();
  if (!r.ok) { console.error('FAILED HTTP ' + r.status, resp); throw new Error('Comms journey draft not created.'); }

  console.log('%cDONE.', 'color:#22c55e;font-weight:bold;font-size:14px');
  console.log('  Comms journey draft: ' + realId);
  if (emailContentId) console.log('  Email content created + published: ' + emailContentId);
  else console.log('  Email activity left untouched — edit it by hand in the backoffice.');
})();
"""


def build_js(body: dict, email_content: dict | None = None) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY_NAME@", str(body.get("journeyName", "")))
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@PAYLOAD@", json.dumps(body, ensure_ascii=False))
    js = js.replace("@FOLDER_ID@", json.dumps(DEFAULT_FOLDER_ID))
    js = js.replace("@NC_ICON_TOKEN@", json.dumps(NC_ICON_TOKEN))
    js = js.replace("@POPUP_BG_TOKEN@", json.dumps(POPUP_BG_TOKEN))
    js = js.replace("@RESERVED_ID_TOKEN@", json.dumps(RESERVED_ID_TOKEN))
    js = js.replace("@EMAIL_CONTENT@", json.dumps(email_content, ensure_ascii=False))
    js = js.replace("@EMAIL_HERO_TOKEN@", json.dumps(EMAIL_HERO_TOKEN))
    js = js.replace("@EMAIL_PROMO_TOKEN@", json.dumps(EMAIL_PROMO_TOKEN))
    js = js.replace("@EMAIL_CONTENT_ID_TOKEN@", json.dumps(EMAIL_CONTENT_ID_TOKEN))
    # Comms bakes the promo link directly, so the script need not re-fill it.
    js = js.replace("@EMAIL_PROMO_PAGE_ID@", json.dumps(""))
    return js


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="Comms send date YYYY-MM-DD (Chile); window is always 12:00->19:00 that day")
    p.add_argument("--promo-page-id", required=True, help="UUID of the GOW promo page draft (from gow_campaign.py's DONE output)")
    p.add_argument("--public-domain", default=DEFAULT_PUBLIC_DOMAIN, help=f"Public site domain for the SMS link (default {DEFAULT_PUBLIC_DOMAIN})")
    p.add_argument("--journey-name", default="", help="Override the journey name (default: reuse template name with the date refreshed)")
    p.add_argument("--spec", required=True, help="Path to the pasted spec blob, or '-' to read it from stdin")

    p.add_argument("--name", default="comms_campaign", help="Output file basename (default: comms_campaign)")
    p.add_argument("--dry-run", action="store_true", help="Write prepared payload to out/ instead of a console script")
    args = p.parse_args()

    spec_text = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
    spec = parse_spec(spec_text)
    for w in spec.warnings:
        print(f"  WARN  {w}", file=sys.stderr)
    if not spec.nc.title_en or not spec.popup.title_en or not spec.sms.text_en:
        print("\nspec is missing Notification/Pop-up/Sms copy — nothing written.", file=sys.stderr)
        return 1

    body, report, start_local, stop_local, email_content = prepare_comms(
        date_str=args.date,
        promo_page_id=args.promo_page_id,
        public_domain=args.public_domain,
        journey_name=args.journey_name,
        nc=nc_dict_from_spec(spec.nc),
        popup=popup_dict_from_spec(spec.popup),
        sms=sms_dict_from_spec(spec.sms),
        email=email_dict_from_spec(spec),
    )

    print("Applied:")
    for line in report:
        print("  " + line)

    print("Verification:")
    all_ok = True
    for ok, msg in verify(body, args.promo_page_id):
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

    js = build_js(body, email_content)
    out = Path("console_scripts")
    out.mkdir(exist_ok=True)
    path = out / f"{args.name}_console.js"
    path.write_text(js, encoding="utf-8")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    if email_content is not None:
        print("Three file pickers will pop up in turn — NC icon, Pop-up background, then Email hero.")
    else:
        print("Two file pickers will pop up in turn — NC icon first, then the Pop-up background.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
