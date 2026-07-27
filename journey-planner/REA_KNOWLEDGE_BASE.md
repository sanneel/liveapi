# REA Backoffice — Knowledge Base for the AI Journey Builder

Purpose: a single reference an AI-assisted builder (and its human reviewers)
can ground itself in when turning a campaign brief into REA Backoffice objects.

## How to read this document — TRUST LEVELS

Every fact here is tagged so the builder knows what to rely on:

- **[VERIFIED]** — taken directly from a real captured object (the birthday
  promo HAR, brand JBCL) or from working code (`create_journeys.py`). Exact wire
  field names. Trust for generation.
- **[GR8-DOC]** — from GR8's official product docs / onboarding. Describes the
  UI and product behaviour. Field names are *conceptual* and may NOT match the
  wire JSON. Use for meaning and grammar, NOT for exact field names.
- **[INFERRED]** — reasoning not yet confirmed against a capture. Treat as a
  hypothesis; verify before relying on it.
- **[UNKNOWN]** — an open question. The builder must not guess here.

**Golden rule of precedence when sources disagree:**
captured object > working code > GR8 official doc > inference.

**Golden rule of grounding:** the builder never invents journey structure. It
assembles from captured objects and fills gaps only with rules recorded here.

---

## 1. The three subsystems (the core mental model) [VERIFIED]

A player-facing promo is assembled from THREE independent backoffice subsystems
that reference each other by id. Almost every bug comes from an id not crossing
a boundary cleanly.

```
  PROMO PAGE            RANDOMIZER (Fortune Wheel)
  (banner / landing)    (weighted random prize picker)
        │                      │
        │  each entry / prize points at →   { journeyId, activityId }
        ▼                      ▼
                 PLAYER JOURNEY(S)
        (deliver the actual reward: freespins / freebet /
         casino bonus / promotion, gated by deposit, etc.)
```

1. **Journey Builder** (`/crm/journey-builder/v0`) — the reward engines. A
   journey is a node graph players move through.
2. **Promo** (`/crm/promo/v2`) — the *front door*: Promo Pages and Randomizers.
   These are NOT journeys; they reference journeys as their payload.
3. **Design / Content** — visuals live in S3 "mf" bundles referenced by
   `contentId` / `frontId`; email lives in Content Studio.

The hand-off between subsystems is always the pair **`{ journeyId, activityId }`**
— the specific entry activity inside a journey that a prize/page routes a player
into.

---

## 2. The dual-storage rule (the #1 footgun) [VERIFIED]

Every journey is stored **twice inside one payload**, and both copies must agree:

| Copy | Where | Who reads it |
|---|---|---|
| Compiled / runtime | `body.activities[]` | the journey engine at runtime |
| Editor mirror | `body.rawJourneyData` | the visual builder UI |

`rawJourneyData` contains:
- `elements[]` — canvas nodes + edges (positions, ports, handles, event labels)
- `activitiesConfiguration{}` — a dict **keyed by activityId**, mirroring each
  activity's config
- `infoValues` — a second copy of the top-level scheduling/name fields
- `pathesConfiguration`, `boundaryConfiguration`, `exitCriteriaSettings` — branch
  / boundary wiring

**Any user-visible edit (name, dates, promocode, content) must be written to
BOTH copies** or the journey ships inconsistent. "Content not changing" almost
always means the `rawJourneyData` mirror wasn't updated.

**`elements[]` (the canvas layout) has no generator.** [VERIFIED] It is always
copied from a captured template, never synthesized. This is the single biggest
constraint on the builder — see §9.

---

## 3. Top-level journey object keys [VERIFIED]

From captured JBCL journeys:

```
activities, rawJourneyData, journeyName, journeyId, reservedJourneyId,
brand, currencyCodes, timeZoneId, startAt, stopAt, isImmediatelyAfterPublish,
isUnlimited, isArchived, reEntryRule, metadata, journeySource, status, version,
author, createdAt, changedAt, changeHistory, testControlGroupParameters,
activityEventConversionMetrics, allJourneyActivationsCount,
overJourneyActivationsCount, areJourneyMetricsAvailable,
duplicatedFromId, duplicatedFromVersion
```

Notes:
- `startAt` may be `null` when `isImmediatelyAfterPublish: true`.
- Dates use TWO formats: top-level uses .NET fractional seconds
  (`...T04:00:00.0000000Z`); `rawJourneyData.infoValues` uses plain
  (`...T04:00:00Z`). A single formatter everywhere is a bug. [VERIFIED]
- `brand: "JBCL"`, `currencyCodes: ["CLP"]`, `timeZoneId: "Chile/Continental"`.
- `duplicatedFromId`/`duplicatedFromVersion` are lineage — strip when cloning.

---

## 4. Every activity object has the same envelope [VERIFIED]

```
activityId            UUID — the node's identity (regenerate on clone)
activityName          the type, e.g. "promotion", "freespin_bonus"
activityDisplayName   human label shown on the card (must be set explicitly;
                      NOT derived from translation keys)
events[]              outgoing transitions (see below)
dependencies[]        data deps on other activities via journeyActivityId
dataDependencies[]    keys this activity needs (e.g. CurrencyCode, BrandDomain)
dataKeys              keys this activity produces
initializationData    the activity's config (shape differs per type)
isEditable, version, changedBy, changedAt, eventsHistory, tcGroupEvents
```

### events[] — how the graph is wired [VERIFIED]

The graph is encoded ENTIRELY in `events[*].nextActivityId`. There is no
separate edges array in `activities[]`.

```
{ "eventName": "PromotionAccepted", "eventType": "Completion",
  "nextActivityId": "<uuid of next activity>" }
```

- `eventType: "Completion"` — a real transition; `nextActivityId` points at the
  next activity.
- `eventType: "Boundary"` — fires at a moment (e.g. offer shown), usually
  `nextActivityId: null`; used to attach notifications/reminders ("Boundary
  Events" in the UI). [GR8-DOC + VERIFIED]

---

## 5. Activity catalogue (the palette) [VERIFIED palette + mixed wire names]

The live JBCL Tools panel groups activities as below. `wire` = the
`activityName` seen in captured JSON (blank = not yet captured → builder cannot
generate it safely).

### Input Source
| UI label | wire `activityName` | notes |
|---|---|---|
| Custom Segment | `dwh_source` [VERIFIED] | DWH/segment audience; holds `filterDetails` tree |
| Reference codes | *(uncaptured)* [UNKNOWN] | promocode-triggered entry |
| CSV | *(uncaptured)* [UNKNOWN] | uploaded player list |
| API | `external_system_source` [VERIFIED] | API/externally triggered; `targetSystem` e.g. `"Randomizer"`, `"PromoPage"`; keys: `description, targetSystem, webhookId, isWebhookUrlHidden, displayData` |
| Predefined Segment | *(uncaptured)* [UNKNOWN] | |
| Events | *(uncaptured)* [UNKNOWN] | real-time event entry |
| Promotion (as source) | *(uncaptured)* [UNKNOWN] | greyed in capture |

All sources fire activation event **`PlayerAdded`** into the first real
activity. [VERIFIED]

### Flow control
| UI label | wire | notes |
|---|---|---|
| Decision split | `ams_decision_split` [VERIFIED] | rules-based audience split; used in the birthday freespin prize for value-based routing |
| Random split | *(uncaptured)* [UNKNOWN] | |
| SMS / Email / Native push / On-site engagement split | `notification_center_engagement_split` [VERIFIED], `email_engagement_split` / `*_engagement_split` [GR8-DOC] | branch on Sent/Read/Clicked; must follow the matching comms + Wait/Date |

### Communication
| UI label | wire | notes |
|---|---|---|
| On-site messaging | `notification_center` [VERIFIED] | `contract:1` = Notification (bell), `contract:5` = Pop-up |
| SMS | `dextra_sms` [VERIFIED code] | text stored in 3 places; needs `BrandDomain` |
| Email | `dextra_email` [VERIFIED] | references Content Studio content by `CSE-0-#####` |
| Native push | `native_push` [GR8-DOC] | *(uncaptured)* |
| Web push | *(uncaptured)* [UNKNOWN] | |
| WhatsApp | *(uncaptured)* [UNKNOWN] | |

### Delays
| UI label | wire | notes |
|---|---|---|
| Wait | `wait_interval` [VERIFIED] | `waitPeriod` ISO-8601 (`P0Y0M1DT0H0M0S` = 1 day) + `exitCriteria`; events: `WaitTimeStarted`(B), `WaitTimeCompleted`(C) |
| Date | `wait_date` [VERIFIED — sport_promos.har] | wait until fixed date; init keys: `waitTo, waitStrategy, timezoneMode, exitCriteria`; events: `WaitTimeStarted`(B), `WaitTimeCompleted`(C) |
| Event Detector | `event_detector` [VERIFIED elsewhere] | watches a platform event for a window; `DetectorSuccess`/`DetectorFailed` |

### Connectors
| UI label | wire | notes |
|---|---|---|
| Campaign Connector | `campaign_connector` [VERIFIED] | links journeys; see §6 |
| Outgoing API request | *(uncaptured)* [UNKNOWN] | |

### Multiple flows
| UI label | wire | notes |
|---|---|---|
| Parallel flows | `parallelFlow` (rawJourneyData element) [GR8-DOC] | run branches in parallel |
| Choosable flows | *(in `multipurpose_promotion` split)* [VERIFIED partial] | player picks 1 of N |

### Promotion type
| UI label | wire | notes |
|---|---|---|
| Promotion | `promotion` [VERIFIED] | single offer; carries reward config + placements |
| Multipurpose Promotion | `multipurpose_promotion` [VERIFIED] | offer with choosable/parallel flows |

### Conditions
| UI label | wire | notes |
|---|---|---|
| Deposit | `deposit` [VERIFIED] | gate; events `DepositConditionSatisfied/Unsatisfied/Canceled`(C) + `DepositConditionAccepted`(B); init `depositConditions` |
| Deposit Collection | *(uncaptured)* [UNKNOWN] | cashback collection |
| Bet Insurance | *(uncaptured)* [UNKNOWN] | |
| Bet | `sport_bet_condition` [VERIFIED — sport_promos.har] | init keys: `betTypes, betsCount, channels, lineTypes, minBetAmount, minItems, minOdd, minOddItemParlay, availableEvents/Sports/Tournaments, sportTickets, isBetBuilderRequired, expireInDays`; events: `Satisfied/Unsatisfied/Terminated/Canceled`(C) + `Activated`(B) |
| Bet Collection | *(uncaptured)* [UNKNOWN] | |
| Casino Bet Collection | *(uncaptured)* [UNKNOWN] | |

### Reward type
| UI label | wire | notes |
|---|---|---|
| Casino FreeSpin | `freespin_bonus` [VERIFIED] | see §7 |
| Casino Bonus | `casino_bonus_v2` [VERIFIED] | wagering/deposit-match; see §7 |
| Sport FreeBet | `freebet` [VERIFIED] | |
| Sport Bonus | *(uncaptured)* [UNKNOWN] | wagering sport bonus |
| Money Bonus | *(uncaptured)* [UNKNOWN] | cash to main balance |
| Coins Bonus | *(uncaptured)* [UNKNOWN] | |

### Terminals
| UI label | wire | notes |
|---|---|---|
| — | `end_of_path` [VERIFIED] | ends one branch |
| — | `end_of_journey` [VERIFIED] | ends the whole journey |

---

## 6. Campaign Connector — how journeys link [VERIFIED]

`campaign_connector.initializationData.campaignConnectorConditions`:
```
campaignId              server-minted UUID — BLANK to "" on clone (else 409)
campaignProductType
campaignSubProductType
activityData.HostJourneyId   the JRN-* of the journey being linked to
```
On clone: blank `campaignId`, and repoint `HostJourneyId` at the correct
journey created in the same run.

---

## 7. Reward activity detail [VERIFIED]

### freespin_bonus — `initializationData.freespinActivity`
```
spins                 e.g. 30
provider              e.g. "jugabet-games"
lobbyGameId           e.g. "jugabet-games-la-gran-copa-jugabet"
walletGameId / externalGameId
gameTranslationKey / providerTranslationKey
productType, subcategory, withWagering, allowReject
spinsExpirationDuration   ms (86400000 = 24h)
startAt / stopAt          free-spin validity window (plain Z)
currenciesConfig.CLP = {
   betAmount: 12000, betAmount_majorUnits: 120,
   minBonusAmount: 10000, minBonusAmount_majorUnits: 100,
   maxBonusAmount: 5000000, maxBonusAmount_majorUnits: 50000
}
```
Also set `activityDisplayName` = "<provider_name> | <game_name>" on the activity
AND `rawJourneyData.activitiesConfiguration[id].displayName` — it is NOT derived
from the translation keys.

### casino_bonus_v2 — `initializationData`
```
activitySubtype ("deposit"), productType ("slots")
bonusPercent          100 = 100% match
wageringRequirement   x-multiplier (25, 30, ...)   ← "x25 on winnings" = 25
limitType, releaseLimitMultiplier
bonusExpirationTime   ms (172800000 = 48h)
withoutLockBalance, allowReject
currenciesConfig.CLP.maxBonusAmount
wageringActivity{}    nested mirror
```

### event_detector — `initializationData` [VERIFIED — Giro Finde HAR]
Watches for a server-side event within a time window.
```
initializationData keys: displayData, placements, properties, usedVariables
properties.startingOptions.durationTime   ISO-8601 (e.g. P0Y0M1DT0H0M0S = 1 day)
properties.subscriptionOptions[]:
    event: { eventName: "deposit.approved", sourceName: "platform.orders" }
    filter: { property: { name, type, value, operator }, variables: [{ name, type, value }] }
    useV2Flow: true
    shouldCollectEvents: false
```
Example filter: `amount greaterThanOrEqualCurrency CLP 5000` = "deposit ≥ $50".
Events: `DetectorSuccess`(C), `DetectorFailed`(C), `DetectorStarted`(B),
`EventNotReceived`(B), `EventReceived`(B).

### deposit — `initializationData.depositConditions` [VERIFIED — both HARs]
```
depositConditions keys: channelsCondition, depositAccountingType,
                        expirationTimeout, minDepositAmounts, payGroups
minDepositAmounts: [{ brand, amount (minor units), currencyCode }]
expirationTimeout: ISO-8601 duration (e.g. P0Y0M1DT0H0M0S = 1 day)
```

### Money units [VERIFIED]
CLP amounts are stored in **minor units (×100)**: `12000` minor = `$120`.
Fields carry both: `amount` (minor) + `amount_majorUnits` (major).

### Durations [VERIFIED]
Milliseconds for bonus expiry (`86400000`=24h, `172800000`=48h). ISO-8601 for
wait/deposit/detector (`P0Y0M1DT0H0M0S`=1 day). Promo dates use `04:00:00Z` =
Chile midnight (UTC−4).

---

## 8. ID classes — the heart of cloning [VERIFIED]

| Class | Examples | Action |
|---|---|---|
| External references | `promotionId`, `promotionLinkId`, `ContentId`, `FrontId`, notification `templates` | **KEEP** — point at real platform objects |
| Structural ids | `activityId`, `id`, and everything embedding them (`nextActivityId`, `journeyActivityId`, ports, handles, edge source/target, `activitiesConfiguration` keys) | **REGENERATE** consistently (global string-replace old→new UUID) |
| Server-minted | `promotionDisplayId` (strip), `campaignConnectorConditions.campaignId` (blank to "") | **STRIP / BLANK** so server re-mints |
| Lineage | `duplicatedFromId`, `duplicatedFromVersion` | **REMOVE** |

The regenerator matches only UUIDs that are values of keys named `activityId` or
`id`, then string-replaces on the serialized JSON so all embedded refs update
together.

**Watch list (id-like fields NOT handled — verify before trusting):** [UNKNOWN]
- `flowId` (appears in choosable-flow journeys; unconfirmed whether structural)
- `webhookId` on `external_system_source`
- `campaignId` semantics: blank vs absent
- whether `freespin_bonus`/`casino_bonus_v2` carry any server-minted unique id
  analogous to `promotionDisplayId`

---

## 9. What the builder CAN and CANNOT do [VERIFIED reasoning]

**CAN (reliably):** take a captured journey/randomizer, swap the campaign values
(game, bets, dates, promocode, names, routed journey ids), strip/blank/regenerate
ids, sync both storage copies, verify, and create. This is proven.

**CANNOT (safely):**
- Generate `rawJourneyData.elements` (canvas) from scratch. Always copy from a
  capture.
- Build an activity type with no captured example (see [UNKNOWN] rows in §5).
- Invent structure from a brief. A brief is *intent*, not structure.

**Therefore the builder is an ASSEMBLER, not a generator.** It composes real
captured pieces and only fills gaps with the rules in §11.

---

## 10. The promo subsystems [VERIFIED from birthday HAR]

### Randomizer — `POST /promo/v2/promo-drafts/randomizer`
Returns `{ id: <numeric> }` (HTTP 201). Key fields:
```
type: "Randomizer"
randomizationType: "FortuneWheel" | "ScratchCard"    ← two confirmed types
randomizerShotPolicy: "Once"          ← 1 spin/player (SEPARATE from visibility)
playerVisibility: "Authorized" | "Unauthorized"
    ↳ "Unauthorized" = visible to logged-OUT / anonymous visitors too (public,
      acquisition, anniversary, "anyone can spin" wheels).  ← birthday wheel used this
    ↳ "Authorized"   = only logged-IN players see it (segment-gated / retention wheels).
    Pick from the brief's audience: "everyone / all visitors / before login" →
    Unauthorized;  "our players / a segment / logged-in" → Authorized. [VERIFIED — birthday HAR]
internalName, urlShortName
showDate/hideDate      when visible
startDate/endDate      when active
promoCode, isUsedInJourney, contentId, frontId
filterConditions[]     audience
prizes[]               weighted, see below
```
[VERIFIED — birthday HAR (FortuneWheel), randomizers.har (ScratchCard + 2× FortuneWheel)]

**Prizes are weighted `JourneyPrize`s; weights sum to 100.** Each prize:
```
weight, type:"JourneyPrize", isEmptyPrize, isLimitedPrize, prizeQuantity,
journeyPrizeSettings: { journeyId, activityId, activityDescription }
```

### Promo Page — `POST /promo/v2/promo-drafts/promo-page` [VERIFIED — promop_age.har]
Returns `{ id: <numeric> }` (HTTP 201). Routes a player into ONE journey activity.

```
type: "PromoPage"
brand, internalName, urlShortName
playerVisibility: "Authorized" | "Unauthorized"
showDate, startDate, endDate          (dotnet .0000000Z format)
contentId, frontId                    (visual bundle pointers)
currencies: [{ brand, currency }]
currencyMode: "single"
languages: ["en","es"]
filterConditions[]                    (audience targeting, same as randomizer)
promotionDisplayId: null              (not pre-minted for promo pages)
riskLevels: null
promotionSettings: {
    type: "JourneyPromotion",
    journeyPromotionSettings: {
        journeyId: "JRN-0-...",
        activityId: "<entry activity uuid>",
        activityDescription: "..."
    }
}
```

**Promo Page build order** (per page):
```
1.  2× POST /contents/v1/copy         (fork visual bundle)
2.  1× POST /promo/v2/promo-drafts/promo-page  (create, returns {id})
3.  1× PUT  /promo/v2/promo-drafts/promo-page/<id>  (initial save)
4.  N× POST /promo/v2/s3/upload        (write JSON to bundle — settings, content)
    +  POST /promo/v2/s3/upload-content (write binary images)
5.  1× PUT  /promo/v2/promo-drafts/promo-page/<id>  (final save after visuals)
```

Both do a `POST /promo/v2/s3/copy` first to fork a visual bundle.

---

## 11. Brief-invisible rules (HIGHEST-VALUE knowledge) [VERIFIED from birthday HAR]

These are decisions the platform/operator requires but a brief will NEVER state.
The builder must apply them from here, not from the brief.

1. **Every wheel needs an Empty Prize journey.** Even a 3-prize brief produced a
   4th prize: `isEmptyPrize: true, weight: 0`, routing to a near-empty journey
   (`external_system_source → end_of_journey`). The wheel needs a routable target
   for the "no win" segment.
2. **A physical/limited prize is a notify-only journey.** No reward activity —
   just `notification_center` (+ campaign_connectors). The wheel prize sets
   `isLimitedPrize: true, prizeQuantity: N`. Delivery is manual/coordinated.
3. **Visibility and spin-count are separate fields.** "1 spin per player" →
   `randomizerShotPolicy: "Once"`. "who can see it" → `playerVisibility`. Do not
   conflate. **Choosing the value is itself brief-invisible:** a public /
   acquisition / anniversary wheel that anonymous or logged-out visitors can play
   → `playerVisibility: "Unauthorized"`; a wheel gated to logged-in players or a
   segment → `"Authorized"`. Default an "anyone can spin" wheel to `Unauthorized`
   (the birthday wheel was Unauthorized). Flag the choice with ⚠.
4. **Daily-drip freespins = N freespin_bonus activities separated by
   `wait_interval`s, NOT one scheduled activity.** "100 FS/day × 3 days" in the
   birthday casino follow-up was 3 freespins + waits.
5. **Value-based prizes use `ams_decision_split`.** "value based on player value"
   → a decision split routing to different reward tiers.
6. **A wheel prize's `activityId` must be the journey's ENTRY activity** (the
   `external_system_source`), so the player lands at the start of the reward
   journey.

*(This list grows every time a new capture reveals another such rule. Append,
never assume completeness.)*

---

## 12. Worked fixture — the Birthday promo (3 Years JugaBet) [VERIFIED]

The reference campaign. 1 randomizer + 6 journeys.

| Object | Id | Role |
|---|---|---|
| Wheel | `RND-0-16617` | `JBCL|BD|WHEEL|01.07`, url `birthday`, 4 prizes, `playerVisibility: "Unauthorized"`, `randomizerShotPolicy: "Once"` |
| Freespin Prize | `JRN-0-599527` | weight 69.9% — promotion+freespin+casino_bonus ×3 tiers + `ams_decision_split` |
| Freebet Prize | `JRN-0-599599` | weight 30.08% — promotion + freebet |
| Physical Prize | `JRN-0-599605` | weight 0.02%, limited qty 3 — notify-only |
| Empty Prize | `JRN-0-600736` | weight 0, isEmptyPrize — entry → end |
| Casino Follow-up | `JRN-0-600218` | deposit → 300 FS (3×freespin + waits) + casino_bonus + comms + email |
| Sport Follow-up | `JRN-0-600958` | deposit → 30% match freebet + comms + email |

The wheel's 4 prizes route into the first 4 journeys via `{journeyId,
activityId}`. The 2 follow-ups are reached separately (deposit-offer banner).

**This is the builder's answer key**, not its output spec. Success = "produces a
functionally equivalent set of objects the operator signs off on and the platform
accepts," NOT byte-equality with this HAR.

---

## 13. The actual build order (how the UI creates a journey) [VERIFIED — Giro Finde create HAR]

This was the biggest unknown, now solved. The Giro Finde HAR captured a real
create session (brand PMCL/FTCL, 3 journeys). The exact sequence the backoffice
UI follows per journey:

```
1.  5× POST /promo/v0/promotion-display-identifier
       → server mints { promotionDisplayId: 741930 } per promotion activity
       → these are PRE-ALLOCATED before the draft is posted
2.  1× POST /journey-builder/v0/journeys/identifier
       → reserves JRN-0-###### (form-urlencoded)
3.  70× POST /contents/v1/copy
       → forks visual bundles for each promotion placement
       → body: { sourcePath: "mf/v1/<old>/spa", destinationPath: "mf/v1/<new>/spa" }
       → returns { destinationPath: "mf/v1/<new>/spa" }
4.  1× POST /journey-builder/v0/journey-drafts
       → creates the draft (full body, HTTP 201)
```

Repeat for each journey in the campaign. Journeys with no promotions (like the
comms journey) skip steps 1 and 3 — they go straight from reserve-id to
POST draft.

**Key discovery: `promotionDisplayId` is pre-minted by the UI.** The UI calls a
separate endpoint (`/promo/v0/promotion-display-identifier`) BEFORE posting the
draft, one call per promotion activity. This is why re-posting a captured
template's display ids fails — they're already registered. The cloner's approach
of stripping them is correct; the server re-mints them on its own during draft
creation. But there IS also an explicit mint endpoint if you want to pre-allocate.

**Key discovery: `POST /contents/v1/copy` is how visual bundles are forked.**
70 calls per journey = one copy per visual target path (spa/widget/widgetModulor
× each promotion's ContentId/FrontId bundle). This replaces the older
`POST /promo/v2/s3/copy` for journey visual bundles.

### Second brand confirmed [VERIFIED]

This capture is brand `PMCL` (`x-brand: PMCL`), operator name `FTCL` (Fortuna
Chile). Journey names: `FTCL | CS | Giro Finde JULY 18.07`. Same API, same
endpoints, same structure as JBCL. The only difference is
`brand: "PMCL"`, `currencyCodes: ["CLP"]`, and deposit brand references use
`"PMCL"` instead of `"JBCL"`. Confirms the system is multi-brand.

### Randomizer create sequence [VERIFIED — randomizers.har]

Per randomizer, much simpler than journeys:
```
1.  2× POST /contents/v1/copy    (fork the visual bundle — spa + widget)
2.  1× POST /promo/v2/promo-drafts/randomizer   (full body)
       → returns { id: 73557 }   (HTTP 201)
```
No separate reserve-id step (unlike journeys). No promotion-display-id step.
The response is just `{ "id": <numeric> }` — NOT a `RND-0-*` string.

Three types captured in one session: `ScratchCard` (FTCL), `FortuneWheel`
sport (JBCL, 6 prizes), `FortuneWheel` casino (JBCL, 4 prizes).

### Journey create + immediate PUT pattern [VERIFIED — sport_promos.har]

The sport promos HAR shows a consistent pattern per journey:
```
1.  N× POST /promo/v0/promotion-display-identifier
2.  1× POST /journey-builder/v0/journeys/identifier
3.  N× POST /contents/v1/copy
4.  1× POST /journey-builder/v0/journey-drafts      (creates the draft)
5.  1× PUT  /journey-builder/v0/journey-drafts/<id>  (updates it immediately)
```
Step 5 is new — the UI creates then immediately PUTs. Likely saves the visual
bundle references or other post-create edits. The PUT uses the numeric id from
the create response (e.g. `638977`), not the `JRN-*` id.

---

## 14. Endpoint catalogue [VERIFIED + code]

Base CRM: `https://pmi.rea-backoffice.gr8.tech/api/ubo/api/v0/crm`
Journey base appends `/journey-builder/v0`.

| Purpose | Method + path |
|---|---|
| **Mint promotion display id** | **`POST /promo/v0/promotion-display-identifier`** → `{ promotionDisplayId: N }` [NEW — Giro Finde] |
| Reserve journey id | `POST /journey-builder/v0/journeys/identifier` → `JRN-0-#####` |
| **Fork visual bundle** | **`POST /contents/v1/copy`** body `{ sourcePath, destinationPath }` [NEW — Giro Finde] |
| Create journey draft | `POST /journey-builder/v0/journey-drafts` |
| Update journey draft | `PUT /journey-builder/v0/journey-drafts/<id>` |
| Read journey | `GET /journey-builder/v0/journeys/<JRN>` |
| Randomizer draft | `POST /promo/v2/promo-drafts/randomizer` → `RND-0-#####` |
| Promo page draft | `POST /promo/v2/promo-drafts/promo-page` |
| Fork visual bundle | `POST /promo/v2/s3/copy` |
| Upload JSON to bundle | `POST /promo/v2/s3/upload` |
| Upload binary to bundle | `POST /promo/v2/s3/upload-content` |
| Email content | `POST /content-studio/v0/eb-backoffice/email/contents` → `CSE-0-#####`, then `POST .../<CSE>`, then `PATCH .../<CSE>/publish` |
| Visual bundle read | `GET /api/aws-get/mf/v1/<id>/{spa,widget,widgetModulor}/...` |

Headers on every call: `authorization: Bearer <jwt>`, `x-brand: JBCL`,
`content-type` per endpoint. Tokens ~5-min expiry (Keycloak). A failed create
still leaves an archived shell journey — clean up periodically.

---

## 12b. Worked fixture — Giro Finde (PMCL/FTCL) [VERIFIED — CREATE session]

The first captured CREATE session. Brand PMCL (Fortuna Chile). 3 journeys.

| Object | Id | Role |
|---|---|---|
| Main journey (18.07) | `JRN-0-621795` | 149 activities: 5× (promotion+deposit+event_detector+freespin_bonus+casino_bonus_v2+notification_center) + ends. Immediate start. |
| Comms journey | `JRN-0-621796` | dwh_source (segment "Fortunazo players 1+dep") → 2× notification_center + 2× event_detector + 2× wait_interval + dextra_sms. No startAt/stopAt (unlimited). |
| Main journey (19.07) | `JRN-0-621799` | Same 149-activity shape as 18.07, different date. |

**New things this revealed:**
- The exact build order (§13): display-id mint → reserve JRN → 70× contents/copy → POST draft.
- `event_detector` full structure (deposit.approved event, amount filter).
- `dwh_source` with `currentTemplate` (a saved segment reference).
- `dextra_sms` with `rawValues.messageText` containing the promo page link.
- Brand PMCL (second brand), confirming multi-brand on same API.
- A journey with 149 activities / 5 tiers — largest captured so far.
- `promotionDisplayId` is pre-minted by the UI (but the cloner's strip approach also valid).

---

## 14. Failure → cause → fix (debugging playbook) [VERIFIED]

On a failed `POST /journey-drafts`, read
`aggregatedError.journeyActivityError[].problemDetails[].type` — the stable slug,
not the human title.

| Symptom | Real cause | Fix |
|---|---|---|
| "journey with the same identifier already exists" | `duplicatedFromId` present | strip lineage |
| same, on 2nd immediate journey | identical `startAt` | stagger by 1 min |
| same, on 2H/linked journey | reused `campaignId` | blank it |
| "activities with the same identifier already exist" | reused `activityId`s | regenerate internal ids |
| HTTP 422 `already-existing-promotion-display-id` | reused `promotionDisplayId` | strip it |

General rule: the platform enforces uniqueness on server-minted identity fields
across all journeys for a brand. Identify the field from `problemDetails.type`,
then strip/blank/regenerate it.

---

## 15. Design / visual layer (summary) [VERIFIED + code]

Design is NOT in the draft — the draft holds two pointers, `contentId` (copy +
images) and `frontId` (theme: colours + layout). Actual assets live in an S3
"mf" bundle rendered in targets `spa/` (full page), `widget/` (banner),
`widgetModulor/`.

Recurring image slots per promo: `widgetImgKey` (banner), `HeaderImageKey`
(hero), `prizeImageKey` (main prize/logo), `<prizeActivityId>.prizeImageKey`
(per-wheel-prize icon, keyed by the prize's activityId), `bonusHeaderImage`
(per-tier), `background.imageUrl` (in settings.json). A campaign swap = re-upload
these + rewrite text keys + hex colours; everything else copies from the base via
`s3/copy`. The birthday "candle/bday" theme lives entirely here.

Figma → REA is a buildable pipeline (export named frames → `s3/copy` →
`s3/upload-content` PNGs → `s3/upload` settings/content JSON → POST draft) but
needs a Figma token + file key + a layer-naming convention. Not yet built.

---

## 16. Open questions / capture backlog [UNKNOWN]

To expand coverage, capture a real (create-session) HAR for each:
- Any [UNKNOWN] activity in §5 (Sport Bonus, Money Bonus, Bet, Bet Insurance,
  Collections, Web push, WhatsApp, CSV/Events/Reference-code sources, Date,
  Outgoing API, Random split, Parallel/Choosable flow internals).
- A **create** session (POST/PUT order, id wiring, s3 uploads) — the birthday
  HAR is view-only (all GETs), so build ORDER is not yet captured.
- The **Promo Page** object body (not present in the birthday capture).
- Resolution of the §8 watch-list id fields.

When a new "already exists"/validation error appears: capture the failing POST
response, read `problemDetails[].type`, add a row to §14, and if it revealed a
brief-invisible requirement, add a rule to §11.

---

*Knowledge base v1. Grounded in the JugaBet Chile (JBCL) birthday promo HAR
capture and the journey-cloner code. Treat [GR8-DOC] field names as conceptual;
verify against a fresh capture before relying on any field name for a new
campaign type.*
