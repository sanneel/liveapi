#!/usr/bin/env bash
# Backup the SQLite DB. Run from cron — see DEPLOY.md.
#
# Saves a timestamped copy locally; optionally pushes to Backblaze B2 via rclone.
#
# Recovery: just copy the backup file over data/jugabet.db and restart.

set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-/var/backups/jugabet}"
KEEP_DAILY="${KEEP_DAILY:-30}"
REMOTE="${REMOTE:-}"  # e.g. "b2:jugabet-backups" — leave empty to skip upload

mkdir -p "$BACKUP_DIR"

STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/jugabet-$STAMP.db"

# 1. Snapshot SQLite via its safe online backup API (sqlite3 .backup)
# This is safer than `cp` because it captures a consistent view even while
# the server is writing.
sqlite3 data/jugabet.db ".backup '$DEST'"
gzip -f "$DEST"
echo "✓ Backup: $DEST.gz ($(du -h "$DEST.gz" | cut -f1))"

# 2. Push to remote object storage if configured
if [[ -n "$REMOTE" ]]; then
  if command -v rclone >/dev/null 2>&1; then
    rclone copy "$DEST.gz" "$REMOTE/" --quiet
    echo "✓ Uploaded to $REMOTE"
  else
    echo "⚠ REMOTE is set but rclone is not installed. Skipping upload."
  fi
fi

# 3. Prune local backups older than $KEEP_DAILY days
find "$BACKUP_DIR" -name 'jugabet-*.db.gz' -type f -mtime "+$KEEP_DAILY" -delete
echo "✓ Pruned backups older than $KEEP_DAILY days"
