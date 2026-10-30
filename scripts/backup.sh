#!/usr/bin/env bash
# Back up PostGIS, uploads and Tessera cache into ./backups/<timestamp>/.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PREFIX="${COMPOSE_PROJECT_NAME:-nasmap}"
DEST="$ROOT/backups/$STAMP"
mkdir -p "$DEST"

echo "Backing up database..."
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$DEST/database.dump"

echo "Backing up uploads volume..."
docker run --rm -v "${PREFIX}_uploads":/data:ro -v "$DEST":/backup alpine \
  tar czf /backup/uploads.tar.gz -C /data .

if [[ "${BACKUP_TESSERA:-true}" == "true" ]]; then
  echo "Backing up Tessera cache (set BACKUP_TESSERA=false to skip)..."
  docker run --rm -v "${PREFIX}_tessera_cache":/data:ro -v "$DEST":/backup alpine \
    tar czf /backup/tessera_cache.tar.gz -C /data . || true
fi

cat > "$DEST/manifest.txt" <<MANIFEST
Strata backup
created_utc=$STAMP
database=database.dump (pg_dump custom format)
uploads=uploads.tar.gz
tessera=${BACKUP_TESSERA:-true}
git_commit=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)
MANIFEST

echo "Backup complete: $DEST"
echo "Restore with: make restore FILE=$DEST"
