# Corrections — operator-taught fixes

One fix per line, newest at the bottom. Format each as: the wrong assumption →
the right rule. These are appended to the planner's system prompt and OVERRIDE
the knowledge base when they conflict. Add a line the moment you learn something
— no need to restructure the main KB.

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
  - The ONLY valid recipes are the 3 in the catalog: `comms`, `sport_deposit_freebet`, `casino_deposit_freespins`. `multipurpose_promotion`, `empty_prize`, `instant_bonus`, `choosable_deposit` etc. are NOT recipes — emitting them is a hallucination. If no recipe fits, output the ⛔ UNCAPTURED line, do NOT map to the nearest recipe.
  - NEVER map an empty-prize/fallback journey to `comms`. NEVER map an instant-bonus (no wagering) journey to `casino_deposit_freespins` with `wagering_x: 1` — that recipe chains a real `casino_bonus_v2` wagering node, which contradicts an instant bonus. Both are ⛔ UNCAPTURED until a matching recipe is captured.
- MODE 3 spec must preserve blockers (⛔ survives into the machine spec):
  - Any ⛔ UNCAPTURED or ⛔ RESOLVE_AT_BUILD_TIME from the plan MUST appear in the spec as an explicit unresolved field, e.g. `"spin_game_id": "⛔ RESOLVE_AT_BUILD_TIME"`.
  - The composer REFUSES to build a spec containing any ⛔ value, and REFUSES any recipe not in the proven list. A blocker is never silently dropped or guessed away — it stays visible until a human resolves it.
- Game/provider IDs come from the games registry ONLY (fixes guessed lobby IDs):
  - The registry is the GAMES REGISTRY section of this prompt (source: journey-cloner/library/games.json). Match the brief's game name/alias to an entry and use its exact `provider`/`lobbyGameId`/`walletGameId`/`externalGameId`.
  - Never invent a `lobbyGameId`/`provider`. Real IDs are opaque + provider-prefixed (`pragmatic-sweet-bonanza-super-scatter`, wallet `vs20swbonsup`) — unguessable.
  - If the game is not in the registry, flag `⛔ RESOLVE_AT_BUILD_TIME — game "<name>" not in registry` for the game fields — never a plausible-looking guess. (e.g. "Big Bass Bonanza 1000" is NOT in the registry yet; "Sweet Bonanza Super Scatter" IS.)
- "Instant Bonus" IS a `freespin_bonus` with `withWagering: false` (captured — templates/casino/instfs.json):
  - Chain is `external_system_source → promotion → freespin_bonus → end_of_journey` (promotion-gated, no deposit, NO casino_bonus_v2). This is now a captured, renderable pattern — not ⛔.
  - The instant marker is `freespinActivity.withWagering: false` + no wagering follow-up node; cashout/release-limit 1 is expressed by the absence of the wagering chain.
