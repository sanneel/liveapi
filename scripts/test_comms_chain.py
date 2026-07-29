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

print("\nthe email's copy is authored, not borrowed")


def email_spec(**email):
    return {"name": "test | email", "source": {"type": "segment"},
            "chain": [{"type": "nc", "desc_es": "D", "link_es": LINK,
                       "icon": "https://example.com/i.png"},
                      dict({"type": "email"}, **email),
                      {"type": "sms", "text_es": "JugaBet | S"}],
            "date": "2026-08-01"}


def refuses(label: str, **email) -> None:
    try:
        JC.compose(email_spec(**email))
        check(label, False, "composed instead of refusing")
    except SystemExit:
        check(label, True)
    except BaseException as exc:
        check(label, False, f"{type(exc).__name__}: {exc}")


refuses("reusing a CSE and authoring at once is refused",
        template="CSE-0-14726", subject_es="S")
refuses("authoring without promo_page_id is refused (the hero IS the CTA)",
        subject_es="S", preheader_es="P", hero="PICK")

try:
    res = JC.compose(email_spec(subject_es="SUBJ", preheader_es="PRE", heading="HEAD",
                                hero="PICK", promo_page_id="abc-123"))
    content = res["email_content"]
    check("a content payload was built", isinstance(content, dict))
    comp = content["translations"]["es"]["composition"]
    check("the subject is the operator's", comp["subject"] == "SUBJ", comp["subject"])
    check("the pre-header is the operator's", comp["preHeader"] == "PRE", comp["preHeader"])
    check("the heading reached the HTML", "HEAD" in comp["body"]["source"])
    check("the promo page reached the HTML", "promoPage/abc-123" in comp["body"]["source"])
    check("the hero is left for paste time",
          JC.EMAIL_HERO_TOKEN in comp["body"]["source"])
    check("no other placeholder survived in the HTML",
          not [t for t in set(__import__("re").findall(r"@@[A-Z_]+@@", comp["body"]["source"]))
               if t != JC.EMAIL_HERO_TOKEN])
    body = res["body"]
    check("the journey is repointed at the id the script will get",
          JC.EMAIL_CONTENT_ID_TOKEN in json.dumps(body))
    check("verify() passes on an authored-email chain", not JC.verify(body),
          str(JC.verify(body)))

    out = REPO / "journey-cloner" / "out" / "_test_email.console.js"
    JC.emit_console_script(body, out, content)
    js = out.read_text(encoding="utf-8")
    check("the script creates the content", "/email/contents" in js)
    check("the script publishes it", "/publish" in js)
    check("the hero is referenced via cdn_hostname, not the absolute URL",
          "{{cdn_hostname}}' + asset.relative_link" in js)
    check("the email is authored before the draft is POSTed",
          js.index("authorEmail") < js.index("const body = JSON.parse(text)"))
    check("an incomplete repoint refuses", "email repoint incomplete" in js)
    check("no bearer token was written into the script", "Bearer ey" not in js)
    out.unlink(missing_ok=True)
except BaseException as exc:
    check("an authored-email chain composes", False, f"{type(exc).__name__}: {exc}")

print("\nthe email content name is one Content Studio will accept")
# It rejects *@#?|&<>"'/ with 422 RESTRICTED_SYMBOLS_IN_CONTENT_NAME. Journey
# names here are pipe-separated and the default content name is derived from one,
# so every authored email failed at paste time — after four images were uploaded.
for raw, want_clean in [
    ("JBCL | Torneo del Olimpo Legendario | Comms — 2026-08-01", True),
    ("Promo #1 & friends <today>", True),
    ('Torneo "Olimpo"/x?y*z@w', True),
]:
    got = JC.clean_email_name(raw)
    bad = [ch for ch in got if ch in JC.EMAIL_NAME_FORBIDDEN]
    check(f"cleaned {raw[:34]!r}", not bad and bool(got), f"{got!r} left {bad}")
check("a real hyphen and date survive cleaning",
      JC.clean_email_name("JBCL | x — 2026-08-01").endswith("2026-08-01"),
      JC.clean_email_name("JBCL | x — 2026-08-01"))
check("a name of nothing but forbidden symbols cleans to empty",
      JC.clean_email_name("|||") == "", repr(JC.clean_email_name("|||")))

try:
    res = JC.compose(email_spec(subject_es="S", preheader_es="P", desc_es="D",
                                hero="PICK", cta="PICK", hero_link=LINK))
    nm = res["email_content"]["name"]
    check("the built content name carries no forbidden symbol",
          not [ch for ch in nm if ch in JC.EMAIL_NAME_FORBIDDEN], repr(nm))
    check("the rename is reported, not silent",
          any("content name" in line for line in res["report"]),
          str(res["report"][-2:]))
    check("the journey keeps its own pipe-separated name",
          "|" in res["body"]["journeyName"], res["body"]["journeyName"])
except BaseException as exc:
    check("an authored email names its content acceptably", False,
          f"{type(exc).__name__}: {exc}")

refuses("a content name that is only forbidden symbols",
        subject_es="S", desc_es="D", hero_link=LINK, email_name="|||")

print("\nthe composed-body artefact never costs the operator their script")
# The name-derived out/ path is shared by every run for a campaign. A file left
# there by a run under another user (a root shell run, say) made every later
# admin run die with EACCES on a path nobody asked about, after the journey had
# already composed and verified.
import os
import stat
import subprocess
_basename = "test_comms_chain_perm"
_json = REPO / "journey-cloner" / "out" / f"{_basename}.journey.json"
_js = REPO / "journey-cloner" / "console_scripts" / f"{_basename}_console.js"
try:
    # A full spec: cmd_compose also runs the inherited-content audit, which
    # (rightly) refuses a chain whose nodes still carry the reference's copy.
    spec = spec()
    spec["chain"].append({"type": "email", "subject_es": "S", "preheader_es": "P",
                          "desc_es": "D", "hero": "PICK", "cta": "PICK",
                          "hero_link": LINK})
    rc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import json, journey_composer as JC; "
         "JC.cmd_compose(json.loads(sys.stdin.read()), as_json=False, script=True, "
         "basename=%r)" % (str(REPO / "journey-cloner"), _basename)],
        input=json.dumps(spec), capture_output=True, text=True, cwd=REPO / "journey-cloner")
    check("a basename run writes its own out/ file, not the shared slug path",
          _json.exists(), f"exit {rc.returncode}: {rc.stderr[-160:]}")
    check("the console script was written", _js.exists())

    # Now make out/ unwritable and confirm the script still arrives.
    outdir = REPO / "journey-cloner" / "out"
    mode = stat.S_IMODE(outdir.stat().st_mode)
    _json.unlink(missing_ok=True)
    _js.unlink(missing_ok=True)
    try:
        outdir.chmod(0o555)
        writable = os.access(outdir, os.W_OK)
        rc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); import json, journey_composer as JC; "
             "JC.cmd_compose(json.loads(sys.stdin.read()), as_json=False, script=True, "
             "basename=%r)" % (str(REPO / "journey-cloner"), _basename)],
            input=json.dumps(spec), capture_output=True, text=True,
            cwd=REPO / "journey-cloner")
        if writable:
            # Running as root: chmod cannot make it unwritable, so this half of
            # the check is not exercised. Say so instead of passing silently.
            print("  [SKIP] unwritable out/ — running as a user chmod cannot restrict")
        else:
            check("an unwritable out/ still yields the console script", _js.exists(),
                  f"exit {rc.returncode}: {rc.stderr[-200:]}")
            check("it warns rather than raising", "WARN" in rc.stdout and not rc.stderr.strip(),
                  f"stdout={rc.stdout[-120:]!r} stderr={rc.stderr[-120:]!r}")
    finally:
        outdir.chmod(mode)
finally:
    _json.unlink(missing_ok=True)
    _js.unlink(missing_ok=True)

print("\nthe text_body creative carries the brief's own paragraphs")
DESC = ("⚡ Los dioses te llaman.\n\n🎰 Juega Olympus 1000, apuesta mínima $25.\n\n"
        "🏆 49 posiciones se reparten $3.000.000.\n\n⏳ Del 1 al 31 de agosto.")
try:
    res = JC.compose(email_spec(subject_es="SUBJ", preheader_es="PRE", desc_es=DESC,
                                hero="PICK", cta="PICK", hero_link=LINK))
    src = res["email_content"]["translations"]["es"]["composition"]["body"]["source"]
    check("the creative with a text body was chosen", "@@EMAIL_CTA_URL@@" in src)
    check("all four paragraphs are in the body", src.count("<br><br>") == 3,
          f"{src.count('<br><br>')} separators")
    for frag in ("Los dioses te llaman", "apuesta mínima $25", "49 posiciones",
                 "1 al 31 de agosto"):
        check(f"body carries {frag!r}", frag in src)
    check("the captured campaign's copy is gone",
          "Leyendas Ganadoras" not in src and "8.000.000" not in src)
    check("both hrefs are the operator's link", src.count(LINK) == 2,
          f"{src.count(LINK)} occurrences")
    check("the shared footer block is kept", "[[block(CSE-0-6615)]]" in src)
    check("hero and CTA are both left for the picker",
          JC.EMAIL_HERO_TOKEN in src and JC.EMAIL_CTA_TOKEN in src)
    check("markup in the copy is escaped, not injected",
          "&lt;script&gt;" in JC._desc_to_html("<script>x</script>"),
          JC._desc_to_html("<script>x</script>"))
    out = REPO / "journey-cloner" / "out" / "_test_textbody.console.js"
    JC.emit_console_script(res["body"], out, res["email_content"])
    js = out.read_text(encoding="utf-8")
    check("the script asks for both email images",
          js.count('"label": "the EMAIL HERO image"') == 1
          and js.count('"label": "the EMAIL CTA BUTTON image"') == 1)
    check("an unfilled email image refuses",
          "email image placeholder was left unfilled" in js)
    out.unlink(missing_ok=True)
except BaseException as exc:
    check("a text_body email composes", False, f"{type(exc).__name__}: {exc}")

refuses("a body given to the creative that has no body slot",
        subject_es="S", desc_es=DESC, hero_link=LINK, creative="hero_only")
refuses("a heading given to the creative that has no heading slot",
        subject_es="S", heading="H", hero_link=LINK, creative="text_body")
refuses("the text_body creative with no body copy",
        subject_es="S", hero="PICK", hero_link=LINK, creative="text_body")
refuses("an unknown creative name",
        subject_es="S", hero_link=LINK, creative="fancy")

print("\na brand's players are never sent another brand's creative")
import os
import subprocess
probe = (
    "import sys; sys.path.insert(0,'journey-cloner');"
    "import journey_composer as JC;"
    "spec={'name':'p','source':{'type':'segment'},'chain':["
    "{'type':'nc','desc_es':'x','link_es':'https://jugabet.cl/x','icon':'https://e/i.png'},"
    "{'type':'email','subject_es':'S','heading':'H','promo_page_id':'abc'}],'date':'2026-08-01'};"
    "JC.compose(spec)"
)
env = dict(os.environ, BRAND="PMCL")
rc = subprocess.run([sys.executable, "-c", probe], cwd=REPO, env=env,
                    capture_output=True, text=True)
check("a PMCL run refuses the JBCL email creative", rc.returncode != 0,
      f"exit {rc.returncode}")
check("the refusal names the brand mismatch", "brand swap" in rc.stderr,
      rc.stderr.strip()[-160:])

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All comms-chain checks passed.")
