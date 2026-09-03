# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Jugabet Odds CRM: a FastAPI admin (`app/`), a set of promo-campaign generators
(`journey-cloner/`), an AI journey planner (`journey-planner/`), and the
player-facing content pages the generators' promos link to
(`journey-cloner/content_pages/`).

## Triggers — when one of these happens, read that file first

| The operator … | Read, then follow |
| --- | --- |
| **sends a `.har`** and wants an automation | **`journey-cloner/HAR_TO_AUTOMATION.md`** — the runbook. Start with `har_analyse.py`; never cat, commit or store the HAR |
| asks what exists / where a script is | `journey-cloner/AUTOMATIONS.md`, and `GENERATORS` in `app/services/promotions_catalog.py` |
| asks about the AI planner's state | `JOURNEY_COMPOSER_STATUS.md` |
| wants a new journey shape composed | `journey-cloner/RECIPE_BUILDING.md`, then `COMPOSER_RULES.md` |
| reports a generator building the wrong thing | `COMPOSER_RULES.md` — most such bugs are a value never written, so the template's own value shipped |
| wants a page the **player** touches (wheel, slot, scratch) | `journey-cloner/content_pages/README.md` — the paste-survival rules and the turn-state contract |
| asks what art a promo needs | `journey-cloner/REA_BACKOFFICE_AND_JOURNEYS.md` §17.7 — the fixed image slots that get replaced every campaign |

## How this system works, in five lines

Generators do **not** call the backoffice from the server: it authenticates with a
short-lived bearer token that only the browser has. So every generator ends at a
**console script the operator pastes into a logged-in backoffice tab**. The
pipeline is always: capture by hand with DevTools → store a template that renders
→ substitute the per-run values → **verify, refusing rather than warning** → emit
the script. `AUTOMATIONS.md` has the detail.

## The admin service, in five more

`app/` is layered `routes/` (one module per admin area) → `services/` (the logic
worth testing) → `repositories/` (all SQLAlchemy access) → `models/`. Three
things no single file tells you:

- **One worker, always** (`uvicorn --workers 1`). The odds parser runs in
  in-process background threads and the PNG cache is process-local, so a second
  worker means duplicate feed fetches, SQLite write contention, and cached PNGs
  that admin actions cannot invalidate across the boundary. Scale vertically;
  move the parser to a sidecar before adding workers.
- **The renderers are separate processes.** `server:app` is port 8000; each
  `render_servers/*.py` is its own uvicorn on 8001–8005 (`launch.txt` has the six
  lines). They drive Playwright to render PNGs/GIFs — which is why `server.py`
  installs a `faulthandler` and a `threading.excepthook`: a dying Playwright
  subprocess otherwise takes uvicorn down with no diagnostic at all.
- **Migrations apply themselves** on startup
  (`server._run_migrations_on_startup`), so no deploy step runs
  `alembic upgrade head` by hand.

## Commands

```bash
# the app (add the five renderers from launch.txt if you need PNG/GIF output)
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload

# admin CSS — admin.tw.css is a COMMITTED build artifact that base.html links
# directly, so a new Tailwind class in a template does nothing until you rebuild
npm run build:css        # app/static/tw-input.css -> app/static/admin.tw.css
npm run watch:css

# operator accounts (there is no user-management page in the admin UI)
.venv/bin/python scripts/new_user.py --role editor NAME  # prints a one-time password
.venv/bin/python scripts/new_user.py --reset NAME        # re-key; KEEPS their current role
.venv/bin/python scripts/create_admin.py --username NAME --role admin  # set a chosen password
```

Roles are ranked `viewer < editor < admin` (`app/auth/dependencies.py`). Almost
every write route is gated at `editor`; only the logs page and tutorials admin
need `admin`.

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
- **One turn per day means one randomizer per day.** The captured wheels carry
  `randomizerShotPolicy: "Once"` — one turn *ever*, not one per day.
  `randomizer_campaign.py --dates D1 D2` already creates a draft per date, and
  each draft's own window (04:02 → 03:58 the next day) is what enforces the daily
  limit server-side. A player-facing page must read every day's slug and never
  decide availability itself.
- **A content page must survive CKEditor.** It is pasted into a rich-text field
  that can escape the whole body, so: no `<` and no `&` anywhere in the script,
  no markup built in JS (`createElement`, never `innerHTML` with tags), no SVG,
  everything scoped and `!important`. The trap sitting on top of that rule —
  **never put `!important` on a property the script writes inline or a keyframe
  animates.** Author `!important` beats both inline styles and animations, so it
  freezes the thing silently while every computed check still passes.
- **HARs are credential dumps.** Scrub on load, never persist the raw file, never
  paste one into a chat or a commit.
- **Drafts only.** Nothing here publishes a live promotion.

## Environment

- Python: **`.venv/bin/python`** (not bare `python`).
- The service is `jugabet.service`; it runs from this working tree, so
  **do not `git checkout` another branch here** — merge into the current one
  instead. Restart with `sudo systemctl restart jugabet`.
- After a restart, `/health` reports `ok:false` for a few minutes while the parser
  feeds refill. That is normal, not a regression.
- Unauthenticated `GET /admin/*` returns **404 by design** (a cloak, see
  `app/auth/dependencies.py`). Test views by calling the function, not over HTTP.

## Tests

There is no pytest — each test is a standalone script, so "run one test" means
running that one file. Offline, no key, safe to run any time:

```bash
.venv/bin/python scripts/test_composer_contract.py   # planner -> composer contract
.venv/bin/python scripts/test_journey_design.py      # design-board renderer (needs pillow)
.venv/bin/python scripts/test_har_analyse.py         # HAR analyser + secret scrubbing
.venv/bin/python -m compileall -q app server.py journey-cloner journey-planner
```

Needs a browser; skips cleanly without one, so run it after editing a page:

```bash
python3 journey-cloner/content_pages/test_giro_ganador_diario.py
```

Needs a live `GEMINI_API_KEY` and spends tokens — run deliberately, before and
after any prompt change:

```bash
.venv/bin/python scripts/eval_planner.py             # scores the planner's plans
```
