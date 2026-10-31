# Live data

Strata can add live feeds as normal layers. Live data is refreshed by re-querying
the provider; it is not streamed continuously.

## Weather radar

**Live → Weather radar → Add radar overlay** creates a raster layer backed by
RainViewer. The tile proxy resolves the latest radar frame and caches it for five
minutes. Radar layers update automatically without re-importing.

RainViewer only serves radar tiles up to zoom 7. Strata caps the layer at zoom 7
and lets MapLibre upscale that tile at closer zooms, so RainViewer's "zoom level
not supported" placeholder never appears on the map.

- Attribution: RainViewer
- Max zoom: 7 (upscaled above 7)
- Config: `RAINVIEWER_ENABLED`, `RAINVIEWER_METADATA_URL`

## Weather points

**Live → Weather points** lets you search for a place or drag an area, then samples
Open-Meteo current conditions on a 3×3, 4×4 or 5×5 grid. Each point carries:

- temperature
- humidity
- precipitation/rain
- wind speed and direction
- cloud cover
- pressure
- WMO weather code and description
- observation time

Existing weather layers have a **Refresh** button. Refreshing replaces the points
with a new observation from the same area. Manual edits to a live layer are
replaced by the next refresh.

- Attribution: Open-Meteo (CC BY 4.0)
- Config: `OPEN_METEO_URL`, `LIVE_GRID_POINTS`

## Earthquakes

**Live → Earthquakes** imports the USGS current-day GeoJSON feed, filtered by
minimum magnitude. Points carry magnitude, place, time, depth, tsunami flag,
significance and the USGS event URL. Existing layers can be refreshed.

- Attribution: USGS Earthquake Hazards Program (public domain)
- Config: `USGS_EARTHQUAKES_URL`

## Operational notes

- Live requests are made by the API/worker host, not by the browser.
- Provider URLs are validated with the same SSRF rules as remote imports.
- Live layers use source type `api`; they are normal layers for visibility,
  permissions, styling and exports, but they are not editable vector data unless
  a provider imports vector features (weather/earthquakes are points).
- The live radar layer is raster and cannot be edited.
- Respect provider rate limits and terms. Point `OPEN_METEO_URL` or the other
  URLs at a proxy/self-hosted mirror if needed.
