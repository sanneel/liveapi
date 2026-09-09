#!/usr/bin/env python3
"""Pick channels, splits and waits; paste the sheet; get the console script.

Why this exists: composing a comms chain by hand meant hand-writing a spec, and
asking a model to write one meant trusting it not to invent copy, links or a
chain shape. Neither is necessary — every input here is either a choice the
operator makes explicitly or a cell the parser reads out of their sheet.

    NOTHING IS INFERRED.
      * the chain shape  <- the channels/splits/waits the operator picked
      * every word of copy <- spec_parser.py reading the pasted sheet
      * the link          <- the sheet's "Link" row
      * the journey body  <- journey_composer.py cloning captured nodes

    A channel with no copy in the sheet is refused, not filled in. A split on a
    channel that has no engagement event is refused. Nothing is guessed and no
    model is called, so there is nothing to hallucinate.

Shape produced (only the parts asked for):

    segment -> NC -> [wait] -> [NC split] -> Pop-up -> [wait] -> [Pop-up split]
            -> Email -> [wait] -> [Email split] -> SMS -> end

Run:
    python comms_builder.py --sheet sheet.tsv --channels nc,popup,email,sms \\
        --splits nc,popup,email --wait nc=2h --wait popup=1d --wait email=1d \\
        --date 2026-08-01 --script
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import journey_composer as JC          # noqa: E402
from spec_parser import parse_spec     # noqa: E402

# The four comms channels, in the order a chain uses them when several are
# picked. Order is fixed rather than free because it is the captured order every
# comms journey in this repo uses; --order overrides it explicitly.
CHANNELS = ("nc", "popup", "email", "sms")
CHANNEL_LABELS = {"nc": "Notification (bell)", "popup": "Pop-up (Cat-fish)",
                  "email": "Email", "sms": "SMS"}

# A variant is only defaults — anything given on the command line still wins.
VARIANTS = {
    # Only GOW. The other three shapes each have a tab of their own that builds
    # them better — Tournament via tournament_comms_base (wait_date gates, the
    # revoke period, the brand's own capture), Scratch card via
    # sport_comms_campaign (it fetches the liveapi campaign card), Discount NC via
    # its baked calendar. Offering thinner copies of them here was two ways to
    # build one thing, and the thinner way was the one on the shorter path.
    #
    # GOW is the shape with no tab of its own: the GOW tab builds it only as part
    # of a full campaign, so this is how you build the comms half alone.
    #
    # There is no PMCL variant and cannot be one: journey_composer's node library
    # is entirely JBCL-captured, so a PMCL run here would put PMCL copy in JBCL
    # nodes — the brand swap the email guard already refuses.
    "gow": {
        "what": "Game of the Week comms: NC -> pop-up -> SMS, copy from the GOW sheet",
        "channels": ["nc", "popup", "sms"],
        "splits": [],
        # A delivered message never leads straight into another send (0 in 18
        # captures) and verify() refuses it, so the sends are spaced. 2h is a
        # placeholder cadence — pass --wait if the brief says otherwise.
        "waits": {"nc": "2h", "popup": "2h"},
        "replaces": "comms_campaign.py (the comms half of the GOW tab)",
    },
}
# Which composer node an engagement split after each channel maps to. SMS has no
# engagement event captured, so a split cannot follow it — asking is a refusal,
# not a silently dropped option.
SPLIT_NODE = {"nc": "ncsplit", "popup": "ncsplit", "email": "emailsplit"}

_DUR_RE = re.compile(r"^(\d+)\s*([mhdw])$", re.IGNORECASE)


def parse_wait(text: str) -> str:
    """'2h' / '30m' / '1d' / '1w' -> the ISO-8601 form the builder stores.

    Accepts the ISO form verbatim too, so a captured value can be pasted back.
    """
    t = (text or "").strip()
    if t.upper().startswith("P"):
        return t
    m = _DUR_RE.match(t)
    if not m:
        raise SystemExit(f"unreadable wait {text!r} — use 30m, 2h, 1d, 1w, or an "
                         f"ISO-8601 duration like P0Y0M1DT0H0M0S")
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit == "m":
        return f"P0Y0M0DT0H{n}M0S"
    if unit == "h":
        return f"P0Y0M0DT{n}H0M0S"
    if unit == "d":
        return f"P0Y0M{n}DT0H0M0S"
    return f"P0Y0M{n * 7}DT0H0M0S"


def _copy_for(channel: str, parsed) -> dict:
    """The composer settings for one channel, straight from the parsed sheet."""
    if channel == "sms":
        c = parsed.sms
        out = {}
        for lang in ("en", "es"):
            val = getattr(c, f"text_{lang}", "")
            if val:
                out[f"text_{lang}"] = val
        return out
    if channel == "email":
        c = parsed.email
        out = {}
        if c.subject_es:
            out["subject_es"] = c.subject_es
        if c.preheader_es:
            out["preheader_es"] = c.preheader_es
        if c.desc_es:
            out["desc_es"] = c.desc_es
        return out
    c = parsed.nc if channel == "nc" else parsed.popup
    out = {}
    for field, skey in (("title", "title"), ("desc", "desc"), ("caption", "caption")):
        for lang in ("en", "es"):
            val = getattr(c, f"{field}_{lang}", "")
            if val:
                out[f"{skey}_{lang}"] = val
    return out


def build_spec(
    *,
    sheet_text: str,
    channels: list[str],
    splits: set[str] | None = None,
    waits: dict[str, str] | None = None,
    date: str = "",
    days: int | None = None,
    name: str = "",
    link: str = "",
    email_hero_link: str = "",
    email_promo_page_id: str = "",
    email_template: str = "",
    email_heading: str = "",
    artwork: str = "PICK",
) -> tuple[dict, list[str]]:
    """Return (composer spec, notes). Refuses rather than filling a gap."""
    splits = set(splits or ())
    waits = dict(waits or {})
    notes: list[str] = []

    unknown = [c for c in channels if c not in CHANNELS]
    if unknown:
        raise SystemExit(f"unknown channel(s) {unknown}. Pick from {list(CHANNELS)}")
    if not channels:
        raise SystemExit("pick at least one channel")
    dupes = sorted({c for c in channels if channels.count(c) > 1})
    if dupes:
        raise SystemExit(f"channel(s) {dupes} picked twice — a chain uses each once")

    bad_split = sorted(s for s in splits if s not in SPLIT_NODE)
    if bad_split:
        raise SystemExit(
            f"no engagement split exists for {bad_split} — the captured library has "
            f"one for {sorted(SPLIT_NODE)} only. SMS has no engagement event, so a "
            f"split after it would branch on nothing.")
    orphan = sorted(s for s in splits if s not in channels)
    if orphan:
        raise SystemExit(f"split asked for {orphan}, which is not in the picked "
                         f"channels {channels}")
    orphan_wait = sorted(w for w in waits if w not in channels)
    if orphan_wait:
        raise SystemExit(f"wait asked for {orphan_wait}, which is not in the picked "
                         f"channels {channels}")

    parsed = parse_spec(sheet_text, expect_game_offer=False)
    notes += [f"sheet: {w}" for w in parsed.warnings]
    resolved_link = link or parsed.raw_link
    if not resolved_link:
        raise SystemExit(
            "no link — the sheet has no 'Link' row and none was given. Every comms "
            "card needs a destination; unset, the journey keeps the captured "
            "campaign's promo page.")

    chain: list[dict] = []
    for channel in channels:
        settings = _copy_for(channel, parsed)
        if not settings:
            raise SystemExit(
                f"{CHANNEL_LABELS[channel]} was picked but the sheet has no copy for "
                f"it. Add its rows to the sheet or untick the channel — an empty "
                f"channel ships the captured campaign's words.")
        if channel in ("nc", "popup"):
            settings["link_en"] = settings["link_es"] = resolved_link
            settings["icon" if channel == "nc" else "image"] = artwork
        elif channel == "email":
            if email_template:
                settings = {"template": email_template}
            else:
                if email_hero_link:
                    settings["hero_link"] = email_hero_link
                elif email_promo_page_id:
                    settings["promo_page_id"] = email_promo_page_id
                else:
                    settings["hero_link"] = resolved_link
                    notes.append("email: hero links the sheet's Link row "
                                 f"({resolved_link})")
                settings["hero"] = artwork
                if settings.get("desc_es"):
                    # The sheet has body copy, so use the creative that has a body:
                    # a hero image, that text, and a CTA button image under it.
                    settings["cta"] = artwork
                    if parsed.email.button_es:
                        notes.append(
                            "email: the CTA is an image in this creative, so the sheet's "
                            f"Button text ({parsed.email.button_es!r}) is not placed — it "
                            "has to be part of the button image you pick")
                else:
                    settings["heading"] = email_heading or parsed.event_name
                    if not settings["heading"]:
                        raise SystemExit(
                            "email: the sheet has no Description row for the email and no "
                            "'Event' row to use as a heading. Add the email's Description, "
                            "or give --email-heading — otherwise the email has no words.")
        chain.append(dict({"type": channel}, **settings))

        wait = waits.get(channel)
        if wait:
            chain.append({"type": "wait", "wait": parse_wait(wait)})
        if channel in splits:
            # The engaged path ends; the chain continues down the unengaged one,
            # which is the captured default (HAPPY) for both split nodes.
            passed = ("NCEngagementSplitPassedPath01" if SPLIT_NODE[channel] == "ncsplit"
                      else "Path1")
            chain.append({"type": SPLIT_NODE[channel],
                          "branches": {passed: [{"type": "end_of_path"}]}})

    spec: dict = {
        "name": name or f"JBCL | {parsed.event_name or 'Comms'} | Comms",
        "source": {"type": "segment"},
        "chain": chain,
        "date": date or parsed.tournament_start_date,
    }
    if not spec["date"]:
        raise SystemExit("no date — the sheet has no 'Start date' row and none was "
                         "given")
    if days:
        spec["days"] = days
    return spec, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True, help="file with the pasted sheet ('-' for stdin)")
    ap.add_argument("--variant", choices=sorted(VARIANTS),
                    help="start from a known comms shape: "
                         + "; ".join(f"{k} = {v['what']}" for k, v in VARIANTS.items()))
    ap.add_argument("--channels", default=None,
                    help=f"comma-separated, from {','.join(CHANNELS)} "
                         f"(default: the variant's, else all four)")
    ap.add_argument("--splits", default=None, help="channels to add an engagement split after")
    ap.add_argument("--wait", action="append", default=[], metavar="CHAN=DUR",
                    help="wait after a channel, e.g. --wait nc=2h (repeatable)")
    ap.add_argument("--date", default="", help="start date YYYY-MM-DD (default: the sheet's)")
    ap.add_argument("--days", type=int, help="build one journey per day for N days")
    ap.add_argument("--name", default="", help="journey name (default: from the sheet's Event)")
    ap.add_argument("--out-name", default="", metavar="BASENAME",
                    help="write console_scripts/<BASENAME>_console.js — how the admin "
                         "reads the script back, instead of the name-derived out/ path")
    ap.add_argument("--link", default="", help="override the sheet's Link row")
    ap.add_argument("--email-template", default="", help="reuse an existing CSE id instead of authoring")
    ap.add_argument("--email-hero-link", default="", help="email hero href (default: the link)")
    ap.add_argument("--email-promo-page-id", default="", help="email hero links this promo page")
    ap.add_argument("--email-heading", default="", help="heading above the hero (default: Event)")
    ap.add_argument("--artwork", default="PICK",
                    help="'PICK' to choose images at paste time, or a URL for all of them")
    ap.add_argument("--script", action="store_true", help="emit the console script")
    ap.add_argument("--json", action="store_true", help="print the spec and stop")
    args = ap.parse_args()

    text = sys.stdin.read() if args.sheet == "-" else Path(args.sheet).read_text(encoding="utf-8")
    waits = {}
    for item in args.wait:
        if "=" not in item:
            raise SystemExit(f"--wait wants CHAN=DUR, got {item!r}")
        k, v = item.split("=", 1)
        waits[k.strip()] = v.strip()

    # A variant only fills what was not asked for, so --channels/--splits/--wait
    # stay authoritative and a variant can never quietly override a choice.
    base = VARIANTS.get(args.variant or "", {})
    if args.variant:
        print(f"  variant {args.variant} — {base['what']}")
    channels = ([c.strip() for c in args.channels.split(",") if c.strip()]
                if args.channels is not None
                else list(base.get("channels") or CHANNELS))
    splits = ({s.strip() for s in args.splits.split(",") if s.strip()}
              if args.splits is not None
              else set(base.get("splits") or ()))
    if not args.wait:
        waits = dict(base.get("waits") or {})

    spec, notes = build_spec(
        sheet_text=text,
        channels=channels,
        splits=splits,
        waits=waits,
        date=args.date,
        days=args.days,
        name=args.name,
        link=args.link,
        email_hero_link=args.email_hero_link,
        email_promo_page_id=args.email_promo_page_id,
        email_template=args.email_template,
        email_heading=args.email_heading,
        artwork=args.artwork,
    )
    for n in notes:
        print(f"  note  {n}")
    print("  chain " + " -> ".join(c["type"] for c in spec["chain"]))
    if args.json:
        print(json.dumps(spec, ensure_ascii=False, indent=2))
        return 0
    return JC.cmd_compose(spec, as_json=False, script=args.script,
                          basename=args.out_name or None)


if __name__ == "__main__":
    raise SystemExit(main())
