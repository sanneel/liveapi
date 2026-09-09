# Script Runner — the paste step, as a button

A Chrome extension that runs a generated promo console script in a logged-in REA
backoffice tab. It replaces this:

> Click **Copy script** → open the backoffice → F12 → Console → type
> `allow pasting` → paste 650 KB → squint at the console for the JRN ids

with this:

> Click **Run in backoffice** in the CRM → click **Run** in the extension popup →
> read the log and the created JRN ids in the popup

Nothing about how the scripts are built changes. The generators, the templates,
the verification and the refusals are all untouched, and **Copy script** is still
there — it is the fallback whenever a run misbehaves.

---

## What it does not change

- **Verification still happens in Python, before the script exists.** The
  extension never builds a payload and never decides anything about one. A
  script that a generator refused to emit cannot be run, because there is
  nothing to run.
- **Drafts only.** The extension has no opinion about what the script does; it
  runs what the generator produced.
- **A refusal still reads as a refusal.** Every `console.log` the script makes is
  streamed into the popup verbatim, and a script that throws leaves the run
  marked `failed` with the error. A run that stopped early must look stopped.

The one thing it does change is spelled out below, because it is the whole
mechanism: it fills in the `MANUAL_TOKEN` knob the scripts already expose.

---

## Install

Not on the Web Store, and not intended for it — it runs script text produced by
your own server, which is remote code by Chrome's definition. Load it unpacked,
or force-install it by enterprise policy.

1. `chrome://extensions` → **Developer mode** on → **Load unpacked** → pick this
   `extension/` directory.
2. Open the extension's **Settings** (from the popup, or the Details page) and
   add the CRM admin origin — e.g. `https://crm.example.com/*`. Chrome will ask
   for permission; the button only appears on origins you allow. The local
   defaults (`http://127.0.0.1:8000/*`, `http://localhost:8000/*`) are listed but
   still need allowing once.
3. Reload the CRM tab. **Run in backoffice** now sits next to every
   **Copy script**.

The backoffice host (`*.rea-backoffice.gr8.tech`) is in the manifest already —
that one is not deployment-specific.

## Use

1. Generate a script in the CRM as usual (Optimization ▸ whichever tab, or the
   AI page).
2. **Run in backoffice**. The toolbar icon shows how many scripts are queued.
3. Make sure a logged-in backoffice tab is open, then open the popup and press
   **Run**.
4. Watch the log. Created `JRN-…` ids are pulled out and shown as chips.

If there is no backoffice tab open, the run is refused and the script stays
queued — open the tab, log in, press Run again.

---

## How it works

### The token

Every generated script needs the backoffice's short-lived bearer token, and
today it gets one by monkeypatching `window.fetch` and waiting for the page to
make a request — hence "Waiting for a token… click anything in the backoffice UI".

An extension does not need that trick. `chrome.webRequest.onBeforeSendHeaders`
reads the `Authorization` header off the backoffice's *own* traffic, passively,
with nothing injected into the page. The extension validates it exactly the way
the scripts do (`typ` must be `Bearer`, and it must have more than
`MIN_TOKEN_TTL_S` left — stricter than the scripts' 30s, because a run that
reserves JRN ids and then 401s halfway leaves orphan drafts behind) and seeds it
into the script.

That seed is **the only edit made to a generated script**, and it is deliberately
brittle:

```js
const MANUAL_TOKEN = '';        // <- exactly this line, exactly once
```

Exact string, single occurrence, or no edit at all. If a generator ever
reformats that line, the extension seeds nothing, the script falls back to its
own capture, and the operator sees the old "click anything" message — degraded,
never wrong. `scripts/test_script_runner.py` asserts the string is identical on
both sides of the Python/JS boundary so it cannot drift silently.

### Running it

`chrome.debugger` → `Runtime.evaluate`, which is what the DevTools console does.
The alternatives were all worse:

| Approach | Why not |
| --- | --- |
| ISOLATED-world content script | Cannot patch the page's `window.fetch`, so token capture breaks for the 6 scripts that have no `MANUAL_TOKEN` knob |
| MAIN-world injection of a dynamic string | Needs `eval`, which the page CSP may forbid — and we would find out in production |
| `fetch` from an extension page | Requests become third-party, so a `SameSite` session cookie silently stops being sent, and all 54 scripts send `credentials: 'include'` |

`Runtime.evaluate` gives the same context, the same cookies and the same
semantics as the paste it replaces, and `allowUnsafeEvalBlockedByCSP` settles the
CSP question outright. The cost is Chrome's "started debugging this browser" bar,
which disappears when the run detaches.

### State

One run at a time, on purpose: these scripts reserve JRN ids and POST drafts, and
two concurrent runs are how you get *"activities with the same identifier already
exist"*.

The queue lives in `chrome.storage.session`, not in the service worker's memory —
an MV3 worker is torn down after ~30s idle, and "clicked Run, opened the popup a
minute later, queue was empty" is exactly the papercut this exists to remove.
`session` rather than `local` because a queued job is a rendered draft payload: it
belongs in memory for the browser session, never on disk.

---

## Files

| File | Role |
| --- | --- |
| `manifest.json` | MV3 manifest. Backoffice host is static; CRM origins are optional and granted per deployment |
| `background.js` | Token capture, queue, and the run itself |
| `content.js` / `content.css` | Adds the Run button to the CRM's script cards |
| `popup.html` / `.js` / `.css` | Token status, queue, live log, created JRN ids |
| `options.html` / `.js` | CRM origins, and the permission prompt for each |
| `registration.js` | Registers the content script for granted origins only |
| `config.js` | Shared constants and the token validation shared with the scripts |
| `console_format.js` | CDP console args → a readable line (`%c` styling and all) |

`content.js` cannot import `config.js` — MV3 content scripts are not modules — so
the two constants it needs are repeated there. Both places say so.

---

## Tests

The Python side guards the cross-language contract and the manifest:

```bash
.venv/bin/python scripts/test_script_runner.py
```

The JS behaviour tests are browser pages, because there is no JS runtime on the
deploy box:

```bash
python3 extension/tests/serve.py
```

Open the URLs it prints. Every line on every page must read `OK`. They cover the
button finding the admin's real card markup (including htmx-inserted cards), the
token validation, seeding leaving all 54 emitted scripts parseable, every
generator's JS template holding the knob exactly once, and `%c` console lines
coming back out readable.

---

## Known rough edges

- **The "being debugged" bar.** Unavoidable with `Runtime.evaluate`, and the
  honest tradeoff for running the script exactly as a paste would. It clears on
  detach.
- **`fetch_games_catalog_console.js` has no `MANUAL_TOKEN` knob.** It is
  hand-written rather than generated, so it still waits for a token. It runs
  fine; you just have to click something in the backoffice once.
- **Remote code.** The script text comes from the CRM at run time. Fine for an
  internal, force-installed extension; a blocker for Web Store distribution. If
  that ever matters, the fix is to ship payloads plus a static runner instead of
  JS — a much bigger change, because `gow_combined` and `prediction` have bespoke
  multi-step flows.
