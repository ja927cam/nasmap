# Architecture

Strata is a single-host, Docker Compose application. The design goal is to keep
the number of moving parts small enough for a NAS while still separating the
request path from long-running geospatial processing.

## Services

```
 Browser
   │  HTTPS / HTTP
   ▼
 Caddy ──────────────► web (nginx static React build)
   │  /api/*                 │
   ├──────────────► api (FastAPI, uvloop)
   │                   │  ├── PostgreSQL 16 + PostGIS 3.4 (db)
   │                   │  ├── Redis 7 (queue + rate limits)
   │                   │  └── /data/uploads, /data/tessera
   │  /tiles/*
   └──────────────► tileserver (TileServer GL) ── tiles_data volume

 worker (RQ) ──► PostgreSQL, Redis, uploads/tessera/tiles volumes
 osm-import (one-shot, profile "osm") ──► PostgreSQL
```

Only Caddy publishes ports. All other services join the internal `nasmap`
bridge network. Named volumes: `db_data`, `redis_data`, `uploads`,
`tessera_cache`, `tiles_data`, `caddy_data`, `caddy_config`.

## Key decisions

### Monorepo, one Compose file

The API, worker, web app, database migrations and tile tooling share one
repository. `docker-compose.yml` is the normal deployment; the `prod` overlay
only adds log rotation and is the recommended production invocation. Platform
differences (Synology, QNAP, TrueNAS, Unraid) are handled at the Compose level
rather than with custom installers.

### PostgreSQL schemas

- `app` — users, layers, features, permissions, API keys, audit, Tessera
  metadata and OSM publications.
- `imports` — import jobs, external sources and staging tables.
- `osm` — reserved for `osm2pgsql` output (prefix `osm_`).

Keeping OSM-derived tables out of `app` makes it possible to drop and re-import
an extract without touching private data. SQL migrations are idempotent and are
applied both by the Postgres entrypoint (fresh volumes) and by
`python -m app.migrate` (existing volumes). A `schema_migrations` table records
filenames; `make migrate` is safe to re-run.

### Async API, sync worker

FastAPI uses SQLAlchemy 2 async with asyncpg. Long imports run on an RQ worker
because GDAL, rasterio and GeoTessera are CPU/IO-heavy and often blocking.
Jobs are persisted in `imports.import_jobs`; Redis is only the queue. A worker
restart therefore does not lose job history, and the UI reconnects by polling
`/api/v1/imports/{id}`.

Progress callbacks from GDAL/GeoTessera threads use a small psycopg2 helper
(`workers/sync_db.py`) rather than sharing SQLAlchemy sessions across threads.
Cancellation is cooperative: the UI sets `cancel_requested`, and long loops
check it between batches; Tessera callbacks check it between tiles.

### GDAL via Python wheels

`pyogrio` and `rasterio` ship GDAL in binary wheels. This keeps the Docker image
self-contained and avoids compiling GDAL. Formats are still parsed by GDAL/OGR
under the hood (Shapefile, GPKG, KML, KMZ, GPX, GeoJSON, GeoTIFF/COG). CSV is
parsed by pandas because coordinate-column detection is easier there.

### Raster serving

COG/GeoTIFF layers are served by the API at
`/api/v1/layers/{id}/tiles/{z}/{x}/{y}.png` using `rio-tiler` and a 256 px
tile size. This is a COG-compatible endpoint and avoids sending whole rasters to
the browser. WMS layers are proxied through the API so credentials/CORS and
authentication are handled server-side. TileServer GL remains responsible for
the optional local OSM **vector** basemap.

### Authentication

- Argon2id password hashes (`argon2-cffi`).
- Short-lived HS256 JWT access tokens in the `Authorization` header.
- Opaque refresh tokens stored only as SHA-256 hashes in `app.sessions`, sent in
  an `HttpOnly`, `SameSite=Lax` cookie scoped to `/api/v1/auth`. Refresh rotates
  on every use.
- Optional `X-API-Key` keys (hashed, prefix indexed) for scripts and QGIS.
- The browser never receives database credentials.

CSRF is not applicable to bearer-token endpoints. The two cookie endpoints
(`/auth/refresh`, `/auth/logout`) validate the `Origin` header when present and
rely on `SameSite=Lax`; set `COOKIE_SECURE=true` for HTTPS deployments.

### Permissions

Global roles are `admin`, `editor`, `viewer`. Layer access is additive:

- admins can read/write everything;
- the owner has full control;
- a row in `app.layer_permissions` grants `editor` or `viewer`;
- `public` layers are readable by any authenticated user;
- `organisation` is treated as "any authenticated user on this instance" because
  Strata is deliberately single-tenant. This is documented rather than
  pretending to support multi-organisation isolation.

Reads require any layer role; writes additionally require a global
`admin`/`editor` role. A global viewer with an `editor` grant is still read-only.

### Overlays

XYZ/TMS, TileJSON, WMS, vector-tile and Tessera overlays all become normal
layers. Raster providers use the API tile proxy; vector providers use a PBF
proxy with a generic fill/line/point style.
Provider configuration lives in `layer.metadata`, so adding another provider does
not require a new table or a new map data path. XYZ and TileJSON tiles are
proxied and cached by the API; WMS uses a GetMap proxy; Tessera stores a COG.
Tessera is therefore one provider in the same model, not a separate concept.

### Tessera

`services/tessera.py` is a thin adapter over the official `geotessera` package.
It uses only documented methods:

- `registry.get_available_years()`
- `registry.load_blocks_for_region(bounds, year)`
- `export_embedding_geotiffs(tiles, output_dir, bands, progress_callback)`
- `merge_geotiffs_to_mosaic(files, output_path, target_crs)`

The package is a Docker image dependency (`pip install .[tessera]`) but is
imported lazily so the rest of the API works if the registry is unreachable or
Tessera support is disabled.

### Server/NAS ingestion

Bulk local ingestion is opt-in through a read-only bind mount. `INGEST_ROOTS`
is the allowlist; the API resolves symlinks and rejects paths outside those
roots. The worker scans in a thread, processes photos as point features plus
attachments, and reuses the existing child import pipeline for geodata files.
Source geodata files are not copied; photo originals are referenced in place,
with thumbnails cached in the uploads volume. Too many files or unreadable
entries produce explicit job errors rather than partial silent scans.

### Live data

Live feeds are adapters that return normal records/layers: RainViewer radar is a
dynamic raster proxy; Open-Meteo and USGS are point-vector snapshots refreshed
on demand. Provider URLs are configuration, not user input, and still pass the
SSRF validator. Cached radar frames are keyed by frame path so a new frame does
not serve stale tiles.

### SSRF model

Remote imports resolve DNS and reject loopback, RFC1918, link-local, multicast,
reserved and cloud-metadata addresses on **every redirect hop**. Only http/https
is allowed, and downloads have a byte cap and a timeout. DNS rebinding is a
residual risk when the target is attacker-controlled; `ALLOW_PRIVATE_URL_IMPORTS`
is off by default and should only be enabled on a trusted LAN.

## Data model highlights

- `app.features.geometry` is `geometry(Geometry, 4326)` with a GIST index.
- Geotagged photos become point features plus `app.attachments` rows. The
  original image is stored in the uploads volume and served through a
  permission-checked API endpoint; thumbnails are generated on demand.
- A trigger increments `version` on every update and writes the previous row to
  `app.feature_versions`; the API additionally records the change reason and
  user.
- Soft deletes set `deleted_at`; triggers keep `layers.feature_count` accurate.
- Layer `style` and `metadata` are JSONB so new renderers and source types can be
  added without schema churn.
- Import jobs and external sources are separate: a source can be refreshed many
  times while each run has its own job and error trail.

## Deliberate limitations

- Publishing to OSM supports **nodes only** in this release. Ways and relations
  need a richer conflict/version workflow; the API rejects them clearly.
- Local vector tiles are generated by Planetiler and served by TileServer GL.
  There is no automatic diff replication; `scripts/update-osm.sh` re-imports and
  rebuilds. For daily diffs, use `osm2pgsql-replication` separately.
- The JavaScript bundle is intentionally dependency-light (React, React Router,
  MapLibre) and is ~1 MB uncompressed; no UI framework is used.
- Backups use `pg_dump` plus tar of the uploads/Tessera volumes; generated tiles
  are excluded because they are reproducible.
