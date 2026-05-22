# Staging Deployment Runbook

End-to-end instructions for deploying the staging instance to a VPS that
already hosts (or will host) the production `jugabet` service. **Production
is never modified by this runbook.** Staging gets its own:

| Resource | Production | Staging |
|---|---|---|
| Path | `/var/www/jugabet` | `/var/www/jugabet-staging` |
| Service | `jugabet` | `jugabet-staging` |
| Port | 8000 | 8001 |
| DB file | `/var/www/jugabet/data/jugabet.db` | `/var/www/jugabet-staging/data/jugabet.db` |
| Logs | `/var/log/jugabet/` | `/var/log/jugabet-staging/` |
| Domain | `yourdomain.tld` (Caddy) | `staging.yourdomain.tld` (Caddy) |

---

## 0. One-time host prep (skip if already done)

```bash
# All commands as root unless noted.

# OS user — same one production uses.
id -u jugabet >/dev/null 2>&1 || useradd -r -m -s /bin/bash jugabet

# Directories
mkdir -p /var/www/jugabet-staging
mkdir -p /var/log/jugabet-staging
chown -R jugabet:jugabet /var/www/jugabet-staging /var/log/jugabet-staging

# (Optional) Add staging vhost to Caddy if your prod uses Caddy. Reload
# Caddy AFTER the service is up so the upstream is reachable.
```

## 1. Clone + checkout the validated commit

```bash
sudo -u jugabet -i  # become the app user
cd /var/www/jugabet-staging
git clone https://github.com/<your-org>/jugabet.git .
# Pin to the exact commit that passed local + audit:
git checkout <commit-sha-or-tag>
```

## 2. Python venv + dependencies

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip wheel
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps   # may need root; sudo separately if so
```

## 3. Environment file

```bash
# As jugabet user:
cp deploy/staging.env.example .env
chmod 600 .env

# Generate a unique JWT secret:
openssl rand -hex 48
# Paste output into JWT_SECRET_KEY=... in .env

# Edit ALLOWED_HOSTS + PUBLIC_BASE_URL to match your staging domain.
$EDITOR .env
```

## 4. Pre-flight DB sanity check

```bash
mkdir -p /var/www/jugabet-staging/data
# Confirm Alembic can talk to the DB (this also auto-creates the file).
.venv/bin/alembic current
# Should print nothing if no head exists yet, or '0009 (head)' if pre-populated.
```

## 5. Install + start the systemd unit (as root)

```bash
exit  # back to root
cp /var/www/jugabet-staging/deploy/jugabet-staging.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jugabet-staging

# Watch boot:
journalctl -u jugabet-staging -f
# Expect:
#   "INFO  [alembic.runtime.migration] Running upgrade -> 0009 ..."
#   "INFO  server: parser: spawning 16 feed threads (pid=...)"
#   "INFO  uvicorn.server: Application startup complete."
```

## 6. Smoke test (from the VPS)

```bash
# Health
curl -fsS http://127.0.0.1:8001/health | python3 -m json.tool | head -40
# Look for:
#   "ok": true,
#   "worker_pid": <some-pid>,
#   "parser_owner_pid": <same-pid as worker_pid>,
#   "parser_owner_alive": true,
#   "db": {"ok": true},
#   "parser_freshness_seconds" appears after first parse cycle (~120s).

# Admin pages return HTML
curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/admin/login
# 200

# Public endpoints
curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/hot/football
curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/hot/football.png
# 200 / 200
```

## 7. From your laptop

Login at `https://staging.yourdomain.tld/admin/login` and walk each section:

- Dashboard — `Parser freshness` should show `Fresh` after one cycle.
- Hot → click into football → drag a row, confirm the slot saves.
- Hot → suppress one match, confirm it moves to the "Hidden" bucket.
- Campaigns → create one Auto + one Manual.
- Manual edit → click `+ Add` on a picker row → verify the row appears in **Selected matches IMMEDIATELY** (no save-settings click required) and disappears from the picker.
- Auto edit → confirm the "Live preview" card shows matches; if you set a league with no current matches, a yellow warning banner appears.
- Clubs → click `+ Create club` → seed `test-club` → open `/club/test-club.png`.
- Clubs → toggle "Hide opponent logo" on a club with a next match → confirm `/club/<slug>.png` reloads without the rival logo (TTL is 30s; bump query: `?t=1`).
- Logs → verify your `campaign.create`, `hot.reorder`, `club.update` entries are listed.

## 8. 24h soak — what to watch

```bash
# Cheap cron-style polling every 5 min:
watch -n 300 'curl -s http://127.0.0.1:8001/health | jq "{ok, parser_freshness_seconds, db, parser_owner_alive}"'

# Tail for errors:
sudo tail -F /var/log/jugabet-staging/app.stderr.log

# Crashes show up here:
sudo journalctl -u jugabet-staging --since "1h ago" | grep -E "(ERROR|Traceback|StartLimit)"
```

Pass criteria (all must hold for 24 hours):
- `ok: true` on every `/health` poll
- `parser_freshness_seconds` never exceeds `2 × parser_refresh_seconds` (i.e. ≤ 240s by default)
- `parser_owner_alive: true` continuously
- No restart events in `journalctl`
- No tracebacks in `app.stderr.log`
- `/hot/<sport>.png` and `/r/<slug>.png` and `/club/<slug>.png` continue to return 200 with non-1x1 content for sports that have matches

## 9. Failure modes & rollback

| Symptom | Likely cause | Action |
|---|---|---|
| `journalctl` shows `Unsafe production configuration` | `APP_ENV=production` but JWT/cookies/hosts misconfigured | Edit `.env`, restart |
| `OperationalError: unable to open database file` | `data/` dir missing or wrong perms | `mkdir -p data && chown jugabet:jugabet data` |
| `/health` returns 500 | `db.ok=false` (DB unreachable) | Check `data/jugabet.db` permissions; check disk space |
| `parser_owner_alive=false` | Parser thread crashed and `atexit` failed to clean pidfile | `rm /var/www/jugabet-staging/data/parser.pid && systemctl restart jugabet-staging` |
| `parser_freshness_seconds` keeps growing | Parser threads exited; check `app.log` for the per-feed `Traceback` | Usually upstream HTML changed; fix `parse_html`, redeploy |
| Service flaps (`StartLimitIntervalSec`) | Crash on startup | `journalctl -u jugabet-staging -n 200`, fix root cause, `systemctl reset-failed jugabet-staging` |

**Rollback to a previous commit:**
```bash
sudo -u jugabet -i
cd /var/www/jugabet-staging
git fetch --tags
git checkout <previous-good-tag>
.venv/bin/pip install -r requirements.txt
exit
systemctl restart jugabet-staging
```

Migrations 0001–0009 are forward-only — if you roll the code back to a
pre-0009 commit but the DB is already at 0009, run the matching downgrade
manually: `.venv/bin/alembic downgrade 0008` (etc.). Each migration's
`downgrade()` re-adds dropped columns with default values, so existing data
in columns that were never dropped is preserved.

---

## Production cutover (only after the 24h soak passes)

Same general flow as staging, applied to `/var/www/jugabet` + `jugabet.service`.
Before stopping prod:

```bash
# 1. Backup the current prod DB (atomic via sqlite3 .backup, NOT cp).
sudo /var/www/jugabet/deploy/backup.sh
# Verify the backup is non-zero and openable:
ls -lah /var/backups/jugabet/
sqlite3 /var/backups/jugabet/<latest>.db "SELECT COUNT(*) FROM matches;"

# 2. Tag the deploy
sudo -u jugabet git -C /var/www/jugabet tag -a "deploy-$(date -u +%Y%m%d-%H%M)" -m "..."

# 3. Run deploy.sh — does pull + pip + alembic + restart + healthcheck
sudo /var/www/jugabet/deploy/deploy.sh

# 4. Verify
curl -fsS http://127.0.0.1:8000/health | jq '.ok'
```

If `deploy.sh` fails the healthcheck, it exits non-zero — read the printed
log section, restore the backup if needed, and re-run.
