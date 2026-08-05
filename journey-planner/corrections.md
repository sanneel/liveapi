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
  - The deposit gate sits between the offer and the reward — `promotion → deposit → (reward)` — so it is before the REWARD but after the PROMOTION. See rule #1 below; that ordering is not negotiable.
  - "Casino FreeSpin + Wagering + Deposit" chain: `external_system_source → promotion → deposit → freespin_bonus → casino_bonus_v2 → end`.
- RULE #1 — PROMOTION IS NEVER LATER THAN DEPOSIT (the single most important wiring rule; overrides anything above that appears to say otherwise):
  - Order is ALWAYS `promotion → deposit → reward`, wired on `PromotionAccepted`. NEVER `deposit → promotion`.
  - The player must ACCEPT the offer before a condition can gate its reward. A deposit/bet condition placed first has nothing to gate — the platform rejects it or misbehaves.
  - This is not a stylistic preference and there is no flow that reverses it. Evidence: across the five captures carrying both nodes (`casino/gow.json`, `casino/multipurpose_spinladder.json`, `pmcl_betandget/journey.json`, `udch/two_hours.json`, `colocolo/followup.json`) there are 13 `promotion → deposit` edges, every one on `PromotionAccepted`, and ZERO `deposit → promotion`.
  - The composer now REFUSES any body containing a `deposit → promotion` edge, including one reached through a split path. If a plan produces that edge it is a bug in the plan, not something to force through. Do not try to satisfy the refusal by deleting the deposit gate — reorder it.
  - Historical note so it is not reintroduced: the `casino_deposit_freespins` recipe itself shipped with the chain reversed and built every draft gate-first, while this file simultaneously stated the correct order. Both are fixed. If a recipe's declared chain and this rule ever disagree again, THIS RULE WINS and the recipe is the bug.
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
- THIS APPLIES TO EVERY SEND NODE, IN EVERY JOURNEY — not only to journeys you would call "comms" (learned from a real run: a reward journey ending `... -> freebet -> nc -> email` sailed past the comms rule below because the planner read it as a reward journey, and the two channels fired together at everyone). A `notification_center`, `dextra_sms` or `dextra_email` anywhere in any chain obeys the send rules. The composer now REFUSES a delivered message wired straight to another send, so this is a failed build, not a style note.
- A COMMS JOURNEY IS NEVER A BARE CHAIN OF SENDS (HARD RULE — this is the #1 cause of useless comms plans):
  - WRONG, and what was being produced: `segment → nc → popup → sms → email`. Four sends back to back fire the whole set at once, nobody is ever measured, and every player gets every channel however they behaved. No captured journey looks like this.
  - The repeating unit is **`send → wait → split → send`**. After a channel sends you WAIT, then you branch on how the player engaged, and only the branch that needs chasing gets the next channel.
  - Evidence — every captured comms journey, without exception: `casino/gow_comms.json` (3 waits, 2 nc splits, 1 email split, 1 detector), `tournament/tournament_comms_create.json` (2 wait_date + 1 wait_interval, 2 nc splits), `casino/tournament_pmcl_comms.json` (same), `sportcomms/scratch_card_comms_create.json` (3 waits, 1 nc split, 2 decision splits, 1 detector). A comms plan with zero waits and zero splits contradicts all four.
  - The proven serial shape (from tournament_comms_create, verified to compose):
    `segment → nc [NotificationSent] → wait → ncsplit [NCEngagementSplitPassedPath05] → popup [NotificationSent] → wait → sms [SuccessSmsSend] → wait → email`
  - Set `follow` on EVERY node in a comms chain. The default happy event is not the one you want on a split — a split's real exit is a specific path (the captures take `NCEngagementSplitPassedPath05` off an NC split and `Path2` off an email split), and picking the default silently routes the journey to an end.
  - `event_detector` (conversion: did they deposit / play) belongs on its OWN parallel flow off the source, never inline in the send chain — both gow_comms and scratch_card_comms put it on Flow 1 with the messaging on Flow 2. Inline, it blocks the sends behind it. Use `"parallel": [[...detector...], [...sends...]]` on the source-adjacent node.
  - `wait_date` is NOT composable — `chain_types` has only `wait_interval` (alias `wait`, ISO-8601 via the `wait` setting). A brief that needs an absolute gate date is either a MODE 4 clone of a template that already has `wait_date`, or ⛔ RESOLVE_AT_BUILD_TIME. Never emit `wait_date` in a MODE 5 chain — it is rejected as an unknown type.
  - THE PRECISE RULE, measured over all 18 captures — the SUCCESS branch and the FAILURE branch of a send behave differently, and this is the part that was being got wrong:
    - A **delivered** message (`NotificationSent`, `SuccessEmailSend`, `SuccessSmsSend`) is followed by a wait, a split, or an end. It is followed by another send **ZERO times in 18 journeys**. If you have chained send → send on a success event, it is wrong.
    - A **failed** message (`NotificationNotSent`, `FailedEmailSend`, `FailedSmsSend`) goes STRAIGHT to the next channel, with no wait — 7 occurrences (`nc→nc` ×4, `nc→email` ×2, `email→sms` ×1). That is the fallback: it never landed, so try another channel immediately. Do not insert a wait on a failure branch.
    - So the shape is: success ⇒ wait/split; failure ⇒ immediate next channel.
  - Minimum bar before emitting any comms plan: every success branch leads to a wait or a split, and there is at least one engagement split. If the brief genuinely wants one blast with no follow-up, say so with ⚠ rather than silently producing a bare chain — a single-send journey is `segment → nc` and nothing more (that is what nc_discount is), not four sends in a row.
  - The most common comms edges in the captures, if you want the well-trodden path: `nc → wait_interval` (18×, 8 files), `wait_interval → nc_engagement_split` (8×, 7 files), `nc_engagement_split → nc` (24×, 6 files), `dwh_source → nc` (6×, 6 files), `dwh_source → event_detector` (3×, 3 files, its own flow).
- "Specs for EVERY object" means EVERY object — emit one block per journey, and count them (fixes "the script only covered some of the journeys"):
  - The build button asks for "the spec JSON for every object in the plan above — one ```json block each". The composer builds exactly the blocks it finds: N blocks in the reply produce N objects in the script, so a reply carrying 3 blocks for a 9-journey plan silently ships a third of the campaign, and the operator only discovers it after pasting.
  - Before finishing that reply, COUNT the journeys in the plan and COUNT the blocks you emitted. They must be equal. Open with the count ("9 journeys, 9 spec blocks below") so the mismatch is visible to both of us.
  - If the objects will not fit in one reply, do NOT quietly emit fewer. Emit as many complete blocks as fit, then end with the explicit line `⚠ TRUNCATED — emitted X of N; ask "continue specs from N+1" for the rest`. A half-campaign labelled as a whole one is the failure; a half-campaign labelled honestly is fine.
  - Never merge two journeys into one block to save room, and never abbreviate a block with `...` or "same as above" — the composer parses each block literally and cannot expand a reference to another one.
- A NEW CAMPAIGN NEVER SHARES THE CAPTURED CAMPAIGN'S PROMOTION OR CONTENT TREE:
  - A cloned promotion node arrives carrying the reference's `promotionId`, `promotionLinkId`, `campaignId` and its promo-page `ContentId` + `FrontId`. Those are not copies — they are the SAME server-side objects. The draft hangs off the captured campaign's promotion, and editing its promo-page content REWRITES that live campaign's page. It is the Sport WOF bug exactly: every wheel shared one `contentId`, so editing this week's artwork rewrote every published wheel.
  - The composer now mints a fresh uuid for each of those five ids on the spec, graph and chain paths, consistently across both storages, and `verify()` still refuses anything that slips through. You do not need to ask for this and you must not pass the reference's ids back in.
  - The audit that catches leaked COPY does not catch these, and that is why it went unnoticed for so long: `_is_content()` only accepts uppercase-leading tokens (it was built for message text and `CSE-*` ids), so a lowercase uuid sails straight through it.
  - THE PROMO PAGE IS A SEPARATE BUILD — say so, and wire it. A fresh `ContentId` names a content tree that does not exist yet, so the offer card renders EMPTY. Cloning that tree is not one call: `gow_campaign.py` copies it per target folder (`spa`, `widget`, `cashier`, `widgetModulor`) with role-specific `fileFilters` that depend on the item content ids, plus a separate S3 copy and manifest rewrites. The composer has no promo-page capture and must not fake one.
    - So the correct sequence for a casino promo journey is: build the promo page first (`gow_campaign.py`, Optimization ▸ GOW), then pass ITS ids into the journey as the promotion node's `content_id` / `front_id` settings. Those settings now exist for exactly this.
    - Given them, the journey points at real content and nothing is minted. Omit them and the build still succeeds but reports `INCOMPLETE — the promo page`; carry that line into your answer rather than presenting the draft as finished.
    - Those two ids live in THREE places that must agree — `initializationData.placements[].data.ContentId/FrontId`, `config.properties.placements[].data...` (a SIBLING of `config.data`, not inside it) and `config.metadata.contentId/frontId` in camelCase. The composer writes all three; never hand-patch one.
  - The bare-clone path (`compose.py <recipe>` with no spec) deliberately still shares — reproducing one captured campaign verbatim is what it is for.
- THE CONNECTION GRAMMAR IS CLOSED — 80 distinct `from → to` pairs exist across the 18 captures, and nothing else is proven (fixes invented wiring):
  - If the pair you want is not one the captures contain, you are inventing platform behaviour. Say ⛔ UNCAPTURED instead of wiring it and hoping. The authoritative machine-readable list is the connection grammar in the prompt's generated sections; the fixed orderings below are the ones worth memorising because getting them wrong produces a draft that looks right and misbehaves.
  - `promotion → deposit` on `PromotionAccepted`: 17×, 5 files. Reverse: 0×. (Rule #1.)
  - `deposit → reward` on `DepositConditionSatisfied`: `→ freebet` 9×, `→ casino_bonus_v2` 4×, `→ freespin_bonus` 4×. The gate sits between the offer and the reward.
  - `freespin_bonus → casino_bonus_v2` on `FreespinBonusCollectingFinished`: 4×. Never reversed, never parallel — the spins make winnings, the bonus wagers them.
  - `multipurpose_promotion → promotion` on `PromotionAccepted`: 11×, 3 files. A choosable-flow wrapper feeds REAL promotion nodes; it is not itself the offer.
  - `event_detector → promotion` on `DetectorSuccess`: 3×. A detector gates an offer on a platform event; it does not sit inline in a send chain.
  - `freebet → campaign_connector` on `PlayerFreebetUsed`: 10×. `freebet → notification_center` on `FreebetIssued`: 6× (issue and notify are different events — do not use one for the other).
- DATA HEALTH OF THE CAPTURED LIBRARY (know these so you do not mistake a library defect for a platform rule):
  - 14 of the 23 activity types the composer loads have an element carrying a `parentNode` pointing at a `parallelFlow` container that is NOT emitted, because the node was cut out of one. Left in, the builder renders a grey/blank canvas. The composer now strips it on layout and `verify()` refuses any that survive. Never "fix" this by inventing a container.
  - The 4 split types load with far fewer canvas path ports than they have completion events (`ams_decision_split` 1 port/21 events, `notification_center_engagement_split` 1/5, `email_engagement_split` 1/6, `random_split` 2/10), because the capture only kept the ports it had wired. A split's handle is named `path<N>`/`other`, NOT after the event, so the composer now derives the handle and mints the missing port. This is why branching past path 1 used to silently vanish from the canvas.
  - `end_of_journey` has no captured canvas node at all; the composer synthesises exits itself. That is expected, not a gap to report.
  - `library/fragments/*.json` is a GENERATED inspection artifact (`extract_fragments.py`) that the composer does not read — it loads elements straight from the templates in `SOURCES`. Never reason about composer behaviour from the fragments directory.
