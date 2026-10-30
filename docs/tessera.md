# Tessera / GeoTessera

Strata integrates the official
[`geotessera`](https://github.com/ucam-eo/geotessera) Python package. The
adapter lives in `api/app/services/tessera.py` and only calls documented
GeoTessera APIs. No undocumented HTTP endpoints are assumed.

## What it does

Tessera provides 128-channel satellite embeddings on a 0.1° grid (about
10 m pixels, 1,000 × 1,000 per tile). Strata can:

- check coverage for a bounding box, year and variant before downloading;
- preview the tile list on the map;
- download selected tiles into the `tessera_cache` Docker volume;
- export native-UTM GeoTIFFs for QGIS/GDAL;
- build a web-friendly mosaic, convert it to a COG and register it as a raster
  layer with full metadata.

## Configuration

```dotenv
TESSERA_ENABLED=true
TESSERA_VERSION=v1.1
# v1.1 GeoTIFF export uses the NPY "cambridge" variant.
TESSERA_VARIANT=cambridge
# Optional mirror / pinned registry URL.
TESSERA_REGISTRY_URL=
TESSERA_MAX_TILES=64
```

The API image installs the `tessera` extra (`geotessera>=0.11,<0.12`). If you
build a custom image and omit it, `/api/v1/tessera/*` returns a clear 503.

The library writes registry manifests under
`/data/tessera/registry` and tiles under `/data/tessera/tiles`; the compose stack
mounts the `tessera_cache` volume for both. Job outputs live under
`/data/tessera/jobs/<job-id>`.

## Using the UI

1. Open **Overlays → Tessera**.
2. Search for a place or drag a rectangle on the map.
3. Choose a year and variant.
4. Press **Check coverage**. The response includes tile count, the tile grid,
   available years/variants, resolution, band count, licence and the configured
   cap.
5. Press **Import Tessera**. The job runs in the worker.

The import is a background job: progress, cancellation and errors are shown in
the job dialog. Cancel is cooperative and checked between tiles. Failed jobs can
be retried from the API or the dashboard.

By default only channels 1, 2 and 3 are exported to the web COG so the layer is
small. Clear the **Export bands** field to export all 128 channels for GIS work
(this can be very large). The dataset metadata records both the source channel
count and the number of bands actually written.

When the job succeeds:

- a raster layer named `Tessera <year> <variant>` is created (private by
  default);
- a COG mosaic is stored in the uploads volume and served as XYZ tiles;
- `app.tessera_datasets` records the bbox, year, variant, tile list, band count,
  resolution, CRS, licence and cache path;
- native-UTM GeoTIFF tiles remain in the job cache for GIS export.

## Export

**Overlays → Tessera exports → Download GeoTIFFs** returns a ZIP of the
native tiles:

```
GET /api/v1/tessera/datasets/{dataset_id}/download
```

The web mosaic is EPSG:3857 because it is built for MapLibre; the individual
tiles preserve their native UTM zones. For analysis, prefer the individual
GeoTIFFs or read embeddings directly with `GeoTesseraZarr` / `sample_points`
from the official library.

## API examples

```bash
# Coverage
curl -X POST http://localhost/api/v1/tessera/coverage \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"bbox":[-0.2,51.4,0.1,51.6],"year":2024}'

# Import (returns a job)
curl -X POST http://localhost/api/v1/tessera/import \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"bbox":[-0.2,51.4,0.1,51.6],"year":2024,"name":"London 2024"}'

# Poll
curl http://localhost/api/v1/imports/<job-id> -H "Authorization: Bearer $TOKEN"
```

## Limits and safety

- A job is capped at `TESSERA_MAX_TILES` (default 64). Narrow the bbox or raise
  the cap deliberately.
- The adapter refuses bounding boxes larger than 25 square degrees.
- Downloads can be large and slow. The worker has a 12-hour RQ timeout; adjust
  it in `api/app/workers/queue.py` for very large jobs.
- Disk use grows with the cache. Clean `/data/tessera/jobs` or remove old
  datasets if space is tight. `scripts/backup.sh` includes the cache by default;
  set `BACKUP_TESSERA=false` to skip it.

## Licensing

Application code is MIT. Tessera embeddings are data, not code, and are subject
to the GeoTessera dataset terms (see <https://geotessera.readthedocs.io>). The layer records
“Tessera dataset terms” as its licence and “Tessera / GeoTessera” as
attribution. Confirm the current upstream terms before redistributing derived
data.

## Troubleshooting

- **503 “geotessera package is not installed”**: rebuild the API image with the
  provided Dockerfile, or install `./api[tessera]`.
- **Registry timeouts**: test outbound HTTPS from the host and, if needed, set
  `TESSERA_REGISTRY_URL` to a mirror.
- **No tiles**: the bbox may be outside coverage, land mask water, or the chosen
  year has no data. Coverage returns `tile_count: 0` and the import is blocked.
- **Job fails after download**: check worker logs; mosaic creation falls back to
  the first tile if `merge_geotiffs_to_mosaic` fails, but COG conversion or a
  missing GeoTIFF will surface a clear error.
