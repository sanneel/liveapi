# Plan — HAR in, automation out

**Goal:** you do a promo once by hand with DevTools recording, drop the HAR into a
page in the admin, and get back a working generator: it tells you which inputs it
needs, asks for them, and emits the console script. New promo types stop being a
week of my time.

Status: **plan, not built.** Numbers below are measured against the real HAR
already in the repo (`raw_fetches/journey.har`, 5.2 MB, 158 entries) so the
estimates are grounded rather than hopeful.

---

## Why a HAR is the right thing to always hand over

Every generator here was hand-built from a *single* `Copy as fetch` — one request,
no ordering, no dependencies. That is why each took a session: the flow around the
request (reserve an id, copy the content bundles, then POST the draft, then point
the journey at the content) had to be reverse-engineered by reading the network
tab and asking you questions.

A HAR carries the **whole flow**: every request, in order, with responses. That is
exactly the missing information, and it is enough to reconstruct a console script
mechanically.

What that one HAR actually contains:

| | count | what it is |
| --- | --- | --- |
| entries | 158 | everything the tab did |
| GET | 97 | noise — lists, lookups, polling |
| mutating (POST/PUT/PATCH) | 61 | the candidates |
| `contents/v1/copy` | 48 | copying the visual bundle, in a loop |
| `promotion-display-identifier` | 4 | reserving display ids |
| `journeys/identifier` | 1 | reserving the JRN id |
| `journey-drafts` | **1** | the draft POST — the actual payload |
| `…/envelope/` (Sentry) | 7 | analytics noise |
| requests reusing an id from an earlier response | **18 of 61** | the chaining a script must reproduce |

Two things fall out of that table:

1. **The signal is small and findable.** One terminal POST, a couple of id
   reservations, one loop. Filtering GETs and analytics hosts removes 104 of 158
   entries before any cleverness.
2. **Dependency detection works by value matching.** 18 requests contain an id
   that appeared in an earlier *response*. Finding those is a string search, not
   an inference — and it is precisely what the generated script has to wire up.

---

## What you would do

```
1. Record      DevTools ▸ Network ▸ preserve log. Do the promo once, by hand.
               Right-click ▸ Save all as HAR.
2. Drop it     Optimization ▸ New automation ▸ drop the .har
3. Review      "Here is the flow I found: 5 steps, 1 draft POST, 2 reserved ids,
               48 content copies. Here are the 9 values that look per-run.
               Name this automation."
4. Answer      It asks only for what it cannot infer: which values are inputs vs
               fixed, what to call each input, and anything it flagged as unknown.
5. Get it      A generator + template + a form, registered in the optimizer,
               appearing on the Overview like every other automation.
```

Step 3 is the important one: **it tells you what inputs it wants** rather than
making you guess, and step 4 is a form, not a conversation.

---

## What the machine can work out on its own

Already-built pieces do most of it — this plan is mostly wiring, not new science.

| Job | How | Reuses |
| --- | --- | --- |
| Drop the noise | GETs, analytics hosts, 4xx/5xx, static assets | new, ~20 lines |
| Find the payload | the mutating call with the largest JSON body that returns 2xx | new |
| Reconstruct order | HAR entries are timestamped; keep the mutating ones | new |
| Group loops | N calls to one endpoint with bodies differing in one field = a loop | new |
| Find dependencies | a value in request N that appeared in response M (M<N) | new, string search |
| Extract the template | the draft POST body, saved as `templates/<brand>/<name>.json` | `extract_templates.py` |
| Propose the inputs | flatten the body to dotted leaves, keyword-classify operator-tunable vs boilerplate, flag external refs (contentId / CSE / frontId) | **`extract_knobs.py` already does exactly this** |
| Name the activities | reconstruct the graph from `events[].nextActivityId` | `mine_flows.py` |
| Emit the script | token capture → reserve id → POST, with the loop and the dependency wiring | the emitter every generator already shares |

The input-proposal step is the one that sounds hardest and is already written:
`extract_knobs.py` splits a captured activity's fields into `primary` (what an
operator changes), `external_refs` (ids to keep or re-copy) and the rest. Pointing
it at a HAR-derived body instead of a fragment is a small change.

---

## What it must ask you

It cannot know business meaning, so it asks — with its own guess pre-filled:

- **Which per-run values are inputs?** It proposes: anything matching a date, a
  name/title, an amount, a URL, a game id, or copy text. You tick and rename.
- **What is this called, and whose is it?** Automation name, brand (JBCL / PMCL),
  group (Casino / Sport / Comms / …). Goes straight into `GENERATORS`.
- **Which ids are reserved vs reused?** It shows the chain it found
  ("`journeys/identifier` → used in `journey-drafts`") and asks you to confirm,
  because a wrong answer here produces two drafts sharing an id.
- **Anything it flagged unknown.** A value that varies but matches no pattern gets
  listed rather than guessed at. Silence is worse than a question.

---

## Phases

Each phase ends in something usable, not a half-feature.

### Phase 1 — Read-only report *(~1 day)*
`har_analyse.py`: HAR → a JSON report + a page rendering it. No generation.
**Done when:** the existing `journey.har` produces a report naming the draft POST,
both id reservations, the 48-call loop and the 18 dependency links — and you can
read it and say "yes, that is what I did".

### Phase 2 — Replay script *(~1 day)*
Emit a console script that reproduces the captured flow **with the captured
values**. No parameters yet.
**Done when:** pasting it creates the same draft the HAR did (verified in
staging, not asserted).

### Phase 3 — Inputs *(~2 days)*
The review page: proposed inputs, tick/rename, save as an input schema. Generate
the form and substitute at emit time.
**Done when:** changing the date and the game in the form produces a correspondingly
different draft, and `verify()` refuses a nonsense value.

### Phase 4 — First-class automation *(~1 day)*
Write `templates/<brand>/<name>.json`, a generator module from a template, and the
`GENERATORS` entry. It appears on the Overview with a tab like the others.
**Done when:** a HAR you record becomes an automation on the Overview without me
touching the repo.

### Phase 5 — Guards *(ongoing)*
Inherit the protections the composer already has: refuse to emit when content is
still shared with another captured campaign, when a game is unregistered, when an
amount is implausible. These are the reason the existing generators are trustworthy
and a HAR-derived one gets them for free by reusing `verify()`.

---

## Safety — this part is not optional

**A HAR is a credential dump.** The one in the repo contains cookies. HARs
routinely contain bearer tokens, session ids and player PII.

- **Scrub on ingest, before anything is written to disk:** drop `cookies`,
  `Authorization`, `Set-Cookie`, `X-*-Token` headers and any `password` /
  `token` / `secret` field. Keep the scrubbed copy only.
- **Never persist the raw upload.** Parse in memory, write the scrubbed report and
  the extracted template; delete the rest.
- **Cap the upload** (25 MB) and reject anything that is not a HAR.
- **Editor-only**, same as every other generator route.
- **Say what was scrubbed** in the report, so nobody assumes a token survived and
  wonders why the script still asks for one.

The generated script still captures the token from the live page at paste time,
exactly like today. No token is ever stored.

---

## What this will not do

Worth stating so the plan is not oversold:

- **It will not understand the promo.** It reproduces a flow you performed. If you
  did it wrong by hand, it automates doing it wrong.
- **It will not publish anything.** Generators create *drafts*; a human reviews and
  publishes. That does not change.
- **It will not invent a template.** No HAR, no automation — the capture is the
  input, which is the same rule the composer already lives by.
- **A one-off is not worth automating.** If a promo runs once, run the replay
  script from Phase 2 and stop there.

---

## To start Phase 1 I need

1. **A second HAR**, ideally of a promo type not yet automated (Bet & Get came from
   one, so its shape is known — something different would prove the analyser is
   not fitted to a single example).
2. **Which promo you want automated next.** Phase 1 is generic, but I would tune
   the classifier against the flow you actually want.

That is it. The first phase reads a file you already have and writes a report —
nothing in the admin changes until you have read one and agreed it is right.
