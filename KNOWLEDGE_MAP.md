# Knowledge map — which document is authoritative for what

Roughly twenty markdown files describe this system, four of them carry an
activity catalogue, and until you know which one the AI actually reads, "it's in
the docs" is not an answer. This file is the map. It says, per document, what it
is the source of truth for, what it is *not*, and whether the planner LLM sees
it.

`CLAUDE.md` stays the entry point for a working session — it routes you by task.
This routes you by *fact*.

---

## The five files the AI reads

These, and only these, are assembled into the planner's system prompt on every
request (`app/routes/admin_planner.py::_build_system_prompt`, mirrored exactly by
`journey-planner/planner.py`). Nothing else in this repo reaches the model. There
is no retrieval step: all five are inlined whole, ~23K tokens, every call.

| # | file | authoritative for | generated? |
| --- | --- | --- | --- |
| 1 | `journey-planner/system_prompt.txt` | the response modes, output shapes, and the rules of engagement | no |
| 2 | `journey-planner/REA_KNOWLEDGE_BASE.md` | the platform's mental model: subsystems, activity palette, reward field names, brief-invisible rules, what a randomizer spec can and cannot set | no |
| 3 | `journey-planner/REA_CAPTURE_BACKLOG_CHECKLIST.md` | *why* a thing is or is not captured, and what to capture next | no |
| 4 | `journey-cloner/recipes_catalog.json` | **the build surface** — recipe keys, knob names, units, ranges; the chain palette and its inline settings; wheel kinds and prize counts | **yes** (`compose.py --catalog`) |
| 5 | `journey-cloner/library/games_index.md` | provider counts only — the 4,901 titles are NOT inlined | **yes** (`build_games_registry.py`) |
| + | `journey-planner/corrections.md` | operator-taught fixes; **highest precedence of all** | no |

### Precedence, when two of them disagree

```
corrections.md  >  recipes_catalog.json / games_index.md  >  REA_KNOWLEDGE_BASE.md
                                                          >  REA_CAPTURE_BACKLOG_CHECKLIST.md
```

The generated files cannot drift from the code — they are produced from it. The
hand-written ones can and have. `corrections.md` beats everything because it is
where an operator records something learned after the fact; inside that file the
list is append-only and a **later bullet beats an earlier one**, so a correction
is superseded by appending, never by editing.

Two rules that follow from this, and both have been violated in practice:

- **Never restate a generated fact as prose.** Recipe keys, knob names, chain
  settings, game ids and wheel prize counts belong in the catalog, and a prose
  copy anywhere else is a future contradiction. `corrections.md` says this about
  itself, and has broken it twice.
- **A hand-written doc that contradicts the catalog is stale, not a veto.** Four
  activity types sat marked "uncaptured — must refuse" in the knowledge base and
  the backlog while the composer was happily building them.

---

## What the AI does *not* read

Everything below is for humans and for coding sessions. Grounding a plan or a
spec in any of it is how a spec ends up using vocabulary the composer has never
heard of.

### Reference — how the platform works

| file | source of truth for | explicitly NOT for |
| --- | --- | --- |
| `journey-cloner/REA_BACKOFFICE_AND_JOURNEYS.md` (952 l) | the narrative "why": why cloning is hard, which fields the platform treats as unique, how errors read | the build surface — its activity list is descriptive, not a menu |
| `journey-cloner/REA_BACKOFFICE_DB.md` (367 l) | the lookup table companion to the above: exact field names per activity, channel, segment, endpoint | the same caveat; where the two overlap this one is the quick reference, the other is the reasoning |
| `journey-planner/REA_BUILD_MECHANICS.md` (274 l) | how a journey is actually POSTed: dual storage, the activity envelope, ID classes, build order, endpoints, the debugging playbook, the visual layer. **Holds §§2–4, 8, 13–16 of the knowledge base** — which is why that file's numbering jumps | anything the planner needs; it was split out precisely because the model never acts on it |

### Process — how to build things

| file | source of truth for |
| --- | --- |
| `journey-cloner/AUTOMATIONS.md` | every automation, how it works, and the end-to-end AI flow. The registry it describes lives in code: `app/services/promotions_catalog.py::GENERATORS` |
| `journey-cloner/COMPOSER_RULES.md` | the canvas rules a composed journey must satisfy to render. Scoped: rule 2 governs the recipe engine, not the chain engine |
| `journey-cloner/RECIPE_BUILDING.md` | turning a captured journey into a `compose.py` recipe, step by step |
| `journey-cloner/HAR_TO_AUTOMATION.md` | the runbook for HAR → new automation. Start at `har_analyse.py`; never cat, commit or paste a HAR |
| `JOURNEY_COMPOSER_STATUS.md` | where the AI stands and what is left — status and roadmap, not reference |

### Operational

| file | source of truth for |
| --- | --- |
| `CLAUDE.md` | task routing + the non-negotiables |
| `README.md`, `DEPLOY.md`, `deploy/STAGING_RUNBOOK.md` | running and deploying the service |
| `CHANGELOG.md` | what changed when |
| `journey-cloner/README.md` | the cloner CLI |
| `journey-planner/icons/README.md` | overriding a design-board icon (the folder is empty on purpose — the renderer draws built-in glyphs) |
| `journey-cloner/email_cards/README.md` | the reveal-card / GIF assets |

---

## Two things that look like sources of truth and are not

- **`journey-cloner/catalog.json`** — built by `build_catalog.py`, read by the
  Optimization overview graph. Different file and different purpose from
  `recipes_catalog.json`, and its `recipes` key is a different concept again:
  prose flow patterns ("free spins after a deposit"), not composer recipe keys.
  Nothing in the AI prompt reads it.
- **`plan_lint.py` + `ai_campaign_builder.py`** — a dormant earlier design with
  its own flow-DSL, its own aliases (`NC1`, `NC5`, `SMS`) and its own recipe
  names, validated against `catalog.json`. Nothing calls either one.
  `ai_campaign_builder.py` still describes itself as "the single entry point an
  agent uses"; it is not. The live path is the one in `AUTOMATIONS.md`.

---

## Keeping this true

The failure mode this map exists to prevent is a doc that describes behaviour
the code does not have — every audit finding so far has been one. Three habits
hold the line:

1. **Regenerate, don't retype.** After touching `RECIPES`, `SETTINGS_DOC`,
   `ALIASES`, `HAPPY` or a wheel template, run `python journey-cloner/compose.py
   --catalog` and confirm all four sections survived (`recipes`, `references`,
   `chain_composer`, `randomizer`). Both palette builders swallow import errors
   and return `{}`, so a missing dependency silently produces a *smaller*
   catalog — and `scripts/test_composer_contract.py` will then bless it.
2. **When a capture lands, update three places**, per the backlog's own §G.7: the
   wire-name row in the knowledge base, any new brief-invisible rule (§11), and
   the error mapping in `REA_BUILD_MECHANICS.md`.
3. **When you learn something mid-campaign, append to `corrections.md`** rather
   than restructuring the knowledge base. That is what the file is for, and the
   append-only rule is what makes it safe to do in a hurry.
