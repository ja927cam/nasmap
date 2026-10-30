#!/usr/bin/env bash
# Crop a downloaded PBF to a bounding box using osmium-tool in Docker.
#   BBOX=0.08,52.17,0.18,52.24 ./scripts/crop-osm.sh data/osm/cambridge-latest.osm.pbf data/osm/cambridge.osm.pbf
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT="${1:-$ROOT/data/osm/cambridge-latest.osm.pbf}"
OUTPUT="${2:-$ROOT/data/osm/cropped.osm.pbf}"
BBOX="${BBOX:-0.08,52.17,0.18,52.24}"

[[ -f "$INPUT" ]] || { echo "Missing input PBF: $INPUT" >&2; exit 1; }
IN_REL="/data/$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$INPUT" "$ROOT/data/osm")"
OUT_REL="/data/$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$OUTPUT" "$ROOT/data/osm")"

rm -f "$OUTPUT"
echo "Cropping $INPUT to bbox $BBOX"
docker run --rm -v "$ROOT/data/osm":/data stefda/osmium-tool \
  osmium extract --bbox="$BBOX" --output="$OUT_REL" "$IN_REL"
echo "Wrote $OUTPUT"
