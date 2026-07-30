#!/usr/bin/env python3
"""Contract tests for comms_builder.py — the pick-channels-and-paste path.

The builder's whole claim is that nothing is inferred: the chain is the
operator's picks, every word is a cell in their sheet, and any gap is a refusal
rather than a filled-in guess. These checks are that claim, stated as tests.

  * a channel picked with no copy in the sheet   -> refused (was the whole risk:
    an empty channel ships the captured campaign's words)
  * a split on SMS                               -> refused (no engagement event)
  * a split or wait on an unpicked channel       -> refused
  * a channel picked twice, or none at all       -> refused
  * an unreadable wait                           -> refused
  * a missing link / date / email heading        -> refused
  * the copy that reaches the spec is byte-identical to the sheet's cells
  * the chain order and split/wait placement match what was picked

No network, no model, no live server. Run: python scripts/test_comms_builder.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "journey-cloner"))

import comms_builder as CB  # noqa: E402

FAILURES: list[str] = []

LINK = "https://jugabet.cl/launch/slots/iframe/pragmatic-jugabet-leyendas-del-olympus-1000"
NC_TITLE_ES = "⚡ ¡Llegó el Torneo del Olimpo Legendario!"
NC_DESC_ES = "🏆 Olympus 1000: suma multiplicadores y compite por $1.500.000"
POPUP_TITLE_ES = "⚡ Reina el Olimpo"
EMAIL_SUBJECT_ES = "⚡ Vuélvete leyenda del Olimpo"
SMS_ES = ("JugaBet | ¡Torneo del Olimpo Legendario en vivo! Juega Olympus 1000, "
          "suma multiplicadores y compite por un premio de $1.500.000.")

SHEET = f"""Specifications
Brand\tJugaBet (JBCL)
Event\t"Torneo del Olimpo Legendario" (Pragmatic)
Start date\t01.08.2026 00:01
End date\t31.08.2026 23:59
Link\t{LINK}

Communication channels
Field\tENG\tMax symb\tLeft symb\tESP\tMax symb\tLeft symb
Notification\tTRUE
Title\t⚡ The Legendary Olympus Tournament is here!\t50\t7\t{NC_TITLE_ES}\t50\t9
Description\t🏆 Spin Olympus 1000, stack multipliers and win from $3,000,000\t65\t2\t{NC_DESC_ES}\t65\t3
Button\tJoin the tournament\t20\t1\tUnirme al torneo\t20\t4

Notification Pop-up (Cat-fish)\tTRUE
Title\t⚡ Rule Olympus\t18\t4\t{POPUP_TITLE_ES}\t18\t1
Description\t🔥 Play Olympus 1000\t80\t2\t🔥 Juega Olympus 1000\t80\t3
Button\tJoin now\t20\t12\tParticipar ya\t20\t7

Email\tTRUE
Title\t\t41\t41\t{EMAIL_SUBJECT_ES}\t41\t12
Pre-header\t\t130\t130\t🏆 Torneo del Olimpo Legendario\t130\t27
Button\t\t20\t20\tUnirme al torneo\t20\t4

Sms\tTRUE
Description\tJugaBet | Olympus is live!\t130\t20\t{SMS_ES}\t130\t2
"""


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [OK]   {label}")
    else:
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))
        FAILURES.append(label if not detail else f"{label}: {detail}")


def build(**kw):
    kw.setdefault("sheet_text", SHEET)
    kw.setdefault("channels", ["nc"])
    return CB.build_spec(**kw)


def refuses(label: str, **kw) -> None:
    try:
        build(**kw)
        check(label, False, "built instead of refusing")
    except SystemExit:
        check(label, True)
    except BaseException as exc:
        check(label, False, f"{type(exc).__name__}: {exc}")


def node(spec: dict, kind: str) -> dict:
    for n in spec["chain"]:
        if n["type"] == kind:
            return n
    return {}


print("\nevery gap is a refusal, never a guess")
refuses("a channel with no copy in the sheet",
        sheet_text=SHEET.replace("Sms\tTRUE", "").replace(SMS_ES, ""),
        channels=["nc", "sms"])
refuses("a split on SMS (no engagement event)", channels=["nc", "sms"], splits={"sms"})
refuses("a split on an unpicked channel", channels=["nc"], splits={"email"})
refuses("a wait on an unpicked channel", channels=["nc"], waits={"email": "1d"})
refuses("an unknown channel", channels=["nc", "push"])
refuses("the same channel twice", channels=["nc", "nc"])
refuses("no channels at all", channels=[])
refuses("an unreadable wait", channels=["nc"], waits={"nc": "soon"})
refuses("no Link row and no --link",
        sheet_text=SHEET.replace(f"Link\t{LINK}", ""), channels=["nc"])
refuses("no Start date row and no --date",
        sheet_text=SHEET.replace("Start date\t01.08.2026 00:01", ""), channels=["nc"])
refuses("an email with no heading available",
        sheet_text=SHEET.replace('Event\t"Torneo del Olimpo Legendario" (Pragmatic)', ""),
        channels=["email"])

print("\nthe copy in the spec is the sheet's, byte for byte")
spec, notes = build(channels=["nc", "popup", "email", "sms"])
check("NC title_es", node(spec, "nc").get("title_es") == NC_TITLE_ES,
      repr(node(spec, "nc").get("title_es")))
check("NC desc_es", node(spec, "nc").get("desc_es") == NC_DESC_ES)
check("NC caption_es", node(spec, "nc").get("caption_es") == "Unirme al torneo")
check("pop-up title_es", node(spec, "popup").get("title_es") == POPUP_TITLE_ES)
check("email subject_es", node(spec, "email").get("subject_es") == EMAIL_SUBJECT_ES)
check("SMS text_es", node(spec, "sms").get("text_es") == SMS_ES)
check("the EN copy survives too",
      node(spec, "nc").get("title_en") == "⚡ The Legendary Olympus Tournament is here!")
check("the link is the sheet's Link row",
      node(spec, "nc").get("link_es") == LINK, repr(node(spec, "nc").get("link_es")))
check("the date is the sheet's Start date", spec["date"] == "2026-08-01", spec["date"])
check("the name comes from the sheet's Event",
      spec["name"] == "JBCL | Torneo del Olimpo Legendario | Comms", spec["name"])
check("artwork defaults to a paste-time picker",
      node(spec, "nc").get("icon") == "PICK" and node(spec, "popup").get("image") == "PICK")

print("\nthe chain is exactly what was picked")
spec, _ = build(channels=["nc", "popup", "email", "sms"],
                splits={"nc", "popup", "email"},
                waits={"nc": "2h", "popup": "1d", "email": "1d"})
kinds = [n["type"] for n in spec["chain"]]
check("full chain order", kinds == ["nc", "wait", "ncsplit", "popup", "wait", "ncsplit",
                                   "email", "wait", "emailsplit", "sms"], str(kinds))
check("the wait after NC is 2h",
      spec["chain"][1]["wait"] == "P0Y0M0DT2H0M0S", spec["chain"][1]["wait"])
check("the wait after the pop-up is 1d",
      spec["chain"][4]["wait"] == "P0Y0M1DT0H0M0S", spec["chain"][4]["wait"])

spec, _ = build(channels=["nc", "sms"])
check("two channels, no splits or waits",
      [n["type"] for n in spec["chain"]] == ["nc", "sms"],
      str([n["type"] for n in spec["chain"]]))

spec, _ = build(channels=["popup", "email"], splits={"popup"})
check("a split follows only the channel it was asked for",
      [n["type"] for n in spec["chain"]] == ["popup", "ncsplit", "email"],
      str([n["type"] for n in spec["chain"]]))

print("\nthe email either authors or reuses, never both")
spec, _ = build(channels=["email"], email_template="CSE-0-14726")
check("reusing a CSE carries no authoring settings",
      node(spec, "email") == {"type": "email", "template": "CSE-0-14726"},
      str(node(spec, "email")))
spec, _ = build(channels=["email"])
em = node(spec, "email")
check("authoring sets the hero destination from the link", em.get("hero_link") == LINK)
check("authoring takes the heading from the sheet's Event",
      em.get("heading") == "Torneo del Olimpo Legendario", str(em.get("heading")))
check("authoring never also sets a template", "template" not in em)

print("\nwait shorthand")
for text, iso in (("30m", "P0Y0M0DT0H30M0S"), ("2h", "P0Y0M0DT2H0M0S"),
                  ("1d", "P0Y0M1DT0H0M0S"), ("1w", "P0Y0M7DT0H0M0S"),
                  ("P0Y0M1DT0H0M0S", "P0Y0M1DT0H0M0S")):
    check(f"{text} -> {iso}", CB.parse_wait(text) == iso, CB.parse_wait(text))

print("\nthe sheet's own quirks do not become copy")
from spec_parser import parse_spec  # noqa: E402

_QUIRKY = "\n".join([
    "Specifications",
    "Offer Link\t\t\thttps://jugabet.cl/services/promo/offers/randomizer/raspa-nov",
    "\u0421ommunication channels",
    "\t\tTo do\tText\tMax symb\tLeft symb\t\tTo do\tText\tMax symb\tLeft symb",
    "Notification\t\tTRUE\t\t\t\t\tTRUE",
    "Tittle\t\t\tEN TITLE\t50\t7\t\t\tES TITLE\t50\t9",
    "Description\t\t\tEN DESC\t65\t-12\t\t\tES DESC\t65\t1",
    "Button\t\t\t#VALUE!\t20\t#VALUE!\t\t\tES CTA\t20\t9",
    "Sms ",
    'Description (all sms should begin from: "JugaBet |")\t\tTRUE\tJugaBet | EN\t\t\t\tTRUE\tJugaBet | ES\t130\t31',
])
q = parse_spec(_QUIRKY, expect_game_offer=False)
check("a spreadsheet error cell never becomes copy",
      "#VALUE!" not in (q.nc.caption_en + q.nc.caption_es),
      f"{q.nc.caption_en!r}/{q.nc.caption_es!r}")
check("the error cell is reported, not silently dropped",
      any("error cells" in w for w in q.warnings), str(q.warnings))
check("an 'Offer Link' row is read as the link",
      q.link.endswith("raspa-nov"), repr(q.link))
check("its randomizer slug is still extracted", q.promo_slug == "raspa-nov",
      repr(q.promo_slug))
check("a TRUE on a field row still ticks the channel", q.sms.enabled,
      "sms read as disabled with its copy sitting right there")
check("that inference is reported", any("field row" in w for w in q.warnings),
      str(q.warnings))
check("the real copy either side of the error cell survived",
      q.nc.title_en == "EN TITLE" and q.nc.title_es == "ES TITLE",
      f"{q.nc.title_en!r}/{q.nc.title_es!r}")
check("the negative Left-symb counter is still filtered",
      q.nc.desc_es == "ES DESC", repr(q.nc.desc_es))

print("\nthe variants are the shapes that used to be a script each")
check("every variant declares what it replaces",
      all(v.get("replaces") and v.get("what") for v in CB.VARIANTS.values()),
      str(sorted(CB.VARIANTS)))
for name, v in sorted(CB.VARIANTS.items()):
    bad = [c for c in v["channels"] if c not in CB.CHANNELS]
    check(f"{name}: channels are real", not bad, str(bad))
    bad = [s for s in v["splits"] if s not in CB.SPLIT_NODE]
    check(f"{name}: splits are possible", not bad, str(bad))
    orphan = [s for s in v["splits"] if s not in v["channels"]]
    check(f"{name}: splits sit on its own channels", not orphan, str(orphan))
    orphan = [w for w in v["waits"] if w not in v["channels"]]
    check(f"{name}: waits sit on its own channels", not orphan, str(orphan))
    try:
        spec, _ = build(channels=list(v["channels"]), splits=set(v["splits"]),
                        waits=dict(v["waits"]))
        check(f"{name}: builds from the sheet", bool(spec["chain"]))
    except BaseException as exc:
        check(f"{name}: builds from the sheet", False, f"{type(exc).__name__}: {exc}")

check("no variant claims a brand the node library cannot build",
      not [k for k, v in CB.VARIANTS.items() if "pmcl" in k.lower()],
      "PMCL needs its own capture in journey_composer.SOURCES first")

print("\nthe registry points at one comms entry point")
sys.path.insert(0, str(REPO))
from app.services.promotions_catalog import GENERATORS, unlisted_generators  # noqa: E402
check("no script is unregistered", not unlisted_generators(), str(unlisted_generators()))
entry = [g for g in GENERATORS if g["key"] == "comms_builder"]
check("the comms builder is registered", len(entry) == 1)
superseded = [g for g in GENERATORS if g.get("superseded_by")]
check("superseded generators name their replacement",
      all(any(x["key"] == g["superseded_by"] for x in GENERATORS) for g in superseded),
      str([g["key"] for g in superseded]))
check("the JBCL comms scripts are marked superseded",
      {g["key"] for g in superseded} >= {"gow_comms", "sport_comms", "nc_discount"},
      str(sorted(g["key"] for g in superseded)))
check("no PMCL generator is marked superseded",
      not [g for g in superseded if g["brand"] == "PMCL"],
      str([g["key"] for g in superseded if g["brand"] == "PMCL"]))

print("\nthe built spec actually composes and verifies")
try:
    import journey_composer as JC
    spec, _ = build(channels=["nc", "popup", "email", "sms"],
                    splits={"nc", "popup", "email"},
                    waits={"nc": "2h", "popup": "1d", "email": "1d"})
    res = JC.compose(spec)
    check("composes", bool(res["body"]["activities"]))
    check("verify() passes", not JC.verify(res["body"]), str(JC.verify(res["body"])))
    check("an email content was authored", isinstance(res.get("email_content"), dict))
    text = __import__("json").dumps(res["body"], ensure_ascii=False)
    check("the sheet's ES copy reached the journey", NC_TITLE_ES in text and SMS_ES in text)
    check("nothing still points at the captured campaign",
          "junio-de-mundial" not in text, f"{text.count('junio-de-mundial')} left")
except BaseException as exc:
    check("composes", False, f"{type(exc).__name__}: {exc}")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All comms-builder checks passed.")
