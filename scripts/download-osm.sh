#!/usr/bin/env bash
# Download a regional OSM extract.
#   ./scripts/download-osm.sh cambridge         # small BBBike city extract (default)
#   ./scripts/download-osm.sh england           # Geofabrik England (~1 GB)
#   ./scripts/download-osm.sh europe/united-kingdom/england
# Override the full URL with OSM_PBF_URL=https://... ./scripts/download-osm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGION="${1:-${REGION:-cambridge}}"
LOWER="$(printf '%s' "$REGION" | tr '[:upper:]' '[:lower:]')"
DEST_DIR="$ROOT/data/osm"
DEST="$DEST_DIR/$(basename "$REGION")-latest.osm.pbf"
mkdir -p "$DEST_DIR"

BASE="${OSM_GEOFABRIK_BASE:-https://download.geofabrik.de}"
case "$LOWER" in
  cambridge)
    URL="${OSM_PBF_URL:-https://download.bbbike.org/osm/bbbike/Cambridge/Cambridge.osm.pbf}"
    ;;
  england|scotland|wales|united-kingdom)
    PATH_PART="europe/united-kingdom"
    [[ "$LOWER" != "united-kingdom" ]] && PATH_PART="$PATH_PART/$LOWER"
    URL="${OSM_PBF_URL:-$BASE/$PATH_PART-latest.osm.pbf}"
    ;;
  */*)
    URL="${OSM_PBF_URL:-$BASE/$REGION-latest.osm.pbf}"
    ;;
  *)
    # Convenience for first-level Geofabrik regions such as europe/germany.
    URL="${OSM_PBF_URL:-$BASE/europe/$REGION-latest.osm.pbf}"
    ;;
esac

echo "Downloading $URL"
echo "          -> $DEST"
curl -fL --retry 4 --retry-delay 2 --progress-bar -o "$DEST.tmp" "$URL"

MD5_URL="$URL.md5"
if curl -fsL --retry 2 -o "$DEST.md5" "$MD5_URL"; then
  EXPECTED="$(awk '{print $1}' "$DEST.md5" | head -1)"
  if command -v md5sum >/dev/null 2>&1; then
    ACTUAL="$(md5sum "$DEST.tmp" | awk '{print $1}')"
  else
    ACTUAL="$(md5 -q "$DEST.tmp")"
  fi
  if [[ -n "$EXPECTED" && "$EXPECTED" != "$ACTUAL" ]]; then
    rm -f "$DEST.tmp"
    echo "Checksum mismatch: expected $EXPECTED, got $ACTUAL" >&2
    exit 1
  fi
  echo "Checksum OK"
fi

mv "$DEST.tmp" "$DEST"
echo "Saved $DEST"
