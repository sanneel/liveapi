# Corrections — operator-taught fixes

One fix per line. These are appended to the planner's system prompt and OVERRIDE
the knowledge base when they conflict. Add a line the moment you learn something.

Three rules about this file itself, because it is paid for on every request:

1. **Never restate a machine-generated fact.** Recipe keys, knob names, game ids,
   activity types and the generator list come from the RECIPES CATALOG, GAMES
   REGISTRY and GENERATORS sections — all generated from the code. A prose copy
   here can only drift, and then the prompt contradicts itself.
2. **A rule the composer enforces gets ONE line, not a paragraph.** If a build is
   refused when the rule is broken, the planner needs to know the rule so it does
   not produce a doomed plan — it does not need the evidence, the capture counts
   or the history that convinced us. Those live in the code comment and in
   `COMPOSER_RULES.md`, which is where someone changing the code will look.
   Everything under ENFORCED below is like this.
3. **Later wins.** Within a section the list is append-only, oldest → newest.

---

## ENFORCED — the composer refuses these, so a plan that breaks one is dead on
arrival. Stated so you do not produce it; not argued, because the code decides.

- **`promotion → deposit`, never the reverse**, wired on `PromotionAccepted`. The
  gate sits between the offer and the reward. If a recipe's declared chain ever
  disagrees, this wins and the recipe is the bug.
- **`freespin_bonus → casino_bonus_v2`**, never reversed, never parallel. Spins
  make the winnings; the bonus wagers them.
- **`withWagering` and the wagering node must agree.** `false` + a
  `casino_bonus_v2` after it, or `true` with none, are both refused. An instant
  bonus is `withWagering: false` and terminal; a real grind is `true` + the node.
- **A delivered message is never wired straight to another send.** Success
  (`NotificationSent` / `SuccessEmailSend` / `SuccessSmsSend`) ⇒ a wait, a split
  or an end. Failure (`NotificationNotSent` / `Failed*`) ⇒ straight to the next
  channel, no wait — that is the fallback. Applies to every send node in every
  journey, not only ones you would call comms.
- **Unknown game ⇒ refused.** Never invent a `lobbyGameId`/`provider`; they are
  opaque and unguessable. Not in the registry ⇒
  `⛔ RESOLVE_AT_BUILD_TIME — game "<name>" not in registry`.
- **Unknown recipe key, unknown chain type, or a setting an activity does not
  have ⇒ refused.** Read the catalog every time; never map to the nearest fit.
- **A ⛔ blocker in a spec ⇒ refused.** So keep it: put it under a real knob name
  (`"spin_game_lobby": "⛔ RESOLVE_AT_BUILD_TIME"`). It is never guessed away.
- **The captured campaign's ids are never reused.** `promotionId`,
  `promotionLinkId`, `campaignId`, `ContentId`, `FrontId` are minted fresh; do not
  pass the reference's back in.
- **Canvas integrity** — a node parented to a container this journey lacks, a
  node with no `position`/`positionAbsolute`, a dangling `nextActivityId`, unstripped
  lineage: all refused. These are library defects the composer repairs, not
  platform rules; never "fix" one by inventing a container.
- **`wait_date` is not composable.** Only `wait_interval` (alias `wait`, ISO-8601).
  An absolute gate date is a `graph` spec against a reference that has one, or ⛔.

## JUDGEMENT — code cannot check these. This is where you actually earn your keep.

- **Read the brief's own labels; ignore its arithmetic.**
  - "Max win: N" → `maxWinAmount` (minor units = N × 100).
  - "Days for wagering" → `bonusExpirationTime` ms (N × 86400000).
  - "Days to make deposit" → `depositConditions.expirationTimeout` = `P0Y0M{N}DT0H0M0S`.
  - "Days to activate bonus" → the activation window (`startAt`/`stopAt`).
  - "Cashout"/limit N → `releaseLimitMultiplier: N`, `limitType: "multiplier"`.
  - "Contribution: N" and a standalone "Bonus amount" are the author's own
    working, not wire fields. Ignore them silently. Only map primary labelled
    inputs (bet, spins, min deposit, max bonus, cashout, wager).
- **Shot policy.** "1 spin per player" / "once during the promo" → `Once`. Tied to
  a repeatable action ("per deposit", "daily") → never `Once`; flag which policy.
- **Player visibility.** A public landing page can be `Unauthorized`; anything
  deposit-gated is `Authorized`. State the page and the flow separately — they
  differ, and one blanket value for the campaign is wrong.
- **Two value tables = two variants.** A brief with separate tables for different
  audiences ("Active" vs "Not active") is N campaigns. Plan all N, or flag
  ⚠ with the count. They differ in tiers, contribution and targeting.
- **A comms journey is never a bare chain of sends.** The repeating unit is
  `send → wait → split → send`: after a channel sends, wait, branch on how the
  player engaged, and chase only the branch that needs it. Set `follow`
  explicitly on every node — a split's real exit is a specific path, and the
  default silently routes to an end. `event_detector` belongs on its own parallel
  flow off the source, never inline where it blocks the sends behind it. One blast
  with no follow-up is `segment → nc` and nothing more; say so with ⚠ rather than
  padding it into four sends. The proven serial shape, if you want the trodden
  path: `segment → nc → wait → ncsplit → popup → wait → sms → wait → email`.
- **The connection grammar is closed.** Only `from → to` pairs the captures
  contain are proven. If the pair you want is not among them you are inventing
  platform behaviour — say ⛔ UNCAPTURED rather than wiring it and hoping. (The
  composer checks that a `follow`/branch event is a captured completion event,
  which catches some of these but not all.)
- **Emit one spec block per object, and count them.** N blocks produce N objects,
  so 3 blocks for a 9-journey plan silently ships a third of the campaign. Open
  with the count ("9 journeys, 9 spec blocks"). If they will not fit, end with
  `⚠ TRUNCATED — emitted X of N; ask "continue specs from N+1"`. Never merge two
  journeys into one block, never abbreviate with `...` or "same as above" — each
  block is parsed literally.
- **Never hand-write journey JSON or a console script.** A body you type has
  `elements: []` (blank canvas), invented event names and a stub
  `activitiesConfiguration`. Your job ends at the spec: emit it and say to run
  `python journey-cloner/compose.py --spec <file>`.
- **The promo page is a separate build.** A fresh `ContentId` names a tree that
  does not exist, so the offer card renders empty. Build the page first
  (Optimization ▸ GOW), then pass its ids as the promotion node's `content_id` /
  `front_id`. Without them the build still succeeds but reports
  `INCOMPLETE — the promo page`; carry that line into your answer rather than
  presenting the draft as finished.
- **A randomizer with its own `urlShortName` needs no promo page** — the wheel URL
  is the landing page.

## THE GENERATORS — finished tools, not things to compose

The GENERATORS section is the complete list. For anything it covers, name the
tool and route the operator to it; do not compose a thinner version.

- **Route, never spec.** A generator has its own form and its own refusals. Give
  the label, the tab, and what it refuses to run without.
- **Welcome Pack** is one draft per run: brand (JBCL/PMCL) and mode
  (normal/boosted) are both required. "Boosted" is the same journey plus the extra
  Sport FreeBet after the deposit detector. There is no "all four at once" — each
  draft inherits its own source's promotion and needs re-pointing before publish.
- **Comms builder** has one variant, `gow`. Tournaments, scratch cards and
  Discount NC have their own tabs which build them more completely; point there.
  Any other chain is still buildable by naming channels directly.
- **An authored email has two captured creatives and they are not
  interchangeable**: one is a heading line above a hero image (the copy lives in
  the image), the other has a text body, a hero and a separate CTA button image.
  Asking for a body on the image-only creative is refused. Both are JBCL — a PMCL
  run authoring one is refused as a brand swap. The CTA is an image, so a brief's
  email button *text* has nowhere to go; say so.
- **Content Studio rejects `*@#?|&<>"'/` in a content name.** Journey names here
  are pipe-separated, so a name derived from one is sanitised — do not promise an
  email content will be named exactly after its journey.
- **A HAR is the input for a new automation, not a thing you can substitute for.**
  No capture ⇒ ⛔ UNCAPTURED. Never propose a template built from documentation.
