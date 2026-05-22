# Deployment Guide

A step-by-step guide for getting the Jugabet odds CRM running on a fresh VPS.
Assumes Ubuntu 22.04 or Debian 12. Everything is copy-paste.

---

## TL;DR — Daily Operations

| Action | Command |
|---|---|
| **Deploy latest code** | `cd /var/www/jugabet && ./deploy/deploy.sh` |
| **View live logs** | `sudo journalctl -u jugabet -f` |
| **Restart service** | `sudo systemctl restart jugabet` |
| **Check health** | `curl -s http://127.0.0.1:8000/health \| jq .` |
| **Run a backup now** | `./deploy/backup.sh` |
| **Roll back to previous commit** | `git reset --hard HEAD~1 && ./deploy/deploy.sh` |
| **Reset someone's 2FA** | `.venv/bin/python scripts/reset_2fa.py USERNAME` |

> **Run uvicorn with `--workers 1`** (the default). The parser uses
> in-process background threads and the PNG cache is process-local, so
> running multiple workers causes duplicate feed fetches, SQLite write
> contention, and stale cached PNGs that admin actions can't invalidate
> across worker boundaries. Scale vertically first; if you outgrow that,
> move the parser to a sidecar process before adding workers.

> **Migrations run automatically** on every server startup via the FastAPI
> startup hook (`server._run_migrations_on_startup`). No manual
> `alembic upgrade head` step is needed for the standard deploy flow,
> but you can still run it by hand for ad-hoc schema work.

---

## 1. First-time VPS setup (do this once)

SSH into your fresh VPS as root.

### 1.1 — Create a non-root user

```bash
adduser jugabet                          # set a strong password
usermod -aG sudo jugabet                 # give sudo
mkdir -p /home/jugabet/.ssh
# Paste your SSH public key:
nano /home/jugabet/.ssh/authorized_keys
chown -R jugabet:jugabet /home/jugabet/.ssh
chmod 600 /home/jugabet/.ssh/authorized_keys
```

Verify you can log in as `jugabet` from another terminal **before** continuing.

### 1.2 — Harden SSH (no password / no root login)

```bash
nano /etc/ssh/sshd_config
```
Change these lines:
```
PermitRootLogin no
PasswordAuthentication no
```
Then:
```bash
systemctl restart sshd
```

### 1.3 — Firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

### 1.4 — Fail2ban (auto-block SSH brute force)

```bash
apt install -y fail2ban
systemctl enable --now fail2ban
```

### 1.5 — Automatic security updates

```bash
apt install -y unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades
```

### 1.6 — Install Python + system deps

```bash
apt update
apt install -y python3.11 python3.11-venv python3-pip git sqlite3 curl rclone

# Playwright system libraries (needed by the parser):
apt install -y libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
               libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
```

### 1.7 — Install Caddy (auto-HTTPS reverse proxy)

```bash
apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update
apt install -y caddy
```

---

## 2. Install the app

Log in as `jugabet`, **not** root.

```bash
sudo mkdir -p /var/www/jugabet /var/log/jugabet /var/backups/jugabet
sudo chown jugabet:jugabet /var/www/jugabet /var/log/jugabet /var/backups/jugabet

cd /var/www/jugabet
git clone https://your-git-host/jugabet-odds.git .    # or copy files via scp

# Create the virtualenv
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Install Playwright's browser binaries (one-time)
.venv/bin/playwright install chromium
```

### 2.1 — Configure environment

```bash
cp .env.example .env
nano .env
```

Generate a strong JWT secret and paste it in:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set in `.env`:
```
APP_ENV=production
PUBLIC_BASE_URL=https://your-domain.com
ALLOWED_HOSTS=your-domain.com
JWT_SECRET_KEY=<paste the long random string>
COOKIE_SECURE=true       # mandatory in production
COOKIE_SAMESITE=lax
LOG_LEVEL=INFO
```

### 2.2 — Initialize DB

```bash
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/create_admin.py     # creates your first admin user
```

### 2.3 — Install the systemd service

```bash
sudo cp deploy/jugabet.service /etc/systemd/system/
sudo cp deploy/jugabet.logrotate /etc/logrotate.d/jugabet
sudo systemctl daemon-reload
sudo systemctl enable --now jugabet
sudo systemctl status jugabet
```

Watch live logs:
```bash
sudo journalctl -u jugabet -f
```

You should see `Application startup complete` and parser activity.

### 2.4 — Wire up Caddy

Edit `deploy/Caddyfile` and replace `odds.jugabet.cl` with your real domain.

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo mkdir -p /var/log/caddy
sudo systemctl restart caddy
```

Within 30 seconds Caddy obtains a Let's Encrypt cert and starts serving HTTPS.

Open `https://your-domain.com/admin/login` — you should see the login page.

---

## 3. Cloudflare in front of Caddy (recommended)

In Cloudflare DNS, add an A record for your subdomain pointing to your VPS IP. Then:

- **SSL/TLS** → mode **Full (Strict)**
- **Always Use HTTPS** → On
- **Automatic HTTPS Rewrites** → On
- **Bot Fight Mode** → On
- **Browser Integrity Check** → On
- **Security Level** → Medium
- (Optional) **Page Rule** for `*your-domain.com/admin/*`:
  - Security Level: High
  - Cache Level: Bypass
- (Optional) **WAF Custom Rule** to block non-Chile IPs from `/admin/*`:
  - Field: URI Path · contains · `/admin`
  - AND Country · ≠ · Chile
  - Action: Block

Once Cloudflare proxies traffic (orange cloud), only Cloudflare IPs reach Caddy.
To **enforce** that (block direct-IP scans), you can configure Caddy to only
accept connections from Cloudflare's published IP list. See:
https://developers.cloudflare.com/fundamentals/reference/ips/

---

## 4. Backups

### 4.1 — Local backups (always)

Add this line to root's crontab (`sudo crontab -e`):

```cron
0 */6 * * * /var/www/jugabet/deploy/backup.sh > /var/log/jugabet/backup.log 2>&1
```

This runs every 6 hours; backups land in `/var/backups/jugabet/`. The script keeps 30 days locally.

### 4.2 — Off-site backups (recommended)

Sign up for **Backblaze B2** (free tier: 10 GB). Create an application key, then:

```bash
rclone config        # follow prompts to add a "b2" remote
```

Edit the cron entry to include the remote:

```cron
0 */6 * * * REMOTE=b2:jugabet-backups /var/www/jugabet/deploy/backup.sh > /var/log/jugabet/backup.log 2>&1
```

Now backups are uploaded automatically.

### 4.3 — Recovery

Stop the service, restore, restart:

```bash
sudo systemctl stop jugabet
gunzip -c /var/backups/jugabet/jugabet-20260518_120000.db.gz > /var/www/jugabet/data/jugabet.db
sudo systemctl start jugabet
```

---

## 5. Monitoring

### 5.1 — Local cron-based health check

```cron
*/5 * * * * /var/www/jugabet/deploy/healthcheck.sh >> /var/log/jugabet/healthcheck.log 2>&1
```

### 5.2 — External alerting (recommended)

Sign up free at https://healthchecks.io and create a check. Then:

```cron
*/5 * * * * /var/www/jugabet/deploy/healthcheck.sh && curl -fsS https://hc-ping.com/YOUR-UUID > /dev/null
```

If the script fails — or doesn't ping in time — you get an email/Slack alert.

---

## 6. Deploying updates

After the first install, every future deploy is one command:

```bash
cd /var/www/jugabet
./deploy/deploy.sh
```

The script:
1. Snapshots the current DB (`data/jugabet.db.before-deploy-...`)
2. Pulls latest code
3. Installs new dependencies if `requirements.txt` changed
4. Runs any new Alembic migrations
5. Restarts the systemd service
6. Health-checks; if it fails, prints rollback instructions

### Rollback

```bash
# Roll back code only:
git reset --hard HEAD~1 && ./deploy/deploy.sh

# Roll back code + DB:
git reset --hard HEAD~1
mv data/jugabet.db.before-deploy-XXXX data/jugabet.db
sudo systemctl restart jugabet
```

---

## 7. Staging environment (optional but recommended)

Run a second copy on the same VPS, different port + DB file + domain.

```bash
# Clone to a second path
sudo cp -a /var/www/jugabet /var/www/jugabet-staging
sudo chown -R jugabet:jugabet /var/www/jugabet-staging
cd /var/www/jugabet-staging

# Use a separate DB
sed -i 's|jugabet.db|jugabet_staging.db|' .env
.venv/bin/python scripts/init_db.py

# Make a copy of the systemd unit, on port 8001
sudo cp deploy/jugabet.service /etc/systemd/system/jugabet-staging.service
sudo sed -i 's|WorkingDirectory=/var/www/jugabet|WorkingDirectory=/var/www/jugabet-staging|g; s|port 8000|port 8001|g; s|jugabet.stderr|jugabet-staging.stderr|g; s|jugabet.stdout|jugabet-staging.stdout|g' /etc/systemd/system/jugabet-staging.service
sudo systemctl daemon-reload
sudo systemctl enable --now jugabet-staging
```

In `/etc/caddy/Caddyfile`, add:

```caddy
staging.odds.jugabet.cl {
    reverse_proxy 127.0.0.1:8001
}
```

```bash
sudo systemctl reload caddy
```

Now you have `staging.odds.jugabet.cl` with its own DB. Test everything there
before deploying the same code to production.

---

## 8. Security checklist (production)

Before going live:

- [ ] `.env` has a unique strong `JWT_SECRET_KEY`
- [ ] `.env` has `APP_ENV=production`, `PUBLIC_BASE_URL=https://...`, and exact `ALLOWED_HOSTS`
- [ ] `COOKIE_SECURE=true` in `.env`
- [ ] SSH password authentication is disabled (`PasswordAuthentication no`)
- [ ] SSH root login is disabled (`PermitRootLogin no`)
- [ ] `ufw enable` confirmed active (`sudo ufw status`)
- [ ] `fail2ban` enabled (`sudo systemctl status fail2ban`)
- [ ] Cloudflare in front with at least Bot Fight Mode ON
- [ ] All admin users have 2FA enabled (`/admin/2fa`)
- [ ] First admin user has a strong (16+ chars) password
- [ ] Backups confirmed running (`ls -lh /var/backups/jugabet/`)
- [ ] Backups confirmed reaching off-site storage
- [ ] Health check cron is set
- [ ] An external monitor (healthchecks.io etc.) is wired up
- [ ] Origin firewall blocks direct access to ports other than 80/443/22
- [ ] Render-only legacy ports 8001-8007 are not exposed publicly

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Service won't start | Syntax error in code | `sudo journalctl -u jugabet -n 50` shows the traceback |
| Login redirects in a loop | Cookie not being saved | Make sure `COOKIE_SECURE=true` only if HTTPS works, else `false` |
| Admin pages return 503 | DB not initialized | `python scripts/init_db.py` |
| Empty PNG renders | Parser geo-blocked | Check `/health` — feeds will show errors; VPS must reach jugabet.cl |
| 2FA codes never accepted | Server clock drift | `sudo timedatectl set-ntp true` |
| `502 Bad Gateway` from Caddy | App isn't running on 8000 | `sudo systemctl status jugabet` |
| Caddy can't get cert | DNS doesn't point to VPS | `dig your-domain.com` should return the VPS IP |

---

## 10. Files & where they live

```
/var/www/jugabet/                  ← app code (this repo)
/var/www/jugabet/data/             ← SQLite DB (backed up)
/var/www/jugabet/logs/             ← app's own log files (rotating)
/var/www/jugabet/.env              ← secrets (NEVER committed to git)
/etc/systemd/system/jugabet.service ← systemd unit
/etc/caddy/Caddyfile               ← reverse proxy config
/var/log/jugabet/                  ← stdout/stderr from systemd
/var/log/caddy/                    ← Caddy access logs
/var/backups/jugabet/              ← local DB backups
```

Stay safe. Keep your `.env` and SSH keys private. 🛡️
