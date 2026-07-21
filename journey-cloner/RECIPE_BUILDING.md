# How to build a new recipe (guide + reusable prompt)

A **recipe** teaches `compose.py` to assemble one kind of journey from a single
captured reference journey. This doc is both the human guide and a prompt you
can hand to an AI agent to build a recipe for you. Read `COMPOSER_RULES.md`
first — the canvas rules a recipe must obey.

---

## The mental model (why recipes work)

The composer is an **assembler, not a generator**. It never invents journey
structure. A recipe says:

> "Take THIS reference journey (which renders), pull out THIS ordered chain of
> activities, rewire them into a straight line, regenerate ids, and re-emit both
> storage copies."

So every recipe is bound to **one reference journey** that already renders in the
backoffice. The composer sources every node/edge/config/shell shape from it —
this is the "one node schema per recipe, no mixing" rule. If the reference can't
supply an activity in the chain, the build fails loudly (correct behaviour).

---

## The three pieces you define (in `compose.py`, the `RECIPES` dict)

```python
@dataclass
class Node:
    activity: str      # activityName, e.g. "freespin_bonus"
    primary: str       # the ONE forward event that wires to the next node
    display: str | None = None   # optional card label override

@dataclass
class Knob:             # a named, LLM-facing value → a real dotted path
    activity: str       # which activity in the chain it lands on
    path: str           # dotted path INSIDE that activity object
    unit: str = "raw"   # "raw" | "minor" (minor = major CLP × 100)
    desc: str = ""      # one-line meaning, shown to the planner

@dataclass
class Recipe:
    key: str            # the recipe name the planner emits in a MODE 3 spec
    reference: str      # template path under templates/, MUST render
    chain: list[Node]   # ordered; the last node wires to the terminal
    terminal: str = "end_of_journey"
    knobs: dict[str, Knob] = {}   # LLM name -> Knob
```

---

## The 7 steps

### 1. Capture the reference journey
Build the journey once in the backoffice, export a HAR, and pull the
`POST /journey-drafts` request body. It MUST be one that renders (open it in the
editor, confirm a live canvas — not a blank gray one). Save it under
`templates/<family>/<name>.json` (bare journey body, same shape as `gow.json`).

### 2. Read the real chain (entry-first, follow `nextActivityId`)
Don't trust `activities[]` order — follow the wiring. For each activity, find the
ONE completion event whose `nextActivityId` points at the next step:

```python
import json
b = json.load(open("templates/<family>/<name>.json"))
idmap = {a["activityId"]: a["activityName"] for a in b["activities"]}
for a in b["activities"]:
    fwd = [(e["eventName"], idmap.get(e.get("nextActivityId")))
           for e in a.get("events", []) or [] if e.get("nextActivityId")]
    print(a["activityName"], "->", fwd)
```

The `primary` event for each Node is the one that advances the main path (e.g.
deposit's `DepositConditionSatisfied`, promotion's `PromotionAccepted`,
freespin's `FreespinBonusCollectingFinished`). Secondary/failure events stay
unwired (the editor shows them as valid unconnected drop-ports).

### 3. Find the knob paths (per THIS reference)
Knob paths are **per-reference** — the same activity can be shaped differently in
different journeys. Inspect the real `initializationData` of each activity in
YOUR reference, or run `extract_knobs.py`. A path is dotted, relative to the
activity object, list indices allowed:
`initializationData.freespinActivity.currenciesConfig.CLP.betAmount`.
Use `unit: "minor"` for CLP amounts (the planner sends major CLP; the composer
×100s them).

### 4. Write the Recipe
Add an entry to `RECIPES` in `compose.py`. Name knobs for the LLM, not the wire
(`spins`, `deposit_min_clp`, `spin_game_id`) and map each to its real path.

### 5. Compose + verify
```
python compose.py <key>
```
Every `verify()` check must pass (nextActivityId resolves, every activity has a
canvas node, edges connect real nodes, positions present, terminal exists). If a
node came from a nested container, confirm de-nesting stripped `parentNode`,
`extent`, `pathes` (see COMPOSER_RULES rule 3).

### 6. Render-check in the backoffice
Paste `console_scripts/composed_<key>_console.js` into a logged-in console,
confirm the draft renders wired (not blank). This is the only real proof.

### 7. Publish the recipe to the planner
```
python compose.py --catalog     # rewrites recipes_catalog.json
```
The planner now advertises the recipe and can emit MODE 3 specs against it. The
validator (`validate_spec`) will accept the new key and still refuse ⛔ blockers.

---

## Game knobs (casino recipes)

For freespin/casino recipes, expose the game as knobs sourced from
`library/games.json` (never a guessed id). Add knobs for each id field that lives
in the reference:
```python
"spin_game_lobby": Knob("freespin_bonus", "initializationData.freespinActivity.lobbyGameId"),
"spin_game_wallet": Knob("freespin_bonus", "initializationData.freespinActivity.walletGameId"),
"spin_game_external": Knob("freespin_bonus", "initializationData.freespinActivity.externalGameId"),
"spin_provider": Knob("freespin_bonus", "initializationData.freespinActivity.provider"),
```
The planner resolves the brief's game NAME → these ids via the registry; if the
game isn't in the registry it emits `⛔ RESOLVE_AT_BUILD_TIME` and the validator
refuses the build.

---

## Worked example — `casino_instant_freespin` (from instfs.json)

Reference `templates/casino/instfs.json` renders (6 nodes). Real wiring:
`external_system_source --PlayerAdded--> promotion --PromotionAccepted-->
freespin_bonus --FreespinBonusCollectingFinished--> end_of_journey`.
"Instant" = `freespinActivity.withWagering: false`, no `casino_bonus_v2` chain.

```python
"casino_instant_freespin": Recipe(
    key="casino_instant_freespin",
    reference="casino/instfs.json",
    chain=[
        Node("external_system_source", "PlayerAdded", "Entry"),
        Node("promotion", "PromotionAccepted", "Offer"),
        Node("freespin_bonus", "FreespinBonusCollectingFinished", "Instant free spins"),
    ],
    knobs={
        "spins":            Knob("freespin_bonus", "initializationData.freespinActivity.spins"),
        "spin_bet_clp":     Knob("freespin_bonus", "initializationData.freespinActivity.currenciesConfig.CLP.betAmount", "minor"),
        "spin_provider":    Knob("freespin_bonus", "initializationData.freespinActivity.provider"),
        "spin_game_lobby":  Knob("freespin_bonus", "initializationData.freespinActivity.lobbyGameId"),
        "spin_game_wallet": Knob("freespin_bonus", "initializationData.freespinActivity.walletGameId"),
        "spin_game_external": Knob("freespin_bonus", "initializationData.freespinActivity.externalGameId"),
    },
),
```
Then `python compose.py casino_instant_freespin` → render-check → `--catalog`.

> Note: validate the knob paths against instfs.json's ACTUAL shape before
> trusting them (`apply_values` logs `MISS` for a path that doesn't exist and
> keeps going — check the log).

---

## Non-linear recipes (choosable flows, splits) — NOT covered yet

Recipes today assume a **linear** chain (`pathesConfiguration: {}`,
`boundaryConfiguration: {}`). A `multipurpose_promotion` with choosable/parallel
flows (e.g. `templates/casino/multipurpose_spinladder.json` — 74 nodes, 4 tiers)
needs the composer to reproduce `pathesConfiguration`/`boundaryConfiguration` and
the split events. That's a dedicated engine change, not a recipe you can add with
the linear machinery. Flag such a campaign ⛔ until that support lands.

---

## Reusable prompt (hand this to an AI agent)

> Build a new `compose.py` recipe named `<key>` from the reference journey
> `templates/<family>/<name>.json` (already captured; confirm it renders).
> Follow journey-cloner/RECIPE_BUILDING.md:
> 1. Read the real chain entry-first by following `nextActivityId`; give me the
>    ordered activities and each one's primary forward event.
> 2. For the reward/condition activities, find the tunable knob paths from the
>    reference's actual `initializationData` (CLP amounts as unit "minor"). For
>    casino games, expose provider + lobby/wallet/external game-id knobs sourced
>    from library/games.json.
> 3. Add the Recipe to the RECIPES dict; keep every node sourced from this ONE
>    reference (no schema mixing); leave secondary events unwired.
> 4. Run `python compose.py <key>`; all verify() checks must pass; fix any
>    de-nesting (strip parentNode/extent/pathes) per COMPOSER_RULES.
> 5. Run `python compose.py --catalog` to publish it to the planner.
> Do NOT invent structure the reference doesn't contain; if it can't supply a
> chain activity, stop and tell me which reference would.
