#!/usr/bin/env bash
# Saves the whole database to ~/prayerfit-backups/prayerfit-YYYY-MM-DD.sql.gz
# and deletes backups older than 14 days. Cron runs it every day at 3:30 am
# (set up by server-setup.sh). Run it by hand any time:  deploy/backup.sh
# How to restore one is in the README, under "Deploy".

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$HOME/prayerfit-backups"
KEEP_DAYS=14
FILE="$BACKUP_DIR/prayerfit-$(date +%F).sql.gz"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cd "$REPO_DIR"

# The user and database names come from the db container's own settings,
# so no password is needed here. Written to a temp file first, so a failed
# dump never looks like a good backup.
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" --clean --if-exists "$POSTGRES_DB"' \
  | gzip > "$FILE.part"
mv "$FILE.part" "$FILE"
chmod 600 "$FILE"

find "$BACKUP_DIR" -name 'prayerfit-*.sql.gz' -mtime +$((KEEP_DAYS - 1)) -delete
echo "$(date '+%F %T') saved $FILE ($(du -h "$FILE" | cut -f1))"
