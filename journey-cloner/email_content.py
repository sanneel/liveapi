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
