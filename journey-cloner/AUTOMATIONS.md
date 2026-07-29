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
