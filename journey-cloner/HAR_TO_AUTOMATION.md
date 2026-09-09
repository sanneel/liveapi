# HAR in → automation out — the runbook

**If the operator gave you a `.har` and asked for an automation, follow this file
top to bottom.** It is written for a Claude session with no prior context on this
repo. You do not need to ask what a HAR is for or how the generators work; it is
all here.

The operator's side of the deal is one sentence: *record the promo once by hand
with DevTools ▸ Network ▸ Preserve log, right-click ▸ Save all as HAR, send it.*

---

## Step 0 — Get a Python that runs (do this FIRST, or every command fails)

The rest of this repo's docs say `.venv/bin/python`. **That venv only exists on
the deploy server.** In a fresh clone — which is what a web session gets — there
is no `.venv`, and `.venv/bin/python …` fails with *No such file or directory* on
your very first command. That single wrong path is the most common reason a cold
HAR session "can't get anything to run."

So, before Step 1:

```bash
ls .venv/bin/python 2>/dev/null && PY=.venv/bin/python || PY=python3
$PY -V         # expect 3.11+
```

Use `$PY` everywhere below in place of `.venv/bin/python`.

- **Step 1 (the analyser) needs nothing installed** — `har_analyse.py` is pure
  stdlib. It runs on a bare `python3`. Do the analysis before you worry about
  anything else.
- **The generator** imports a couple of repo helpers (`create_journeys`,
  `comms_campaign`) that pull in `python-dotenv`. **A DB-aware generator** (one
  that reads a liveapi campaign, like `sport_comms`) and **the tests** also need
  the app stack. Install on demand — when an import errors, install exactly what
  it named:

  ```bash
  pip install python-dotenv pillow                     # generator + design test
  pip install fastapi jinja2 sqlalchemy pydantic-settings python-multipart \
              python-jose passlib bcrypt                # only if DB-aware / rendering a tab
  ```

  If `cryptography` panics on import (a prebuilt-wheel/Debian clash you may hit),
  `pip install --force-reinstall --no-cache-dir cffi cryptography` fixes it.

Do not sink time into a full environment up front. Analyse first; install the
moment an import complains, nothing sooner.

---

## Step 0.5 — Read these two things (5 minutes, saves hours)

- `AUTOMATIONS.md` — what already exists. **If the promo is a variant of an
  existing automation, extend that generator instead of writing a new one.**
- `COMPOSER_RULES.md` — the traps that make a journey render or ship a blank
  canvas. Non-negotiable; violating them produces drafts that look created and
  are broken.

---

## Step 1 — Analyse the HAR

```bash
$PY journey-cloner/har_analyse.py <path to .har>
```

It scrubs credentials in memory before anything else (a HAR carries the bearer
token, cookies and sometimes player data — **never** cat a HAR into the chat,
never commit one, and never write the raw file anywhere), then prints:

- **FLOW** — the mutating calls in order, with repeats collapsed into loops and
  the fields that vary across a loop named.
- **PAYLOAD** — the call carrying the object, i.e. your template.
- **DEPENDENCIES** — ids that must flow from one step's response into a later
  step's request. This is the part a "Copy as fetch" never tells you, and the
  reason every generator here was previously hand-built.
- **CANDIDATE INPUTS** — the leaves that look per-run, classified by the same
  code the recipes use, plus the external refs to keep rather than invent.

On the reference HAR in this repo (`raw_fetches/journey.har`, 158 entries) that
report is four steps, one 154 KB payload, three dependency edges and 171
candidate inputs out of 4,804 leaves. Useful flags:

```bash
--json report.json                       # the full report, all inputs
--write-template templates/casino/x.json # save the payload as a template
```

---

## Step 2 — Show the operator the flow and ask the questions only they can answer

Post the FLOW and DEPENDENCIES sections back, then ask — **with your own answer
proposed**, so they are confirming rather than composing:

1. **Is this what you did?** A HAR of a fumbled run automates the fumble. If
   there are failed writes in the report, ask before continuing.
2. **Which candidate inputs are really inputs?** Propose the shortlist. Dates,
   amounts, copy and games almost always are; ids usually are not.
3. **What is it called, whose brand, which group?** (Casino / Sport / Comms /
   Wheels & cards / Assets) — this becomes its registry entry.
4. **Anything the report flagged that you cannot explain.** Ask. A guess here
   ships a wrong campaign.

Do not skip to Step 3 with unanswered questions. Nothing below is expensive to
redo; a wrong template is.

---

## Step 3 — Save the template

```bash
$PY journey-cloner/har_analyse.py run.har \
    --write-template journey-cloner/templates/<brand>/<name>.json
```

**A HAR of a journey usually holds more than one write.** `sport_comms` captured
five: reserve id → **create** draft (`POST /journey-drafts`) → **save** draft
(`PUT /journey-drafts/<id>`) → create email content → save email content. The
create and the save bodies of the same draft **differ** — the create body carries
extra per-activity fields (`isEditable`, `version`, `changedBy`, an
`eventsHistory`), the save body is the normalised one and carries the final
schedule (`startAt`/`stopAt`, `isImmediatelyAfterPublish`). Save **each write**
as its own template, and substitute across **all** of them. A generator that only
templated the create body would ship a draft that never got its final save.

The template is **the source of truth for shape**: everything a generator does not
explicitly substitute stays exactly as captured. Two real bugs came from
forgetting that — a campaign specifying "max bonus 200.000" shipped the
template's 50.000, and a journey granting one game advertised another's name on
its card. If the brief has a value, the generator must write it.

---

## Step 4 — Write the generator

Copy the closest existing generator and keep its shape:

- `nc_discount_campaign.py` — the simplest clone-and-substitute (one journey, a
  handful of string swaps).
- `bet_and_get_pmcl_campaign.py` — a multi-draft flow with content uploads.
- **`sport_comms_campaign.py` — the reference for the hard case**, and the one to
  read if your HAR is a multi-channel comms journey (SMS + notification + pop-up
  + email), takes a liveapi campaign as input, or has copy in two languages. Its
  contract test `scripts/test_sport_comms.py` is the reference for Step 6. Every
  trap listed below was a real bug found while building it.

```python
def prepare(...) -> tuple[dict, list[str]]:   # template(s) + inputs -> bodies, report
def verify(bundle) -> list[tuple[bool, str]]: # every check that must hold
def emit(bundle, name) -> Path                # console_scripts/<name>_console.js
def main() -> int                             # argparse; refuse before emitting
```

### The rules that are not style preferences

- **Regenerate every id, per draft — from the UNION of all bodies.** Two drafts
  sharing an `activityId` collide. Build the old→new id map from *create + save
  together*; a UUID that appears only in the save body must be regenerated too,
  or the two bodies describe different journeys.
- **Wire the dependencies the report found.** Reserve the id, capture it from the
  response at paste time, substitute it into the later request — never hardcode
  the captured one.
- **`verify()` refuses, it does not warn, and it checks that the new value
  LANDED — not merely that the old one is gone.** `audit_inherited_content(body,
  reference)` catches a draft still carrying the captured campaign's copy, but it
  is not enough on its own (see the copy trap below).
- **Never emit on a failed check.** A refusal naming the field beats a draft that
  looks right.
- **The token comes from the browser at paste time.** Copy the capture preamble
  from any existing script; never take a token from the HAR or ask for one.
- **Both storages or neither.** A journey lives twice — compiled `activities[]`
  and the `rawJourneyData` editor mirror. Every substitution must hit both, or
  the builder shows a blank canvas.

### The substitution traps — read before you write a single `.replace()`

Whole-body string replacement is *not* the safe default. It is safe only for a
value that is unambiguous in the serialized body (an id, a slug, a stop date).
For copy it is actively dangerous. These are the traps, each one a shipped bug:

1. **Channel copy must be substituted structurally, by field name — never by
   string replace.** The captured EN and ES slots hold *identical* strings for
   title / description / caption, each value appears 8–16 times (compiled
   activity + `objectForSend.variables` + the mirror), and different channels
   reuse the same literal (the pop-up's caption was the same `"Juega Ya "` as the
   notification's). A global replace therefore writes one language into every
   slot and gives one channel another's copy — while every leftover check passes,
   because the captured literal *is* gone. Address each field by the name the
   template already encodes (`title-en`, `caption_es`, `des-en`,
   `description_es`), in both storages. See `set_channel_copy` / `set_sms_text`.

2. **`displayData` is a hidden second copy of the text.** It is the label the
   builder prints on a node, it duplicates the message, and in the mirror it
   hangs off the config entry itself, not its `data` — so anything that walks
   *settings* misses it. Left alone, the SMS node showed the previous campaign's
   whole message and the email node its name. Rewrite it too (`set_display_data`).

3. **The email BODY copy is a separate leak from the email content id.** Pointing
   the journey at a fresh email content is not enough — the email *html* still
   read "la semifinal Inglaterra vs Argentina" for a different fixture. If the
   brief has body copy, write it into the html; refuse if the sheet lacks it.

4. **A live-data image is the point, not decoration.** `sport_comms`' email
   banner is the liveapi campaign's copy link (`/r/<slug>.png`) with per-player
   tracking (`?…&v={{JourneyActivityId}}&u={{playerID}}`) — it renders live on
   every open. The capture held that slot two ways: a literal placeholder
   (`variable?…`) in one body and the *previous* campaign's real URL in the
   other. Un-replaced, one ships a broken image and the other the wrong card.
   Replace both; keep the tracking query verbatim.

5. **Reusing the captured value is legitimate — test for the wrong value, not the
   captured string.** An operator may deliberately point this run at the same
   promo page the capture used. A check of "the captured slug is absent" then
   refuses a correct build. Assert "no *other* slug survives" instead.

6. **A parallel journey's canvas carries scaffolding nodes.** `dropEdge`,
   `mergeEdge`, `flowEntry` and friends have no `position` and no matching
   activity — that is correct. The COMPOSER_RULES position rule is about
   *activity* nodes only; apply it there, and refuse any canvas node that is
   neither an activity nor known scaffolding.

7. **Create the email content FIRST, then wire its id in.** The recorded run
   created the content but left the journey pointing at the *copied* campaign's
   email — so replaying the capture verbatim emails the wrong template. Reorder:
   create content, capture the returned `CSE-…` id, substitute it into the
   journey. `verify()` refuses while the captured id survives.

### When the input is a liveapi thing, read it from the DB

If a per-run input already exists in liveapi (a campaign, a match), take it from
the database, not from the operator's memory. `sport_comms` reads the campaign
via `CampaignRepository` and derives the email hero from
`settings.public_base_url + /r/<slug>.png`. A refusal when `PUBLIC_BASE_URL` is
unset beats a broken image discovered in an inbox.

---

## Step 5 — Register it

Add an entry to `GENERATORS` in `app/services/promotions_catalog.py`:

```python
{"key": "<slug>", "group": "Casino", "brand": "PMCL",
 "label": "<what the operator calls it>",
 "what": "<one line: what it builds>",
 "script": "<file>.py", "tab": None},     # or "tab": "<tab>" / "route": "/admin/x"
```

`unlisted_generators()` warns in the admin about any generator script the registry
does not name, so this step is enforced. Add the prose to `AUTOMATIONS.md` in the
same commit — the registry says *what*, that file says *how*.

A tab is optional and often unnecessary: shell-only is fine for something that
runs monthly. Ask before building UI. **If you do build a tab**, four edits wire
it — copy them from the `sport_comms` commits:

1. **Runner** — a `generate_<key>_console_script(...)` in
   `app/services/journey_cloner_runner.py` that shells the generator (`--spec -`
   pipes a pasted sheet over stdin so it never touches disk) and returns
   `(exit_code, output, display_cmd, js_text, basename)`.
2. **Route + namespace** — a `POST /admin/promotions/<key>` handler in
   `app/routes/admin_views.py`, a `_<key>_ns(...)` context builder, the key added
   to `_PROMO_TABS`, and the namespace threaded through `_promotions_context`.
3. **Panel** — a `<section data-panel="<key>">` in `promotions.html` (or a
   `partials/_<key>_form.html`) with the input form. For the "here is your
   script" half, **include the shared component** — do not hand-roll a copy
   button:
   ```jinja
   {% with console_script=<ns>.console_script,
           steps=["tab-specific note"], final_step="what success looks like" %}
     {% include "partials/_console_script.html" %}
   {% endwith %}
   ```
4. **Tab button** — a `<button data-tab="<key>">` in the tab bar.

A refusal (non-zero exit) should render the run output and **no copy button** —
there is nothing to paste when the build was rejected.

---

## Step 6 — Prove it, then hand it over

1. `$PY -m compileall -q journey-cloner app` — no syntax errors.
2. `$PY scripts/test_har_analyse.py` — the analyser still holds.
3. **Write a contract test** modelled on `scripts/test_sport_comms.py`, and run
   it. A "diff the body against the template" check alone is not enough — it
   passes while shipping copy in the wrong language (that value *is* a change you
   meant, just misplaced). The reference test also:
   - reads each channel's copy back out **per node and per language** and asserts
     it equals what the sheet said (this is what catches trap #1);
   - asserts EN ≠ ES where they should differ, and that one channel is not
     wearing another's copy;
   - checks the mirror agrees with the compiled activity;
   - feeds `verify()` a body that breaks **exactly one** rule and asserts it
     refuses — one such case per guard.
4. **Run it end-to-end through the real path**, not just the unit test: build a
   throwaway DB row (or use a real one), call the runner the tab calls, and grep
   the emitted `.js` for any captured literal that should be gone. Trap #1 and #2
   survived four commits and every offline check — they only surfaced on a real
   run. Do this before you claim it works.
5. Tell the operator what to paste, and say plainly what you did *not* verify —
   **no draft has been created from here; the paste is the only real test.** They
   paste; they confirm.

---

## What this procedure will not do

State these plainly rather than discover them later:

- **It does not understand the promo.** It reproduces a flow. A mistake in the
  recording becomes a mistake in the automation.
- **It never publishes.** Generators create drafts; a human reviews and publishes.
- **No HAR, no automation.** The capture is the input. Do not invent a template
  from documentation or from another brand's file.
- **A one-off is not worth automating.** If the promo runs once, produce the
  console script for this run and stop.

---

## If you get stuck

| Symptom | Cause | Fix |
| --- | --- | --- |
| `.venv/bin/python: No such file` | fresh clone has no venv | Step 0 — use `python3`, install on demand |
| `ModuleNotFoundError` mid-run | the import named its own fix | `pip install` exactly that module (Step 0 has the list) |
| `cryptography` panics on import | prebuilt-wheel/Debian clash | `pip install --force-reinstall --no-cache-dir cffi cryptography` |
| Report shows no payload | the HAR missed the creating POST | ask for a recording with Preserve log on, from before the first click |
| Draft created but canvas blank | the two storages disagree | substitute in both; see `COMPOSER_RULES.md` |
| Two drafts share ids | ids not regenerated, or map built from one body | regenerate from the **union** of create + save |
| Draft looks right but ships wrong-language copy | copy string-replaced, not substituted by field | trap #1 — `set_channel_copy`; test per-language |
| Node label shows the old campaign | `displayData` not rewritten | trap #2 — `set_display_data` |
| Email names the wrong fixture | body copy or content id not replaced | traps #3 / #7 |
| Email image broken or wrong | banner `img src` placeholder/stale URL left | trap #4 — replace both, keep the tracking query |
| `verify()` refuses a correct build | it tests for the captured string, not the wrong one | trap #5 — assert "no *other* value survives" |
| `verify()` fails on inherited content | a value still matches the template | that is correct — set the value, do not weaken the check |
| Position check refuses a real journey | it ran on scaffolding nodes | trap #6 — activity nodes only |
| Unknown game refused | not in `library/games.json` | `build_games_registry.py`, or ask which registered game to use. **Never substitute a near match** |

---

## Where the pieces are

| | |
| --- | --- |
| `har_analyse.py` | HAR → flow, payload, dependencies, candidate inputs |
| `scripts/test_har_analyse.py` | its contract: secrets never survive, flow read correctly |
| **`sport_comms_campaign.py`** | **the reference build for the hard case — every trap above lives here** |
| **`scripts/test_sport_comms.py`** | **the reference contract test (per-language copy, one-broken-rule refusals)** |
| `partials/_console_script.html` | the shared "copy & paste" card every tab includes |
| `extract_templates.py` | single `Copy as fetch` → template (pre-HAR path) |
| `extract_knobs.py` | the input classifier `har_analyse` reuses |
| `mine_flows.py` | activity graphs across all captured templates |
| `compose.py` / `journey_composer.py` | the composer, when a recipe fits better than a clone |
| `AUTOMATIONS.md` | every existing automation and how it works |
| `../JOURNEY_COMPOSER_STATUS.md` | where the AI planner stands |
