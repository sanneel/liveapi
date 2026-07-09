# REA Backoffice — Structured Reference / "DB"

A catalog-style companion to `REA_BACKOFFICE_AND_JOURNEYS.md`. That file is the
narrative working-knowledge; this one is the **lookup table**: every activity,
promo mechanic, channel, segment, endpoint and field I've seen, with how each is
wired and what changes per campaign. Where the two overlap, this one is the
quick reference and the other is the "why".

> Scope note: everything here is reverse-engineered from real captured journeys
> (Game-of-the-Week, 5-day boost, birthday follow-up) and live HAR captures for
> brand **JBCL** (JugaBet Chile). Field names are exact; values are examples.

---

## 0. Platform identity & environment

| Thing | Value |
|---|---|
| Vendor | gr8.tech "REA" backoffice (Optimove-style CRM + Journey Builder) |
| Operator | `PMI` |
| Brand | `JBCL` (JugaBet Chile); brands on the token also include `PMCL` |
| Currency | `CLP` (Chilean peso). Amounts stored in **minor units** (×100): `15000` minor = `$150` major. Fields often carry both: `amount: 15000` + `amount_majorUnits: 150` |
| Timezone | `Chile/Continental` |
| UI host | `https://pmi.rea-backoffice.gr8.tech` |
| Public site | `win.jugabet.cl` / `jugabet.cl` (resolved at send time via the `{{BrandDomain}}` dwh variable) |
| Media CDN | `https://static.contentin.cloud/<folder>/<asset>.png` |
| Error tracking | Sentry (`errs.qwrt.xyz`) — ignore these envelope POSTs in HARs |

### Auth
- Keycloak (`auth-backoffice.gr8.tech/realms/PMI`), OIDC. Bearer JWT, ~5-min expiry.
- Console scripts **never hard-code a token** — they hook `window.fetch` +
  `XMLHttpRequest.setRequestHeader`, capture the first valid `Bearer` the page
  emits, validate `exp`, and reuse it. Required headers on every call:
  `authorization: Bearer …`, `x-brand: JBCL`, `content-type` per endpoint.

---

## 1. API endpoint catalog

Base for CRM APIs: `…/api/ubo/api/v0/crm`. Journey base appends `/journey-builder/v0`.

| Purpose | Method + path (relative to CRM base) | Notes |
|---|---|---|
| Reserve journey id | `POST /journey-builder/v0/journeys/identifier` | returns `JRN-0-######` (form-urlencoded) |
| Create journey draft | `POST /journey-builder/v0/journey-drafts` | body = full journey object |
| Update journey draft | `PUT /journey-builder/v0/journey-drafts/<numericId>` | full body; used for manual edits |
| Media upload | `PUT /media-library/v0/folder/<folderId>/upload/<name>.png?height=H&width=W` | multipart `file`; returns asset w/ `absolute_link` + `relative_link` |
| Media thumb | `PUT /media-library/v0/asset/thumb/<assetId>.png` | multipart; non-fatal if it fails |
| Email content create | `POST /content-studio/v0/eb-backoffice/email/contents` | returns `{"id":"CSE-0-#####"}` |
| Email content save | `POST /content-studio/v0/eb-backoffice/email/contents/<CSE>` | same body shape |
| Email content publish | `PATCH /content-studio/v0/eb-backoffice/email/contents/<CSE>/publish` | body `{}`, 204 |
| Promo page draft | `POST /promo/v2/promo-drafts/promo-page` | the landing page players hit |
| Randomizer / wheel | `POST /promo-drafts/randomizer` | weighted-prize Fortune Wheel |
| Visual bundle (design) | `media-front` / AWS-backed bundle endpoints | `frontId`=theme, `contentId`=copy+images |
| Default media folder | `c5c7c614-5169-4346-b90b-8225836a1c63` | where the NC/popup/email photos land |

---

## 2. Journey object model (the single most important concept)

Every journey is stored **twice** inside one payload, and both must agree:

| Copy | Where | Role | Who reads it |
|---|---|---|---|
| **Compiled / runtime** | `body.activities[]` | the executable graph | the journey engine at runtime |
| **Editor mirror** | `body.rawJourneyData` | the visual builder's working state | the Journey Builder UI |

`rawJourneyData` itself has:
- `elements[]` — nodes + edges of the flow diagram (positions, ports, event labels)
- `activitiesConfiguration[<activityId>]` — `{ data, error, displayData, displayName, … }` where `data` mirrors that activity's `initializationData` **minus** `displayData` (which sits one level up at the config level)
- `pathesConfiguration`, `boundaryConfiguration` — split/boundary path wiring
- `infoValues` — a second copy of the top-level scheduling/name fields

**Lesson burned in twice:** editing only `activities[]` leaves the UI showing
old copy (and can be what actually ships, depending on activity type). Any edit
must be mirrored into `rawJourneyData.activitiesConfiguration[id].data` (and
`displayData`, `infoValues`, notification metadata) or the draft looks unchanged.

### ID classes (what cloning must touch)
| Class | Pattern | Cloning action |
|---|---|---|
| Journey id | `JRN-0-######` | reserve fresh; replace a placeholder token |
| Activity ids | UUID, keys of `activitiesConfiguration` + `activityId` + every `nextActivityId`/`journeyActivityId` ref | regenerate **consistently** (global string-replace each old→new UUID) |
| Content/Front ids | UUID (`ContentId`/`FrontId`) | regenerate + re-fork the visual bundle |
| Promo display ids | numeric (`promotionDisplayId`) | **strip** — backend mints fresh; stale ones 409 |
| Lineage | `duplicatedFromId` / `duplicatedFromVersion` | strip |
| Email content id | `CSE-0-#####` | created at paste-time; swapped into `dextra_email.template.id` |

The browser `regen()` collects every UUID appearing as `"activityId"` or `"id"`
and string-replaces all occurrences, so cross-references stay intact. It does NOT
touch `nodeId`/`filterConditionId` inside segment filter trees — those stay
internally consistent on their own.

---

## 3. Entry sources (how players enter a journey)

The first activity is the **source**. Two kinds seen:

| activityName | UI label | Purpose | Key init fields |
|---|---|---|---|
| `dwh_source` | "Custom Segment" | DWH/segment-targeted audience | `dataSourceName:"default"`, `filterDetails` (the filter tree), `currentTemplate` (the saved segment template) |
| `external_system_source` | "API" | externally/API-triggered entry (no audience filter) | `description`, `targetSystem` (e.g. `"PromoPage"`), `isWebhookUrlHidden`, `placements:[]` |

Both fire the activation event `PlayerAdded` (`eventType: "Activation"`) into the
first real activity. The segment source's `PlayerAdded` carries
`payloadKeys: ["CurrencyCode"]` that downstream activities depend on; the API
source emits `CurrencyCode` too (downstream deps point at the source id either way).

**Swapping segment→API** (or vice-versa) = replace the source activity in
`activities[]` + its `rawJourneyData` node + the activation edge + the
`activitiesConfiguration` entry, keeping the same activityId so all
`journeyActivityId` references and the edge target stay valid.

---

## 4. Activity catalog

Distinguish activities by `activityName` (+ `contract` for notification_center).

### 4.1 Sources & flow control
| activityName | Role |
|---|---|
| `dwh_source` | segment entry source (§3) |
| `external_system_source` | API entry source (§3) |
| `wait_interval` | delay; `waitPeriod` ISO-8601 duration (`P0Y0M1DT0H0M0S` = 1 day), `exitCriteria` |
| `event_detector` | waits for a server-side event (e.g. a deposit) before continuing |
| `deposit` | deposit **condition** gate; `depositConditions.minDepositAmounts`, `expirationTimeout`; emits Satisfied/Unsatisfied/Canceled, can split |
| `*_engagement_split` (`notification_center_engagement_split`, `email_engagement_split`) | branch on Clicked/Read/Sent of a prior comms activity; `DextraNotificationCenterActivityId` points back at the comms activity |
| `ams_decision_split` | rules-based audience split (`rules`, `remainder`, `pathesConfig`) |
| `end_of_path` | terminates one parallel-flow branch |
| `end_of_journey` | terminates the whole journey |
| `parallelFlow` (rawJourneyData element) | container grouping multiple `flowEntry` branches that run in parallel |

### 4.2 Reward / promo mechanics
| activityName | Mechanic | Key fields |
|---|---|---|
| `multipurpose_promotion` | "Flat Drip" offer shown in lobby/cashier | `promotionId`, `promotionLinkId`, `timeToAccept`, `placements[]` (PromoLobby/Cashier), `minDepositAmounts` |
| `promotion` | generic offer (Offered→Accepted→Expired) | `promotionId`, `promotionLinkId`, `promotionStatus` (`Offered`/`Accepted`), `placements[]` w/ embedded reward `freespinActivity` + `wageringActivity` |
| `freespin_bonus` | casino free spins | `freespinActivity`: `spins`, `provider` (`pragmatic`), `lobbyGameId` (`pragmatic-vs20olympgate`), `walletGameId`/`externalGameId`, `currenciesConfig.<CCY>.betAmount`, `gameTranslationKey`, `spinsExpirationDuration` (ms), `startAt`/`stopAt`, `withWagering` |
| `casino_bonus_v2` | wagering (deposit-match) bonus | `bonusPercent`, `wageringRequirement` (×), `releaseLimitMultiplier`, `bonusExpirationTime` (ms), `currenciesConfig.<CCY>.maxBonusAmount`, `dependencyMechanic:"FreeSpin"` |

Reward chaining seen in GOW/boost: `promotion` (offer) → `freespin_bonus`
(award spins) → `casino_bonus_v2` (wager the winnings). The `promotion.placements[]`
carries a **copy** of the reward config + `ContentId`/`FrontId` for the lobby card.

### 4.3 Communication channels
| activityName | Channel | Identifier |
|---|---|---|
| `notification_center` (`contract:1`) | On-site Notification (bell) | template `1935` / `1315` etc. |
| `notification_center` (`contract:5`) | On-site Pop-up (Cat-fish) | template `20678` |
| `native_push` | mobile push (Android/iOS) | `imageUrl`, `defaultNotification.{pushTitle,pushMessage}`, `applicationsWithPlatforms` |
| `dextra_sms` | SMS | `version:"v2"`, `rawValues` + `smsSettings` + `displayData` |
| `dextra_email` | Email | references a **content-studio** content by `emailSettings.template.id` (`CSE-0-#####`) |

> Note the Push **Pop-up** ("Notification Pop-up (Push)") is a *second* pop-up
> variant distinct from the Cat-fish one; in the GOW spec only the Cat-fish
> pop-up is wired up.

---

## 5. notification_center deep-dive (Notification + Pop-up)

Content lives in **two** sub-objects that must both be set, plus the
`rawJourneyData` mirror:
- `initializationData.objectForSend.variables[]` — list of `{name,value}`. The
  engine resolves `%token%` references, so `title` = `"%title-en%"` and the real
  text is in `title-en`. `defaultVariables`/`localizedVariables` are empty in
  practice.
- `initializationData.singleChannel.localizedLanguagesTab.{en,es,common}` — the
  editor's per-language tabs (mirror of the same keys).

| Contract 1 (Notification) var names | Contract 5 (Pop-up) var names |
|---|---|
| `title-en/es`, `des-en/es`, `caption-en/es`, `link-en/es`, `icon` (token `icon-src`), `deeplink`, `buttons_1_*` | `title_en/es`, `description_en/es`, `caption_en/es`, `link`, `deeplink`, `background_image_src` |

- **Link** = relative promo path `/promo/offers/promoPage/<id>?%$utm_tags%`.
- **Deeplink** = **same relative path** as the link (not the absolute
  `win.jugabet.cl` form). Set both NC and Pop-up `deeplink` to this.
- Photos (`icon` / `background_image_src`) are uploaded at paste-time to the
  media folder and the asset's `absolute_link` is swapped into a placeholder.

---

## 6. dextra_sms deep-dive

SMS text is stored in **three** places, all must agree, and `BrandDomain` must
be declared so `{{BrandDomain}}` resolves:

| Location | Form |
|---|---|
| `rawValues.messageText` + `rawValues.localizedMessageTexts.{es,en}` | editor form, `\n` before the link |
| `smsSettings.messageText` + `smsSettings.localizedMessageTexts[]` (list es,en) | flattened send form |
| `displayData[0]` | UI preview string |

- **Prefix:** every SMS starts `JugaBet | `.
- **Link (current):** `https://{{BrandDomain}}//services/promo/offers/promoPage/<id>`
  — `{{BrandDomain}}` host, `/services/` path, **no** `?%$utm_tags%`. (The leading
  `//services` double-slash is how it was saved; servers normalize it.)
- **BrandDomain "tick":** the variable object
  `{name:"BrandDomain", dataSource:"dwh_source", isRequired:true, …}` must appear
  in each localized message's `variables[]`, in `smsSettings.variables`, and
  `initializationData.listOfUsedVariables` must contain `"BrandDomain"`.

---

## 7. dextra_email deep-dive (the content-studio flow)

Email is **not** inline like SMS/NC. The journey activity only references a
content id; the content itself is a separate content-studio entity.

**Activity** (`dextra_email`): `emailSettings.template.id = "CSE-0-#####"`,
`emailSource:"Template"`, `playerAgreementName:"CasinoPromo"`,
`dataDependencies:[{key:"BrandDomain"}]`, `displayData:["<CSE> <name>"]`.

**Content** (`POST …/email/contents`): top-level
`{brand, name, type:"template", parameters[], translations.es.composition, unsubscribeSettings}`.
`composition = {subject, preHeader, body:{type:"html", source:<HTML>}}`. Spanish-only.

**Per-run substitutions** (everything else stays):
| Field | Source |
|---|---|
| `name` | `JBCL CS - GOW <DD.MM>` |
| `subject` | spec Email "Tittle" (ES) |
| `preHeader` | spec Email "Pre-header" (ES) |
| body heading `<td>` | `"<game> | <provider>"` |
| hero `<img>` (the editable one, wrapped in the promo `<a>`) | uploaded photo → `https://{{cdn_hostname}}<relative_link>` |
| promo CTA `href` (×2) | `https://jugabet.cl/services/promo/offers/promoPage/<id>` (no utm) |

**Paste-time sequence:** upload hero → `POST contents` (create) → `POST contents/<CSE>`
(save) → `PATCH …/publish` → swap the returned `CSE` into the journey's
`dextra_email.template.id` (both copies). The 4 non-hero images (logo, social,
footer) are static brand assets; the spec Email "Button" text is **not** used
(the CTA is the hero image itself).

---

## 8. Segment / audience model (`dwh_source.filterDetails`)

A node graph, not a flat list:
- `filtersTree[]` — nodes. `nodeType:"Filter"` (a condition) or `"Operator"`
  (`And` / `Or` / `Exclude`). Each filter node: `name`/`column.tableName`,
  `operator` (`lte`,`in`,`notIn`,`equal`,`notEqual`,`between`…),
  `settings.values`/`settings.amount`, `databaseName`, `parentNodeId`,
  `filterConditionId`.
- `filterConditions[]` — flattened compiled form of the same conditions (with `id`).
- `currentTemplate` — the saved segment template this was loaded from
  (`id`, `name`, its own `filterDetails`).

**Known data sources / columns seen:** `casino_stats.cnt`,
`player_summary_total.last_deposit` / `.fairplay_casino_segment` / `.player_id`,
`agg_player_summary` (dv_marts) `.last_deposit`, `player_restriction.restriction_name`,
`player_product_segment.highest_prob_pref_category`, `player_product_type_segment.casino_rank`/`.overall_rank`,
`risk_casino_segment` / `risk_sport_segment`.

**Known segment templates (catalog):**
| Template name | Id | Used for |
|---|---|---|
| `301. JBCL \|CS\| Active / Dep <14d` | `c59a22fc-…` | **CS** comms journey (`segment_cs_301.json`) |
| `JBCL /CS&SP/ Updated Sport Segment 06.26` | `44b54348-…` | **CS&SP** GOW comms (baked into `gow_comms.json`) |

> Caveat: real captured segments often carry a `player_id equal [list]` branch
> (a QA/seed list — 1 id in CS&SP, 20 in 301), OR'd into the audience. It's
> faithful to the capture; strip that one node if you don't want seeded players.

---

## 9. Promo Page & visual/design layer

| Concept | What it is |
|---|---|
| `frontId` → `settings.json` | the **theme** (colors, layout) of a card/page |
| `contentId` → `content-<lang>.json` | the **copy + image keys** (per language) |
| Visual bundle | a folder of `manifest.json`, `content/content-es.json`, `content/content-en.json`, media. Cloning **forks** it under fresh ids and fixes self-referential absolute paths inside `content-<lang>.json` |
| Promo Page | `POST /promo/v2/promo-drafts/promo-page` — the `/promo/offers/promoPage/<id>` landing page every channel links to |
| Recurring image slots | `prizeImageKey`, `headerImageKey`, `widgetImgKey`, `bonusHeaderImage`, item `itemImageKey` — the same physical photo is uploaded into several slot paths (`mf/v1/<contentId>/spa/media/…`, `…/widget/media/…`) |

"Change the design" = fork the bundle, replace the media under those keys,
repoint `ContentId`/`FrontId`. Connecting Figma would mean exporting frames to
those slot keys — see §17 of the narrative doc.

---

## 10. Worked system: Game-of-the-Week (GOW)

Three sub-systems created from one pasted spec:

1. **Campaign journey** (`gow.json`): API entry (`external_system_source`) →
   `multipurpose_promotion` flat-drip → `deposit` gate → split into 3 reward
   flows, each `promotion` → `freespin_bonus` (50 FS on the spec's game) →
   `casino_bonus_v2`. 4 deposit tiers. **Starts immediately after publish**
   (`startAt:null`, `isImmediatelyAfterPublish:true`); free-spin validity = date
   + 7 days. Also creates the **Promo Page**.
2. **Comms journey** (`gow_comms.json`): segment entry → Notification (1935) →
   Pop-up (20678) → SMS → Email. Window = same day 12:00→19:00 Chile. Now
   produces **two** journeys per run: **CS&SP** (Sport Segment) and **CS**
   (segment 301, name `CS&SP`→`CS`) sharing photos + email content.
3. **Email content** (`gow_email.json`): content-studio create→save→publish (§7).

Spec → fields: Offer cell → `game | provider` + `bet $` tiers; per-channel
EN/ES copy table → NC/Pop-up/SMS/Email. `TRUE/FALSE` flags gate each channel.

---

## 11. Cloning rules / gotchas (checklist)

- Strip `duplicatedFromId`/`duplicatedFromVersion`, stale `promotionDisplayId`,
  stale campaign-connector ids.
- Regenerate all activity UUIDs consistently; never reuse a `JRN`/`CSE` id.
- Mirror every content edit into `rawJourneyData` + `infoValues` + notification
  metadata `journeyName`.
- Output filenames must be **request-unique** (a date-only name caused a
  read-back race in the web layer that served stale scripts — fixed with a uuid
  suffix).
- "Content not changing" almost always = the `rawJourneyData` mirror wasn't
  updated, OR a stale console script from a different run.
- 409 "already exists" → an id wasn't regenerated/stripped (display id, content
  id, or journey id).

---

## 12. My own observations & open questions

**Synthesis**
- The platform is really **three loosely-coupled systems** stitched by ids:
  Journey Builder (orchestration), Promo/Reward engine (the actual bonus +
  landing page), and Content/Design (visual bundles + content-studio email).
  Almost every bug in this project came from an id not crossing a boundary
  cleanly, or a second storage copy not being updated.
- The **dual storage** (`activities` vs `rawJourneyData`) is the defining
  footgun. A DB of journeys should treat them as one logical record with a
  validation invariant "compiled == editor mirror".
- Channels are **inconsistent by design**: NC/Pop-up store copy inline (in two
  sub-objects), SMS in three, Email by reference to an external content. Any
  tool must special-case each.
- Reward config is **duplicated** between the `freespin_bonus`/`casino_bonus_v2`
  activities and the `promotion.placements[].data` that renders the lobby card —
  edits must hit both.

**If building a DB of this backoffice, suggested tables**
- `journeys(jrn_id, name, brand, immediate, start_at, stop_at, recurrence, source_type, segment_template_id, created_from)`
- `activities(activity_uuid, jrn_id, type, contract, display_name, next_refs[], depends_on[])`
- `promotions(promotion_id, link_id, type, content_id, front_id, reward_mechanic, min_deposit, currencies)`
- `rewards(activity_uuid, mechanic, spins|bonus_percent, wagering_req, game_lobby_id, provider, expiry_ms)`
- `channels(activity_uuid, channel, template_no, subject|title, link, deeplink, languages, uses_brand_domain)`
- `email_contents(cse_id, name, subject, preheader, promo_id, hero_asset)`
- `segments(template_id, name, db_tables[], conditions_json, has_player_id_seed)`
- `promo_pages(promo_id, internal_name, content_id, front_id, media_slots[])`
- `assets(asset_id, folder_id, absolute_link, relative_link, used_in[])`

**Open questions / unknowns**
- Exact semantics of `Exclude` vs nested `And/Or` in the filter tree (the
  birthday segment OR'd a player_id list onto an Exclude group — needs a UI
  cross-check to be sure of evaluation order).
- Whether the API (`external_system_source`) entry needs a webhook/feed
  registered elsewhere, or if `targetSystem:"PromoPage"` is self-sufficient.
- Whether `POST /journey-drafts` ever re-hydrates `notification_center` content
  from the saved `templates:<no>` at create time (we proved the inline payload
  IS honored once the `rawJourneyData` mirror is correct, but a server-side
  re-hydrate for some activity types hasn't been fully ruled out).
- Full prize→journey routing for the randomizer/Fortune Wheel (`/promo-drafts/randomizer`).
- The complete set of `targetSystem` values and `validityType` semantics.

---

*Generated as a working reference. Treat values as examples and verify field
names against a fresh capture before relying on them for a new campaign type.*
