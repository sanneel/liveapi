#!/usr/bin/env python3
"""The tournament comms engine, shared by the PMCL and JBCL generators.

Both brands announce a tournament the same way — Notification Center + Cat-fish
pop-up + SMS + a marketing email, one journey, gated by two `wait_date`
activities on the tournament window — but from *different* captures: different
backoffice host, different notification node names, different email template,
different SMS brand prefix. Everything that differs is a `Brand` below;
everything that is a rule lives here once, so the two cannot drift.

Rules this engine enforces (each one was a real broken draft):

  * **Any link, no Smartico id.** The operator pastes whatever URL the promo
    lives at. Its *path* is what ships: the notification and pop-up get
    ``/xxx/yy/gg?%$utm_tags%`` and the SMS gets
    ``https://{{BrandDomain}}/xxx/yy/gg``. The captured
    ``#_smartico_dp=dp:gf_tournaments&id=<n>`` deeplink is removed outright —
    it only ever addressed one tournament on one product, and a run that kept
    it silently pointed every channel at the captured tournament.
  * **The sheet owns the tournament window.** ``Start date`` / ``End date``
    drive the two wait_date gates, the notification revoke period (a
    notification for a tournament that ended is still sitting in the centre
    otherwise) and the journey name. There is no operator field to disagree
    with them.
  * **The journey starts on the send date at 12:00 Chile** and stops at 19:00
    the same day — never "immediately after publish", which fired a draft the
    moment somebody published it days early.
  * Copy is written structurally, per node and per language, in both storages
    (see `comms_engine`), and `verify()` reads it back and refuses.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from create_journeys import LOCAL_TZ, UTC, utc_api  # noqa: E402
from compose import audit_inherited_content  # noqa: E402
from spec_parser import parse_spec  # noqa: E402
import comms_engine as E  # noqa: E402

# Paste-time tokens the console script fills from the browser.
RESERVED_TOKEN = "%%RESERVED%%"
NC_ICON_TOKEN = "%%NC_ICON%%"
POPUP_BG_TOKEN = "%%POPUP_BG%%"
EMAIL_ID_TOKEN = "%%EMAIL_CONTENT_ID%%"
EMAIL_HERO_TOKEN = "%%EMAIL_HERO%%"
EMAIL_NAME_TOKEN = "%%EMAIL_NAME%%"
EMAIL_SUBJECT_TOKEN = "%%EMAIL_SUBJECT%%"
EMAIL_PREHEADER_TOKEN = "%%EMAIL_PREHEADER%%"
EMAIL_BODY_TOKEN = "EMAIL_BODY_COPY_PLACEHOLDER"

# The Smartico deeplink this engine strips. Kept as a pattern rather than a
# literal id so a *different* captured tournament is caught too.
SMARTICO_RE = re.compile(r"#?_smartico_dp=dp:[A-Za-z0-9_]+(?:&(?:amp;)?id=\d+)?")
_GAME_RE = re.compile(r"/launch/slots/iframe/([A-Za-z0-9][A-Za-z0-9._-]*)")
_SLUG_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SMS_PREFIX_RE = re.compile(r"^\s*[^|\n]{1,20}\|\s*")


class Refused(SystemExit):
    """Raised instead of emitting something wrong."""


@dataclass(frozen=True)
class Brand:
    """Everything that differs between the two captures."""
    code: str                     # "PMCL" / "JBCL"
    title: str                    # what the report and console banner say
    base_url: str                 # journey-builder API root for this backoffice
    folder_id: str                # media-library folder — hardcoded, not an input
    create_tpl: Path
    save_tpl: Path
    nc_node: str                  # singleChannel activityName, contract 1
    popup_node: str               # singleChannel activityName, contract 5
    journey_prefix: str           # "FTCL | CS" / "JBCL | CS&SP"
    sms_prefix: str               # "Fortunazo | " / "JugaBet | "
    email_create_tpl: Path
    email_save_tpl: Path
    email_name_prefix: str
    tpl_email_content_id: str     # the captured campaign's email content
    tpl_email_hero: str           # captured hero image URL in the email HTML
    tpl_email_cta: str            # the literal in the email HTML the CTA points at
    tpl_nc_icons: tuple           # captured notification icon URLs
    tpl_popup_bg: str
    tpl_reserved: str             # captured reservedJourneyId
    tpl_journey_names: tuple      # captured journeyName spellings, longest first
    tpl_links: tuple = field(default_factory=tuple)   # captured link literals to scrub
    # What the email's call-to-action opens. "game": a slot the operator names
    # (…/launch/slots/iframe/<slug>) — the JBCL capture's shape. "link": the same
    # promo the other channels open, which is how the PMCL capture reads once its
    # Smartico deeplink is removed.
    email_cta_kind: str = "game"


# ── inputs ──────────────────────────────────────────────────────────────
def link_path(link: str) -> str:
    """The path every channel links to, from whatever URL the operator pasted.

    ``https://jugabet.cl/xxx/yy/gg`` → ``/xxx/yy/gg``. A bare path is taken as
    is. Any query or fragment is dropped — the fragment is where the captured
    Smartico deeplink lived, and the query is rebuilt per channel.
    """
    v = (link or "").strip()
    if not v:
        return ""
    if "://" not in v and not v.startswith("/"):
        v = "//" + v                       # "jugabet.cl/x" parses as a host
    parts = urlsplit(v)
    path = parts.path if (parts.scheme or parts.netloc) else v.split("?")[0].split("#")[0]
    path = "/" + path.strip("/")
    if path == "/":
        raise Refused(
            f"link {link!r} has no path. Give the full promo URL "
            f"(https://<brand>/xxx/yy/gg) or the path itself (/xxx/yy/gg)."
        )
    return path


def parse_game_slug(value: str) -> str:
    """The game slug the email CTA opens, from a launch URL or a bare slug."""
    v = (value or "").strip()
    if not v:
        return ""
    m = _GAME_RE.search(v)
    if m:
        return m.group(1)
    if "/" in v or ":" in v:
        raise Refused(
            f"email game link {v!r} is not a launch URL. Expected "
            f"…/launch/slots/iframe/<game-slug> (or just the slug)."
        )
    if not _SLUG_OK.match(v):
        raise Refused(f"game slug {v!r} is not usable.")
    return v


def read_spec(brand: Brand, path: Path, link: str = ""):
    """Parse the pasted sheet and refuse anything this build cannot fill in."""
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    spec = parse_spec(text, expect_game_offer=False)
    # The operator's --link wins; the sheet's "Link" row is the fallback. A
    # pathless sheet link falls through to the missing-input refusal below
    # rather than aborting with a less useful message.
    if (link or "").strip():
        spec.link_path = link_path(link)
    else:
        try:
            spec.link_path = link_path(getattr(spec, "raw_link", ""))
        except Refused:
            spec.link_path = ""

    missing = []
    if not spec.link_path:
        missing.append(
            'no promo link — give --link (any URL, e.g. https://jugabet.cl/xxx/yy/gg)'
        )
    if not (spec.tournament_start_date and spec.tournament_end_date):
        missing.append(
            'the sheet\'s "Start date" and "End date" rows (they set the Wait/Date '
            "gates, the notification revoke period and the journey name)"
        )
    if not (spec.nc.title_es and spec.nc.desc_es and spec.nc.caption_es):
        missing.append("Notification title/description/caption")
    if not (spec.popup.title_es and spec.popup.desc_es and spec.popup.caption_es):
        missing.append("Pop-up (Cat-fish) title/description/caption")
    if not (spec.sms.text_es and spec.sms.text_en):
        missing.append("Sms text (EN and ES)")
    if missing:
        raise Refused("missing input:\n  - " + "\n  - ".join(missing))
    if spec.tournament_end_date < spec.tournament_start_date:
        raise Refused(
            f"the sheet's End date ({spec.tournament_end_date}) is before its "
            f"Start date ({spec.tournament_start_date})."
        )
    return spec


def chile_window(date_str: str) -> tuple[str, str]:
    """(startAt, stopAt) — the send day, 12:00 → 19:00 Chile, as .NET UTC."""
    day = datetime.strptime(date_str, "%Y-%m-%d")
    start = day.replace(hour=12, tzinfo=LOCAL_TZ).astimezone(UTC)
    stop = day.replace(hour=19, tzinfo=LOCAL_TZ).astimezone(UTC)
    return utc_api(start, dotnet_fraction=True), utc_api(stop, dotnet_fraction=True)


def _gate(date_str: str) -> str:
    """A wait_date gate: that date at 12:00 Chile, as the template stores it."""
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, tzinfo=LOCAL_TZ)
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def tournament_days(start_date: str, end_date: str) -> int:
    """Tournament length in days, both endpoints counted (20→26 July = 7)."""
    s = datetime.strptime(start_date, "%Y-%m-%d")
    e = datetime.strptime(end_date, "%Y-%m-%d")
    return (e - s).days + 1


def sms_body(brand: Brand, text: str) -> str:
    """The sheet's SMS copy behind this brand's required prefix."""
    body = _SMS_PREFIX_RE.sub("", (text or "").strip()).lstrip()
    return brand.sms_prefix + body


# ── prepare ─────────────────────────────────────────────────────────────
def prepare(brand: Brand, spec, *, date_str: str, journey_name: str = "",
            email_content_id: str = "", email_game: str = "",
            upload_photos: bool = True, now: datetime | None = None
            ) -> tuple[dict, list[str]]:
    now = now or datetime.now(LOCAL_TZ)
    path = spec.link_path
    nc_link = f"{path}?%$utm_tags%"                 # notification + pop-up
    sms_link = "https://{{BrandDomain}}" + path      # SMS carries the domain
    start_date, end_date = spec.tournament_start_date, spec.tournament_end_date
    days = tournament_days(start_date, end_date)
    start_at, stop_at = chile_window(date_str)
    make_email = not email_content_id.strip()

    if journey_name.strip():
        name = journey_name.strip()
    else:
        s = datetime.strptime(start_date, "%Y-%m-%d")
        e = datetime.strptime(end_date, "%Y-%m-%d")
        label = spec.event_name or path.strip("/").replace("/", " ")
        name = f"{brand.journey_prefix} | {label} {s:%d.%m}-{e:%d.%m}"

    nc_copy = {
        "title": {"en": spec.nc.title_en, "es": spec.nc.title_es},
        "description": {"en": spec.nc.desc_en, "es": spec.nc.desc_es},
        "caption": {"en": spec.nc.caption_en, "es": spec.nc.caption_es},
    }
    popup_copy = {
        "title": {"en": spec.popup.title_en, "es": spec.popup.title_es},
        "description": {"en": spec.popup.desc_en, "es": spec.popup.desc_es},
        "caption": {"en": spec.popup.caption_en, "es": spec.popup.caption_es},
    }
    sms_en = f"{sms_body(brand, spec.sms.text_en)}\n{sms_link}"
    sms_es = f"{sms_body(brand, spec.sms.text_es)}\n{sms_link}"

    def string_swaps(text: str) -> str:
        s = text
        for captured in brand.tpl_journey_names:
            s = s.replace("Copy of " + captured, name).replace(captured, name)
        s = s.replace(brand.tpl_reserved, RESERVED_TOKEN)
        # Artwork → tokens, always: the audit must never see a captured URL. The
        # console script fills them from an upload, or restores the captured one
        # when the operator opted out of the pickers.
        for icon in brand.tpl_nc_icons:
            s = s.replace(icon, NC_ICON_TOKEN)
        s = s.replace(brand.tpl_popup_bg, POPUP_BG_TOKEN)
        s = s.replace(brand.tpl_email_content_id,
                      EMAIL_ID_TOKEN if make_email else email_content_id.strip())
        return s

    create = json.loads(string_swaps(brand.create_tpl.read_text(encoding="utf-8")))
    save = json.loads(string_swaps(brand.save_tpl.read_text(encoding="utf-8")))

    written: dict[str, int] = {}
    for body in (create, save):
        body["duplicatedFromId"] = None
        body["duplicatedFromVersion"] = None
        body.pop("changeHistory", None)
        # copy — structural, never string-replaced
        written["nc"] = E.set_channel_copy(body, brand.nc_node, nc_copy)
        written["popup"] = E.set_channel_copy(body, brand.popup_node, popup_copy)
        written["sms"] = E.set_sms_text(body, sms_en, sms_es)
        # links — the captured Smartico deeplink is overwritten, not patched
        written["nc link"] = E.set_channel_link(body, brand.nc_node, nc_link)
        written["popup link"] = E.set_channel_link(body, brand.popup_node, nc_link)
        # revoke period = the tournament's length
        written["revoke"] = E.set_expire_after(body, days)
        # canvas labels (displayData) — the hidden second copy
        E.set_display_data(body, lambda a: a.get("activityName") == "dextra_sms", sms_es)
        # the two gates, in the order the templates store them (later first)
        _set_wait_dates(body, _gate(end_date), _gate(start_date))
        E.backfill_position_absolute(body)

    for what, n in written.items():
        if not n:
            raise Refused(
                f"wrote no {what} — the node was not found. The template changed "
                f"shape; this build would ship the captured campaign's {what}."
            )

    # ── schedule: this date at 12:00 Chile, never "immediately after publish" ──
    for body in (create, save):
        body["startAt"] = start_at
        body["stopAt"] = stop_at
        body["isImmediatelyAfterPublish"] = False
        body["journeyName"] = name
        iv = body.get("rawJourneyData", {}).get("infoValues")
        if isinstance(iv, dict):
            iv["startAt"] = start_at
            iv["stopAt"] = stop_at
            iv["isImmediatelyAfterPublish"] = False
            iv["journeyName"] = name

    # ── the email content, built first so its id can be wired into the journey ──
    email_create = email_save = None
    email_name = ""
    email_body_copy = ""
    game = cta = ""
    if make_email:
        if not spec.email.desc_es.strip():
            raise Refused(
                'the sheet has no "Email Description" row and no email content id '
                "was given. Either supply the email body copy or point the node at "
                "an existing CSE-* — a draft keeping the captured email is refused."
            )
        if brand.email_cta_kind == "game":
            game = parse_game_slug(email_game)
            if not game:
                raise Refused(
                    "no email link (the game the email CTA opens, "
                    "…/launch/slots/iframe/<game-slug>). The captured game must not ship."
                )
            cta = game
        else:
            cta = sms_link            # the email opens the same promo as the SMS
        email_name = (f"{brand.email_name_prefix} - {spec.event_name or name} - "
                      f"{now:%d.%m.%Y %H:%M:%S}")
        email_body_copy = "\n<br><br>\n".join(
            line.strip() for line in spec.email.desc_es.splitlines() if line.strip()
        )

        def swap_email(text: str) -> str:
            s = text
            s = s.replace(EMAIL_NAME_TOKEN, E.json_escape(email_name))
            s = s.replace(EMAIL_SUBJECT_TOKEN, E.json_escape(spec.email.subject_es))
            s = s.replace(EMAIL_PREHEADER_TOKEN, E.json_escape(spec.email.preheader_es))
            s = s.replace(EMAIL_BODY_TOKEN, E.json_escape(email_body_copy))
            s = s.replace(E.json_escape(brand.tpl_email_cta), E.json_escape(cta))
            s = s.replace(brand.tpl_email_hero, EMAIL_HERO_TOKEN)
            return s

        email_create = json.loads(swap_email(brand.email_create_tpl.read_text(encoding="utf-8")))
        email_save = json.loads(swap_email(brand.email_save_tpl.read_text(encoding="utf-8")))

    bundle = {
        "brand": brand, "create": create, "save": save,
        "email_create": email_create, "email_save": email_save,
        "make_email": make_email, "email_name": email_name,
        "email_game": game, "email_cta": cta,
        "link_path": path, "nc_link": nc_link, "sms_link": sms_link,
        "journey_name": name, "days": days,
        "start_date": start_date, "end_date": end_date,
        "email_content_id": email_content_id.strip(),
        "upload_photos": upload_photos,
        "expected": {brand.nc_node: nc_copy, brand.popup_node: popup_copy,
                     "sms": {"en": sms_en, "es": sms_es},
                     "email_body": email_body_copy},
    }
    report = [
        f"journeyName   {name!r}",
        f"link          {path}  (notification/pop-up: {nc_link})",
        f"sms link      {sms_link}",
        f"send window   {start_at} → {stop_at}  (starts on the date, 12:00 Chile)",
        f"tournament    {start_date} → {end_date}  ({days} days: gates + revoke period)",
        (f"email         creating {email_name!r} (hero uploaded, CTA → {cta})"
         if make_email else f"email content {email_content_id} (existing, wired into the journey)"),
        f"nc title es   {spec.nc.title_es[:56]!r}",
        f"popup title   {spec.popup.title_es[:56]!r}",
        f"sms es        {sms_es[:72]!r}",
        f"photos        {'uploaded at paste (icon + background)' if upload_photos else 'kept from template'}",
    ]
    for w in spec.warnings:
        report.append(f"sheet warning: {w}")
    return bundle, report


def _set_wait_dates(body: dict, late_iso: str, early_iso: str) -> None:
    """Write the two wait_date gates in both storages, keeping capture order."""
    order = [late_iso, early_iso]
    cfg = body.get("rawJourneyData", {}).get("activitiesConfiguration", {})
    seen = 0
    for a in body.get("activities", []):
        if a.get("activityName") != "wait_date":
            continue
        val = order[seen] if seen < len(order) else order[-1]
        a.setdefault("initializationData", {})["waitTo"] = val
        mirror = cfg.get(a.get("activityId"))
        if isinstance(mirror, dict) and isinstance(mirror.get("data"), dict):
            mirror["data"]["waitTo"] = val
        seen += 1


# ── verify — refuses, does not warn ─────────────────────────────────────
def verify(bundle: dict) -> list[tuple[bool, str]]:
    brand: Brand = bundle["brand"]
    create, save = bundle["create"], bundle["save"]
    path, nc_link, sms_link = bundle["link_path"], bundle["nc_link"], bundle["sms_link"]
    s_create = json.dumps(create, ensure_ascii=False)
    s_save = json.dumps(save, ensure_ascii=False)
    both = s_create + s_save

    reference = json.loads(brand.save_tpl.read_text(encoding="utf-8"))
    leaked = audit_inherited_content(save, reference)

    # every link field on both nodes carries this run's link
    wrong_links: list[str] = []
    for node in (brand.nc_node, brand.popup_node):
        for store in E.storages(save, E.comms_node(node)):
            tabs = (store.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
            for lang_tab in tabs.values():
                if not isinstance(lang_tab, dict):
                    continue
                for key, value in lang_tab.items():
                    if key in E._LINK_FIELDS and not str(value).startswith("%") and value != nc_link:
                        wrong_links.append(f"{node} {key}={value!r}")

    # copy landed, per node and per language
    expected = bundle.get("expected") or {}
    copy_mismatch: list[str] = []
    for node in (brand.nc_node, brand.popup_node):
        want = expected.get(node) or {}
        for store in E.storages(save, E.comms_node(node)):
            tabs = (store.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
            for lang_tab in tabs.values():
                if not isinstance(lang_tab, dict):
                    continue
                for key, value in lang_tab.items():
                    m = E._LANG_FIELD_RE.match(key)
                    if not m or (isinstance(value, str) and value.startswith("%")):
                        continue
                    base = "description" if m.group(1) in ("des", "description") else m.group(1)
                    target = (want.get(base) or {}).get(m.group(2))
                    if target and value != target:
                        copy_mismatch.append(f"{node} {key}")
    sms_want = expected.get("sms") or {}
    for store in E.storages(save, lambda a: a.get("activityName") == "dextra_sms"):
        for entry in ((store.get("smsSettings") or {}).get("localizedMessageTexts") or []):
            want = sms_want.get(entry.get("languageCode"))
            if want and entry.get("messageText") != want:
                copy_mismatch.append(f"sms[{entry.get('languageCode')}]")

    dangling = E.dangling_edges(save)
    unknown = E.unknown_canvas_nodes(save)
    no_pos = E.activity_nodes_without_position(save)
    broken = E.canvas_edges_to_missing_node(save)
    iv = save.get("rawJourneyData", {}).get("infoValues", {})
    revoke = sorted(set(re.findall(r'"expire_after"\s*:\s*"([^"]*)"', both)))
    want_revoke = f'{bundle["days"]}.00:00:00.000'
    gates = sorted({a["initializationData"]["waitTo"]
                    for a in save.get("activities", [])
                    if a.get("activityName") == "wait_date"})
    want_gates = sorted({_gate(bundle["start_date"]), _gate(bundle["end_date"])})

    # ── email content, when this run builds it ──
    email_checks: list[tuple[bool, str]] = []
    if bundle.get("make_email"):
        ec, es = bundle["email_create"], bundle["email_save"]
        s_email = json.dumps(ec, ensure_ascii=False) + json.dumps(es, ensure_ascii=False)
        cta = bundle.get("email_cta", "")
        html = ""
        for tr in (es.get("translations") or {}).values():
            src = ((tr.get("composition") or {}).get("body") or {}).get("source")
            if isinstance(src, str):
                html += src
        want_body = expected.get("email_body") or ""
        email_checks = [
            (EMAIL_ID_TOKEN in s_create and EMAIL_ID_TOKEN in s_save,
             "journey email node is a placeholder (filled from the created content)"),
            (EMAIL_HERO_TOKEN in s_email and brand.tpl_email_hero not in s_email,
             "email hero is a placeholder (uploaded at paste)"),
            (E.json_escape(brand.tpl_email_cta) not in s_email,
             f"email no longer opens the captured target ({brand.tpl_email_cta[:48]})"),
            (bool(cta) and E.json_escape(cta) in s_email,
             f"email CTA opens this run's target ({cta})"),
            (bool(want_body) and want_body in html,
             "email body carries the sheet's copy"),
            (EMAIL_BODY_TOKEN not in s_email, "email body placeholder filled"),
            (EMAIL_NAME_TOKEN not in s_email and EMAIL_SUBJECT_TOKEN not in s_email
             and EMAIL_PREHEADER_TOKEN not in s_email,
             "email name / subject / pre-header filled"),
        ]

    return [
        (not wrong_links, f"every notification/pop-up link is {nc_link}"
         + (f" (WRONG: {wrong_links[:2]})" if wrong_links else "")),
        (sms_link in both, f"the SMS carries {sms_link}"),
        (not SMARTICO_RE.search(both),
         "no Smartico deeplink survives (the captured tournament id is gone)"),
        (all(lit not in both for lit in brand.tpl_links),
         "captured links gone" + (f" (LEFT: {[l for l in brand.tpl_links if l in both][:1]})"
                                  if any(l in both for l in brand.tpl_links) else "")),
        (RESERVED_TOKEN in s_create and brand.tpl_reserved not in both,
         "reservedJourneyId is a placeholder, captured id gone"),
        (brand.tpl_email_content_id not in both,
         f"email node no longer points at the captured content ({brand.tpl_email_content_id})"),
        (all(n not in both for n in brand.tpl_journey_names),
         'journey renamed (no "Copy of", no captured name)'),
        (create.get("duplicatedFromId") is None, "lineage stripped"),
        (not copy_mismatch, "every channel field matches the sheet"
         + (f" (WRONG: {copy_mismatch[:3]})" if copy_mismatch else "")),
        (revoke == [want_revoke],
         f"notification revoke period = the tournament's {bundle['days']} days ({revoke})"),
        (gates == want_gates, f"both Wait/Date gates sit on the tournament window ({gates})"),
        (not dangling, "every nextActivityId resolves"
         + (f" (DANGLING: {dangling[:2]})" if dangling else "")),
        (not broken, "every canvas edge connects two real nodes"
         + (f" (BROKEN: {broken[:2]})" if broken else "")),
        (not unknown, "every canvas node is an activity or known scaffolding"
         + (f" (UNKNOWN: {unknown[:2]})" if unknown else "")),
        (not no_pos, "every activity node has position + positionAbsolute"
         + (f" (MISSING: {no_pos[:2]})" if no_pos else "")),
        (save.get("isImmediatelyAfterPublish") is False
         and iv.get("isImmediatelyAfterPublish") is False,
         "the journey starts on its date, not on publish (both storages)"),
        (bool(iv.get("startAt")) and save.get("startAt", "").startswith(iv["startAt"][:19]),
         f"both storages agree on startAt ({iv.get('startAt')})"),
        (bool(iv.get("stopAt")) and save.get("stopAt", "").startswith(iv["stopAt"][:19]),
         f"both storages agree on stopAt ({iv.get('stopAt')})"),
        (iv.get("journeyName") == save.get("journeyName"),
         "both storages agree on journeyName"),
        (any(a.get("activityName") == "end_of_journey" for a in save.get("activities", [])),
         "a terminal activity exists"),
        (not leaked, "no content still shared with the capture"
         + (f" (LEAK: {leaked[:2]})" if leaked else "")),
    ] + email_checks


# ── emit ────────────────────────────────────────────────────────────────
JS_TEMPLATE = r"""// @BRAND@ Tournament comms — @JOURNEY@ — generated @GENERATED_AT@
// ONE journey: notification + pop-up + SMS + email, gated by the tournament
// window. Creates the draft (POST) and then SAVES it (PUT) — the save is what
// finalises the canvas, and skipping it left nodes unconnected. Draft only.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND_JSON@;
  const FOLDER_ID = @FOLDER_ID@;
  const CAPTURED_NC_ICON = @CAPTURED_NC_ICON@;   // restored when no folder is set
  const CAPTURED_POPUP_BG = @CAPTURED_POPUP_BG@;
  const MAKE_EMAIL = @MAKE_EMAIL@;               // build + publish email content, then wire it
  const EMAIL_CREATE = @EMAIL_CREATE@;
  const EMAIL_SAVE = @EMAIL_SAVE@;
  const CREATE = @CREATE@;
  const SAVE = @SAVE@;
  const CRM_BASE = BASE.replace(/\/journey-builder\/v0$/, '');
  const CS_BASE = CRM_BASE + '/content-studio/v0/eb-backoffice/email/contents';

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
      input.type = 'file'; input.accept = 'image/*';
      Object.assign(input.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999, background: '#fff', padding: '8px', border: '3px solid #22c55e', borderRadius: '6px' });
      document.body.appendChild(input);
      console.log('%cSelect the image for ' + label + ' (top-left).', 'color:#eab308;font-weight:bold');
      input.addEventListener('change', () => { const f = input.files && input.files[0]; input.remove(); if (!f) { reject(new Error('No file for ' + label)); return; } resolve(f); });
    });
  }
  function imageDims(file) { return new Promise((resolve, reject) => { const url = URL.createObjectURL(file); const img = new Image(); img.onload = () => { URL.revokeObjectURL(url); resolve({ width: img.naturalWidth, height: img.naturalHeight }); }; img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('bad image ' + file.name)); }; img.src = url; }); }

  const auth = await obtainAuth();
  const H = (ct) => { const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND }; if (ct) h['content-type'] = ct; return h; };

  async function upload(file, label) {
    const dims = await imageDims(file);
    const base = (file.name || 'image').replace(/\.[^./]+$/, '');
    const url = CRM_BASE + '/media-library/v0/folder/' + FOLDER_ID + '/upload/' + encodeURIComponent(base) + '.png?height=' + dims.height + '&width=' + dims.width;
    const fd = new FormData(); fd.append('file', file, file.name);
    const r = await fetch(url, { method: 'PUT', headers: H(), credentials: 'include', body: fd });
    const t = await r.text(); if (!r.ok) throw new Error(label + ' upload HTTP ' + r.status + ' ' + t);
    const asset = JSON.parse(t);
    const tfd = new FormData(); tfd.append('file', file, file.name);
    await fetch(CRM_BASE + '/media-library/v0/asset/thumb/' + asset.id + '.png', { method: 'PUT', headers: H(), credentials: 'include', body: tfd }).catch(() => {});
    console.log('    ' + label + ' -> ' + asset.absolute_link);
    return asset.absolute_link;
  }
  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', { method: 'POST', headers: H('application/json'), credentials: 'include', body: '' });
    const t = await r.text(); if (!r.ok) throw new Error('reserve id HTTP ' + r.status + ' ' + t);
    const id = JSON.parse(t).journeyId; if (!id) throw new Error('no journeyId: ' + t); return id;
  }

  // One id map, from BOTH bodies, applied to both — so create and save describe
  // the same journey and a uuid seen only in the save body is regenerated too.
  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  const UUID_RE = /"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  function idMap(txt) { const map = new Map(); let m; UUID_RE.lastIndex = 0; while ((m = UUID_RE.exec(txt)) !== null) if (!map.has(m[1])) map.set(m[1], newUuid()); return map; }
  function applyMap(txt, map) { let t = txt; for (const [o, n] of map) t = t.split(o).join(n); return t; }

  console.log('%c@BRAND@ Tournament comms', 'color:#3b82f6;font-weight:bold;font-size:14px');
  try {
    // 1. artwork
    let iconUrl = CAPTURED_NC_ICON, bgUrl = CAPTURED_POPUP_BG;   // defaults: keep template art
    if (FOLDER_ID) {
      iconUrl = await upload(await pickFile('the NOTIFICATION ICON (200x200)'), 'notification icon');
      bgUrl = await upload(await pickFile('the POP-UP BACKGROUND'), 'pop-up background');
    } else {
      console.log('%cNo photo upload — keeping the template artwork (no pickers).', 'color:#eab308');
    }

    // 2. email content FIRST — the journey needs its id
    let emailContentId = null;
    if (MAKE_EMAIL) {
      if (!FOLDER_ID) throw new Error('the email hero needs an upload — rerun without "keep the template images".');
      const heroUrl = await upload(await pickFile('the EMAIL HERO IMAGE'), 'email hero');
      let body = JSON.stringify(EMAIL_CREATE).split('%%EMAIL_HERO%%').join(heroUrl);
      let er = await fetch(CS_BASE, { method: 'POST', headers: H('application/json'), credentials: 'include', body: body });
      let et = await er.text(); if (!er.ok) throw new Error('email create HTTP ' + er.status + ' ' + et);
      emailContentId = JSON.parse(et).id; if (!emailContentId) throw new Error('no email content id: ' + et);
      console.log('%c    email content created ' + emailContentId, 'color:#22c55e');
      body = JSON.stringify(EMAIL_SAVE).split('%%EMAIL_HERO%%').join(heroUrl);
      er = await fetch(CS_BASE + '/' + emailContentId, { method: 'POST', headers: H('application/json'), credentials: 'include', body: body });
      et = await er.text(); if (!er.ok) throw new Error('email save HTTP ' + er.status + ' ' + et);
      console.log('    email content saved (subject + pre-header + body)');
    }

    // 3. the journey, wired to the email that was just created
    const jid = await reserveId();
    console.log('    reserved ' + jid);
    const fill = (s) => { s = s.split('%%RESERVED%%').join(jid).split('%%NC_ICON%%').join(iconUrl).split('%%POPUP_BG%%').join(bgUrl); if (emailContentId) s = s.split('%%EMAIL_CONTENT_ID%%').join(emailContentId); return s; };
    let createStr = fill(JSON.stringify(CREATE)), saveStr = fill(JSON.stringify(SAVE));
    const map = idMap(createStr + saveStr);
    createStr = applyMap(createStr, map); saveStr = applyMap(saveStr, map);

    let r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: H('application/json'), credentials: 'include', body: createStr });
    let t = await r.text(); if (!r.ok) throw new Error('create HTTP ' + r.status + ' ' + t);
    const numId = JSON.parse(t).id; if (!numId) throw new Error('no draft id: ' + t);
    console.log('    draft created ' + numId);

    r = await fetch(BASE + '/journey-drafts/' + numId, { method: 'PUT', headers: H('application/json'), credentials: 'include', body: saveStr });
    t = await r.text(); if (!r.ok) throw new Error('draft ' + jid + ' created but SAVE failed HTTP ' + r.status + ' ' + t);

    console.log('%cDONE — ' + jid + ' (draft ' + numId + ')' + (emailContentId ? ', email ' + emailContentId : ''), 'color:#22c55e;font-weight:bold;font-size:14px');
    console.log('The draft is unpublished — review it in the Journeys UI, check the canvas, then publish.');
  } catch (e) {
    console.error('%cFAILED — ' + ((e && e.message) || e), 'color:#ef4444;font-weight:bold');
    console.error('Nothing was published. Fix the cause and rerun; delete any half-made draft first.');
  }
})();
"""


def build_js(bundle: dict) -> str:
    brand: Brand = bundle["brand"]
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY@", bundle["journey_name"])
    js = js.replace("@BASE_URL@", json.dumps(brand.base_url))
    js = js.replace("@BRAND_JSON@", json.dumps(brand.code))
    js = js.replace("@FOLDER_ID@", json.dumps(brand.folder_id if bundle["upload_photos"] else ""))
    js = js.replace("@CAPTURED_NC_ICON@", json.dumps(brand.tpl_nc_icons[0] if brand.tpl_nc_icons else ""))
    js = js.replace("@CAPTURED_POPUP_BG@", json.dumps(brand.tpl_popup_bg))
    js = js.replace("@MAKE_EMAIL@", "true" if bundle.get("make_email") else "false")
    js = js.replace("@EMAIL_CREATE@", json.dumps(bundle.get("email_create") or {}, ensure_ascii=False))
    js = js.replace("@EMAIL_SAVE@", json.dumps(bundle.get("email_save") or {}, ensure_ascii=False))
    js = js.replace("@CREATE@", json.dumps(bundle["create"], ensure_ascii=False))
    js = js.replace("@SAVE@", json.dumps(bundle["save"], ensure_ascii=False))
    js = js.replace("@BRAND@", brand.code)
    return js


def emit(bundle: dict, name: str) -> Path:
    out = HERE / "console_scripts"
    out.mkdir(exist_ok=True)
    path = out / f"{name}_console.js"
    path.write_text(build_js(bundle), encoding="utf-8")
    return path


def run_cli(brand: Brand, argv: list | None = None) -> int:
    p = argparse.ArgumentParser(
        description=f"{brand.title} tournament comms — sheet in, console script out.")
    p.add_argument("--date", required=True, help="comms send date YYYY-MM-DD (Chile); the journey starts that day at 12:00")
    p.add_argument("--spec", required=True, type=Path, help="content sheet; '-' reads stdin")
    p.add_argument("--link", default="", help="the promo URL every channel opens (any link)")
    p.add_argument("--journey-name", default="", help="override the journey name")
    p.add_argument("--email-content-id", default="",
                   help="existing CSE-* content id — use INSTEAD of building the email")
    p.add_argument("--email-link", default="",
                   help="the game the email CTA opens (…/launch/slots/iframe/<slug>). "
                        "Required when the email is built (no --email-content-id).")
    p.add_argument("--no-photos", action="store_true", help="keep template artwork; no file pickers")
    p.add_argument("--name", default=f"tournament_{brand.code.lower()}", help="output basename")
    p.add_argument("--dry-run", action="store_true", help="write bodies to out/ instead of a script")
    args = p.parse_args(argv)

    spec = read_spec(brand, args.spec, args.link)
    bundle, report = prepare(
        brand, spec, date_str=args.date, journey_name=args.journey_name,
        email_content_id=args.email_content_id, email_game=args.email_link,
        upload_photos=not args.no_photos)

    print(f"{brand.title} tournament comms:")
    for line in report:
        print("  " + line)

    print("\nChecks:")
    all_ok = True
    for ok, msg in verify(bundle):
        print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
        all_ok = all_ok and ok
    if not all_ok:
        print("\nVERIFICATION FAILED — nothing written.", file=sys.stderr)
        return 1

    if args.dry_run:
        out = HERE / "out"; out.mkdir(exist_ok=True)
        path = out / f"{args.name}_bodies.json"
        path.write_text(json.dumps({k: bundle[k] for k in
                                    ("create", "save", "email_create", "email_save")},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — bodies written: {path}")
        return 0

    path = emit(bundle, args.name)
    print(f"\nConsole script written: {path}")
    print(f"Paste it into the DevTools console on a logged-in {brand.code} backoffice tab.")
    return 0
