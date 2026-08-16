#!/usr/bin/env bash
# Dumps the Supabase Postgres database (free plan has no automatic backups)
# and prunes dumps older than RETENTION_DAYS. Intended to run from cron.
#
# Reads the DB connection string from .env in this project's root, using the
# same precedence as app/database.py's get_supabase_db_url(): prefer
# CLOUD_DATABASE_URL, then SUPABASE_DB_URL, then DATABASE_URL.
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$BASE_DIR/.env"
BACKUP_DIR="/media/cloudbrand/sambashare/fileserver/studiamo-backups/db"
RETENTION_DAYS=14

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found" >&2
    exit 1
fi

get_env_var() {
    local key="$1"
    grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d'=' -f2- \
        | sed -E 's/[[:space:]]+#.*$//' \
        | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
        | sed -e "s/^[\"']//" -e "s/[\"']$//" || true
}

DB_URL="$(get_env_var CLOUD_DATABASE_URL)"
[ -z "$DB_URL" ] && DB_URL="$(get_env_var SUPABASE_DB_URL)"
[ -z "$DB_URL" ] && DB_URL="$(get_env_var DATABASE_URL)"

if [ -z "$DB_URL" ]; then
    echo "ERROR: none of CLOUD_DATABASE_URL / SUPABASE_DB_URL / DATABASE_URL set in $ENV_FILE" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H%M)"
OUT_FILE="$BACKUP_DIR/studiamo_${TIMESTAMP}.sql.gz"
TMP_FILE="${OUT_FILE}.part"

# Supabase runs Postgres 17; Ubuntu 24.04's postgresql-client package only
# ships pg_dump 16, which refuses to dump a newer-major-version server. Using
# a matching pg_dump via Docker avoids adding a third-party apt repo just for
# this one binary.
# --network host: Supabase's direct-connection endpoint is IPv6-only, and
# Docker's default bridge network doesn't route IPv6 even though the host
# does. Host networking borrows the host's route instead of touching
# /etc/docker/daemon.json (which would affect every container on this box).
if docker run --rm --network host postgres:17-alpine pg_dump --no-owner --no-privileges "$DB_URL" | gzip > "$TMP_FILE"; then
    mv "$TMP_FILE" "$OUT_FILE"
    echo "$(date -Iseconds) OK backup written: $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"
else
    rm -f "$TMP_FILE"
    echo "$(date -Iseconds) ERROR pg_dump failed, no backup written" >&2
    exit 1
fi

find "$BACKUP_DIR" -name "studiamo_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
