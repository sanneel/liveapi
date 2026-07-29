#!/usr/bin/env python3
"""Score the planner's MODE 1 output against the ways it actually goes wrong.

Every planner fix in this repo has so far been judged by one ad-hoc run, which
cannot tell an improvement from a lucky sample: the same brief and prompt gave 32
journeys on one call and 6 on the next. This runs a fixed brief set through the
live planner and scores each reply mechanically, so a prompt or model change can
be shown to help instead of asserted.

Each check is a failure that really happened, not a hypothetical:

  mode1_shape    MODE 1 replies arrived as MODE 2 detail dumps ("Entry:",
                 "Key settings:", "Template reference:") — 29.5K chars instead
                 of a 20-line outline.
  no_invented    A plan grew six "(Fallback)" copies of journeys 1-6 that the
                 brief never asked for.
  grouped        A 5-tier x 6-level matrix was enumerated as 30-37 journeys
                 instead of grouped into lines.
  wheel_fits     A wheel was planned with 7 prize slices; no captured template
                 has 7 (they have 4, 5 and 6), so the whole wheel was refused
                 at build time.
  design_block   The `diagram` block was missing, or truncated into JSON the
                 renderer could not parse, so no boards were drawn.
  flags_terse    A single ❓ flag ran to 1,200 characters of prose. The limit is
                 what a board chip can show on two wrapped lines (~400 chars).
  closing_line   The reply must end with the handoff line, which is what tells
                 the operator the outline is finished.
  no_false_blockers
                 A plan declared ⛔ "game X not found in registry" for a game
                 that IS registered, which reads as "this campaign is blocked"
                 when nothing is wrong. The planner cannot see the registry, so
                 it must never make the claim; this checks it against the file
                 the composer grounds against.

NOT in CI: it needs a live GEMINI_API_KEY and spends real tokens (roughly 30-40K
per brief). Run it deliberately, before and after a prompt change:

    .venv/bin/python scripts/eval_planner.py                # all briefs
    .venv/bin/python scripts/eval_planner.py --brief matrix  # just one
    .venv/bin/python scripts/eval_planner.py --repeat 3      # sample variance
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "journey-planner"))

from app.config import get_settings                                    # noqa: E402
from app.routes.admin_planner import _complete, _usage_start           # noqa: E402
import render_journey_design as R                                      # noqa: E402

# Prize slice counts of the captured randomizer templates. A plan asking for any
# other count cannot be built, so the wheel silently vanishes from the campaign.
CAPTURED_SLICES = {4, 5, 6}


def _game_resolves(name: str) -> bool:
    """Is this game in the registry the composer grounds against?"""
    if not hasattr(_game_resolves, "_idx"):
        try:
            games = json.loads((REPO / "journey-cloner" / "library" / "games.json")
                               .read_text(encoding="utf-8")).get("games") or {}
        except (OSError, ValueError):
            games = {}
        idx = set()
        for lobby_id, entry in games.items():
            for key in (lobby_id, entry.get("gameTranslationKey"),
                        *(entry.get("aliases") or [])):
                if key:
                    idx.add(re.sub(r"[^a-z0-9]+", "", str(key).lower()))
        _game_resolves._idx = idx
    return re.sub(r"[^a-z0-9]+", "", name.lower()) in _game_resolves._idx


BRIEFS: dict[str, dict] = {
    "simple": {
        "why": "one journey, no matrix — the floor. If this fails, nothing else matters.",
        "brief": """CAMPAIGN BRIEF — "Tuesday Free Spins"
Brand: JugaBet Chile (JBCL). Currency: CLP. Runs 04 Aug 2026, one day.
Every player who deposits at least 5.000 CLP gets 25 free spins on
"La Gran Copa Jugabet" at 100 CLP per spin, no wagering, spins expire in 24h.
Notify them on site when the spins land.""",
        "max_journeys": 3,
        "expect_wheel": False,
    },
    "matrix": {
        "why": "5 deposit tiers x 6 prize levels — must be GROUPED, not enumerated.",
        "brief": """CAMPAIGN BRIEF — "Ruletazo"
Brand: Fortuna Chile (PMCL). Currency: CLP. Runs 12-13 Sep 2026 (2 days).
Casino promo page open to all players.

Players deposit to earn wheel spins. The wheel awards free spins in six sizes:
10, 20, 30, 40, 50 and 100 FS, all with x30 wagering.

The bet per spin follows the DEPOSIT TIER the player made:
  deposit 2.500 CLP -> bet 50    deposit 5.000 -> bet 100
  deposit 10.000    -> bet 200   deposit 15.000 -> bet 300
  deposit 20.000    -> bet 400
Every free-spin bonus: max bonus 200.000 CLP, min bonus 100 CLP, cashout 20,
wager x30, 3 days to wager, 1 day to activate.
Game for every tier: "La Gran Copa Jugabet".
Comms on both days: NC, Email, SMS and Pop Up.""",
        # 6 prize journeys + a grouped deposit line + comms + wheel + empty is
        # about a dozen lines. Thirty means the matrix was enumerated.
        "max_journeys": 14,
        "expect_wheel": True,
        # 6 prize sizes + empty = 7 slices, which fits no captured template.
        "expect_slice_warning": True,
    },
    "wheel_too_big": {
        "why": "7 prize slices exist in no captured template — the plan must SAY so.",
        "brief": """CAMPAIGN BRIEF — "Mega Wheel"
Brand: JugaBet Chile (JBCL). Currency: CLP. Runs 20 Aug 2026, one day.
A public fortune wheel anyone can spin once. Seven prizes:
  10 FS, 20 FS, 30 FS, 40 FS, 50 FS, 100 FS, and one empty slice.
All free spins on "La Gran Copa Jugabet", bet 100 CLP, x30 wagering.""",
        "max_journeys": 10,
        "expect_wheel": True,
        # The point of this brief: the reply must flag that 7 slices do not fit.
        "expect_slice_warning": True,
    },
}

MODE2_MARKERS = (r"(?m)^\s*Entry:\s", r"(?m)^\s*Key settings:\s*$",
                 r"(?m)^\s*Template reference:\s", r"(?m)^\s*Flow:\s")


# "Journey 3:", "Journeys 1–6 (×5):", "Comms Journey: …", "Promo Page: …" — the
# outline names objects in several shapes and a grouped line may carry a count.
OBJECT_LINE = re.compile(
    r"(?m)^\s*(?:\d+[.)]\s*)?"                       # optional "3. " list number
    r"(?:Journeys?\s+\d+(?:\s*[–\-]\s*\d+)?"        # "Journey 3" / "Journeys 1–5"
    r"|[A-Z][\w ]*?(?:Journey|Page|Randomizer|Wheel|Scratch))"
    r"[^:\n]*:\s*(.+?)\s*$")


def outline_journeys(text: str) -> list[str]:
    """Object lines in part (a). A grouped "Journeys N–M (×K)" line counts once —
    that is the whole point of grouping."""
    body = text.split("━━ CREATION ORDER")[0]
    return [m.group(1) for m in OBJECT_LINE.finditer(body)]


def wheel_slices(text: str) -> int | None:
    """How many prize slices the reply asks for, from the spec or the outline."""
    m = re.search(r'"weights"\s*:\s*\[([^\]]*)\]', text)
    if m:
        return len([x for x in m.group(1).split(",") if x.strip()])
    m = re.search(r"(?mi)^\s*(?:\d+[.)]\s*)?Randomizer[^\n]*?(\d+)\s*prizes?", text)
    return int(m.group(1)) if m else None


def score(text: str, spec: dict) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    journeys = outline_journeys(text)
    grouped = re.findall(r"(?m)^\s*Journeys?\s+\d+\s*[–\-]\s*\d+\s*[:.]", text)

    hits = [p for p in MODE2_MARKERS if re.search(p, text)]
    out["mode1_shape"] = (not hits and bool(journeys),
                          "MODE 2 detail in a MODE 1 reply" if hits else
                          ("no Journey lines" if not journeys else "ok"))

    names = [n.split("—")[0].strip() for n in journeys]
    dupes = [n for n in set(names) if names.count(n) > 1]
    invented = re.findall(r"\(fallback\)|\(copy\)|\(duplicate\)|\(spare\)", text, re.I)
    out["no_invented"] = (not dupes and not invented,
                          f"duplicate names {dupes}" if dupes else
                          (f"{len(invented)} invented variant(s)" if invented else "ok"))

    cap = spec["max_journeys"]
    out["grouped"] = (len(journeys) <= cap,
                      f"{len(journeys)} journey lines (cap {cap}, "
                      f"{len(grouped)} grouped)")

    if spec.get("expect_wheel"):
        n = wheel_slices(text)
        if spec.get("expect_slice_warning"):
            # The honest answer is a flag, not a spec: 7 slices fit nothing.
            said = bool(re.search(r"(?i)(slice|prize).{0,80}(no captured|does not fit|"
                                  r"cannot be added|max is|closest)", text)) or \
                   bool(re.search(r"(?i)⛔[^\n]*(slice|prize)", text))
            out["wheel_fits"] = (said or (n in CAPTURED_SLICES),
                                 "flagged the slice mismatch" if said else
                                 f"asked for {n} slices and did not flag it")
        else:
            out["wheel_fits"] = (n is None or n in CAPTURED_SLICES,
                                 f"{n} slices" if n else "no count stated")

    try:
        diagram = R.normalise(R.extract_diagram(text))
        raw = len(diagram["journeys"])
        # Score the BOARDS, not the block: near-identical journeys are folded onto
        # one board by the renderer, so a block that enumerates a matrix still
        # produces a reviewable set. What the operator sees is what counts.
        boards, folded = R.collapse_variants(diagram["journeys"])
        # FEWER boards than outline lines is the folding working as intended. The
        # failure mode is the opposite: a block that enumerates what the outline
        # grouped, handing the reviewer a wall of near-identical pictures.
        ok = (len(boards) > 0) if not journeys else (len(boards) <= len(journeys) + 2)
        out["design_block"] = (ok, f"{len(boards)} boards from {raw} entries "
                                   f"(folded {folded}) vs {len(journeys)} outline lines")
    except Exception as exc:
        out["design_block"] = (False, f"unusable: {str(exc)[:60]}")

    flags = re.findall(r"(?m)^[⚠❓⛔][^\n]*", text)
    longest = max((len(f) for f in flags), default=0)
    # 400 chars is what two wrapped lines hold on a board — past that the chip
    # clips and the operator loses the end of the flag.
    out["flags_terse"] = (longest <= 400, f"longest flag {longest} chars")

    false_blockers = []
    for line in re.findall(r"(?m)^⛔[^\n]*", text):
        if not re.search(r"(?i)regist|not found|unknown game", line):
            continue
        for name in re.findall(r'"([^"]{3,60})"', line) or re.findall(r"'([^']{3,60})'", line):
            if _game_resolves(name):
                false_blockers.append(name)
    out["no_false_blockers"] = (not false_blockers,
                                f"claimed unregistered but resolves: {false_blockers}"
                                if false_blockers else "ok")

    out["closing_line"] = (text.rstrip().endswith("Say which object(s) you want in full."),
                           "ok" if text.rstrip().endswith(
                               "Say which object(s) you want in full.") else "missing")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brief", action="append", choices=sorted(BRIEFS),
                    help="run only these briefs (repeatable)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="calls per brief — the planner is not deterministic")
    ap.add_argument("--save", default="", help="directory to write each reply to")
    args = ap.parse_args()

    settings = get_settings()
    if not settings.gemini_api_key.strip() and not settings.groq_api_key.strip():
        print("no planner key configured — set GEMINI_API_KEY")
        return 2
    chosen = args.brief or sorted(BRIEFS)
    save_dir = Path(args.save) if args.save else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    print(f"model {settings.gemini_model} · thinking {settings.gemini_thinking_budget} "
          f"· {len(chosen)} brief(s) x {args.repeat}")
    all_checks: dict[str, list[bool]] = {}
    spend = {"calls": 0, "input": 0, "cached": 0, "thought": 0, "answer": 0}

    for key in chosen:
        spec = BRIEFS[key]
        print(f"\n── {key}: {spec['why']}")
        for run in range(1, args.repeat + 1):
            totals = _usage_start()
            text, err = _complete(settings, [{"role": "user", "text": spec["brief"]}], 0.2)
            for k in spend:
                spend[k] += totals.get(k, 0)
            if err or not text:
                print(f"   run {run}: CALL FAILED — {err}")
                continue
            if save_dir:
                (save_dir / f"{key}_{run}.txt").write_text(text, encoding="utf-8")
            results = score(text, spec)
            passed = sum(1 for ok, _ in results.values() if ok)
            print(f"   run {run}: {passed}/{len(results)} checks "
                  f"({totals['thought']}t/{totals['answer']}a tokens)")
            for name, (ok, note) in results.items():
                all_checks.setdefault(name, []).append(ok)
                if not ok:
                    print(f"        ✗ {name}: {note}")

    print("\n══ SUMMARY ══")
    if not all_checks:
        print("no successful calls")
        return 1
    total_pass = 0
    total_n = 0
    for name, oks in sorted(all_checks.items()):
        rate = 100 * sum(oks) / len(oks)
        total_pass += sum(oks)
        total_n += len(oks)
        bar = "█" * round(rate / 10) + "·" * (10 - round(rate / 10))
        print(f"  {name:14} {bar} {rate:5.0f}%  ({sum(oks)}/{len(oks)})")
    print(f"  {'OVERALL':14} {100*total_pass/total_n:5.0f}%  ({total_pass}/{total_n})")
    billed_in = spend["input"] - spend["cached"]
    print(f"\ntokens: {spend['calls']} call(s), input {spend['input']:,} "
          f"({spend['cached']:,} cached -> {billed_in:,} billed), "
          f"thought {spend['thought']:,}, answer {spend['answer']:,}")
    return 0 if total_pass == total_n else 1


if __name__ == "__main__":
    sys.exit(main())
