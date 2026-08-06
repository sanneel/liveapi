# CLAUDE.md — working in this repo

Jugabet Odds CRM: a FastAPI admin (`app/`) plus a set of promo-campaign
generators (`journey-cloner/`) and an AI journey planner (`journey-planner/`).

## Triggers — when one of these happens, read that file first

| The operator … | Read, then follow |
| --- | --- |
| **sends a `.har`** and wants an automation | **`journey-cloner/HAR_TO_AUTOMATION.md`** — the runbook. Start with `har_analyse.py`; never cat, commit or store the HAR |
| asks what exists / where a script is | `journey-cloner/AUTOMATIONS.md`, and `GENERATORS` in `app/services/promotions_catalog.py` |
| asks about the AI planner's state | `JOURNEY_COMPOSER_STATUS.md` |
| wants a new journey shape composed | `journey-cloner/RECIPE_BUILDING.md`, then `COMPOSER_RULES.md` |
| reports a generator building the wrong thing | `COMPOSER_RULES.md` — most such bugs are a value never written, so the template's own value shipped |

## How this system works, in five lines

Generators do **not** call the backoffice from the server: it authenticates with a
short-lived bearer token that only the browser has. So every generator ends at a
**console script the operator pastes into a logged-in backoffice tab**. The
pipeline is always: capture by hand with DevTools → store a template that renders
→ substitute the per-run values → **verify, refusing rather than warning** → emit
the script. `AUTOMATIONS.md` has the detail.

## Non-negotiables

- **A refusal is the feature.** Every guard here was written after the failure it
  prevents reached a real draft. Never weaken one to make a build pass; fix the
  input. Especially: an unregistered game is never swapped for a near match, and
  content still shared with the captured campaign is never shipped.
- **The template is the source of truth for shape.** Anything not explicitly
  substituted stays as captured — that is how "max bonus 200.000" silently
  shipped as 50.000.
- **Both storages or neither.** A journey lives twice (compiled `activities[]` and
  the `rawJourneyData` editor mirror). Disagreement = blank canvas in the builder.
- **Regenerate every id, per draft.** Shared `activityId`s collide.
- **HARs are credential dumps.** Scrub on load, never persist the raw file, never
  paste one into a chat or a commit.
- **Drafts only.** Nothing here publishes a live promotion.

## Environment

- Python: **`.venv/bin/python`** (not bare `python`) — **but only on the deploy
  server.** A fresh clone (any web session) has no `.venv`; there, use `python3`
  and `pip install` deps on demand. `journey-cloner/har_analyse.py` is pure
  stdlib and runs on either. See `HAR_TO_AUTOMATION.md` Step 0.
- The service is `jugabet.service`; it runs from this working tree, so
  **do not `git checkout` another branch here** — merge into the current one
  instead. Restart with `sudo systemctl restart jugabet`.
- After a restart, `/health` reports `ok:false` for a few minutes while the parser
  feeds refill. That is normal, not a regression.
- Unauthenticated `GET /admin/*` returns **404 by design** (a cloak, see
  `app/auth/dependencies.py`). Test views by calling the function, not over HTTP.

## Tests

Offline, no key, safe to run any time:

```bash
.venv/bin/python scripts/test_composer_contract.py   # planner -> composer contract
.venv/bin/python scripts/test_generators_catalog.py  # what the planner knows about the generators
.venv/bin/python scripts/test_comms_chain.py         # comms chain: languages, links, artwork pickers
.venv/bin/python scripts/test_comms_builder.py       # pick channels + paste sheet -> spec
.venv/bin/python scripts/test_journey_design.py      # design-board renderer
.venv/bin/python scripts/test_har_analyse.py         # HAR analyser + secret scrubbing
.venv/bin/python scripts/test_sport_comms.py         # sport scratch-card comms generator
.venv/bin/python scripts/test_tournament_comms.py    # tournament comms, both brands
.venv/bin/python scripts/test_sport_wof.py           # Sport Wheel of Fortune randomizer
.venv/bin/python -m compileall -q app server.py journey-cloner journey-planner
```

Needs a live `GEMINI_API_KEY` and spends tokens — run deliberately, before and
after any prompt change:

```bash
.venv/bin/python scripts/eval_planner.py             # scores the planner's plans
```
