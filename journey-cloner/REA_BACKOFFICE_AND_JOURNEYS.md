# REA Backoffice & Player Journeys — Working Knowledge

This document captures everything we currently understand about the **REA
Backoffice** (the `gr8.tech` "UBO" CRM platform) and its **Player Journey
Builder**, gathered while building and debugging the Journey Cloner. It is
written so that a future maintainer (or a new teammate) can understand how the
platform models journeys, why cloning is hard, and which fields the platform
treats as unique identifiers.

> Scope: this is reverse-engineered knowledge from captured API payloads and
> observed API errors, **not** official vendor documentation. Where something
> is inferred rather than confirmed, it says so.

---

## 1. What the platform is

- **REA Backoffice** is a betting/casino operator back office built on the
  **gr8.tech "UBO"** platform. The brand we work with is **JBCL** (Jugabet
  Chile), timezone `America/Santiago`.
- The relevant subsystem is the **CRM Journey Builder** — a visual, node-based
  automation tool. A "journey" is a flow that players enter and move through:
  it can offer promotions, issue freebets, send notifications, wait, branch on
  conditions, etc.
- API base URL (JBCL):
  ```
  https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/journey-builder/v0
  ```
- Brand is sent as the `x-brand: JBCL` header on every request.

---

## 2. Authentication

- Auth is a **Bearer JWT** in the `Authorization` header. Tokens are
  short-lived and expire frequently.
- The token's JWT payload has `typ: "Bearer"` and an `exp` (expiry) claim. The
  console script validates both before using a captured token (rejects tokens
  with < 30s left).
- Two ways we obtain it:
  1. **Direct (Python runner)**: paste a fresh token into `.env` as
     `AUTH_TOKEN`. Optionally a `COOKIE` for session-bound endpoints.
  2. **Console script (no token copying)**: a generated browser script hooks
     `window.fetch` and `XMLHttpRequest.setRequestHeader` to **capture the auth
     token from the page's own requests** the next time the logged-in
     backoffice tab makes any API call. This avoids ever copy/pasting tokens.

There is no password auth for these APIs — only the Bearer token issued to a
logged-in backoffice session.

---

## 3. The two API endpoints that matter

The whole cloning workflow uses just two endpoints:

### 3.1 Reserve a journey identifier
```
POST {BASE}/journeys/identifier
Content-Type: application/x-www-form-urlencoded
```
- Returns a fresh journey id of the form **`JRN-...`** (e.g. `JRN-0-598872`).
- The response may be a **bare string** (`"JRN-0-598872"`) or an **object**
  like `{"journeyId":"JRN-..."}` / `{"identifier":"..."}` — our parsers handle
  both shapes (`parse_identifier_response` in Python, the same logic inline in
  the console script).
- You call this **once per draft** you intend to create, before posting it.

### 3.2 Create a draft
```
POST {BASE}/journey-drafts
Content-Type: application/json
```
- Body is the full journey object (see §5).
- On success: returns the created draft.
- On failure: returns the journey object with `status: "CreationFailed"` and an
  **`aggregatedError`** block describing exactly which activities failed and
  why (this is gold for debugging — see §7).

---

## 4. The four journey types in a campaign

A single "promocode match campaign" is **four separate journeys**, created
together. Creation order matters (see §6.3).

| Type        | Name tag | Starts                         | Stops                              |
|-------------|----------|--------------------------------|------------------------------------|
| `followup`  | FollowUp | immediately after publish (now)| match day + 2 → 00:00 local        |
| `bfr`       | BFR      | immediately after publish (now)| 2h-before-match minus 1 minute     |
| `two_hours` | 2H       | match time − 2 hours           | match time                         |
| `aft`       | AFT      | match time + 1 minute          | next day 00:00 local               |

- **"Immediately after publish"** journeys (`followup`, `bfr`) set
  `isImmediatelyAfterPublish: true` and `startAt = now`.
- **Match-relative** journeys (`two_hours`, `aft`) compute `startAt`/`stopAt`
  from the match datetime.
- All times are written to the API in **UTC** with a .NET-style fractional
  second on the top-level fields (`...T17:00:00.0000000Z`) and a plain
  `...Z` form inside `rawJourneyData.infoValues`. Timezone id sent is
  `Chile/Continental`.

### 4.1 The 2H → FollowUp link
The `two_hours` journey contains a **Campaign Connector** activity whose
`HostJourneyId` must point at the **FollowUp journey created in the same run**.
That's why `followup` is always created first: its real `JRN-...` id is then
substituted into the 2H connector before 2H is posted.

---

## 5. The journey object model

A draft body is a large JSON object. The fields that matter for cloning:

### 5.1 Top-level identity / scheduling
- `reservedJourneyId` — the `JRN-...` id reserved in §3.1.
- `journeyName` — display name, e.g.
  `JBCL|SP|uch vs espanol|PrmCode-JUGAKING|FollowUp | 29.06`.
- `brand`, `currencyCodes` (`["CLP"]`), `timeZoneId`.
- `startAt`, `stopAt`, `isImmediatelyAfterPublish`.
- `duplicatedFromId` / `duplicatedFromVersion` — lineage pointers (see §6.1).

### 5.2 `activities[]` — the executable graph
Each activity is a node. Common shapes:
- `activityId` — **UUID**, the node's identity.
- `activityName` — type, e.g. `promotion`, `multipurpose_promotion`,
  `freebet`, `deposit`, `notification_center`, `wait_interval`,
  `external_system_source` (the "API" entry node), `campaign_connector`,
  `end_of_path`, `end_of_journey`.
- `events[]` — outgoing transitions. Each event has a `nextActivityId`
  (another `activityId`) and an event name like `PromotionAccepted`,
  `FreebetIssued`, `WaitTimeCompleted`, `NotificationSent`, etc. This is how
  the graph is wired.
- `dependencies[]` — references to other activities via `journeyActivityId`
  (data dependencies, e.g. a freebet depends on the promotion's `PromotionId`).
- `initializationData` — the activity's config. For promotions this holds
  `promotionId`, `promotionLinkId`, `promotionDisplayId`, placements,
  `ContentId`/`FrontId`, etc. For notifications it holds templates, languages,
  `objectForSend` (with `metadata.journeyName`), variables, etc.

### 5.3 `rawJourneyData` — the visual editor's mirror
This is the **React-flow front-end state**: `elements[]` (nodes + edges with
`x/y` positions, `ports`, `handles`), `infoValues` (a second copy of name /
dates / brand / etc.), `pathesConfiguration`, `boundaryConfiguration`, and
**`activitiesConfiguration`** (a per-activity config map keyed by `activityId`).

**Critical:** many things appear **twice** — once in `activities[]` and once in
`rawJourneyData`. Edits often have to be applied to both. Examples:
- `journeyName` (top-level, `rawJourneyData.infoValues.journeyName`, and inside
  each notification's `objectForSend.metadata.journeyName`).
- dates (`startAt`/`stopAt` top-level and in `infoValues`).
- `promotionDisplayId` (in `activities[].initializationData` **and** in
  `rawJourneyData.activitiesConfiguration[id].data`).

### 5.4 ID classes (this is the heart of cloning)
There are two fundamentally different kinds of identifier in the payload:

| Kind | Examples | Clone behaviour |
|------|----------|-----------------|
| **External references** (point at real platform objects) | `promotionId`, `promotionLinkId`, `ContentId`, `FrontId`, `contentId`, `templates` (notification template ids) | **Keep unchanged** — the draft must keep pointing at the same promotions/content. |
| **Structural ids** (the journey's own internal graph) | `activityId`, `id` (node ids), and everything that embeds them: `nextActivityId`, `journeyActivityId`, port/handle ids, edge `source`/`target` | **Regenerate** consistently per clone. |
| **Server-minted unique ids** (platform assigns; must NOT be reused) | `campaignId` (campaign connector), `promotionDisplayId` | **Strip/blank** so the server mints fresh ones. |
| **Lineage metadata** | `duplicatedFromId`, `duplicatedFromVersion` | **Remove** — create as a standalone draft. |

Understanding this table is the difference between a clone that works and one
the platform rejects.

---

## 6. How cloning works (what the cloner does to a captured template)

A "template" is a real journey's `POST /journey-drafts` body, captured from
Chrome DevTools via **Copy as fetch** and extracted with `extract_templates.py`
(it un-escapes the `"body"` string field into clean JSON). Templates live in
`templates/<team>/<type>.json`.

For each draft, `prepare_body()` transforms the template:

### 6.1 Remove lineage
`strip_duplicate_lineage()` drops `duplicatedFromId` / `duplicatedFromVersion`.
Re-posting these tells the backoffice "this is another copy of journey X",
which fails when a copy already exists. We always reserve a fresh id, so the
lineage is just stale.

### 6.2 Clear server-minted unique ids
- `clear_stale_campaign_connector_ids()` — blanks `campaignConnectorConditions.
  campaignId`. The captured template carries the original campaign binding; the
  backoffice rejects re-use with *"the journey with the same identifier already
  exists"*. Blank it → backoffice mints a fresh campaign binding (same state as
  an unlinked connector in the UI).
- `strip_promotion_display_ids()` — removes every `promotionDisplayId`. The
  backoffice mints these server-side per promotion activity; re-posting the
  source journey's display ids fails with HTTP **422
  `already-existing-promotion-display-id`**: *"Promotion activity with
  PromotionDisplayId: 'NNN' already exists"*. Dropping them lets the backoffice
  assign new ones, exactly like adding a promotion in the UI. These ids are
  pure display metadata — nothing else references them.

### 6.3 Regenerate internal activity ids
`regenerate_internal_ids()` collects every `activityId`/`id` UUID, maps each to
a fresh `uuid4`, and does a **global string replace** across the serialized
JSON. Because ports, handles, edges, and the `rawJourneyData.
activitiesConfiguration` keys all **embed** the activity id as a substring, a
string-level replace keeps the entire graph internally consistent. External
reference ids (different keys) are left untouched.

Why: a captured template reuses the source journey's activity UUIDs. Posting
them claims ids already owned by the live source journey → rejected with
*"activities with the same identifier already exist in other journeys"*.

> **Console-script nuance:** the generated browser script regenerates these
> activity UUIDs **again at paste time** (in JS, mirroring the Python logic), so
> that re-pasting the *same* generated script never collides with drafts a
> previous paste already created. Each paste is independent.

### 6.4 Substitute campaign variables
`deep_replace()` swaps, as plain string replacements throughout the JSON:
- old promocode → new code (also `set_promocode_everywhere()` updates
  `promocodeSettings.values` and "Promo codes: X" display lines).
- old match text → new match name (handles apostrophe variants like
  `O'higgins` / `O’Higgins`, longest-first to avoid partial overlaps).
- old date label (`DD.MM`) → new date label.
- the 2H connector's old `HostJourneyId` → the new FollowUp `JRN-...`.
- team asset swaps (`asset_overrides`: old image URL → club image URL).

Old values come from two sources: curated per-team hints (`Team.old_codes`,
`old_match_texts`, `old_date_labels`) **and** values derived from the template
itself (`_derive_from_name()` parses the journey name; `_template_promocodes()`
reads `promocodeSettings`).

### 6.5 Set name, id, dates
- `build_journey_name()` builds the per-type name (each type has slightly
  different spacing/format — see the function; these are matched exactly by the
  verifier).
- A per-run uniqueness tag (`#DDMM-HHMMSS`) is appended by default so
  re-creating the same campaign doesn't collide on the journey name (disable
  with `--no-unique-name`).
- `set_dates()` writes `startAt`/`stopAt`/`isImmediatelyAfterPublish`/
  `timeZoneId` to both the top level and `rawJourneyData.infoValues`.
- "Start now" journeys are **staggered by a minute each** (`now_offset_minutes`)
  so two immediate journeys in one run don't share an identical `startAt`.

### 6.6 Verify before posting
`verify_body()` runs a checklist (name matches, reservedJourneyId set, no
leftover old campaign values, promocode correct, dates sane, **no stale
campaignId**, **no stale promotionDisplayId**, 2H connector points at the new
FollowUp). The runner refuses to POST a draft that fails verification.

---

## 7. Reading platform errors (debugging playbook)

The single most useful debugging artifact is the **`POST /journey-drafts`
response on failure**. When creation fails, the platform returns the journey
object with:

```json
"status": "CreationFailed",
"aggregatedError": {
  "journeyError": { "errorType": "CreateJourneyError", "description": "ActivitiesFailed" },
  "journeyActivityError": [
    {
      "activityId": "…",
      "activityName": "promotion",
      "problemDetails": [
        {
          "type": ".../already-existing-promotion-display-id",
          "title": "Promotion activity with PromotionDisplayId: '677571' already exists'",
          "status": 422
        }
      ]
    }
  ]
}
```

`journeyActivityError[].problemDetails[].type` is a stable, machine-readable
error slug — **always read that, not just the human title**. It names the
exact field/constraint.

### Known "already exists" failure modes (and fixes)
These all surface with similar wording but are **different fields**. They were
discovered one at a time:

1. **`duplicatedFromId` present** → "the journey with the same identifier
   already exists" → remove lineage (§6.1).
2. **Identical `startAt` for two immediate journeys** → second is rejected →
   stagger by a minute (§6.5).
3. **Reused `campaignId`** in the 2H campaign connector → "same identifier
   already exists" → blank it (§6.2).
4. **Reused `activityId`s** (re-running the same generated script) →
   "activities with the same identifier already exist in other journeys" →
   regenerate internal ids; the console script also regenerates at paste time
   (§6.3).
5. **Reused `promotionDisplayId`** → HTTP 422
   `already-existing-promotion-display-id` → strip them (§6.2).

### General rule
The platform enforces uniqueness on **server-minted identity fields** across
all journeys for a brand. Any such field baked into a captured template will
collide on the second-or-later creation. The fix pattern is always: **identify
the field from `problemDetails.type`, then strip/blank/regenerate it in
`prepare_body` so the server assigns a fresh one.** There may be more such
fields we haven't hit yet; the diagnostic loop is reliable.

### Cleanup note
A failed creation leaves an **archived `CreationFailed` journey** (e.g.
`JRN-0-598872`) in the backoffice. It's harmless but should be deleted
periodically to keep the journeys list clean.

---

## 8. Activity types seen in these journeys

From the captured FollowUp/2H journeys:

- **`external_system_source` ("API")** — the entry node; players are added here
  (`PlayerAdded` activation event).
- **`multipurpose_promotion`** — an offer with **choosable flows** (a split into
  parallel paths the player picks from). Holds `flowsData` / `flowsSetup` and a
  `split` with `pathId`/`flowId`/`nextActivityId`.
- **`promotion`** — a single offer (e.g. "Active Promotion (30%)"). Carries
  `promotionId`, `promotionLinkId`, `promotionDisplayId`, placements
  (`PromoLobby`, `Cashier`), deposit-rate, freebet max amounts, etc.
- **`deposit`** — a condition node ("deposit ≥ X within 1 day"); branches into
  Satisfied / Unsatisfied / Canceled.
- **`freebet` ("Sport FreeBet")** — issues a freebet; branches into Issued /
  Not issued / Used / Timeout / Canceled.
- **`notification_center` / "On-site messaging"** — sends a templated message
  (push/pop-up). Holds `templates` id, languages, `objectForSend` with
  variables and `metadata.journeyName`.
- **`wait_interval` ("Wait")** — delays (`waitPeriod` ISO-8601 duration like
  `P0Y0M0DT1H0M0S`).
- **`campaign_connector`** — links this journey to another (the 2H→FollowUp
  link). Holds `campaignConnectorConditions` with `campaignId` + `HostJourneyId`.
- **`end_of_path` / `end_of_journey`** — terminal nodes.

Boundary/branch behaviour lives in `rawJourneyData.boundaryConfiguration` and
`pathesConfiguration`; the visual node graph in `rawJourneyData.elements`.

---

## 9. Teams / template inheritance

The cloner supports multiple "teams" (clubs):

- **`udch`** (UDCH) — has its own captured templates in `templates/udch/`.
- **`colocolo`** (Colo Colo) — **inherits** UDCH templates via `base_team`; it
  only declares an `asset_overrides` map (old image URL → Colo Colo image URL)
  for the one differing visual. A club-specific file dropped in
  `templates/colocolo/` takes precedence over the inherited one.

This avoids duplicating very large template files when two clubs share a journey
design and differ only by an image.

---

## 10. The toolchain (files)

| File | Purpose |
|------|---------|
| `extract_templates.py` | Turn a DevTools "Copy as fetch" of `POST /journey-drafts` into a clean template JSON. |
| `create_journeys.py` | The core. Prepares + verifies + (optionally) posts the 4 drafts directly via the API. Holds all the transform logic (`prepare_body`, the strip/clear/regenerate functions, `verify_body`). |
| `generate_console_script.py` | Renders a **self-contained browser console script** that does the API calls from a logged-in backoffice tab (captures token, reserves ids, regenerates activity ids at paste time, posts drafts). Reuses `prepare_body`/`verify_body`. |
| `web_ui.py` | A small local HTML form wrapper around the runner. |
| `app/services/journey_cloner_runner.py` | Integrates the cloner into the main app's admin UI (runs the scripts as subprocesses, manages templates per team). |

### Two ways to create drafts
1. **Direct API** (`create_journeys.py`, on a machine that can reach the
   backoffice API + has a token in `.env`).
2. **Console script** (for a locked-down work laptop on the office VPN that
   can't run Python but has a logged-in browser): generate the `.js`, paste
   into DevTools console. **Important: generated scripts are snapshots** — after
   any cloner code change, **regenerate** the script; old `.js` files keep the
   old behaviour.

---

## 11. Practical gotchas / lessons learned

- **Edit both copies.** Anything user-visible (name, dates, promocode) lives in
  both `activities[]`/top-level and `rawJourneyData`. Miss one and the journey
  is inconsistent.
- **String-replace, not key-walk, for ids that are embedded.** Activity ids are
  substrings of port/handle/edge ids, so regeneration must be a global text
  replace to stay consistent.
- **Never touch external reference ids.** `promotionId`, `promotionLinkId`,
  `ContentId`, `FrontId`, notification `templates` ids point at real platform
  objects — changing them breaks the offer/content.
- **Server-minted ids are the enemy of cloning.** `campaignId`,
  `promotionDisplayId` (and possibly others) must be cleared so the server
  re-mints them. The error message wording ("identifier already exists") is the
  same for several different fields — rely on `problemDetails.type`.
- **Tokens expire fast.** Prefer the console script's auto-capture over pasting
  tokens; never commit tokens (`.env` is git-ignored; `COOKIE`/`AUTH_TOKEN`
  must stay out of the repo).
- **A failed POST still creates an archived shell journey.** Clean these up.
- **Re-running an already-run console script** is now safe (activity ids
  regenerate at paste time + display ids/campaign id are stripped), but the
  cleanest path for a partial failure is to re-create only the missing types
  (`--types ...`, and `--followup-id JRN-...` to relink 2H).

---

## 12. The bigger picture: three subsystems, not one

A player-facing promotion is assembled from **three independent backoffice
subsystems** that reference each other by id. This is the single most important
mental model:

```
  PROMO PAGE  ──or──  RANDOMIZER (Fortune Wheel)
  (banner / landing)  (weighted random prize picker)
        │                      │
        │  each entry / each prize points at →   journeyId + activityId
        ▼                      ▼
                 PLAYER JOURNEY(S)
        (deliver the actual reward: freebet / free spins /
         casino bonus / promotion, gated by deposit, etc.)
```

- **Journey Builder** (`/crm/journey-builder/v0`) — the reward engines (§1–§11).
- **Promo** (`/crm/promo/v2`) — the *front door*: **Promo Pages** and
  **Randomizers** (the Fortune Wheel). These are **NOT journeys**; they live in
  a different API and reference journeys as their payload.

So "build a Spin-the-Wheel promo" = build the reward **journeys** first, then
build a **Randomizer** whose prizes point at those journeys' entry activities.
The wheel does the *random selection + visuals*; the journey does the *reward*.

API base for this subsystem (JBCL):
```
https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm/promo/v2
```

---

## 13. Randomizer / Fortune Wheel (`POST /promo-drafts/randomizer`)

The Fortune Wheel is a **Randomizer** promo object. Captured example:
`JBCL|SP|WOF|09.06.26` — a 6-prize sport wheel.

Key fields:
```jsonc
{
  "type": "Randomizer",
  "randomizationType": "FortuneWheel",   // the wheel UI
  "randomizerShotPolicy": "Once",        // 1 spin per player  (= "1 spin per player")
  "playerVisibility": "Authorized",      // must be logged in to spin
  "internalName": "JBCL|SP|WOF|09.06.26",
  "urlShortName": "sport-09-06-2026",
  "showDate": "...", "hideDate": "...",  // when the wheel is visible
  "startDate": "...", "endDate": "...",  // when it's active
  "languages": ["en","es"],
  "currencies": [{"brand":"JBCL","currency":null}],
  "isUsedInJourney": false,
  "daysToAccept": null,
  "promoCode": null,                     // can gate entry behind a promocode
  "contentId": "...", "frontId": "...",  // visual content (the candle/birthday skin lives here)
  "filterConditions": [ /* segment targeting, see §15 */ ],
  "prizes": [ /* see below */ ]
}
```

### Prizes — weighted random, each routed to a journey
Every prize is a **`JourneyPrize`** with a `weight`. **Weights sum to 100** (they
are percentages of the wheel). On spin, the platform picks a prize by weight and
**routes the player into that journey's specific activity**.

```jsonc
"prizes": [
  {
    "weight": 36.9,                 // 36.9% chance
    "type": "JourneyPrize",
    "isEmptyPrize": false,          // true = a "no win" wheel segment
    "isLimitedPrize": false,        // true = capped-quantity prize…
    "prizeQuantity": null,          // …e.g. set to 3 for "3 winners" physical prizes
    "journeyPrizeSettings": {
      "journeyId": "JRN-0-222272",
      "activityId": "ff2e626c-7ec7-4c1c-859e-078ef18004be",  // the entry activity inside that journey
      "activityDescription": "JBCL | SP | RB - Wheel of fortune | Dep | Freebet",
      "isEmptyPrize": false
    }
  }
  // … more prizes, weights total 100
]
```

The captured wheel's six prizes (weights): Free Money `0.1`, Free Bonuses `3`,
Dep Bonus `25`, Bet Insurance `10`, Dep Freebet `36.9`, Bet Freebet `25`
→ **= 100**.

**This answers two earlier unknowns:**
- The **randomizer is `weight`-based** here, not a journey node. To make a
  3-prize wheel, define 3 prizes with weights summing to 100.
- **Limited / physical prizes** (e.g. "3 headset winners"): set
  `isLimitedPrize: true` + `prizeQuantity: 3`. Use `isEmptyPrize: true` for
  "better luck next time" segments.

---

## 14. Promo Page (`POST /promo-drafts/promo-page`)

A **Promo Page** is the banner/landing entry point (the "banner on promotions
page" trigger). Captured example: `JBCL|CS|GOW-24-06-26` (Game of the Week).

```jsonc
{
  "type": "PromoPage",
  "internalName": "JBCL|CS|GOW-24-06-26",
  "brand": "JBCL",
  "playerVisibility": "Unauthorized",    // banner visible even when logged out
  "showDate": "...", "startDate": "...", "endDate": "...",
  "currencies": [{"brand":"JBCL","currency":"CLP"}],
  "currencyMode": "single",
  "languages": ["en","es"],
  "urlShortName": "<uuid-or-slug>",
  "contentId": "...", "frontId": "...",  // the page visual/content
  "filterConditions": [ /* segment targeting, see §15 */ ],
  "promotionSettings": {
    "type": "JourneyPromotion",
    "journeyPromotionSettings": {
      "journeyId": "JRN-0-577417",
      "activityId": "615a8e8d-93cd-466f-aa4e-42f848283fbf",  // entry activity in the journey
      "activityDescription": "JBCL | CS | RB - Game of the week | 50 FS"
    }
  }
}
```

So a Promo Page **routes a player into one journey activity** (vs. the wheel,
which routes to one-of-N by weight). Both use the same `{journeyId, activityId}`
hand-off to the Journey Builder.

> Both Randomizer and Promo Page also do a `POST /promo/v2/s3/copy` first
> (copies visual assets in S3) before the draft `POST`. The `contentId` /
> `frontId` reference those assets.

---

## 15. Segment targeting (`filterConditions`)

Both promo objects target audiences with a `filterConditions[]` array. Each
condition:
```jsonc
{
  "key": "Sport" | "Business" | ...,
  "filterType": "fairplay_business_segment" | ...,
  "conditionType": "MultiSelect",
  "operator": "in" | "notIn",
  "values": [ {"id": 31, "name": "Negative"}, {"id": 40, "name": "VIP-Platinum"}, … ]
}
```
- The Game-of-Week page **excluded** the `Negative` business segment
  (`operator: "notIn"`).
- The wheel listed VIP / risk segments (`VIP-Platinum/Gold/Silver`,
  `Suspicious`, `Scammer`, `Arbitrageur`, …) — this is how "All active players"
  vs. a VIP-only wheel is expressed.

---

## 16. Casino reward activity types (Journey Builder)

From the **Game of the Week** journey (`JBCL | CS | Game of the week | 50 FS`),
the casino reward nodes that the sport templates never showed:

### `freespin_bonus` — casino free spins
```jsonc
"freespinActivity": {
  "spins": 50,
  "provider": "jugabet-games",
  "lobbyGameId": "jugabet-games-la-gran-copa-jugabet",
  "walletGameId": "gg_la_gran_copa_jugabet",
  "externalGameId": "gg_la_gran_copa_jugabet",
  "productType": "slots", "subcategory": "freeSpin",
  "withWagering": true,
  "spinsExpirationDuration": 86400000,        // ms (24h)
  "startAt": "...", "stopAt": "...",
  "currenciesConfig": {"CLP": {"betAmount": 20000, "minBonusAmount": 10000, "maxBonusAmount": 20000000}}
}
```
Output paths: `FreespinBonusCollectingFinished` (→ next reward), `FreespinBonusNotUsed`,
`FreeSpinsBonusTermsNotComplied`, `FreespinBonusRejectConfirmed`, plus
withdrawal/abort variants.

### `casino_bonus_v2` — wagering (deposit-match) casino bonus
```jsonc
{
  "activitySubtype": "deposit", "productType": "slots",
  "bonusPercent": 100,                         // 100% deposit match
  "wageringRequirement": 30,                    // x30 wagering ("x25 on winnings" → 25)
  "limitType": "multiplier", "releaseLimitMultiplier": 15,
  "bonusExpirationTime": 172800000,             // ms (48h)
  "withoutLockBalance": false,
  "currenciesConfig": {"CLP": {"maxBonusAmount": 20000000, "releaseLimitAmount": 0}},
  "wageringActivity": { /* nested mirror; dependencyMechanic: "FreeSpin" */ }
}
```
Output paths: `WageringBonusFinished`, `WageringBonusLost`, `WageringBonusForfeited`,
`WageringBonusExpired`, `WageringBonusRejectConfirmed`, `WageringBonusCancelledByWithdrawalConfirmed`,
`WageringBonusAwardAborted`.

### `event_detector` — server-side event watcher
A non-interactive condition that subscribes to a platform event for a window:
```jsonc
"properties": {
  "startingOptions": {"durationTime": "P0Y0M1DT0H0M0S"},   // watch for 1 day
  "subscriptionOptions": [{
    "event": {"eventName": "deposit.approved", "sourceName": "platform.orders"},
    "filter": {"condition": "and", "filters": [
      {"property": {"name":"amount","value":"CLP","operator":"greaterThanOrEqualCurrency"}, "variables":[{"value":"15000"}]},
      {"property": {"name":"amount","value":"CLP","operator":"lessThanCurrency"},          "variables":[{"value":"25000"}]}
    ]}
  }]
}
```
Output paths: `DetectorSuccess` / `DetectorFailed`. Used to detect a deposit in
a value band (e.g. route by deposit size) without the interactive `deposit` node.

### Game-of-the-Week flow (reconstructed)
```
[API entry] → [Multipurpose Promotion: pick 1 of 4 deposit tiers]
   small/middle/big/bigger → [Deposit ≥ 10k/20k/30k/50k]
        Satisfied → [Freespin Bonus: 50 FS "La Gran Copa"]
              CollectingFinished → [Casino Bonus v2: 100% match, x30 wagering] → End
```
`metadata.productType: "Casino"`, `reEntryRule: Prohibited` (one entry/player).

### Useful constants
- Durations are **milliseconds**: `86400000` = 24h, `172800000` = 48h.
- ISO-8601 durations on deposit/wait/detector: `P0Y0M3DT0H0M0S` = 3 days.
- Promo dates use `04:00:00Z` = Chile midnight (UTC−4).

---

## 17. The design / visual layer (and how Figma would connect)

This is the part the user flagged as "the most problematic." The **design** of a
Promo Page or Randomizer is **not** stored in the promo draft itself — the draft
only holds two pointers, `contentId` and `frontId` (UUIDs). The actual visuals
live in a **micro-frontend (mf) asset bundle in S3**, served through:
```
GET /api/ubo/api/v0/.../aws-get/mf/v1/<id>/...
```

### 17.1 How the two pointers map
| Draft field | S3 bundle | Holds |
|-------------|-----------|-------|
| `frontId` | `mf/v1/<frontId>/spa/settings.json` (+ `widget/settings.json`) | **Theme / layout**: colours, background image, layout toggles |
| `contentId` | `mf/v1/<contentId>/spa/content/content-<lang>-<hash>` (+ `widget/...`) | **Copy + images** per language (`en`, `es`) |

Each bundle has **two render targets**: `spa/` (the full promo page) and
`widget/` (the small banner widget). There's also a per-module default at
`mf/player/<ModuleType>/assets/...` (`Randomizer`, `MultipurposePromotion`,
`WidgetModulor`) used as a fallback.

When a draft is created, `POST /promo/v2/s3/copy` (empty body) **clones a base
asset bundle** and returns the new prefix `mf/v1/<uuid>` — that uuid becomes the
draft's `contentId` / `frontId`.

### 17.2 `frontId` → `settings.json` (the theme)
Randomizer example:
```jsonc
{
  "headerColor": "#613249",
  "fortuneWheelColor": "#b6de13",                 // wheel-only
  "background": {
    "imageUrl": "mf/v1/background/34befd6e-….png", // S3 path to the bg PNG
    "filePath": "mf/v1/background/34befd6e-….png",
    "name": "Wheel bg.png"
  },
  "withDescription": true,
  "hiddenBlocks": [],                              // e.g. ["prizes"] to hide a section
  "redirects": [ { "id": "…", "redirect": {"targetPage":"to_bonus"} } ],
  "listGroupBonuses": [ … ]                        // ordering/grouping of prize cards
}
```
Promo-Page example is the same shape (`headerColor: "#189EF8"`,
`background.imageUrl: "mf/v1/background/…png"`, `hiddenBlocks: ["prizes"]`).

So the **theme = a few hex colours + a background PNG + layout toggles.**

### 17.3 `contentId` → `content-<lang>.json` (copy + images)
Keys are a mix of **text** and **image keys**. Image keys are S3 media paths
`<bundle>/spa/media/<uuid>.png`:
- `prizeDefaultImageKey` — fallback prize image (`Randomizer/assets/spa/media/box.png`).
- `HeaderImageKey` — the page hero image (promo page).
- **per-prize** `"<prizeActivityId>.prizeImageKey"` — the icon shown for each
  wheel prize, keyed by the **same `activityId`** the prize points at in the
  randomizer draft (§13). This is the link between a prize's reward and its
  picture.
- text keys: titles, button labels, terms — e.g. `randomizerBtnSpinText`,
  `randomizerRewardTitle`, `TitleKey`, `TermsDescriptionText`,
  `"prize_<id>.prizeTextKey"` (the prize's caption), localized per `en`/`es`.

### 17.4 Journey design — two places
A journey's visuals come from **two** sources:

**(a) Notification content** (sport-style journeys): each `notification_center`
carries a `templates` id and an `objectForSend.variables` list with image URLs —
`background_image_src`, `icon-src`, `icon` — pointing at
`https://static.contentin.cloud/<account>/<uuid>.png`, plus localized text.
That's the cloner's `asset_overrides` mechanism.

**(b) Placement visual bundles** (casino-style / promo journeys): the
`multipurpose_promotion` and `promotion` activities carry **`placements[]`**
whose `data.ContentId` / `data.FrontId` (and per-flow `flowsData[].contentId`)
point at the **same `mf/v1/<id>` S3 bundles** described in §17.1–17.3. **These are
the "visual settings in the journey" that must be changed before publishing** —
they are how the offer/prize art is shown to the player. Confirmed from the
Game-of-Week journey (see §17.8).

### 17.5 So "change the design" means, concretely:
1. Replace the **background PNG** (`settings.json → background.imageUrl`) and/or
   **header/prize PNGs** (`content → *ImageKey`) in the S3 bundle.
2. Change the **hex colours** (`headerColor`, `fortuneWheelColor`).
3. Change the **text keys** per language.
4. Re-`POST` the draft (the `contentId`/`frontId` keep pointing at the bundle).

For journeys: swap the `static.contentin.cloud` image URLs and notification
template variables.

### 17.6 Connecting Figma — the realistic plan
There is **no native Figma integration** in REA — the platform only consumes
PNGs + hex + text from the S3 bundle. So Figma connects via a **custom export
pipeline** we'd build:

1. **Figma file conventions.** Name layers/frames so they map to keys:
   - a frame `background` (1920×1080) → `settings.background.imageUrl`
   - a frame `header` → `content.HeaderImageKey`
   - frames `prize/<slot>` → each prize's `<activityId>.prizeImageKey`
   - colour **styles/variables** `header`, `wheel` → `headerColor`,
     `fortuneWheelColor`
   - text layers → the corresponding text keys (per `en`/`es`).
2. **Pull from Figma REST API** (needs a Figma token + file key):
   - `GET /v1/files/{key}` — node tree + layer names.
   - `GET /v1/images/{key}?ids=…&format=png&scale=2` — export named frames as PNG.
   - colour tokens from node `fills` / `GET /v1/files/{key}/styles`; text from
     node `characters`.
3. **Upload the exported PNGs** into the promo asset bundle and get back their
   `mf/v1/<id>/spa/media/<uuid>.png` paths.
4. **Write** those paths + hex + text into `settings.json` / `content-<lang>.json`,
   then `POST` the `promo-drafts/randomizer` (or `/promo-page`) draft.

**Upload endpoints (now captured — the pipeline is fully buildable):**
- **`POST /promo/v2/s3/upload`** (JSON) — writes a **JSON file** to the bundle.
  Body: `{"path":"mf/v1/<id>/spa/settings.json","data":{…}}`; returns
  `{"path":"…"}`. Used for `settings.json` and `content-<lang>.json`.
- **`POST /promo/v2/s3/upload-content`** (multipart/form-data) — writes a
  **binary file**. The multipart **field name is the target S3 path** (e.g.
  `mf/v1/<id>/widget/media/widgetImgKey.png`) and the part body is the file
  bytes; returns `["mf/v1/…png"]`.
- (`POST /promo/v2/s3/copy` still clones a base bundle to get a fresh
  `mf/v1/<uuid>` prefix first.)

So the full **Figma → REA** flow is now:
1. Figma REST export the named frames → PNGs (and read hex/text).
2. `s3/copy` → fresh bundle prefix.
3. `s3/upload-content` each PNG to its slot path (see the slot list in §17.7).
4. `s3/upload` the `settings.json` + `content-en.json` / `content-es.json`
   referencing those paths + hex + text.
5. `POST` the `randomizer` / `promo-page` draft pointing `contentId`/`frontId`
   at the bundle.

Still required externally: a Figma API token + the design file key, and a
naming convention in the Figma file that maps layers → the slot keys in §17.7.

### 17.7 The recurring image slots ("the same photos, every time")
Per promo, the **same fixed set of image slots** is replaced each time. Each
bundle renders in **three targets** — `spa/` (full page), `widget/` (banner),
`widgetModulor/` (modular widget) — so most images are uploaded once per target.

| Slot key | Path | What it is |
|----------|------|------------|
| `widgetImgKey` | `mf/v1/<id>/widget/media/widgetImgKey.png` | the **banner/widget** image (the thing on the promotions page) |
| `HeaderImageKey` | `mf/v1/<id>/spa/media/HeaderImageKey.png` | the **page hero/header** image |
| `prizeImageKey` | `mf/v1/<id>/spa/media/prizeImageKey.png` | the main **prize** image |
| `prizeDefaultImageKey` | `…/{spa,widget,widgetModulor}/media/box.png` | default prize "box" image (per target) |
| `<itemId>.itemImageKey` | `mf/v1/<id>/spa/media/<uuid>.png` | per **bonus-item** image (one per listed bonus) |
| `<prizeActivityId>.prizeImageKey` | `mf/v1/<id>/spa/media/<uuid>.png` | per **wheel-prize** image (randomizer; keyed by the prize's `activityId`) |
| `background.imageUrl` | `mf/v1/background/<uuid>.png` | page **background** (in `settings.json`) |

That's the answer to "always the same photos to be changed": a campaign swap =
re-upload **widgetImgKey + HeaderImageKey + background + one image per
prize/bonus item**, then rewrite the text keys + hex colours. Everything else in
the bundle is boilerplate that can be copied from the base via `s3/copy`.

> Summary: design = **hex colours + PNGs + localized text** in an S3 mf-bundle
> referenced by `contentId`/`frontId`, written via `s3/upload` (JSON) and
> `s3/upload-content` (files). Figma → REA is now a fully specified build-it
> pipeline; the only externals are a Figma token, the file key, and a layer
> naming convention.

### 17.8 Worked example: Game-of-Week — every picture changed before publish
Captured from a full "change all the pictures" session. The journey's
`multipurpose_promotion` + 4 `promotion` placements reference **5 visual
bundles**; the images uploaded into them (via `s3/upload-content`) are:

| Bundle (`ContentId`) | Bound to | Images |
|----------------------|----------|--------|
| `f9107c2e…` | Multipurpose Promotion (offer) | `widgetImgKey.png`, **`prizeImageKey.png`**, **4× `<flowId>.itemImageKey.png`** |
| `e3b199fb…` | Promotion "small dep" | `widgetImgKey.png`, `bonusHeaderImage.png` |
| `22ea33ce…` | Promotion "middle dep" | `widgetImgKey.png`, `bonusHeaderImage.png` |
| `1f4afead…` | Promotion "big dep" | `widgetImgKey.png`, `bonusHeaderImage.png` |
| `d8cefb1a…` | Promotion "bigger dep" | `widgetImgKey.png`, `bonusHeaderImage.png` |

The 4 multipurpose **flow `contentId`s** equal the 4 `itemImageKey` filenames in
`f9107c2e` — i.e. each wheel/offer flow has its own tier image.

**The logos** (the square game-logo cut, e.g. 360×330) are the
**`prizeImageKey` + the 4 `itemImageKey`** slots = **5 logo placements in the
journey**, plus the **promo page's `prizeImageKey`/`HeaderImageKey`** → the same
logo is reused **~6 places** across journey + promo page. The wide
**`widgetImgKey`** is the banner/card (e.g. 474×256); **`bonusHeaderImage`** is a
per-tier header.

> Note: pixel dimensions are **not** in any API payload and image bytes are
> usually not captured in HARs — size categories (360×330 etc.) come from the
> Figma/asset spec, so map them to slots by name (`itemImageKey`/`prizeImageKey`
> = logo, `widgetImgKey` = banner), or fetch the live images and measure.

### 17.9 Worked example: Promo Page — "one photo, used everywhere"
Captured from editing the GOW **promo page** (single bundle `9cdc2ebb`). One
source photo is placed into **3 image slots**; the UI stores a **separate uuid'd
copy per slot**:

| Slot | Target | Stored file |
|------|--------|-------------|
| `widgetImgKey` | `widget/` | `466e3dd9-….png` (banner/card) |
| `HeaderImageKey` | `spa/` | `7c4b35cd-….png` (hero) |
| `prizeImageKey` | `spa/` | `70f6edc8-….png` (logo) |
| `prizeDefaultImageKey` | `spa/` | `box.png` (left as default) |
| `background.imageUrl` | `spa/` | unchanged |

So **"upload one photo and use it everywhere" = the same source image is uploaded
once per slot**, each becoming its own `mf/v1/<bundle>/<target>/media/<uuid>.png`.
The slot→media mapping is then written by `s3/upload` (content JSON) and saved by
`PUT /promo-drafts/promo-page`.

**Net difference in scope:**
- **Promo page** = 1 bundle, ~3 image slots (`widgetImgKey`, `HeaderImageKey`,
  `prizeImageKey`).
- **Journey** = 1 offer bundle (`widgetImgKey` + `prizeImageKey` + N tier
  `itemImageKey`) + 1 bundle per deposit-tier promotion (`widgetImgKey` +
  `bonusHeaderImage`).

A Figma→REA tool would therefore take **one logo + one banner + one header**
source image and fan them out across all these slot paths in both objects.

---

## 18. Open questions / unknowns

- Whether there are **further server-minted unique fields** beyond `campaignId`
  and `promotionDisplayId` that a clone must clear (none known to remain, but
  the pattern has recurred).
- Whether `promotionDisplayId` should be **removed** (current approach) vs
  **blanked** — removal has been chosen as the closest match to "freshly added
  in the UI"; confirm against a live successful creation.
- The exact server-side semantics of `campaignId` blank vs absent.
- Whether `journeySource` / `version` / `changeHistory` fields have any effect
  when posting a fresh draft (currently passed through from the template).
- **Promo subsystem cloning**: the `promo/v2` Randomizer and Promo Page almost
  certainly carry their own server-minted ids (`contentId`, `frontId`,
  `promotionDisplayId`, the draft id) that would need the same strip/regenerate
  treatment if we ever clone *them*. Not yet exercised by the cloner (the cloner
  currently only builds journeys, not promo pages/wheels).
- Whether `freespin_bonus` / `casino_bonus_v2` carry a server-minted unique id
  analogous to `promotionDisplayId` (watch for it when cloning casino journeys).

**Now solved (previously open):**
- The **wheel randomizer** is a `promo/v2` Randomizer with weighted
  `JourneyPrize` entries — NOT a journey node (§13).
- **Casino free spins / wagering bonus** are the `freespin_bonus` /
  `casino_bonus_v2` activities (§16).
- **Limited / physical prizes** = `isLimitedPrize` + `prizeQuantity` on a wheel
  prize (§13).

These are the spots to watch if a new "already exists" or validation error
appears: capture the failing `POST /journey-drafts` (or `promo-drafts`)
response, read `aggregatedError.journeyActivityError[].problemDetails[].type`,
and extend the strip/regenerate logic in `prepare_body`.
