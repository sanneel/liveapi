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

**Why the section numbers jump.** §§2–4, 8 and 13–16 are not missing — they moved
to `REA_BUILD_MECHANICS.md` (dual storage, the activity envelope, ID classes,
build order, the endpoint catalogue, the debugging playbook, the visual layer).
That file is deliberately NOT injected into the planner prompt: the planner
produces plans and specs, the composer does the POSTing. So a pointer here to a
section you cannot see means it lives there. Numbers are kept stable rather than
renumbered, so older cross-references still resolve.

**What outranks this document.** Three prompt sections do, in this order: the
CORRECTIONS list (highest — operator-taught, append-only, and where two of its
bullets conflict the LATER one wins), then the RECIPES CATALOG and the GAMES
REGISTRY, which are generated from the code and so cannot drift. Where this
document disagrees with one of those, that one wins — and the disagreement is a
bug worth reporting, not a judgement call to make mid-plan.

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

## 5. Activity catalogue (the palette) [VERIFIED palette + mixed wire names]

The live JBCL Tools panel groups activities as below. `wire` = the
`activityName` seen in captured JSON (blank = not yet captured → builder cannot
generate it safely).

### Input Source
| UI label | wire `activityName` | notes |
|---|---|---|
| Custom Segment | `dwh_source` [VERIFIED] | DWH/segment audience; holds `filterDetails` tree. Chain alias `segment` / `csv` |
| Reference codes | `registration` [VERIFIED — udch/two_hours.json] | promocode-triggered entry; takes `promocode`. Fires `PlayerAdded` (an Activation), so it can only ever be the ENTRY node |
| CSV | *(uncaptured)* [UNKNOWN] | uploaded player list. The chain composer's `csv` alias maps to `dwh_source`, not to a real CSV node |
| API | `external_system_source` [VERIFIED] | API/externally triggered; `targetSystem` e.g. `"Randomizer"`, `"PromoPage"`; keys: `description, targetSystem, webhookId, isWebhookUrlHidden, displayData`. This is the entry for a journey a randomizer routes winners into |
| Predefined Segment | *(uncaptured)* [UNKNOWN] | |
| Events | *(uncaptured)* [UNKNOWN] | real-time event entry |
| Promotion (as source) | *(uncaptured as a SOURCE)* [UNKNOWN] | greyed in capture. `promotion` is captured as a mid-chain activity — that is a different thing |

All sources fire activation event **`PlayerAdded`** into the first real
activity. [VERIFIED]

### Flow control
| UI label | wire | notes |
|---|---|---|
| Decision split | `ams_decision_split` [VERIFIED] | rules-based audience split; used in the birthday freespin prize for value-based routing. Paths `DecisionSplitPassedPath01..20` + `RemainderPath` |
| Random split | `random_split` [VERIFIED — udch/two_hours.json] | captured and chainable; no default forward event, so a chain node MUST name its path with `follow` or `branches` |
| SMS / Email / Native push / On-site engagement split | `notification_center_engagement_split` [VERIFIED], `email_engagement_split` [VERIFIED — casino/gow_comms.json] | branch on Sent/Read/Clicked; must follow the matching comms + Wait/Date. NC paths `NCEngagementSplitPassedPath01..05`; email paths `Path1..Path6` |

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
| Sport FreeBet | `freebet` [VERIFIED] | settings: `amount` (minor), `max_odds`, `expire_days` |
| Sport Bonus | `sport_bonus` [VERIFIED — udch/two_hours.json] | wagering sport bonus. Chainable, forward event `SportBonusFinished`, but NO settings are wired yet — a `sport_bonus` node ships two_hours' own values |
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

## 10a. What a randomizer spec can and cannot change [VERIFIED — randomizer_campaign.py + the three captured templates]

A wheel or scratch card is built by `randomizer_campaign.py` from a captured
template. Unlike a journey, it has **no knob layer and no inherited-content
guard** — the spec overrides a short list of fields and everything else ships
exactly as captured. Knowing which is which is the difference between a plan
that describes the draft and a plan that describes something the operator never
receives.

**Settable from a MODE 6 spec** (these are the whole list):

| field | how |
|---|---|
| `kind` | `sport_wof` \| `casino_wof` \| `casino_scratch` — picks the template |
| `date` / `dates` | one draft per date; each date re-anchors show/start/end/hide |
| `days` | window length (defaults per kind: 1, 1, 2) |
| `weights` | one per slice, in template order, summing to 100 |
| `journeys` | one per slice, in template order — the journey each prize routes to |
| `internal_name`, `url_short` | otherwise derived from the kind + date |

**NOT settable — inherited from the template, silently:**

| field | what the templates carry today | why it matters |
|---|---|---|
| `randomizerShotPolicy` | `"Once"` in all three | a brief asking for a spin per deposit, or a daily spin, still ships `Once` |
| `playerVisibility` | `"Authorized"` in all three | §11.3 says a public/anniversary wheel should be `Unauthorized`; the build cannot do it |
| `filterConditions` | the captured campaign's audience (e.g. casino_wof's `Business: Premium, Negative`) | the new wheel targets the old campaign's segment |
| `contentId` / `frontId` | the captured campaign's visual bundle | the new wheel wears the old one's artwork |
| `isEmptyPrize`, `isLimitedPrize`, `prizeQuantity` | per slice, as captured — casino_wof has NO empty slice at all | §11.1 and §11.2 cannot be applied by the build |
| `randomizationType`, `promoCode` | as captured | |

Two consequences the planner must state rather than assume:

1. **Prize slices cannot be added or removed.** `prize_count` is 6 (sport_wof),
   4 (casino_wof), 5 (casino_scratch). A brief with a different prize count
   needs a new capture, and the composer refuses the spec until then.
2. **Anything in the "NOT settable" table that the brief contradicts is a
   hand-fix.** Flag it ⚠ and say so explicitly — "not settable from the spec;
   change it in the backoffice after the draft is created". Stating the intended
   value in prose alone reads as if the build applied it.

**Prize routing has two paths, and only one of them resolves names.** A
randomizer built *alongside recipe journeys* (`compose.py --batch`, which the
backoffice takes when a reply carries more than one MODE 3 spec) creates the
journeys first and substitutes the real `JRN-*` ids into the prizes. A
randomizer built **on its own** — which is what happens when the wheel is asked
for alone, or when its prize journeys are MODE 5 chains — writes the
`journeys` values into `journeyPrizeSettings.journeyId` **verbatim**, and
`verify()` only checks the field is non-empty. So a standalone wheel spec must
carry real `JRN-*` ids; journey NAMES in that path produce a draft routed to
journeys that do not exist, with a clean green build.

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

## 12b. Worked fixture — Giro Finde (PMCL/FTCL) [VERIFIED — CREATE session]

The first captured CREATE session. Brand PMCL (Fortuna Chile). 3 journeys.

| Object | Id | Role |
|---|---|---|
| Main journey (18.07) | `JRN-0-621795` | 149 activities: 5× (promotion+deposit+event_detector+freespin_bonus+casino_bonus_v2+notification_center) + ends. Immediate start. |
| Comms journey | `JRN-0-621796` | dwh_source (segment "Fortunazo players 1+dep") → 2× notification_center + 2× event_detector + 2× wait_interval + dextra_sms. No startAt/stopAt (unlimited). |
| Main journey (19.07) | `JRN-0-621799` | Same 149-activity shape as 18.07, different date. |

**New things this revealed:**
- The exact build order (`REA_BUILD_MECHANICS.md` §13): display-id mint → reserve JRN → 70× contents/copy → POST draft.
- `event_detector` full structure (deposit.approved event, amount filter).
- `dwh_source` with `currentTemplate` (a saved segment reference).
- `dextra_sms` with `rawValues.messageText` containing the promo page link.
- Brand PMCL (second brand), confirming multi-brand on same API.
- A journey with 149 activities / 5 tiers — largest captured so far.
- `promotionDisplayId` is pre-minted by the UI (but the cloner's strip approach also valid).

---

## Build & wire mechanics — moved

How a journey is actually POSTed (build order, endpoints, the dual-storage
rule, the activity envelope, ID classes, the visual layer, the debugging
playbook) lives in `REA_BUILD_MECHANICS.md`. It is deliberately NOT injected
into the planner prompt: the planner produces plans and specs, and the
composer does the POSTing, so that material was ~39% of the prompt the model
never acts on.

