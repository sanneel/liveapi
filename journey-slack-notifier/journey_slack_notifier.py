#!/usr/bin/env python3
"""
journey_slack_notifier.py

Polls a Tableau Server view for the "Journey Funnel Dashboard" underlying data,
detects journeys whose status field has flipped to "finished", and posts a
summary + CSV export of that journey to a Slack channel.

Designed to be run on a schedule (cron) from your own VPS. See README.md for
full setup instructions (Tableau Personal Access Token, Slack Bot Token,
finding your status field name, and the crontab entry).

Usage:
    python3 journey_slack_notifier.py               # normal run: check + notify
    python3 journey_slack_notifier.py --list-columns # diagnostic: print all
                                                       # column headers Tableau
                                                       # returns for the view,
                                                       # so you can fill in
                                                       # JOURNEY_STATUS_FIELD /
                                                       # JOURNEY_ID_FIELD /
                                                       # JOURNEY_NAME_FIELD in .env
    python3 journey_slack_notifier.py --dry-run       # detect + build message,
                                                       # but don't post to Slack
                                                       # or update the state file
    python3 journey_slack_notifier.py --seed-state    # mark all currently-
                                                       # finished journeys as
                                                       # already sent, without
                                                       # posting. RUN THIS ONCE
                                                       # before the first real
                                                       # run, or the whole
                                                       # backlog inside the
                                                       # view's date window is
                                                       # posted in one burst.
"""

import argparse
import csv
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

# The main app already has TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in its own .env
# (see app/config.py). Fall back to that file so the bot token doesn't have to be
# copied into a second place. load_dotenv() never overrides an already-set value,
# so anything in this directory's .env still wins.
_PARENT_ENV = Path(__file__).resolve().parent.parent / ".env"
if not os.environ.get("TELEGRAM_BOT_TOKEN") and _PARENT_ENV.exists():
    load_dotenv(_PARENT_ENV)

TABLEAU_SERVER_URL = os.environ.get("TABLEAU_SERVER_URL", "").rstrip("/")
TABLEAU_SITE_CONTENT_URL = os.environ.get("TABLEAU_SITE_CONTENT_URL", "")  # "" = Default site
TABLEAU_API_VERSION = os.environ.get("TABLEAU_API_VERSION", "3.20")
TABLEAU_PAT_NAME = os.environ.get("TABLEAU_PAT_NAME", "")
TABLEAU_PAT_SECRET = os.environ.get("TABLEAU_PAT_SECRET", "")
TABLEAU_WORKBOOK_NAME = os.environ.get("TABLEAU_WORKBOOK_NAME", "Journey Flow Report")
TABLEAU_VIEW_NAME = os.environ.get("TABLEAU_VIEW_NAME", "Journey Funnel Dashboard")

# Column headers in the CSV Tableau returns for the view. Run with
# --list-columns first to discover the exact names - they will not
# necessarily match the filter labels shown in the dashboard UI.
JOURNEY_ID_FIELD = os.environ.get("JOURNEY_ID_FIELD", "Journey Id")
JOURNEY_NAME_FIELD = os.environ.get("JOURNEY_NAME_FIELD", "Journey Name")
JOURNEY_STATUS_FIELD = os.environ.get("JOURNEY_STATUS_FIELD", "")
JOURNEY_FINISHED_VALUE = os.environ.get("JOURNEY_FINISHED_VALUE", "Finished")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Where to deliver: "telegram", "slack", or "both".
NOTIFY_TARGET = os.environ.get("NOTIFY_TARGET", "telegram").strip().lower()

STATE_FILE = Path(os.environ.get("STATE_FILE_PATH", "./state/sent_journeys.json"))
LOG_FILE = Path(os.environ.get("LOG_FILE_PATH", "./state/notifier.log"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("journey_slack_notifier")


# ---------------------------------------------------------------------------
# Tableau REST API helpers
# ---------------------------------------------------------------------------

class TableauClient:
    def __init__(self):
        self.token = None
        self.site_id = None

    def signin(self):
        url = f"{TABLEAU_SERVER_URL}/api/{TABLEAU_API_VERSION}/auth/signin"
        body = {
            "credentials": {
                "personalAccessTokenName": TABLEAU_PAT_NAME,
                "personalAccessTokenSecret": TABLEAU_PAT_SECRET,
                "site": {"contentUrl": TABLEAU_SITE_CONTENT_URL},
            }
        }
        resp = requests.post(url, json=body, headers={"Accept": "application/json"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()["credentials"]
        self.token = data["token"]
        self.site_id = data["site"]["id"]
        log.info("Signed in to Tableau (site id %s)", self.site_id)

    def signout(self):
        if not self.token:
            return
        url = f"{TABLEAU_SERVER_URL}/api/{TABLEAU_API_VERSION}/auth/signout"
        requests.post(url, headers=self._headers(), timeout=30)
        log.info("Signed out of Tableau")

    def _headers(self, accept="application/json"):
        return {"X-Tableau-Auth": self.token, "Accept": accept}

    def find_workbook_id(self, name):
        url = f"{TABLEAU_SERVER_URL}/api/{TABLEAU_API_VERSION}/sites/{self.site_id}/workbooks"
        params = {"filter": f"name:eq:{name}"}
        resp = requests.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        workbooks = resp.json()["workbooks"].get("workbook", [])
        if not workbooks:
            raise RuntimeError(f"No workbook found named {name!r}")
        return workbooks[0]["id"]

    def find_view_id(self, workbook_id, view_name):
        url = f"{TABLEAU_SERVER_URL}/api/{TABLEAU_API_VERSION}/sites/{self.site_id}/workbooks/{workbook_id}/views"
        resp = requests.get(url, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        views = resp.json()["views"].get("view", [])
        for v in views:
            if v["name"] == view_name:
                return v["id"]
        raise RuntimeError(f"No view named {view_name!r} in workbook {workbook_id}")

    def query_view_data_csv(self, view_id):
        """Returns (rows, column_names) for the view's data.

        NOTE: this endpoint returns the view's *summary* data - the aggregated
        marks in the viz - not row-level underlying data. If the dashboard
        aggregates away the per-journey status column, no amount of .env
        tuning will surface it; the view itself has to expose it.

        column_names is returned separately from the rows because a response
        can legitimately carry a header row and zero data rows, and that is
        exactly the case where --list-columns is most needed.
        """
        url = f"{TABLEAU_SERVER_URL}/api/{TABLEAU_API_VERSION}/sites/{self.site_id}/views/{view_id}/data"
        resp = requests.get(url, headers=self._headers(accept="text/csv"), timeout=60)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        return rows, (reader.fieldnames or [])


# ---------------------------------------------------------------------------
# State (avoid re-notifying the same journey)
# ---------------------------------------------------------------------------

def load_sent_ids():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_sent_ids(sent_ids):
    """Write the state file atomically.

    Written via a temp file + os.replace so an interrupted run (cron kill,
    laptop sleep, disk full) can never leave a half-written JSON file that
    load_sent_ids() would then crash on - which would mean re-notifying
    every journey.
    """
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(sorted(sent_ids)))
    os.replace(tmp, STATE_FILE)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def build_journey_csv(rows_for_journey):
    """Serialise one journey's rows to CSV bytes."""
    buf = io.StringIO()
    if rows_for_journey:
        writer = csv.DictWriter(buf, fieldnames=list(rows_for_journey[0].keys()))
        writer.writeheader()
        writer.writerows(rows_for_journey)
    return buf.getvalue().encode("utf-8")


def post_journey_to_slack(journey_id, journey_name, rows_for_journey):
    from slack_sdk import WebClient

    summary_text = "\n".join([
        f"*Journey finished:* {journey_name or journey_id} (`{journey_id}`)",
        f"Detected: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Rows in export: {len(rows_for_journey)}",
    ])
    client = WebClient(token=SLACK_BOT_TOKEN)
    client.files_upload_v2(
        channel=SLACK_CHANNEL_ID,
        content=build_journey_csv(rows_for_journey),
        filename=f"journey_{journey_id}.csv",
        title=f"Journey {journey_id} export",
        initial_comment=summary_text,
    )
    log.info("Posted journey %s to Slack channel %s", journey_id, SLACK_CHANNEL_ID)


def post_journey_to_telegram(journey_id, journey_name, rows_for_journey):
    """Send the summary + CSV to Telegram.

    Mirrors app/services/telegram_notify.py (Bot API, parse_mode=HTML) but is
    self-contained: importing the app package would drag pydantic-settings and
    the whole FastAPI config layer into this script's 3-dependency venv.

    Unlike that module, this RAISES on failure instead of returning False. The
    app's sender is deliberately best-effort because a dropped alert there is
    cosmetic. Here, a swallowed failure would let main() record the journey as
    sent, and that journey would then never be announced by any later run.
    """
    from html import escape

    csv_bytes = build_journey_csv(rows_for_journey)
    caption = "\n".join([
        f"<b>Journey finished:</b> {escape(journey_name or journey_id)} "
        f"(<code>{escape(journey_id)}</code>)",
        f"Detected: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Rows in export: {len(rows_for_journey)}",
    ])

    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

    if rows_for_journey:
        # One sendDocument carries both the file and the summary as its caption.
        resp = requests.post(
            f"{api}/sendDocument",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"document": (f"journey_{journey_id}.csv", csv_bytes, "text/csv")},
            timeout=30,
        )
    else:
        # An empty document is rejected by the Bot API, so send text only.
        resp = requests.post(
            f"{api}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )

    # Telegram signals application errors in the body with HTTP 200 in some
    # cases, so check ok= rather than trusting the status code alone.
    ok = False
    try:
        ok = bool(resp.json().get("ok"))
    except ValueError:
        pass
    if not (resp.status_code == 200 and ok):
        raise RuntimeError(
            f"Telegram delivery failed for journey {journey_id}: "
            f"HTTP {resp.status_code} {resp.text[:300]}"
        )
    log.info("Posted journey %s to Telegram chat %s", journey_id, TELEGRAM_CHAT_ID)


def notify_journey(journey_id, journey_name, rows_for_journey, dry_run=False):
    """Deliver one journey to whichever targets NOTIFY_TARGET selects."""
    targets = ["telegram", "slack"] if NOTIFY_TARGET == "both" else [NOTIFY_TARGET]

    if dry_run:
        log.info(
            "[DRY RUN] Would notify %s about journey %s (%s): %d rows, %d csv bytes",
            "+".join(targets), journey_id, journey_name or "unnamed",
            len(rows_for_journey), len(build_journey_csv(rows_for_journey)),
        )
        return

    for target in targets:
        if target == "telegram":
            post_journey_to_telegram(journey_id, journey_name, rows_for_journey)
        elif target == "slack":
            post_journey_to_slack(journey_id, journey_name, rows_for_journey)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-columns", action="store_true",
                         help="Print the CSV column headers Tableau returns for the view, then exit.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Detect finished journeys and log what would be sent, but don't post to Slack "
                              "or update the state file.")
    parser.add_argument("--seed-state", action="store_true",
                         help="Mark every currently-finished journey as already sent, WITHOUT posting "
                              "anything. Run this once before the first real run, otherwise the entire "
                              "backlog of journeys that finished inside the view's date window is posted "
                              "to Slack in one burst.")
    args = parser.parse_args()

    if args.seed_state and args.dry_run:
        log.error("--seed-state and --dry-run are mutually exclusive: seeding is a state write, "
                  "dry-run suppresses state writes.")
        sys.exit(2)

    missing = [name for name, val in [
        ("TABLEAU_SERVER_URL", TABLEAU_SERVER_URL),
        ("TABLEAU_PAT_NAME", TABLEAU_PAT_NAME),
        ("TABLEAU_PAT_SECRET", TABLEAU_PAT_SECRET),
    ] if not val]
    if missing:
        log.error("Missing required .env values: %s", ", ".join(missing))
        sys.exit(1)

    if NOTIFY_TARGET not in ("telegram", "slack", "both"):
        log.error("NOTIFY_TARGET=%r is invalid; use telegram, slack, or both.", NOTIFY_TARGET)
        sys.exit(1)

    # Check delivery credentials before touching Tableau, but only for a run
    # that will actually deliver. --list-columns / --dry-run / --seed-state
    # never post, so they must not be blocked by an unconfigured target.
    if not (args.list_columns or args.dry_run or args.seed_state):
        needed = []
        if NOTIFY_TARGET in ("telegram", "both"):
            needed += [("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
                       ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)]
        if NOTIFY_TARGET in ("slack", "both"):
            needed += [("SLACK_BOT_TOKEN", SLACK_BOT_TOKEN),
                       ("SLACK_CHANNEL_ID", SLACK_CHANNEL_ID)]
        blank = [k for k, v in needed if not v]
        if blank:
            log.error("NOTIFY_TARGET=%s but these are blank: %s", NOTIFY_TARGET, ", ".join(blank))
            sys.exit(1)
        if NOTIFY_TARGET in ("slack", "both") and not SLACK_BOT_TOKEN.startswith("xoxb-"):
            log.error("SLACK_BOT_TOKEN does not start with 'xoxb-'. A bot token is required for "
                      "files_upload_v2; xoxp-/xoxe- tokens will not work.")
            sys.exit(1)

    tab = TableauClient()
    try:
        tab.signin()
        workbook_id = tab.find_workbook_id(TABLEAU_WORKBOOK_NAME)
        view_id = tab.find_view_id(workbook_id, TABLEAU_VIEW_NAME)
        rows, columns = tab.query_view_data_csv(view_id)

        if args.list_columns:
            if columns:
                print(f"Columns returned by Tableau for this view ({len(rows)} data rows):")
                for col in columns:
                    print(f"  - {col}")
                if not rows:
                    print("\nNOTE: the header row is present but there are zero data rows. "
                          "The column names above are still correct; the view's own filters "
                          "are excluding every record.")
            else:
                print("Tableau returned no header row at all - the view produced an empty "
                      "response. Check that the view renders data in the browser.")
            return

        if not JOURNEY_STATUS_FIELD:
            log.error("JOURNEY_STATUS_FIELD is not set in .env. Run with --list-columns to see "
                      "available column names, then set JOURNEY_STATUS_FIELD / JOURNEY_ID_FIELD / "
                      "JOURNEY_NAME_FIELD accordingly.")
            sys.exit(1)

        # Refuse rather than silently detect nothing. A typo in any of these
        # names would otherwise make every row unmatchable: the run would exit
        # 0, log "Checked 0 journeys", and cron would report success forever
        # while never noticing a finished journey.
        configured = {
            "JOURNEY_ID_FIELD": JOURNEY_ID_FIELD,
            "JOURNEY_STATUS_FIELD": JOURNEY_STATUS_FIELD,
            "JOURNEY_NAME_FIELD": JOURNEY_NAME_FIELD,
        }
        unknown = {k: v for k, v in configured.items() if v and v not in columns}
        if unknown:
            for key, val in unknown.items():
                log.error("%s=%r is not a column in the Tableau export.", key, val)
            log.error("Columns actually returned: %s", ", ".join(columns) or "(none)")
            log.error("Fix these in .env - run with --list-columns to see the list. Refusing to "
                      "continue, because a mismatched column name detects nothing while looking "
                      "like a healthy run.")
            sys.exit(1)

        sent_ids = load_sent_ids()

        # Group rows by journey id, find journeys whose status matches "finished"
        # and that we haven't notified about yet.
        by_journey = {}
        for row in rows:
            jid = row.get(JOURNEY_ID_FIELD)
            if jid is None:
                continue
            by_journey.setdefault(jid, []).append(row)

        newly_finished = []
        for jid, journey_rows in by_journey.items():
            if jid in sent_ids:
                continue
            statuses = {r.get(JOURNEY_STATUS_FIELD) for r in journey_rows}
            if JOURNEY_FINISHED_VALUE in statuses:
                newly_finished.append(jid)

        log.info("Checked %d journeys, %d newly finished", len(by_journey), len(newly_finished))

        if args.seed_state:
            sent_ids.update(newly_finished)
            save_sent_ids(sent_ids)
            log.info("Seeded state with %d finished journeys WITHOUT posting to Slack. "
                     "Only journeys that finish from now on will be notified.",
                     len(newly_finished))
            return

        # Persist after each successful post, not once at the end. If Slack
        # fails partway through (a 429 is easy to hit - files_upload_v2 is a
        # three-call sequence), the journeys already delivered stay recorded
        # instead of being re-posted on the next run.
        for jid in newly_finished:
            journey_rows = by_journey[jid]
            jname = journey_rows[0].get(JOURNEY_NAME_FIELD, "")
            notify_journey(jid, jname, journey_rows, dry_run=args.dry_run)
            if not args.dry_run:
                sent_ids.add(jid)
                save_sent_ids(sent_ids)

    finally:
        tab.signout()


if __name__ == "__main__":
    main()
