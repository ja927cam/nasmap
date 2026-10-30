#!/usr/bin/env bash
# Restore a NasMap backup created by scripts/backup.sh.
#   ./scripts/restore.sh backups/20260101T000000Z
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SOURCE="${1:-}"
if [[ -z "$SOURCE" || ! -d "$SOURCE" ]]; then
  echo "Usage: $0 backups/<timestamp>" >&2
  exit 1
fi
DUMP="$SOURCE/database.dump"
[[ -f "$DUMP" ]] || { echo "Missing $DUMP" >&2; exit 1; }
SOURCE_ABS="$(cd "$SOURCE" && pwd)"
PREFIX="${COMPOSE_PROJECT_NAME:-nasmap}"

echo "This will replace the current NasMap database and uploads."
read -r -p "Type RESTORE to continue: " CONFIRM
[[ "$CONFIRM" == "RESTORE" ]] || { echo "Aborted"; exit 1; }

echo "Stopping API and worker..."
docker compose stop api worker >/dev/null

echo "Restoring database..."
docker compose start db >/dev/null
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$DUMP"

if [[ -f "$SOURCE/uploads.tar.gz" ]]; then
  echo "Restoring uploads..."
  docker run --rm -v "${PREFIX}_uploads":/data -v "$SOURCE_ABS":/backup:ro alpine \
    sh -c 'rm -rf /data/* && tar xzf /backup/uploads.tar.gz -C /data'
fi
if [[ -f "$SOURCE/tessera_cache.tar.gz" ]]; then
  echo "Restoring Tessera cache..."
  docker run --rm -v "${PREFIX}_tessera_cache":/data -v "$SOURCE_ABS":/backup:ro alpine \
    sh -c 'rm -rf /data/* && tar xzf /backup/tessera_cache.tar.gz -C /data'
fi

echo "Starting services..."
docker compose up -d
echo "Restore complete."
