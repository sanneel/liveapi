#!/usr/bin/env bash
# Auto-deploy: when origin/main moves, pull it and restart the :8000 app.
# Safe no-op when there's nothing new. Meant to run from cron every minute.
#
# OFF BY DEFAULT. Continuously deploying whatever lands on main is appropriate
# for STAGING, not production. To enable, set AUTODEPLOY_ENABLED=1 in the
# crontab line (alongside RESTART_CMD if the unit name differs):
#   * * * * * AUTODEPLOY_ENABLED=1 RESTART_CMD="systemctl restart yourunit" /usr/bin/flock -n /tmp/autodeploy.lock /home/admin/staging_html/scripts/auto_deploy.sh
# For production, prefer an explicit, gated deploy instead:
#   git fetch && git checkout <known-good-tag> && ./deploy/deploy.sh
set -u
REPO=/home/admin/staging_html
RESTART_CMD="${RESTART_CMD:-systemctl restart jugabet}"
AUTODEPLOY_ENABLED="${AUTODEPLOY_ENABLED:-0}"
LOG="$REPO/logs/autodeploy.log"

if [ "$AUTODEPLOY_ENABLED" != "1" ]; then
  echo "$(date -u) auto-deploy disabled (set AUTODEPLOY_ENABLED=1 to enable; staging only)" >>"$LOG" 2>/dev/null
  exit 0
fi

cd "$REPO" 2>/dev/null || { echo "$(date -u) no repo at $REPO" >>"$LOG"; exit 1; }
exec >>"$LOG" 2>&1

git fetch origin main --quiet 2>/dev/null || { echo "$(date -u) git fetch failed"; exit 0; }

if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
  exit 0   # already current — nothing to do
fi

echo "$(date -u) new commits on main -> deploying"
if ! git pull --ff-only origin main; then
  echo "$(date -u) pull failed (uncommitted changes to tracked files?) — skipping"
  exit 1
fi

if eval "$RESTART_CMD"; then
  echo "$(date -u) restarted via: $RESTART_CMD"
else
  echo "$(date -u) '$RESTART_CMD' failed; auto-detecting the :8000 unit"
  PID=$(ss -ltnpH 2>/dev/null | grep -E ':8000\b' | grep -oP 'pid=\K[0-9]+' | head -1)
  UNIT=$(systemctl status "$PID" 2>/dev/null | head -1 | grep -oE '[A-Za-z0-9@._-]+\.service' | head -1)
  if [ -n "${UNIT:-}" ]; then
    systemctl restart "$UNIT" && echo "$(date -u) restarted unit $UNIT"
  else
    echo "$(date -u) ERROR: could not restart automatically — set RESTART_CMD in the crontab line"
  fi
fi

# Post-restart health gate: surface a bad deploy in the log instead of silently
# leaving a broken service running.
sleep 2
if curl -fsS -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "$(date -u) health OK after deploy"
else
  echo "$(date -u) WARNING: /health not OK after deploy at $(git rev-parse --short HEAD) — investigate"
fi

echo "$(date -u) now at $(git rev-parse --short HEAD)"
