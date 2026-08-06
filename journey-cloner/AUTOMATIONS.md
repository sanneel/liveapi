# Automations — what we have scripted, and how each one works

Every promo automation in this repo, what it builds, and the mechanics behind it.
The **registry** that the Optimization page renders lives in code —
`app/services/promotions_catalog.py::GENERATORS` — and `unlisted_generators()`
warns in the admin about any generator script the registry does not name. This
document is the prose behind that list: read it when you need to know *how* one
works, or when you are adding the next one.

Related docs:
- `COMPOSER_RULES.md` — the hard rules learned building the composer (why a
  journey renders or ships a blank canvas).
- `RECIPE_BUILDING.md` — turning a captured journey into a composable recipe.
- `REA_BACKOFFICE_AND_JOURNEYS.md` — how the backoffice models journeys.
- `../JOURNEY_COMPOSER_STATUS.md` — where the AI planner is and what is left.

---

## The shape every automation shares

None of these call the backoffice API from the server. They all end at a
**console script you paste into a logged-in backoffice tab (F12)**, and there is
one reason for that: the backoffice authenticates with a short-lived bearer token
that only the browser has. So every generator follows the same five steps.

```
 1. CAPTURE     Do it once by hand in the backoffice with DevTools open.
                "Copy as fetch" the POST that creates the draft.
 2. TEMPLATE    Store that body under templates/<brand>/<name>.json. It is a
                REAL object that renders — the single most important property.
 3. SUBSTITUTE  Python swaps the per-run pieces (dates, game, bets, copy) and
                regenerates every id so two drafts cannot collide.
 4. VERIFY      Refuse to emit when the result is wrong: an unknown game, a knob
                the recipe lacks, content still shared with the template.
 5. EMIT        A console script that captures the token from the page's own
                traffic, reserves a JRN id, and POSTs the draft(s).
```

Two consequences worth internalising:

- **The template is the source of truth for shape.** Everything not explicitly
  substituted stays as captured. That is why "the caps were wrong" and "the card
  advertised the wrong game" were both real bugs: the value was simply never
  written, so the reference's own value shipped.
- **A refusal is the feature.** Every generator would rather emit nothing than
  emit a draft that looks right and grants the wrong thing. If one refuses, the
  message names the field and what to do.

**Substitute copy structurally, not by string replacement.** A whole-body
`.replace()` is safe only for a value unambiguous in the serialized body (an id,
a slug, a date). For channel copy it is dangerous: the captured EN and ES slots
hold identical strings, each value appears 8–16 times, and different channels
reuse the same literal — so a replace writes one language everywhere and gives
one channel another's copy, while every leftover check still passes. Address each
field by name, in both storages. The full trap list — copy, the `displayData`
label, the email body, a live-data image, testing for the wrong value not the
captured one — is in **`HAR_TO_AUTOMATION.md` Step 4**, and every one of them is
worked in `sport_comms_campaign.py`. Read that before adding a comms generator.

Where output lands: `console_scripts/<name>_console.js`, plus `out/` for
intermediate JSON when a generator writes one.

---

## Casino

### Game of the Week — `gow_combined.py` → Optimization ▸ GOW
The full weekly promo in one paste: the casino free-spin journey **and** its promo
page (`gow_campaign.py`) **and** the comms journey (`comms_campaign.py`:
notification + pop-up + SMS). Everything — game, provider, per-tier bets, all
channel copy — comes from one pasted spec blob (`spec_parser.py`); only the date
is a separate field.

The interesting mechanic: the comms links must point at the promo page that the
same run creates, and that id does not exist until mid-script. It is captured
client-side between steps rather than typed in by hand. Images come from Figma
(`figma_export.py`) or an upload.

The tab's **Create Campaign** / **Create Communication** checkboxes pick which
halves to build: both (the default, `gow_combined.py`), campaign only
(`gow_campaign.py`), or comms only (`comms_campaign.py` — notification + pop-up +
SMS against an existing promo page id). So there is no separate "GOW comms"
generator; it is this tab with the campaign box unticked.

### Bet & Get — `bet_and_get_pmcl_campaign.py` → Optimization ▸ PMCL Bet & Get
PMCL (Fortunazo) weekend promo as three linked drafts from one script: a promo
page (its micro-frontend content copied from the captured template and
re-uploaded to S3), a journey (`external source → promotion → deposit → freebet →
email`), and an email content created and saved, which the journey's email
activity is then pointed at. Templates in `templates/pmcl_betandget/`, extracted
from a HAR of one manual run.

### Discount NC — `nc_discount_campaign.py` → Optimization ▸ Discount NC
One notification journey per game per day (`segment → notification → end`),
twice weekly on the baked calendar. Clones `templates/casino/nc_discount.json`
once per game, swapping values **by string replacement** so the editor mirror
(`rawJourneyData`) and the compiled `activities` stay byte-identical — they are
two copies of the same journey and the builder shows a blank canvas if they
disagree.

`nc_discount_pmcl_campaign.py` is the same shape for fortunazo.cl; both forms sit
on that one tab.

### Instant free spins / deposit free spins — `compose.py` → **AI** page
Not a clone: the **composer**. Picks a recipe (`casino_instant_freespin`,
`casino_deposit_freespins`, …), applies typed knobs to a captured reference, and
verifies before emitting. This is the path the AI planner drives, and the one to
prefer for new casino reward journeys — knobs are declared, validated and
unit-aware, where a clone is a string swap.

### Casino GOW clone — `casino_journey.py` — **legacy, shell only**
The pre-composer way to clone the GOW journey with a different game, per-tier
bets and dates. Still works and is still imported for helpers
(`DEFAULT_BASE_URL`, `utc_dotnet`), but the composer recipes do the same job with
validation. Kept for reference; no UI on purpose.

---

## Sport

### Promo Codes — `create_journeys.py` → Optimization ▸ Promo Codes
Four Journey Builder drafts per fixture (FollowUp, BFR, 2H, AFT) from a match,
date, Chile kick-off time and promocode. Per-team templates under
`templates/udch/` and `templates/colocolo/`; a team with no file of its own
inherits the base team's.

### Prediction — `prediction_campaign.py` → Optimization ▸ Prediction
Updates a Multi Number Prediction promo from a pasted Google Sheets table:
uploads SPA + widget content, both manifests, SPA + widget settings, then PUTs
the promo draft — nine requests in the exact sequence captured in
`templates/prediction/multi_number_prediction.json`.

---

## Wheels & cards

### Randomizers — `randomizer_campaign.py` → Optimization ▸ Randomizers
Sport Wheel of Fortune, Casino Wheel of Fortune, Raspa y Gana. A randomizer is a
weighted set of prize slices, each routing a winner to a journey
(`journeyId` + `activityId`).

**The slices come from the captured template and cannot be added or removed** —
today 7 (sport_wof), 4 (casino_wof), 5 (casino_scratch). A campaign wanting more
prizes cannot be built until a wheel with that many slices is captured. Weights
must sum to 100, and `journeys` needs exactly one entry per slice.

#### Sport WOF runs the full captured flow (the other two do not, yet)

Rebuilt from `45a1240c-wheeloffort_new.har`, which captured what the first HAR
had missed. Every wheel now **owns its own visual content**:

```
1. POST /crm/contents/v1/copy         ×2   clone the master tree into a FRESH
                                           contentId + frontId, minted per draft
2. POST /promo/v2/promo-drafts/randomizer  create the draft
3. POST /promo/v2/s3/upload           ×8   spa+widget content EN/ES, both
                                           manifests, both settings — new tree
4. PUT  /promo/v2/promo-drafts/randomizer/<id>?draftId=<id>   save
```

Why this matters: before the rebuild every Sport WOF ever generated shared one
hardcoded `contentId`/`frontId`, so **editing this week's artwork rewrote every
past and published wheel**. The `%%CONTENT_ID%%` token is filled at paste time
from `crypto.randomUUID()` — including the ~48 media paths *inside* the payload,
which otherwise point the new wheel at the captured wheel's images.

Two more things the rebuild corrected:

- **The fill endpoint was wrong.** The old script did
  `POST /promo/v2/randomizer?draftId=<id>`; the capture does a `PUT` on
  `/promo/v2/promo-drafts/randomizer/<id>`, with `id` as a string,
  `currencyMode: null` and `hasCsv: false`.
- **Four of the seven slices showed the operator's INTERNAL journey name to
  players** (`JBCL | SP | RB - Wheel of fortune | Free | Bonuses`) because the
  wheel editor pre-fills the copy field with it and nobody replaced it.

  Three of those four are the *same prize* re-pointed at a new journey, and
  their real copy was still in the capture under the OLD activityId — so it is
  carried across (`INHERITED_COPY`), never retyped. The genuinely new
  `10%- Dep | Freebet` slice now ships **baked** player copy too
  (EN `10% extra free bet` / ES `Apuesta gratis 10% extra`, in
  `spa/content/content-{en,es}.json`), so a normal run needs **no prize copy at
  all — only a date**. `--prize-text` (and the Advanced → "Prize copy override"
  box in the UI) still lets you rewrite any slice: one `<n><TAB>EN<TAB>ES` line,
  or seven unnumbered lines in wheel order. A build where any slice still matches
  the internal shape is **refused**, and the error lists the wheel's slices in
  order so the right number is obvious. Copy for slices the wheel no longer has
  (three removed activity ids plus four numeric orphans) is dropped.

  Prize copy is a **spa** concern: it lives in `spa/content/content-{en,es}.json`
  and the key is created where the capture lacks it — the captured ES file
  carried copy for only three of the seven slices, so writing only over existing
  keys left four slices blank for every Spanish-speaking player. The widget
  content file is the teaser beside the wheel and holds no `prize_*` key at all.

`urlShortName` stays date-derived (`sport-DD-MM-YYYY`). It is unique
server-side, so a batch that repeated one would 409 on the second wheel *after*
the first was already created; the build refuses a repeat locally instead.

The wheel background lives outside the per-wheel tree
(`mf/v1/background/<uuid>.png`) and is kept as captured — the HAR's
`POST /promo/v2/s3/upload-content` is a multipart image upload whose bytes a HAR
does not carry.

Contract: `scripts/test_sport_wof.py`. Casino WOF and Raspa y Gana still use the
older create-then-fill path and **still share one visual pair each** — they need
their own capture before they can be given the same treatment.

Because prize routing needs journey ids that do not exist until the journeys are
created, `compose.py --batch` can build the **whole promotion in one paste**:
give it `{"journeys": [...], "randomizer": {...}}` and the script creates the
journeys, then creates and fills the wheel with the ids it just received. Each
prize names its journey by `journey_name`; the script resolves the name at run
time. It refuses rather than guess when the routing is unusable — silently
keeping the template's own routing would point a live wheel at another
campaign's journeys.

---

## Comms

### Tournament comms — two brands, one engine
`tournament_pmcl_campaign.py` → Optimization ▸ **PMCL Tournament**
`tournament_jbcl_campaign.py` → Optimization ▸ **JBCL Tournament**

A tournament announced on Notification Center + Cat-fish pop-up + SMS + email,
one journey, gated by two `wait_date` activities on the tournament window.

The two brands are **separate entries against separate backoffices** — PMCL
(Fortunazo) at `pmi.rea-backoffice…`, JBCL (JugaBet) at the shared host — with
separate captures, node names, email templates, SMS prefixes and media-library
folders. For a while a JBCL capture had replaced the PMCL generator, which pointed
Fortunazo operators at the wrong brand; do not merge them again. Every *rule*
lives once in `tournament_comms_base.py`, and each brand file is only what its
capture happens to contain, so the two cannot drift. The structural-copy engine
underneath is `comms_engine`, shared with `sport_comms`.

**The four rules the engine enforces**

1. **Any link, no Smartico id.** The operator pastes whatever URL the promo lives
   at. Only its *path* ships: the notification and pop-up get
   `/xxx/yy/gg?%$utm_tags%`, the SMS gets `https://{{BrandDomain}}/xxx/yy/gg`,
   and the PMCL email's CTA opens the same promo. The captured
   `#_smartico_dp=dp:gf_tournaments&id=<n>` deeplink is **removed**, not patched —
   it only ever addressed one tournament on one product, and a run that kept it
   silently pointed every channel at the captured tournament. There is no
   tournament-id field any more, and `verify()` refuses a body where the pattern
   survives anywhere.
2. **The sheet owns the tournament window.** Its `Start date` / `End date` rows
   set both **Wait/Date** gates, the **notification revoke period**
   (`objectForSend.expire_after` = the tournament's length in days — otherwise a
   tournament that ended last week is still sitting in the player's centre) and
   the journey name. There are no operator start/end fields to disagree with
   them; a missing or reversed window is refused, not guessed.
3. **The journey starts on its date at 12:00 Chile** and stops at 19:00 the same
   day. `isImmediatelyAfterPublish` is forced **false** in both storages —
   left true, publishing a draft early fired it early.
4. **The media-library folder is a property of the brand**, baked into the
   generator (PMCL `67e37e66-…`, JBCL `c5c7c614-…`), not an operator field. It
   was possible to paste one brand's folder into the other's form and upload a
   tournament's artwork into the wrong library.

**Inputs**: the send `--date`, `--link` (any URL), the pasted `--spec` sheet, and
— JBCL only — `--email-link`, the game the email CTA opens
(`/launch/slots/iframe/<game>`). Everything else is optional.

**The email** is built and published the way GOW/sport_comms do it: the console
script uploads the hero photo, POSTs the content (create → save) to
content-studio, and swaps the returned `CSE-*` id into the journey's email node —
email created FIRST, journey wired to it. Body, subject and pre-header come from
the sheet's Email rows; templates in `templates/tournament/`
(`tournament_email_{create,save}.json` for JBCL, `pmcl_email_{create,save}.json`
for PMCL). Passing an existing `--email-content-id` instead skips the build;
either way a run keeping the captured content is refused.

**Why the shared engine exists** — the version this replaced created "shit comms,
nodes not connected":

- **It only POSTed the draft, never the follow-up PUT (save).** The capture does
  create *then* save, and the save is what the editor writes back to finalise the
  canvas; without it nodes render unconnected. The console script now does both,
  regenerating ids from the union of the two bodies so they describe one journey.
  (The PMCL capture is a single body: it is POSTed and then PUT back unchanged.)
- **A capture can carry `positionAbsolute: null`** — the blank-canvas crash of
  COMPOSER_RULES rule 1. `comms_engine.backfill_position_absolute` repairs it.
- **Copy was string-replaced**, shipping one language into every slot. Now it is
  structural (`set_channel_copy`), and `verify()` reads it back per node and per
  language.

`verify()` refuses a build that leaves a captured link, Smartico id, email id,
journey name or copy behind, whose revoke period or gates disagree with the
sheet's window, that would start on publish, or that has a dangling
`nextActivityId`, a canvas edge to a missing node or an activity node without
`positionAbsolute`. Contract: `scripts/test_tournament_comms.py` — the **same
suite runs against both brands**, so a change that only fixes one fails.

### Scratch Card Comms — `sport_comms_campaign.py` → Optimization ▸ Scratch Card Comms
The fixture scratch-card promo announced on four channels from **one** journey:
SMS, Notification Center, Cat-fish pop-up and email, with waits, two decision
splits and a `deposit.approved` detector between them. Built from a HAR of the
15.07 ENG vs ARG run; templates in `templates/sportcomms/` (four bodies, because
the capture creates the draft, saves it, creates the email content and saves
that).

Two inputs, both of which the operator already has:

```bash
python sport_comms_campaign.py --campaign <liveapi-slug> --spec sheet.tsv
python sport_comms_campaign.py --campaign <liveapi-slug> --spec -   # sheet on stdin
```

- **the liveapi campaign** (`app/models/campaign.py`) gives the journey name
  (its title), the schedule (`expires_at` → `stopAt`, so the comms cannot
  outlive the page they link to) and — the point of the whole feature — the
  **email banner**: the campaign's copy link (`/r/<slug>.png`) is written into
  the banner slot the captured email already carries, keeping its
  `?limit=1&v={{JourneyActivityId}}&u={{playerID}}` query, so the card renders
  live odds on every open and each open is tracked per player. The capture
  held that slot two ways — the literal placeholder `variable` in one body and
  the PREVIOUS campaign's real URL (`engvsarg`) in the other — and un-replaced,
  one is a broken image in the inbox and the other the wrong campaign's card.
  `verify()` refuses both, and refuses when `PUBLIC_BASE_URL` is unset (the
  banner needs an absolute URL a mail client can fetch). The email *hero* is
  ordinary promo artwork, picked at paste time like the icon and background;
- **the content sheet** gives every channel's EN/ES copy through
  `spec_parser.py`, and its `Link` row gives the randomizer promo slug that all
  four channels point at.

**The link** has its own field (`--promo-link`) because it is the one value that
has to be right in all four channels at once — SMS, notification, pop-up and
email, in both languages. Give it as a full promo URL or a bare slug; it
overrides the sheet's `Link` row, and a blank field falls back to that row. A
URL that is not a randomizer promo page is **refused rather than guessed at**:
quietly taking the last path segment of some other URL would send every player
to the wrong page. Whichever source wins, the slug is written everywhere and
`verify()` refuses if any captured slug survives or if EN and ES disagree.

**The tab** (`/admin/promotions?tab=sport_comms`) is the way to drive it: the
campaign is a **dropdown read live from the liveapi database**, not a slug typed
from memory, and the sheet is a textarea piped to the generator over stdin
(`--spec -`) so a pasted sheet never touches disk. Each option shows the
campaign's sport and expiry; **every enabled campaign is listed**, including
ones with no expiry date.

The stop date is its own optional field (`--stop-at`), prefilled from the
selected campaign's expiry and overridable per run. That is deliberate: an
earlier version listed only campaigns that already carried an expiry, and on a
database where nobody sets expiry dates the dropdown came up empty with no way
forward. An expiry is the *default* stop date, not an eligibility rule — the
generator still refuses when it has neither, which is a refusal the operator can
now act on. Route:
`POST /admin/promotions/sport-comms` → `generate_sport_comms_console_script`
(`app/services/journey_cloner_runner.py`). Dry run writes the four request
bodies to `out/` instead of a script. A refusal renders the failing check in the
run output and **no copy button**, so there is nothing to paste when the build
was rejected.

The notification icon and the pop-up background are still picked by hand at
paste time — they are per-campaign artwork, and leaving them as captured would
ship the previous promotion's images.

Two things the capture did that this generator deliberately does not:

| the recording | why it is not reproduced |
| --- | --- |
| created email content `CSE-0-16076` but left the journey pointing at `CSE-0-15619` | that is the copied campaign's email. The order is reversed here — content first, its returned id substituted into the journey — and `verify()` refuses while the captured id survives |
| pointed `link-en` at `/randomizer/sf-sc-2026` and `link-es` at `/randomizer/arg-eng-sc` | a leftover from the earlier semifinal campaign. Both languages get the sheet's one slug, and the sheet's own SMS copy has any stale randomizer URL rewritten |
| left the email **body** as the previous campaign's copy | the body still read "la semifinal Inglaterra vs Argentina" whatever fixture the run was for. The sheet's `Email Description` row replaces it, and a sheet without that row is refused |

The sheet's `Email Button` row is **not** used: this email's CTA is the hero
image, not a text button, so there is no slot for it. The generator says so in
its report rather than dropping the value silently.

**Channel copy is written structurally, not by string replacement**, and this is
the part to understand before changing anything. Each captured value appears
8–16 times — in the compiled activity, in its `objectForSend.variables` list,
and again in the `rawJourneyData` mirror — and the captured EN and ES slots hold
*identical* strings for title, description and caption. Worse, the pop-up's
caption is the same literal (`"Juega Ya "`) as the notification's. A global
replace therefore wrote one language into every slot and gave the pop-up the
notification's caption, while the sheet's pop-up caption was parsed and
discarded. It looked fine: the captured literal was gone, so every
leftover-detection check passed.

`set_channel_copy` / `set_sms_text` address each field by **name** instead —
the template already encodes the language (`title-en`, `caption_es`, `des-en`,
`description_es`) — and write both storages. `verify()` then reads the copy back
out per node and per language and compares it with the sheet, so a field that
lands in the wrong language or the wrong node is a refusal rather than a
draft that looks right.

This is a **parallel** journey, so its canvas carries `dropEdge` / `mergeEdge` /
`flowEntry` scaffolding beside the activity nodes. `COMPOSER_RULES.md`'s
position rule applies to the activity nodes only; the scaffolding has no
position in the capture either, so `verify()` checks position on activity nodes
and refuses any canvas node that is neither an activity nor known scaffolding.

Contract: `scripts/test_sport_comms.py` — offline, no key. It asserts the
prepared body differs from the template only in leaves holding a value the
generator meant to write, and feeds `verify()` eight bodies that each break one
rule to prove it refuses rather than warns.

### Comms journey from content — `journey_composer.py` → **AI** page
Composes an arbitrary comms chain from captured nodes with **your** copy:
`nc` → `popup` → `sms` → `email`, one journey per date (the channels are nodes in
one chain, not separate journeys).

Four settings are not optional here, because a comms node is copied whole and
whatever you leave unset stays the captured campaign's:

| setting | on | leaving it unset ships |
| --- | --- | --- |
| `icon` | `nc` | the old promotion's card artwork |
| `image` | `popup` | the old pop-up background (`background_image_src`, *not* `icon`) |
| `template` | `email` | the old campaign's content-studio email |
| `subject_es` + `hero` + `hero_link`/`promo_page_id` | `email` | *(authors a new content instead — see below)* |
| `link_en/es` | `nc`, `popup` | players sent to the old promo page |

`icon` and `image` take a URL **or** the literal `PICK`. A brief carries files,
not media-library URLs, so `PICK` writes a placeholder that the emitted console
script resolves at paste time: it opens a file picker, uploads to the media
library, and substitutes the returned `absolute_link`. It is not a way to skip
the artwork — the script refuses to POST while any placeholder survives, and a
`PICK` build with no `--script` fails, since the placeholder would otherwise sit
where a URL belongs.

Two things about that table are easy to get wrong, and both shipped a draft that
reported VERIFIED OK:

- **The pop-up's link is language-independent.** It keeps one `link` in the
  `common` tab (`buttons_1_link` is the `%link%` indirection), so `link_en` /
  `link_es` both write that one slot. Before they did, neither matched and the
  pop-up button kept sending players to the captured campaign's promo page.
- **`deeplink` now defaults to the link.** Unset, it was the reference's own
  in-app URL — so the card was right on web and wrong in the app.

`desc_en` vs `desc_es` is matched on the language **suffix**, not by substring:
`"es" in "des-en"` is true, and that made the Spanish pass overwrite every
English description, so the EN notification shipped the ES copy.

#### The email: author a content, don't borrow one

An email's copy is not inline on the activity — the activity references a
content-studio content by id, which is why `template` alone can only ever reuse
someone else's creative. Setting `subject_es` / `preheader_es` / `heading` /
`hero` / `hero_link` (or `promo_page_id`) instead **authors a new content**: the
composer substitutes the captured JBCL creative, and the console script creates
it, publishes it, and repoints the journey at the id it gets back — the same
create → save → publish flow `comms_campaign.py` uses for GOW. The content the
spec names is never edited; a new one is always created. `template` and the
authoring settings are mutually exclusive, and asking for both is refused.

Two captured JBCL creatives, with different slots. `creative` picks one; left
unset, whichever fits the settings given is used and reported:

| creative | template | slots | when |
| --- | --- | --- | --- |
| `hero_only` | `gow_email.json` | `heading`, `hero` | the copy is *in* the image (how GOW works) |
| `text_body` | `jbcl_tournament_email.json` | `desc_es`, `hero`, `cta` | the brief has body paragraphs |

`desc_es` takes the brief's Description verbatim — blank lines become the
`<br><br>` breaks the creative uses, and the text is **escaped**, so a stray `<`
in a spreadsheet cell shows up instead of breaking the body. `cta` is the button
image *below* the text; both it and `hero` accept a URL or `PICK`.

What these creatives can and cannot carry, because they are real captures and
not a layout invented per campaign:

- **A setting the chosen creative has no slot for is refused**, never dropped.
  Giving `desc_es` to `hero_only` is a refusal — silently ignoring it is how a
  brief's body copy "shipped" while the email showed only a picture.
- **The CTA is an image in `text_body`.** A sheet's email Button *text* has
  nowhere to go: it has to be part of the button image. `comms_builder.py` says
  so rather than dropping it quietly.
- **`hero_link` vs `promo_page_id`.** One is required — unset, the email ships a
  dead link. `hero_only` bakes the promo path around an id token, `text_body`
  holds the whole href, so a promo id is expanded into one.
- **The brand must match.** Both captures are JBCL's; a PMCL run authoring one is
  refused. Emailing one brand's players another brand's creative is a brand swap,
  not a substitution.

The inherited-content check refuses a build that still shares any content value
with its reference, so an unset one is a failed build rather than a cosmetic
slip. That check exists because a "Physical Prize" journey once shipped carrying
the Game of the Week SMS, email and promo link.

### Comms builder — `comms_builder.py` → shell
**The JBCL comms entry point.** Pick the channels, say where you want engagement
splits and waits, paste the sheet, get the script. **No model is involved**,
which is the point: a comms chain is not something worth inferring.

`--variant` starts from a shape that used to be a script of its own. A variant is
only defaults — anything on the command line still wins — so four near-identical
generators became four rows of data, not four code paths:

| `--variant` | chain | replaces |
| --- | --- | --- |
| `tournament` | NC → wait → split → pop-up → wait → split → email → wait → split → SMS | hand-written specs |
| `gow` | NC → pop-up → SMS | `comms_campaign.py` (standalone use) |
| `scratch_card` | NC → pop-up → email | `sport_comms_campaign.py` |
| `nc_only` | NC | `nc_discount_campaign.py` |

The superseded generators still exist and still work — the GOW tab calls
`comms_campaign.py`, and `nc_discount_campaign.py` owns the baked calendar. They
are marked `superseded_by` in the registry so the Optimization list says which to
reach for. Reach for the builder for anything new.

**PMCL comms is deliberately not here.** `journey_composer`'s node library is
entirely JBCL-captured (`SOURCES` is `gow`, `gow_comms` and the two `udch`
files); `tournament_pmcl_comms.json` is PMCL and excluded. Routing PMCL through
the builder would build PMCL copy into JBCL nodes — the brand swap the email
guard already refuses — and adding a second brand's capture to the node library
is the node-schema-mixing risk `COMPOSER_RULES.md` exists for. So
`tournament_pmcl_campaign.py` and `nc_discount_pmcl_campaign.py` stay separate
until that capture is added to `SOURCES` on purpose, with the blank-canvas checks
re-run.

```bash
.venv/bin/python journey-cloner/comms_builder.py --sheet sheet.tsv \
    --channels nc,popup,email,sms --splits nc,popup,email \
    --wait nc=2h --wait popup=1d --wait email=1d --script
```

Where each input comes from — nothing else is consulted:

| | |
| --- | --- |
| the chain shape | `--channels` / `--splits` / `--wait`, verbatim |
| every word of copy | `spec_parser.py` reading the pasted sheet |
| the link, date, journey name | the sheet's `Link`, `Start date`, `Event` rows |
| the journey body | `journey_composer.py` cloning captured nodes |

Waits take shorthand (`30m`, `2h`, `1d`, `1w`) or an ISO-8601 duration. A split
after a channel ends the *engaged* path and continues down the unengaged one.
Artwork defaults to `PICK`, so the script prompts for each image at paste time.

Every gap refuses instead of being filled:

- **A channel picked with no copy in the sheet.** This was the whole risk — an
  empty channel ships the captured campaign's words.
- **A split on SMS.** No SMS engagement event is captured, so it would branch on
  nothing. Splits exist for `nc`, `popup` and `email`.
- A split or wait naming a channel that was not picked; a channel picked twice;
  no channels; an unreadable wait; no link, date, or email heading anywhere.

`scripts/test_comms_builder.py` asserts the copy reaching the spec is the
sheet's cells byte for byte, and that each refusal above fires.

### GOW comms — `comms_campaign.py` → built with GOW
The comms half of a GOW campaign; runs as part of that tab by default.

---

## Assets

- **Slot Cards** → Optimization ▸ Slot Cards. Reveal cards / GIFs for email and
  on-site.
- **Figma export** — `figma_export.py`. Pulls the GOW image slots straight out of
  Figma (needs `FIGMA_TOKEN`); used by the GOW flow.

---

## Tools

- **AI planner** — `compose.py` + `journey_composer.py` + `render_journey_design.py`,
  driven from the **AI** page. Brief → plan → design boards → console scripts.
  Status and roadmap: `../JOURNEY_COMPOSER_STATUS.md`.
- **Games registry** — `build_games_registry.py`. Rebuilds `library/games.json`
  (4,901 games / 48 providers) from the backoffice catalog. The composer refuses
  any game not in it, so a stale registry looks like "that game does not exist".
- **Automation catalog** — `build_catalog.py`. Rebuilds `catalog.json`, which the
  Optimization overview's "captured automations" graph reads.

---

## Adding a new automation

> **Faster path:** `HAR_TO_AUTOMATION.md` is a runbook a Claude session executes
> — hand it a HAR of one manual run and it analyses the flow, asks you the
> questions only you can answer, and writes the template + generator. Start with
> `har_analyse.py`; the hand-build below is what it automates.


1. **Capture** the flow by hand with DevTools open; save the request bodies.
2. Put the template in `templates/<brand>/<name>.json` — verify it renders.
3. Write the generator next to its peers: `prepare()` builds the bodies,
   `verify()` refuses a wrong one, `emit()` writes the console script. Copy the
   token-capture preamble from any existing script.
4. Add it to `GENERATORS` in `app/services/promotions_catalog.py` with its group,
   brand and where it is driven from. The admin warns until you do.
5. If it is a journey shape the composer could express instead, prefer a
   **recipe** (`RECIPE_BUILDING.md`) — recipes are validated and unit-aware, and
   the AI can drive them.
