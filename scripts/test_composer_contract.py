#!/usr/bin/env python3
"""Contract tests for the planner LLM -> compose.py path.

The planner's whole safety story is that a spec it emits is either built
correctly or refused loudly. Every check below corresponds to a failure that
was silently producing a rendered-but-wrong journey:

  * an invented recipe key            -> refused
  * an invented knob name             -> refused (was: dropped with a warning)
  * an omitted required knob          -> refused (was: shipped the template's game)
  * a blocker sentinel                -> refused
  * a fabricated game id              -> refused (was: composed and shipped)
  * game ids mixed across two games   -> refused
  * a knob path that no longer resolves -> refused (was: silent no-op)
  * a ```json-fenced reply            -> parsed (was: raw JSONDecodeError)

Also asserts recipes_catalog.json is byte-identical to what compose.py
generates, since it is injected verbatim into the planner prompt and drifts
silently when someone forgets `python compose.py --catalog`.

No network, no live server. Run: python scripts/test_composer_contract.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "journey-cloner"))

import compose as C  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [OK]   {label}")
    else:
        FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label} — {detail}")


def refuses(label: str, spec: dict) -> None:
    """The composer must refuse this spec with a SpecError."""
    try:
        C.compose_from_spec(spec)
    except C.SpecError:
        print(f"  [OK]   refuses {label}")
        return
    except Exception as exc:  # a crash is not a clean refusal
        FAILURES.append(f"refuses {label}: raised {type(exc).__name__} not SpecError")
        print(f"  [FAIL] refuses {label} — raised {type(exc).__name__}, not SpecError")
        return
    FAILURES.append(f"refuses {label}: spec was ACCEPTED")
    print(f"  [FAIL] refuses {label} — spec was ACCEPTED")


# A spec that must always build: real game, every required knob present.
GOOD = {
    "recipe": "casino_instant_freespin",
    "journey_name": "CI | contract test",
    "knobs": {
        "spins": 20,
        "spin_bet_clp": 100,
        "spin_provider": "pragmatic",
        "spin_game_lobby": "pragmatic-big-bass-bonanza-1000",
        "spin_game_wallet": "vs10bbbnz1000",
        "spin_game_external": "vs10bbbnz1000",
    },
}


def mutate(**knobs) -> dict:
    spec = copy.deepcopy(GOOD)
    for key, value in knobs.items():
        if value is None:
            spec["knobs"].pop(key, None)
        else:
            spec["knobs"][key] = value
    return spec


print("catalog freshness")
generated = json.dumps(C.catalog(), indent=2, ensure_ascii=False).strip()
on_disk = (REPO / "journey-cloner" / "recipes_catalog.json").read_text(encoding="utf-8").strip()
check("recipes_catalog.json matches compose.py --catalog", generated == on_disk,
      "stale — run: python journey-cloner/compose.py --catalog")

print("\nevery recipe still composes from its reference")
for key, recipe in C.RECIPES.items():
    try:
        body, _name, _ = C.compose(recipe)
        check(f"{key} composes", bool(body["activities"]), "no activities")
        check(f"{key} passes verify()", all(good for good, _ in C.verify(body)),
              "; ".join(msg for good, msg in C.verify(body) if not good))
    except Exception as exc:
        check(f"{key} composes", False, f"{type(exc).__name__}: {exc}")

print("\na well-formed spec builds and its values actually land")
try:
    _recipe, body, _name, unknown = C.compose_from_spec(GOOD)
    check("no unknown knobs", not unknown, str(unknown))
    check("verify() passes", all(good for good, _ in C.verify(body)))
    blob = json.dumps(body)
    check("requested game reached the journey",
          "pragmatic-big-bass-bonanza-1000" in blob, "game id absent from body")
    check("reference's own game is fully gone",
          "sweet-bonanza-super-scatter" not in blob and "vs20swbonsup" not in blob,
          "instfs.json's game survived — a promo card or mirror was missed")
except Exception as exc:
    check("well-formed spec builds", False, f"{type(exc).__name__}: {exc}")

print("\nrefusal gates")
bad_recipe = copy.deepcopy(GOOD)
bad_recipe["recipe"] = "instant_bonus"
refuses("an invented recipe key", bad_recipe)
refuses("an invented knob name", mutate(spin_game_id="pragmatic-big-bass-bonanza-1000"))
refuses("an omitted required knob", mutate(spin_game_lobby=None))
refuses("a blocker sentinel", mutate(spin_game_lobby="⛔ RESOLVE_AT_BUILD_TIME"))
refuses("a fabricated game id", mutate(spin_game_lobby="pragmatic-mega-dragon-fortune-deluxe"))
refuses("a placeholder in the identifying game field", mutate(spin_game_lobby="TBD"))
# A placeholder in a DERIVED field is corrected, not refused — provider/wallet/
# external all come from the lobby row, so the right value is already known.
# What matters is that the placeholder never reaches the journey.
try:
    _r, tbd_body, _n, _u = C.compose_from_spec(mutate(spin_provider="TBD"))
    check("a placeholder in a derived field never reaches the journey",
          "TBD" not in json.dumps(tbd_body))
except Exception as exc:
    check("a placeholder in a derived field is handled", False, f"{type(exc).__name__}: {exc}")

# Games are named in plain language now — the registry is far too large to inline.
print("\ngame names resolve to the full id tuple")
for label, name, want_lobby in [
    ("display name", "Big Bass Bonanza 1000", "pragmatic-big-bass-bonanza-1000"),
    ("raw lobby id", "pragmatic-big-bass-bonanza-1000", "pragmatic-big-bass-bonanza-1000"),
]:
    try:
        _r, nb, _n, _u = C.compose_from_spec(mutate(spin_game_lobby=name))
        fa = next(a for a in nb["activities"]
                  if a["activityName"] == "freespin_bonus")["initializationData"]["freespinActivity"]
        entry = C._games_registry().get(want_lobby, {})
        check(f"{label} -> correct tuple",
              fa["lobbyGameId"] == want_lobby and fa["walletGameId"] == entry.get("walletGameId")
              and fa["provider"] == entry.get("provider"),
              f"got {fa['lobbyGameId']}/{fa['walletGameId']}/{fa['provider']}")
    except Exception as exc:
        check(f"{label} -> correct tuple", False, f"{type(exc).__name__}: {exc}")

# A mixed tuple is COERCED, not refused: lobbyGameId is the registry's primary
# key, so the correct wallet/external/provider are already determined. The model
# produces these by pattern-matching two similarly-named titles; refusing bounced
# a spec whose right answer was known.
print("\na game tuple mixed across two games is corrected from the registry")
try:
    mixed = mutate(spin_game_wallet="vs20swbonsup", spin_game_external="vs20swbonsup")
    _r, mixed_body, _n, _u = C.compose_from_spec(mixed)
    fa = next(a for a in mixed_body["activities"]
              if a["activityName"] == "freespin_bonus")["initializationData"]["freespinActivity"]
    check("wallet id corrected to the lobby's game", fa["walletGameId"] == "vs10bbbnz1000", fa["walletGameId"])
    check("external id corrected to the lobby's game", fa["externalGameId"] == "vs10bbbnz1000", fa["externalGameId"])
    check("lobby id untouched", fa["lobbyGameId"] == "pragmatic-big-bass-bonanza-1000", fa["lobbyGameId"])
except Exception as exc:
    check("mixed tuple is coerced", False, f"{type(exc).__name__}: {exc}")
# ...but an unresolvable lobby id is still a hard refusal.
refuses("an unknown lobby id even when the rest is valid",
        mutate(spin_game_lobby="pragmatic-not-a-real-game"))
# Reproduced live 2026-07-27: a "100 CLP per spin" brief came back as 10000
# (minor units), which the x100 conversion turned into a 10,000 CLP spin with
# every check green. The prose unit contract did not hold; the range gate does.
refuses("minor units where major CLP was asked for", mutate(spin_bet_clp=10000))
refuses("a quoted amount instead of a number", mutate(spins="25"))
refuses("an absurd spin count", mutate(spins=999999))

print("\na drifted knob path fails closed instead of silently not applying")
knob = C.RECIPES["casino_instant_freespin"].knobs["spin_game_lobby"]
original = knob.path
knob.path = "initializationData.freespinActivity.nope.gone"
try:
    refuses("a knob path that no longer resolves", GOOD)
finally:
    knob.path = original

print("\ninherited campaign content is detected")
# The failure this guard exists for: a journey that composes cleanly but still
# carries the reference campaign's SMS body, email template and promo links.
comms_body, _n, _ = C.compose(C.RECIPES["comms"])
comms_leaks = C.audit_inherited_content(comms_body, C._load("casino/gow_comms.json"))
check("a verbatim comms clone is flagged", len(comms_leaks) > 0, "no leaks reported")
check("the leaked SMS body is named",
      any("Gran Copa" in leak for leak in comms_leaks), str(comms_leaks[:2]))
check("the leaked email template id is named",
      any("CSE-0-14458" in leak for leak in comms_leaks), str(comms_leaks[:2]))
# ...and a reward journey with no communication nodes is clean, so the check is
# not simply flagging everything.
_r, fs_body, _n, _u = C.compose_from_spec(GOOD)
check("a journey with no comms nodes is clean",
      not C.audit_inherited_content(fs_body, C._load("casino/instfs.json")))
# Template placeholders and field names are plumbing, not content.
check("template placeholders are not content", not C._is_content("%link-es%?%$utm_tags%"))
check("field names are not content", not C._is_content("buttons_1_highlighted"))
check("real copy IS content", C._is_content("Elige tu deposito y gana 50 giros"))
check("a real link IS content", C._is_content("https://win.jugabet.cl/promocion/x"))

print("\nthe planner's real output shapes parse")
payload = json.dumps(GOOD)
for label, raw in [
    ("bare JSON", payload),
    ("```json fenced", f"```json\n{payload}\n```"),
    ("prose lead-in", f"Here is the spec:\n\n{payload}"),
    ("prose + fence + trailer", f"Sure!\n```json\n{payload}\n```\nRun compose.py next."),
]:
    try:
        check(f"parses {label}", C._extract_json(raw).get("recipe") == GOOD["recipe"])
    except Exception as exc:
        check(f"parses {label}", False, f"{type(exc).__name__}: {exc}")
try:
    C._extract_json("I cannot help with that.")
    check("rejects a reply with no JSON", False, "accepted non-JSON")
except C.SpecError:
    check("rejects a reply with no JSON", True)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for failure in FAILURES:
        print(f"  - {failure}")
    sys.exit(1)
print("All composer contract checks passed.")
