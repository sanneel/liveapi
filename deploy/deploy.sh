#!/usr/bin/env bash
# One-command deployment.
#
# Run on the VPS:
#   cd /var/www/jugabet
#   ./deploy/deploy.sh
#
# Rollback (revert to previous commit):
#   git reset --hard HEAD~1 && ./deploy/deploy.sh

set -euo pipefail

cd "$(dirname "$0")/.."

echo "═══ JUGABET DEPLOY ════════════════════════════════════════════"
echo "📂 $(pwd)"
echo "🕓 $(date)"
echo ""

# ── 1. Snapshot the current DB (instant rollback) ──────────────────────
SNAPSHOT="data/jugabet.db.before-deploy-$(date +%Y%m%d_%H%M%S)"
if [[ -f data/jugabet.db ]]; then
  sqlite3 data/jugabet.db ".backup '$SNAPSHOT'"
  echo "✓ DB snapshot:  $SNAPSHOT"
fi

# ── 2. Pull latest code ───────────────────────────────────────────────
echo ""
echo "▶ git pull"
git pull --ff-only

# ── 3. Update dependencies if requirements changed ────────────────────
if git diff --name-only HEAD@{1} HEAD 2>/dev/null | grep -q '^requirements.txt$'; then
  echo ""
  echo "▶ requirements.txt changed, installing"
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
else
  echo "= requirements.txt unchanged"
fi

# ── 4. Run any new migrations ─────────────────────────────────────────
echo ""
echo "▶ alembic upgrade head"
.venv/bin/alembic upgrade head

# ── 5. Restart the service ────────────────────────────────────────────
echo ""
echo "▶ systemctl restart jugabet"
sudo systemctl restart jugabet
sleep 2

# ── 6. Health check ───────────────────────────────────────────────────
echo ""
echo "▶ health check"
if ./deploy/healthcheck.sh > /dev/null 2>&1; then
  echo "✓ Service is healthy"
else
  echo "✗ HEALTH CHECK FAILED"
  echo ""
  echo "Last logs:"
  sudo journalctl -u jugabet --no-pager -n 30
  echo ""
  echo "To roll back the DB:    mv $SNAPSHOT data/jugabet.db && sudo systemctl restart jugabet"
  echo "To roll back the code:  git reset --hard HEAD~1 && ./deploy/deploy.sh"
  exit 1
fi

# ── 7. Deep post-deploy verification (hard gate) ──────────────────────
# Exercises DB health, /hot JSON, PNG endpoints, club + legacy render parity.
# The admin-override check SKIPs unless PHASE_B_USERNAME/PHASE_B_PASSWORD are
# exported. Exit code is non-zero only on a real FAIL (WARN/SKIP still pass).
echo ""
echo "▶ deep health check (phase_b_health.py)"
if .venv/bin/python scripts/phase_b_health.py; then
  echo "✓ Deep health checks passed"
else
  echo "✗ DEEP HEALTH CHECK FAILED — service is up but behaving incorrectly"
  echo ""
  echo "To roll back the DB:    mv $SNAPSHOT data/jugabet.db && sudo systemctl restart jugabet"
  echo "To roll back the code:  git reset --hard HEAD~1 && ./deploy/deploy.sh"
  exit 1
fi

echo ""
echo "✅ Deployed successfully at $(date)"
