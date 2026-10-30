#!/usr/bin/env bash
# Generate local vector tiles from a downloaded OSM PBF using Planetiler,
# register them with TileServer GL, and switch the local style.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
REGION="${1:-${REGION:-cambridge}}"
PBF="$ROOT/data/osm/$(basename "$REGION")-latest.osm.pbf"
if [[ ! -f "$PBF" ]]; then
  echo "Missing $PBF. Run: make download-osm REGION=$REGION" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required" >&2
  exit 1
fi

VOLUME="${COMPOSE_PROJECT_NAME:-nasmap}_tiles_data"
docker volume create "$VOLUME" >/dev/null
MEMORY="${PLANETILER_MEMORY:-1g}"

echo "Generating MBTiles with Planetiler (memory ${MEMORY})..."
docker run --rm \
  -e JAVA_TOOL_OPTIONS="-Xmx${MEMORY}" \
  -v "$ROOT/data/osm":/input:ro \
  -v "$VOLUME":/output \
  ghcr.io/onthegomap/planetiler:latest \
  --download --force \
  --osm-path="/input/$(basename "$PBF")" \
  --output=/output/nasmap.mbtiles

echo "Registering MBTiles with TileServer GL..."
python3 - "$ROOT/tiles/config.json" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    config = json.load(fh)
config.setdefault("data", {})["nasmap"] = {"mbtiles": "nasmap.mbtiles"}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(config, fh, indent=2)
    fh.write("\n")
PY
cp "$ROOT/tiles/styles/nasmap/style.local.json" "$ROOT/tiles/styles/nasmap/style.json"

docker compose up -d tileserver >/dev/null
docker compose restart tileserver >/dev/null
echo "Done. Set BASEMAP_MODE=local in .env and run: docker compose up -d"
echo "Then reload the app and choose 'Local vector tiles' in the basemap switcher."
