"""Build the PMCL (Fortunazo) tournament marketing-email content.

Like GOW's email_content.py, the comms journey's dextra_email activity does
not carry its copy inline — it references an email *content* by id
(emailSettings.template.id = "CSE-0-...."). Changing the email therefore means
creating a fresh content from the captured template, substituting the per-run
pieces, publishing it, and pointing the journey's email activity at the new id.

Captured from a real create -> save flow (the ftcl_email HAR). The pieces that
change run to run:
  * name      -> "FTCL Tournament <DD.MM>"
  * subject   -> the spec's Email "Title" (ES)
  * preHeader -> the spec's Email "Pre-header" (ES)
  * body copy -> the spec's Email "Description" (ES) — the single editable
                 paragraph block in the captured template
  * link      -> the Smartico tournament deeplink id (swapped in both places)
  * hero img  -> the uploaded photo (the @@EMAIL_HERO_URL@@ token, filled at
                 paste time after the upload, like NC icon / Pop-up bg)

This module only builds the substituted content body; the live create -> save ->
publish calls happen in the console script at paste time, which swaps the
resulting content id into the journey payload via EMAIL_CONTENT_ID_TOKEN.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

# Reuse the same paste-time token GOW uses for the created content id, so the
# journey payload's dextra_email repoint is filled the same way.
from email_content import EMAIL_CONTENT_ID_TOKEN  # noqa: F401  (re-exported)

EMAIL_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "casino" / "tournament_pmcl_email.json"

# Paste-time placeholder for the uploaded hero photo (swapped in by the
# console script after the upload, like the NC icon / Pop-up background)
EMAIL_HERO_TOKEN = "@@EMAIL_HERO_URL@@"

# The single editable body paragraph in the captured template. Its inner HTML
# (emoji lines joined by <br><br>) is what the sheet's Email "Description"
# replaces. Verified unique in the captured source.
_DESC_OPEN = '<p style="margin:0 0 20px 0; font-size:16px;">'
_DESC_RE = re.compile(re.escape(_DESC_OPEN) + r".*?</p>", re.DOTALL)
_LINK_ID_RE = re.compile(r"(_smartico_dp=dp:[A-Za-z0-9_]+&id=)\d+")
# Hero image URL in the topimg section (the main banner image)
_HERO_IMG_RE = re.compile(r'<img src="https://\{\{cdn_hostname\}\}/73b22051-b16d-46e3-90cb-eeb045f59eea/9278b1e0-8f37-42b2-b988-95cf08112a7c\.png"[^>]*>')


def email_name(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"FTCL Tournament {dt:%d.%m}"


def _html_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _desc_to_html(desc: str) -> str:
    """Turn the sheet's multi-line description cell into the template's body
    markup: blank-line-separated paragraphs joined by <br><br>."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", desc.strip()) if p.strip()]
    if not paragraphs:
        paragraphs = [desc.strip()]
    inner = "\n<br><br>\n".join(_html_escape(p) for p in paragraphs)
    return f"{_DESC_OPEN}\n{inner}\n</p>"


def prepare_email_content(
    *,
    date_str: str,
    subject_es: str,
    preheader_es: str,
    desc_es: str,
    tournament_id: str = "",
    upload_hero_image: bool = False,
) -> dict:
    """Return the email-content payload for POST .../email/contents.

    When upload_hero_image is True, the hero image URL is replaced with
    EMAIL_HERO_TOKEN for the console script to fill in after upload.
    """
    content = json.loads(EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8"))
    content["name"] = email_name(date_str)

    comp = content["translations"]["es"]["composition"]
    comp["subject"] = subject_es
    comp["preHeader"] = preheader_es

    src = comp["body"]["source"]
    if desc_es.strip():
        src = _DESC_RE.sub(lambda _m: _desc_to_html(desc_es), src, count=1)
    if tournament_id.strip():
        src = _LINK_ID_RE.sub(r"\g<1>" + tournament_id.strip(), src)
    if upload_hero_image:
        # Replace the hero image with a placeholder token
        src = _HERO_IMG_RE.sub(f'<img src="{EMAIL_HERO_TOKEN}" alt="" style="border-radius: 10px; border: none; width: 100%; max-width: 100%; height: auto;  outline: none; text-decoration: none;display:block;" width="100%">', src)
    comp["body"]["source"] = src
    return content
