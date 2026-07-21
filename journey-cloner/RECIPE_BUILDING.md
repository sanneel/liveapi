# RECIPE_BUILDING.md

How to turn ONE captured REA journey into a reusable, verifiable **recipe** with
`compose.py`. The whole discipline is: **read what the reference actually
contains, keep every node, and flag — never invent — anything the capture does
not prove.**

---

## 0. Mental model

- A **reference** is one real journey draft, captured from the backoffice
  (`POST /journey-builder/v0/journey-drafts` body in a HAR) and saved verbatim to
  `templates/<family>/<name>.json`. It carries the full `activities[]` graph and
  the editor mirror `rawJourneyData`.
- A **recipe** (`recipes/<key>.json`) is a thin descriptor pointing at exactly
  ONE reference, plus a title / kind / notes. It invents no structure.
- `compose.py <key>` reads the reference, keeps every node, regenerates activity
  UUIDs, strips server-minted ids, and emits a clean create-body to
  `out/<key>.composed.json` — **only if `verify` passes**.
- `games.json` is the game-id knob source, captured from
  `GET …/free-spins-bonus-deposit/data/games`.

```
python compose.py --list
python compose.py <key>                       # compose + verify
python compose.py <key> --verify              # verify only
python compose.py <key> --game <lobbyId>      # swap freespin game from games.json
python compose.py <key> --set freespin_bonus:freespinActivity.spins=3
python compose.py <key> --catalog             # compose + verify + register in catalog.json
```

---

## 1. Read the chain by following `nextActivityId`

Every activity node is `{activityId, activityName, events[], initializationData}`.
The graph edges live in **`events[].nextActivityId`**, and for `freespin_bonus`
they are mirrored in **`initializationData.pathesConfig[].nextActivityId`**.
`activityName` is the type discriminator (`external_system_source`, `promotion`,
`freespin_bonus`, `deposit`, `casino_bonus_v2`, `multipurpose_promotion`,
`notification_center`, the `*_split` branchers, `end_of_path`, `end_of_journey`, …).

Entry is `external_system_source` (API trigger) or `dwh_source` (segment).
Walk from the entry, following every `nextActivityId`, to see the real shape.

- **instant_bonus** (linear, 11 nodes):
  `external_system_source → promotion → freespin_bonus → end_of_journey…`
- **multipurpose** (branching, 148 nodes): `external_system_source → wait_date →
  multipurpose_promotion` then 4× `deposit / promotion / freespin_bonus /
  casino_bonus_v2` reward flows plus comms branches (`native_push`,
  `dextra_email`, `notification_center`, `ams_decision_split`, engagement splits).

## 2. Find knob paths from the reference's REAL `initializationData`

Knobs are **discovered**, not assumed. `compose.py` walks each activity's
`initializationData` and, for known activity types, records only the dot-paths
that actually resolve in *this* capture (`KNOB_PATHS` in `compose.py`). Examples
that resolved in the references:

| activity | knob paths (real) |
|---|---|
| `freespin_bonus` | `freespinActivity.spins`, `.startAt`, `.stopAt`, `.currenciesConfig.<CCY>.betAmount`, `.maxBonusAmount`, `.spinsExpirationDuration` |
| `casino_bonus_v2` | `bonusPercent`, `wageringRequirement`, `releaseLimitMultiplier`, `bonusExpirationTime` |
| `deposit` | `depositConditions.expirationTimeout`, `depositConditions.minDepositAmounts[].amount` |
| `promotion` / `multipurpose_promotion` | `timeToAccept`, `autoAccept`, `startAt`, `stopAt` |

If a path is not in the capture, it is not a knob. Override live values with
`--set activityName:dot.path=value`.

## 3. Expose game-id knobs from `games.json`

The `freespin_bonus` node's `freespinActivity` holds the game identity. Each field
maps 1:1 to a `games.json` row:

| freespinActivity field | games.json field |
|---|---|
| `lobbyGameId` | `lobbyId` |
| `walletGameId` | `walletId` |
| `externalGameId` | `externalGameId` |
| `provider` | `gameProvider` |
| `gameTranslationKey` | `translationKey` |

`--game <lobbyId>` swaps all five consistently. `verify` warns ⚠ if a freespin
game is not in `games.json`.

> **games.json is page 1 only.** The capture returned `totalItems: 293` across 3
> pages but the HAR only recorded page 1 (100 games). So several real games used
> by the multipurpose reference (`endorphina-fortune-chests`,
> `jugabet-games-la-gran-copa-jugabet`, `pragmatic-sweet-bonanza-1000`,
> `amigo-1000-olympus-rivals`) verify as ⚠ unresolved. That is honest: they are
> real, just not in the captured page. Capture pages 2–3 to resolve them — do not
> hand-add rows.

## 4. Keep EVERY node from this ONE reference

`compose.py` never drops or adds nodes. It:

1. regenerates every `activityId` UUID **consistently** across `activities[]` and
   the `rawJourneyData` mirror (global id substitution), and
2. strips server-minted ids only: top-level `reservedJourneyId`,
   `duplicatedFromId`, `duplicatedFromVersion`; per-node `promotionId`,
   `promotionDisplayId`, `promotionLinkId`, `campaignId`.

## 5. `verify` is the gate

Hard failures (`✗`) — a broken executable graph:

- a `nextActivityId` that resolves to no activity (dangling chain),
- no entry node,
- a `rawJourneyData` edge pointing to an id that is neither an activity nor any
  mirror element,
- leftover server-minted ids,
- an unreachable **non-terminal** node.

Reported but not fatal — reference-inherent facts, kept as-is:

- `⚠` a freespin game not in `games.json` (see §3),
- `·` unwired **terminal** nodes (`end_of_path` / `end_of_journey`) the reference
  itself left disconnected — kept, never auto-wired,
- `·` editor-chrome cards in `rawJourneyData` (`flowEntry`, `dropZone`,
  `parallelFlow`) that back no activity.

Run until `verify … PASS`, then `--catalog` registers the recipe (its real
pattern + discovered knob paths) into `catalog.json`.

---

## Corrections / KB rules

### Object connections use campaign_connector, not CTAs
- Journeys connect to other journeys/randomizers via the campaign_connector
  activity + the {journeyId, activityId} hand-off. NOT via a notification CTA
  link. A notification/CTA is marketing (tells the player), never the structural
  connection.
- If a journey needs to grant/unlock a randomizer (scratch card, wheel) after a
  condition, that is a campaign_connector to the randomizer's entry — describe
  it that way.

### Journey → randomizer direction is UNCAPTURED
- All captured examples are randomizer → journey (prize routes into reward).
- A journey GRANTING a randomizer shot (deposit → unlock scratch card) has NO
  captured example. Flag ⛔: "journey-grants-randomizer mechanic unverified —
  confirm how the shot entitlement is wired before building."

> **Why these rules exist.** The failure class they guard against is not "wrong
> number" — it is *inventing a connection mechanic with no ground truth*, the same
> class as guessed game IDs or a guessed instant-bonus mapping. The model is solid
> on structure it has examples for and improvises when it doesn't; the fix is the
> same discipline everywhere in this doc — flag ⛔ instead of improvising.
> Capturing one real "deposit unlocks scratch card" journey would resolve the
> journey→randomizer direction properly; until then, neither a human nor the tool
> actually knows the exact wiring, so it must not be built blind.
