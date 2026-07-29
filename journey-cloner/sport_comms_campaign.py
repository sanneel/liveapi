#!/usr/bin/env python3
"""Build the Sport scratch-card comms campaign from a liveapi campaign + a sheet.

Business flow (captured 15.07, "JBCL | SP | SCR Card - ENG vs ARG | Comms"):
a fixture-driven scratch-card promo announced on four channels from ONE journey
— SMS, Notification Center, Cat-fish pop-up and email — with waits, two decision
splits and a `deposit.approved` detector between them. Everything links to the
randomizer promo page for that fixture.

Two inputs, both of which the operator already has:

  --campaign <slug>   a campaign created in liveapi (app/models/campaign.py).
                      Supplies the journey name (its title), the schedule (its
                      expires_at) and the email hero image (its rendered card,
                      /r/<slug>.png).
  --spec <file>       the content sheet, pasted/saved as tab-separated text.
                      Supplies every channel's EN/ES copy and — from its "Link"
                      row — the randomizer promo slug all four channels use.

What the generator substitutes, by string replacement across the whole body so
the compiled `activities[]` and the `rawJourneyData` editor mirror stay
byte-identical (they are two copies of one journey; disagreement renders a blank
canvas):

  * the journey name, in both its "| SP |" and "| CS&SP |" spellings,
  * the promo slug in every link, deeplink and the SMS URL,
  * SMS text, notification title/description/caption, pop-up
    title/description/caption, email subject and pre-header — EN and ES,
  * the email content id, the notification icon and the pop-up background,
    all filled at paste time from what the console script creates/uploads,
  * the schedule (stopAt) and the reserved journey id.

Two facts about the capture that this generator deliberately does NOT reproduce:

  1. **The recorded run never wired its email in.** It created content
     CSE-0-16076 but left the journey pointing at CSE-0-15619 — the email of the
     campaign it was copied from. Replayed as captured, every draft would send
     the previous campaign's email. Here the email content is created FIRST and
     its returned id substituted into the journey, and `verify()` refuses to
     emit while the captured id is still present.
  2. **Its EN and ES notification links pointed at different promo pages**
     (`sf-sc-2026` vs `arg-eng-sc`) — a leftover from the earlier semifinal
     campaign. Both languages get the one slug from the sheet, and `verify()`
     refuses if they disagree.

Usage:
  python sport_comms_campaign.py --campaign eng-arg-sc --spec sheet.tsv
  python sport_comms_campaign.py --campaign eng-arg-sc --spec sheet.tsv --dry-run
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
from spec_parser import parse_spec, _PROMO_SLUG_RE  # noqa: E402

TEMPLATE_DIR = HERE / "templates" / "sportcomms"
TPL_CREATE = TEMPLATE_DIR / "scratch_card_comms_create.json"
TPL_SAVE = TEMPLATE_DIR / "scratch_card_comms_save.json"
TPL_EMAIL_CREATE = TEMPLATE_DIR / "scratch_card_email_create.json"
TPL_EMAIL_SAVE = TEMPLATE_DIR / "scratch_card_email_save.json"

# ── literals in the capture we swap per run ─────────────────────────────
TPL_JOURNEY_SP = "JBCL | SP | SCR Card - ENG vs ARG | Comms 15.07"
TPL_JOURNEY_CSSP = "JBCL | CS&SP | SCR Card - ENG vs ARG | Comms 15.07"
TPL_JOURNEY_COPY = "Copy of " + TPL_JOURNEY_SP

# The promo page every channel points at. Two slugs were captured: the ES one
# is this campaign's, the EN one is the previous campaign's leftover.
TPL_SLUG_ES = "arg-eng-sc"
TPL_SLUG_EN = "sf-sc-2026"

TPL_NC_TITLE = "Inglaterra vs Argentina: Raspa y gana un Bono"
TPL_NC_DES = "Raspa la tarjeta y gana un Bono + Freebet de $1.000 en una semana. 🎁"
TPL_NC_CAPTION = "Juega Ya "
TPL_POPUP_TITLE = "Raspe y Gana Bono 🎁"
TPL_POPUP_DES_EN = (
    "Inglaterra vs Argentina, po. Raspa y ganai un Bono + Freebet $1.000 "
    "el miércoles que viene"
)
TPL_POPUP_DES_ES = (
    "Raspa y gana un Bono + Freebet de $1.000 con Inglaterra vs. Argentina "
    "el miércoles que viene."
)

# Two distinct SMS strings live in the capture: `rawValues.messageText` and the
# one in `smsSettings` + both localized lists. Both must be written or the node
# ships half the previous campaign's copy.
TPL_SMS_PRIMARY = (
    "JugaBet | Raspa y gana un Bono con Inglaterra vs. Argentina + Freebet de "
    "$1.000 el proximo miércoles. ¡Juega ya! "
    "https://jugabet.cl/services/promo/offers/randomizer/arg-eng-sc"
)
TPL_SMS_RAW = (
    "JugaBet | Raspa y gana un Bono con Inglaterra vs. Argentina + Freebet de "
    "$1.000 este miércoles. Juega ya: "
    "https://jugabet.cl/services/promo/offers/randomizer/arg-eng-sc"
)

TPL_EMAIL_SUBJECT = "Raspa y Gana un Bono con la semifinal ⚽🏆"
TPL_EMAIL_PREHEADER = (
    "Inglaterra vs Argentina en semifinal. Raspa, ganai un Bono y un Freebet "
    "en una semana "
)
TPL_EMAIL_NAME = "JBCL - Scratch Card - Arg vs Eng - 15.07 29.07.2026 16:28:20"
# The full-width hero in the email body. The 40%-wide one below it is the CTA
# button artwork and is campaign-agnostic, so it stays as captured.
TPL_EMAIL_HERO = (
    "https://{{cdn_hostname}}/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/"
    "3fe1396f-45c4-4335-964b-e36f054d4f6a.png"
)

TPL_EMAIL_CONTENT_ID = "CSE-0-15619"   # the copied campaign's email — must go
TPL_NC_ICON = (
    "https://static.contentin.cloud/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/"
    "d8fad07f-b4d2-4204-a0f2-3b8b7bfd7588.png"
)
TPL_POPUP_BG = (
    "https://static.contentin.cloud/c93ad623-44ae-40f6-9aa5-b1aef7fd931a/"
    "8c05db96-72b5-4ff2-86ad-807c42c18cc7.png"
)

TPL_RESERVED = "JRN-0-634415"
TPL_DUPLICATED_FROM = "JRN-0-617284"
TPL_STOPAT = "2026-08-01T04:00:00Z"

# Filled by the console script from what it creates at paste time.
RESERVED_TOKEN = "%%RESERVED%%"
EMAIL_ID_TOKEN = "%%EMAIL_CONTENT_ID%%"
NC_ICON_TOKEN = "%%NC_ICON%%"
POPUP_BG_TOKEN = "%%POPUP_BG%%"
EMAIL_HERO_TOKEN = "%%EMAIL_HERO%%"

PROMO_URL = "https://jugabet.cl/services/promo/offers/randomizer/{slug}"
_SMS_URL_RE = re.compile(
    r"https://jugabet\.cl/services/promo/offers/randomizer/[A-Za-z0-9._-]+"
)


class Refused(SystemExit):
    """Raised instead of emitting something wrong."""


# ── input 1: the liveapi campaign ───────────────────────────────────────
def load_campaign(slug: str) -> dict:
    """Campaign row + its rendered-card URL, read straight from the liveapi DB."""
    sys.path.insert(0, str(HERE.parent))
    try:
        from app.config import get_settings
        from app.database import db_session
        from app.repositories.campaign_repo import CampaignRepository
    except ImportError as exc:  # pragma: no cover - environment problem, not input
        raise Refused(f"cannot import the liveapi app to read campaigns: {exc}")

    with db_session() as session:
        row = CampaignRepository(session).find_by_slug(slug)
        if row is None:
            raise Refused(
                f"no campaign {slug!r} in liveapi. Create it first "
                f"(Admin ▸ Campaigns), or check the slug."
            )
        campaign = {
            "slug": row.slug,
            "title": row.title,
            "sport": row.sport,
            "mode": row.mode,
            "enabled": row.enabled,
            "expires_at": row.expires_at,
        }

    base = (get_settings().public_base_url or "").rstrip("/")
    campaign["image_url"] = f"{base}/r/{row.slug}.png" if base else ""
    return campaign


def _schedule(campaign: dict, stop_at: str = "") -> tuple[str, str]:
    """(plain-UTC stopAt for the body strings, .NET stopAt for the top level).

    The captured journey starts immediately on publish and runs to a fixed stop.
    `stop_at` wins when given (the form field); otherwise it falls back to the
    campaign's expiry, so by default the comms cannot outlive the page every one
    of them links to. Naive values are read as Chile local, like every other
    date in this repo.
    """
    chosen, source = None, ""
    if stop_at.strip():
        try:
            chosen = datetime.fromisoformat(stop_at.strip().replace("Z", "+00:00"))
        except ValueError:
            raise Refused(
                f"stop date {stop_at!r} is not a date I can read. Use "
                f"YYYY-MM-DD or YYYY-MM-DDTHH:MM."
            )
        source = "the stop date given"
    elif campaign.get("expires_at") is not None:
        chosen = campaign["expires_at"]
        source = f"campaign {campaign['slug']!r} expiry"

    if chosen is None:
        raise Refused(
            f"no stop date. Either set one on this run, or give campaign "
            f"{campaign['slug']!r} an expiry date in liveapi — without one the "
            f"comms would outlive the page they link to."
        )
    if chosen.tzinfo is None:
        chosen = chosen.replace(tzinfo=LOCAL_TZ)
    stop = chosen.astimezone(UTC)
    if stop <= datetime.now(UTC):
        raise Refused(
            f"{source} is {stop:%Y-%m-%d %H:%M} UTC, already past — nothing to "
            f"announce. Pick a stop date in the future."
        )
    return stop.strftime("%Y-%m-%dT%H:%M:%SZ"), utc_api(stop, dotnet_fraction=True)


# ── input 2: the content sheet ──────────────────────────────────────────
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def promo_slug_from(value: str) -> str:
    """The randomizer slug in `value` — a full promo URL or a bare slug.

    Operators paste whichever is in front of them, so both are accepted. A URL
    that is not a randomizer promo page is refused rather than guessed at: the
    slug ends up in every channel's link, and quietly taking the last path
    segment of some other URL would send every player to the wrong page.
    """
    v = (value or "").strip()
    if not v:
        return ""
    found = _PROMO_SLUG_RE.search(v)
    if found:
        return found.group(1)
    if "/" in v or ":" in v:
        raise Refused(
            f"link {v!r} is not a randomizer promo page. Expected "
            f"…/services/promo/offers/randomizer/<slug> (or just the slug)."
        )
    if not _SLUG_RE.match(v):
        raise Refused(f"promo slug {v!r} is not a usable slug.")
    return v


def read_spec(path: Path, promo_link: str = ""):
    # "-" reads stdin, so the admin tab can pipe a pasted sheet without ever
    # putting it on disk — same convention as the gow/prediction textareas.
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    spec = parse_spec(text, expect_game_offer=False)
    # An explicit link wins over the sheet's "Link" row: it is the value the
    # operator just typed for this run, and it is the one thing that has to be
    # right in all four channels at once.
    override = promo_slug_from(promo_link)
    if override:
        spec.promo_slug = override
    missing = []
    if not spec.promo_slug:
        missing.append(
            "no randomizer promo link — give one on this run, or put it in the "
            'sheet\'s "Link" row (…/services/promo/offers/randomizer/<slug>)'
        )
    if not (spec.sms.text_es and spec.sms.text_en):
        missing.append("Sms text (EN and ES)")
    if not (spec.nc.title_es and spec.nc.desc_es and spec.nc.caption_es):
        missing.append("Notification title/description/caption")
    if not (spec.popup.title_es and spec.popup.desc_es and spec.popup.caption_es):
        missing.append("Pop-up (Cat-fish) title/description/caption")
    if not (spec.email.subject_es and spec.email.preheader_es):
        missing.append("Email subject/pre-header")
    if missing:
        raise Refused("missing input:\n  - " + "\n  - ".join(missing))
    return spec


def _sms_text(raw: str, slug: str) -> str:
    """Sheet SMS copy with the promo URL forced to this run's slug.

    The sheet's own text carries a link, and a stale one there sends players to
    the previous campaign — the same class of failure as the EN/ES mismatch. Any
    randomizer URL in the copy is rewritten; if there is none, it is appended.
    """
    url = PROMO_URL.format(slug=slug)
    text = raw.strip()
    if _SMS_URL_RE.search(text):
        return _SMS_URL_RE.sub(url, text)
    return f"{text} {url}"


# ── prepare ─────────────────────────────────────────────────────────────
def prepare(campaign: dict, spec, now: datetime | None = None,
            stop_at: str = "") -> tuple[dict, list[str]]:
    now = now or datetime.now(LOCAL_TZ)
    slug = spec.promo_slug
    stop_plain, stop_dotnet = _schedule(campaign, stop_at)

    label = campaign["title"].strip()
    stamp = f"{now:%d.%m}"
    journey_sp = f"JBCL | SP | SCR Card - {label} | Comms {stamp}"
    journey_cssp = f"JBCL | CS&SP | SCR Card - {label} | Comms {stamp}"
    email_name = f"JBCL - Scratch Card - {label} - {stamp} {now:%d.%m.%Y %H:%M:%S}"

    sms_es = _sms_text(spec.sms.text_es, slug)
    sms_en = _sms_text(spec.sms.text_en, slug)

    def swap_journey(text: str) -> str:
        s = text
        # Longest first: "Copy of …" contains the plain name.
        s = s.replace(TPL_JOURNEY_COPY, journey_sp)
        s = s.replace(TPL_JOURNEY_CSSP, journey_cssp)
        s = s.replace(TPL_JOURNEY_SP, journey_sp)
        # Links: both captured slugs collapse onto this run's single slug.
        s = s.replace(TPL_SLUG_EN, slug)
        s = s.replace(TPL_SLUG_ES, slug)
        # SMS — the two distinct strings, before any shorter copy replacement.
        s = s.replace(json_escape(TPL_SMS_PRIMARY), json_escape(sms_es))
        s = s.replace(json_escape(TPL_SMS_RAW), json_escape(sms_en))
        # Notification / pop-up copy. EN slots first: the captured EN and ES
        # values are identical for title/caption, so replacing ES first would
        # also consume the EN slot and both languages would ship ES copy.
        s = s.replace(json_escape(TPL_POPUP_DES_EN), json_escape(spec.popup.desc_en))
        s = s.replace(json_escape(TPL_POPUP_DES_ES), json_escape(spec.popup.desc_es))
        s = replace_lang(s, TPL_NC_TITLE, spec.nc.title_en, spec.nc.title_es)
        s = replace_lang(s, TPL_NC_DES, spec.nc.desc_en, spec.nc.desc_es)
        s = replace_lang(s, TPL_NC_CAPTION, spec.nc.caption_en, spec.nc.caption_es)
        s = replace_lang(s, TPL_POPUP_TITLE, spec.popup.title_en, spec.popup.title_es)
        # Artwork + the email the journey points at: filled at paste time.
        s = s.replace(TPL_NC_ICON, NC_ICON_TOKEN)
        s = s.replace(TPL_POPUP_BG, POPUP_BG_TOKEN)
        s = s.replace(TPL_EMAIL_CONTENT_ID, EMAIL_ID_TOKEN)
        s = s.replace(TPL_STOPAT, stop_plain)
        s = s.replace(TPL_RESERVED, RESERVED_TOKEN)
        return s

    create = json.loads(swap_journey(TPL_CREATE.read_text(encoding="utf-8")))
    save = json.loads(swap_journey(TPL_SAVE.read_text(encoding="utf-8")))
    for body in (create, save):
        body["duplicatedFromId"] = None
        body["duplicatedFromVersion"] = None
        body.pop("changeHistory", None)
    save["stopAt"] = stop_dotnet
    save["rawJourneyData"]["infoValues"]["stopAt"] = stop_plain

    # ── the email content, created before the journey so its id can be wired ──
    def swap_email(text: str) -> str:
        s = text
        s = s.replace(TPL_SLUG_EN, slug).replace(TPL_SLUG_ES, slug)
        s = s.replace(json_escape(TPL_EMAIL_SUBJECT), json_escape(spec.email.subject_es))
        s = s.replace(json_escape(TPL_EMAIL_PREHEADER), json_escape(spec.email.preheader_es))
        s = s.replace(TPL_EMAIL_HERO, EMAIL_HERO_TOKEN)
        s = s.replace(TPL_EMAIL_NAME, email_name)
        return s

    email_create = json.loads(swap_email(TPL_EMAIL_CREATE.read_text(encoding="utf-8")))
    email_save = json.loads(swap_email(TPL_EMAIL_SAVE.read_text(encoding="utf-8")))

    bundle = {
        "journey_create": create,
        "journey_save": save,
        "email_create": email_create,
        "email_save": email_save,
        "campaign": campaign,
        "promo_slug": slug,
        "journey_name": journey_sp,
        # The notification nodes label themselves with a "| CS&SP |" spelling of
        # the same journey. It is a second literal, so it is a second thing that
        # can be left as the capture's.
        "journey_name_nc": journey_cssp,
        "email_name": email_name,
    }
    report = [
        f"campaign      {campaign['slug']!r} — {label!r} ({campaign['sport']})",
        f"journeyName   {journey_sp!r}",
        f"promo link    {PROMO_URL.format(slug=slug)}  (in all four channels)",
        f"stopAt        {stop_plain}  ({'given on this run' if stop_at.strip() else 'campaign expires_at'})",
        f"email         {email_name!r}  (created first, id wired into the journey)",
        f"hero image    {campaign['image_url'] or '(no PUBLIC_BASE_URL — file picker)'}",
        f"sms es        {sms_es[:78]!r}",
        f"nc title es   {spec.nc.title_es[:60]!r}",
        f"popup title   {spec.popup.title_es[:60]!r}",
        f"email subject {spec.email.subject_es[:60]!r}",
    ]
    for w in spec.warnings:
        report.append(f"sheet warning: {w}")
    return bundle, report


def json_escape(value: str) -> str:
    """The value as it appears inside the serialized template."""
    return json.dumps(value, ensure_ascii=False)[1:-1]


def replace_lang(text: str, captured: str, en: str, es: str) -> str:
    """Write EN then ES into a field the capture holds twice with one value.

    The captured EN and ES slots carry identical strings for several fields.
    Replacing with the ES value first would rewrite both, and the EN copy from
    the sheet would never land — the silent class of bug the runbook warns about.
    """
    cap = json_escape(captured)
    if cap not in text:
        return text
    first, rest = text.split(cap, 1)
    return first + json_escape(en) + rest.replace(cap, json_escape(es))


# ── verify — refuses, does not warn ─────────────────────────────────────
def verify(bundle: dict) -> list[tuple[bool, str]]:
    create, save = bundle["journey_create"], bundle["journey_save"]
    email_save = bundle["email_save"]
    slug = bundle["promo_slug"]
    s_create = json.dumps(create, ensure_ascii=False)
    s_save = json.dumps(save, ensure_ascii=False)
    s_email = json.dumps(email_save, ensure_ascii=False)
    both = s_create + s_save

    reference = json.loads(TPL_SAVE.read_text(encoding="utf-8"))
    leaked = audit_inherited_content(save, reference)

    iv = save.get("rawJourneyData", {}).get("infoValues", {})
    acts = {a.get("activityId") for a in save.get("activities", [])}
    elements = save.get("rawJourneyData", {}).get("elements", [])
    dangling = [
        ev.get("nextActivityId")
        for a in save.get("activities", [])
        for ev in (a.get("events") or [])
        if ev.get("nextActivityId") and ev.get("nextActivityId") not in acts
    ]
    # This journey is a PARALLEL flow, so its canvas carries scaffolding
    # elements alongside the activity nodes. COMPOSER_RULES' position rule is
    # about activity nodes: the edge-shaped scaffolding below has no position in
    # the capture either, and requiring one would refuse a journey that renders.
    # What must not appear is a node that is neither an activity nor known
    # scaffolding — that is a node the editor cannot resolve.
    scaffolding = {"default", "parallelFlow", "exit", "flowEntry", "dropZone",
                   "emptyEdge", "dropEdge", "mergeEdge"}
    unknown_nodes = [
        e.get("id") for e in elements
        if e.get("id") not in acts and e.get("type") not in scaffolding
    ]
    no_position = [
        e.get("id") for e in elements
        if e.get("id") in acts
        and not (isinstance(e.get("position"), dict) and isinstance(e.get("positionAbsolute"), dict))
    ]

    checks = [
        (TPL_EMAIL_CONTENT_ID not in both,
         f"journey no longer points at the copied campaign's email ({TPL_EMAIL_CONTENT_ID})"),
        (EMAIL_ID_TOKEN in s_create and EMAIL_ID_TOKEN in s_save,
         "email-content placeholder present in both bodies (filled at paste)"),
        (TPL_SLUG_EN not in both and TPL_SLUG_ES not in both,
         f"no captured promo slug left ({TPL_SLUG_EN} / {TPL_SLUG_ES})"),
        (both.count(f"/randomizer/{slug}") >= 6,
         f"every channel links to /randomizer/{slug} "
         f"({both.count('/randomizer/' + slug)} occurrences)"),
        (s_email.count(f"/randomizer/{slug}") >= 1 and TPL_SLUG_ES not in s_email,
         "email links to this run's promo page"),
        (RESERVED_TOKEN in s_create and TPL_RESERVED not in both,
         "reservedJourneyId is a placeholder, captured id gone"),
        (NC_ICON_TOKEN in both and TPL_NC_ICON not in both,
         "notification icon replaced (uploaded at paste)"),
        (POPUP_BG_TOKEN in both and TPL_POPUP_BG not in both,
         "pop-up background replaced (uploaded at paste)"),
        (EMAIL_HERO_TOKEN in s_email and TPL_EMAIL_HERO not in s_email,
         "email hero image replaced by the campaign card"),
        (TPL_JOURNEY_COPY not in both and TPL_JOURNEY_SP not in both
         and TPL_JOURNEY_CSSP not in both,
         'journey renamed (no "Copy of", no captured name)'),
        (create.get("duplicatedFromId") is None and TPL_DUPLICATED_FROM not in both,
         "lineage stripped (duplicatedFromId)"),
        (TPL_SMS_PRIMARY not in both and TPL_SMS_RAW not in both,
         "both captured SMS strings replaced"),
        (TPL_NC_TITLE not in both and TPL_POPUP_TITLE not in both,
         "notification and pop-up titles replaced"),
        (TPL_NC_DES not in both and TPL_POPUP_DES_ES not in both
         and TPL_POPUP_DES_EN not in both,
         "notification and pop-up descriptions replaced"),
        (TPL_EMAIL_SUBJECT not in s_email and TPL_EMAIL_PREHEADER not in s_email,
         "email subject and pre-header replaced"),
        (bool(iv.get("stopAt")) and save.get("stopAt", "").startswith(iv["stopAt"][:19]),
         f"both storages agree on stopAt ({iv.get('stopAt')})"),
        (iv.get("journeyName") == save.get("journeyName"),
         "both storages agree on journeyName"),
        (iv.get("isImmediatelyAfterPublish") == save.get("isImmediatelyAfterPublish"),
         "both storages agree on the start trigger"),
        (not dangling, "every nextActivityId resolves" + (f" (DANGLING: {dangling[:3]})" if dangling else "")),
        (not unknown_nodes, "every canvas node is an activity or known scaffolding"
         + (f" (UNKNOWN: {unknown_nodes[:3]})" if unknown_nodes else "")),
        (not no_position, "every activity node has position + positionAbsolute"
         + (f" (MISSING: {no_position[:3]})" if no_position else "")),
        (any(a.get("activityName") == "end_of_journey" for a in save.get("activities", [])),
         "a terminal activity exists"),
        (not leaked, "no content still shared with the capture"
         + (f" (LEAK: {leaked[:2]})" if leaked else "")),
    ]
    return checks


# ── emit ────────────────────────────────────────────────────────────────
JS_TEMPLATE = r"""// Sport scratch-card comms — @JOURNEY_NAME@ — generated @GENERATED_AT@
// ONE journey (SMS + notification + pop-up + email) for the liveapi campaign
// @CAMPAIGN@. Order matters: the email content is created FIRST so the journey
// can point at it — the recorded run skipped that and kept the previous
// campaign's email. The draft is left unpublished for review.
(async () => {
  'use strict';
  const MANUAL_TOKEN = '';
  const BASE = @BASE_URL@;
  const BRAND = @BRAND@;
  const FOLDER_ID = @FOLDER_ID@;
  const CAMPAIGN = @CAMPAIGN@;
  const HERO_URL = @HERO_URL@;          // liveapi campaign card, '' if unset
  const EMAIL_CREATE = @EMAIL_CREATE@;
  const EMAIL_SAVE = @EMAIL_SAVE@;
  const JOURNEY_CREATE = @JOURNEY_CREATE@;
  const JOURNEY_SAVE = @JOURNEY_SAVE@;
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
      console.log('%cSelect the image for ' + label + ' (top-left of the page).', 'color:#eab308;font-weight:bold');
      input.addEventListener('change', () => { const f = input.files && input.files[0]; input.remove(); if (!f) { reject(new Error('No file selected for ' + label)); return; } resolve(f); });
    });
  }
  function imageDims(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file); const img = new Image();
      img.onload = () => { URL.revokeObjectURL(url); resolve({ width: img.naturalWidth, height: img.naturalHeight }); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read image dimensions for ' + file.name)); };
      img.src = url;
    });
  }
  // The campaign card lives on liveapi, not the backoffice CDN, so it has to be
  // uploaded to the media library like any other asset. If the browser cannot
  // fetch it cross-origin, fall back to picking the file by hand.
  async function heroFile() {
    if (HERO_URL) {
      try {
        const r = await fetch(HERO_URL, { mode: 'cors', credentials: 'omit' });
        if (r.ok) { const b = await r.blob(); console.log('    campaign card fetched from liveapi'); return new File([b], CAMPAIGN + '.png', { type: b.type || 'image/png' }); }
        console.warn('    campaign card HTTP ' + r.status + ' — falling back to a file picker');
      } catch (e) { console.warn('    campaign card not fetchable (' + e.message + ') — falling back to a file picker'); }
    }
    return pickFile('the EMAIL HERO (the campaign card)');
  }

  const auth = await obtainAuth();
  const H = (ct) => { const h = { accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND }; if (ct) h['content-type'] = ct; return h; };

  async function upload(file, label) {
    const dims = await imageDims(file);
    const base = (file.name || 'image').replace(/\.[^./]+$/, '');
    const url = CRM_BASE + '/media-library/v0/folder/' + FOLDER_ID + '/upload/' + encodeURIComponent(base) + '.png?height=' + dims.height + '&width=' + dims.width;
    const fd = new FormData(); fd.append('file', file, file.name);
    const r = await fetch(url, { method: 'PUT', headers: H(), credentials: 'include', body: fd });
    const t = await r.text(); if (!r.ok) throw new Error(label + ' upload failed HTTP ' + r.status + ' ' + t);
    const asset = JSON.parse(t);
    const tfd = new FormData(); tfd.append('file', file, file.name);
    await fetch(CRM_BASE + '/media-library/v0/asset/thumb/' + asset.id + '.png', { method: 'PUT', headers: H(), credentials: 'include', body: tfd }).catch(() => {});
    console.log('    ' + label + ' -> ' + asset.absolute_link);
    return asset.absolute_link;
  }

  async function reserveId() {
    const r = await fetch(BASE + '/journeys/identifier', { method: 'POST', headers: H('application/json'), credentials: 'include', body: '' });
    const t = await r.text(); if (!r.ok) throw new Error('reserve id failed HTTP ' + r.status + ' ' + t);
    const id = JSON.parse(t).journeyId; if (!id) throw new Error('no journeyId in reserve response: ' + t); return id;
  }

  // Both journey bodies carry the SAME activity ids, so one shared mapping has
  // to be applied to both — otherwise the create and the save describe two
  // different journeys and the editor shows a blank canvas.
  const newUuid = () => (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random()*16|0; return (c === 'x' ? r : (r&0x3)|0x8).toString(16); });
  const UUID_RE = /"(?:activityId|id)"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"/g;
  function idMap(txt) {
    const map = new Map(); let m; UUID_RE.lastIndex = 0;
    while ((m = UUID_RE.exec(txt)) !== null) if (!map.has(m[1])) map.set(m[1], newUuid());
    return map;
  }
  function applyMap(txt, map) { let t = txt; for (const [o, n] of map) t = t.split(o).join(n); return t; }

  console.log('%cSport comms — campaign ' + CAMPAIGN, 'color:#3b82f6;font-weight:bold;font-size:14px');
  try {
    // 1. artwork
    const heroUrl = await upload(await heroFile(), 'email hero');
    const iconUrl = await upload(await pickFile('the NOTIFICATION ICON (200x200)'), 'notification icon');
    const bgUrl = await upload(await pickFile('the POP-UP BACKGROUND'), 'pop-up background');

    // 2. email content FIRST — the journey needs its id
    let body = EMAIL_CREATE.split('%%EMAIL_HERO%%').join(heroUrl);
    let r = await fetch(CS_BASE, { method: 'POST', headers: H('application/json'), credentials: 'include', body: body });
    let t = await r.text(); if (!r.ok) throw new Error('email create HTTP ' + r.status + ' ' + t);
    const contentId = JSON.parse(t).id; if (!contentId) throw new Error('no content id in response: ' + t);
    console.log('%c    email content created ' + contentId, 'color:#22c55e');

    body = EMAIL_SAVE.split('%%EMAIL_HERO%%').join(heroUrl);
    r = await fetch(CS_BASE + '/' + contentId, { method: 'POST', headers: H('application/json'), credentials: 'include', body: body });
    t = await r.text(); if (!r.ok) throw new Error('email save HTTP ' + r.status + ' ' + t);
    console.log('    email content saved (subject + pre-header + body)');

    // 3. the journey, wired to the email that was just created
    const jid = await reserveId();
    console.log('    reserved ' + jid);
    const fill = (s) => s.split('%%RESERVED%%').join(jid)
                         .split('%%EMAIL_CONTENT_ID%%').join(contentId)
                         .split('%%NC_ICON%%').join(iconUrl)
                         .split('%%POPUP_BG%%').join(bgUrl);
    let createStr = fill(JOURNEY_CREATE), saveStr = fill(JOURNEY_SAVE);
    const map = idMap(createStr);
    createStr = applyMap(createStr, map); saveStr = applyMap(saveStr, map);

    r = await fetch(BASE + '/journey-drafts', { method: 'POST', headers: H('application/json'), credentials: 'include', body: createStr });
    t = await r.text(); if (!r.ok) throw new Error('journey create HTTP ' + r.status + ' ' + t);
    const numId = JSON.parse(t).id; if (!numId) throw new Error('no draft id in create response: ' + t);
    console.log('    draft created ' + numId);

    r = await fetch(BASE + '/journey-drafts/' + numId, { method: 'PUT', headers: H('application/json'), credentials: 'include', body: saveStr });
    t = await r.text(); if (!r.ok) throw new Error('draft ' + jid + ' created but save failed HTTP ' + r.status + ' ' + t);

    console.log('%cDONE — ' + jid + ' (draft ' + numId + '), email ' + contentId, 'color:#22c55e;font-weight:bold;font-size:14px');
    console.log('The draft is unpublished — review it in the Journeys UI, check the email renders, then publish.');
  } catch (e) {
    console.error('%cFAILED — ' + ((e && e.message) || e), 'color:#ef4444;font-weight:bold');
    console.error('Nothing was published. Fix the cause and rerun; delete any half-made draft first.');
  }
})();
"""


def build_js(bundle: dict) -> str:
    js = JS_TEMPLATE
    js = js.replace("@GENERATED_AT@", datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z"))
    js = js.replace("@JOURNEY_NAME@", bundle["journey_name"])
    js = js.replace("@BASE_URL@", json.dumps(DEFAULT_BASE_URL))
    js = js.replace("@BRAND@", json.dumps(BRAND))
    js = js.replace("@FOLDER_ID@", json.dumps(DEFAULT_FOLDER_ID))
    js = js.replace("@CAMPAIGN@", json.dumps(bundle["campaign"]["slug"]))
    js = js.replace("@HERO_URL@", json.dumps(bundle["campaign"]["image_url"]))
    for token, key in (
        ("@EMAIL_CREATE@", "email_create"),
        ("@EMAIL_SAVE@", "email_save"),
        ("@JOURNEY_CREATE@", "journey_create"),
        ("@JOURNEY_SAVE@", "journey_save"),
    ):
        js = js.replace(token, json.dumps(json.dumps(bundle[key], ensure_ascii=False), ensure_ascii=False))
    return js


def emit(bundle: dict, name: str) -> Path:
    out = HERE / "console_scripts"
    out.mkdir(exist_ok=True)
    path = out / f"{name}_console.js"
    path.write_text(build_js(bundle), encoding="utf-8")
    return path


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--campaign", required=True, help="liveapi campaign slug")
    p.add_argument("--spec", required=True, type=Path,
                   help="content sheet (tab-separated); '-' reads stdin")
    p.add_argument("--promo-link", default="",
                   help="randomizer promo URL (or bare slug) every channel links to. "
                        "Overrides the sheet's Link row.")
    p.add_argument("--stop-at", default="",
                   help="journey stop date (YYYY-MM-DD or YYYY-MM-DDTHH:MM, Chile local). "
                        "Defaults to the campaign's expiry.")
    p.add_argument("--name", default="sport_comms", help="output basename")
    p.add_argument("--dry-run", action="store_true",
                   help="write the prepared bodies to out/ instead of a console script")
    args = p.parse_args()

    campaign = load_campaign(args.campaign)
    spec = read_spec(args.spec, args.promo_link)
    bundle, report = prepare(campaign, spec, stop_at=args.stop_at)

    print("Sport scratch-card comms:")
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
        out = HERE / "out"
        out.mkdir(exist_ok=True)
        path = out / f"{args.name}_bodies.json"
        path.write_text(json.dumps(
            {k: bundle[k] for k in
             ("journey_create", "journey_save", "email_create", "email_save")},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nDry run — bodies written: {path}")
        return 0

    path = emit(bundle, args.name)
    print(f"\nConsole script written: {path}")
    print("Paste it into the DevTools console on a logged-in backoffice tab.")
    print("It asks for the notification icon and the pop-up background; the email")
    print("hero comes from the campaign card automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
