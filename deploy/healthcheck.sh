#!/usr/bin/env bash
# Cron-friendly health check.
# Exits 0 if everything is fine, non-zero (with stderr message) otherwise.
#
# Usage in crontab:
#   */5 * * * * /var/www/jugabet/deploy/healthcheck.sh \
#       || curl -fsS -m 5 https://hc-ping.com/YOUR-UUID/fail

set -euo pipefail

URL="${URL:-http://127.0.0.1:8000/health}"
MAX_STALE_SECONDS="${MAX_STALE_SECONDS:-300}"   # alert if any feed older than 5 min

RESP=$(curl -fsS -m 5 "$URL")

# Parse the latest_updated_epoch from each feed
NOW=$(date +%s)
PYTHON=$(command -v python3 || command -v python)

RESP="$RESP" NOW="$NOW" MAX_STALE_SECONDS="$MAX_STALE_SECONDS" "$PYTHON" - <<'EOF'
import json, sys, os
now = int(os.environ.get("NOW", "0")) or int(__import__("time").time())
max_stale = int(os.environ.get("MAX_STALE_SECONDS", "300"))
data = json.loads(os.environ["RESP"])
feeds = data.get("feeds", {})
stale = []
failed = []
for name, meta in feeds.items():
    last = meta.get("last_updated_epoch") or 0
    age = int(now - last) if last else None
    if not meta.get("ok"):
        failed.append(f"{name} (error={meta.get('error')})")
    elif age is None or age > max_stale:
        stale.append(f"{name} (age={age}s, ok={meta.get('ok')})")
if failed:
    sys.stderr.write("FAILED FEEDS:\n  " + "\n  ".join(failed) + "\n")
    sys.exit(1)
if stale:
    sys.stderr.write("STALE FEEDS:\n  " + "\n  ".join(stale) + "\n")
    sys.exit(1)
print(f"OK: {len(feeds)} feeds, max stale = {max_stale}s")
EOF
