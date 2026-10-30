# Overlays

An overlay is a layer you put on top of your own data without importing or
copying the source pixels. Strata treats overlays as a normal raster layer with
a provider configuration in `layer.metadata`.

## Providers

| Provider | Use |
| --- | --- |
| XYZ / TMS | Any raster tile service with a `{z}/{x}/{y}` URL template |
| TileJSON | A TileJSON document describing raster tiles |
| WMS | An OGC Web Map Service layer |
| GeoTIFF / COG | Download a remote raster and convert it to a COG layer |
| Tessera | GeoTessera satellite embeddings, imported as a COG layer |

The **Overlays** page adds XYZ, TileJSON and WMS sources immediately. GeoTIFF/
COG URLs and Tessera use the same page but run background jobs. Vector overlays
from GeoJSON, WFS and ArcGIS are available from **Map → Add layer → From URL**.

## XYZ / TMS

Required fields:

- name;
- URL template containing `{z}`, `{x}` and `{y}`;
- tile size (256 or 512);
- XYZ or TMS scheme;
- optional min/max zoom, bounds, attribution and licence.

Example:

```text
https://tile.example.org/{z}/{x}/{y}.png
```

The API proxies tile requests through
`/api/v1/layers/{layer_id}/tiles/{z}/{x}/{y}.png`, so API keys in the upstream
URL are not exposed to the browser and CORS is not required. Tiles are cached in
the `tiles_data` volume for `OVERLAY_TILE_CACHE_TTL_HOURS` (default 24). A `{s}`
subdomain token is substituted with `a`.

## TileJSON

Provide the TileJSON URL. Strata validates the URL, fetches the document
server-side, and stores the first `tiles` URL plus tile size, zoom limits,
scheme, bounds and attribution. Tile requests are then proxied like XYZ.

## WMS

Provide the base GetMap endpoint, layer name(s), version and image format.
Requests are proxied through
`/api/v1/layers/{layer_id}/wms?bbox=...&width=256&height=256` with
`EPSG:3857`. WMS servers must be reachable from the API container.

## GeoTIFF / COG

Provide a URL to a GeoTIFF or Cloud Optimized GeoTIFF. The worker downloads it,
converts it to a COG with overviews, stores it in the uploads volume and registers
a raster layer. Large files are bounded by `MAX_URL_IMPORT_MB`.

## Tessera

See [tessera.md](tessera.md). Tessera is one provider, not a special case in the
data model: after import it is a normal raster layer with a COG and Tessera
metadata.

## Security

- Overlay URLs are validated with the same SSRF rules as remote imports.
- Private/LAN overlay endpoints require `ALLOW_PRIVATE_URL_IMPORTS=true`.
- The API tile cache is on-demand; there is no bulk prefetching.
- Visibility and layer permissions are enforced by the tile and WMS endpoints.

## API

```text
GET  /api/v1/overlays/providers
POST /api/v1/overlays/xyz
POST /api/v1/overlays/tilejson
POST /api/v1/overlays/wms
```

The response is the created layer. Use the normal layer/feature and map endpoints
afterward.
