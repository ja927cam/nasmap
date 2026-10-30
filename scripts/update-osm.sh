#!/usr/bin/env bash
# Refresh a regional OSM extract and rebuild local tiles.
# This is a full re-import; for daily diffs use osm2pgsql-replication separately.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGION="${1:-${REGION:-cambridge}}"
"$ROOT/scripts/download-osm.sh" "$REGION"
"$ROOT/scripts/import-osm.sh" "$REGION"
"$ROOT/scripts/generate-tiles.sh" "$REGION"
echo "OSM data and local vector tiles refreshed for $REGION."
