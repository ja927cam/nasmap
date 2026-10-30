# NasMap

**Self-hosted private maps for a NAS, home server or VPS.** NasMap serves
OpenStreetMap-based basemaps, lets you add and manage private vector and raster
layers, import data from files and remote services, and optionally ingest
TESSERA / GeoTessera satellite embeddings. It is a Docker Compose stack with a
PostGIS datastore, FastAPI backend, Redis/RQ worker, React + MapLibre front end,
TileServer GL and Caddy.

> **Status:** production-oriented reference implementation. The default stack
> runs with zero external data downloads and uses remote OSM raster tiles for
> light personal use. Local vector tiles and Tessera imports are opt-in.

## Features

- Email/password accounts, JWT access tokens, rotating refresh cookies, API keys.
- Roles: `admin`, `editor`, `viewer`; per-layer `owner` / `editor` / `viewer`
  permissions and private / internal / public visibility.
- Vector CRUD with geometry validation, version history, soft delete, GIST
  indexes and spatial filtering.
- Import GeoJSON, GeoPackage, Shapefile ZIP, KML/KMZ, GPX, CSV (lat/lon, WKT or
  GeoJSON), GeoTIFF/COG, WMS, WFS, ArcGIS Feature Services, STAC items and
  remote file URLs. Long jobs run in a background worker.
- Import batches of geotagged photos (JPEG, TIFF, PNG, WebP and Fujifilm RAF),
  read EXIF GPS/timestamps, attach the originals as permission-checked files and
  optionally match photos to the nearest surveyed point.
- Bulk-process photos and geodata already on the NAS/server through a read-only
  `/ingest` mount, with a scan preview and background jobs.
- CRS detection and reprojection to EPSG:4326, invalid-geometry reporting and
  repair without silent data loss.
- COG raster tiling through the API and WMS proxying.
- Generic XYZ/TMS, TileJSON and WMS overlays, plus Tessera coverage, import,
  caching and GeoTIFF export via the official `geotessera` package.
- Editable local OSM layers imported from Overpass (buildings, landuse, roads,
  waterways, natural features, amenities and boundaries) using the normal
  drawing and attribute editing tools.
- OSM OAuth 2.0 sign-in/linking and a preview/confirm/dry-run workflow that
  publishes a single point feature to a changeset.
- MapLibre UI: layer panel, styling, attribute table, drawing, vertex editing,
  measurement, search, viewport filtering, basemap switcher, exports.
- Caddy automatic HTTPS when you supply a domain, structured JSON logs, audit
  log, rate limiting, SSRF protections, backups and health checks.

## Quick start

Requirements: Docker Engine 24+ with Docker Compose v2, 4 GB RAM minimum
(8 GB+ if you build local tiles or import Tessera data), and a few GB of disk.

```bash
git clone https://github.com/ja927cam/nasmap nasmap
cd nasmap
cp .env.example .env
# Edit .env: at minimum set SECRET_KEY and POSTGRES_PASSWORD.
# If you change POSTGRES_PASSWORD, update DATABASE_URL to match.
docker compose up -d --build
```

Open <http://localhost>. The **first account you register becomes the
administrator**. Then:

1. Import `sample-data/cambridge-landmarks.geojson` from **Map → Add layer →
   Upload file**.
2. Draw a layer or connect a remote URL.
3. Open <http://localhost/docs> for the OpenAPI UI.

Useful commands:

```bash
make logs
make ps
make test
make backup
make restore FILE=backups/<timestamp>
```

Only Caddy publishes ports (`80`/`443`). Database, Redis, API, worker, web and
TileServer GL stay on the internal Docker network.

## Platform notes

The stack uses standard `docker compose`, so it runs on Linux and macOS directly.
On NAS systems, create a **Project / Stack** from this repository (or upload it),
paste the `.env` values, and use the platform’s Compose UI:

- **Synology DSM**: Container Manager → Project → Create. Use a folder under
  `docker/nasmap`; keep the default bridge network.
- **QNAP**: Container Station → Applications → Create; import
  `docker-compose.yml`.
- **TrueNAS SCALE**: Apps → Custom App → Install via YAML, or run from a jail
  with Docker. Mount an app dataset for the repository if you want backups.
- **Unraid**: install the Compose Manager plugin and create a stack from the
  repository.

On all of these, set `SITE_ADDRESS` to the LAN address or domain users will
visit, and make sure the host firewall allows ports 80/443.

## Configuration

All deployment-specific values are environment variables. See
[.env.example](.env.example) and [docs/setup.md](docs/setup.md). The most
important ones:

| Variable | Purpose |
| --- | --- |
| `SITE_ADDRESS` | `http://localhost`, `http://192.168.1.20` or `maps.example.com` (automatic HTTPS) |
| `SECRET_KEY` | JWT signing and OAuth-token encryption root; use `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` / `DATABASE_URL` | Database credentials; keep the URL in sync |
| `BASEMAP_MODE` | `remote_osm` (default) or `local` |
| `OSM_OAUTH_*` | Optional OSM OAuth application |
| `TESSERA_*` | Optional Tessera version, variant, registry mirror and tile cap |
| `ALLOW_PRIVATE_URL_IMPORTS` | Opt-in SSRF exception for trusted LAN services |

For production:

1. Put a DNS record in front of the host.
2. Set `SITE_ADDRESS=maps.example.com`, `SITE_URL=https://maps.example.com`,
   `FRONTEND_URL=https://maps.example.com`, `COOKIE_SECURE=true`.
3. Open ports 80 and 443. Caddy obtains and renews certificates automatically.
4. Register the OSM OAuth callback as
   `https://maps.example.com/api/v1/osm/callback`.
5. Run `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.

## Documentation

- [docs/setup.md](docs/setup.md) — install, environment, production, backups.
- [docs/architecture.md](docs/architecture.md) — design and trade-offs.
- [docs/data-import.md](docs/data-import.md) — supported formats and URL sources.
- [docs/overlays.md](docs/overlays.md) — generic XYZ, TileJSON and WMS overlays.
- [docs/tessera.md](docs/tessera.md) — Tessera coverage, import and export.
- [docs/osm.md](docs/osm.md) — basemaps, OSM PBF import, tiles and publishing.
- [tiles/README.md](tiles/README.md) — TileServer GL layout and tile generation.

## OSM basemap and tile policy

The default `remote_osm` mode uses `tile.openstreetmap.org`. That service is
intended for **light, personal, non-commercial use** and has a strict usage
policy. Do not use it for heavy traffic, bulk downloads, or a public production
site. For anything beyond testing, switch to local vector tiles or point
`OSM_TILE_URL` at a tile provider you are entitled to use. See
[docs/osm.md](docs/osm.md).

## Security

- Never commit `.env`. Rotate `SECRET_KEY` and `POSTGRES_PASSWORD` before
  exposing the instance.
- Rate limiting uses Redis and applies to auth and upload endpoints.
- Remote URL imports enforce http/https, DNS/IP checks on every redirect hop,
  a byte cap and a timeout. Private/LAN imports require the explicit
  `ALLOW_PRIVATE_URL_IMPORTS=true` opt-in.
- Uploads are size-capped, extension-checked and parsed by GDAL, never executed.
- OSM tokens are encrypted with Fernet using `OSM_TOKEN_ENCRYPTION_KEY` (or a key
  derived from `SECRET_KEY`). Publishing always requires a preview and explicit
  confirmation, and supports dry runs.
- Audit entries are written for imports, deletes, permission changes and OSM
  publications.

## Tests and CI

```bash
make test   # API tests against an isolated db-test container
make lint
```

Unit tests cover password hashing, JWT, geometry validation and OSM XML.
Integration tests cover registration/login/refresh, layer permissions, GeoJSON
and CSV import, spatial bbox queries, attribute search, feature versioning and
SSRF rejection. GitHub Actions runs Ruff, pytest against a PostGIS service,
frontend lint/typecheck/build, and Docker image builds.

## License

MIT for the application code. Map data has its own licenses: OpenStreetMap data
is © OpenStreetMap contributors (ODbL); Tessera embeddings are subject to the
GeoTessera dataset terms; imported layers retain the licence you record.
