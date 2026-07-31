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
today 6 (sport_wof), 4 (casino_wof), 5 (casino_scratch). A campaign wanting 7
prizes cannot be built until a 7-slice wheel is captured. Weights must sum to
100, and `journeys` needs exactly one entry per slice.

**Only six things are overridden; everything else ships as captured.** The run
sets the dates (per-kind minute offsets reproduce each capture exactly),
`internalName`, `urlShortName` (prefixed per kind — a bare date 409s
`UrlShortNameAlreadyUsed`), the weights and the prize routing. There is **no
knob layer and no inherited-content guard here** — unlike a composed journey,
nothing refuses a wheel that still carries the previous campaign's content. So
these ride along untouched, and every one of them has been wrong at least once:

| inherited field | what the templates carry today |
| --- | --- |
| `randomizerShotPolicy` | `"Once"` — all three. A "spin per deposit" brief still ships `Once` |
| `playerVisibility` | `"Authorized"` — all three, including wheels a brief wants public |
| `filterConditions` | the captured campaign's audience (casino_wof: `Business: Premium, Negative`) |
| `contentId` / `frontId` | the captured campaign's visual bundle |
| `isEmptyPrize` / `isLimitedPrize` / `prizeQuantity` | per slice, as captured — casino_wof has no empty slice at all |

`verify()` checks slice count, numeric weights, non-empty routing, date ordering
and that a visual bundle is present. It does not — cannot — check that any of the
above is right for *this* campaign. Fix them in the backoffice after the draft is
created, and say so in the plan rather than implying the build applied them.

**Prize routing resolves journey NAMES on exactly one path.** `compose.py
--batch` (`{"journeys": [...], "randomizer": {...}}`) creates the journeys first
and substitutes the real `JRN-*` ids it gets back — that is what makes the whole
promotion one paste. Run standalone, `randomizer_campaign.py --journeys` writes
its arguments into `journeyPrizeSettings.journeyId` **verbatim**, and `verify()`
only asserts the field is non-empty. A standalone wheel therefore needs real
`JRN-*` ids; passing names there produces a green build routed at journeys that
do not exist. Note which path you are on: the backoffice only takes the batch
path when a reply carries more than one *recipe* spec, so a wheel whose prize
journeys are MODE 5 chains is built standalone.

Other things worth knowing: `--dates` creates one draft per date in a single
paste; the generated script has `PREVIEW=true` (log the bodies without sending)
and `DEBUG=true` (create one draft, print the response, skip the fill); the fill
is `POST /promo/v2/randomizer?draftId=<id>` for all three kinds, because the
`PUT /randomizer/<id>` variant wants a different randomization GUID and 422s
`Invalid Randomization identifier` on a numeric draft id.

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

### PMCL Tournament — `tournament_pmcl_campaign.py` → Optimization ▸ PMCL Tournament
Notification + pop-up + SMS wired to the Smartico tournament deeplink
(`#_smartico_dp=dp:<slug>&id=<id>`), driven from a pasted sheet. The email is
part of this run: `tournament_pmcl_email.py` is a **module it imports**, not a
separate generator — it builds the substituted email *content*, and the console
script creates + publishes it at paste time, then swaps the resulting content id
into the journey.

Five mechanics that are not obvious from the tab, each of which changes what the
operator receives:

- **The entry window is fixed** to the same day as `--date`, 12:00 → 19:00 Chile
  — identical to GOW comms, and not driven by the sheet.
- **The tournament dates drive two derived activities.** `calc_tournament_days`
  turns the sheet's start/end into the `wait_date` the journey waits on and the
  revoke window on the notification, so a wrong end date moves more than the
  copy. `--tournament-id` swaps the id in every channel's link; the notification
  and the SMS build that link differently (`notif_link` vs `sms_link`), so both
  are rewritten, not one.
- **Photos are paste-time, and only with a folder id.** The template keeps two
  placeholder tokens (NC icon, pop-up background) that the console script fills
  from a PMCL media-library upload. `DEFAULT_FOLDER_ID` is baked in so a normal
  run gets the file pickers; `--folder-id` overrides it and `--no-photos` opts
  out — and opting out means the captured campaign's image URLs ship.
- **The SMS gets a `Fortunazo | ` prefix** added by the generator, so the sheet
  should not carry one.
- **Brand is PMCL** and the base URL is the shared `pmi.rea-backoffice` host —
  the same one the PMCL Discount NC generator uses.

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
| `link_en/es` | `nc` | players sent to the old promo page |

The inherited-content check refuses a build that still shares any content value
with its reference, so an unset one is a failed build rather than a cosmetic
slip. That check exists because a "Physical Prize" journey once shipped carrying
the Game of the Week SMS, email and promo link.

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
  The end-to-end flow is below; status and roadmap: `../JOURNEY_COMPOSER_STATUS.md`.
- **Games registry** — `build_games_registry.py`. Rebuilds `library/games.json`
  (4,901 games / 48 providers) from the backoffice catalog. The composer refuses
  any game not in it, so a stale registry looks like "that game does not exist".
  Note the registry outgrew the prompt: only `library/games_index.md` (provider
  counts, ~1.5 KB) is injected, so the model names games in plain language and
  the composer resolves them. It cannot see the titles, and must never claim one
  is unregistered.
- **Recipe catalog** — `compose.py --catalog` writes `recipes_catalog.json`,
  which IS the machine-readable part of the planner prompt. Regenerate it in the
  full venv and check all four sections survived (`recipes`, `references`,
  `chain_composer`, `randomizer`): the two palette builders swallow import
  errors and return `{}`, so a missing dependency silently produces a smaller
  catalog and the freshness check in `scripts/test_composer_contract.py` will
  then happily bless the smaller one.
- **Automation catalog** — `build_catalog.py`. Rebuilds `catalog.json`, which the
  Optimization overview's "captured automations" graph reads. Different file,
  different purpose from `recipes_catalog.json` above, and its `recipes` key is
  a different thing again — prose flow patterns ("free spins after a deposit"),
  not the composer's recipe keys. Nothing in the AI prompt reads it.
- **HAR analyser** — `har_analyse.py`. Step 1 of `HAR_TO_AUTOMATION.md`; reads a
  capture and reports, builds no draft. Registered in `_NOT_GENERATORS` so the
  drift alarm does not flag it.
- **Plan linter / agent entry point** — `plan_lint.py` + `ai_campaign_builder.py`.
  A **dormant** earlier design: a text flow-DSL validated against `catalog.json`,
  with its own aliases (`NC1`, `NC5`, `SMS`), its own recipe names and its own
  knob shape. Nothing in the app or the AI page calls either one. `ai_campaign_builder.py`
  still describes itself as "the single entry point an agent uses" — it is not;
  the live path is the one below. Do not ground a plan or a spec in these files
  or in `catalog.json`'s vocabulary.

---

## How the AI path actually runs

Nine steps, from the operator's paste to a pasteable script. Everything the model
is grounded in is assembled per request from files on disk, so editing a doc
takes effect without a restart.

```
 1. INPUT        Operator pastes a brief into /admin/ai (editor role required).
                 POST /admin/planner/api  {messages[], temperature}
                 Last 40 messages forwarded; 20 000 chars each, upstream.

 2. PROMPT       app/routes/admin_planner.py::_build_system_prompt() reads
                 journey-planner/system_prompt.txt and substitutes five blocks:
                   <KNOWLEDGE_BASE>  REA_KNOWLEDGE_BASE.md
                   <CAPTURE_BACKLOG> REA_CAPTURE_BACKLOG_CHECKLIST.md
                   <RECIPES_CATALOG> journey-cloner/recipes_catalog.json  (generated)
                   <GAMES_REGISTRY>  journey-cloner/library/games_index.md (generated)
                   <CORRECTIONS>     corrections.md   (highest precedence)
                 journey-planner/planner.py does the identical substitution for
                 the CLI, which is why the two never disagree.

 3. RETRIEVAL    There is none — no embeddings, no search, no chunking. The whole
                 knowledge base is inlined every call (~17 K tokens). "Retrieval
                 quality" here is a question about what is IN those five files.

 4. MODEL        Gemini by default (gemini-2.5-flash for planning,
                 gemini-2.5-flash-lite for mechanical calls); Groq is opt-in and
                 gets a LEAN prompt — the KB and backlog swapped for one-line
                 pointers, because the free tier's 12 K TPM cannot carry them.
                 Transient 429/5xx retried 3× with 1.5 s / 4 s backoff.

 5. CONTINUE     A reply cut off by the output cap is continued from the exact
                 character it stopped at, up to 4 rounds, and the pieces stitched
                 (_complete). A 30-journey design block does not fit one round.

 6. MODES        The reply is prose (MODE 1/2) or a JSON spec (MODE 3–6). The
                 engine is picked from the spec's OWN keys, never from the
                 browser's guess: `kind`+`date` → randomizer, `reference` →
                 graph, `chain` → chain, `recipe` → recipe.

 7. DESIGN       POST /admin/planner/design runs render_journey_design.py over
                 the MODE 1 `diagram` block and returns PNG boards as data URLs.
                 An outline that arrived without a design block gets ONE repair
                 round asking for just the block. The model never sees the images.

 8. COMPOSE      POST /admin/planner/compose extracts EVERY spec in the reply and
                 dispatches through app/services/journey_cloner_runner.py:
                   recipe  → compose.py --spec       (validate_spec: 5 gates)
                   graph   → compose.py --graph
                   chain   → journey_composer.py compose --script
                   wheel   → randomizer_campaign.py  (argv, not stdin)
                   many recipe specs → compose.py --batch (one paste, N drafts,
                                       and the wheel that routes into them)

 9. REPAIR       A refusal is fed back to the model with the offending spec and
                 one instruction — fix only what the refusal names — for up to 2
                 rounds. A refusal that says the SHAPE is wrong instead forces a
                 switch to a MODE 5 chain. Repairs run on the lean prompt with a
                 1 024-token thinking budget. A repair that swapped a game for a
                 near match the composer suggested is DROPPED, not accepted:
                 granting spins on a different game is wrong, not fixed. The best
                 scoring round is what the operator gets.
```

The output is always a console script the operator pastes into a logged-in
backoffice tab. Nothing on this path POSTs to the backoffice, and the model never
writes journey JSON by hand — a hand-written body has `elements: []` and renders
as a blank canvas.

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
