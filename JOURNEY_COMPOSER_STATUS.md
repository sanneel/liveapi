# Journey Composer System — Project Status & Implementation Guide

**Last Updated:** 2026-07-29  
**Branch:** `claude/ai-planner-chain-composer`  
**Status: BETA — trust the builder, verify the plan.** The pipeline runs end to
end from the admin (brief → plan → design boards → console scripts → drafts in
the backoffice), and the composer's refusals are reliable. The *planning* step is
probabilistic and still makes domain mistakes, so no plan should reach production
without an operator reading its flags. See **Phase** below for what that means
concretely and what is left.

---

## What This System Does

Converts a campaign **brief** → AI **outline** → AI **spec JSON** → **working journey draft** that renders in the backoffice.

> **Building a new recipe?** See `journey-cloner/RECIPE_BUILDING.md` — the step-by-step
> guide (and a reusable prompt) for turning a captured journey into a composable recipe.

### Recent additions (2026-07-21)
- **Spec validator** (`compose.py::validate_spec`) — refuses unknown recipes and any
  ⛔/RESOLVE_AT_BUILD_TIME blocker before building.
- **Games registry** (`library/games.json`, 106 games) — planner resolves a brief's game
  NAME → real ids; unknown games flagged ⛔. Refresh live with
  `console_scripts/fetch_games_catalog_console.js`; rebuild from HAR with
  `build_games_registry.py`.
- **Captured templates** (not yet recipes): `templates/casino/instfs.json` (instant
  freespin, renders) and `templates/casino/multipurpose_spinladder.json` (choosable
  ladder, 74 nodes).
- Model → `gemini-2.5-flash-lite`; planner UI hardened against no-text responses.

```
Human Brief
    ↓
Planner LLM (MODE 1 → MODE 2 → MODE 3)
    ↓
Spec JSON (recipe + knobs)
    ↓
compose.py (assembler engine)
    ↓
Console Script (token capture + POST)
    ↓
Backoffice (paste + renders ✅)
```

---

---

## Phase: where the AI actually is (2026-07-29)

The system has two halves and they are at different maturities. Conflating them
is how "can I trust it?" gets the wrong answer.

### The builder — dependable
Deterministic, and it refuses rather than guesses. Measured behaviour:

| Guard | Refuses when |
| --- | --- |
| games registry | a game is not in `library/games.json` (4,901 games) — with near matches |
| knob validation | a spec uses a knob the recipe does not define, or omits a required one |
| recipe fit | the recipe cannot express the journey (no game knob, a deposit gate it does not want) |
| inherited content | the built journey still shares copy, artwork, links or an email template with its reference |
| game swaps | a repair round tried to substitute a near-match game for an unregistered one |
| wheel slices | the prize count does not match a captured template (4 / 5 / 6) |
| implausible values | amounts nobody meant (a 0-spin bonus, a bet outside the sane range) |

Every one of these was written after the failure it prevents reached a real
draft. **This half is worth relying on**: it will not silently ship something
wrong, and when it refuses, the message names the field and the fix.

### The planner — assistive, not autonomous
Scored by `scripts/eval_planner.py` (a fixed brief set, mechanical checks):

```
closing_line      ██████████ 100%     grouped           ██████████ 100%
design_block      ██████████ 100%     mode1_shape       ██████████ 100%
flags_terse       ██████████ 100%     no_false_blockers ██████████ 100%
no_invented       ██████████ 100%     wheel_fits        ████████·· 75%
OVERALL 98%  (was 85% before the 2026-07-29 changes)
```

Those checks cover **format and internal consistency**. Nothing verifies that a
plan matches what the brief *meant* — that judgement is the operator's. Real
mistakes seen while building this: a 31-slice wheel, six invented "(Fallback)"
journeys, a ⛔ claiming a registered game was missing, and a run that dropped the
brief's deposit ladder entirely.

**The working contract:** read the ⚠ / ❓ / ⛔ flags and the design boards before
pressing Full script. Almost every problem was visible there.

### What moved on 2026-07-29
- Thinking was **off** (`gemini_thinking_budget: 0`) to save cost. Measured: the
  saving was imaginary — without it the model wrote 10,950 tokens of wrong answer
  instead of 8,189 thought + 2,946 of right answer, 0.5% total difference. Now on.
- Planning runs on `gemini-2.5-flash`, mechanical repairs on flash-lite with the
  lean prompt and a 1024 thinking budget (−58% billed output, same result).
- A truncated reply continues itself; `planner_max_tokens` 4096 → 16384. At the
  old cap a 30-journey plan died mid-JSON and every later step had nothing.
- Design boards, and near-identical journeys fold onto one board by shape.
- Journeys **and the wheel** in one paste (`compose.py --batch`).
- Token usage is reported per reply and totalled in the AI page.

### What is left, in the order I would do it

1. **Games registry gaps.** `Bone Fortune` (TaDa) and `3x5 Double Blazing`
   (Gamzix) are absent — those providers are not in the registry at all. Any
   campaign naming them cannot be built. Refresh with
   `build_games_registry.py`; needs a backoffice catalog capture.
2. **`wheel_fits` at 75%.** One run stated no prize count at all, so a reviewer
   could not tell whether the wheel was buildable. Should be 100%.
3. **The eval stops at MODE 1.** Nothing scores the steps after planning: does
   "give specs" then "full script" produce journeys that match the brief? That is
   the gap between 98% on format and confidence in the output.
4. **A 7-slice wheel.** Six prizes plus an empty slice is a shape no captured
   template has. Real campaigns ask for it.
5. **Email content beyond the template id.** A comms journey can point at an
   email content, but the copy inside it is still created by hand.
6. **Recipes that cannot carry a game.** `casino_deposit_freespins` has no game
   knob, so a deposit+freespins brief is pushed to MODE 5 chains via a repair
   round. Adding the knob would remove a whole class of refusal-and-retry.

### Cost, for reference
A full workflow (plan → boards → specs → script) is roughly 5–7 model calls.
Input is ~23K tokens per call but Gemini's implicit cache hits it hard (measured
`cached 23,515 of 23,528` on a repeat), so output dominates. The AI page shows a
running total; watch the cached percentage — if it drops, inputs get expensive.

---

## What's Complete (Shipped)

### 1. **Planner with LLM Modes** ✅
- **MODE 1:** Outline skeleton (one line per object)
- **MODE 2:** Full detail (user says "journey 1 in full")
- **MODE 3:** Machine spec JSON (user says "generate json")
- Integrated into backoffice chat at `/admin/planner`
- Cost-optimized: thinking tokens disabled (85% cost reduction)

**Files:**
- `journey-planner/system_prompt.txt` (includes MODE 3 spec grammar)
- `journey-planner/planner.py` (CLI version)
- `app/routes/admin_planner.py` (backoffice endpoint)
- `app/config.py` (gemini_thinking_budget: 0)

### 2. **Recipe Catalog** ✅
3 proven recipes, each with named knobs for the LLM to emit:

| Recipe | Chain | Proven | Knobs |
|--------|-------|--------|-------|
| `comms` | segment → notif → SMS → email | ✅ Renders | 0 (template as-is) |
| `sport_deposit_freebet` | registration → deposit → promo → freebet | ✅ Renders | 5 (deposit, freebet, promocode) |
| `casino_deposit_freespins` | api → deposit → promo → freespins → wagering | ✅ Renders | 7 (deposit, spins, bet, bonus, wager, expiry, limit) |

**Files:**
- `journey-cloner/compose.py` (Recipe definitions, lines 70–153)
- `journey-cloner/recipes_catalog.json` (LLM-facing index)

### 3. **Composer Engine** ✅
Takes MODE 3 spec → builds verified journey draft.

**Core features:**
- Assembles activity chain from ONE reference template (rule: no schema mixing)
- De-nests reward nodes from containers (strips `parentNode`, `extent`, `pathes`, etc.)
- Regenerates UUIDs consistently (global string-replace keeps ports/handles/edges in sync)
- Auto-fixes dates (stopAt in past → 7 days out; startAt in past → now)
- Validates canvas dual-storage (activities[] + rawJourneyData must match)
- Emits console script with proven token-capture harness

**Files:**
- `journey-cloner/compose.py` (main engine, ~600 lines)
- `journey-cloner/console_scripts/` (3 generated scripts, ready to paste)

### 4. **Knowledge Base & Library** ✅
21 activity types captured, 22 documented, 200+ tunable paths.

**Files:**
- `journey-planner/REA_KNOWLEDGE_BASE.md` (activity semantics, wire names, rules)
- `journey-planner/REA_CAPTURE_BACKLOG_CHECKLIST.md` (what's captured vs. uncaptured)
- `journey-planner/corrections.md` (operator-taught fixes, highest precedence)
- `journey-cloner/library/knobs.json` (tunable paths per activity, per reference journey)
- `journey-cloner/COMPOSER_RULES.md` (7 canvas synthesis rules, proven via live render)

### 5. **Console Scripts (Ready to Paste)** ✅
3 proven scripts, each embeds a full verified journey body:

```
journey-cloner/console_scripts/
├── composed_comms_console.js
├── composed_sport_deposit_freebet_console.js
└── composed_casino_deposit_freespins_console.js
```

Each script:
- Captures auth token automatically (waits for UI click)
- Reserves a journey ID from the backoffice
- Freshens all UUIDs
- POSTs the draft body
- Prints success message with journey ID

**How to use:**
```
1. Open backoffice, press F12 (console)
2. Paste script content, press Enter
3. Click anywhere in the UI (token capture)
4. Wait for green "DRAFT CREATED" message
5. Search for new JRN-xxxxx in Journey Builder
6. Open draft → canvas renders ✅
```

### 6. **Verified Render Cycles** ✅
Both sport and casino recipes proven to render + save in the backoffice editor.

- Sport draft (2026-07-20): 5 nodes, all wired, no blank canvas
- Casino draft (2026-07-20): 6 nodes (including de-nested rewards), all wired, no blank canvas

---

## What's Pending

The UI integration this section used to describe has shipped: the AI page
(`/admin/ai`) runs brief → plan → boards → **Full script** → drafts, with
`POST /admin/planner/api`, `/design` and `/compose` behind it. For the current
list of what is genuinely outstanding, see **Phase → What is left** above.

---

## How to Test It Today

### **CLI Workflow (fully working)**

```bash
cd /home/user/liveapi

# 1. Get MODE 3 spec from planner
# (via the AI page at /admin/ai, or use the test spec below)

# 2. Create a brief.json file
cat > /tmp/test_brief.json <<'EOF'
{
  "recipe": "sport_deposit_freebet",
  "journey_name": "JBCL | Test Sport 27.07",
  "knobs": {
    "deposit_min_clp": 2500,
    "freebet_amount_clp": 1000,
    "freebet_expire_days": 1,
    "freebet_max_odd": 5,
    "promocode": "VAMOSBULLA"
  }
}
EOF

# 3. Compose
python journey-cloner/compose.py sport_deposit_freebet

# 4. Console script ready at:
cat journey-cloner/console_scripts/composed_sport_deposit_freebet_console.js

# 5. Paste into backoffice console (F12) + click to capture token
# 6. Draft renders in editor ✅
```

### **Backoffice Chat (partially working)**

1. Navigate to `/admin/planner` in logged-in backoffice
2. Paste a campaign brief (e.g., "I need a casino campaign: deposit $10, get 50 FS, 3-day wager")
3. See MODE 1 outline
4. Ask "change X" for revisions (MODE 1 updated)
5. Say "generate json"
6. Get MODE 3 spec JSON back
7. Run `compose.py --spec <spec>` locally to get console script

---

## Technical Architecture

### **Dual-Storage Rule (Footgun #1)**
Every journey stored TWICE and both must agree:
- `activities[]` (runtime) — the journey engine reads this
- `rawJourneyData` (editor mirror) — the visual builder reads this

Canvas (`rawJourneyData.elements`) has NO generator — always copied from template.

### **Recipe + Reference Journey Model**
Each recipe is bound to ONE reference journey that renders:
- Recipes define the chain of activities (`registration → deposit → ...`)
- Reference journey supplies the shape (every node, event, config, visual layout)
- Composer de-nests reward nodes from container journeys (strips `parentNode`, `extent`)

### **Knob Variance Per Reference**
Same activity has different internal paths in different references:
- `freebet.freeBetAmount.CLP` in colocolo
- `freebet.freeBetAmount.CLP` in two_hours
- Named knob → `freebet_amount_clp` (stable for LLM)
- Mapped to dotted path per recipe's reference journey

### **Brief-Invisible Rules**
Applied by the planner even when brief doesn't mention them:
- Empty-prize journey (every randomizer needs weight=0 outcome)
- Notify-only limited prize (wheels with 50%+ prizes)
- Player visibility: public → `Unauthorized`, logged-in → `Authorized`
- Start immediately after publish: `isImmediatelyAfterPublish: true`

---

## File Structure

```
liveapi/
├── app/
│   ├── config.py                       # gemini_thinking_budget: 0
│   ├── routes/admin_planner.py         # /admin/planner endpoint
│   └── templates/planner/index.html    # UI (needs compose button)
│
├── journey-planner/
│   ├── system_prompt.txt               # LLM instructions + MODE 3 grammar
│   ├── planner.py                      # CLI version (same logic)
│   ├── REA_KNOWLEDGE_BASE.md           # Activity semantics (21 types)
│   ├── REA_CAPTURE_BACKLOG_CHECKLIST.md # What's captured vs. uncaptured
│   └── corrections.md                  # Operator-taught fixes
│
├── journey-cloner/
│   ├── compose.py                      # Assembler engine (main logic)
│   ├── COMPOSER_RULES.md               # 7 canvas synthesis rules
│   ├── library/
│   │   └── knobs.json                  # Tunable paths per activity (200+)
│   ├── recipes_catalog.json            # Recipe index for LLM
│   ├── console_scripts/
│   │   ├── composed_comms_console.js
│   │   ├── composed_sport_deposit_freebet_console.js
│   │   └── composed_casino_deposit_freespins_console.js
│   └── templates/                      # Reference journeys (captured HARs)
│       ├── casino/
│       │   └── gow.json                # Casino multi-reward template
│       └── udch/
│           └── two_hours.json          # Sport deposit+freebet template
│
└── JOURNEY_COMPOSER_STATUS.md          # This file
```

---

## Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| **Recipes** | 3 | Proven to render; ready for 4+ more |
| **Activity types captured** | 21 | 72% of platform coverage |
| **Tunable knob paths** | 200+ | Per-activity, per-reference variance |
| **Cost per LLM call** | ~$0.02 | Thinking tokens disabled |
| **Console script size** | ~3–4 KB | Embeds full journey body + harness |
| **Render success rate** | 100% | Both recipes rendered without blank canvas |
| **Time to add 1 recipe** | 2 hours | Capture → template → knobs → recipe → test |
| **Time to ship UI integration** | 2 hours | Button + endpoint + download flow |

---

## Known Limitations & Gaps

### **Cannot Generate (Uncaptured)**
- Sport Wagering Bonus
- Money Bonus, Coins Bonus
- Native push, Web push, WhatsApp
- Bet Insurance, Cashback variants

**How to fix:** Capture one in backoffice → extract as template fragment → add to knobs → create recipe (2 hours per type).

### **Knob Paths Are Per-Reference**
If brief mentions a freebet but uses a reference journey where freebet has a different internal path:
- Planner doesn't know this
- `apply_values()` logs `MISS` and moves on gracefully
- Draft still renders, but knob didn't apply

**How to avoid:** Keep reference journeys focused (one per recipe type).

### **Canvas Nodes Have No Generator**
`rawJourneyData.elements` (canvas layout) is always copied from template, never synthesized.
- Pro: 100% correctness (no blank-canvas bugs)
- Con: Can't yet compose arbitrary node layouts

**Future:** If recipes get very diverse, may need manual canvas templates per recipe.

---

## Next Steps (Priority Order)

1. **UI Integration** (2 hours)
   - Add "Generate journey spec" button in `/admin/planner`
   - Add `POST /admin/planner/compose` endpoint
   - Display console script, allow copy/download

2. **Sport Wagering Bonus** (2 hours capture + recipe)
   - Build in backoffice
   - Extract template fragment
   - Add knobs.json entry
   - Create recipe, test

3. **Money Bonus** (2 hours)
   - Same process as Sport Bonus

4. **Randomizer + Promo Page** (future, optional)
   - Currently only journeys are automated
   - Can extend to wheels + landing pages

---

## For New Chat Session

Copy this path to provide context:
```
/home/user/liveapi/JOURNEY_COMPOSER_STATUS.md
```

Key files to review:
- `journey-cloner/compose.py` — core engine
- `journey-planner/system_prompt.txt` — LLM modes
- `KNOWLEDGE_BASE_SUMMARY.md` — activity catalog & knobs

Quick test:
```bash
python journey-cloner/compose.py sport_deposit_freebet
# Outputs console script ready to paste
```

---

## Contact / Questions

All system knowledge is in:
- `REA_KNOWLEDGE_BASE.md` — the platform rules
- `COMPOSER_RULES.md` — the canvas rules
- Code comments in `compose.py` — the engine logic

System is stable and ready for production UI integration.
