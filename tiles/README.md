# Tiles

TileServer GL serves three things from this directory:

* `config.json` — TileServer GL configuration, mounted at `/data/config.json`.
* `styles/nasmap/style.json` — the MapLibre style requested by the web app at
  `/tiles/styles/nasmap/style.json`.
* `/data/tiles` — generated MBTiles, stored in the Docker named volume
  `nasmap_tiles_data`.

The committed style is a neutral background, so the default `BASEMAP_MODE=remote_osm`
works with no downloads. To switch to local vector tiles:

```bash
make download-osm REGION=cambridge
make import-osm REGION=cambridge      # optional, keeps OSM in PostGIS
make generate-tiles REGION=cambridge  # Planetiler -> MBTiles -> TileServer GL
```

Then set `BASEMAP_MODE=local` in `.env` and restart the stack. The generation
script copies `style.local.json` over `style.json` and registers the MBTiles
file in `config.json`.

Attribution: OpenStreetMap data © OpenStreetMap contributors, available under
the Open Database License (ODbL).
