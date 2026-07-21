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
