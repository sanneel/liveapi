#!/usr/bin/env python3
"""Structural substitution for backoffice comms journeys — the shared engine.

Both `sport_comms_campaign.py` and `tournament_pmcl_campaign.py` build the same
family of journey: `notification_center` ("JBCL NC Dynamic 2026", template 1935)
+ `notification_center` ("JBCL Pop-up CatFish 2026", template 20678) +
`dextra_sms` + `dextra_email`, stored twice (compiled `activities[]` and the
`rawJourneyData` editor mirror). The rules for rewriting their copy without
shipping the previous campaign's text are identical, and were paid for once while
building `sport_comms`. This module is that engine, so the two generators cannot
drift.

Why copy is NOT string-replaced (the trap this exists to prevent): the captured
EN and ES slots hold *identical* strings for title / description / caption, each
value appears 8–16 times (compiled activity + `objectForSend.variables` + the
mirror), and different channels reuse the same literal (the pop-up's caption is
the same `"¡Quiero entrar!"` as the notification's). A global `.replace()` writes
one language into every slot and gives one channel another's copy — while every
leftover-detection check still passes, because the captured literal *is* gone.
Everything here addresses fields by the NAME the template already encodes
(`title-en`, `caption_es`, `des-en`, `description_es`), in both storages.
"""
from __future__ import annotations

import json
import re

# The per-language field names the templates use. The notification node spells
# them with hyphens (`title-en`), the pop-up with underscores (`title_en`); both
# are matched. `des` and `description` are the same field under two names.
_LANG_FIELD_RE = re.compile(r"^(title|des|description|caption)[-_](en|es)$")


def json_escape(value: str) -> str:
    """A string as it appears inside the serialized template (for exact swaps)."""
    return json.dumps(value, ensure_ascii=False)[1:-1]


def comms_node(node_name: str):
    """Predicate: a `notification_center` whose singleChannel is `node_name`."""
    def match(a: dict) -> bool:
        init = a.get("initializationData") or {}
        return (a.get("activityName") == "notification_center"
                and (init.get("singleChannel") or {}).get("activityName") == node_name)
    return match


def storages(body: dict, predicate):
    """Every dict holding a matched activity's settings — compiled AND mirror.

    A journey lives twice. Writing one storage and not the other is the
    blank-canvas bug, so every structural write goes through here.
    """
    cfg = body.get("rawJourneyData", {}).get("activitiesConfiguration", {})
    for a in body.get("activities", []):
        if not predicate(a):
            continue
        yield a.get("initializationData") or {}
        mirror = cfg.get(a.get("activityId"))
        if isinstance(mirror, dict) and isinstance(mirror.get("data"), dict):
            yield mirror["data"]


def set_channel_copy(body: dict, node_name: str, copy: dict) -> int:
    """Write one comms node's per-language copy into both storages.

    `copy` maps a field base ("title" / "description" / "caption") to
    {"en": ..., "es": ...}. Only fields the template already carries are written,
    and `%placeholder%` values are left alone — they are template references, not
    copy. Returns the number of slots written (0 means the node was not found —
    the caller should refuse rather than ship the captured copy).
    """
    writes = 0
    for store in storages(body, comms_node(node_name)):
        tabs = (store.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
        for lang_tab in tabs.values():
            if not isinstance(lang_tab, dict):
                continue
            for key, value in list(lang_tab.items()):
                m = _LANG_FIELD_RE.match(key)
                if not m or (isinstance(value, str) and value.startswith("%")):
                    continue
                base = "description" if m.group(1) in ("des", "description") else m.group(1)
                lang = m.group(2)
                if base in copy and copy[base].get(lang):
                    lang_tab[key] = copy[base][lang]
                    writes += 1
        for var in (store.get("objectForSend") or {}).get("variables") or []:
            m = _LANG_FIELD_RE.match(var.get("name") or "")
            if not m or str(var.get("value", "")).startswith("%"):
                continue
            base = "description" if m.group(1) in ("des", "description") else m.group(1)
            lang = m.group(2)
            if base in copy and copy[base].get(lang):
                var["value"] = copy[base][lang]
                writes += 1
    return writes


def set_sms_text(body: dict, en: str, es: str) -> int:
    """Write SMS copy into every place the capture keeps it, per language.

    The capture holds the same string five times — `rawValues.messageText`, the
    two `rawValues.localizedMessageTexts` entries and both
    `smsSettings.localizedMessageTexts` entries — plus the mirror. String-
    replacing the literal wrote the Spanish text into the English slot too.
    """
    by_lang = {"en": en, "es": es}
    writes = 0
    for store in storages(body, lambda a: a.get("activityName") == "dextra_sms"):
        for holder_key in ("rawValues", "smsSettings"):
            holder = store.get(holder_key)
            if not isinstance(holder, dict):
                continue
            if isinstance(holder.get("messageText"), str):
                holder["messageText"] = es          # the default/primary copy
                writes += 1
            loc = holder.get("localizedMessageTexts")
            if isinstance(loc, dict):               # rawValues: {"en": {...}}
                for lang, entry in loc.items():
                    if isinstance(entry, dict) and by_lang.get(lang):
                        entry["messageText"] = by_lang[lang]
                        writes += 1
            elif isinstance(loc, list):             # smsSettings: [{languageCode}]
                for entry in loc:
                    lang = entry.get("languageCode")
                    if by_lang.get(lang):
                        entry["messageText"] = by_lang[lang]
                        writes += 1
    return writes


# Link fields a comms node carries. `link`/`deeplink` live once in the `common`
# tab; `link-en`/`link-es` are the per-language copies the notification node
# keeps. Everything else that mentions a link (`buttons_1_link`,
# `buttons_1_deeplink`) holds a `%reference%` to one of these, never a URL.
_LINK_FIELDS = {"link", "deeplink", "link-en", "link-es", "link_en", "link_es"}


def set_channel_link(body: dict, node_name: str, url: str) -> int:
    """Point one comms node's every link field at `url`, in both storages.

    A `%…%` value is a template reference (`%link-en%?%$utm_tags%`) that resolves
    to one of the fields written here — rewriting it would break the reference,
    so it is left alone. Returns the number of slots written; 0 means the node
    was not found and the caller must refuse rather than ship the captured link.
    """
    writes = 0
    for store in storages(body, comms_node(node_name)):
        tabs = (store.get("singleChannel") or {}).get("localizedLanguagesTab") or {}
        for lang_tab in tabs.values():
            if not isinstance(lang_tab, dict):
                continue
            for key, value in list(lang_tab.items()):
                if key in _LINK_FIELDS and not str(value).startswith("%"):
                    lang_tab[key] = url
                    writes += 1
        for var in (store.get("objectForSend") or {}).get("variables") or []:
            if var.get("name") in _LINK_FIELDS and not str(var.get("value", "")).startswith("%"):
                var["value"] = url
                writes += 1
    return writes


def set_expire_after(body: dict, days: int) -> int:
    """Set every notification node's revoke period, in both storages.

    `objectForSend.expire_after` is a .NET timespan ("9.00:00:00.000"): how long
    the notification stays in the player's centre before it is revoked. It has to
    match the tournament's length, or a tournament that ended last week is still
    sitting in the centre — the capture's own 9/18 days shipped otherwise.
    """
    value = f"{max(int(days), 1)}.00:00:00.000"
    writes = 0
    for store in storages(body, lambda a: a.get("activityName") == "notification_center"):
        obj = store.get("objectForSend")
        if isinstance(obj, dict) and "expire_after" in obj:
            obj["expire_after"] = value
            writes += 1
    return writes


def set_display_data(body: dict, predicate, new_value: str) -> int:
    """Rewrite a node's canvas label, in both the activity and the mirror.

    `displayData` is what the journey builder prints on a node. It duplicates the
    copy, and in the mirror it hangs off the config entry itself rather than its
    `data` — so anything that walks *settings* misses it. Left alone, the SMS node
    shows the previous campaign's whole message on the canvas and the email node
    its name. Every string element is replaced (the label IS the value there;
    matching on content breaks once an earlier substitution has rewritten part
    of it).
    """
    cfg = body.get("rawJourneyData", {}).get("activitiesConfiguration", {})
    writes = 0
    for a in body.get("activities", []):
        if not predicate(a):
            continue
        holders = [a.get("initializationData") or {}]
        mirror = cfg.get(a.get("activityId"))
        if isinstance(mirror, dict):
            holders.append(mirror)          # note: mirror itself, not mirror["data"]
        for holder in holders:
            dd = holder.get("displayData")
            if not isinstance(dd, list):
                continue
            for i, item in enumerate(dd):
                if isinstance(item, str):
                    dd[i] = new_value
                    writes += 1
    return writes


# ── structural integrity checks (shared verify helpers) ─────────────────
SCAFFOLDING = {"default", "parallelFlow", "exit", "flowEntry", "dropZone",
               "emptyEdge", "dropEdge", "mergeEdge", "joinEdge"}


def dangling_edges(body: dict) -> list:
    """Completion events whose `nextActivityId` resolves to no activity."""
    acts = {a.get("activityId") for a in body.get("activities", [])}
    return [
        ev.get("nextActivityId")
        for a in body.get("activities", [])
        for ev in (a.get("events") or [])
        if ev.get("nextActivityId") and ev.get("nextActivityId") not in acts
    ]


def unknown_canvas_nodes(body: dict) -> list:
    """Canvas nodes that are neither an activity nor known scaffolding."""
    acts = {a.get("activityId") for a in body.get("activities", [])}
    els = body.get("rawJourneyData", {}).get("elements", [])
    return [e.get("id") for e in els
            if e.get("id") not in acts and e.get("type") not in SCAFFOLDING]


def activity_nodes_without_position(body: dict) -> list:
    """Activity nodes missing `position`/`positionAbsolute` (the blank-canvas
    crash). Scaffolding legitimately has neither, so it is excluded."""
    acts = {a.get("activityId") for a in body.get("activities", [])}
    els = body.get("rawJourneyData", {}).get("elements", [])
    return [
        e.get("id") for e in els
        if e.get("id") in acts
        and not (isinstance(e.get("position"), dict)
                 and isinstance(e.get("positionAbsolute"), dict))
    ]


def canvas_edges_to_missing_node(body: dict) -> list:
    """Edges whose source/target is not a rendered node — a broken connection."""
    els = body.get("rawJourneyData", {}).get("elements", [])
    node_ids = {e.get("id") for e in els if e.get("type") != "default"}
    return [e.get("id") for e in els
            if e.get("type") == "default"
            and (e.get("source") not in node_ids or e.get("target") not in node_ids)]


def backfill_position_absolute(body: dict) -> int:
    """Give every node a `positionAbsolute`, copied from `position` when null.

    COMPOSER_RULES rule 1: a missing/null `positionAbsolute` throws
    `Cannot read properties of undefined (reading 'x')` in the editor's layout
    pass → blank canvas. Some real captures save a node with `position` set but
    `positionAbsolute: null` (the tournament HAR had three), so a generator that
    re-templates from a capture must repair it rather than ship the crash.
    """
    fixed = 0
    for e in body.get("rawJourneyData", {}).get("elements", []):
        pos = e.get("position")
        if isinstance(pos, dict) and not isinstance(e.get("positionAbsolute"), dict):
            e["positionAbsolute"] = dict(pos)
            fixed += 1
    return fixed
