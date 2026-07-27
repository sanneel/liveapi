# REA Journey Builder — Capture Backlog & Unknowns Checklist

Companion to `REA_KNOWLEDGE_BASE.md`. This is the honest boundary of what the AI
builder can and cannot do today, and the ordered work to close the gaps.

Legend for status:
- [x] = captured / known (verified from a real object or working code)
- [ ] = NOT captured / unknown — the builder must NOT generate this yet

---

## A. Activity types — capture coverage

Captured = we have at least one real activity object of this type to assemble
from. Source of the captured set: the birthday HAR (JBCL) + `create_journeys.py`
sport templates.

### CAPTURED (builder can assemble these) [x]
- [x] `external_system_source`  (Input Source — "API")
- [x] `dwh_source`              (Input Source — "Custom Segment") *(code/templates)*
- [x] `Reference codes`         (Input Source) *(user confirmed captured)*
- [x] `Promotion` as source     (Input Source) *(user confirmed captured)*
- [x] `promotion`
- [x] `multipurpose_promotion`
- [x] `freespin_bonus`          (Reward — Casino FreeSpin)
- [x] `casino_bonus_v2`         (Reward — Casino Bonus / wagering)
- [x] `freebet`                 (Reward — Sport FreeBet)
- [x] `deposit`                 (Condition)
- [x] `sport_bet_condition`     (Condition — "Bet") *(sport_promos.har)*
- [x] `wait_interval`           (Delay — Wait)
- [x] `wait_date`               (Delay — Date) *(sport_promos.har, wire name confirmed)*
- [x] `ams_decision_split`      (Flow control — Decision split)
- [x] `campaign_connector`      (Connector)
- [x] `notification_center`     (Comms — On-site, contract 1 + 5)
- [x] `notification_center_engagement_split`
- [x] `dextra_email`            (Comms — Email + Content Studio)
- [x] `dextra_sms`              (Comms — SMS)
- [x] `event_detector`          (Delay) *(birthday + Giro Finde HARs)*
- [x] `parallelFlow`            (Multiple flows — Parallel flows) *(birthday HAR)*
- [x] `end_of_path`
- [x] `end_of_journey`

### NOT CAPTURED (builder must refuse / flag these) [ ]

Input Source
- [ ] `CSV`               — uploaded player list (wire name unknown)
- [ ] `Predefined Segment`— (wire name unknown; may share `dwh_source`?)
- [ ] `Events`            — real-time event entry (wire name unknown)

Flow control
- [ ] `Random split`      — wire name unknown
- [ ] `Email engagement split`      — wire name assumed `email_engagement_split`, unconfirmed
- [ ] `Native push engagement split`— wire name unconfirmed

Communication
- [ ] `Native push`       — assumed `native_push`, unconfirmed
- [ ] `Web push`          — wire name unknown
- [ ] `WhatsApp`          — wire name unknown

Connectors
- [ ] `Outgoing API request` — wire name unknown

Multiple flows
- [ ] `Choosable flows`  — seen only inside `multipurpose_promotion` split; standalone uncaptured

Conditions
- [ ] `Bet Insurance`
- [ ] `Bet Collection`
- [ ] `Casino Bet Collection`
- [ ] `Deposit Collection`

Reward type
- [ ] `Sport Bonus`      — wagering sport bonus (wire name unknown)
- [ ] `Money Bonus`      — cash to main balance (wire name unknown)
- [ ] `Coins Bonus`      — wire name unknown

> To capture any of the above: build one in the backoffice, then GET the journey
> (or capture the create POST) and extract the activity object + its
> `rawJourneyData` mirror as a fragment.

---

## B. Subsystem / object coverage

- [x] Journey object (full body) — captured (birthday ×6, sport templates, Giro Finde ×3)
- [x] Journey CREATE sequence — captured (Giro Finde: display-id → reserve → contents/copy → POST)
- [x] Randomizer / Fortune Wheel + ScratchCard — captured (birthday view + randomizers.har creates)
- [x] Randomizer CREATE sequence — DONE (randomizers.har: 2× contents/copy → POST, returns {id})
- [x] **Promo Page** (`promo-page`) — DONE (promop_age.har: create + PUT + s3 uploads)
- [x] Visual bundle fork (`contents/v1/copy`) — captured (Giro Finde + randomizers)
- [x] Visual bundle read shape (`mf/v1/...`) — captured (GETs)
- [x] Email content (`CSE-*`) create/save/publish — known from code
- [ ] Loyalty Program / Engagement Hub bonuses — out of scope, uncaptured

### Multi-brand [NEW — Giro Finde]
- [x] JBCL (JugaBet Chile) — birthday HAR, sport templates, randomizers, sport promos
- [x] PMCL (Fortuna Chile / FTCL) — Giro Finde HAR (create session)
- Same API, same endpoints, different `x-brand` header and `brand` field in bodies.

---

## C. Build-process unknowns

- [x] **Create ORDER / sequence** — SOLVED by Giro Finde HAR (PMCL, 3 journeys).
      Per journey: 5× mint promotionDisplayId → 1× reserve JRN → 70× contents/v1/copy
      (fork visual bundles) → 1× POST journey-drafts. Comms-only journeys skip
      the display-id and contents-copy steps.
- [x] **Visual bundle fork endpoint** — SOLVED: `POST /contents/v1/copy` with
      `{ sourcePath, destinationPath }`. Called per visual target path.
- [x] **promotionDisplayId pre-allocation** — SOLVED: UI calls
      `POST /promo/v0/promotion-display-identifier` → `{ promotionDisplayId: N }`.
      But stripping them (the cloner approach) is equally valid — server re-mints.
- [x] **Randomizer create sequence** — SOLVED (randomizers.har):
      2× contents/copy → POST /promo-drafts/randomizer → {id: N}. No reserve step.
- [x] **Journey POST + immediate PUT pattern** — SOLVED (sport_promos.har):
      UI does POST then immediately PUTs the same draft. PUT uses numeric id.
- [ ] How the wheel prize `activityId` is obtained at build time (is it the
      entry `external_system_source` id? confirm it's always the entry node)
- [ ] Whether Promo Page vs Randomizer is the birthday entry (no promo-page GET
      appeared — banner may point straight at the wheel)

---

## D. Field-level notes (monitor, not blocking)

These were flagged as risks but the cloner works without resolving them.
Watch-for items, not blockers.

- [~] `flowId` — not regenerated by cloner; no errors in practice. If a
      choosable-flow clone fails, check this first.
- [~] `webhookId` on `external_system_source` — passed through, no errors.
- [~] `campaignId` — cloner blanks to ""; proven working.
- [~] Server-minted ids on `freespin_bonus`/`casino_bonus_v2` — none hit.
- [~] NC content re-hydration from saved template — inline payload works.
- [~] `pathesConfiguration`/`boundaryConfiguration` — copied from template, works.
- [~] `activities[]` order — preserved from template, works.

---

## E. GR8-doc field names to confirm against a real capture

These are UI/product terms; wire names NOT yet verified. Do not generate using
these names until confirmed:
- [ ] Sport bonus attributes: `deposit_rate`, `wager_factor`, `min_odd`,
      `min_odd_parlay`, `line_types`, `bet_types`, `prolongation_days`, ...
- [ ] Freebet attributes: `expiration_timeout`, `max_coeff`, `min_coeff`,
      `sport_ticket_condition_values_*`, ...
- [ ] Casino deposit/cashback attributes: `Wagering requirement`,
      `Bonus percent`, `Limit type`, `Bonus Release Limit`, ...
> For each: bind the product term to its real JSON path from a capture before use.

---

## F. Bonus-recipe grammar coverage (from GR8 docs, §21 of onboarding)

Which recipes do we have a working captured example for?

Have a captured example [x]:
- [x] Casino FreeSpin with Wagering (+Deposit)  → birthday casino follow-up
- [x] Casino FreeSpin without conditions        → birthday freespin prize
- [x] FreeBet without conditions                → birthday freebet prize
- [x] FreeBet for Deposit                        → birthday sport follow-up + sport templates

No captured example yet [ ] (grammar known, structure blind):
- [ ] Sport Wagering Bonus (with/without deposit)
- [ ] Bet Insurance (all variants)
- [ ] Bet Cashback (all variants)
- [ ] Deposit Cashback (all variants)
- [ ] Casino Bet Collection (all variants)
- [ ] Combo / Promo Pack (Parallel + Choosable) standalone
- [ ] Mix bonus (Cash Bonus based) variants

---

## G. Priority order to close gaps (do in this order)

1. [x] Capture a **create session** HAR — DONE (Giro Finde, PMCL, 3 journeys).
2. [x] Capture **Randomizer CREATE** — DONE (randomizers.har, 3 randomizers).
3. [x] Capture **sport promo creates** — DONE (sport_promos.har, 5 journeys + PUTs).
4. [ ] Extract the birthday + Giro Finde + sport objects into clean template fragments.
5. [ ] Capture the **Promo Page** object body.
6. [ ] Capture uncaptured rewards: `Sport Bonus`, `Money Bonus`.
7. [ ] For each new capture, append: wire-name row (knowledge base), any new
       brief-invisible rule (§11), any new error mapping (§14).

---

*Rule of thumb: the builder may only assemble activity types and object types
marked [x] here. Anything [ ] must be surfaced to the human as "no captured
example — cannot build safely" rather than generated.*
