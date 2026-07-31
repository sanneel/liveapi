# Corrections — operator-taught fixes

One fix per line, newest at the bottom. Format each as: the wrong assumption →
the right rule. These are appended to the planner's system prompt and OVERRIDE
the knowledge base when they conflict. Add a line the moment you learn something
— no need to restructure the main KB.

PRECEDENCE INSIDE THIS FILE: the list is append-only and ordered oldest → newest.
When two bullets here conflict, the LATER one wins — it was learned afterwards.
Never restate a machine-generated fact (recipe keys, knob names, game IDs) as
prose here: the RECIPES CATALOG and GAMES REGISTRY sections of the prompt are
generated and authoritative, and a prose copy can only drift out of date.

- Casino "Cashout" / limit value N → `releaseLimitMultiplier: N` with `limitType: "multiplier"` (it's a multiplier, not a bonus amount).
- Casino "Contribution" N → the wagering contribution rate; set it ONLY when `withWagering` is true.
- A Randomizer that has its own `urlShortName` needs NO separate Promo Page — the wheel URL is itself the landing page.
- KB §5/backlog marks these as uncaptured, but they ARE in the templates and can be built: `email_engagement_split`, `random_split`, `sport_bonus`, `registration`.
- A composed (not cloned) journey is proven to render + save in REA — see journey-cloner/COMPOSER_RULES.md for the canvas rules (position+positionAbsolute, one node schema per recipe, de-nest parentNode, start trigger).
- Brief field mappings (CRITICAL — fixes repeated misses):
  - "Max win: N" → `maxWinAmount` (minor units = N × 100).
  - "Bet × Bonus (spins)" → calculate bonus amount as bet × spins count. Sanity check: is it within [minBonusAmount, maxBonusAmount]?
  - "Days to activate bonus" → spins/bonus activation window (via `startAt`/`stopAt`).
  - "Days for wagering" → `bonusExpirationTime` in milliseconds (N days × 86400000).
  - "Days to make deposit" → `depositConditions.expirationTimeout` in ISO-8601 format (N days = `P0Y0M${N}DT0H0M0S`).
- Randomizer shot policy (CRITICAL — fixes "Once" errors):
  - "1 spin per player" / "once during promo" → `randomizerShotPolicy: "Once"`.
  - "spin for each deposit" / "daily spin" / "per-trigger spin" → NOT "Once". Use the repeatable policy; flag with ⚠ which policy (e.g. "once per deposit", "daily").
  - If brief ties spins to a repeatable action, it is NEVER "Once".
- Player visibility (CRITICAL — fixes deposit=public errors):
  - A public promo page anyone can view → `playerVisibility: "Unauthorized"` is fine.
  - Any deposit-gated flow is inherently `Authorized` (must be logged in to deposit). If a journey/wheel is triggered by a deposit gate, mark it `Authorized` even if the landing page is public.
  - Don't apply one visibility across the whole campaign — landing page and deposit flow can differ. State each separately.
- Multi-segment briefs (CRITICAL — fixes dropped tables):
  - If brief has TWO OR MORE value tables for different audiences ("Active" vs "Not Active", each with its own deposits/rewards), that is TWO campaign variants, not one.
  - Build BOTH variants, or flag with ⚠: "Brief has N segments (X, Y) — needs N variants. I've planned all N. Confirm you want all built."
  - Segments differ in: deposit tiers, contribution rates, targeting (dwh_source filter), sometimes reward tiers.
- Reward chaining order (CRITICAL — fixes casino follow-up):
  - Freespins → then wagering bonus: `freespin_bonus → casino_bonus_v2` (freespin produces winnings, casino bonus wagers them). NEVER parallel or reversed.
  - Deposit gate ALWAYS before the reward it gates: `deposit → (reward)`.
  - "Casino FreeSpin + Wagering + Deposit" recipe order: `external_system_source → deposit → promotion → freespin_bonus → casino_bonus_v2 → end`.
- Promotion BEFORE Deposit (HARD RULE — fixes wiring errors):
  - Order is ALWAYS: `promotion → deposit → reward`. NEVER `deposit → promotion`.
  - A deposit/bet condition before promotion has nothing to gate — platform rejects or misbehaves.
  - Player must ACCEPT the promotion before any condition gates the reward.
- Fields to IGNORE (pre-calculated by author, NOT wire fields):
  - "Contribution: N" (e.g. 0.1, 0.3, 0.4) — calculation input, not a wire field. Do NOT map to contributionRate or anything. Ignore silently.
  - "Bonus amount: N" standalone derived helpers — author's math check (bet × spins). Take actual bet, spins, max bonus from their own labelled rows; ignore the derived "bonus amount" column.
  - Rule: if it's a derived/check value the author computed, ignore it. Only map primary labelled inputs (bet, spins, min deposit, max bonus, cashout, wager).
- Instant bonus vs wagering bonus (don't over-chain):
  - "Instant Bonus" with Cashout: 1 (release limit 1×) = NO real wagering grind. Single activity, do NOT chain to casino_bonus_v2.
  - Only chain `freespin_bonus → casino_bonus_v2` when there is a REAL wagering requirement (Wager: N with N > 1, or "x30 on winnings" language).
  - Instant bonuses are terminal rewards; wagering bonuses are chained follow-ups.
- The planner NEVER hand-writes journey JSON or a console script (HARD RULE — this is the #1 cause of blank-canvas / non-working drafts):
  - The ONLY renderable output comes from `journey-cloner/compose.py`. A journey body the LLM types by hand will ALWAYS fail: it has `elements: []` (blank canvas — the canvas has no generator, it is copied from a template), invented event names (real freespin completion is `FreespinBonusCollectingFinished`, NOT `FreespinBonusIssued`; sources fire `PlayerAdded`/`Activation`, NOT `Completion`), and a stub `activitiesConfiguration` — every COMPOSER_RULES.md rule is violated at once.
  - When the user asks for "the console script" / "paste script" / "generate the JS", the planner's job ENDS at the MODE 3 spec. Emit the spec block(s) and say: "Run `python journey-cloner/compose.py --spec <file>` to get the renderable console script — I cannot hand-build one that renders." NEVER fabricate a `fetch()` / `journey-drafts` POST script.
- MODE 3 recipe/knob discipline (refuse, never remap):
  - The ONLY valid recipe keys are exactly the keys of the RECIPES CATALOG section of this prompt — read them from there, never from a list written here (a prose copy drifts every time a recipe is captured). `multipurpose_promotion`, `empty_prize`, `instant_bonus`, `choosable_deposit` etc. are NOT recipe keys — emitting them is a hallucination. If no catalog recipe fits, output the ⛔ UNCAPTURED line, do NOT map to the nearest recipe.
  - NEVER map an empty-prize/fallback journey to `comms` — that is ⛔ UNCAPTURED until a matching recipe is captured. NEVER map an instant-bonus (no wagering) journey to `casino_deposit_freespins` with `wagering_x: 1` — that recipe chains a real `casino_bonus_v2` wagering node, which contradicts an instant bonus; use the `casino_instant_freespin` recipe instead.
- MODE 3 spec must preserve blockers (⛔ survives into the machine spec):
  - Any ⛔ UNCAPTURED or ⛔ RESOLVE_AT_BUILD_TIME from the plan MUST appear in the spec as an explicit unresolved field, under a REAL knob name from the catalog, e.g. `"spin_game_lobby": "⛔ RESOLVE_AT_BUILD_TIME"`.
  - The composer REFUSES to build a spec containing any ⛔ value, and REFUSES any recipe not in the proven list. A blocker is never silently dropped or guessed away — it stays visible until a human resolves it.
- Game/provider IDs come from the games registry ONLY (fixes guessed lobby IDs):
  - The registry is the GAMES REGISTRY section of this prompt (source: journey-cloner/library/games_index.md, generated from library/games.json). Match the brief's game name/alias to an entry and use its exact `provider`/`lobbyGameId`/`walletGameId`/`externalGameId`.
  - Never invent a `lobbyGameId`/`provider`. Real IDs are opaque + provider-prefixed (`pragmatic-sweet-bonanza-super-scatter`, wallet `vs20swbonsup`) — unguessable.
  - If the game is not in the registry, flag `⛔ RESOLVE_AT_BUILD_TIME — game "<name>" not in registry` for the game fields — never a plausible-looking guess. Decide membership by looking it up in the GAMES REGISTRY section every time; never from memory or from an example written here.
- "Instant Bonus" IS a `freespin_bonus` with `withWagering: false` (captured — templates/casino/instfs.json):
  - Chain is `external_system_source → promotion → freespin_bonus → end_of_journey` (promotion-gated, no deposit, NO casino_bonus_v2). This is now a captured, renderable pattern — not ⛔.
  - The instant marker is `freespinActivity.withWagering: false` + no wagering follow-up node; cashout/release-limit 1 is expressed by the absence of the wagering chain.
- SUPERSEDES the "game not in registry → ⛔" bullet above (the registry outgrew the prompt):
  - The GAMES REGISTRY section no longer lists games. It is 4,901 games across 48 providers and only the provider counts are inlined, so you CANNOT see whether a title is registered — and "game X is not in the registry" is therefore a claim you are never in a position to make.
  - Put the brief's game NAME, verbatim, in the game field (`spin_game_lobby` in MODE 3, `game` in MODE 5). The composer resolves it against library/games.json by name, alias or id and fills the whole provider/lobby/wallet/external tuple itself. Send ONLY the game field; the other three are derived and anything you put in them is overwritten.
  - A name that does not resolve makes the composer refuse WITH near matches ("did you mean …?"), which tells the operator exactly what to fix. `⛔ RESOLVE_AT_BUILD_TIME` produces a blocker refusal that names nothing and leaves them stuck — so use it in a game field ONLY when the brief names no game at all and one is required.
  - Never let an unrecognised PROVIDER name become a ⛔ either: provider is derived from the game.
- SUPERSEDES "NEVER map an empty-prize/fallback journey to `comms` — that is ⛔ UNCAPTURED" (still right about `comms`, wrong about ⛔):
  - Do not use the `comms` recipe for it — that part stands, and the composer refuses it outright (zero knobs means it reproduces its reference verbatim, live copy and all).
  - But an empty-prize / notify-only / wheel-prize journey is NOT ⛔ UNCAPTURED: MODE 5 builds it from captured nodes. Write the chain you actually want, e.g. `{"name": "...", "source": {"type": "api"}, "chain": [{"type": "nc", ...copy...}], "date": "...", "days": 1}`.
  - ⛔ UNCAPTURED is the last resort — only when an activity type has no captured node at all, so neither a recipe nor a chain can express it.
- Randomizer fields you CANNOT set from a MODE 6 spec (state them in the plan, then tell the operator to fix them by hand):
  - A MODE 6 spec accepts only `kind`, `date`/`dates`, `days`, `weights`, `journeys`, `internal_name`, `url_short`. EVERYTHING else comes from the captured wheel template and ships as captured.
  - That includes `randomizerShotPolicy` (all three templates carry `"Once"`), `playerVisibility` (all three carry `"Authorized"`), `filterConditions` (the captured campaign's audience), `contentId`/`frontId` (the captured campaign's artwork), and `isEmptyPrize`/`isLimitedPrize`/`prizeQuantity` on each slice.
  - So when the brief implies a different value — a repeatable spin ("per deposit", "daily") rather than `Once`, or a public wheel that should be `Unauthorized` — say so with ⚠ AND add: "not settable from the spec; change it in the backoffice after the draft is created." Stating it in MODE 2 prose alone reads as if the build will apply it, and it will not.
  - There is no inherited-content guard on randomizers the way there is on journeys, so nothing will refuse a wheel that still carries the previous campaign's segment and artwork.
- "Max win: N" has no knob and no chain setting (supersedes the `maxWinAmount` mapping above):
  - No recipe knob and no chain setting writes `maxWinAmount`, and it appears in no captured template. Do not emit it in a spec — an invented knob name is refused, and an invented chain setting is refused.
  - The caps that ARE settable are the free-spin ones: `spin_max_bonus_clp` / `spin_min_bonus_clp` (MODE 3, on `casino_instant_freespin` and `casino_deposit_freespins`). If the brief states a max win that is not one of those, flag it ❓ and say it needs setting by hand.
- `spin_campaign_end` exists ONLY on `casino_instant_freespin`:
  - `casino_deposit_freespins` does not define it, so sending it is refused as an unknown knob. When a deposit-gated free-spin campaign states an end date, that is a reason to use MODE 5 (or to accept `fix_dates`' +7-day default and say so with ❓) — not a reason to invent the knob.
