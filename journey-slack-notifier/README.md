# Journey → Slack notifier

Polls the "Journey Funnel Dashboard" (workbook **Journey Flow Report**) on the
Tableau Server, detects journeys whose status field has flipped to "finished",
and posts a summary + CSV export of that journey to a Slack channel. Runs on the
VPS on a cron schedule.

---

## Corrections applied during setup (2026-08-13)

This README differs from the original draft in the following ways. Each was
verified against the live server, not assumed:

| # | Original said | Reality |
|---|---|---|
| 1 | Check `GET {server}/api/-/serverinfo` | That path returns a **JSON 404** on our server. Use a versioned path: `/api/3.27/serverinfo` |
| 2 | `TABLEAU_API_VERSION=3.20` | Server reports `restApiVersion` **3.27** (product 2025.3.5). 3.20 also answers, but 3.27 is correct |
| 3 | `--dry-run`, then run for real | Inserted a mandatory **`--seed-state`** step. Without it the first real run posts every journey that already finished inside the view's date window, in one burst |
| 4 | `cd /home/youruser/journey-slack-notifier` | Our app lives at `/var/www/jugabet`, runs as user `jugabet`, per `DEPLOY.md` |
| 5 | `>> state/cron.log 2>&1` | The script already writes `state/notifier.log` and also logs to stdout, so this stores every line twice. Send stdout to `/dev/null`, keep stderr |
| 6 | "underlying data" | The REST endpoint used returns the view's **summary** data (aggregated marks), not row-level underlying data. See [Known risk](#known-risk-summary-vs-underlying-data) |

Also fixed in `journey_slack_notifier.py`: duplicate Slack posts after a
mid-run failure, a silent no-op on a mistyped column name, and `--list-columns`
hiding the column names when the view returns zero data rows. See
[Script changes](#script-changes).

---

## Why polling, not a live event

Tableau Server doesn't emit a real-time event for a business condition like
"this specific journey just finished" — its native Webhooks fire on platform
events (e.g. workbook refresh succeeded), not on values inside the data. So the
practical way to detect "journey finished" is to periodically re-pull the
dashboard's data and check a status field yourself. A state file
(`state/sent_journeys.json`) tracks which journey IDs have already been sent, so
re-running doesn't spam Slack with duplicates.

## 1. Tableau Personal Access Token

The script authenticates with a Personal Access Token (PAT) rather than a
username/password, so it doesn't depend on a login session and keeps working
after a password change.

1. In Tableau Server, click your profile icon (top right) → **My Account Settings**.
2. Scroll to **Personal Access Tokens** → name it (e.g. `journey-slack-notifier`) → **Create new token**.
3. **Copy the token secret immediately** — Tableau shows it only once.
4. Put the name and secret into `.env` as `TABLEAU_PAT_NAME` / `TABLEAU_PAT_SECRET`.

If there's no "Personal Access Tokens" section, ask the Tableau admin to enable
PATs for the site (server setting, off by default on some installs).

Already confirmed for our server, no action needed:

* `TABLEAU_SERVER_URL=https://tableau.euc1.prod-analytics.aws.tech-ops.cloud` — reachable, responds `x-tableau: Tableau Server`
* `TABLEAU_API_VERSION=3.27`

Still to confirm:

* `TABLEAU_SITE_CONTENT_URL` — only needed if the dashboard is on a named site.
  Browse to the dashboard; if the URL has a `/site/<name>/` segment, that's the value. No segment → leave blank.

## 2. Choose a delivery target

`NOTIFY_TARGET` in `.env` selects where journeys are announced:

| Value | Behaviour |
|---|---|
| `telegram` | **Current default.** Reuses the main app's bot (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` from `../.env`, see `app/config.py`). Nothing extra to set up |
| `slack` | Needs a real `xoxb-` bot token, see below |
| `both` | Posts to each; a failure on either aborts that journey so the next run retries it |

Telegram needs no new credentials — the script falls back to `../.env` so the bot
token lives in one place. **It is only configured on the VPS**, though: this
repo has no `.env` on a dev machine, so a real send can only be tested there.

The summary and CSV are delivered as a single `sendDocument` call with the
summary as its HTML caption. Journey names are HTML-escaped, so a journey called
`Winback <b>50%</b>` can't break the message markup.

## 2b. Slack Bot

A plain Incoming Webhook can only post text, not attach a CSV, so this needs a
small Slack App with a bot token:

1. https://api.slack.com/apps → **Create New App** → **From scratch**.
2. Name it (e.g. "Journey Notifier"), pick the workspace.
3. **OAuth & Permissions** → **Bot Token Scopes**, add:
   * `chat:write`
   * `files:write`
4. **Install App to Workspace** → approve.
5. Copy the **Bot User OAuth Token** (`xoxb-...`) into `.env` as `SLACK_BOT_TOKEN`.
6. In Slack, invite the bot to the target channel: `/invite @Journey Notifier`.
   **Required** — `files_upload_v2` fails if the bot isn't a channel member.
7. Channel ID: open the channel → **View channel details** → ID (`C...`) at the
   bottom → `.env` as `SLACK_CHANNEL_ID`.

## 3. Find the real column names

Tableau's exported headers don't always match the filter labels in the dashboard
UI, so confirm them:

```bash
venv/bin/python journey_slack_notifier.py --list-columns
```

Find the column representing completion status and the value it holds when a
journey is done, then set in `.env`:

```
JOURNEY_ID_FIELD=<the real id column>
JOURNEY_NAME_FIELD=<the real name column>
JOURNEY_STATUS_FIELD=<the real status column>
JOURNEY_FINISHED_VALUE=<value meaning finished, e.g. Finished / Completed / Y>
```

The script now **refuses to run** if any of these names isn't present in the
export, and prints the actual column list. That's deliberate: a mistyped name
previously meant every run exited 0 having detected nothing.

If nobody's sure which field marks completion, ask whoever owns the dashboard
(the report owner is shown on the dashboard itself).

## 4. Install

On the VPS, as the `jugabet` user:

```bash
cd /var/www/jugabet/journey-slack-notifier
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
nano .env          # fill in the PAT + Slack values from steps 1-3
```

The notifier gets its **own** venv rather than reusing the service's `.venv`, so
installing `slack_sdk` can't disturb the running `jugabet.service` dependency
set.

## 5. First run, in this order

The order matters — step 3 is what stops a backlog dumping into Slack.

```bash
# 1. Confirm the column names are right.
venv/bin/python journey_slack_notifier.py --list-columns

# 2. Confirm detection works. Posts nothing, writes no state.
venv/bin/python journey_slack_notifier.py --dry-run

# 3. MANDATORY ONCE: record everything already finished as "sent",
#    without posting. Skip this and every journey that finished inside
#    the view's date window is posted to Slack at once.
venv/bin/python journey_slack_notifier.py --seed-state

# 4. Live. Only journeys finishing from now on are notified.
venv/bin/python journey_slack_notifier.py
```

To verify end-to-end delivery without waiting for a real journey, temporarily
remove one known-finished id from `state/sent_journeys.json` and run again — it
will re-post that one journey, proving the Slack path works.

## 6. Schedule it

As the `jugabet` user (`crontab -e`, not root's — state file and log ownership
depend on it). Every 15 minutes; match this to how often the dashboard's data
actually refreshes, since polling faster than the data changes achieves nothing:

```cron
*/15 * * * * cd /var/www/jugabet/journey-slack-notifier && venv/bin/python journey_slack_notifier.py >/dev/null 2>>/var/log/jugabet/journey-notifier-error.log
```

`>/dev/null` because the script already writes `state/notifier.log`; without it
every line is stored twice. `2>>` still captures tracebacks.

## Known risk: summary vs underlying data

`GET /sites/{site}/views/{view}/data` returns the view's **summary** data — the
aggregated marks in the viz — not row-level underlying data, despite what the
original draft implied. If the funnel dashboard aggregates away the per-journey
status column, that column will not appear in the export and no `.env` change
will fix it.

`--list-columns` is the test. If there's no per-journey status column in the
output, the options are:

1. Have the dashboard owner expose the status field in the view, or
2. Point the script at the underlying data source / database directly — more
   reliable long-term than parsing a dashboard export anyway.

## Other limitations

* The endpoint respects the view's **current default filter state** (e.g. a
  "Last 5 weeks" date filter). A journey that finished outside that window won't
  appear. Widening it means changing the view's default filters.
* Large views can hit row limits on this endpoint and truncate. Narrowing the
  fields, or filtering server-side with `?vf_<FieldName>=<value>`, keeps the
  payload manageable.
* Two workbooks with the same name in different projects → the script picks the
  first arbitrarily.
* `state/sent_journeys.json` is not covered by the repo `.gitignore`. Not a
  secret, but it will show up as an untracked file.

## Script changes

Beyond the README corrections, `journey_slack_notifier.py` was changed to fix
three behaviours, each reproduced with a stubbed Tableau + Slack before and
after the fix:

* **Duplicate posts after a mid-run failure.** `save_sent_ids()` ran only after
  the whole loop, so a Slack 429 on the 3rd journey discarded the record of the
  1st and 2nd — which had already been delivered — and the next run re-posted
  them. State is now saved after each successful post, and written atomically
  via temp file + `os.replace`.
* **Silent no-op on a mistyped column name.** `row.get()` returned `None` for
  every row, so the run exited 0 having detected nothing, forever. Configured
  column names are now validated against the header row and the run refuses.
* **`--list-columns` hid the answer when it was most needed.** It read
  `rows[0].keys()`, so a header-row-with-zero-data-rows response printed "zero
  rows" and no names. It now uses `csv.DictReader.fieldnames`.
* **Added `--seed-state`** (mutually exclusive with `--dry-run`).

## Optional: trigger on refresh instead of a timer

If Tableau Server can reach an HTTPS endpoint on the VPS, you can skip the fixed
interval:

1. Stand up a one-route listener on the VPS that runs the script on POST.
2. Register a Tableau Webhook for `workbook-refresh-succeeded`, scoped to the
   Journey Flow Report workbook, pointing at it.
3. Keep an hourly cron as backup in case a delivery is missed.

Requires Tableau Server 2021.3+ with Webhooks enabled (ours is 2025.3.5, so the
version is fine) and a VPS reachable from the Tableau Server's network. If
either isn't true, cron polling is the more reliable default.
