# HAR in → automation out — the runbook

**If the operator gave you a `.har` and asked for an automation, follow this file
top to bottom.** It is written for a Claude session with no prior context on this
repo. You do not need to ask what a HAR is for or how the generators work; it is
all here.

The operator's side of the deal is one sentence: *record the promo once by hand
with DevTools ▸ Network ▸ Preserve log, right-click ▸ Save all as HAR, send it.*

---

## Step 0 — Read these two things first (5 minutes, saves hours)

- `AUTOMATIONS.md` — what already exists. **If the promo is a variant of an
  existing automation, extend that generator instead of writing a new one.**
- `COMPOSER_RULES.md` — the traps that make a journey render or ship a blank
  canvas. Non-negotiable; violating them produces drafts that look created and
  are broken.

---

## Step 1 — Analyse the HAR

```bash
.venv/bin/python journey-cloner/har_analyse.py <path to .har>
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
.venv/bin/python journey-cloner/har_analyse.py run.har \
    --write-template journey-cloner/templates/<brand>/<name>.json
```

The template is **the source of truth for shape**: everything a generator does not
explicitly substitute stays exactly as captured. Two real bugs came from
forgetting that — a campaign specifying "max bonus 200.000" shipped the
template's 50.000, and a journey granting one game advertised another's name on
its card. If the brief has a value, the generator must write it.

---

## Step 4 — Write the generator

Copy the closest existing generator and keep its shape. `nc_discount_campaign.py`
is the simplest clone-and-substitute; `bet_and_get_pmcl_campaign.py` is the
reference for a multi-draft flow with content uploads.

```python
def prepare(...) -> tuple[dict, list[str]]:   # template + inputs -> body, report
def verify(body) -> list[tuple[bool, str]]:   # every check that must hold
def emit(body, name) -> Path                  # console_scripts/<name>_console.js
def main() -> int                             # argparse; refuse before emitting
```

Rules that are not style preferences:

- **Regenerate every id, per draft.** Two drafts sharing an `activityId` collide.
- **Substitute in BOTH storages.** A journey is stored twice — compiled
  `activities[]` and the `rawJourneyData` editor mirror. If they disagree the
  builder shows a blank canvas. String replacement across the whole body is the
  safe way when the value is unambiguous (see `nc_discount_campaign.py`).
- **Wire the dependencies the report found.** Reserve the id, capture it from the
  response, substitute it into the later request — do not hardcode the captured
  one.
- **`verify()` refuses, it does not warn.** Reuse what exists:
  `compose.audit_inherited_content(body, reference)` catches a draft still
  carrying the captured campaign's copy, links, artwork or email template. That
  check exists because a "Physical Prize" journey once shipped with the Game of
  the Week's SMS and email.
- **Never emit on a failed check.** A refusal naming the field beats a draft that
  looks right.
- **The token comes from the browser at paste time.** Copy the capture preamble
  from any existing script; never take a token from the HAR or ask for one.

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
runs monthly. Ask before building UI.

---

## Step 6 — Prove it, then hand it over

1. `.venv/bin/python -m compileall -q journey-cloner app` — no syntax errors.
2. `.venv/bin/python scripts/test_har_analyse.py` — the analyser still holds.
3. Run the generator with the captured values and **diff the body against the
   template**: only the fields you meant to change may differ. This is the check
   that catches the silent class of bug.
4. Tell the operator what to paste, and say plainly what you did *not* verify —
   you cannot create a real draft from here. They paste; they confirm.

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
| Report shows no payload | the HAR missed the creating POST | ask for a recording with Preserve log on, from before the first click |
| Draft created but canvas blank | the two storages disagree | substitute in both; see `COMPOSER_RULES.md` |
| Two drafts share ids | ids not regenerated per draft | regenerate inside the per-draft loop |
| `verify()` fails on inherited content | a value still matches the template | that is correct — set the value, do not weaken the check |
| Unknown game refused | not in `library/games.json` | `build_games_registry.py`, or ask which registered game to use. **Never substitute a near match** |

---

## Where the pieces are

| | |
| --- | --- |
| `har_analyse.py` | HAR → flow, payload, dependencies, candidate inputs |
| `scripts/test_har_analyse.py` | its contract: secrets never survive, flow read correctly |
| `extract_templates.py` | single `Copy as fetch` → template (pre-HAR path) |
| `extract_knobs.py` | the input classifier `har_analyse` reuses |
| `mine_flows.py` | activity graphs across all captured templates |
| `compose.py` / `journey_composer.py` | the composer, when a recipe fits better than a clone |
| `AUTOMATIONS.md` | every existing automation and how it works |
| `../JOURNEY_COMPOSER_STATUS.md` | where the AI planner stands |
