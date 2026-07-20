"""Parser for the pasted spreadsheet-style GOW spec blob.

The marketing team copies a block of cells out of a spreadsheet (tab-separated,
with the "Offer" cell quoted because it spans multiple lines) and pastes it
into one textarea. This module turns that raw paste into the structured
values the campaign/comms generators need: game name, provider, bet tiers,
and the per-channel EN/ES copy for Notification, Pop-up (Cat-fish) and Sms.

Column counts in the paste are not reliable (spreadsheets leave empty tab
cells inconsistently), so fields are located by row label rather than by
column index, and EN/ES values are picked out of a row by filtering out
empty cells, pure-number cells (the "Max symb"/"Left symb" counters) and
TRUE/FALSE cells, then taking the first remaining value as EN and the
second as ES.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field


_BOOL_RE = re.compile(r"^(true|false)$", re.IGNORECASE)
_NUM_RE = re.compile(r"^[\d.,]+$")
_BET_RE = re.compile(r"bet\s*\$\s*([\d.,]+)", re.IGNORECASE)
_TRADEMARK_RE = re.compile(r"[™®©]")

# Channel section labels (lowercased, substring-matched) we care about.
_NOTIFICATION = "notification"
_POPUP = "notification pop-up"
_SMS = "sms"
_EMAIL = "email"
_KNOWN_CHANNEL_PREFIXES = (
    # More specific prefixes must be checked before shorter ones they
    # contain (e.g. "notification pop-up..." also starts with
    # "notification", so it has to win the match first).
    _POPUP,
    _NOTIFICATION,
    _EMAIL,
    _SMS,
    "promo lobby",
    "slider",
)


@dataclass
class ChannelCopy:
    enabled: bool = False
    title_en: str = ""
    title_es: str = ""
    desc_en: str = ""
    desc_es: str = ""
    caption_en: str = ""
    caption_es: str = ""


@dataclass
class SmsCopy:
    enabled: bool = False
    text_en: str = ""
    text_es: str = ""


@dataclass
class EmailCopy:
    enabled: bool = False
    subject_en: str = ""
    subject_es: str = ""
    preheader_en: str = ""
    preheader_es: str = ""
    desc_en: str = ""
    desc_es: str = ""
    button_en: str = ""
    button_es: str = ""


@dataclass
class ParsedSpec:
    game_name: str = ""
    provider: str = ""
    provider_name: str = ""
    bets: list = field(default_factory=list)
    offer_text: str = ""
    tournament_start_date: str = ""  # ISO format YYYY-MM-DD, or empty if not in spec
    tournament_end_date: str = ""    # ISO format YYYY-MM-DD, or empty if not in spec
    nc: ChannelCopy = field(default_factory=ChannelCopy)
    popup: ChannelCopy = field(default_factory=ChannelCopy)
    sms: SmsCopy = field(default_factory=SmsCopy)
    email: EmailCopy = field(default_factory=EmailCopy)
    warnings: list = field(default_factory=list)


def _row_values(row: list, start_idx: int = 1) -> list:
    """Non-empty, non-numeric, non-boolean cells after the label column."""
    out = []
    for cell in row[start_idx:]:
        c = (cell or "").strip()
        if not c:
            continue
        if _NUM_RE.match(c):
            continue
        if _BOOL_RE.match(c):
            continue
        out.append(c)
    return out


def _row_bool(row: list) -> bool:
    for cell in row:
        c = (cell or "").strip().lower()
        if c == "true":
            return True
        if c == "false":
            return False
    return False


def _channel_key(label: str) -> str:
    low = label.strip().lower()
    for prefix in _KNOWN_CHANNEL_PREFIXES:
        if low.startswith(prefix):
            return prefix
    return ""


def _parse_date(date_str: str) -> str:
    """Parse date string like '20.07.2026' or '20.07.2026 00:00' to 'YYYY-MM-DD'."""
    if not date_str:
        return ""
    # Extract just the date part (before any time)
    date_part = date_str.split()[0] if date_str else ""
    parts = date_part.split(".")
    if len(parts) == 3:
        try:
            day, month, year = parts
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        except (ValueError, IndexError):
            return ""
    return ""


def _parse_offer(offer_text: str, spec: ParsedSpec) -> None:
    spec.offer_text = offer_text
    lines = [l.strip() for l in offer_text.splitlines() if l.strip()]
    game_line = next((l for l in reversed(lines) if "|" in l), "")
    if game_line:
        game_part, _, provider_part = game_line.partition("|")
        game_name = _TRADEMARK_RE.sub("", game_part).strip()
        provider_name = _TRADEMARK_RE.sub("", provider_part).strip()
        spec.game_name = game_name
        spec.provider_name = provider_name
        spec.provider = provider_name.lower()
    else:
        spec.warnings.append("Offer text has no \"Game | Provider\" line.")

    bets = []
    for m in _BET_RE.finditer(offer_text):
        raw = m.group(1).replace(".", "").replace(",", "")
        if raw.isdigit():
            bets.append(int(raw))
    spec.bets = bets
    if not bets:
        spec.warnings.append("No \"bet $...\" values found in the Offer text.")


def parse_spec(text: str) -> ParsedSpec:
    spec = ParsedSpec()
    reader = csv.reader(io.StringIO(text), delimiter="\t", quotechar='"')
    rows = [row for row in reader if any((c or "").strip() for c in row)]

    current_channel = ""
    field_rows: dict = {}  # channel -> list[(label, en, es)]

    for row in rows:
        label = (row[0] or "").strip()
        if not label:
            continue

        if label.lower() == "offer":
            offer_value = ""
            for cell in row[1:]:
                if (cell or "").strip():
                    offer_value = cell
                    break
            _parse_offer(offer_value, spec)
            continue

        if label.lower() == "start date":
            date_value = ""
            for cell in row[1:]:
                if (cell or "").strip():
                    date_value = cell
                    break
            spec.tournament_start_date = _parse_date(date_value)
            continue

        if label.lower() == "end date":
            date_value = ""
            for cell in row[1:]:
                if (cell or "").strip():
                    date_value = cell
                    break
            spec.tournament_end_date = _parse_date(date_value)
            continue

        channel = _channel_key(label)
        if channel:
            if channel == _POPUP and "cat-fish" not in label.lower():
                # Only the Cat-fish pop-up is wired up today. The Push variant
                # shares the same "Notification pop-up..." prefix, so without
                # this it would keep current_channel pointed at _POPUP and its
                # (usually empty) rows would land in the same field_rows list,
                # overwriting the real Cat-fish copy below.
                current_channel = ""
                continue
            current_channel = channel
            field_rows.setdefault(channel, [])
            if channel == _NOTIFICATION:
                spec.nc.enabled = _row_bool(row)
            elif channel == _POPUP:
                spec.popup.enabled = _row_bool(row)
            elif channel == _SMS:
                spec.sms.enabled = _row_bool(row)
            elif channel == _EMAIL:
                spec.email.enabled = _row_bool(row)

            # Extract field name if label is "Channel FieldName" (e.g., "Notification Title")
            # or "Channel (descriptor) FieldName" (e.g., "Notification Pop-up (Cat-fish) Title")
            field_name = label[len(next(prefix for prefix in _KNOWN_CHANNEL_PREFIXES if label.lower().startswith(prefix))):].strip()
            # Remove descriptor in parentheses (e.g., "(Cat-fish)")
            field_name = re.sub(r'\s*\([^)]*\)\s*', ' ', field_name).strip()
            if field_name:
                values = _row_values(row)
                en = values[0] if len(values) >= 1 else ""
                es = values[1] if len(values) >= 2 else en
                field_rows[channel].append((field_name.lower(), en, es))
            continue

        if not current_channel:
            continue

        values = _row_values(row)
        en = values[0] if len(values) >= 1 else ""
        es = values[1] if len(values) >= 2 else en
        field_rows[current_channel].append((label.lower(), en, es))

    def _fill_channel(target: ChannelCopy, rows_for_channel: list) -> None:
        for label, en, es in rows_for_channel:
            if label.startswith("tit"):
                # Matches both "Title" and the sheet's "Tittle" spelling.
                target.title_en, target.title_es = en, es
            elif "desc" in label:
                target.desc_en, target.desc_es = en, es
            elif "button" in label or "caption" in label:
                target.caption_en, target.caption_es = en, es

    _fill_channel(spec.nc, field_rows.get(_NOTIFICATION, []))
    _fill_channel(spec.popup, field_rows.get(_POPUP, []))

    sms_rows = field_rows.get(_SMS, [])
    if sms_rows:
        _, en, es = sms_rows[0]
        spec.sms.text_en, spec.sms.text_es = en, es

    for label, en, es in field_rows.get(_EMAIL, []):
        if label.startswith("tit"):
            # "Tittle"/"Title" row = the email subject line.
            spec.email.subject_en, spec.email.subject_es = en, es
        elif "header" in label:
            # "Pre-header" row.
            spec.email.preheader_en, spec.email.preheader_es = en, es
        elif "desc" in label:
            # "Description" row = the email body copy (may be multi-line).
            spec.email.desc_en, spec.email.desc_es = en, es
        elif "button" in label or "caption" in label:
            spec.email.button_en, spec.email.button_es = en, es

    if spec.nc.enabled and not (spec.nc.title_en and spec.nc.desc_en and spec.nc.caption_en):
        spec.warnings.append("Notification is ticked TRUE but some Notification fields are missing.")
    if spec.popup.enabled and not (spec.popup.title_en and spec.popup.desc_en and spec.popup.caption_en):
        spec.warnings.append("Pop-up (Cat-fish) is ticked TRUE but some Pop-up fields are missing.")
    if spec.sms.enabled and not (spec.sms.text_en and spec.sms.text_es):
        spec.warnings.append("Sms is ticked TRUE but the Sms text is missing.")
    if spec.email.enabled and not (spec.email.subject_es and spec.email.preheader_es):
        spec.warnings.append("Email is ticked TRUE but the subject/pre-header is missing.")

    return spec


if __name__ == "__main__":
    import sys

    raw = sys.stdin.read()
    result = parse_spec(raw)
    print("game_name:", result.game_name)
    print("provider:", result.provider)
    print("provider_name:", result.provider_name)
    print("bets:", result.bets)
    print("nc:", result.nc)
    print("popup:", result.popup)
    print("sms:", result.sms)
    print("email:", result.email)
    print("warnings:", result.warnings)
