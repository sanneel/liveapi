#!/usr/bin/env python3
"""Contract tests for the comms-chain path of journey_composer.py.

Every check here is a failure that reached a composed draft while the build
reported VERIFIED OK — the dangerous class, because nothing looked wrong:

  * a plan normalised to the platform's own wire names was refused as an
    unknown chain type ("notification_center#contract1"), so a linted plan
    could not be built at all
  * a branch written as [{"type": "end_of_path"}] — how the planner and the
    operator both spell "this path just ends" — was refused the same way
  * `lang in name` matched "es" inside "des-en", so the Spanish pass overwrote
    every English description: the EN notification shipped the ES copy
  * the pop-up holds ONE language-independent `link`, so link_en/link_es
    matched nothing and the captured campaign's promo URL survived — the
    pop-up button sent players to the previous promotion
  * an unset `deeplink` kept the reference's in-app URL, so the card was
    correct on web and wrong in the app
  * the SMS card's `displayData` kept the previous campaign's message, so a
    reviewer read the old SMS next to the new messageText
  * artwork left for paste time must reach the script as a picker, and must
    never be able to ship as an unresolved placeholder

No network, no live server. Run: python scripts/test_comms_chain.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "journey-cloner"))

import journey_composer as JC  # noqa: E402

FAILURES: list[str] = []
LINK = "https://jugabet.cl/launch/slots/iframe/pragmatic-jugabet-leyendas-del-olympus-1000"


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
        FAILURES.append(label if not detail else f"{label}: {detail}")


def values(body: dict, name: str) -> list:
    """Every objectForSend variable with this name, across all activities."""
    out = []
    for act in body["activities"]:
        init = act.get("initializationData") or {}
        for v in (init.get("objectForSend") or {}).get("variables") or []:
            if (v.get("name") or "").lower() == name.lower():
                out.append(v.get("value"))
    return out


def spec(**over) -> dict:
    s = {
        "name": "test | comms chain",
        "source": {"type": "segment"},
        "chain": [
            {"type": "nc",
             "title_en": "EN TITLE", "desc_en": "EN DESC", "caption_en": "EN CTA",
             "title_es": "ES TITLE", "desc_es": "ES DESC", "caption_es": "ES CTA",
             "link_en": LINK, "link_es": LINK, "icon": "PICK"},
            {"type": "wait", "wait": "P0Y0M0DT2H0M0S"},
            {"type": "ncsplit",
             "branches": {"NCEngagementSplitPassedPath01": [{"type": "end_of_path"}]}},
            {"type": "popup",
             "title_en": "EN POP", "desc_en": "EN POP DESC", "caption_en": "EN POP CTA",
             "title_es": "ES POP", "desc_es": "ES POP DESC", "caption_es": "ES POP CTA",
             "link_en": LINK, "link_es": LINK, "image": "PICK"},
            {"type": "sms", "text_en": "EN SMS", "text_es": "ES SMS"},
        ],
        "date": "2026-08-01",
    }
    s.update(over)
    return s


print("\nthe canonical wire names round-trip")
for wire in ("notification_center#contract1", "notification_center#contract5"):
    check(f"{wire} resolves as a chain type", JC.ALIASES.get(wire) == wire)
check("every canonical name is also an accepted input",
      not [v for v in set(JC.ALIASES.values()) if v not in JC.ALIASES],
      str([v for v in set(JC.ALIASES.values()) if v not in JC.ALIASES]))

print("\na chain of wire names + a terminal-only branch composes")
try:
    wire_spec = spec()
    wire_spec["chain"][0]["type"] = "notification_center#contract1"
    wire_spec["chain"][3]["type"] = "notification_center#contract5"
    res = JC.compose(wire_spec)
    body = res["body"]
    check("composes", bool(body["activities"]))
    check("verify() passes", not JC.verify(body), str(JC.verify(body)))
except BaseException as exc:                     # SystemExit is the refusal
    check("composes", False, f"{type(exc).__name__}: {exc}")
    body = None

if body:
    print("\neach language lands in its own slot")
    check("des-en keeps the EN copy", values(body, "des-en") == ["EN DESC"],
          str(values(body, "des-en")))
    check("des-es keeps the ES copy", values(body, "des-es") == ["ES DESC"],
          str(values(body, "des-es")))
    check("description_en keeps the EN copy",
          values(body, "description_en") == ["EN POP DESC"],
          str(values(body, "description_en")))
    check("description_es keeps the ES copy",
          values(body, "description_es") == ["ES POP DESC"],
          str(values(body, "description_es")))
    check("title-en keeps the EN copy", values(body, "title-en") == ["EN TITLE"],
          str(values(body, "title-en")))

    print("\nno destination still points at the captured campaign")
    ref_markers = ("junio-de-mundial", "e885e241-af8b-4ef9-9d40-ca211b2e8e0b")
    text = json.dumps(body, ensure_ascii=False)
    for marker in ref_markers:
        check(f"reference URL {marker[:22]} is gone", marker not in text,
              f"{text.count(marker)} occurrences")
    check("the pop-up's language-independent link was set",
          all(v == LINK for v in values(body, "link")), str(values(body, "link")))
    check("no deeplink kept the reference's value",
          all(v == LINK for v in values(body, "deeplink")), str(values(body, "deeplink")))

    print("\nthe builder's own card labels were updated")
    display = [d for act in body["activities"]
               for d in (act.get("initializationData") or {}).get("displayData") or []]
    check("no card label mentions the captured campaign",
          not [d for d in display if "Gran Copa" in str(d) or "Grand Cup" in str(d)],
          str([d for d in display if "Gran Copa" in str(d)])[:120])

    print("\nartwork left for paste time becomes a picker, never a shipped value")
    slots = JC.pick_slots(body)
    check("both artwork slots were found", len(slots) == 2, str(slots))
    check("the NC icon slot is labelled",
          any("NC ICON" in s["label"] for s in slots), str([s["label"] for s in slots]))
    check("the pop-up background slot is labelled",
          any("POP-UP BACKGROUND" in s["label"] for s in slots),
          str([s["label"] for s in slots]))
    out = REPO / "journey-cloner" / "out" / "_test_comms_chain.console.js"
    out.parent.mkdir(parents=True, exist_ok=True)
    JC.emit_console_script(body, out)
    js = out.read_text(encoding="utf-8")
    check("the script opens a file picker", "function pickFile" in js)
    check("the script uploads to the media library", "media-library/v0/folder/" in js)
    check("the script substitutes before the body is parsed",
          js.index("PICK_SLOTS") < js.index("const body = JSON.parse(text)"))
    check("the script refuses on an unresolved placeholder",
          "unresolved artwork placeholder" in js)
    check("no bearer token was written into the script",
          "Bearer ey" not in js and "authorization: '" not in js)
    out.unlink(missing_ok=True)

    print("\na PICK with no script is a failed build, not a composed value")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = JC.cmd_compose(spec(), as_json=False, script=False)
    check("cmd_compose refuses PICK without --script", rc != 0, f"exit {rc}")
    check("the refusal names the artwork", "artwork left for paste time" in buf.getvalue(),
          buf.getvalue()[-160:])

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All comms-chain checks passed.")
