# Data import

## Formats

| Format | Extensions | Path | Notes |
| --- | --- | --- | --- |
| GeoJSON | `.geojson`, `.json` | vector | FeatureCollection or single Feature |
| GeoPackage | `.gpkg` | vector | All layers in the GPKG are read as one dataset |
| FlatGeobuf | `.fgb` | vector | Read through GDAL/OGR |
| GeoParquet | `.parquet` | vector | Read with GeoPandas/pyarrow |
| GML / DXF | `.gml`, `.dxf` | vector | Read through GDAL/OGR when the driver is available |
| Shapefile | `.zip` (containing `.shp`) | vector | Upload the ZIP, not loose `.shp` components |
| KML / KMZ | `.kml`, `.kmz` | vector | KMZ is opened through GDAL `/vsizip/` |
| GPX | `.gpx` | vector | Waypoints, tracks and routes as GDAL exposes them |
| CSV | `.csv` | vector | lat/lon, WKT or GeoJSON geometry column |
| Geotagged photos | `.jpg`, `.jpeg`, `.jfif`, `.tif`, `.tiff`, `.png`, `.webp`, `.raf` | vector + attachment | EXIF GPS scan, point feature and original image |
| GeoTIFF / COG | `.tif`, `.tiff` | raster | Converted to COG with overviews |
| WMS | URL | raster | Proxy kept server-side |
| WFS | URL | vector | Capabilities discovery or explicit `type_name` |
| ArcGIS Feature Service | URL | vector | Queries `f=geojson` |
| STAC Item | URL | raster | First COG/GeoTIFF asset |
| Remote file | URL | vector/raster | Detected by extension, headers and content |

Unsupported extensions are rejected before the job is queued.

## CSV conventions

Columns are matched case-insensitively:

- Longitude: `longitude`, `lon`, `lng`, `x`
- Latitude: `latitude`, `lat`, `y`
- WKT: `geometry`, `wkt`, `geom`
- GeoJSON: `geojson`

If a WKT/GeoJSON column exists it wins over lat/lon. All other columns become
feature properties. Empty or invalid coordinates produce a feature with a null
geometry and an import warning, not a silent drop.

## Create or append

The upload and URL wizards let you:

- create a new layer (auto-detected geometry type and bounds), or
- append to an existing vector layer.

Appending validates that the file's geometry types fit the target layer. Raster
layers cannot be appended to; create a new raster layer instead.

## CRS handling

Datasets with a CRS are reprojected to EPSG:4326 with pyproj/GeoPandas. Datasets
without a CRS are assumed to be EPSG:4326 and logged with a warning. For CSV,
coordinates are assumed WGS84 longitude/latitude.

The original CRS string, bounds, feature count, geometry types and import stats
are stored in the layer `metadata` JSONB.

## Invalid geometries

Every geometry is checked with Shapely. Invalid geometries are:

1. counted and reported in the job result (`stats.invalid_count`);
2. repaired with `make_valid` when possible (`stats.repaired_count`);
3. annotated with `_nasmap_invalid_geometry` (the validity reason) and
   `_nasmap_original_geometry_wkt` (the original shape) so nothing is silently
   lost.

Null/empty geometries are kept as warnings and skipped from the layer. The UI
shows imported, skipped and repaired counts when the job completes.

## Background jobs and progress

Uploads and URL imports return `202` with a job object. The browser polls
`/api/v1/imports/{job_id}` and can cancel a queued job immediately or request
cooperative cancellation of a running one. Jobs record `queued`, `running`,
`succeeded`, `failed` and `cancelled`, plus progress, message, error, attempts
and result.

Retry a failed/cancelled job with `POST /api/v1/imports/{job_id}/retry`.

## Remote URL imports

`POST /api/v1/imports/url` accepts:

```json
{
  "url": "https://example.org/parks.geojson",
  "name": "Parks",
  "kind": "auto",
  "visibility": "private",
  "licence": "CC-BY-4.0",
  "attribution": "Example City",
  "refresh_interval_seconds": 86400
}
```

`kind` may be `auto`, `geojson`, `gpkg`, `cog`, `wms`, `wfs`, `arcgis`, `stac`
or `url`. For WMS include `wms_layers`. For WFS you can supply `type_name`;
otherwise the task reads the capabilities document and picks the first feature
type.

The source URL, resolved URL, content type, checksum, retrieval time, licence
and attribution are stored in `imports.external_sources`. When a refresh
interval is set, the worker checks due sources every minute and enqueues a new
import.

### SSRF and size limits

- Only `http` and `https`.
- DNS/IP checks on the initial URL and every redirect (max 6 hops).
- Blocked: loopback, private, link-local, multicast, reserved, unspecified,
  cloud metadata (`169.254.169.254` and friends), credentials in URL.
- `MAX_URL_IMPORT_MB` byte cap and `URL_FETCH_TIMEOUT_SECONDS` wall clock.
- `ALLOW_PRIVATE_URL_IMPORTS=true` is an explicit, documented exception for
  trusted LAN services (for example a WMS on `192.168.x.x`).

DNS rebinding against attacker-controlled hosts remains a residual risk; run
Strata on a network where outbound access is appropriate.

## Geotagged photos

**Map → Add layer → Photos** accepts multiple JPEG/TIFF/PNG/WebP files. Strata
reads each file's EXIF GPS tags and:

- creates a point feature per geotagged photo in a new photo layer (or an
  existing point/mixed layer);
- stores the original image as a permission-checked attachment;
- records timestamp, camera, altitude, pixel dimensions and filename as
  feature properties;
- lists every photo that has no GPS tag instead of silently placing it at
  `0,0` or deleting it from your disk.

When importing into an existing layer you can enable **attach to nearest
existing point** and set a radius. This matches a photo to a surveyed feature
within that distance instead of creating a duplicate point. Duplicate files are
detected by SHA-256 checksum and skipped.

The photo gallery appears in the feature panel. Clicking a point with an
attachment shows the first photo immediately; additional photos are shown as
thumbnails. For any editable feature, not only photo layers, **Add file** in the
feature panel attaches an image without requiring GPS. The same control accepts
PDF, text, CSV, video, audio and glTF files as generic attachments. Non-image
files are listed with a Download action. Thumbnails are generated on demand and
cached in the uploads volume. Limits:

- `MAX_PHOTO_MB` (default 100 MB per photo);
- `MAX_ATTACHMENT_MB` (default 250 MB for non-image media);
- up to 100 photos per request;
- Fujifilm RAF files are read through their embedded JPEG preview for EXIF GPS
  and thumbnails. A RAF without a preview/EXIF GPS is skipped and listed.
- HEIC files must be converted to JPEG first, and GPS stored only in XMP (not
  EXIF) is not read in this release.

## Server / NAS folder ingestion

Files already on the machine running the stack can be processed without a
browser upload. The host folder is mounted read-only at `/ingest` by Compose and
only paths under `INGEST_ROOTS` are visible. There is no arbitrary filesystem
browsing: absolute paths are resolved, symlinks are handled, and anything
outside the configured roots is rejected.

**Map → Add layer → Server / NAS**:

1. choose a configured root and an optional subfolder;
2. choose **Geotagged photos** or **Geodata files**;
3. scan to preview supported files and counts;
4. start a background job.

Photo mode reads EXIF GPS from every image and creates photo points/attachments.
Original images stay in place (read-only reference); thumbnails are cached in
Strata’s uploads volume. Geodata mode imports each GeoJSON/GPKG/Shapefile ZIP/
KML/KMZ/GPX/CSV/GeoTIFF/COG as its own child import job and layer, reported in
the parent job.

NAS metadata folders such as `@eaDir`, `#recycle`, `.@__thumb`, `__MACOSX`,
`$RECYCLE.BIN` and `System Volume Information` are skipped. Hidden files and
unsupported extensions are skipped. Unreadable paths are reported rather than
aborting the whole scan.

Limits: `INGEST_MAX_SCAN_FILES` for previews, `INGEST_MAX_FILES_PER_JOB` for a
job, `MAX_PHOTO_MB` for photo parsing. Folder imports do not copy the source
geodata file into the uploads volume.

## Overlays

Raster services can be added without copying their pixels. See
[overlays.md](overlays.md) for XYZ/TMS, TileJSON and WMS providers. Tessera is
implemented as one overlay provider and is documented separately in
[tessera.md](tessera.md).

## Editable OSM data

**Map → OSM data** imports a small area of current OSM data from Overpass into a
normal editable layer. Polygons, lines and points use the same feature editing,
attribute table, styling and export behaviour as any other layer. Edits are
local and are not written back to OSM automatically. See [osm.md](osm.md) for
categories and limits.

## Raster ingestion

GeoTIFFs are inspected with rasterio (CRS, bounds, resolution, band count,
nodata, overviews) and converted to a Cloud Optimized GeoTIFF in the uploads
volume. Layers are served as XYZ PNG tiles by the API:

```
GET /api/v1/layers/{layer_id}/tiles/{z}/{x}/{y}.png
```

MapLibre sends the access token for these requests. Download the original COG
with `GET /api/v1/layers/{layer_id}/download`. WMS layers use
`GET /api/v1/layers/{layer_id}/wms?bbox=...&width=256&height=256`.

## Exports

Vector layers can be exported as GeoJSON, GeoPackage, KML or CSV from the layer
panel:

```
GET /api/v1/layers/{id}/export?format=geojson|gpkg|kml|csv
```

Exports include all non-deleted features and current properties. CSV includes a
`geometry_wkt` column. Raster layers can be downloaded as GeoTIFF. Tessera
datasets can be downloaded as a ZIP of native UTM GeoTIFFs (see
[docs/tessera.md](tessera.md)).

## Limits

| Limit | Default | Where |
| --- | --- | --- |
| File upload | 512 MB | `MAX_UPLOAD_MB` |
| Remote download | 1024 MB | `MAX_URL_IMPORT_MB` |
| Remote timeout | 90 s | `URL_FETCH_TIMEOUT_SECONDS` |
| Features returned by the map API | 20,000 | per-request `limit` |
| Tessera tiles per job | 64 | `TESSERA_MAX_TILES` |

For larger vector datasets, upload in batches and append to a layer.
