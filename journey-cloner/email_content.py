"""Build the GOW marketing-email content (content-studio email/contents).

The comms journey's dextra_email activity does not carry its copy inline like
the Notification/Pop-up/SMS activities do — it references an email *content*
by id (emailSettings.template.id = "CSE-0-...."). Changing the email therefore
means creating a brand-new content from the captured template, substituting
the per-run pieces, publishing it, and then pointing the journey's email
activity at the new content id.

Captured from a real create -> edit -> publish flow (the emailcomms HAR). The
only things that change run to run:
  * name      -> "JBCL CS - GOW <DD.MM>"
  * subject   -> the spec's Email "Tittle" (ES)
  * preHeader -> the spec's Email "Pre-header" (ES)
  * heading   -> "<game> | <provider>" (the @@EMAIL_HEADING@@ token)
  * hero img  -> the uploaded photo (the @@EMAIL_HERO_URL@@ token, filled at
                 paste time after the upload, like the NC icon / Pop-up bg)
  * promo CTA -> /promo/offers/promoPage/<id> (the shared @@PROMO_PAGE_ID@@
                 token; baked here when the promo id is already known, left
                 for the console script to fill when the promo page is created
                 in the same run)

This module only builds the substituted content body (server-side). The live
create -> save -> publish calls and the photo upload happen in the console
script at paste time, which then swaps the resulting content id into the
journey payload via @@EMAIL_CONTENT_ID@@.
"""
from __future__ import annotations

import json
from datetime import datetime
from html import escape as html_escape
from pathlib import Path

EMAIL_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "casino" / "gow_email.json"

# Paste-time placeholder for the uploaded hero photo (the email body references
# it as https://{{cdn_hostname}}<relative_link>, so the console script fills
# this with that form rather than the absolute static URL).
EMAIL_HERO_TOKEN = "@@EMAIL_HERO_URL@@"
# Build-time placeholder for the "<game> | <provider>" heading cell.
EMAIL_HEADING_TOKEN = "@@EMAIL_HEADING@@"
# Paste-time placeholder for the content id the create call returns; swapped
# into the journey's dextra_email activity once the content exists.
EMAIL_CONTENT_ID_TOKEN = "@@EMAIL_CONTENT_ID@@"
# Shared with the journey payload's promo link.
PROMO_PAGE_ID_TOKEN = "@@PROMO_PAGE_ID@@"


def email_name(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"JBCL CS - GOW {dt:%d.%m}"


def prepare_email_content(
    *,
    date_str: str,
    game_name: str,
    provider_name: str,
    subject_es: str,
    preheader_es: str,
    promo_page_id: str | None = None,
) -> dict:
    """Return the email-content payload for POST .../email/contents.

    The hero photo and (when promo_page_id is None) the promo link stay as
    tokens for the console script to fill in at paste time.
    """
    content = json.loads(EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8"))
    content["name"] = email_name(date_str)

    comp = content["translations"]["es"]["composition"]
    comp["subject"] = subject_es
    comp["preHeader"] = preheader_es

    heading = f"{game_name} | {provider_name}".strip(" |")
    src = comp["body"]["source"].replace(EMAIL_HEADING_TOKEN, heading)
    if promo_page_id:
        src = src.replace(PROMO_PAGE_ID_TOKEN, promo_page_id)
    comp["body"]["source"] = src
    return content


# ── the Champions/comms shell (templates/casino/champions_email.json) ────────
# A second captured shell, kept apart from the GOW one because its chrome
# differs: the footer and banner are content-studio blocks
# ([[block(CSE-0-...)]]) rather than inline HTML, and its call to action is an
# image, not a text button. Everything outside the tokens below is reproduced
# exactly as captured.
COMMS_EMAIL_TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "templates" / "casino" / "champions_email.json"
)

# Filled at build time, server-side.
EMAIL_BODY_TOKEN = "@@EMAIL_BODY_HTML@@"
EMAIL_GREETING_TOKEN = "@@EMAIL_GREETING@@"
EMAIL_LINK_TOKEN = "@@EMAIL_LINK@@"
EMAIL_CTA_TEXT_TOKEN = "@@EMAIL_CTA_TEXT@@"
# Filled at paste time, once the console script has uploaded the photo.
EMAIL_TOP_IMAGE_TOKEN = "@@EMAIL_TOP_IMAGE_URL@@"
EMAIL_CTA_IMAGE_TOKEN = "@@EMAIL_CTA_IMAGE_URL@@"

DEFAULT_GREETING_ES = "¡Hola, {{FirstName}}!"


def body_html_from_text(text: str) -> str:
    """Turn the sheet's plain email copy into the shell's paragraph markup.

    A blank line becomes the double break the captured shell uses between
    thoughts, a single newline a single break. HTML metacharacters are escaped,
    so sheet copy can never inject markup — pass already-marked-up copy through
    ``body_html`` instead.
    """
    lines = [html_escape(ln.strip()) for ln in str(text).strip().splitlines()]
    out: list[str] = []
    for ln in lines:
        out.append(ln if ln else "<br>")
    return "<br>\n".join(out)


def prepare_comms_email_content(
    *,
    name: str,
    subject_es: str,
    preheader_es: str,
    body_html: str,
    link: str,
    cta_text: str = "",
    greeting: str = DEFAULT_GREETING_ES,
) -> dict:
    """Return the email-content payload for POST .../email/contents.

    Refuses rather than warns: an empty subject, pre-header, body or link would
    publish the captured campaign's placeholder to real players. The two photo
    slots stay as tokens for the console script to fill after the upload.
    """
    missing = [n for n, v in (("name", name), ("subject", subject_es),
                              ("pre-header", preheader_es), ("body", body_html),
                              ("link", link)) if not str(v).strip()]
    if missing:
        raise ValueError("email content is missing " + ", ".join(missing)
                         + " — refusing to build a content that would publish blank.")
    if not str(link).startswith(("http://", "https://")):
        raise ValueError(f"email link {link!r} is not absolute — the CTA would not resolve.")

    content = json.loads(COMMS_EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8"))
    content["name"] = name

    comp = content["translations"]["es"]["composition"]
    comp["subject"] = subject_es
    comp["preHeader"] = preheader_es

    src = comp["body"]["source"]
    for token, value in ((EMAIL_BODY_TOKEN, body_html),
                         (EMAIL_GREETING_TOKEN, greeting),
                         (EMAIL_LINK_TOKEN, link),
                         (EMAIL_CTA_TEXT_TOKEN, cta_text)):
        if token not in src and token != EMAIL_CTA_TEXT_TOKEN:
            raise ValueError(f"{token} is not in the captured shell — it has drifted.")
        src = src.replace(token, value)
    comp["body"]["source"] = src

    for token in (EMAIL_TOP_IMAGE_TOKEN, EMAIL_CTA_IMAGE_TOKEN):
        if token not in src:
            raise ValueError(f"{token} vanished from the shell — the photo slot would ship empty.")
    return content
