# REA build & wire mechanics (composer-facing)

Split out of REA_KNOWLEDGE_BASE.md. This is the reference for whoever
maintains compose.py / journey_composer.py and for debugging a draft that
will not render. It is NOT part of the planner's system prompt.

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
