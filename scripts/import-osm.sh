#!/usr/bin/env bash
# Import an OSM PBF into PostGIS (schema osm) with osm2pgsql.
# Requires the db service to be running.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
REGION="${1:-${REGION:-cambridge}}"
PBF="$ROOT/data/osm/$(basename "$REGION")-latest.osm.pbf"
if [[ ! -f "$PBF" ]]; then
  echo "Missing $PBF. Run: make download-osm REGION=$REGION" >&2
  exit 1
fi

docker compose up -d db >/dev/null
echo "Waiting for database health..."
for _ in $(seq 1 60); do
  if docker compose exec -T db pg_isready >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

RELATIVE="/data/$(basename "$PBF")"
echo "Importing $RELATIVE into schema osm with osm2pgsql..."
# --drop replaces the previous osm_* tables, making re-imports idempotent.
# Use scripts/update-osm.sh for a scheduled full refresh.
docker compose --profile osm run --rm osm-import \
  --slim --hstore --schema=osm --prefix=osm_ --create --drop \
  --number-processes="${OSM2PGSQL_THREADS:-2}" \
  --cache="${OSM2PGSQL_CACHE_MB:-1024}" \
  "$RELATIVE"

echo "OSM import complete. Tables: osm.osm_* (nodes, ways, relations, point, line, polygon, roads)."
