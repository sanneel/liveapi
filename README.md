# Live Odds Management

Backoffice and image-rendering service for live sports odds. A background parser
scrapes jugabet.cl, stores every match in one database, and serves on-demand PNG
images that get embedded in marketing emails and journeys. An admin panel lets
operators curate what those images show.

For the deep technical write-up see [ARCHITECTURE_REPORT.md](ARCHITECTURE_REPORT.md).
For server setup and deploys see [DEPLOY.md](DEPLOY.md) and
[deploy/STAGING_RUNBOOK.md](deploy/STAGING_RUNBOOK.md).

---

## What it produces

Everything renders from a single `matches` table. There are four public,
cache-friendly image surfaces, each independent of the others:

| Surface | URL | What it renders |
|---|---|---|
| Campaigns | `/r/{slug}.png` | A hand-picked (manual) or league-filtered (auto) list of matches with odds. The main email asset. |
| Hot | `/hot/{sport}.png` | The auto-ranked hottest matches for a sport, admin-reorderable. |
| Clubs | `/club/{slug}.png` | A single team's next upcoming match. Pure PNG, one per club slug. |
| Cubes | `/cube/{theme}.png` (plus `.gif`, `/widget`, `/data.json`) | A promotional 3D-cube unit that auto-picks matches by hot score. |

Campaigns also carry the journey URL used in emails:
`https://<host>/r/{slug}.png?limit=N&v={{JourneyActivityId}}&u={{playerID}}`.

---

## Tech stack

- Python 3, FastAPI, served by uvicorn (`server:app`).
- SQLAlchemy 2 over SQLite, with Alembic migrations.
- Playwright (headless Chromium) for the parser.
- Pillow for image rendering.
- Jinja2 templates and a little Alpine.js for the admin UI.
- bcrypt + JWT cookie sessions for auth.

---

## Repository layout

```
server.py                 Production entry point: FastAPI app + the parser threads
app/
  config.py               All settings (env-overridable). See "Configuration" below.
  database.py             Session factory and the db_session() context manager
  models/                 SQLAlchemy models (Match, Campaign, Club, User, ...)
  repositories/           Data-access layer (CampaignRepository, UserRepository, ...)
  routes/                 HTTP routes: admin_*.py (panel) and public_*.py (images)
  services/               Rendering engine, hot engine, telegram_notify, campaign_monitor
  parser/                 Feed parsing + extra-feed management
  render/                 Shared rendering helpers (logos.py: disk cache + initials fallback)
  templates/              Jinja2 admin pages (base.html is the shared shell)
  static/                 redesign.css (the live design system), favicon, admin bundle
scripts/                  Operational CLI tools (see "Scripts" below)
alembic/                  Database migrations
```

Note: the various `*_render_server.py` and `server_v2.py` files at the repo root
are legacy or standalone experiments. The live service is `server.py` on port
8000.

---

## Quick start (local development)

```bash
# 1. Virtualenv + dependencies
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium      # one-time, for the parser

# 2. Initialize the database (creates the SQLite file + runs migrations)
python scripts/init_db.py

# 3. Create your first admin account
python scripts/create_admin.py --username sandros7 --role admin

# 4. Run the app
uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1
```

Then open `http://127.0.0.1:8000/admin/login`.

Always run with `--workers 1`. The parser uses background threads inside the
process; more than one worker would spawn duplicate parsers (a pidfile guard
also blocks this, but one worker is the rule).

To run without the parser (UI-only work), set `PARSER_ENABLED=false`.

---

## Configuration

Settings live in `app/config.py` and can be overridden with environment
variables (a `.env` file is loaded automatically). The common ones:

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` enables stricter checks at startup. |
| `DATABASE_URL` | local SQLite file | Database connection string. |
| `PARSER_ENABLED` | `true` | Set `false` to run the UI without scraping. |
| `PARSER_REFRESH_SECONDS` | `120` | How often each feed re-parses. |
| `MATCH_DEACTIVATE_AFTER_HOURS` | `12` | When a stale match is marked inactive. |
| `JWT_SECRET_KEY` | placeholder | Must be set to a long random string in production. |
| `COOKIE_SECURE` | `false` | Set `true` in production (HTTPS only). |
| `ALLOWED_HOSTS` | localhost set | Comma-separated hostnames allowed to serve. |
| `TELEGRAM_BOT_TOKEN` | empty | Bot token for campaign-health alerts (from @BotFather). |
| `TELEGRAM_CHAT_ID` | empty | Chat id alerts are sent to (from @userinfobot). |
| `CAMPAIGN_MONITOR_ENABLED` | `true` | Master switch for the campaign monitor. |
| `CAMPAIGN_MONITOR_INTERVAL_SECONDS` | `300` | How often the monitor runs. |
| `CAMPAIGN_STALE_MINUTES` | `20` | Data older than this counts as "dead". |
| `ADMIN_LOGIN_MAX_ATTEMPTS` | `5` | Failed logins before a temporary lockout. |
| `ADMIN_LOGIN_LOCKOUT_MINUTES` | `15` | Lockout duration. |

Never commit real secrets. `.env` is gitignored.

---

## The admin panel

Sign in at `/admin/login`. The sidebar adapts to the signed-in user's role, so
people only see pages they can open.

### Roles and permissions

Hierarchy: `admin` > `editor` > `viewer`. Each role inherits everything below it.

| Capability | Viewer | Editor | Admin |
|---|:---:|:---:|:---:|
| View dashboard, matches, hot, cubes, weights, clubs, campaigns, live parses | yes | yes | yes |
| Edit campaigns, hot, cubes, weights, clubs | no | yes | yes |
| Delete / duplicate / bulk-delete campaigns | no | yes | yes |
| Delete clubs | no | yes | yes |
| Parser Links, Journey Cloner | no | yes | yes |
| Logs page | no | no | yes |
| Tutorial management (upload / delete) | no | no | yes |

Watching tutorials (the Help button) is available to every signed-in user.

### Pages

- Dashboard: parser status and quick stats.
- Matches: every match the parser has seen, searchable.
- Campaigns: create and manage the `/r/{slug}.png` assets (manual or auto).
- Hot: per-sport ranking, with pin / suppress / reorder overrides.
- Journey Cloner: tooling to spin up email-journey drafts.
- Parser Links: extra league or tournament feed URLs the parser pulls.
- Live Parses: live per-feed health, computed from the database (not a guess).
- Weights: tune the hot-score formula per sport.
- Cubes: manage the promotional cube units.
- Clubs: per-team `/club/{slug}.png` definitions.
- Logs: audit trail of admin actions (admin only).

### Account onboarding

Accounts are created with a one-time password (see Scripts). The flow:

1. The operator signs in with the password you give them.
2. They are sent straight to the change-password page and confined there until
   they set a new password. The forced change only asks for the new password,
   not the temporary one they just used to sign in.
3. After the change they land on the dashboard with a welcome prompt that points
   them at the tutorials. They can watch or dismiss it and keep working.

---

## Account management (scripts)

All run from the project root. On the server, prefix with `.venv/bin/python`.

Create one admin (interactive or with flags):

```bash
python scripts/create_admin.py --username adminusername --role admin
```

Create operator accounts with generated one-time passwords:

```bash
# interactive: pick a role once, then type usernames
python scripts/new_user.py

# batch
python scripts/new_user.py --role editor user1 user2 user3
# re-issue a password for someone who lost theirs
python scripts/new_user.py --reset user1
```

List and remove accounts:

```bash
python scripts/manage_users.py list

# delete specific account(s); dry run, then add --yes to confirm
python scripts/manage_users.py delete --user user1
python scripts/manage_users.py delete --user user1 user2 --yes

# delete everyone except the named account(s)
python scripts/manage_users.py delete-others --keep user1 --yes
```

Both delete commands refuse to run if a named account does not exist, or if the
deletion would leave no active admin, so you cannot lock yourself out. Without
`--yes` they only preview.

---

## The parser

`server.py` starts one parser thread per feed inside the main process, driven by
a single shared Playwright Chromium worker. Each feed re-parses every
`PARSER_REFRESH_SECONDS`. A watchdog respawns dead feeds. A lightweight
priority-odds HTTP loop keeps featured leagues (campaign / hot / World Cup) fresh
even when the heavy browser feeds are slow.

Extra feeds (specific leagues or tournaments) are managed from the Parser Links
page and stored in `data/parser_extra_feeds.json`.

Matches that drop out of the feed are marked `is_active = false`. A match still
flagged live but not refreshed within the stale window is treated as finished by
downstream logic.

---

## Campaign health monitor (Telegram)

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, a background monitor
(running only in the parser-holding process, so workers do not double-alert)
checks every enabled campaign on an interval and:

- Sends a red alert when a campaign's data goes dead (its league has no live
  matches, or its picked matches went stale or were removed), and a green alert
  when it recovers. Alerts fire only on state changes, not every cycle.
- Auto-disables a manual campaign whose every picked match has finished
  (inactive, removed, or frozen-stale), so it stops rendering blank, and sends a
  one-time notice. Empty-by-design campaigns are left alone.

The monitor loop also runs the auto-disable pass when Telegram is unconfigured;
the alerts simply become no-ops. Use the "Test Telegram alert" button on the
Parser Links page to confirm the bot credentials work.

---

## Useful operational scripts

| Script | Purpose |
|---|---|
| `scripts/init_db.py` | Create the database and run migrations. |
| `scripts/create_admin.py` | Create or update one admin/operator. |
| `scripts/new_user.py` | Create operators with generated one-time passwords. |
| `scripts/manage_users.py` | List, delete, or prune accounts. |
| `scripts/import_tutorial.py` | Add a tutorial video from the server (bypasses upload size limits). |
| `scripts/reset_hot.py` | Clear hot overrides for a sport. |
| `scripts/reset_2fa.py` | Clear legacy 2FA state on an account. |
| `scripts/test_all_endpoints.py` | Smoke-test every endpoint against a running server. |

Several `scripts/probe_*.py` and `scripts/capture_*.py` files are parser
investigation tools, not part of normal operations.

---

## Deployment

Production runs on a VPS behind nginx, which proxies to uvicorn on port 8000,
managed by systemd. Updates are a pull plus restart:

```bash
cd /home/admin/<app-dir>
git pull --ff-only origin <branch>
systemctl restart <service>
```

Full first-time setup, backups, monitoring, and rollback are in
[DEPLOY.md](DEPLOY.md). The staging procedure is in
[deploy/STAGING_RUNBOOK.md](deploy/STAGING_RUNBOOK.md). The runbook is the source
of truth for hostnames and service names; treat any conflicting older notes with
caution.

---

## Conventions

- Many small, focused files over a few large ones.
- All user input is validated at the route boundary; database access goes through
  the repository layer.
- Admin actions are recorded in the audit log.
- Renderers share `app/render/logos.py` for logo caching and fallback.
- The three image systems (Campaigns, Hot, Clubs) are intentionally independent
  and must not be merged.
```
