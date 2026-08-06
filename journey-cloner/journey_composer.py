#!/usr/bin/env python3
"""Journey Composer — build a REAL custom journey draft JSON from a chain spec.

This is the "AI creates journeys by itself" tool. Input is a chain of activity
types with per-node settings; output is a full POST /journey-drafts body
(activities[] + rawJourneyData mirror), assembled from REAL captured nodes in
templates/casino/gow.json and gow_comms.json — never invented shapes.

How it stays accurate (grounded in REA_BACKOFFICE_AND_JOURNEYS.md):
  * every activity is a deep-cloned captured node, with ALL its captured
    events, initializationData and editor mirror entry;
  * chain wiring uses each node's real "happy path" completion event; every
    other completion event routes to its own end_of_journey activity — exactly
    like the capture (which has 18 undrawn end_of_journey targets);
  * dependencies (CurrencyCode -> source, PromotionId -> promotion, ...) are
    rewired by role to the nearest upstream node of the same captured type;
  * external reference ids (promotionId, ContentId, templates, ...) are never
    touched; internal activity ids are freshly regenerated per node via the
    documented global-string-replace technique;
  * lineage (duplicatedFromId) and server-minted promotionDisplayId are
    stripped so the platform mints fresh ones.

Usage (AI or human):

  # 1. what can I chain, and which settings does each node take?
  python journey_composer.py options --json

  # 2. echo back the interpreted chain for confirmation ("you want this?")
  python journey_composer.py describe spec.json

  # 3. compose the real journey JSON -> out/<name>.journey.json
  python journey_composer.py compose spec.json --json

Spec example (the user's "active segment deposit freespins then wagering"):

  {
    "name": "JBCL | CS | Active seg | Dep -> 50FS -> Wager x30",
    "source": {"type": "segment"},
    "chain": [
      {"type": "promotion"},
      {"type": "deposit", "min_deposit": 1500000},
      {"type": "freespins", "spins": 50, "game": "lagrancopa"},
      {"type": "casino_bonus", "bonus_percent": 100, "wagering": 30}
    ],
    "date": "2026-08-01",
    "days": 1
  }

The composed JSON has reservedJourneyId left blank: creating it live is the
existing hand-off (console script / create_journeys.py machinery reserves a
JRN id and POSTs). This tool never calls the API.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TPL = HERE / "templates" / "casino"
OUT = HERE / "out"
CONSOLE_OUT = HERE / "console_scripts"     # shared with compose.py / the runner

GOW = TPL / "gow.json"
COMMS = TPL / "gow_comms.json"
DEFAULT_SEGMENT = TPL / "segment_cs_301.json"

# Every capture the library draws activity types from, in priority order: the
# first template containing a type supplies the canonical instance.
#
# The "one reference per journey, never mix" rule in COMPOSER_RULES.md is about
# compose.py's RECIPE model, which lifts a whole chain out of one capture and
# depends on that capture's shared shell. This composer works differently — it
# deep-clones each activity WITH its own mirror element, regenerates ids per
# node and rewires dependencies by role — so a node from a second capture is no
# more foreign than a second node from the first. Sport activities (freebet,
# registration) live only in the udch captures, and excluding them made every
# sport prize unbuildable.
SOURCES = (
    GOW,
    COMMS,
    HERE / "templates" / "udch" / "two_hours.json",     # freebet, registration
    HERE / "templates" / "udch" / "followup.json",      # multipurpose + freebet
)

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Known games (mirrors casino_journey.py GAMES — the only captured-valid tuples).
GAMES: dict[str, dict[str, str]] = {
    "lagrancopa": {
        "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
        "walletGameId": "gg_la_gran_copa_jugabet",
        "externalGameId": "gg_la_gran_copa_jugabet",
        "provider": "jugabet-games",
        "gameTranslationKey": "La Gran Copa Jugabet",
    },
    "spinandscoremegaways": {
        "lobbyGameId": "pragmatic-spin-score-megaways",
        "walletGameId": "vswaysfrywld",
        "externalGameId": "vswaysfrywld",
        "provider": "pragmatic",
        "gameTranslationKey": "Spin & Score Megaways",
    },
}

# The two entries above are legacy shorthands. The authoritative registry is
# library/games.json (106 games), the same file compose.py grounds against —
# hardcoding a two-game list here meant every other game was unbuildable.
GAMES_FILE = HERE / "library" / "games.json"
_GAME_FIELDS = ("lobbyGameId", "walletGameId", "externalGameId", "provider",
                "gameTranslationKey", "providerTranslationKey")


def _norm(s: str) -> str:
    """Loose key for name matching: 'La Gran Copa Jugabet' -> 'lagrancopajugabet'."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def _game_index() -> dict[str, dict[str, str]]:
    """Every way a brief might name a game -> that game's captured id tuple.
    Indexes lobbyGameId, each alias, and the display name, all normalised."""
    if not hasattr(_game_index, "_cache"):
        idx: dict[str, dict[str, str]] = {}
        for slug, entry in GAMES.items():          # legacy shorthands win ties
            idx[_norm(slug)] = dict(entry)
        try:
            registry = json.loads(GAMES_FILE.read_text(encoding="utf-8")).get("games") or {}
        except (OSError, ValueError):
            registry = {}
        for lobby_id, entry in registry.items():
            tup = {f: entry.get(f) for f in _GAME_FIELDS if entry.get(f)}
            if not tup.get("providerTranslationKey") and entry.get("provider"):
                tup["providerTranslationKey"] = " ".join(
                    w.capitalize() for w in str(entry["provider"]).replace("_", "-").split("-") if w)
            if not tup.get("lobbyGameId"):
                continue
            keys = [lobby_id, entry.get("gameTranslationKey"), *(entry.get("aliases") or [])]
            for k in keys:
                if k:
                    idx.setdefault(_norm(k), tup)
        _game_index._cache = idx
    return _game_index._cache


def resolve_game(name: str) -> dict[str, str]:
    """Resolve a brief's game name to its captured id tuple, or refuse.

    Previously an unknown game only warned and kept the reference template's
    game, so a journey would silently award spins on gow.json's own game under
    a fully green build. A game nobody can resolve is a plan with a hole."""
    idx = _game_index()
    hit = idx.get(_norm(name))
    if hit:
        return hit
    import difflib
    key = _norm(name)
    near = difflib.get_close_matches(key, list(idx), n=3, cutoff=0.6)
    # Briefs often use a short form ("Big Bass"), which scores too low for
    # difflib but is an unambiguous prefix/substring of the real title.
    if len(key) >= 4:
        near += [k for k in idx if key in k and k not in near][:5]
    suggestions = sorted({idx[n].get("gameTranslationKey") or n for n in near})[:5]
    raise SystemExit(
        f"unknown game {name!r} — not in {GAMES_FILE.name} ({len(idx)} lookup keys). "
        + (f"Did you mean: {suggestions}? " if suggestions else "")
        + "Refusing to keep the reference template's game, which would award "
          "spins on the wrong title.")

# chain-type aliases -> canonical captured activity key (every captured type)
ALIASES = {
    "csv": "dwh_source", "segment": "dwh_source", "dwh_source": "dwh_source",
    "api": "external_system_source", "external_system_source": "external_system_source",
    "promotion": "promotion",
    "drip": "multipurpose_promotion", "multipurpose_promotion": "multipurpose_promotion",
    "deposit": "deposit",
    "freespin": "freespin_bonus", "freespins": "freespin_bonus", "freespin_bonus": "freespin_bonus",
    "bonus": "casino_bonus_v2", "casino_bonus": "casino_bonus_v2", "wagering": "casino_bonus_v2",
    "casino_bonus_v2": "casino_bonus_v2",
    "notification": "notification_center#contract1", "nc": "notification_center#contract1",
    # The canonical activity name must resolve too. Without it a spec written
    # with the platform's own wire name — which is what the knowledge base and
    # MODE 1/2 output both use — was refused as an unknown chain type.
    "notification_center": "notification_center#contract1",
    "onsite": "notification_center#contract1",
    "popup": "notification_center#contract5",
    # The contract-suffixed wire names must round-trip too: plan_lint.py
    # normalises every plan to these before the composer sees it, so a plan that
    # linted clean was then refused as an unknown chain type.
    "notification_center#contract1": "notification_center#contract1",
    "notification_center#contract5": "notification_center#contract5",
    # Sport activities, available since the udch captures joined SOURCES.
    "freebet": "freebet", "free_bet": "freebet", "sport_freebet": "freebet",
    "sport_bonus": "sport_bonus", "sportbonus": "sport_bonus",
    "registration": "registration", "promocode": "registration",
    "reference_codes": "registration",
    "campaign_connector": "campaign_connector", "connector": "campaign_connector",
    "random_split": "random_split", "randomsplit": "random_split",
    "sms": "dextra_sms", "dextra_sms": "dextra_sms",
    "email": "dextra_email", "dextra_email": "dextra_email",
    "wait": "wait_interval", "wait_interval": "wait_interval",
    "event": "event_detector", "event_detector": "event_detector",
    "ncsplit": "notification_center_engagement_split",
    "notification_center_engagement_split": "notification_center_engagement_split",
    "emailsplit": "email_engagement_split", "email_engagement_split": "email_engagement_split",
    "decisionsplit": "ams_decision_split", "ams_decision_split": "ams_decision_split",
}
# Entry activities. `registration` (the backoffice's "Reference codes" node)
# fires PlayerAdded, an ACTIVATION — it starts a journey, it cannot sit in
# the middle of one, so it belongs here rather than among the chain types.
SOURCE_TYPES = {"dwh_source", "external_system_source", "registration"}

# The default forward completion event per node type — all are real captured
# events. Override per node with "follow": "<EventName>"; route other events
# into sub-chains with "branches": {"<EventName>": [ ...nodes ]}.
HAPPY = {
    "promotion": "PromotionAccepted",
    "multipurpose_promotion": "PromotionAccepted",
    "deposit": "DepositConditionSatisfied",
    "freespin_bonus": "FreespinBonusCollectingFinished",
    "casino_bonus_v2": "WageringBonusFinished",
    "notification_center#contract1": "NotificationSent",
    "notification_center#contract5": "NotificationSent",
    "dextra_sms": "SuccessSmsSend",
    "dextra_email": "SuccessEmailSend",
    "freebet": "PlayerFreebetUsed",
    "sport_bonus": "SportBonusFinished",
    "campaign_connector": "PlayerAddedToCampaign",
    "wait_interval": "WaitTimeCompleted",
    "event_detector": "DetectorSuccess",
    # splits: default to the captured "engaged" path; use follow/branches to
    # route the other paths (all path events are real captured Completions)
    "notification_center_engagement_split": "NCEngagementSplitPassedPath02",
    "email_engagement_split": "Path2",
    "ams_decision_split": "DecisionSplitPassedPath01",
}

# Artwork the operator will choose at paste time instead of naming a URL.
# A brief almost never carries a media-library URL — the images are files on the
# operator's desktop — so demanding a URL up front made every comms build stall
# on "artwork missing". Setting icon/image to PICK writes a sentinel that the
# emitted console script resolves by opening a file picker and uploading, then
# substitutes the real URL. It is not a way to skip the artwork: the script
# refuses to POST while any sentinel survives, so the captured campaign's
# picture can still never ship.
PICK_VALUES = {"pick", "@pick", "PICK", "upload", "@upload"}
PICK_PREFIX = "@@PICK:"
PICK_SUFFIX = "@@"
# What the picker calls each slot in the console prompt.
PICK_LABELS = {
    ("notification_center#contract1", "icon"): "NC ICON (the bell card artwork)",
    ("notification_center#contract1", "image"): "NC IMAGE",
    ("notification_center#contract5", "icon"): "POP-UP ICON",
    ("notification_center#contract5", "image"): "POP-UP BACKGROUND",
}
_pick_counter = [0]


# Authoring an email means creating a NEW content-studio content rather than
# pointing at an existing one — the flow comms_campaign.py proved: substitute the
# captured creative, create -> save -> publish at paste time, then repoint the
# journey's email activity at the id that comes back. The email's copy is not
# inline on the activity, which is why setting `template` alone can only ever
# reuse someone else's creative.
EMAIL_AUTHORING_KEYS = {"subject_es", "preheader_es", "heading", "hero", "desc_es",
                        "cta", "creative", "promo_page_id", "hero_link", "email_name"}
# The GOW creative's call to action is the hero image, wrapped in a link to a
# promo page. A campaign whose CTA is not a promo page (a game launch URL, say)
# sets hero_link instead and the whole href is replaced.
EMAIL_PROMO_HREF = "https://jugabet.cl/services/promo/offers/promoPage/@@PROMO_PAGE_ID@@"
# Filled by the console script once the content exists, exactly like the
# reserved journey id. Shared with email_content.py so both spell it the same.
EMAIL_CONTENT_ID_TOKEN = "@@EMAIL_CONTENT_ID@@"
EMAIL_HERO_TOKEN = "@@EMAIL_HERO_URL@@"
EMAIL_DESC_TOKEN = "@@EMAIL_DESC@@"
EMAIL_CTA_TOKEN = "@@EMAIL_CTA_URL@@"
EMAIL_LINK_TOKEN = "@@EMAIL_LINK@@"
# The captured creatives, and which slots each actually has. They are real
# captures, not a layout invented per campaign, so a setting the chosen creative
# has nowhere to put is a refusal — silently dropping it is how a brief's body
# copy "shipped" while the email showed only a picture.
EMAIL_CREATIVES = {
    # One uppercase heading line above a hero image that is itself the CTA.
    "hero_only": {"file": "gow_email.json",
                  "slots": {"heading", "hero"},
                  "what": "heading line + hero image (the copy lives in the image)"},
    # A text body, a hero image and a separate CTA button image.
    "text_body": {"file": "jbcl_tournament_email.json",
                  "slots": {"desc_es", "hero", "cta"},
                  "what": "text body + hero image + CTA button image"},
}
# Image slots a creative can leave for paste time, and what the picker calls them.
EMAIL_IMAGE_LABELS = {
    "@@EMAIL_HERO_URL@@": "the EMAIL HERO image",
    EMAIL_CTA_TOKEN: "the EMAIL CTA BUTTON image",
}


# Content Studio rejects these in a content name outright:
#   422 CONTENT_ERROR / RESTRICTED_SYMBOLS_IN_CONTENT_NAME
# Journey names here are pipe-separated ("JBCL | Torneo … | Comms"), and the
# default content name is derived from one, so every authored email 422'd at
# paste time — after the operator had already picked and uploaded four images.
EMAIL_NAME_FORBIDDEN = '*@#?|&<>"\'/'


def clean_email_name(raw: str) -> str:
    """A content name Content Studio will accept, as close to `raw` as possible."""
    # Mark the removals first: collapsing on "-" afterwards would also chew
    # through hyphens that were always there, turning 2026-08-01 into
    # "2026 - 08 - 01".
    sep = "\x00"
    out = "".join(sep if ch in EMAIL_NAME_FORBIDDEN else ch for ch in str(raw))
    out = re.sub(rf"\s*{sep}+\s*", " - ", out)
    return re.sub(r"[ \t]+", " ", out).strip(" -")


def _desc_to_html(text: str) -> str:
    """Blank-line-separated paragraphs -> the <br><br> form the creative uses.

    The operator's text is escaped: it comes from a spreadsheet cell, and a stray
    '<' or '&' would otherwise break the email body rather than show up in it.
    """
    escaped = (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    paras = [p.strip() for p in re.split(r"\n\s*\n", escaped.strip()) if p.strip()]
    return "\n<br><br>\n".join(p.replace("\n", " ") for p in paras)


def pick_email_creative(s: dict) -> str:
    """Which captured creative this email needs. Explicit wins; otherwise the one
    whose slots cover the settings given."""
    named = s.get("creative")
    if named:
        if named not in EMAIL_CREATIVES:
            raise SystemExit(f"dextra_email: unknown creative {named!r}. Known: "
                             + ", ".join(f"{k} ({v['what']})"
                                         for k, v in EMAIL_CREATIVES.items()))
        return named
    asked = {k for k in ("desc_es", "cta", "heading") if s.get(k)}
    fits = [k for k, v in EMAIL_CREATIVES.items() if asked <= v["slots"]]
    if not fits:
        raise SystemExit(
            f"dextra_email: no captured creative has slots for {sorted(asked)}. "
            + "; ".join(f"{k} has {sorted(v['slots'])}" for k, v in EMAIL_CREATIVES.items()))
    # Prefer the creative that uses the most of what was asked for, so a spec
    # giving desc_es does not land on the creative with no body.
    return max(fits, key=lambda k: len(asked & EMAIL_CREATIVES[k]["slots"]))


EMAIL_TEMPLATE_DIR = HERE / "templates" / "casino"
EMAIL_HEADING_TOKEN = "@@EMAIL_HEADING@@"
EMAIL_PROMO_PAGE_TOKEN = "@@PROMO_PAGE_ID@@"
# Authoring settings collected while the chain is applied; the content itself is
# built in compose(), which is where the journey name and date are known.
_email_authoring: list[dict] = []
# Set when a promotion node asks for its page tree to be cloned at paste time.
_promo_page_requested: list = []


def build_email_content(s: dict, journey_name: str, date_str: str,
                        report: list | None = None) -> dict:
    """The payload for POST .../content-studio/.../email/contents.

    Substitutes a captured creative rather than inventing HTML. Which slots exist
    depends on which creative: `hero_only` is a heading line above a hero image
    that is itself the CTA; `text_body` has a text body, a hero image and a
    separate CTA button image. Everything not substituted stays as captured.
    """
    from create_journeys import BRAND      # lazy, like every other cross-import here

    creative = pick_email_creative(s)
    spec_slots = EMAIL_CREATIVES[creative]
    content = json.loads((EMAIL_TEMPLATE_DIR / spec_slots["file"]).read_text(encoding="utf-8"))
    tpl_brand = str(content.get("brand") or "")
    if tpl_brand and BRAND and tpl_brand.upper() != str(BRAND).upper():
        raise SystemExit(
            f"dextra_email: the {creative} creative is {tpl_brand}'s and this run is "
            f"{BRAND}. Emailing {BRAND} players a {tpl_brand} creative is a brand swap, "
            f"not a substitution — capture a {BRAND} email and add it as a template, or "
            f"set `template` to an existing {BRAND} CSE id instead.")

    # A setting this creative cannot place would otherwise be dropped in silence,
    # which is how a brief's body copy "shipped" while the email showed a picture.
    unusable = sorted({k for k in ("heading", "desc_es", "cta") if s.get(k)}
                      - spec_slots["slots"])
    if unusable:
        raise SystemExit(
            f"dextra_email: the {creative} creative ({spec_slots['what']}) has nowhere to "
            f"put {unusable}. Pick a creative that does — "
            + "; ".join(f"{k}: {sorted(v['slots'])}" for k, v in EMAIL_CREATIVES.items()))

    if s.get("promo_page_id") and s.get("hero_link"):
        raise SystemExit("dextra_email: give either `promo_page_id` or `hero_link`, not "
                         "both — they set the same href.")
    if not s.get("promo_page_id") and not s.get("hero_link"):
        raise SystemExit(
            "dextra_email: authoring needs `promo_page_id` or `hero_link` — in these "
            "creatives the images ARE the call to action. Left unset that link ships "
            "dead. Use `promo_page_id` for a promo page, `hero_link` for any other "
            "destination (a game launch URL), or set `template` to point at an email "
            "content that already has what you want.")

    raw_name = s.get("email_name") or f"{journey_name} — {date_str}"
    content["name"] = clean_email_name(raw_name)
    if not content["name"]:
        raise SystemExit(f"dextra_email: {raw_name!r} leaves nothing usable as a content "
                         f"name once Content Studio's restricted symbols "
                         f"({EMAIL_NAME_FORBIDDEN}) are removed — set `email_name`.")
    if content["name"] != raw_name and report is not None:
        report.append(f"dextra_email: content name {raw_name!r} -> {content['name']!r} "
                      f"(Content Studio rejects {EMAIL_NAME_FORBIDDEN})")
    comp = content["translations"]["es"]["composition"]
    if s.get("subject_es"):
        comp["subject"] = s["subject_es"]
    if s.get("preheader_es"):
        comp["preHeader"] = s["preheader_es"]
    src = comp["body"]["source"]

    if "heading" in spec_slots["slots"]:
        src = src.replace(EMAIL_HEADING_TOKEN, str(s.get("heading") or "").strip())
    if "desc_es" in spec_slots["slots"]:
        if not s.get("desc_es"):
            raise SystemExit(
                f"dextra_email: the {creative} creative has a text body and no copy was "
                f"given for it. Set `desc_es`, or use the hero_only creative whose copy "
                f"lives in the image — an empty body would ship as a blank panel.")
        src = src.replace(EMAIL_DESC_TOKEN, _desc_to_html(s["desc_es"]))

    # The destination. hero_only bakes the promo path around a token; text_body
    # holds the whole href, so a promo page id has to be expanded into one.
    link = str(s.get("hero_link") or "")
    if EMAIL_LINK_TOKEN in src:
        if not link:
            link = f"https://jugabet.cl/services/promo/offers/promoPage/{s['promo_page_id']}"
        src = src.replace(EMAIL_LINK_TOKEN, link)
    elif link:
        if EMAIL_PROMO_HREF not in src:
            raise SystemExit("dextra_email: the captured creative's promo-page href has "
                             "changed shape — `hero_link` matched nothing, so the email "
                             "would keep the captured destination")
        src = src.replace(EMAIL_PROMO_HREF, link)
    else:
        src = src.replace(EMAIL_PROMO_PAGE_TOKEN, str(s["promo_page_id"]))

    # Images: a URL is substituted now, PICK is left for the script's file picker.
    for skey, token in (("hero", EMAIL_HERO_TOKEN), ("cta", EMAIL_CTA_TOKEN)):
        if token not in src:
            continue
        val = s.get(skey)
        if val and not is_pick_request(val):
            src = src.replace(token, str(val))
    comp["body"]["source"] = src

    bad = sorted({ch for ch in str(content.get("name") or "") if ch in EMAIL_NAME_FORBIDDEN})
    if bad:
        raise SystemExit(f"dextra_email: content name {content['name']!r} still contains "
                         f"{bad} — Content Studio rejects it with 422 at paste time, "
                         f"which is after the operator has uploaded the images.")
    left = sorted(set(re.findall(r"@@[A-Z_]+@@", json.dumps(content))))
    # The image tokens are filled at paste time after the upload; anything else
    # unresolved would ship as literal text in a real email.
    stray = [t for t in left if t not in EMAIL_IMAGE_LABELS]
    if stray:
        raise SystemExit(f"dextra_email: unresolved placeholders in the authored "
                         f"content: {stray}")
    return content


def _lang_suffix(name: str, lang: str) -> bool:
    """Does this captured variable name carry `lang` as its language suffix?

    A plain `lang in name` test silently mismatched: "des-en" contains "es"
    (the tail of "des"), so the Spanish pass overwrote every English
    description — the EN notification shipped the ES copy under a green build.
    The language is a suffix behind a delimiter, so match it as one.
    """
    return re.search(rf"(?:^|[^a-z]){lang}$", name) is not None


def is_pick_request(value) -> bool:
    return isinstance(value, str) and value.strip().lower() in {
        v.lower() for v in PICK_VALUES}


def pick_sentinel(label: str) -> str:
    """A unique token per slot: two nodes asking for artwork must not collide."""
    _pick_counter[0] += 1
    return f"{PICK_PREFIX}{_pick_counter[0]}|{label}{PICK_SUFFIX}"


def pick_slots(body: dict) -> list[dict]:
    """The artwork slots left for paste time, in the order they appear."""
    text = json.dumps(body, ensure_ascii=False)
    found: "OrderedDict[str, str]" = OrderedDict()
    for m in re.finditer(re.escape(PICK_PREFIX) + r"(\d+)\|(.*?)" + re.escape(PICK_SUFFIX),
                         text):
        found.setdefault(m.group(0), m.group(2))
    return [{"token": t, "label": lbl} for t, lbl in found.items()]


# Per-node settings the composer knows how to apply (documented for `options`).
SETTINGS_DOC = {
    "dwh_source": {"segment_file": "path to a captured dwh initializationData fragment (default segment_cs_301.json)"},
    "external_system_source": {"description": "free-text label shown on the API entry node"},
    "promotion": {"content_id": "ContentId of a promo page YOU built (gow_campaign.py / the GOW tab). "
                                "Without it the composer mints a fresh id, which owns no content tree, "
                                "so the offer card renders EMPTY",
                  "front_id": "FrontId of that same promo page — set it whenever you set content_id",
                  "promo_page": "\"clone\" copies the captured campaign's page tree onto this "
                                "draft's own freshly-minted ids at paste time, so the offer card "
                                "renders instead of being empty. It carries the captured words and "
                                "artwork — change them in the backoffice, or build the page in GOW "
                                "where the text rewrites live. Leave unset to keep the INCOMPLETE "
                                "warning and wire content_id/front_id yourself."},
    "deposit": {"min_deposit": "minimum deposit amount, platform minor units (all tiers set to this)",
                "timeout": "ISO-8601 window, e.g. P0Y0M1DT0H0M0S"},
    "freespin_bonus": {"spins": "free-spin count",
                       "spins_expiration_ms": "how long the spins stay usable, in "
                                              "milliseconds (24h = 86400000)",
                       "with_wagering": "false for an INSTANT bonus (no wagering "
                                        "grind, no casino_bonus follow-up node)",
                       "game": "game name, id or alias from library/games.json "
                               "(see the `games` key); unknown names are REFUSED",
                       "bet_amount": "currenciesConfig.CLP.betAmount (minor units)"},
    "freebet": {"amount": "free-bet value, platform MINOR units (3,000 CLP -> 300000)",
                "max_odds": "maximum odds the free bet can be used at",
                "expire_days": "days the free bet stays valid once issued"},
    "registration": {"promocode": "the promocode players redeem to enter"},
    "casino_bonus_v2": {"bonus_percent": "deposit-match %", "wagering": "wagering requirement (x)",
                        "release_multiplier": "releaseLimitMultiplier", "expiration_ms": "bonusExpirationTime in ms"},
    "notification_center#contract1": {"title_en/es, desc_en/es, caption_en/es": "on-site notification copy",
                                      "icon": "notification artwork: a URL, or PICK to choose the "
                                              "file when the script is pasted — set one, or the "
                                              "card shows the captured campaign's image",
                                      "link_en/es": "where the card sends the player",
                                      "deeplink": "app deeplink (defaults to link_es/link_en, so it "
                                                  "cannot keep the captured campaign's)"},
    "notification_center#contract5": {"title_en/es, desc_en/es, caption_en/es": "pop-up (Cat-fish) copy",
                                      "image": "pop-up background artwork: a URL, or PICK to choose "
                                               "the file when the script is pasted — set one, or the "
                                               "journey shows the captured campaign's picture",
                                      "link_en/es": "where the button sends the player. This template "
                                                    "holds ONE language-independent link, so en and es "
                                                    "write the same slot",
                                      "deeplink": "app deeplink (defaults to the link)"},
    "dextra_sms": {"text_en/es": "SMS body"},
    "dextra_email": {"template": "content-studio email id (e.g. CSE-0-14458) to point at as-is. "
                                 "Set this or the authoring settings below, or the journey emails "
                                 "the CAPTURED campaign's template — which the inherited-content "
                                 "check refuses to build",
                     "from_name": "from-line text (default: the reference's)",
                     "subject_es": "AUTHOR a new email content instead of reusing one: the "
                                   "subject line. Implies the create -> save -> publish flow, "
                                   "and the journey is repointed at the id it returns",
                     "preheader_es": "the pre-header line of the authored content",
                     "creative": "which captured creative: hero_only (heading + hero image, "
                                 "copy lives in the image) or text_body (text body + hero + "
                                 "CTA button image). Default: whichever fits the settings given",
                     "heading": "hero_only: the one uppercase heading line above the image",
                     "desc_es": "text_body: the email body. Blank lines separate paragraphs; "
                                "the text is escaped, so it cannot carry markup",
                     "cta": "text_body: the CTA button image — a URL, or PICK",
                     "hero": "hero image: a URL, or PICK to choose the file at paste time",
                     "promo_page_id": "the promo page the hero image links to — the captured "
                                      "creative's own CTA shape",
                     "hero_link": "use instead of promo_page_id when the CTA is not a promo "
                                  "page (a game launch URL): replaces the hero's href outright",
                     "email_name": "the content's name in Content Studio (default: derived from "
                                   "the journey name and date)"},
    "wait_interval": {"wait": "ISO-8601 duration, e.g. P0Y0M0DT1H0M0S"},
    "event_detector": {"(none)": "captured deposit-band watcher kept as-is"},
    "multipurpose_promotion": {"(none)": "captured choosable-flow drip kept as-is (see warning on compose)"},
    "notification_center_engagement_split": {"(none)": "branch with follow/branches on NCEngagementSplitPassedPath01..05"},
    "email_engagement_split": {"(none)": "branch with follow/branches on Path1..Path6"},
    "ams_decision_split": {"(none)": "branch with follow/branches on DecisionSplitPassedPath01..20/RemainderPath"},
}
# keys valid on every chain node, besides type + per-type settings
UNIVERSAL_KEYS = {"type", "follow", "branches", "parallel"}


# ── template library ─────────────────────────────────────────────────────────
def _akey(activity: dict) -> str:
    name = activity.get("activityName", "?")
    init = activity.get("initializationData") or {}
    if name == "notification_center" and "contract" in init:
        return f"{name}#contract{init['contract']}"
    return name


def load_library() -> dict:
    """Pick ONE canonical captured instance per activity type, with its mirror
    element, activitiesConfiguration entry, pathesConfiguration entry, and its
    captured outgoing edges keyed by eventName."""
    lib: dict[str, dict] = {}
    for path in SOURCES:
        body = json.loads(path.read_text(encoding="utf-8-sig"))
        raw = body["rawJourneyData"]
        els = raw["elements"]
        nodes = {e["id"]: e for e in els if "source" not in e}
        edges_by_src: dict[str, dict] = {}
        for e in els:
            if "source" in e:
                edges_by_src.setdefault(e["source"], {})[(e.get("data") or {}).get("eventName")] = e
        acfg = raw.get("activitiesConfiguration") or {}
        pcfg = raw.get("pathesConfiguration") or {}
        by_id = {a["activityId"]: a for a in body["activities"]}
        for a in body["activities"]:
            k = _akey(a)
            if k in lib:
                continue
            aid = a["activityId"]
            lib[k] = {
                "activity": a,
                "element": nodes.get(aid),
                "config": acfg.get(aid),
                "paths": pcfg.get(aid),
                "edges": edges_by_src.get(aid, {}),
                "captured_neighbors": by_id,   # to resolve captured dep targets
                "template": path.name,
            }
    # journey skeleton: gow.json top level (drop the graph, keep the envelope)
    skel = json.loads(GOW.read_text(encoding="utf-8-sig"))
    return {"types": lib, "skeleton": skel}


# ── cloning with fresh ids ───────────────────────────────────────────────────
def load_parallel_parts() -> dict | None:
    """The captured parallelFlow container and one flowEntry header.

    Parallel flows are the one structure that is not a plain activity: the owner
    activity's forward event carries `split.paths`, and the canvas gets a
    container element whose children are re-parented into it. Both pieces are
    CAPTURED in gow.json, so this clones them like everything else rather than
    synthesising canvas — synthesising is what produces blank drafts.

    Layout constants come from the capture: flows are columns 480px apart, the
    header sits 88px down, content starts at 208px.
    """
    if not hasattr(load_parallel_parts, "_cache"):
        parts = None
        try:
            els = json.loads(GOW.read_text(encoding="utf-8-sig"))["rawJourneyData"]["elements"]
            container = next(e for e in els if e.get("type") == "parallelFlow")
            entry = next(e for e in els
                         if e.get("type") == "flowEntry"
                         and e.get("parentNode") == container["id"])
            parts = {"container": container, "flow_entry": entry,
                     "col_step": 480, "header_y": 88, "content_y": 208}
        except (OSError, ValueError, StopIteration, KeyError):
            parts = None
        load_parallel_parts._cache = parts
    return load_parallel_parts._cache


def clone_with_fresh_id(entry: dict) -> dict:
    """Deep-clone a library node and swap its captured activityId for a fresh
    uuid4 via serialized string replace (ports/handles/config keys embed the id
    as a substring — the documented technique)."""
    old = entry["activity"]["activityId"]
    new = str(uuid.uuid4())
    blob = json.dumps({
        "activity": entry["activity"],
        "element": entry["element"],
        "config": entry["config"],
        "paths": entry["paths"],
    }, ensure_ascii=False).replace(old, new)
    out = json.loads(blob)
    # De-nest the lift (COMPOSER_RULES rule 3). load_library takes each element
    # straight out of its captured journey, and in gow_comms the comms nodes live
    # inside a parallelFlow container — so every cloned nc / pop-up / wait / split
    # arrived still pointing at a container this journey does not have. The editor
    # reads the missing parent's position and throws, which is a draft that saves
    # and then will not open. _wrap_parallel re-adds these when it really wraps.
    el = out.get("element")
    if isinstance(el, dict):
        el.pop("parentNode", None)
        el.pop("extent", None)
        if isinstance(el.get("data"), dict):
            el["data"].pop("parentNode", None)
    out["new_id"] = new
    out["captured_id"] = old
    return out


def make_end_of_journey(lib: dict) -> dict:
    """A fresh end_of_journey activity (undrawn, exactly like the capture's 18)."""
    tpl = lib["types"]["end_of_journey"]["activity"]
    a = copy.deepcopy(tpl)
    a["activityId"] = str(uuid.uuid4())
    return a


# ── settings appliers (edit activity init + mirror config) ───────────────────
_ISO_DUR_RE = re.compile(
    r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?"
    r"(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", re.IGNORECASE)


def _iso_duration_label(iso: str) -> str:
    """"P0Y0M1DT0H0M0S" -> "1 Days", matching the captured label style.

    The wait node stores its duration twice: waitPeriod (the value) and
    displayData (the caption the canvas prints). They have to agree.
    """
    m = _ISO_DUR_RE.match(str(iso or "").strip())
    if not m:
        return ""
    parts = [(int(g or 0), unit) for g, unit in
             zip(m.groups(), ("Years", "Months", "Days", "Hours", "Minutes", "Seconds"))]
    said = [f"{n} {unit}" for n, unit in parts if n]
    return " ".join(said) if said else "0 Minutes"


def _placements_of(holder: dict) -> list:
    """A promotion's placement list, from either storage.

    The compiled activity keeps it at initializationData.placements; the editor
    mirror keeps it one level deeper, under properties.placements. Both have to
    be written or the two storages disagree and the builder blanks the canvas.
    """
    if not isinstance(holder, dict):
        return []
    direct = holder.get("placements")
    if isinstance(direct, list):
        return direct
    nested = (holder.get("properties") or {}).get("placements")
    return nested if isinstance(nested, list) else []


def _apply_settings(kind: str, node: dict, s: dict, report: list, warnings: list) -> None:
    act = node["activity"]
    init = act.get("initializationData") or {}
    cfg = (node.get("config") or {}).get("data") if node.get("config") else None

    def note(field, old, newv):
        report.append(f"{kind}: {field}: {old!r} -> {newv!r}")

    if kind == "deposit":
        if "min_deposit" in s:
            for t in (init.get("depositConditions") or {}).get("minDepositAmounts", []):
                note("minDepositAmounts.amount", t.get("amount"), s["min_deposit"])
                t["amount"] = s["min_deposit"]
        if "timeout" in s:
            dc = init.get("depositConditions") or {}
            note("expirationTimeout", dc.get("expirationTimeout"), s["timeout"])
            dc["expirationTimeout"] = s["timeout"]
    elif kind == "freespin_bonus":
        fa = init.get("freespinActivity") or {}
        if "spins" in s:
            note("spins", fa.get("spins"), s["spins"]); fa["spins"] = s["spins"]
        if "game" in s:
            # resolve_game refuses an unresolvable name rather than leaving the
            # reference template's game in place under a green build.
            for k, v in resolve_game(str(s["game"])).items():
                note(k, fa.get(k), v); fa[k] = v
        if "spins_expiration_ms" in s:
            note("spinsExpirationDuration", fa.get("spinsExpirationDuration"), s["spins_expiration_ms"])
            fa["spinsExpirationDuration"] = s["spins_expiration_ms"]
        if "with_wagering" in s:
            # The instant-bonus marker: freespinActivity.withWagering false and
            # no wagering follow-up node. Without this setting an instant bonus
            # could only be expressed by omitting the casino_bonus_v2 node, and
            # the captured node's own withWagering=true survived into it.
            v = bool(s["with_wagering"])
            note("withWagering", fa.get("withWagering"), v); fa["withWagering"] = v
        if "bet_amount" in s:
            cc = (fa.get("currenciesConfig") or {}).get("CLP") or {}
            note("betAmount", cc.get("betAmount"), s["bet_amount"]); cc["betAmount"] = s["bet_amount"]
            if "betAmount_majorUnits" in cc:      # proven pipeline keeps both in sync
                cc["betAmount_majorUnits"] = int(s["bet_amount"]) // 100
    elif kind == "freebet":
        props = init.get("properties") or {}
        if "amount" in s:
            cur = props.get("freeBetAmount") or {}
            for ccy in (cur or {"CLP": None}):
                note(f"freeBetAmount.{ccy}", cur.get(ccy), s["amount"]); cur[ccy] = s["amount"]
            props["freeBetAmount"] = cur
        if "max_odds" in s:
            note("maxOdd", props.get("maxOdd"), s["max_odds"]); props["maxOdd"] = s["max_odds"]
        if "expire_days" in s:
            note("expireInDays", props.get("expireInDays"), s["expire_days"])
            props["expireInDays"] = s["expire_days"]
    elif kind == "registration":
        if "promocode" in s:
            # The captured entry node carries a real promocode (VAMOSBULLA);
            # leaving it is how another campaign's code reached a new journey.
            ps = init.get("promocodeSettings") or {}
            note("promocodeSettings.values", ps.get("values"), [s["promocode"]])
            ps["values"] = [s["promocode"]]
            init["displayData"] = [f"Promo codes: {s['promocode']}"]
    elif kind == "casino_bonus_v2":
        pairs = {"bonus_percent": "bonusPercent", "wagering": "wageringRequirement",
                 "release_multiplier": "releaseLimitMultiplier", "expiration_ms": "bonusExpirationTime"}
        for sk, fk in pairs.items():
            if sk in s:
                note(fk, init.get(fk), s[sk]); init[fk] = s[sk]
                wa = init.get("wageringActivity")
                if isinstance(wa, dict) and fk in wa:      # nested mirror
                    wa[fk] = s[sk]
    elif kind in ("notification_center#contract1", "notification_center#contract5"):
        # copy lives in objectForSend.variables AND singleChannel.localizedLanguagesTab
        # (contract1 keys: title-en/des-en/caption-en; contract5: title_en/description_en/caption_en)
        vars_ = (init.get("objectForSend") or {}).get("variables") or []
        tabs = (init.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
        # `link` matters as much as the copy: a captured card carries the OLD
        # campaign's promo-page URL, so a new journey silently linked players to
        # the previous promotion.
        keymap = {"title": "title", "desc": "des", "caption": "caption", "link": "link"}
        for skey, stem in keymap.items():
            for lang in ("en", "es"):
                val = s.get(f"{skey}_{lang}")
                if val is None:
                    continue
                hit = False
                for v in vars_:
                    n = (v.get("name") or "").lower()
                    if stem in n and _lang_suffix(n, lang):
                        note(v["name"], v.get("value"), val); v["value"] = val; hit = True
                for tab in tabs.values():
                    if not isinstance(tab, dict):
                        continue
                    for tk in tab:
                        tn = tk.lower()
                        if stem in tn and _lang_suffix(tn, lang):
                            tab[tk] = val; hit = True
                if not hit and skey == "link":
                    # The pop-up holds ONE language-independent `link` in the
                    # common tab (its buttons_1_link is the `%link%` indirection),
                    # so a per-language link matched nothing and the captured
                    # campaign's promo URL survived under a green build — the
                    # pop-up button sent players to the previous promotion.
                    for v in vars_:
                        if (v.get("name") or "").lower() == "link":
                            note(v["name"], v.get("value"), val); v["value"] = val; hit = True
                    for tab in tabs.values():
                        if isinstance(tab, dict) and "link" in tab:
                            tab["link"] = val; hit = True
                    if hit:
                        other = s.get(f"{skey}_{'es' if lang == 'en' else 'en'}")
                        if other is not None and other != val:
                            warnings.append(
                                f"{kind}: this template has a single language-independent "
                                f"`link`; link_en and link_es differ, so the last one "
                                f"written ({lang}) is what ships")
                if not hit:
                    warnings.append(f"{kind}: no captured variable matched {skey}_{lang}")
        # An unset deeplink is not a neutral omission: it is the captured
        # campaign's own in-app URL, so a player tapping the card in the app
        # landed on the previous promotion while the web link was correct.
        # Brief give one destination, so fall back to the link rather than keep
        # the reference's — and report it, since it was not asked for explicitly.
        if "deeplink" not in s:
            fallback = s.get("link_es") or s.get("link_en")
            if fallback:
                s = dict(s, deeplink=fallback)
                report.append(f"{kind}: deeplink not given — using the link "
                              f"({fallback}) so it cannot keep the captured campaign's")
        # Language-independent fields, held once in the `common` tab.
        for skey, stems in (("icon", ("icon",)),
                            # the pop-up's artwork is a background image, not an
                            # icon — a chain that set only `icon` still shipped
                            # the captured campaign's picture
                            ("image", ("background_image_src", "backgroundimagesrc")),
                            ("deeplink", ("deeplink",))):
            val = s.get(skey)
            if val is None:
                continue
            if is_pick_request(val):
                val = pick_sentinel(PICK_LABELS.get((kind, skey), f"{kind} {skey}"))
            for v in vars_:
                if (v.get("name") or "").lower() in stems:
                    note(v["name"], v.get("value"), val); v["value"] = val
            for tab in tabs.values():
                if isinstance(tab, dict):
                    for tk in list(tab):
                        if tk.lower() in stems:
                            tab[tk] = val
    elif kind == "dextra_email":
        # The email node is copied whole, so without this it keeps the captured
        # campaign's template — and the inherited-content guard (rightly) refuses
        # to build a comms journey that would email players the old promotion.
        es = init.get("emailSettings") or {}
        authoring = sorted(EMAIL_AUTHORING_KEYS & set(s))
        if authoring and "template" in s:
            raise SystemExit(
                f"dextra_email: `template` points at an existing content while "
                f"{authoring} author a new one — pick one. Reusing CSE "
                f"{s['template']} means the copy in this spec is ignored; "
                f"authoring means that content is left untouched.")
        if authoring:
            # The real id only exists once the script has created the content, so
            # leave the token here and let it be swapped in — the same handling
            # the journey's own reserved id gets.
            _email_authoring.append({k: s[k] for k in EMAIL_AUTHORING_KEYS if k in s})
            tpl = es.get("template") or {}
            note("emailSettings.template.id", tpl.get("id"), EMAIL_CONTENT_ID_TOKEN)
            tpl["id"] = EMAIL_CONTENT_ID_TOKEN
            es["template"] = tpl
            es["emailSource"] = "Template"
            init["displayData"] = [EMAIL_CONTENT_ID_TOKEN]
        elif "template" in s and es:
            tpl = es.get("template") or {}
            note("emailSettings.template.id", tpl.get("id"), s["template"])
            tpl["id"] = s["template"]
            es["template"] = tpl
            # displayData is what the builder shows on the card; leaving the old
            # id there is how a reviewer sees the wrong template name.
            init["displayData"] = [str(s["template"])]
        if "from_name" in s and es:
            note("emailSettings.fromLineText", es.get("fromLineText"), s["from_name"])
            es["fromLineText"] = s["from_name"]
    elif kind == "dextra_sms":
        for lang in ("en", "es"):
            val = s.get(f"text_{lang}")
            if val is None:
                continue
            for holder in (init.get("rawValues"), init.get("smsSettings")):
                if not isinstance(holder, dict):
                    continue
                if lang == "en" and "messageText" in holder:
                    note("messageText", holder["messageText"], val); holder["messageText"] = val
                # localizedMessageTexts appears in BOTH captured shapes:
                #   rawValues:   {"en": {messageText,...}, "es": {...}}   (dict by lang)
                #   smsSettings: [{messageText, languageCode}, ...]       (list)
                loc = holder.get("localizedMessageTexts")
                if isinstance(loc, dict):
                    for k in list(loc):
                        if k.lower() != lang:
                            continue
                        if isinstance(loc[k], dict) and "messageText" in loc[k]:
                            note(f"localizedMessageTexts.{k}.messageText", loc[k]["messageText"], val)
                            loc[k]["messageText"] = val
                        else:
                            note(f"localizedMessageTexts.{k}", loc[k], val)
                            loc[k] = val
                elif isinstance(loc, list):
                    for item in loc:
                        if isinstance(item, dict) and str(item.get("languageCode", "")).lower() == lang:
                            note(f"localizedMessageTexts[{lang}].messageText", item.get("messageText"), val)
                            item["messageText"] = val
        # displayData is the label the builder prints on the card. Same reason as
        # the email node: left alone, a reviewer opening the draft reads the
        # PREVIOUS campaign's SMS next to this campaign's correct messageText.
        body_text = s.get("text_es") or s.get("text_en")
        if body_text and isinstance(init.get("displayData"), list):
            note("displayData", init["displayData"], [body_text])
            init["displayData"] = [body_text]
    elif kind == "promotion":
        if str(s.get("promo_page") or "").strip().lower() == "clone":
            _promo_page_requested.append(True)
        # Point the offer card at a promo page the operator actually built.
        # Every promotion-bearing capture carries a promo-page placement
        # (ContentId + FrontId). Left as captured, the draft shares the captured
        # campaign's content tree and editing it rewrites that live page; minted
        # fresh, it owns a tree that does not exist yet and the card renders
        # empty. Building that tree needs the promo-page flow in
        # gow_campaign.py (per-target folder copies with role-specific
        # fileFilters, an S3 copy and manifest rewrites) which the composer does
        # not have — so the correct path is: build the page there, then pass its
        # two ids here.
        full_cfg = node.get("config") or {}
        for src_key, dest_key, meta_key in (("content_id", "ContentId", "contentId"),
                                            ("front_id", "FrontId", "frontId")):
            if src_key not in s:
                continue
            val = str(s[src_key])
            n = 0
            # THREE places hold this id and all three must agree, or the two
            # storages disagree and the builder shows a blank canvas:
            #   1. activity.initializationData.placements[].data.<PascalCase>
            #   2. config.properties.placements[].data.<PascalCase>  (a SIBLING
            #      of config.data, not inside it — the trap that made an earlier
            #      pass write only the compiled copy)
            #   3. config.metadata.<camelCase>
            for holder in (init, full_cfg):
                for placement in _placements_of(holder):
                    data = placement.get("data")
                    if isinstance(data, dict) and dest_key in data:
                        note(f"placements[].{dest_key}", data.get(dest_key), val)
                        data[dest_key] = val
                        n += 1
            meta = full_cfg.get("metadata")
            if isinstance(meta, dict) and meta_key in meta:
                note(f"metadata.{meta_key}", meta.get(meta_key), val)
                meta[meta_key] = val
                n += 1
            if not n:
                warnings.append(f"promotion: {src_key} given but no placement or "
                                f"metadata carries {dest_key} — nothing was set")

    elif kind == "wait_interval":
        if "wait" in s:
            note("waitPeriod", init.get("waitPeriod"), s["wait"]); init["waitPeriod"] = s["wait"]
            # displayData is the label the BUILDER PRINTS ON THE NODE, and it is
            # a separate copy of the value — writing only waitPeriod left every
            # composed wait captioned with the capture's own "2 Hours", so a
            # 1-day wait read as 2 hours on the canvas and the operator had no
            # way to see the real duration without opening the node.
            label = _iso_duration_label(s["wait"])
            if label:
                note("displayData", init.get("displayData"), [label])
                init["displayData"] = [label]
                if cfg is not None and "displayData" in cfg:
                    cfg["displayData"] = [label]
    elif kind == "external_system_source":
        if "description" in s:
            note("description", init.get("description"), s["description"])
            init["description"] = s["description"]
            if cfg is not None and "description" in cfg:
                cfg["description"] = s["description"]
    elif kind == "dwh_source":
        frag_path = Path(s.get("segment_file") or DEFAULT_SEGMENT)
        if not frag_path.is_absolute():
            frag_path = HERE / frag_path
        frag = json.loads(frag_path.read_text(encoding="utf-8-sig"))
        for k in ("filterDetails", "currentTemplate", "dataSourceName"):
            if k in frag:
                init[k] = frag[k]
                if cfg is not None and k in cfg:    # keep the editor mirror in sync
                    cfg[k] = copy.deepcopy(frag[k])
        report.append(f"dwh_source: segment <- {frag_path.name} "
                      f"({(frag.get('currentTemplate') or {}).get('name')!r})")

    # DUAL STORAGE: the editor mirror keeps its own copy of the activity config,
    # and the setters above edit only initializationData. Without this sync the
    # journey RUNS with the new copy while the builder still SHOWS the captured
    # campaign's — the notification content set on a wheel-prize journey landed
    # on the activity and left "🏆 La Gran Copa JugaBet" in the mirror.
    if cfg is not None:
        for mirror_key in list(cfg.keys()):
            if mirror_key in init:
                cfg[mirror_key] = copy.deepcopy(init[mirror_key])
    # displayData is the label the builder prints on the node, and it lives at
    # the mirror entry's TOP level, a sibling of `data` — so the loop above never
    # reached it and a renamed promocode still showed "Promo codes: VAMOSBULLA".
    conf = node.get("config")
    if isinstance(conf, dict):
        for top_key in ("displayData",):
            if top_key in conf and top_key in init:
                conf[top_key] = copy.deepcopy(init[top_key])

    # Unknown keys are REFUSED, not warned about. A warning here meant a spec
    # that nested its values under "settings", or used a recipe knob name like
    # spin_bet_clp instead of bet_amount, composed cleanly and shipped the
    # captured template's own values — 50 spins on La Gran Copa when the brief
    # asked for 30 on Big Bass, "VERIFIED OK", exit 0.
    known = {
        "deposit": {"min_deposit", "timeout"},
        "freespin_bonus": {"spins", "game", "bet_amount", "with_wagering",
                           "spins_expiration_ms"},
        "freebet": {"amount", "max_odds", "expire_days"},
        "registration": {"promocode"},
        "casino_bonus_v2": {"bonus_percent", "wagering", "release_multiplier", "expiration_ms"},
        "notification_center#contract1": {f"{a}_{l}" for a in ("title", "desc", "caption", "link") for l in ("en", "es")} | {"icon", "image", "deeplink"},
        "notification_center#contract5": {f"{a}_{l}" for a in ("title", "desc", "caption", "link") for l in ("en", "es")} | {"icon", "image", "deeplink"},
        "promotion": {"content_id", "front_id"},
        "promotion": {"content_id", "front_id", "promo_page"},
        "dextra_sms": {"text_en", "text_es"},
        "dextra_email": {"template", "from_name"} | EMAIL_AUTHORING_KEYS,
        "wait_interval": {"wait"},
        "external_system_source": {"description"},
        "dwh_source": {"segment_file"},
    }.get(kind, set())
    bad = [k for k in s if k not in known and k not in UNIVERSAL_KEYS]
    if bad:
        hint = ""
        if "settings" in bad:
            hint = (" — put settings INLINE on the node "
                    '({"type": "freespins", "spins": 30}), not nested under a '
                    '"settings" key')
        raise SystemExit(
            f"{kind}: unsupported setting(s) {sorted(bad)}{hint}. "
            f"Known for this activity: {sorted(known)} (plus {sorted(UNIVERSAL_KEYS)}). "
            f"Refusing to build — an ignored setting ships the captured "
            f"template's own value instead of the one you asked for.")


# ── the composer ─────────────────────────────────────────────────────────────
def compose(spec: dict) -> dict:
    lib = load_library()
    types = lib["types"]
    report: list[str] = []
    warnings: list[str] = []
    _pick_counter[0] = 0     # per-build, so the same spec yields the same tokens
    _email_authoring.clear()
    _promo_page_requested.clear()

    # resolve source
    src_spec = spec.get("source") or {}
    src_kind = ALIASES.get(str(src_spec.get("type", "")).lower())
    if src_kind not in SOURCE_TYPES:
        raise SystemExit(f"source.type must be one of csv/segment/api, got {src_spec.get('type')!r}")
    chain_specs = spec.get("chain") or []
    # A spec often ends with an explicit terminal because that is how MODE 1/2
    # writes the flow out ("... -> freespins -> end_of_journey"). The composer
    # appends the terminal itself, so an explicit one is redundant, not wrong —
    # refusing it made the model rewrite a correct chain to fix a non-problem.
    _TERMINALS = {"end", "end_of_journey", "end_of_path", "exit", "endofjourney"}
    while chain_specs and str((chain_specs[-1] or {}).get("type", "")).lower() in _TERMINALS:
        chain_specs = chain_specs[:-1]
    if not chain_specs:
        raise SystemExit("chain must have at least one node")

    def resolve_kind(c: dict) -> str:
        k = ALIASES.get(str(c.get("type", "")).lower())
        if k is None or k in SOURCE_TYPES:
            raise SystemExit(f"unknown chain node type {c.get('type')!r}. Known: "
                             + ", ".join(sorted(set(ALIASES) - {'csv', 'segment', 'api'})))
        if k not in types:
            raise SystemExit(f"{k} has no captured template node — cannot compose it accurately")
        return k

    src = clone_with_fresh_id(types[src_kind])
    _apply_settings(src_kind, src, src_spec, report, warnings)

    ends: list[dict] = []

    def fresh_end() -> str:
        e = make_end_of_journey(lib)
        ends.append(e)
        return e["activityId"]

    # placed: every chain/branch node with its upstream context for dep rewiring
    # entry: {kind, node, upstream: [(kind,new_id),...], col, row}
    placed: list[dict] = []
    edges_wanted: list[tuple] = []     # (node_entry|"src", event, target_id)
    exits_drawn: list[tuple] = []      # (end_id, col, row)
    parallel_blocks: list[dict] = []   # filled by build_level, drawn after layout
    col_counter = [0]

    def completion_events(kind: str) -> set:
        return {e["eventName"] for e in types[kind]["activity"].get("events", [])
                if e.get("eventType") == "Completion"}

    def build_level(specs: list[dict], upstream: list[tuple], row: int) -> str:
        """Clone+wire one chain level; returns the head node's new id."""
        # A branch that is only a terminal — "branches": {"...Path01":
        # [{"type": "end_of_path"}]} — is how both the planner and the operator
        # say "this path just ends", and the composer already ends every level
        # with its own terminal. Strip them here as well as on the top-level
        # chain, or that spelling is refused as an unknown chain type.
        specs = [c for c in specs
                 if str((c or {}).get("type", "")).lower() not in _TERMINALS]
        level: list[dict] = []
        for c in specs:
            k = resolve_kind(c)
            node = clone_with_fresh_id(types[k])
            _apply_settings(k, node, c, report, warnings)
            if k == "multipurpose_promotion":
                warnings.append("multipurpose_promotion: choosable-flow sub-elements are not "
                                "re-drawn; open the draft in the editor to verify the flows")
            level.append({"kind": k, "node": node, "spec": c})

        term = fresh_end()
        col0 = col_counter[0]
        for i, entry in enumerate(level):
            k, node, c = entry["kind"], entry["node"], entry["spec"]
            comp = completion_events(k)
            follow = c.get("follow") or HAPPY.get(k)
            if follow not in comp:
                raise SystemExit(f"{k}: follow event {follow!r} is not a captured Completion "
                                 f"event (captured: {sorted(comp)})")
            branches = c.get("branches") or {}
            for bev in branches:
                if bev not in comp:
                    raise SystemExit(f"{k}: branch event {bev!r} is not a captured Completion "
                                     f"event (captured: {sorted(comp)})")
                if bev == follow:
                    raise SystemExit(f"{k}: event {bev!r} cannot be both follow and branch")

            node_upstream = upstream + [(e["kind"], e["node"]["new_id"]) for e in level[:i + 1]]
            placed.append({"kind": k, "node": node, "upstream": node_upstream[:-1],
                           "col": col_counter[0], "row": row})
            col_counter[0] += 1

            nxt = level[i + 1]["node"]["new_id"] if i + 1 < len(level) else term
            branch_heads = {bev: build_level(bspecs, node_upstream, row + 1 + list(branches).index(bev))
                            for bev, bspecs in branches.items()}

            # PARALLEL: the follow event fans out into N simultaneous flows via
            # split.paths instead of a single nextActivityId. Each flow is an
            # ordinary chain; the wrap into a container element happens after
            # layout, in _wrap_parallel().
            parallel_specs = c.get("parallel") or []
            parallel_plan = None
            if parallel_specs:
                if not isinstance(parallel_specs, list) or not all(
                        isinstance(f, list) and f for f in parallel_specs):
                    raise SystemExit(
                        f"{k}: `parallel` must be a list of flows, each a non-empty "
                        f"list of chain nodes — e.g. "
                        f'"parallel": [[{{"type":"freespins","spins":100}}], [...], [...]]')
                if branches:
                    raise SystemExit(
                        f"{k}: use either `branches` (one event each) or `parallel` "
                        f"(one event, simultaneous flows), not both on one node.")
                flows = []
                for fi, fspecs in enumerate(parallel_specs):
                    head = build_level(fspecs, node_upstream, row + 1 + fi)
                    flows.append({"flow_id": str(uuid.uuid4()), "head": head,
                                  "path_id": fi + 1, "name": f"Flow {fi + 1}"})
                parallel_plan = {"owner": entry, "event": follow, "flows": flows, "after": nxt}
                parallel_blocks.append(parallel_plan)

            for ev in node["activity"].get("events", []):
                # A captured node can arrive with `split` already on one of its
                # events — the original journey's parallel block. Its flowIds and
                # nextActivityIds point at nodes that do not exist here, so it is
                # a dangling reference on every event we are not fanning out on.
                if not (parallel_plan and ev.get("eventName") == follow):
                    ev.pop("split", None)
                if ev.get("eventType") != "Completion":
                    ev.pop("nextActivityId", None)      # boundary events carry no next
                    continue
                en = ev.get("eventName")
                if en == follow and parallel_plan:
                    # The capture keeps nextActivityId alongside split; the split
                    # is what the engine fans out on.
                    ev["split"] = {"paths": [
                        {"pathId": f["path_id"], "pathName": f["name"],
                         "flowId": f["flow_id"], "nextActivityId": f["head"]}
                        for f in parallel_plan["flows"]]}
                    ev["nextActivityId"] = parallel_plan["flows"][0]["head"]
                elif en == follow:
                    ev["nextActivityId"] = nxt
                    edges_wanted.append((entry, en, nxt))
                elif en in branch_heads:
                    ev["nextActivityId"] = branch_heads[en]
                    edges_wanted.append((entry, en, branch_heads[en]))
                else:
                    ev["nextActivityId"] = fresh_end()  # undrawn end, like the capture
        exits_drawn.append((term, col0 + len(level), row))
        # Nothing but terminals: the branch routes straight to its end node.
        return level[0]["node"]["new_id"] if level else term

    head_id = build_level(chain_specs, [(src_kind, src["new_id"])], 0)

    # source activation -> chain head
    for ev in src["activity"].get("events", []):
        if ev.get("eventType") == "Activation":
            ev["nextActivityId"] = head_id

    # ── dependency rewiring by role (upstream-aware, branch-aware) ──
    def rewire_deps(entry: dict) -> None:
        k, node = entry["kind"], entry["node"]
        cap_neighbors = types[k]["captured_neighbors"]
        act = node["activity"]
        ups = entry["upstream"]
        for dep_list_key in ("dependencies", "dataDependencies"):
            deps = act.get(dep_list_key)
            if not isinstance(deps, list):
                continue
            kept = []
            for d in deps:
                if not isinstance(d, dict) or "journeyActivityId" not in d:
                    kept.append(d)
                    continue
                tgt_cap = cap_neighbors.get(d["journeyActivityId"])
                role = _akey(tgt_cap) if tgt_cap else None
                if role in SOURCE_TYPES:
                    d["journeyActivityId"] = src["new_id"]
                    kept.append(d)
                    continue
                up = next((uid for un, uid in reversed(ups) if un == role), None)
                if up:
                    d["journeyActivityId"] = up
                    kept.append(d)
                else:
                    warnings.append(
                        f"{k}: dropped dependency {d.get('key')!r} -> {role or 'unknown'} "
                        f"(no upstream {role} in this chain; the platform may reject if it is required)")
            act[dep_list_key] = kept

    for entry in placed:
        rewire_deps(entry)

    # ── mirror: elements, edges, configs ──
    elements: list[dict] = []
    X0, XSTEP, Y0, YSTEP = 120, 420, 300, 260

    def put(el: dict | None, col: int, row: int, kind: str) -> None:
        if not el:
            warnings.append(f"{kind}: captured node had no mirror element; left undrawn")
            return
        pos = {"x": X0 + col * XSTEP, "y": Y0 + row * YSTEP}
        el["position"] = dict(pos)
        el["positionAbsolute"] = dict(pos)
        # Drop the capture's own grouping. 13 of the 24 fragments were extracted
        # from inside a parallelFlow container, so their node carries that
        # container's id in parentNode (+ extent "parent"). The container is not
        # a fragment and is never emitted, so keeping the reference leaves the
        # node parented to a node that does not exist and the builder renders a
        # grey/blank canvas. No valid capture has a dangling parentNode.
        # This composer lays out a FLAT canvas here; the parallel-block code
        # below is the only legitimate re-parenting and it sets both keys itself,
        # after this call.
        el.pop("parentNode", None)
        el.pop("extent", None)
        elements.append(el)

    put(src.get("element"), 0, 0, src_kind)
    for entry in placed:
        put(entry["node"].get("element"), entry["col"] + 1, entry["row"], entry["kind"])
    for end_id, col, row in exits_drawn:
        elements.append({
            "id": end_id,
            "data": {"name": "end_of_journey", "ports": [{"id": f"input-{end_id}"}],
                     "width": 40, "height": 40},
            "type": "exit", "style": {}, "width": 40, "height": 40, "hidden": False, "zIndex": 2,
            "position": {"x": X0 + (col + 1) * XSTEP, "y": Y0 + row * YSTEP},
            "selected": False, "draggable": True, "connectable": True,
            "positionAbsolute": {"x": X0 + (col + 1) * XSTEP, "y": Y0 + row * YSTEP},
        })

    def names_raw(k: str) -> str:
        return k.split("#", 1)[0]

    def make_edge(sid: str, src_kind_: str, ev_name: str, tgt_id: str) -> dict:
        # prefer the node's own captured edge for this event; else any captured
        # edge with the event; else synthesize the minimal captured edge shape
        cap = types[src_kind_]["edges"].get(ev_name)
        if cap is None:
            for t in types.values():
                if ev_name in t["edges"]:
                    cap = t["edges"][ev_name]
                    break
        if cap is not None:
            blob = json.dumps(cap, ensure_ascii=False)
            blob = blob.replace(cap["source"], sid).replace(cap["target"], tgt_id)
            e = json.loads(blob)
            e["id"] = str(uuid.uuid4())
            return e
        return {
            "id": str(uuid.uuid4()),
            "data": {"isHidden": False, "eventName": ev_name, "eventType": "Completion",
                     "activityName": names_raw(src_kind_), "isLabelHidden": True,
                     "isReconnectable": False, "eventDisplayName": ev_name,
                     "isDisconnectable": False, "canBeUsedInChoosableFlow": False},
            "type": "default", "style": {}, "hidden": False,
            "source": sid, "target": tgt_id, "zIndex": 1,
            "sourceHandle": f"{ev_name}-{sid}", "targetHandle": f"input-{tgt_id}",
        }

    def port_edge(sid: str, tgt_id: str, source_handle: str, activity_name: str,
                  event_name: str = "") -> dict:
        """An edge whose source port is NOT an event handle — the container and
        flowEntry connectors, which hang off named ports instead."""
        return {
            "id": str(uuid.uuid4()),
            "data": {"isHidden": False, "eventName": event_name,
                     "eventType": "Completion" if event_name else None,
                     "activityName": activity_name, "isLabelHidden": True,
                     "isReconnectable": False, "eventDisplayName": event_name,
                     "isDisconnectable": False, "canBeUsedInChoosableFlow": False},
            "type": "default", "style": {"strokeDasharray": "3"}, "hidden": False,
            "source": sid, "target": tgt_id, "zIndex": 1,
            "sourceHandle": source_handle, "targetHandle": f"input-{tgt_id}",
            "labelBgPadding": [10, 3], "labelBgBorderRadius": 4,
            "labelStyle": {"color": "#000", "fontSize": 14, "fontWeight": 700},
            "labelBgStyle": {"fill": "#D2D2D2"},
        }

    act_ev = next((e["eventName"] for e in src["activity"].get("events", [])
                   if e.get("eventType") == "Activation"), "PlayerAdded")
    elements.append(make_edge(src["new_id"], src_kind, act_ev, head_id))
    for entry, ev_name, tgt in edges_wanted:
        elements.append(make_edge(entry["node"]["new_id"], entry["kind"], ev_name, tgt))

    # ── split handles ────────────────────────────────────────────────────────
    # A split node names its canvas handles `path1..pathN` / `other`, NOT after
    # the event (`NCEngagementSplitPassedPath02`, `Path2`, …) the way every other
    # node does. On top of that the captured fragment only kept the ports it
    # happened to have wired — `input`, `path1`, `other` — so an edge off any
    # path but the first pointed at a handle the node did not expose and the
    # canvas dropped it.
    #
    # Rewrite the handle to the platform's own naming and mint the port when it
    # is missing. Without this a comms chain can only ever branch on path 1,
    # which is not the branch the captures actually take.
    def _split_path_no(ev: str) -> str | None:
        """`NCEngagementSplitPassedPath02` -> 'path2'; a remainder -> 'other'."""
        if not ev:
            return None
        if re.search(r"remainder", ev, re.I):
            return "other"
        m = re.search(r"(?:path)0*(\d+)$", ev, re.I)
        return f"path{int(m.group(1))}" if m else None

    node_by_id = {e["id"]: e for e in elements if "source" not in e}
    for e in elements:
        if "source" not in e:
            continue
        node = node_by_id.get(e["source"])
        if not node:
            continue
        if "split" not in str((node.get("data") or {}).get("name") or ""):
            continue
        handle = _split_path_no((e.get("data") or {}).get("eventName"))
        if not handle:
            continue
        e["sourceHandle"] = f"{handle}-{e['source']}"
        ports = (node.setdefault("data", {})).setdefault("ports", [])
        if not any(p.get("id") == e["sourceHandle"] for p in ports):
            ports.append({"id": e["sourceHandle"]})

    # ── wrap parallel blocks: container element + flowEntry headers ──
    # Done AFTER layout so each flow is laid out as an ordinary chain first and
    # then re-parented, rather than teaching the grid about nested coordinates.
    for block in parallel_blocks:
        parts = load_parallel_parts()
        if not parts:
            warnings.append("parallel: gow.json has no captured parallelFlow container; "
                            "flows are wired in the activities but not drawn")
            continue
        by_id = {e["id"]: e for e in elements if "source" not in e}
        owner_id = block["owner"]["node"]["new_id"]
        cont = copy.deepcopy(parts["container"])
        cont_id = str(uuid.uuid4())
        cont["id"] = cont_id
        cont["data"] = dict(cont.get("data") or {})
        cont["data"]["ports"] = [{"id": f"input-{cont_id}"},
                                 {"id": f"parallel-flow-output-{cont_id}"}]
        # Collect each flow's elements: its head plus everything downstream of it
        # that layout put on the same row.
        flow_members: list[list[dict]] = []
        for flow in block["flows"]:
            head_el = by_id.get(flow["head"])
            row = next((e["row"] for e in placed
                        if e["node"]["new_id"] == flow["head"]), None)
            members = [by_id[e["node"]["new_id"]] for e in placed
                       if e["row"] == row and e["node"]["new_id"] in by_id] if row is not None else []
            if head_el and head_el not in members:
                members.insert(0, head_el)
            flow_members.append(members)

        col_step, header_y, content_y = parts["col_step"], parts["header_y"], parts["content_y"]
        base_x, base_y = 120, 300 + 260 * (max(
            (e["row"] for e in placed), default=0) + 1)
        cont["position"] = {"x": base_x, "y": base_y}
        cont["positionAbsolute"] = dict(cont["position"])
        cont["width"] = cont["data"]["width"] = max(col_step * len(block["flows"]) + 120, 600)
        cont["height"] = cont["data"]["height"] = 602
        cont["style"] = {"width": f"{cont['width']}px", "cursor": "pointer",
                         "height": f"{cont['height']}px"}
        elements.append(cont)

        for fi, (flow, members) in enumerate(zip(block["flows"], flow_members)):
            fx = 96 + fi * col_step
            # flowEntry header — its id IS the flowId the split refers to.
            fe = copy.deepcopy(parts["flow_entry"])
            fe["id"] = flow["flow_id"]
            fe["data"] = dict(fe.get("data") or {})
            fe["data"]["order"] = fi + 1
            fe["data"]["ports"] = [{"id": f"flow-entry-output-{flow['flow_id']}"}]
            fe["data"]["parentNode"] = owner_id
            fe["parentNode"] = cont_id
            fe["extent"] = "parent"
            fe["position"] = {"x": fx, "y": header_y}
            fe["positionAbsolute"] = {"x": base_x + fx, "y": base_y + header_y}
            elements.append(fe)
            # re-parent the flow's own nodes into the container
            for mi, el in enumerate(members):
                el["parentNode"] = cont_id
                el["extent"] = "parent"
                el["position"] = {"x": fx, "y": content_y + mi * 120}
                el["positionAbsolute"] = {"x": base_x + el["position"]["x"],
                                          "y": base_y + el["position"]["y"]}
            if members:
                # flowEntry -> the flow's first node, off the header's own port
                elements.append(port_edge(
                    flow["flow_id"], members[0]["id"],
                    f"flow-entry-output-{flow['flow_id']}", "flowEntry"))
        # owner -> container (the event's handle into the container's input),
        # then container -> whatever follows the whole block.
        elements.append(port_edge(
            owner_id, cont_id, f"{block['event']}-{owner_id}",
            names_raw(block["owner"]["kind"]), event_name=block["event"]))
        elements.append(port_edge(
            cont_id, block["after"], f"parallel-flow-output-{cont_id}", "parallelFlow"))

    all_nodes = [src] + [e["node"] for e in placed]
    acfg = {n["new_id"]: n["config"] for n in all_nodes if n.get("config")}
    pcfg = {n["new_id"]: n["paths"] for n in all_nodes if n.get("paths")}

    # ── assemble the body ──
    body = copy.deepcopy(lib["skeleton"])
    body["activities"] = [n["activity"] for n in all_nodes] + ends
    kinds = [e["kind"] for e in placed]
    raw = body["rawJourneyData"]
    raw["elements"] = elements
    raw["activitiesConfiguration"] = acfg
    raw["pathesConfiguration"] = pcfg
    raw["boundaryConfiguration"] = {}
    raw["exitCriteriaSettings"] = None

    # name — top-level, infoValues, AND every notification's
    # objectForSend.metadata.journeyName (the documented three places)
    name = spec.get("name") or f"JBCL | composed | {' -> '.join(kinds)}"
    body["journeyName"] = name
    raw["infoValues"]["journeyName"] = name
    for d in _walk_dicts(body):
        md = d.get("metadata")
        if isinstance(md, dict) and "journeyName" in md:
            md["journeyName"] = name

    # dates — byte-identical behavior to the proven set_dates() /
    # set_immediately_after_publish(): top-level in .NET ".0000000Z" form,
    # infoValues in plain "Z" form, and startAt is NULL when immediate.
    date = spec.get("date")
    days = int(spec.get("days", 1))
    immediately = bool(spec.get("immediately", True))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if date:
        y, m, d = (int(x) for x in date.split("-"))
        start = datetime(y, m, d, 4, 0, tzinfo=timezone.utc)      # Chile midnight
        stop = start + timedelta(days=days)
    else:
        start = now
        stop = now + timedelta(days=days)
    dotnet = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    plain = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    info = raw["infoValues"]
    body["stopAt"] = dotnet(stop)
    info["stopAt"] = plain(stop)
    body["timeZoneId"] = info["timeZoneId"] = "Chile/Continental"
    body["isImmediatelyAfterPublish"] = info["isImmediatelyAfterPublish"] = immediately
    if immediately:
        body["startAt"] = info["startAt"] = None    # captured immediate-publish state
    else:
        body["startAt"] = dotnet(start)
        info["startAt"] = plain(start)
    # free-spin validity window: starts with the campaign, claimable for a week
    for a in body["activities"]:
        fa = (a.get("initializationData") or {}).get("freespinActivity")
        if isinstance(fa, dict):
            fa["startAt"] = plain(start)
            fa["stopAt"] = plain(start + timedelta(days=7))

    # placeholder matching the proven console-script swap; lineage stripped
    body["reservedJourneyId"] = "DRY-RUN-CASINO"
    for k in ("duplicatedFromId", "duplicatedFromVersion"):
        body.pop(k, None)

    _strip_key_everywhere(body, "promotionDisplayId")

    email_content = None
    if _email_authoring:
        if len(_email_authoring) > 1:
            raise SystemExit("more than one email node authors a content; the script "
                             "creates one, so give the others an existing `template` id")
        email_content = build_email_content(_email_authoring[0], name,
                                           str(spec.get("date") or ""), report)
        report.append(f"dextra_email: authoring content {email_content['name']!r} "
                      f"(created + published at paste time, journey repointed at it)")

    return {"body": body, "report": report, "warnings": warnings,
            "chain": [src_kind] + kinds, "name": name,
            "email_content": email_content}


def _walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dicts(v)


def _strip_key_everywhere(obj, key: str) -> int:
    n = 0
    if isinstance(obj, dict):
        if key in obj:
            obj.pop(key); n += 1
        for v in obj.values():
            n += _strip_key_everywhere(v, key)
    elif isinstance(obj, list):
        for v in obj:
            n += _strip_key_everywhere(v, key)
    return n


# ── verification (the composer's own gatekeeper) ─────────────────────────────
def verify(body: dict) -> list[str]:
    errs: list[str] = []
    acts = body["activities"]
    ids = [a["activityId"] for a in acts]
    if len(ids) != len(set(ids)):
        errs.append("duplicate activityIds")
    idset = set(ids)
    for a in acts:
        for ev in a.get("events", []):
            nid = ev.get("nextActivityId")
            if nid and nid not in idset:
                errs.append(f"{a['activityName']}.{ev.get('eventName')} -> dangling nextActivityId")
        for dl in ("dependencies", "dataDependencies"):
            for d in a.get(dl) or []:
                if isinstance(d, dict) and d.get("journeyActivityId") and d["journeyActivityId"] not in idset:
                    errs.append(f"{a['activityName']} {dl} {d.get('key')} -> dangling journeyActivityId")
    raw = body["rawJourneyData"]
    el_ids = {e["id"] for e in raw["elements"] if "source" not in e}
    for e in raw["elements"]:
        if "source" in e:
            if e["source"] not in el_ids or e["target"] not in el_ids:
                errs.append(f"edge {e.get('data', {}).get('eventName')} references undrawn node")
    # A node parented to a node that is not on the canvas is the grey/blank
    # canvas: React Flow cannot place it, and it takes the whole draft down with
    # it. This shipped for a long time because 13 of the 24 fragments were cut
    # out of a parallelFlow container and kept its id in parentNode. No valid
    # capture has one — all nine checked templates have zero — so any dangling
    # parentNode is a defect, never a style.
    for e in raw["elements"]:
        if "source" in e:
            continue
        parent = e.get("parentNode")
        if parent and parent not in el_ids:
            errs.append(
                f"node {e.get('data', {}).get('name') or e['id']} has parentNode "
                f"{parent} which is not on the canvas (grey/blank canvas)")
        if e.get("extent") == "parent" and not e.get("parentNode"):
            errs.append(
                f"node {e.get('data', {}).get('name') or e['id']} has extent "
                "'parent' but no parentNode")
    # Every activity node the builder draws needs a position, or the canvas
    # collapses (COMPOSER_RULES rule 1). Exits and scaffolding are positioned by
    # the code above; this catches a fragment whose capture carried a null.
    for e in raw["elements"]:
        if "source" in e:
            continue
        if e.get("positionAbsolute") is None or e.get("position") is None:
            errs.append(
                f"node {e.get('data', {}).get('name') or e['id']} has no "
                "position/positionAbsolute")
    for k in raw.get("activitiesConfiguration", {}):
        if k not in idset:
            errs.append("activitiesConfiguration key not an activity id")
    # RULE #1: promotion is NEVER downstream of the deposit that gates it.
    # The player must ACCEPT the offer before a condition can gate its reward; a
    # deposit gate placed first has nothing to gate and the platform rejects or
    # misbehaves. Across the five captures carrying both nodes there are 13
    # promotion -> deposit edges (all on PromotionAccepted) and zero of the
    # reverse, so a deposit -> promotion edge is always a wiring bug — it is not
    # a variant. This is a refusal rather than a warning because the draft looks
    # completely normal in the builder and only misbehaves once a player enters.
    by_id = {a["activityId"]: a for a in acts}

    def _targets(activity: dict):
        for ev in activity.get("events", []) or []:
            nid = ev.get("nextActivityId")
            if nid:
                yield ev.get("eventName"), nid
            for path in ((ev.get("split") or {}).get("paths") or []):
                if path.get("nextActivityId"):
                    yield ev.get("eventName"), path["nextActivityId"]

    for a in acts:
        if a.get("activityName") != "deposit":
            continue
        for ev_name, nid in _targets(a):
            nxt = by_id.get(nid)
            if nxt is not None and nxt.get("activityName") == "promotion":
                errs.append(
                    f"deposit.{ev_name} -> promotion: the deposit gate is ahead of "
                    "the offer it gates. Order is ALWAYS promotion -> deposit "
                    "(on PromotionAccepted)")

    # A DELIVERED message is never followed straight by another send. Measured
    # over all 18 captures: a success event (NotificationSent / SuccessEmailSend
    # / SuccessSmsSend) leads to a wait, a split or an end — to another send
    # ZERO times. Chaining sends on success fires the whole set at once at
    # everybody and measures nobody, which is the "comms with no waits and no
    # engagement split" complaint. The FAILURE branch is the opposite and is
    # left alone: NotificationNotSent -> next channel is the correct immediate
    # fallback and occurs 7 times.
    SENDS = {"notification_center", "dextra_sms", "dextra_email"}
    SUCCESS = {"NotificationSent", "SuccessEmailSend", "SuccessSmsSend"}
    for a in acts:
        if a.get("activityName") not in SENDS:
            continue
        for ev in a.get("events", []) or []:
            if ev.get("eventName") not in SUCCESS:
                continue
            for nid in ([ev["nextActivityId"]] if ev.get("nextActivityId") else []) + [
                    p_["nextActivityId"] for p_ in ((ev.get("split") or {}).get("paths") or [])
                    if p_.get("nextActivityId")]:
                nxt = by_id.get(nid)
                if nxt is not None and nxt.get("activityName") in SENDS:
                    errs.append(
                        f"{a['activityName']}.{ev['eventName']} -> "
                        f"{nxt['activityName']}: a delivered message goes to a wait "
                        "or an engagement split, never straight to another send "
                        "(0 occurrences in 18 captures). Insert a wait, then a "
                        "split, and send the next channel off the branch that "
                        "still needs chasing")

    # Spins make the winnings, the wagering bonus wagers them — never the other
    # way round. `freespin_bonus -> casino_bonus_v2` occurs 4x in the captures on
    # FreespinBonusCollectingFinished; the reverse occurs 0 times. Reversed, the
    # bonus has nothing to wager.
    for a in acts:
        if a.get("activityName") != "casino_bonus_v2":
            continue
        for ev_name, nid in _targets(a):
            nxt = by_id.get(nid)
            if nxt is not None and nxt.get("activityName") == "freespin_bonus":
                errs.append(
                    f"casino_bonus_v2.{ev_name} -> freespin_bonus: the wagering "
                    "bonus is ahead of the spins that produce the winnings it "
                    "wagers. Order is ALWAYS freespin_bonus -> casino_bonus_v2 "
                    "(on FreespinBonusCollectingFinished)")

    # withWagering and the wagering node must AGREE, in both directions. The
    # captures correlate 1:1 with no exception: gow.json's four freespin nodes
    # are withWagering:true and every one leads to a casino_bonus_v2;
    # instfs.json's is withWagering:false and leads to none.
    #
    #   false + a wagering node  = an "instant" bonus that grinds. The flag is
    #                              what makes it instant; the node contradicts it.
    #   true  + no wagering node = spins marked as requiring wagering with
    #                              nothing downstream to wager. The requirement
    #                              silently does nothing.
    #
    # Both ship a reward that is not the one the brief describes, and both look
    # completely normal in the builder.
    for a in acts:
        if a.get("activityName") != "freespin_bonus":
            continue
        fa = ((a.get("initializationData") or {}).get("freespinActivity") or {})
        with_wagering = fa.get("withWagering")
        if with_wagering is None:
            continue
        leads_to_wagering = any(
            (by_id.get(nid) or {}).get("activityName") == "casino_bonus_v2"
            for _ev, nid in _targets(a))
        if with_wagering is False and leads_to_wagering:
            errs.append(
                "freespin_bonus -> casino_bonus_v2 with withWagering:false: an "
                "instant bonus is a TERMINAL reward and cannot carry a wagering "
                "requirement. Drop the wagering node, or set withWagering:true "
                "if the brief really wants the player to grind it")
        elif with_wagering is True and not leads_to_wagering:
            errs.append(
                "freespin_bonus has withWagering:true but no casino_bonus_v2 "
                "after it: the spins are marked as requiring wagering with "
                "nothing to wager, so the requirement does nothing. Add the "
                "wagering node, or set withWagering:false for an instant bonus")

    # COMPOSER_RULES rule 3. A node kept inside a container it was lifted out of
    # saves fine and then will not open: the editor reads the absent parent's
    # position and throws. Nothing checked it, so it shipped.
    all_el_ids = {e.get("id") for e in raw["elements"]}
    for e in raw["elements"]:
        parent = e.get("parentNode") or (e.get("data") or {}).get("parentNode")
        if parent and parent not in all_el_ids:
            errs.append(f"element {str(e.get('id'))[:8]} is nested in parent "
                        f"{str(parent)[:8]}, which is not in this journey — "
                        f"the editor cannot lay it out (blank canvas)")
    # Rule 1: the synthesized terminal is the easy one to forget.
    for e in raw["elements"]:
        if "source" in e:               # an edge, not a node
            continue
        for key in ("position", "positionAbsolute"):
            pos = e.get(key)
            if not isinstance(pos, dict) or "x" not in pos or "y" not in pos:
                errs.append(f"element {str(e.get('id'))[:8]} has no usable {key}")
    if not body.get("journeyName"):
        errs.append("journeyName missing")
    if body.get("duplicatedFromId"):
        errs.append("lineage not stripped")
    if _count_key(body, "promotionDisplayId"):
        errs.append("promotionDisplayId not stripped")
    return errs


def _count_key(obj, key: str) -> int:
    if isinstance(obj, dict):
        return (key in obj) + sum(_count_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_key(v, key) for v in obj)
    return 0


def captured_connections() -> list[dict]:
    """Every (from, event, to) connection actually captured — the AI's full
    connection grammar, straight from the templates (like build_catalog)."""
    conns: list[dict] = []
    seen: set = set()
    for path in SOURCES:
        body = json.loads(path.read_text(encoding="utf-8-sig"))
        by_id = {a["activityId"]: a for a in body["activities"]}
        for a in body["activities"]:
            for ev in a.get("events", []):
                nxt = by_id.get(ev.get("nextActivityId"))
                if nxt is None:
                    continue
                sig = (_akey(a), ev.get("eventName"), _akey(nxt))
                if sig in seen:
                    continue
                seen.add(sig)
                conns.append({"from": sig[0], "event": sig[1], "to": sig[2],
                              "event_type": ev.get("eventType"), "captured_in": path.name})
    return sorted(conns, key=lambda c: (c["from"], c["event"] or "", c["to"]))


# ── CLI ──────────────────────────────────────────────────────────────────────
def options() -> dict:
    """The composable palette as data: sources, activities, their captured
    events and settings, the games registry and the spec shape.

    Split out of cmd_options so it can be imported — compose.py's catalog()
    publishes a compacted form into the planner prompt, which is what lets the
    planner emit chain specs instead of only the four fixed recipes."""
    lib = load_library()
    have = sorted(k for k in lib["types"] if k not in ("end_of_journey", "end_of_path"))

    def events_of(k: str) -> dict:
        evs = lib["types"][k]["activity"].get("events", [])
        return {"completion": sorted(e["eventName"] for e in evs if e.get("eventType") == "Completion"),
                "boundary": sorted(e["eventName"] for e in evs if e.get("eventType") == "Boundary"),
                "activation": sorted(e["eventName"] for e in evs if e.get("eventType") == "Activation")}

    return {
        "sources": {"csv/segment": "dwh_source (segment/CSV-seeded audience)",
                    "api": "external_system_source (API entry) — use this for a "
                           "journey a randomizer routes winners into",
                    "promocode": "registration (Reference codes entry; takes "
                                 "`promocode`)"},
        "chain_types": {k: {"aliases": sorted(a for a, v in ALIASES.items() if v == k),
                            "default_follow": HAPPY.get(k),
                            "events": events_of(k),
                            "settings": SETTINGS_DOC.get(k, {}),
                            "captured_in": lib["types"][k]["template"]}
                        for k in have if k not in SOURCE_TYPES},
        "captured_connections": captured_connections(),
        # The full registry, so a caller (or an LLM) can resolve a brief's game
        # name without guessing. Keyed by lobbyGameId -> display name.
        "games": {e["lobbyGameId"]: e.get("gameTranslationKey") or e["lobbyGameId"]
                  for e in _game_index().values()},
        "spec_shape": {"name": "str", "source": {"type": "segment|csv|api", "...settings": "?"},
                       "chain": [{"type": "<chain type>", "...settings": "?",
                                  "follow": "optional Completion event that continues the chain (default: default_follow)",
                                  "branches": {"<Completion event>": ["... nested chain nodes ..."]}}],
                       "date": "YYYY-MM-DD (stop anchor)", "days": "int (default 1)",
                       "immediately": "bool (default true)"},
    }


def cmd_options(as_json: bool) -> int:
    out = options()
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for k, v in out["chain_types"].items():
            print(f"{k}: follow={v['default_follow']} settings={list(v['settings'])}")
        print(f"\ncaptured connections: {len(out['captured_connections'])}")
    return 0


def cmd_describe(spec: dict) -> int:
    src = ALIASES.get(str((spec.get("source") or {}).get("type", "")).lower(), "?")
    parts = [f"{src.upper()}"]
    for c in spec.get("chain", []):
        k = ALIASES.get(str(c.get("type", "")).lower(), f"?{c.get('type')}")
        s = {a: b for a, b in c.items() if a != "type"}
        parts.append(f"{k.upper()}({', '.join(f'{a}={b}' for a, b in s.items())})" if s else k.upper())
    parts.append("END")
    print("You want this journey?\n\n  " + "  ->  ".join(parts))
    print(f"\n  name : {spec.get('name') or '(auto)'}")
    print(f"  when : stop {spec.get('date') or '(now+days)'} +{spec.get('days', 1)}d, "
          f"start {'immediately' if spec.get('immediately', True) else 'on date'}")
    return 0


def emit_console_script(body: dict, out_path: Path, email_content: dict | None = None,
                        promo_clones: list[dict] | None = None) -> str:
    """Render the paste-ready browser console script using the PROVEN scaffold
    from casino_journey.py (token auto-capture -> reserve JRN id -> regenerate
    activity uuids at paste time -> POST /journey-drafts -> aggregatedError log).
    """
    from casino_journey import build_js  # the battle-tested JS template
    # body already carries the DRY-RUN-CASINO placeholder the script swaps
    js = build_js(body)
    js = _inject_pickers(js, pick_slots(body), email_content, promo_clones)
    out_path.write_text(js, encoding="utf-8")
    return str(out_path)


# Injected only when a build left artwork for paste time. Mirrors the upload
# mechanic proven in comms_campaign.py / sport_comms_campaign.py: pick the file,
# read its real dimensions (the media library wants them in the URL), PUT it to
# the folder, then use the absolute_link it answers with.
_PICKER_JS = """
  // --- paste-time artwork ---------------------------------------------------
  const PICK_SLOTS = @PICK_SLOTS@;
  const FOLDER_ID = @FOLDER_ID@;
  const CRM_BASE = BASE.replace(/\\/journey-builder\\/v0$/, '');
  function pickFile(label) {
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = 'image/*';
      Object.assign(input.style, { position: 'fixed', top: '12px', left: '12px', zIndex: 999999, background: '#fff', padding: '8px', border: '3px solid #22c55e', borderRadius: '6px' });
      document.body.appendChild(input);
      console.log('%cSelect the image for ' + label + ' (picker is at the top-left of the page).', 'color:#eab308;font-weight:bold');
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
  // No content-type: the media library wants the multipart boundary the browser
  // sets itself.
  const upHeaders = () => ({ accept: 'application/json, text/plain, */*', authorization: auth, 'x-brand': BRAND });
  async function uploadAsset(file, label) {
    const dims = await imageDims(file);
    const base = (file.name || 'image').replace(/\\.[^./]+$/, '');
    const url = CRM_BASE + '/media-library/v0/folder/' + FOLDER_ID + '/upload/' + encodeURIComponent(base) + '.png?height=' + dims.height + '&width=' + dims.width;
    const fd = new FormData(); fd.append('file', file, file.name);
    const r = await fetch(url, { method: 'PUT', headers: upHeaders(), credentials: 'include', body: fd });
    const t = await r.text();
    if (!r.ok) throw new Error(label + ' upload failed HTTP ' + r.status + ' ' + t);
    const asset = JSON.parse(t);
    const tfd = new FormData(); tfd.append('file', file, file.name);
    await fetch(CRM_BASE + '/media-library/v0/asset/thumb/' + asset.id + '.png', { method: 'PUT', headers: upHeaders(), credentials: 'include', body: tfd }).catch(() => {});
    if (!asset.absolute_link || !asset.relative_link) throw new Error(label + ' upload returned no link: ' + t);
    console.log('    ' + label + ' -> ' + asset.absolute_link);
    return asset;
  }
  for (const slot of PICK_SLOTS) {
    if (!text.includes(slot.token)) throw new Error('artwork placeholder for ' + slot.label + ' is not in the payload — regenerate the script.');
    const asset = await uploadAsset(await pickFile(slot.label), slot.label);
    text = text.split(slot.token).join(asset.absolute_link);
  }
  // A surviving placeholder means a node would ship the captured campaign's
  // picture. Refuse, the same way the composer refuses unset artwork.
  if (text.indexOf('@@PICK:') !== -1) throw new Error('unresolved artwork placeholder — refusing to create the draft.');
"""


_EMAIL_JS = """
  // --- author the email content ---------------------------------------------
  // The email's copy is not inline on the activity: it lives in a content-studio
  // content the activity references. So create one, publish it, and repoint the
  // journey at the id — the flow comms_campaign.py proved. The captured content
  // is never edited; this always makes a new one.
  const EMAIL_CONTENT = @EMAIL_CONTENT@;
  const EMAIL_IMAGE_SLOTS = @EMAIL_IMAGE_SLOTS@;
  const EMAIL_CONTENT_ID_TOKEN = @EMAIL_CONTENT_ID_TOKEN@;
  const CONTENT_BASE = CRM_BASE + '/content-studio/v0/eb-backoffice/email/contents';
  async function authorEmail() {
    let cText = JSON.stringify(EMAIL_CONTENT);
    for (const slot of EMAIL_IMAGE_SLOTS) {
      if (cText.indexOf(slot.token) === -1) continue;
      const asset = await uploadAsset(await pickFile(slot.label), slot.label);
      // The body references images as https://{{cdn_hostname}}<relative>, not the
      // absolute URL — the absolute one does not resolve for every recipient.
      cText = cText.split(slot.token).join('https://{{cdn_hostname}}' + asset.relative_link);
    }
    if (/@@EMAIL_[A-Z_]+@@/.test(cText)) throw new Error('an email image placeholder was left unfilled — refusing to create the content.');
    const content = JSON.parse(cText);
    let r = await fetch(CONTENT_BASE, { method: 'POST', headers: { ...upHeaders(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(content) });
    let t = await r.text();
    if (!r.ok) throw new Error('Email content create failed HTTP ' + r.status + ' ' + t);
    const cseId = JSON.parse(t).id;
    if (!cseId) throw new Error('email create returned no id: ' + t);
    console.log('    created email content', cseId);
    r = await fetch(CONTENT_BASE + '/' + cseId, { method: 'POST', headers: { ...upHeaders(), 'content-type': 'application/json' }, credentials: 'include', body: JSON.stringify(content) });
    if (!r.ok) throw new Error('Email content save failed HTTP ' + r.status + ' ' + await r.text());
    r = await fetch(CONTENT_BASE + '/' + cseId + '/publish', { method: 'PATCH', headers: { ...upHeaders(), 'content-type': 'application/json' }, credentials: 'include', body: '{}' });
    if (!r.ok) throw new Error('Email content publish failed HTTP ' + r.status + ' ' + await r.text());
    console.log('    published email content', cseId);
    return cseId;
  }
  const cseId = await authorEmail();
  if (!text.includes(EMAIL_CONTENT_ID_TOKEN)) throw new Error('the journey has no email repoint token — regenerate the script.');
  text = text.split(EMAIL_CONTENT_ID_TOKEN).join(cseId);
  // An unswapped token would leave the email activity pointing at a literal
  // placeholder, which the builder shows as a valid-looking card.
  if (text.indexOf('@@EMAIL_CONTENT_ID@@') !== -1) throw new Error('email repoint incomplete — refusing to create the draft.');
"""


_PROMO_PAGE_JS = """
  // --- clone the promo page ---------------------------------------------------
  // A minted ContentId/FrontId owns no content tree, so the offer card renders
  // empty — every composed casino journey reported INCOMPLETE for that reason.
  // These are gow_campaign.py's own calls, unchanged: a per-target
  // /contents/v1/copy from the captured id to the fresh one. The copy is always
  // scoped by fileFilters, because an unfiltered copy of a years-old bundle
  // folder stalls recursively enumerating ancient assets — the backoffice's own
  // duplicate action scopes it the same way.
  //
  // What this does NOT do: rewrite the marketing text baked into the content, or
  // upload new artwork. The page comes out as the captured campaign's page under
  // ids this draft owns. That is the template being the source of truth for
  // shape; change the words in the backoffice, or build the page in GOW where
  // those rewrites live.
  const PROMO_CLONES = @PROMO_CLONES@;
  async function copyContentsTarget(srcPath, destPath, fileFilters) {
    const body = { sourcePath: srcPath, destinationPath: destPath };
    if (fileFilters) body.fileFilters = fileFilters;
    const r = await fetch(CRM_BASE + '/contents/v1/copy', { method: 'POST', headers: headers('application/json'), credentials: 'include', body: JSON.stringify(body) });
    if (!r.ok) throw new Error('promo page copy failed ' + srcPath + ' -> ' + destPath + ': HTTP ' + r.status + ' ' + await r.text());
  }
  const JSON_FILTERS = ['manifest.json', 'content/content-es.json', 'content/content-en.json'];
  function contentFileFilters(target, role, itemContentIds) {
    if (target === 'widgetModulor' || target === 'cashier') return JSON_FILTERS;
    if (target === 'widget') return JSON_FILTERS.concat(['media/box.png', 'media/widgetImgKey.png']);
    if (target === 'spa') {
      if (role === 'offer') {
        return JSON_FILTERS.concat(
          ['media/HeaderImageKey.png', 'media/prizeImageKey.png'],
          (itemContentIds || []).map((id) => `media/${id}.itemImageKey.png`)
        );
      }
      return JSON_FILTERS.concat(['media/box.png', 'media/bonusHeaderImage.png']);
    }
    return undefined;
  }
  async function cloneBundle(oldId, newId, targets, role, itemContentIds) {
    await Promise.all(targets.map((t) =>
      copyContentsTarget(`mf/v1/${oldId}/${t}`, `mf/v1/${newId}/${t}`,
                         role ? contentFileFilters(t, role, itemContentIds) : undefined)));
  }
  if (PROMO_CLONES.length) {
    console.log('Cloning the promo page bundle(s)...');
    await Promise.all(PROMO_CLONES.map(async (c) => {
      console.log('  [' + c.role + '] content ' + c.old_content + ' -> ' + c.new_content);
      await Promise.all([
        cloneBundle(c.old_content, c.new_content,
                    ['spa', 'widget', 'widgetModulor', 'cashier'], c.role, c.item_content_ids),
        cloneBundle(c.old_front, c.new_front, ['spa', 'widget']),
      ]);
    }));
    console.log('%c  promo page cloned — it carries the captured campaign\\'s words and artwork.',
                'color:#eab308');
  }
"""


def promo_page_clones(id_map: dict) -> tuple[list[dict], list[str]]:
    """Pair each minted ContentId with its FrontId and the role that names its
    fileFilters. Returns (clones, problems).

    The role comes from gow_campaign.PLACEMENTS, which records the captured
    content ids — so it is looked up, not guessed. An id that is not in there has
    no known filter set, and an unfiltered copy of an old bundle can stall, so it
    is reported rather than attempted.
    """
    try:
        from gow_campaign import PLACEMENTS
    except Exception:
        return [], ["cannot import gow_campaign.PLACEMENTS — promo-page roles unknown"]
    by_content = {p["contentId"]: p for p in PLACEMENTS}
    by_front = {p["frontId"]: p for p in PLACEMENTS}
    clones, problems = [], []
    for old, info in id_map.items():
        if info.get("key") not in ("ContentId", "contentId"):
            continue
        placement = by_content.get(old)
        if placement is None:
            problems.append(
                f"ContentId {old} is not one of the captured GOW placements, so its "
                f"fileFilters are unknown — refusing to copy it unfiltered (that "
                f"stalls on old bundles). Build the page in GOW and pass content_id "
                f"/ front_id instead.")
            continue
        front_old = placement["frontId"]
        front_new = (id_map.get(front_old) or {}).get("new")
        if not front_new:
            problems.append(f"ContentId {old} was minted but its FrontId {front_old} "
                            f"was not — the pair must move together")
            continue
        clones.append({"role": placement["role"],
                       "old_content": old, "new_content": info["new"],
                       "old_front": front_old, "new_front": front_new,
                       "item_content_ids": placement.get("itemContentIds") or []})
    return clones, problems


def _inject_pickers(js: str, slots: list[dict], email_content: dict | None = None,
                    promo_clones: list[dict] | None = None) -> str:
    if not slots and not email_content and not promo_clones:
        return js
    from media_library import DEFAULT_FOLDER_ID
    block = (_PICKER_JS
             .replace("@PICK_SLOTS@", json.dumps(slots, ensure_ascii=False))
             .replace("@FOLDER_ID@", json.dumps(DEFAULT_FOLDER_ID)))
    if email_content is not None:
        ctext = json.dumps(email_content, ensure_ascii=False)
        slots = [{"token": t, "label": lbl} for t, lbl in EMAIL_IMAGE_LABELS.items()
                 if t in ctext]
        block += (_EMAIL_JS
                  .replace("@EMAIL_CONTENT@", ctext)
                  .replace("@EMAIL_IMAGE_SLOTS@", json.dumps(slots, ensure_ascii=False))
                  .replace("@EMAIL_CONTENT_ID_TOKEN@", json.dumps(EMAIL_CONTENT_ID_TOKEN)))
    if promo_clones:
        block += _PROMO_PAGE_JS.replace("@PROMO_CLONES@",
                                        json.dumps(promo_clones, ensure_ascii=False))
    # After the ids are regenerated and before the body is parsed and POSTed:
    # substituting on the serialised text hits the compiled activities and the
    # rawJourneyData mirror in one pass, which is what keeps them byte-identical.
    anchor = "  const body = JSON.parse(text);"
    if anchor not in js:
        raise SystemExit("console scaffold changed — cannot inject artwork pickers")
    return js.replace(anchor, block + "\n" + anchor, 1)


def _inherited_content_errors(body: dict) -> list[str]:
    """Campaign content this chain still shares with the templates it was cloned
    from. A chain picks its own activities, but a communication node is copied
    whole — so an SMS node the spec gave no text to still carries the captured
    campaign's message, links and email template."""
    try:
        from compose import audit_inherited_content, audit_shared_promotion_identity
    except Exception:
        return []
    leaks: dict[str, None] = {}
    for path in SOURCES:
        try:
            ref = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        for line in audit_inherited_content(body, ref):
            leaks.setdefault(line, None)
        # A chain clones its promotion node whole, so it arrives carrying the
        # captured campaign's promotionId / campaignId and its promo-page
        # ContentId+FrontId. Those are not copies — they are the SAME
        # server-side objects, so the draft hangs off the captured campaign and
        # editing its page content rewrites that live campaign's page. MODE 5 is
        # the default path, so this is where it mattered most and it was the one
        # place not checked.
        for line in audit_shared_promotion_identity(body, ref):
            leaks.setdefault(f"SHARED PROMOTION IDENTITY — {line}", None)
    return list(leaks)


def cmd_compose(spec: dict, as_json: bool, script: bool, basename: str | None = None) -> int:
    res = compose(spec)
    _id_map: dict = {}
    promo_clones: list[dict] = []
    errs_extra: list[str] = []
    # A chain clones its promotion node whole, so the draft arrives owning the
    # CAPTURED campaign's promotionId / campaignId and promo-page ContentId. Mint
    # fresh ones before verifying, or the draft hangs off that live campaign and
    # editing its page content rewrites it (the Sport WOF bug). The audit below
    # is the backstop for anything this misses.
    try:
        from compose import refresh_promotion_identity
        for _src in SOURCES:
            try:
                _ref = json.loads(_src.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            for _line in refresh_promotion_identity(res["body"], _ref, _id_map):
                res.setdefault("report", []).append(_line)
    except Exception:
        pass
    # Cloning the page turns those minted ids from blanks into a real tree, which
    # is the difference between a shippable journey and one the player sees an
    # empty card in. Only when asked for: a silent clone of another campaign's
    # page is a surprise, and the INCOMPLETE warning is the honest default.
    if _promo_page_requested and _id_map:
        promo_clones, promo_problems = promo_page_clones(_id_map)
        for _line in promo_problems:
            errs_extra.append(f"promo_page — {_line}")
        if promo_clones:
            # refresh_promotion_identity warns INCOMPLETE because a minted id owns
            # no tree. We are about to give it one, so that line now contradicts
            # what the run does — drop it rather than print both.
            res["report"] = [ln for ln in res.get("report", [])
                             if "INCOMPLETE — the promo page" not in ln]
            res.setdefault("report", []).append(
                f"promotion: cloning {len(promo_clones)} promo-page bundle(s) at paste "
                f"time ({', '.join(c['role'] for c in promo_clones)}) — the page will "
                f"carry the captured campaign's words and artwork, so change the copy "
                f"in the backoffice or build it in GOW instead")
    elif _promo_page_requested:
        errs_extra.append("promo_page: 'clone' was asked for but no ContentId was "
                          "minted — this journey shares no page with its reference, "
                          "so there is nothing to copy")
    errs = verify(res["body"]) + errs_extra
    # Treat leaked campaign content as a verification failure: a journey that
    # messages players with another campaign's copy is not a usable draft, and
    # "VERIFIED OK" on one is exactly how the wrong SMS reached a real draft.
    errs = errs + [f"inherited content — {line}" for line in _inherited_content_errors(res["body"])]
    # A PICK sentinel is only ever resolved by the console script's file picker.
    # In a JSON-only build it is an unresolved placeholder sitting where a URL
    # belongs, so it must fail rather than look like a composed value.
    slots = pick_slots(res["body"])
    if slots and not script:
        errs = errs + [f"artwork left for paste time ({s['label']}) but no script was "
                       f"requested — re-run with --script, or give a URL instead of PICK"
                       for s in slots]
    OUT.mkdir(exist_ok=True)
    slug = re.sub(r"[^\w]+", "_", res["name"].lower()).strip("_")[:60]
    # The name-derived path is shared: every run for the same campaign writes the
    # same file. That is fine for a shell run, but for a caller that passes a
    # basename (the admin, which already uniquifies to survive concurrent
    # requests) it means two operators building one campaign overwrite each
    # other — and a file left behind by a run under a different user makes every
    # later run fail with EACCES on a path nobody asked about.
    out_path = OUT / (f"{basename}.journey.json" if basename else f"{slug}.journey.json")
    try:
        out_path.write_text(json.dumps(res["body"], ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except OSError as exc:
        # The composed body is a debugging artefact, not the deliverable. Losing
        # it must not cost the operator the console script they asked for.
        print(f"  WARN  could not write {out_path}: {exc}")
        out_path = None

    js_path = None
    if script and not errs:
        if basename:
            # Called by the backoffice runner, which reads back exactly
            # console_scripts/<basename>_console.js — same convention as every
            # other generator. Bare CLI runs keep the name-derived out/ path.
            CONSOLE_OUT.mkdir(parents=True, exist_ok=True)
            js_path = emit_console_script(res["body"], CONSOLE_OUT / f"{basename}_console.js",
                                          res.get("email_content"), promo_clones)
        else:
            js_path = emit_console_script(res["body"], OUT / f"{slug}.console.js",
                                          res.get("email_content"), promo_clones)

    summary = {
        "ok": not errs,
        "output": str(out_path) if out_path else None,
        "console_script": js_path,
        "chain": res["chain"],
        "activities": len(res["body"]["activities"]),
        "elements": len(res["body"]["rawJourneyData"]["elements"]),
        "settings_applied": res["report"],
        "warnings": res["warnings"],
        "verify_errors": errs,
        "handoff": ("Paste the console script into a logged-in backoffice DevTools console to "
                    "create the draft (it reserves the JRN id and POSTs)."
                    if js_path else
                    "reservedJourneyId carries the DRY-RUN-CASINO placeholder: re-run with "
                    "--script for a paste-ready console script that swaps in a real JRN id. "
                    "This tool never calls the API."),
    }
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"chain    : {' -> '.join(res['chain'])} -> end")
        if out_path:
            print(f"output   : {out_path}")
        if js_path:
            print(f"script   : {js_path}")
        print(f"activities {summary['activities']}, elements {summary['elements']}")
        for line in res["report"]:
            print(f"  set   {line}")
        for w in res["warnings"]:
            print(f"  WARN  {w}")
        for e in errs:
            print(f"  ERROR {e}")
        print("VERIFIED OK" if not errs else "VERIFY FAILED")
    return 0 if not errs else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)
    po = sub.add_parser("options"); po.add_argument("--json", action="store_true")
    pd = sub.add_parser("describe"); pd.add_argument("spec")
    pc = sub.add_parser("compose"); pc.add_argument("spec"); pc.add_argument("--json", action="store_true")
    pc.add_argument("--script", action="store_true",
                    help="also emit the paste-ready browser console script (reserve id -> POST)")
    pc.add_argument("--name", default=None,
                    help="emit console_scripts/<name>_console.js instead of a "
                         "name-derived path under out/ (used by the backoffice runner)")
    a = p.parse_args()
    if a.mode == "options":
        return cmd_options(a.json)
    raw = sys.stdin.read() if a.spec == "-" else Path(a.spec).read_text(encoding="utf-8")
    # Tolerate a planner reply verbatim: ```json fences and prose lead-ins are
    # what the model actually emits, and a bare json.loads turns that into a
    # traceback instead of a usable message.
    from compose import _extract_json, SpecError
    try:
        spec = _extract_json(raw)
    except SpecError as exc:
        raise SystemExit(f"⛔ REFUSED — {exc}")
    if a.mode == "describe":
        return cmd_describe(spec)
    return cmd_compose(spec, a.json, a.script, a.name)


if __name__ == "__main__":
    raise SystemExit(main())
