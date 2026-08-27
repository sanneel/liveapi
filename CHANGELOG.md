# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Tag a release once its changes are on `main` and the deploy has passed
`deploy/deploy.sh` (which now gates on `scripts/phase_b_health.py`). Roll back
with the DB snapshot + `git reset` commands printed by that script.

## [Unreleased]

### Added
- **The onboarding playground caught up with the capture library.** Five
  activities the fragment library has captured since the tour was written —
  Reference codes (`registration`), Random split, Sport FreeBet (`freebet`),
  Sport Bonus and Campaign Connector — are now buildable in the `/onboarding`
  playground, with their real events, upstream data needs and the transitions
  mined from captured journeys (`library/mined_catalog.json`). The validator
  now also enforces the composer's delivered-message rule: a send that lands is
  followed by a wait, a split or an ending, never another send — only a failed
  send goes straight to the fallback channel. Two practice tasks joined the
  note: the sport freebet-for-a-deposit chain, and the wheel's empty-prize
  journey (the brief-invisible rule every wheel build trips over). Quiz options
  are shuffled per showing so the answer's slot cannot be memorised, and a
  primary-port bug was fixed where `Sent$` matched `NotificationNotSent` and
  hung new nodes off the failure port by default. The screens removed in the
  tour rewrite left ~380 lines of dead CSS and script behind; they came out.
- **Journey design boards** in the Optimization → AI tab. MODE 1 now answers a
  brief with the short outline *plus* a `diagram` JSON block, and the boards are
  drawn **automatically** with that reply — one card per activity with its own
  icon, arrows for the flow, a lane per branch, and the ⚠/❓/⛔ flags printed
  under each journey. They appear inline in the conversation (scroll the answer)
  and are collected in a Boards tab. Drawn by
  `journey-planner/render_journey_design.py` (Pillow) via
  `POST /admin/planner/design`; boards come back inline as data URLs and are
  downloadable as PNGs. Icons are built-in line glyphs, each overridable by
  dropping a PNG into `journey-planner/icons/` (see the README there). Covered by
  `scripts/test_journey_design.py` in CI.
- An outline that arrives **without** its design block (MODE 1 compliance slips
  on long spreadsheet briefs) is repaired once server-side: the planner is asked
  for just the block for the plan it already wrote, and that is drawn. Same
  one-shot-repair philosophy as the composer's refusal retry — the operator never
  has to notice or re-ask.
- **Batch compose now repairs itself.** A campaign refused 30 times is one
  mistake made 30 times, so the distinct refusals are digested (per-object
  prefixes stripped) into up to two whole-batch correction rounds. A shape
  refusal ("recipe does not define that knob") deterministically re-emits every
  object as a MODE 5 chain, with the allowed inline settings for exactly the
  activities in play pasted in from `recipes_catalog.json` — which is what
  converges it in one round instead of five. Measured on the Ruletazo brief:
  0 of 39 objects → 20 built console scripts.
- **A repair may not change a game.** When the composer refuses an unregistered
  game it helpfully suggests near matches, and the model would take one — turning
  "Bone Fortune" into "Ocean Fortune". That builds cleanly and grants spins on the
  wrong game, so `_reject_game_swaps` drops any repaired spec naming a game the
  brief never did and reports it as refused with what to do (register the game, or
  name the replacement yourself). Only the operator picks a substitute.
- **Full script** (was "Build script") asks for the build specs itself when the
  last reply is still prose, so "now give me the full script" is one press from an
  approved plan instead of an error telling you to guess the magic words.
- **The whole promotion in one paste — journeys AND the wheel.** A randomizer's
  prize routing needs journey ids that do not exist until the journeys are
  created, which is why it used to be a second script fed by hand-copied JRN ids.
  The campaign script now creates the journeys, then creates and fills the wheel
  with the ids it just received: each prize slice names its journey by
  `journey_name` and that name is resolved at run time (a literal `JRN-…` still
  passes through, for a wheel pointed at existing journeys). Built by
  `compose.py --batch` from `{"journeys": [...], "randomizer": {...}}`.
  Refused loudly rather than guessed when the routing is unusable — no
  `journeys` list, leftover `JRN-0-XXXXXX` placeholders, a count that does not
  match the template's prize slices, or (at run time) a prize naming a journey
  the run did not create. In every case the journeys still build and only the
  wheel is withheld; silently keeping the captured template's own prize routing
  would point a live wheel at somebody else's journeys.
- The AI tab is rebuilt around the assistant layout: header card with model chip,
  starter chips, a Boards/Script results strip, and a sidebar with the journey
  index (click a journey to jump to its board), quick actions and run context.
  All colours come from the redesign.css theme variables, so it follows the
  chosen accent and works in dark mode; fenced JSON in a reply is folded to a
  labelled chip instead of burying the plan.
- **`scripts/eval_planner.py` — the planner is now measured, not asserted.** Every
  planner fix in this session was judged by one ad-hoc run, which cannot tell an
  improvement from a lucky sample: four runs of the same brief scored 85 / 95 / 91
  / 87%. The eval runs a fixed brief set (a simple one-journey campaign, a 5×6
  deposit matrix, a wheel with more prizes than any captured template) and scores
  each reply against the failures that actually shipped — MODE 2 detail in a MODE
  1 reply, invented "(Fallback)" journeys, an enumerated matrix, an impossible
  prize count, a missing or unparseable design block, paragraph-long flags, and a
  ⛔ claiming a game is unregistered when it is not. Not in CI: it needs a live key
  and spends ~35K tokens per brief. Run it before and after a prompt change.

- **AI has its own page (`/admin/ai`)** with a sidebar entry, instead of a tab
  sharing the Optimization page with nine generator forms. `/admin/planner` and
  `/admin/promotions?tab=planner` redirect to it, so old links keep working.
- **A generator registry** (`promotions_catalog.GENERATORS`) — one place that says
  what campaign generators exist, which brand each is for, and where it is driven
  from (a tab, a page, or the shell). The Optimization overview renders it grouped
  Casino / Sport / Wheels / Comms / Assets / Tools, and `unlisted_generators()`
  flags any generator script the registry does not name. Before this, the answer
  to "what can this build?" was split across catalog.json (5 automations), the tab
  list (10) and journey-cloner/ (20+ scripts) — which is how PMCL Bet & Get looked
  missing when it had already shipped, and how `casino_journey.py` sat with no UI.
- **Comms journeys from content, for the AI.** The chain engine could already
  build NC + pop-up + SMS + email, but three settings had no way in — so every
  attempt was refused by the inherited-content guard for still carrying the
  captured campaign's artwork, links and email template. Added `template` /
  `from_name` on `dextra_email` and `image` on the pop-up (the pop-up's artwork is
  `background_image_src`, not `icon`), and taught the planner the pattern with a
  worked example. A comms journey with your own copy now composes clean —
  verified end to end, with none of the reference campaign's content leaking.
  Also fixes a duplicate `dextra_email` key in the palette dict that silently
  overwrote its settings with "(none)", which is why the model never learned them.

- **HAR in → automation out.** `journey-cloner/har_analyse.py` reads a HAR of one
  manual backoffice run and reports the automation inside it: the mutating calls
  in order with repeats collapsed into loops, the call carrying the payload (your
  template), the ids that must flow from one step's response into a later step's
  request, and the leaves that look per-run — classified by the same code the
  recipes use. On the reference HAR: 158 entries → 4 steps, one 154 KB payload,
  3 dependency edges, 171 candidate inputs out of 4,804 leaves.
  `HAR_TO_AUTOMATION.md` is the runbook a Claude session follows to turn that into
  a registered generator, and `CLAUDE.md` routes any session there the moment a
  HAR arrives — so the procedure does not depend on remembering to explain it.
  Credentials are scrubbed in memory before anything else and the raw file is
  never persisted; `scripts/test_har_analyse.py` (in CI) proves a token, session
  cookie, Set-Cookie and password planted in a HAR reach neither the report nor
  the parsed analysis, alongside 16 checks that the flow is read correctly.

- **The composer refuses five wiring rules it used to only ask for.** Each was
  prose in `corrections.md`, and a real brief this week produced a journey that
  violated one and built cleanly — a rule that lives only in the prompt is a
  suggestion. All five are grounded in counts measured over all 18 captures:
  - `deposit -> promotion` (17 `promotion -> deposit` edges across 5 captures,
    all on `PromotionAccepted`; **zero** the other way). The player must accept
    the offer before a condition can gate its reward.
  - `casino_bonus_v2 -> freespin_bonus` (4 the right way, zero reversed) — the
    wagering bonus would have nothing to wager.
  - `withWagering` disagreeing with the presence of a wagering node, **in both
    directions**. The correlation is 1:1 across every capture. `false` plus a
    wagering node is an "instant" bonus that grinds; `true` with no wagering node
    is a requirement that silently does nothing.
  - a **delivered** message wired straight to another send (0 occurrences in 18
    captures — a success goes to a wait, a split or an end). The *failure* branch
    is deliberately untouched: `NotificationNotSent -> next channel` is the
    correct immediate fallback, 7 occurrences.
  - a node whose `parentNode` is not on the canvas, `extent: "parent"` with no
    parent, or a node with no `position`.
- **Explicit Gemini context caching.** The system prompt is byte-identical on
  every call and ~19K tokens; both live calls measured `cached: 0` while the code
  was already reading `cachedContentTokenCount`. A `cachedContents` entry keyed on
  a digest of the prompt **and** the model (so an edited `corrections.md` starts a
  new one) now bills **98% of input as cached from the first call** — implicit
  caching needs warm-up and was not hitting. Fails open: any error disables
  caching for the process and the prompt goes inline, because a planner that
  works uncached beats one that 500s on a rejected cache create. Measured on an
  eval run: 65,284 input tokens, 484 billed.
- **The Prediction tab accepts the sheet ops actually writes.** The parser only
  understood the machine schema (`internalName`, `headerTitle_en`, a questions
  table with an `order` column), which nobody authors by hand.
  `parse_operator_sheet()` reads the label/value sheet ops hands over — Name,
  Start/End Date, Widget Header/Subtitle, Promo Page Header, Promo Content,
  repeated `Prediction`/`Answers` pairs, Prize Structure, Description — and is
  auto-detected, so the machine schema keeps working. Dates are `DD.MM.YYYY HH:MM`
  Chile; `show`/`hide`/`expiration` follow the window; `urlShortName` derives from
  the name. Question text is used verbatim because the answer legend is already
  written into it. `Description` splits on the `Términos:` heading, since one cell
  carries how-to-participate *and* the terms.
- **`resolve_derivable_game_ids()`** fills game fields the registry can derive
  instead of refusing them. A spec that named the game and gave a correct
  `lobbyGameId` still blocked on `walletGameId`/`externalGameId` marked
  `RESOLVE_AT_BUILD_TIME` — the coercion already existed in `_check_games`, it
  just ran 28 lines after the blocker gate refused. The composer was asking the
  model for data sitting next to the id it had already supplied.

### Fixed
- **Every composed journey rendered a grey/blank canvas.** 14 of the 23 activity
  types the composer loads carry a `parentNode` pointing at a `parallelFlow`
  container they were cut out of, and that container is never emitted — so most
  composed journeys referenced a parent that does not exist. All nine valid
  captures have zero dangling `parentNode`, so it is a defect, never a variant.
  `put()` strips it during layout and `verify()` refuses any that survive.
- **Two recipes built the deposit gate ahead of the offer.**
  `casino_deposit_freespins` and `sport_deposit_freebet` both declared
  `deposit -> promotion`, contradicting their own reference captures, so every
  MODE 3 draft was wired backwards. `corrections.md` simultaneously stated the
  correct order four lines above the rule forbidding the wrong one.
- **The `comms` recipe stripped every wait and split out of its own reference.**
  It built `dwh_source -> nc -> nc -> sms -> email` while `gow_comms.json` has 3
  waits and 3 splits — four channels firing at once at everybody, nobody measured.
  It now mirrors the reference. The prompt reinforced the error by describing a
  comms journey as "notification → SMS → email"; corrected.
- **Split branches past path 1 vanished from the canvas.** A split names its
  handles `path<N>`/`other`, *not* after the event, and the captured fragment kept
  only the ports it had wired (`ams_decision_split`: 1 port for 21 events). Edges
  addressed a handle the node did not expose. The handle is now derived and the
  missing port minted, in both engines.
- **Composed drafts shared the captured campaign's promotion and promo page.**
  `ContentId`, `FrontId`, `campaignId`, `promotionId` and `promotionLinkId` were
  the *same server-side objects*, so editing a new draft's promo content rewrote
  the live Game of the Week page — the Sport WOF bug again. Fresh ids are now
  minted per draft on the spec, graph and chain paths, consistently across both
  storages. The audit missed them because `_is_content()` only accepts
  uppercase-leading tokens, so lowercase uuids sailed through.
  ⚠ A minted `ContentId` owns no content tree, so the offer card renders EMPTY;
  the build reports `INCOMPLETE — the promo page`. Build the page with
  `gow_campaign.py` first and pass its ids as the promotion node's new
  `content_id` / `front_id` settings.
- **Game names resolved by silent first-match.** The index squashed spaces (so
  "Coin Volcano" and "Coinvolcano" collided) and kept the first hit with
  `setdefault` — but **47 display names are shared by 2+ games, 94 games in
  total**, so "God of Wealth" picked whichever provider came first in the file.
  Resolution now follows `gow_campaign.py`'s `resolveGame()`: exact match on the
  full normalised name, provider to break a tie, one unambiguous prefix, and a
  refusal listing the studios when a name is ambiguous.
- **Wait nodes were captioned with the capture's own label**, so a 1-day wait read
  as "2 Hours" on the canvas. `displayData` is a second copy of the value and only
  `waitPeriod` was being written.
- **The prompt contained a section contradicting its own catalog.** The hand-written
  capture backlog answered "what is composable" in prose while the generated
  `recipes_catalog.json` answers it from the code that builds — and the prose had
  drifted, still calling `email_engagement_split` unconfirmed long after
  `gow_comms.json` captured it. There was even a correction whose only job was to
  contradict the contradiction. Backlog dropped from the prompt (~2.2K tokens),
  fixed at source, correction deleted; the file stays on disk as a human
  capture-planning note.
- **Prediction promos kept the captured campaign's copy in two slots that had no
  sheet column at all**: `forecastBlockDescriptionKey` (the promo page's top
  marketing blurb — the template's own comment flagged it as a known gap) and the
  widget title, which reused the promo *page* header and forced a two-line title
  into a one-line badge. With no `Prize` row the widget amount is now **blanked**
  rather than inheriting `$20.000 Apuestas Gratis` from the Champions League
  promo — written whenever the key exists, even empty, because a truthiness check
  would have left the captured value standing.
- **Dark mode on the AI page was hooked to `prefers-color-scheme`,** but the app
  toggles `html.dark` (`base.html:202`, `redesign.css:71`), so the panel's shadow
  tokens would never have applied when the operator used the theme toggle and
  every surface would have flattened into the dark ground.

- **Free-spin activities shipped the reference template's caps and labels.**
  `casino_instant_freespin` / `casino_deposit_freespins` had no knob for the
  bonus caps, so a brief specifying *Max bonus 200.000 CLP* silently built with
  instfs.json's own 50.000 — the values only differed when someone opened the
  draft in the backoffice. Added `spin_max_bonus_clp`, `spin_min_bonus_clp` and
  `spin_campaign_end` (all written to the freespin activity *and* the promo-lobby
  card, which carries its own copy).
- The display labels lied: a journey granting La Gran Copa advertised
  "Sweet Bonanza Super Scatter / Pragmatic Play" on the activity card and the
  promo card, because `gameTranslationKey` / `providerTranslationKey` are
  display-only and no knob wrote them. `sync_game_labels()` now derives all of
  them from the games-registry row for the lobby id (chain engine too).
- A date `fix_dates()` rewrites is announced in the build log instead of being
  swallowed — a campaign whose window has already passed gets pushed to +7 days,
  which is how a March campaign shipped an August provider end date.
- The campaign build log was unreadable: `fix_dates` printed one ⚠ per rewritten
  field, so a 20-journey batch buried its refusals under ~100 lines. It is now one
  line per journey, and the build ends with an explicit `IN THE SCRIPT` /
  `NOT BUILT` summary — a dropped wheel used to be invisible.
- The batch result claimed "20 journeys + the wheel" while the script actually
  carried 5 and no wheel. The label is now read back from the build log, so it
  states what the script will really create and flags how many objects were not
  built.
- A wheel whose prize count does not match its captured template refused with
  "--weights has 7 values…", naming a CLI flag nobody typed. It now says which
  kind has how many slices and what the options are.
- Design boards failed with a raw Python traceback in the chat when
  `data/journey_designs/` was not writable by the service user. The directory is
  now owned by `admin:admin`, and a write failure comes back as one clean line
  (`cannot write <path>: …`) instead of a stack trace.

### Changed
- **The planner prompt: six response modes collapsed to three.** Modes 3–6 all
  emitted machine JSON — they were not response modes but four spec *dialects*,
  and the composer already picks the engine from the spec's own keys
  (`_spec_mode`). ~230 lines went on a decision the code makes regardless, and
  "MODE 6 — RANDOMIZER" described an object, not a reply. Now MODE 1 outline /
  MODE 2 detail / MODE 3 spec, with the four shapes as a table inside MODE 3. A
  trap buried in MODE 4's prose is now stated where it applies: `graph` specs take
  **minor** units, `chain` and `recipe` take major CLP. Nine stale references to
  the removed modes fixed across the prompt and corrections.
  Prompt size: **22,785 → 19,066 tokens** full, **16,083 → 14,468** lean.
- **Prediction draft/content/front ids are baked in**, not three form fields.
  They are properties of the promo, not of a run, and three GUIDs retyped from
  memory was an easy way to write this campaign's content over another promo's
  tree. An env var still overrides for a second draft.
- **The AI page is the conversation, full width.** The stage rail, the right-hand
  inspector, the empty state's headline and paragraph, the page subtitle and the
  card around the conversation are all gone; page and conversation are one
  `--surface` field aligned to a single 26px edge. Render design and Full script
  survive as buttons in the bar. Six ids belonging to removed controls are now
  looked up defensively so the JS cannot throw.
- **Eval baseline recorded for the first time: 96% (22/23)** on
  `scripts/eval_planner.py`. The one failure is `wheel_fits` on the matrix brief
  (a wheel planned without a slice count). Note the run used `flash-lite`, not the
  `2.5-flash` the AI page uses — re-run with `--repeat 3` on the real model before
  trusting the number as a trend.

- **The planning call uses `gemini-2.5-flash`; the mechanical calls stay on
  flash-lite.** Planning is the reasoning step, and flash-lite is measurably
  inconsistent at it — across runs of the same brief it enumerated a matrix it was
  told to group and once planned a **31-slice wheel** (no captured template has
  more than 6). Measured with `scripts/eval_planner.py` over six runs, the split
  took `wheel_fits` from 50% to 100% and `grouped` / `mode1_shape` /
  `no_invented` / `no_false_blockers` to 100%, overall 87% -> 91-94%. Repairs and
  design-block extraction are mechanical, so they keep the cheap model: the better
  tier is paid for roughly one call in six. `GEMINI_PLANNING_MODEL` reverts it.
- Prompt: the MODE 1 rules became a **countable checklist** ("object lines: at most
  15", "flag lines: at most 200 characters", "design-block entries: one per object
  line") instead of prose the model skimmed. That alone took grouping from 0/1 to
  3/3 and flag length from 33% to 100% on the eval, before the model change.
- A long flag now **wraps to two lines** on a board instead of being ellipsized. A
  300-character ⛔ was being truncated to its first clause — the flag most worth
  reading, silently cut, and the eval was blaming the model for writing it.
- **Boards fold by shape instead of trusting the model to group.** The outline
  grouped a tier matrix to five lines and the design block then enumerated 11–27
  boards anyway, which is the wall of near-identical pictures grouping exists to
  prevent. `collapse_variants()` now groups journeys by their activity signature
  and folds the NARROWER varying axis, so a 5-tier × 6-prize matrix draws as six
  boards — one per prize level, each card listing what varies
  ("Deposit ≥ 2.500 / 5.000 / 10.000 / 15.000 / 20.000 CLP") and a note naming
  every journey the board stands for. Folding the wider axis too would have lost
  which spin count pairs with which bet, so it deliberately folds only one.
  `--no-collapse` / `--collapse-at N` control it; the manifest and the chat report
  how many journeys share a board. Measured end to end: 85% → 98% on
  `scripts/eval_planner.py`.
- **Planner cost, measured rather than assumed.** Every reply logs and returns its
  token usage (`calls / input / cached / thought / answer`) and the AI tab shows a
  running total, so a campaign's cost is visible while you work. What the numbers
  showed, and what changed because of them:
  * Gemini's implicit cache hits hard — a repeated prompt came back
    `cached 23,515 of 23,528` input tokens. The system prompt is byte-identical on
    every call, so input is mostly billed at the cached rate within a session; the
    expensive part is output, not the big prompt.
  * The three MECHANICAL calls (design-block extraction, spec repair, batch
    repair) now use the lean prompt (no knowledge base, no capture backlog) and a
    1024 thinking budget instead of 8192: they apply a refusal they were just
    handed, they do not plan a campaign. Measured on one design-block repair:
    input 25,016 -> 17,212 and billed output 12,556 -> 5,250 tokens (-58%), same
    result (a valid design block).

- **A truncated planner reply now continues itself.** `planner_max_tokens` was
  4096; a 5-tier × 6-level spreadsheet brief plans 30+ journeys and died mid-JSON
  (`finishReason: MAX_TOKENS`), which left an unparseable design block and no
  boards. The cap is 16384 and `_complete()` resumes a cut-off reply from where it
  stopped (up to 4 rounds), stitching the parts — so plans, per-journey specs and
  design blocks are no longer limited to one round's worth of output. The renderer
  also salvages every whole journey from a still-truncated block and says how many
  were lost, instead of drawing nothing.
- MODE 1 groups a matrix instead of enumerating it: 5 deposit tiers × 6 prize
  levels is one line ("Journeys 8–12: tiers 2.500–20.000 CLP → 10 FS, bet
  50/100/200/300/400 by tier"), not 30. Thirty near-identical boards taught the
  reviewer nothing and did not fit in one reply; the per-tier values are MODE 2's
  job. Measured: the same brief went from 37 journeys to 9.
- A named-but-unregistered game is passed through as its NAME, never as the
  `⛔ RESOLVE_AT_BUILD_TIME` sentinel — the composer then refuses with near
  matches ("did you mean Ocean Fortune?"), which tells the operator what to fix,
  where the sentinel produced a blocker refusal naming nothing. The planner is
  also barred from claiming a game is absent from a registry it cannot see.
- MODE 1 is now outline-only prose: the OUTPUT FORMAT template is explicitly
  MODE 2's, so a first reply no longer arrives as a wall of per-activity
  settings. The activity chain lives in the design block instead.
- MODE 2 is what answers "give specs" / "the details" in words (a *machine* spec
  still needs "build spec" / "generate json"), and it no longer prints its own
  mode name or the MODE 1 "say which object(s)" sign-off.
- The planner chat is taller (`100vh - 250px`, min 660px) and has an
  **⛶ Expand** full-screen toggle — the log was cropped at the old height, and
  a wide design board needs the room.

## [1.1.0] - 2026-06-18

### Added
- **Parser drift canary** (`app/parser/drift_canary.py`): each campaign-monitor
  cycle probes a live jugabet listing URL and classifies the result as
  `ok` / `drifted` / `unreachable` / `no_events`. A `drifted` result (the page
  still advertises events but the extractor returns 0 — i.e. jugabet changed
  their embedded JSON shape) flips `/health` to degraded and fires a Telegram
  alert on the ok↔drifted transition. Configurable via `PARSER_CANARY_ENABLED`
  / `PARSER_CANARY_URL`; covered by `scripts/test_drift_canary.py` in CI.
- Deep post-deploy verification is now a **hard gate** in `deploy/deploy.sh`:
  after the service health check it runs `scripts/phase_b_health.py` and aborts
  the deploy (with rollback guidance) on a real failure. The admin-override
  check is skipped unless `PHASE_B_USERNAME`/`PHASE_B_PASSWORD` are exported.
- `/health` now reports live match volume (`matches.active`, `matches.inactive`,
  `matches.total`) alongside the existing per-feed freshness and degraded-state
  detection.
- Advisory security scanning in CI: a non-blocking `security` job runs
  `pip-audit` and `bandit`, plus a Dependabot config for pip, GitHub Actions,
  and npm.
- `CHANGELOG.md` (this file).

## [1.0.0] - 2026-06-18

First tagged release: the verified-good baseline.

### Added
- GitHub Actions CI (`.github/workflows/ci.yml`): compile check, the standalone
  parser/deactivation regression tests, and a from-scratch Alembic migration.
- Handoff-grade `README.md` with an architecture diagram, operations quick
  reference, and an honest project-status section.

### Changed
- `scripts/auto_deploy.sh` is off by default (`AUTODEPLOY_ENABLED=1` required)
  with a `/health` gate after restart — continuous deploy-on-`main` is for
  staging, not production.
- `DEPLOY.md` clarifies the reverse-proxy story (reference config uses Caddy;
  production runs nginx) and drops stale 2FA instructions (2FA was removed from
  the user-facing auth flow).
- `app/middleware/security.py` CSP comment corrected: Tailwind is served from
  the local bundle, not a CDN; remaining CDN allowances are for
  Alpine/htmx/lucide (unpkg) and SortableJS (jsdelivr).

### Fixed
- `.env.example` `MATCH_DEACTIVATE_AFTER_HOURS` corrected `6` → `12` to match
  the code and docs.

### Security
- `scripts/wipe_matches.py` is now safe by default: it previews row counts and
  requires `--yes` to delete.

[Unreleased]: https://github.com/sanneel/liveapi/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/sanneel/liveapi/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/sanneel/liveapi/releases/tag/v1.0.0
