#!/usr/bin/env python3
"""Build the JBCL tournament comms journey from a captured HAR + a content sheet.

Rebuilt from a fresh capture (fef8c394-tornm.har): a JBCL tournament announced on
three on-journey channels — Notification Center ("JBCL NC Dynamic 2026",
template 1935) + Cat-fish pop-up ("JBCL Pop-up CatFish 2026", template 20678) +
SMS — with two `wait_date` gates tied to the tournament window and an email node
that points at an existing content. Same node family as `sport_comms`, so it uses
the shared `comms_engine` and copies its rules verbatim.

What the earlier version got wrong, and this fixes:

  1. **It only POSTed the draft, never the follow-up PUT (save).** The capture
     does create *then* save; the save is what the editor writes back, and
     without it the canvas can render with unconnected nodes. This does both.
  2. **A capture can carry `positionAbsolute: null` on a node** (this HAR had
     three) — COMPOSER_RULES rule 1, a blank-canvas crash. `backfill_position_
     absolute` repairs it.
  3. **Copy was string-replaced.** The EN and ES slots are identical and shared
     across channels, so a global replace shipped one language everywhere.
     `comms_engine.set_channel_copy` writes each field by name, per language, in
     both storages, and `verify()` reads it back to prove it landed.

Inputs (the tab supplies all of them):

  --date            the comms send date (Chile); the journey runs that day.
  --tournament-link the tournament page URL — its `/page/<slug>` is what every
                    channel links to, and its `&id=<n>` (or --tournament-id) is
                    the Smartico id. Overrides the sheet's Link row.
  --tournament-id   the Smartico tournament id, if not in the link.
  --start / --end   the tournament window; the two wait_date gates get these.
  --spec            the content sheet (tab-separated); EN/ES copy per channel.
  --email-content-id an existing CSE-* content id for the email node. This HAR
                    does not create email content, so the node must point at a
                    real one; a run keeping the captured id is refused.

Usage:
  python tournament_pmcl_campaign.py --date 2026-07-20 \
      --tournament-link https://jugabet.cl/page/torneo-x --tournament-id 5431 \
      --start 2026-07-20 --end 2026-07-27 --spec sheet.tsv
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from create_journeys import BRAND, LOCAL_TZ, UTC, utc_api  # noqa: E402
from casino_journey import DEFAULT_BASE_URL  # noqa: E402
from comms_campaign import DEFAULT_FOLDER_ID  # noqa: E402
from compose import audit_inherited_content  # noqa: E402
from spec_parser import parse_spec  # noqa: E402
import comms_engine as E  # noqa: E402

TEMPLATE_DIR = HERE / "templates" / "tournament"
TPL_CREATE = TEMPLATE_DIR / "tournament_comms_create.json"
TPL_SAVE = TEMPLATE_DIR / "tournament_comms_save.json"

NC_NODE = "JBCL NC Dynamic 2026"
POPUP_NODE = "JBCL Pop-up CatFish 2026"

# ── literals in the capture we swap per run ─────────────────────────────
TPL_JOURNEY = "JBCL | CS&SP | Torneo Leyendas Ganadoras 21-30.06"
TPL_JOURNEY_COPY = "Copy of " + TPL_JOURNEY
# The notification/pop-up nodes label their objectForSend.metadata with a
# shorter spelling of the same journey (no "&SP", no dates). A second literal, so
# a second thing that can be left as the capture's.
TPL_JOURNEY_META = "JBCL | CS | Torneo Leyendas Ganadoras"
TPL_PAGE_SLUG = "torneo-leyendas-ganadoras"      # /page/<slug> — per tournament
TPL_TOURNAMENT_ID = "5196"                        # #_smartico_dp=…&id=<n>
TPL_EMAIL_CONTENT_ID = "CSE-0-14726"              # the captured campaign's email

# ── email content (built + published the way sport_comms/GOW do it) ─────
TPL_EMAIL_CREATE = TEMPLATE_DIR / "tournament_email_create.json"
TPL_EMAIL_SAVE = TEMPLATE_DIR / "tournament_email_save.json"
EMAIL_ID_TOKEN = "%%EMAIL_CONTENT_ID%%"           # journey email node ← created id
EMAIL_HERO_TOKEN = "%%EMAIL_HERO%%"               # hero photo, uploaded at paste
EMAIL_NAME_TOKEN = "%%EMAIL_NAME%%"
EMAIL_SUBJECT_TOKEN = "%%EMAIL_SUBJECT%%"
EMAIL_PREHEADER_TOKEN = "%%EMAIL_PREHEADER%%"
EMAIL_BODY_TOKEN = "EMAIL_BODY_COPY_PLACEHOLDER"
# The captured hero image and game-launch link in the email HTML, per tournament.
TPL_EMAIL_HERO = "https://{{cdn_hostname}}/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/f4323497-5894-43ae-935c-0be3ef5c5056.png"
TPL_EMAIL_GAME = "pragmatic-jugabet-leyendas-del-olympus-1000"
_GAME_RE = re.compile(r"/launch/slots/iframe/([A-Za-z0-9][A-Za-z0-9._-]*)")

TPL_RESERVED = "JRN-0-636011"
TPL_DUPLICATED_FROM = "JRN-0-590173"
TPL_STOPAT = "2026-08-02T04:00:00Z"
# The two wait_date gates, in the order the template stores them (activities 6
# then 9 — the LATER date first). Kept as literals so they are swapped exactly.
TPL_WAIT_LATE = "2026-06-30T16:00:00Z"
TPL_WAIT_EARLY = "2026-06-23T16:00:00Z"

# Artwork uploaded at paste time; ids reserved at paste time. The captured NC
# node carries two icon URLs (icon-src + a common icon) and the pop-up one
# background — all per-tournament, all replaced by tokens so the audit never
# sees a captured URL. The console script fills the tokens: uploads when a folder
# is set, else restores the captured URL (a --no-photos keep, not a leak).
RESERVED_TOKEN = "%%RESERVED%%"
NC_ICON_TOKEN = "%%NC_ICON%%"
POPUP_BG_TOKEN = "%%POPUP_BG%%"

TPL_NC_ICON_A = "https://static.contentin.cloud/73b22051-b16d-46e3-90cb-eeb045f59eea/3247d38f-d24e-4fc1-a753-ac9ced71f539.png"
TPL_NC_ICON_B = "https://static.contentin.cloud/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/bc58e148-13fa-4f6c-a946-3b5b6926dfce.png"
TPL_POPUP_BG = "https://static.contentin.cloud/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/77311945-dfcd-4f56-a9b9-48e44709ae28.png"

_PAGE_RE = re.compile(r"/page/([A-Za-z0-9][A-Za-z0-9._-]*)")
_ID_RE = re.compile(r"[?&]id=(\d+)|&id=(\d+)")
_SLUG_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class Refused(SystemExit):
    """Raised instead of emitting something wrong."""


def json_escape(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


# ── inputs ──────────────────────────────────────────────────────────────
def parse_tournament_link(link: str) -> tuple[str, str]:
    """(page slug, smartico id) from a tournament page URL, or ('','') if blank.

    Both are per-tournament and end up in every channel, so a URL that is not a
    tournament page is refused rather than guessed at."""
    v = (link or "").strip()
    if not v:
        return "", ""
    page = _PAGE_RE.search(v)
    idm = _ID_RE.search(v)
    tid = (idm.group(1) or idm.group(2)) if idm else ""
    if not page:
        if "/" in v or ":" in v:
            raise Refused(
                f"link {v!r} is not a tournament page. Expected …/page/<slug> "
                f"(optionally with &id=<n>)."
            )
        if not _SLUG_OK.match(v):
            raise Refused(f"tournament slug {v!r} is not usable.")
        return v, tid
    return page.group(1), tid


def read_spec(path: Path, tournament_link: str = ""):
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    spec = parse_spec(text, expect_game_offer=False)
    slug, tid = parse_tournament_link(tournament_link)
    if slug:
        spec.promo_slug = slug            # reuse the parsed-sheet field as carrier
    if tid:
        spec.tournament_id = tid
    missing = []
    if not spec.promo_slug:
        missing.append(
            "no tournament page — give --tournament-link (…/page/<slug>) or a "
            'sheet "Link" row'
        )
    if not (spec.nc.title_es and spec.nc.desc_es and spec.nc.caption_es):
        missing.append("Notification title/description/caption")
    if not (spec.popup.title_es and spec.popup.desc_es and spec.popup.caption_es):
        missing.append("Pop-up (Cat-fish) title/description/caption")
    if not (spec.sms.text_es and spec.sms.text_en):
        missing.append("Sms text (EN and ES)")
    if missing:
        raise Refused("missing input:\n  - " + "\n  - ".join(missing))
    return spec


def chile_window(date_str: str) -> tuple[str, str]:
    """(startAt .NET, stopAt .NET) — the send day, 12:00→19:00 Chile → UTC."""
    day = datetime.strptime(date_str, "%Y-%m-%d")
    start = day.replace(hour=12, tzinfo=LOCAL_TZ).astimezone(UTC)
    stop = day.replace(hour=19, tzinfo=LOCAL_TZ).astimezone(UTC)
    return utc_api(start, dotnet_fraction=True), utc_api(stop, dotnet_fraction=True)


def _iso_utc(date_str: str, hh: int = 16) -> str:
    """A tournament-window date as the template stores it (UTC Z, whole hour)."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d:%Y-%m-%d}T{hh:02d}:00:00Z"


# ── prepare ─────────────────────────────────────────────────────────────
def parse_game_slug(value: str) -> str:
    """The game slug the email CTA links to, from a launch URL or a bare slug."""
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


def prepare(spec, *, date_str: str, tournament_start: str, tournament_end: str,
            journey_name: str = "", email_content_id: str = "", email_game: str = "",
            upload_photos: bool = True, now: datetime | None = None
            ) -> tuple[dict, list[str]]:
    now = now or datetime.now(LOCAL_TZ)
    slug = spec.promo_slug
    tid = (spec.tournament_id or "").strip() or TPL_TOURNAMENT_ID
    start_at, stop_at = chile_window(date_str)
    make_email = not email_content_id.strip()

    if journey_name.strip():
        name = journey_name.strip()
    elif spec.event_name and tournament_start and tournament_end:
        s = datetime.strptime(tournament_start, "%Y-%m-%d")
        e = datetime.strptime(tournament_end, "%Y-%m-%d")
        name = f"JBCL | CS&SP | {spec.event_name} {s:%d.%m}-{e:%d.%m}"
    else:
        name = f"JBCL | CS&SP | {slug} {now:%d.%m}"

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

    def string_swaps(text: str) -> str:
        s = text
        s = s.replace(TPL_JOURNEY_COPY, name).replace(TPL_JOURNEY, name)
        s = s.replace(TPL_JOURNEY_META, name)              # objectForSend metadata label
        s = s.replace(TPL_PAGE_SLUG, slug)                 # /page/<slug> everywhere
        s = s.replace(f"id={TPL_TOURNAMENT_ID}", f"id={tid}")   # smartico id
        s = s.replace(TPL_RESERVED, RESERVED_TOKEN)
        # Artwork → tokens, always (the audit must never see a captured URL); the
        # console script fills them from an upload or restores the captured one.
        s = s.replace(TPL_NC_ICON_A, NC_ICON_TOKEN).replace(TPL_NC_ICON_B, NC_ICON_TOKEN)
        s = s.replace(TPL_POPUP_BG, POPUP_BG_TOKEN)
        # The journey's email node: point it at the created content (token filled
        # at paste) or at the existing id the operator gave. Either way the
        # captured CSE-0-14726 must be gone.
        s = s.replace(TPL_EMAIL_CONTENT_ID,
                      EMAIL_ID_TOKEN if make_email else email_content_id.strip())
        return s

    create = json.loads(string_swaps(TPL_CREATE.read_text(encoding="utf-8")))
    save = json.loads(string_swaps(TPL_SAVE.read_text(encoding="utf-8")))

    written = {}
    for body in (create, save):
        body["duplicatedFromId"] = None
        body["duplicatedFromVersion"] = None
        body.pop("changeHistory", None)
        # structural copy — never string-replaced
        written["nc"] = E.set_channel_copy(body, NC_NODE, nc_copy)
        written["popup"] = E.set_channel_copy(body, POPUP_NODE, popup_copy)
        written["sms"] = E.set_sms_text(body, spec.sms.text_en, spec.sms.text_es)
        # canvas labels (displayData) — the hidden second copy
        E.set_display_data(body, lambda a: a.get("activityName") == "dextra_sms",
                           spec.sms.text_es)
        # wait_date gates → the tournament window (later date first, as captured)
        if tournament_start and tournament_end:
            _set_wait_dates(body, _iso_utc(tournament_end), _iso_utc(tournament_start))
        # blank-canvas guard
        E.backfill_position_absolute(body)

    for chan, n in written.items():
        if not n:
            raise Refused(
                f"wrote no {chan} copy — the {chan} node was not found. The "
                f"template changed shape; this build would ship captured copy."
            )

    # schedule + start trigger, in both storages
    save["startAt"] = start_at
    save["stopAt"] = stop_at
    save["isImmediatelyAfterPublish"] = True
    iv = save.get("rawJourneyData", {}).get("infoValues", {})
    iv["stopAt"] = stop_at
    iv["isImmediatelyAfterPublish"] = True
    iv["journeyName"] = name
    save["journeyName"] = name
    create["journeyName"] = name

    # ── the email content, created before the journey so its id can be wired ──
    email_create = email_save = None
    email_name = ""
    email_body_copy = ""
    game = ""
    if make_email:
        if not spec.email.desc_es.strip():
            raise Refused(
                'the sheet has no "Email Description" row and no --email-content-id '
                "was given. Either supply the email body copy or point the node at "
                "an existing CSE-* — a draft keeping the captured email is refused."
            )
        game = parse_game_slug(email_game)
        if not game:
            raise Refused(
                "no --email-link (the game the email CTA opens, "
                "…/launch/slots/iframe/<game-slug>). The captured game must not ship."
            )
        stamp = f"{now:%d.%m}"
        email_name = f"JBCL - Tournament - {spec.event_name or slug} - {stamp} {now:%d.%m.%Y %H:%M:%S}"
        email_body_copy = "\n<br><br>\n".join(
            line.strip() for line in spec.email.desc_es.splitlines() if line.strip()
        )

        def swap_email(text: str) -> str:
            s = text
            s = s.replace(EMAIL_NAME_TOKEN, json_escape(email_name))
            s = s.replace(EMAIL_SUBJECT_TOKEN, json_escape(spec.email.subject_es))
            s = s.replace(EMAIL_PREHEADER_TOKEN, json_escape(spec.email.preheader_es))
            s = s.replace(EMAIL_BODY_TOKEN, json_escape(email_body_copy))
            s = s.replace(TPL_EMAIL_GAME, game)            # /launch/slots/iframe/<game>
            s = s.replace(TPL_EMAIL_HERO, EMAIL_HERO_TOKEN)  # hero → uploaded at paste
            return s

        email_create = json.loads(swap_email(TPL_EMAIL_CREATE.read_text(encoding="utf-8")))
        email_save = json.loads(swap_email(TPL_EMAIL_SAVE.read_text(encoding="utf-8")))

    bundle = {
        "create": create, "save": save,
        "email_create": email_create, "email_save": email_save,
        "make_email": make_email, "email_name": email_name, "email_game": game,
        "slug": slug, "tournament_id": tid, "journey_name": name,
        "email_content_id": email_content_id.strip(),
        "upload_photos": upload_photos,
        "expected": {NC_NODE: nc_copy, POPUP_NODE: popup_copy,
                     "sms": {"en": spec.sms.text_en, "es": spec.sms.text_es},
                     "email_body": email_body_copy},
    }
    report = [
        f"journeyName   {name!r}",
        f"page link     /page/{slug}  (every channel)",
        f"tournament id {tid}  (#_smartico_dp=dp:gf_tournaments&id={tid})",
        f"send window   {start_at} → {stop_at}",
        f"tournament    {tournament_start or '?'} → {tournament_end or '?'} (wait_date gates)",
        (f"email         creating {email_name!r} (hero uploaded, links → /launch/slots/iframe/{game})"
         if make_email else f"email content {email_content_id} (existing, wired into the journey)"),
        f"nc title es   {spec.nc.title_es[:56]!r}",
        f"popup title   {spec.popup.title_es[:56]!r}",
        f"sms es        {spec.sms.text_es[:56]!r}",
        f"photos        {'uploaded at paste (icon + background)' if upload_photos else 'kept from template'}",
    ]
    for w in spec.warnings:
        report.append(f"sheet warning: {w}")
    return bundle, report


def _set_wait_dates(body: dict, late_iso: str, early_iso: str) -> None:
    """Write the two wait_date gates in both storages, keeping capture order."""
    seen = 0
    order = [late_iso, early_iso]
    cfg = body.get("rawJourneyData", {}).get("activitiesConfiguration", {})
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
    create, save = bundle["create"], bundle["save"]
    slug, tid = bundle["slug"], bundle["tournament_id"]
    s_create = json.dumps(create, ensure_ascii=False)
    s_save = json.dumps(save, ensure_ascii=False)
    both = s_create + s_save

    reference = json.loads(TPL_SAVE.read_text(encoding="utf-8"))
    leaked = audit_inherited_content(save, reference)

    page_slugs = set(re.findall(r"/page/([A-Za-z0-9._-]+)", both))
    smartico_ids = set(re.findall(r"[?&]id=(\d+)", both))

    # copy landed, per node and per language
    expected = bundle.get("expected") or {}
    copy_mismatch: list[str] = []
    for node in (NC_NODE, POPUP_NODE):
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
            if sms_want.get(entry.get("languageCode")) and entry.get("messageText") != sms_want[entry["languageCode"]]:
                copy_mismatch.append(f"sms[{entry.get('languageCode')}]")

    dangling = E.dangling_edges(save)
    unknown = E.unknown_canvas_nodes(save)
    no_pos = E.activity_nodes_without_position(save)
    broken = E.canvas_edges_to_missing_node(save)
    iv = save.get("rawJourneyData", {}).get("infoValues", {})

    # ── email content, when this run builds it ──
    email_checks: list[tuple[bool, str]] = []
    if bundle.get("make_email"):
        ec, es = bundle["email_create"], bundle["email_save"]
        s_email = json.dumps(ec, ensure_ascii=False) + json.dumps(es, ensure_ascii=False)
        game = bundle.get("email_game", "")
        html = ""
        for tr in (es.get("translations") or {}).values():
            src = ((tr.get("composition") or {}).get("body") or {}).get("source")
            if isinstance(src, str):
                html += src
        want_body = (expected.get("email_body") or "")
        email_checks = [
            (EMAIL_ID_TOKEN in s_create and EMAIL_ID_TOKEN in s_save,
             "journey email node is a placeholder (filled from the created content)"),
            (EMAIL_HERO_TOKEN in s_email and TPL_EMAIL_HERO not in s_email,
             "email hero is a placeholder (uploaded at paste)"),
            (TPL_EMAIL_GAME not in s_email,
             f"email no longer links to the captured game ({TPL_EMAIL_GAME})"),
            (game and s_email.count(f"/launch/slots/iframe/{game}") >= 2,
             f"email CTA links to this run's game ({game})"),
            (bool(want_body) and want_body in html,
             "email body carries the sheet's copy"),
            (EMAIL_BODY_TOKEN not in s_email,
             "email body placeholder filled"),
            (EMAIL_NAME_TOKEN not in s_email and EMAIL_SUBJECT_TOKEN not in s_email
             and EMAIL_PREHEADER_TOKEN not in s_email
             and (es["translations"]["es"]["composition"].get("subject") or "").strip(),
             "email name / subject / pre-header filled"),
        ]

    return [
        (page_slugs == {slug}, f"every channel links to /page/{slug}"
         + (f" (ALSO: {sorted(page_slugs - {slug})})" if page_slugs - {slug} else "")),
        (both.count(f"/page/{slug}") >= 3, f"the page link reached every channel "
         f"({both.count('/page/' + slug)} occurrences)"),
        (smartico_ids <= {tid}, f"only this tournament id in smartico links ({tid})"
         + (f" (ALSO: {sorted(smartico_ids - {tid})})" if smartico_ids - {tid} else "")),
        (TPL_PAGE_SLUG not in both, f"captured page slug gone ({TPL_PAGE_SLUG})"),
        (f"id={TPL_TOURNAMENT_ID}" not in both or tid == TPL_TOURNAMENT_ID,
         f"captured tournament id replaced ({TPL_TOURNAMENT_ID})"),
        (RESERVED_TOKEN in s_create and TPL_RESERVED not in both,
         "reservedJourneyId is a placeholder, captured id gone"),
        (TPL_EMAIL_CONTENT_ID not in both,
         f"email node no longer points at the captured content ({TPL_EMAIL_CONTENT_ID})"),
        (TPL_JOURNEY not in both and TPL_JOURNEY_COPY not in both,
         'journey renamed (no "Copy of", no captured name)'),
        (create.get("duplicatedFromId") is None and TPL_DUPLICATED_FROM not in both,
         "lineage stripped"),
        (not copy_mismatch, "every channel field matches the sheet"
         + (f" (WRONG: {copy_mismatch[:3]})" if copy_mismatch else "")),
        (not dangling, "every nextActivityId resolves"
         + (f" (DANGLING: {dangling[:2]})" if dangling else "")),
        (not broken, "every canvas edge connects two real nodes"
         + (f" (BROKEN: {broken[:2]})" if broken else "")),
        (not unknown, "every canvas node is an activity or known scaffolding"
         + (f" (UNKNOWN: {unknown[:2]})" if unknown else "")),
        (not no_pos, "every activity node has position + positionAbsolute"
         + (f" (MISSING: {no_pos[:2]})" if no_pos else "")),
        (bool(iv.get("stopAt")) and save.get("stopAt", "").startswith(iv["stopAt"][:19]),
         f"both storages agree on stopAt ({iv.get('stopAt')})"),
        (iv.get("journeyName") == save.get("journeyName"),
         "both storages agree on journeyName"),
        (iv.get("isImmediatelyAfterPublish") == save.get("isImmediatelyAfterPublish") is True,
         "start trigger set in both storages"),
        (any(a.get("activityName") == "end_of_journey" for a in save.get("activities", [])),
         "a terminal activity exists"),
        (not leaked, "no content still shared with the capture"
         + (f" (LEAK: {leaked[:2]})" if leaked else "")),
    ] + email_checks


# ── emit ────────────────────────────────────────────────────────────────
JS_TEMPLATE = r"""// JBCL Tournament comms — @JOURNEY@ — generated @GENERATED_AT@
// ONE journey: notification + pop-up + SMS + email, gated by the tournament
// window. Creates the draft (POST) and then SAVES it (PUT) — the save is what
// finalises the canvas, and skipping it left nodes unconnected. Draft only.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
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

  console.log('%cJBCL Tournament comms', 'color:#3b82f6;font-weight:bold;font-size:14px');
  try {
    // 1. artwork
    let iconUrl = CAPTURED_NC_ICON, bgUrl = CAPTURED_POPUP_BG;   // defaults: keep template art
    if (FOLDER_ID) {
      iconUrl = await upload(await pickFile('the NOTIFICATION ICON (200x200)'), 'notification icon');
      bgUrl = await upload(await pickFile('the POP-UP BACKGROUND'), 'pop-up background');
    } else {
      console.log('%cNo FOLDER_ID — keeping the template artwork (no pickers).', 'color:#eab308');
    }

    // 2. email content FIRST — the journey needs its id
    let emailContentId = null;
    if (MAKE_EMAIL) {
      if (!FOLDER_ID) throw new Error('email needs a media-library folder for the hero upload — set Folder ID.');
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


def build_js(bundle: dict, folder_id: str) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY@", bundle["journey_name"])
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@FOLDER_ID@", json.dumps(folder_id if bundle["upload_photos"] else ""))
    js = js.replace("@CAPTURED_NC_ICON@", json.dumps(TPL_NC_ICON_A))
    js = js.replace("@CAPTURED_POPUP_BG@", json.dumps(TPL_POPUP_BG))
    js = js.replace("@MAKE_EMAIL@", "true" if bundle.get("make_email") else "false")
    js = js.replace("@EMAIL_CREATE@", json.dumps(bundle.get("email_create") or {}, ensure_ascii=False))
    js = js.replace("@EMAIL_SAVE@", json.dumps(bundle.get("email_save") or {}, ensure_ascii=False))
    js = js.replace("@CREATE@", json.dumps(bundle["create"], ensure_ascii=False))
    js = js.replace("@SAVE@", json.dumps(bundle["save"], ensure_ascii=False))
    return js


def emit(bundle: dict, name: str, folder_id: str) -> Path:
    out = HERE / "console_scripts"
    out.mkdir(exist_ok=True)
    path = out / f"{name}_console.js"
    path.write_text(build_js(bundle, folder_id), encoding="utf-8")
    return path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", required=True, help="comms send date YYYY-MM-DD (Chile)")
    p.add_argument("--spec", required=True, type=Path, help="content sheet; '-' reads stdin")
    p.add_argument("--tournament-link", default="", help="tournament page URL (…/page/<slug>[&id=<n>])")
    p.add_argument("--tournament-id", default="", help="Smartico tournament id, if not in the link")
    p.add_argument("--start", default="", help="tournament start YYYY-MM-DD")
    p.add_argument("--end", default="", help="tournament end YYYY-MM-DD")
    p.add_argument("--journey-name", default="", help="override the journey name")
    p.add_argument("--email-content-id", default="",
                   help="existing CSE-* content id — use INSTEAD of building the email")
    p.add_argument("--email-link", default="",
                   help="the game the email CTA opens (…/launch/slots/iframe/<slug>). "
                        "Required when the email is built (no --email-content-id).")
    p.add_argument("--folder-id", default=DEFAULT_FOLDER_ID, help="media-library folder for uploads")
    p.add_argument("--no-photos", action="store_true", help="keep template artwork; no file pickers")
    p.add_argument("--name", default="tournament_comms", help="output basename")
    p.add_argument("--dry-run", action="store_true", help="write bodies to out/ instead of a script")
    args = p.parse_args()

    spec = read_spec(args.spec, args.tournament_link)
    if args.tournament_id.strip():
        spec.tournament_id = args.tournament_id.strip()
    bundle, report = prepare(
        spec, date_str=args.date, tournament_start=args.start, tournament_end=args.end,
        journey_name=args.journey_name, email_content_id=args.email_content_id,
        email_game=args.email_link, upload_photos=not args.no_photos)

    print("JBCL Tournament comms:")
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

    path = emit(bundle, args.name, args.folder_id if not args.no_photos else "")
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in JBCL backoffice tab.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
