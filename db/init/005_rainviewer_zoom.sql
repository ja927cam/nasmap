-- RainViewer radar tiles are only available up to zoom 7. Cap existing layers
-- so MapLibre overzooms the z7 tile instead of requesting placeholder tiles.
UPDATE app.layers
SET metadata = jsonb_set(metadata, '{xyz,maxzoom}', '7'::jsonb, true)
WHERE metadata->>'provider' = 'rainviewer'
  AND (metadata #>> '{xyz,maxzoom}') ~ '^[0-9]+$'
  AND (metadata #>> '{xyz,maxzoom}')::int > 7;
