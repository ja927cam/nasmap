# OpenStreetMap: basemaps, extracts and publishing

Strata is not an OSM editor. It supports OSM in three separate ways:

1. a basemap (remote raster or local vector tiles);
2. importing raw `.osm.pbf` extracts into the `osm` PostGIS schema with
   `osm2pgsql`;
3. a tightly controlled workflow to publish one selected point feature to OSM
   with preview, dry-run and explicit confirmation.

## Basemap modes

### Remote OSM raster (default)

```dotenv
BASEMAP_MODE=remote_osm
OSM_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
OSM_TILE_ATTRIBUTION=&copy; OpenStreetMap contributors
```

This works after `docker compose up` with no downloads. By default MapLibre
requests tiles from Strata's `/api/v1/basemap/osm/{z}/{x}/{y}.png` endpoint,
which fetches the configured upstream tile only on a cache miss and stores it in
the `tiles_data` volume for `OSM_TILE_CACHE_TTL_DAYS` (default 7). There is no
prefetching. Set `OSM_TILE_PROXY=false` to request the upstream URL directly.
The attribution is always displayed.

> **OSM tile usage policy:** `tile.openstreetmap.org` is run by volunteers for
> light, personal, non-commercial use. It forbids bulk downloading, heavy or
> public production traffic, and removing attribution. For a public deployment,
> use local vector tiles below or a commercial/self-hosted tile provider, and
> update `OSM_TILE_URL`. See the
> [OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
> Strata's on-demand cache is a courtesy to the upstream service, not a license
> for heavy use. Do not raise traffic beyond light personal use without switching
> providers or generating local tiles.

### Local OSM vector tiles

The stack includes TileServer GL and a `tiles_data` volume. The flow:

```bash
make download-osm REGION=cambridge
make generate-tiles REGION=cambridge
# set BASEMAP_MODE=local in .env
docker compose up -d
```

The default `cambridge` region is a small BBBike city extract, so the first
local build is fast. `england`, `scotland`, `wales` and `united-kingdom` map to
Geofabrik; any full Geofabrik path such as
`europe/united-kingdom/england` also works. Override the URL entirely with
`OSM_PBF_URL=https://... ./scripts/download-osm.sh`.

What the scripts do:

- `download-osm.sh` downloads `data/osm/<region>-latest.osm.pbf` and verifies
  the `.md5` when Geofabrik provides one.
- `generate-tiles.sh` runs Planetiler in Docker with the PBF mounted read-only,
  writes `nasmap.mbtiles` into the `nasmap_tiles_data` volume, registers it in
  `tiles/config.json`, copies the local style into place and restarts
  TileServer GL.
- The web basemap switcher offers **Local vector tiles**, which loads
  `/tiles/styles/nasmap/style.json` through Caddy.

Planetiler downloads Natural Earth and water polygon data on first use (about
1 GB). Give it enough RAM; set `PLANETILER_MEMORY=2g` for a large extract.

The committed local style uses OpenMapTiles source layers (`water`, `landcover`,
`landuse`, `park`, `transportation`, `boundary`, `building`). It intentionally
omits text labels so it has no font dependency. Extend
`tiles/styles/nasmap/style.local.json` and add glyphs if you want labels.

## Editable OSM layers

**Map → Add → Import OSM area** imports a local, editable copy of OSM from Overpass. Search
for a place or drag a rectangle in the map picker, choose a category (buildings,
landuse, roads, waterways, natural, amenities, leisure or administrative
boundaries) and a layer name. The worker
creates ordinary Strata features, so the existing draw, vertex-edit, delete,
attribute and styling tools work on them.

- Buildings, landuse and other closed features become polygons.
- Roads become lines.
- Nodes become points.
- OSM tags, `osm_type`, `osm_id`, `osm_version`, timestamp and user are preserved
  as feature properties.
- MultiPolygon/MultiLineString relations are split into editable parts; holes
  are preserved on individual polygons.

**Edits are local.** Strata does not write changes back to OpenStreetMap
automatically. OSM publishing remains a separate, explicitly confirmed workflow
for point nodes.

Configuration:

```dotenv
OVERPASS_ENABLED=true
OVERPASS_URL=https://overpass-api.de/api/interpreter
OVERPASS_TIMEOUT_SECONDS=90
OVERPASS_MAX_AREA_DEG2=0.05
OVERPASS_MAX_MB=64
```

Please respect the Overpass service's usage policy; run your own Overpass
instance or use a local PBF pipeline for heavy use. The import is deliberately
area-limited to avoid accidental large queries.

```text
GET  /api/v1/osm/data/categories
POST /api/v1/osm/import
```

## Importing OSM into PostGIS

For custom analysis and the optional `osm` schema:

```bash
make download-osm REGION=cambridge
make import-osm REGION=cambridge
```

This runs the `iboates/osm2pgsql` image as the one-shot `osm-import` Compose
service (profile `osm`), with:

```
--slim --hstore --schema=osm --prefix=osm_ --create --drop
```

The tables are `osm.osm_nodes`, `osm.osm_ways`, `osm.osm_relations`,
`osm.osm_point`, `osm.osm_line`, `osm.osm_polygon`, `osm.osm_roads`, etc.
`--drop` makes re-imports idempotent. Raw OSM is not exposed through the Strata
web API; query it with SQL or connect QGIS to the database over an SSH tunnel.

`make update-osm REGION=...` downloads the latest extract, re-imports it and
regenerates local tiles. This is a full refresh, not a minutely diff. For daily
diffs, run `osm2pgsql-replication` yourself against the same database.

## OSM OAuth 2.0

1. Register an application at
   <https://www.openstreetmap.org/oauth2/applications>.
2. Set the redirect URI to:
   ```
   https://maps.example.com/api/v1/osm/callback
   ```
3. Configure `.env`:
   ```dotenv
   OSM_OAUTH_ENABLED=true
   OSM_CLIENT_ID=...
   OSM_CLIENT_SECRET=...
   OSM_REDIRECT_URI=https://maps.example.com/api/v1/osm/callback
   OSM_API_BASE_URL=https://api.openstreetmap.org
   OSM_AUTH_URL=https://www.openstreetmap.org/oauth2/authorize
   OSM_TOKEN_URL=https://www.openstreetmap.org/oauth2/token
   OSM_SCOPES=read_prefs write_api
   ```
4. Restart the stack, then **Settings → OpenStreetMap → Connect**.

Strata requests only `read_prefs write_api` by default. OAuth tokens are
encrypted with Fernet. If `OSM_TOKEN_ENCRYPTION_KEY` is empty, a key is derived
from `SECRET_KEY`; rotating `SECRET_KEY` forces everyone to reconnect OSM.

### OSM sign-in

Users with an OSM account that is already linked can sign in with OSM from the
login page (`GET /api/v1/osm/login`). The callback creates a Strata refresh
session and redirects back into the SPA.

First-time OSM users get a clear “no linked account” message unless you set
`OSM_SIGNIN_AUTO_CREATE=true`. With auto-create enabled, a `viewer` account is
created with the email `osm-<id>@users.noreply.nasmap`; an admin can promote it
or the user can set a password in Settings. Users should normally sign in with
email/password first and use **Settings → OpenStreetMap → Connect** to link their
OSM identity for publishing.

### Development server

To test against the OSM dev server, register an app at
<https://master.apis.dev.openstreetmap.org> and set:

```dotenv
OSM_API_BASE_URL=https://master.apis.dev.openstreetmap.org
OSM_AUTH_URL=https://master.apis.dev.openstreetmap.org/oauth2/authorize
OSM_TOKEN_URL=https://master.apis.dev.openstreetmap.org/oauth2/token
OSM_REDIRECT_URI=http://localhost/api/v1/osm/callback
```

Use throwaway dev accounts.

## Publishing a feature

Publishing supports **point nodes** in this release. You can create a new node,
or attach a Strata point to an existing OSM node and update its tags.

UI flow:

1. Select a point feature in an editable layer.
2. **Attach / publish to OSM**.
3. To attach to an existing OSM point, choose a search radius and press
   **Find nearby OSM points**. Select the matching OSM node.
4. Review the merged tags, coordinates, changeset comment and source. Existing
   OSM tags are preserved and the OSM node keeps its current position.
5. Press **Dry run** to see the exact OsmChange XML without uploading.
6. Tick “I have reviewed…” and press **Confirm and publish**.

Photos and other files remain attached to the Strata feature. OpenStreetMap
does not host image files; to show a photo on OSM, add an `image` tag with a
publicly reachable URL (for example a Wikimedia Commons or Mapillary URL).

The API performs:

1. `POST /api/v1/osm/nearby` — finds tagged OSM nodes around the feature.
2. `POST /api/v1/osm/preview` — builds merged tags, changeset XML and OsmChange
   diff; no network write.
3. `POST /api/v1/osm/publish` with `dry_run: true` — same, explicitly no write.
3. `POST /api/v1/osm/publish` with `confirm: true`:
   - creates a changeset (`PUT /api/0.6/changeset/create`);
   - uploads the OsmChange diff (`POST /api/0.6/changeset/{id}/upload`);
   - closes the changeset (`PUT /api/0.6/changeset/{id}/close`);
   - parses the returned node id/version and stores `osm_type`, `osm_id`,
     `osm_version` and `osm_changeset` on the feature;
   - writes an audit entry and an `app.osm_publications` row.

If the upload fails after a changeset was created, Strata attempts to close the
changeset and records the error in `app.osm_publications`.

### Review rules

- OSM edits are public and permanent. Strata requires an explicit confirmation
  checkbox and a non-empty changeset comment.
- Only tags the user reviewed are sent. Internal properties (`_nasmap*`,
  `osm_*`, `photo_*`, `exif_*`, `camera_*`, `geometry_wkt`) are excluded.
- When updating an existing node, current OSM tags are fetched and kept.
  Deleting existing tags is not supported in this version; edit values or add
  new tags.
- Do not upload data that violates OSM’s licence or community guidelines.
- Use the dev server before testing against production OSM.

## Troubleshooting

- **`OSM OAuth is not configured`**: enable it and set client id/secret; restart
  the API.
- **`Connect` redirects to an error**: the callback URI must match exactly,
  including scheme and trailing path. Set `SITE_URL`/`FRONTEND_URL` and
  `COOKIE_SECURE` correctly.
- **`Only point features can be published`**: ways/relations are not supported.
- **`OSM upload failed`**: read the `detail` field; the changeset id and error
  are in `app.osm_publications`. Check the OSM API status and your scopes.
- **Local style blank**: generate tiles first, confirm the MBTiles entry in
  `tiles/config.json`, and check `docker compose logs tileserver`.
