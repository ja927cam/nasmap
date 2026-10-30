import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { getAccessToken, tileUrl, vectorTileUrl, wmsTileUrl } from '../api/client';
import type { FeatureCollection, GeoFeature, Layer } from '../api/types';

export type MapTool = 'pan' | 'point' | 'line' | 'polygon' | 'measure-distance' | 'measure-area';

interface MapViewProps {
  layers: Layer[];
  layerData: Record<string, FeatureCollection>;
  visible: Record<string, boolean>;
  opacity: Record<string, number>;
  activeLayerId: string | null;
  basemap: 'remote' | 'local';
  osmTileUrl: string;
  osmAttribution: string;
  tileserverUrl: string;
  tool: MapTool;
  selectedFeature: GeoFeature | null;
  editable: boolean;
  onSelectFeature: (layerId: string, feature: GeoFeature | null) => void;
  onCreateFeature: (layerId: string, geometry: any) => Promise<boolean>;
  onUpdateGeometry: (feature: GeoFeature, geometry: any) => Promise<void>;
  onMeasure: (result: { kind: 'distance' | 'area'; value: number; label: string } | null) => void;
  onMapReady?: (map: MapLibreMap) => void;
  onToolComplete?: () => void;
}

type LngLat = [number, number];

function remoteStyle(osmTileUrl: string, attribution: string): any {
  return {
    version: 8,
    name: 'Strata remote OSM',
    sources: {
      osm: {
        type: 'raster',
        tiles: [osmTileUrl],
        tileSize: 256,
        attribution,
        maxzoom: 19,
      },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#e9eef2' } },
      { id: 'osm', type: 'raster', source: 'osm' },
    ],
  };
}

function haversine(a: LngLat, b: LngLat): number {
  const toRad = (v: number) => (v * Math.PI) / 180;
  const R = 6371008.8;
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function lineLength(coords: LngLat[]): number {
  let total = 0;
  for (let i = 1; i < coords.length; i += 1) total += haversine(coords[i - 1], coords[i]);
  return total;
}

function ringArea(coords: LngLat[]): number {
  const R = 6371008.8;
  const toRad = (v: number) => (v * Math.PI) / 180;
  if (coords.length < 3) return 0;
  let total = 0;
  for (let i = 0; i < coords.length; i += 1) {
    const [lon1, lat1] = coords[i];
    const [lon2, lat2] = coords[(i + 1) % coords.length];
    total += toRad(lon2 - lon1) * (2 + Math.sin(toRad(lat1)) + Math.sin(toRad(lat2)));
  }
  return Math.abs((total * R * R) / 2);
}

function formatDistance(meters: number) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(2)} km` : `${meters.toFixed(1)} m`;
}

function formatArea(squareMeters: number) {
  if (squareMeters >= 1_000_000) return `${(squareMeters / 1_000_000).toFixed(2)} km²`;
  if (squareMeters >= 10_000) return `${(squareMeters / 10_000).toFixed(2)} ha`;
  return `${squareMeters.toFixed(0)} m²`;
}

function vertices(feature: GeoFeature | null): LngLat[] {
  if (!feature?.geometry) return [];
  const g = feature.geometry;
  if (g.type === 'Point') return [g.coordinates as LngLat];
  if (g.type === 'LineString') return g.coordinates as LngLat[];
  if (g.type === 'Polygon') return (g.coordinates[0] as LngLat[]).slice(0, -1);
  if (g.type === 'MultiLineString') return (g.coordinates as LngLat[][]).flat();
  return [];
}

function moveVertex(geometry: any, index: number, position: LngLat) {
  const copy = JSON.parse(JSON.stringify(geometry));
  if (copy.type === 'Point') {
    copy.coordinates = position;
  } else if (copy.type === 'LineString') {
    copy.coordinates[index] = position;
  } else if (copy.type === 'Polygon') {
    copy.coordinates[0][index] = position;
    const ring = copy.coordinates[0];
    if (index === 0) ring[ring.length - 1] = position;
  }
  return copy;
}

function handlesData(feature: GeoFeature | null) {
  return {
    type: 'FeatureCollection' as const,
    features: vertices(feature).map((coordinates, index) => ({
      type: 'Feature' as const,
      id: index,
      properties: { index },
      geometry: { type: 'Point' as const, coordinates },
    })),
  };
}

function previewData(tool: MapTool, coords: LngLat[], cursor: LngLat | null) {
  if (coords.length === 0) return { type: 'FeatureCollection' as const, features: [] };
  const all = cursor ? [...coords, cursor] : coords;
  if (tool === 'measure-area' || tool === 'polygon') {
    if (all.length < 3) {
      return {
        type: 'FeatureCollection' as const,
        features: [
          {
            type: 'Feature' as const,
            properties: {},
            geometry: { type: 'LineString' as const, coordinates: all },
          },
        ],
      };
    }
    return {
      type: 'FeatureCollection' as const,
      features: [
        {
          type: 'Feature' as const,
          properties: {},
          geometry: { type: 'Polygon' as const, coordinates: [[...all, all[0]]] },
        },
      ],
    };
  }
  return {
    type: 'FeatureCollection' as const,
    features: [
      {
        type: 'Feature' as const,
        properties: {},
        geometry: { type: 'LineString' as const, coordinates: all },
      },
    ],
  };
}

function vertexData(coords: LngLat[]) {
  return {
    type: 'FeatureCollection' as const,
    features: coords.map((coordinates, index) => ({
      type: 'Feature' as const,
      properties: { index },
      geometry: { type: 'Point' as const, coordinates },
    })),
  };
}

const emptyCollection = { type: 'FeatureCollection' as const, features: [] };

export default function MapView(props: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const initialized = useRef(false);
  const latest = useRef(props);
  latest.current = props;
  const draft = useRef<LngLat[]>([]);
  const cursor = useRef<LngLat | null>(null);
  const drag = useRef<{ feature: GeoFeature; index: number; moved: boolean; geometry: any } | null>(null);
  const toolRef = useRef<MapTool>('pan');
  toolRef.current = props.tool;
  const [draftCount, setDraftCount] = useState(0);

  const drawLayer = useCallback((tool: MapTool) => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource('nasmap-preview') as maplibregl.GeoJSONSource | undefined;
    source?.setData(previewData(tool, draft.current, cursor.current) as any);
    const verticesSource = map.getSource('nasmap-draft-vertices') as
      | maplibregl.GeoJSONSource
      | undefined;
    verticesSource?.setData(vertexData(draft.current) as any);
  }, []);

  const updateMeasure = useCallback((tool: MapTool, coords: LngLat[]) => {
    if (tool === 'measure-distance') {
      if (coords.length >= 2) {
        const total = lineLength(coords);
        latest.current.onMeasure({ kind: 'distance', value: total, label: formatDistance(total) });
      } else {
        latest.current.onMeasure(null);
      }
    } else if (tool === 'measure-area') {
      if (coords.length >= 3) {
        const area = ringArea(coords);
        latest.current.onMeasure({ kind: 'area', value: area, label: formatArea(area) });
      } else {
        latest.current.onMeasure(null);
      }
    }
  }, []);

  const clearDraft = useCallback(() => {
    draft.current = [];
    cursor.current = null;
    setDraftCount(0);
    drawLayer(toolRef.current);
    latest.current.onMeasure(null);
  }, [drawLayer]);

  const undoDraft = useCallback(() => {
    draft.current = draft.current.slice(0, -1);
    setDraftCount(draft.current.length);
    drawLayer(toolRef.current);
    updateMeasure(toolRef.current, draft.current);
  }, [drawLayer, updateMeasure]);

  const finishDraft = useCallback(async () => {
    const active = toolRef.current;
    const coords = draft.current;
    if (active === 'line' || active === 'polygon') {
      const unique = coords.filter(
        (coord, index) =>
          index === 0 ||
          coord[0] !== coords[index - 1][0] ||
          coord[1] !== coords[index - 1][1],
      );
      const minimum = active === 'line' ? 2 : 3;
      if (unique.length < minimum || !latest.current.activeLayerId) return;
      const geometry =
        active === 'line'
          ? { type: 'LineString', coordinates: unique }
          : { type: 'Polygon', coordinates: [[...unique, unique[0]]] };
      const created = await latest.current.onCreateFeature(
        latest.current.activeLayerId,
        geometry,
      );
      if (!created) return;
      draft.current = [];
      cursor.current = null;
      setDraftCount(0);
      drawLayer(active);
      latest.current.onToolComplete?.();
      return;
    }
    if (active === 'measure-distance' || active === 'measure-area') {
      updateMeasure(active, coords);
      draft.current = [];
      cursor.current = null;
      setDraftCount(0);
      drawLayer(active);
      latest.current.onToolComplete?.();
    }
  }, [drawLayer, updateMeasure]);

  const syncOverlays = useCallback(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const current = latest.current;
    const style = map.getStyle();
    for (const layer of style.layers ?? []) {
      if (layer.id.startsWith('nasmap-')) {
        try {
          map.removeLayer(layer.id);
        } catch {
          /* already gone */
        }
      }
    }
    for (const id of Object.keys(style.sources ?? {})) {
      if (id.startsWith('nasmap-')) {
        try {
          map.removeSource(id);
        } catch {
          /* in use by another layer */
        }
      }
    }

    for (const layer of current.layers) {
      const sourceId = `nasmap-src-${layer.id}`;
      const visible = current.visible[layer.id] !== false;
      const opacity = current.opacity[layer.id] ?? 1;
      const meta = layer.metadata || {};
      if (meta.vector_tiles) {
        const vector = meta.vector_tiles;
        const vectorSource: any = {
          type: 'vector',
          tiles: [vectorTileUrl(layer.id)],
          minzoom: vector.minzoom ?? 0,
          maxzoom: vector.maxzoom ?? 22,
          attribution: layer.attribution || '',
        };
        map.addSource(sourceId, vectorSource);
        const vs = layer.style || {};
        const sourceLayer = vector.source_layer;
        const vis = visible ? 'visible' : 'none';
        map.addLayer({
          id: `nasmap-lyr-${layer.id}-fill`,
          type: 'fill',
          source: sourceId,
          'source-layer': sourceLayer,
          filter: ['==', ['geometry-type'], 'Polygon'],
          layout: { visibility: vis },
          paint: {
            'fill-color': vs.fillColor || vs.color || '#7c3aed',
            'fill-opacity': (vs.fillOpacity ?? 0.16) * opacity,
          },
        } as any);
        map.addLayer({
          id: `nasmap-lyr-${layer.id}-line`,
          type: 'line',
          source: sourceId,
          'source-layer': sourceLayer,
          filter: ['in', ['geometry-type'], ['literal', ['LineString', 'Polygon']]],
          layout: { visibility: vis },
          paint: {
            'line-color': vs.color || '#7c3aed',
            'line-width': vs.lineWidth ?? 1.1,
            'line-opacity': opacity,
          },
        } as any);
        map.addLayer({
          id: `nasmap-lyr-${layer.id}-point`,
          type: 'circle',
          source: sourceId,
          'source-layer': sourceLayer,
          filter: ['==', ['geometry-type'], 'Point'],
          layout: { visibility: vis },
          paint: {
            'circle-color': vs.color || '#7c3aed',
            'circle-radius': vs.circleRadius ?? 4,
            'circle-opacity': opacity,
          },
        } as any);
        continue;
      }
      if (layer.geometry_type === 'raster') {
        let tiles: string[];
        if (meta.wms) tiles = [wmsTileUrl(layer.id)];
        else tiles = [tileUrl(layer.id)];
        const xyz = meta.xyz || {};
        const rasterStyle = layer.style || {};
        const bounds = meta.total_bounds || meta.raster?.bounds_wgs84;
        const rasterSource: any = {
          type: 'raster',
          tiles,
          tileSize: xyz.tile_size || 256,
          attribution: xyz.attribution || layer.attribution || '',
        };
        if (xyz.minzoom !== undefined) rasterSource.minzoom = xyz.minzoom;
        if (xyz.maxzoom !== undefined) rasterSource.maxzoom = xyz.maxzoom;
        if (Array.isArray(bounds) && bounds.length === 4) rasterSource.bounds = bounds;
        map.addSource(sourceId, rasterSource);
        map.addLayer({
          id: `nasmap-lyr-${layer.id}`,
          type: 'raster',
          source: sourceId,
          layout: { visibility: visible ? 'visible' : 'none' },
          paint: { 'raster-opacity': opacity * (rasterStyle.opacity ?? 1) },
        } as any);
        continue;
      }
      const data = current.layerData[layer.id];
      if (!data) continue;
      const renderData = {
        ...data,
        features: data.features.map((feature, index) => ({
          ...feature,
          id: index,
          properties: { ...(feature.properties || {}), __nasmap_id: feature.id },
        })),
      };
      map.addSource(sourceId, { type: 'geojson', data: renderData as any });
      const s = layer.style || {};
      const color = s.color || '#2563eb';
      const fill = s.fillColor || color;
      const baseOpacity = s.opacity ?? 1;
      map.addLayer({
        id: `nasmap-lyr-${layer.id}-fill`,
        type: 'fill',
        source: sourceId,
        filter: ['in', ['geometry-type'], ['literal', ['Polygon', 'MultiPolygon']]],
        layout: { visibility: visible ? 'visible' : 'none' },
        paint: {
          'fill-color': fill,
          'fill-opacity': (s.fillOpacity ?? 0.25) * opacity * baseOpacity,
        },
      } as any);
      map.addLayer({
        id: `nasmap-lyr-${layer.id}-line`,
        type: 'line',
        source: sourceId,
        filter: ['in', ['geometry-type'], ['literal', ['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon']]],
        layout: {
          visibility: visible ? 'visible' : 'none',
          'line-join': 'round',
          'line-cap': 'round',
        },
        paint: {
          'line-color': color,
          'line-width': s.lineWidth ?? 2.5,
          'line-opacity': opacity * baseOpacity,
        },
      } as any);
      const provider = meta.provider;
      const pointPaint: any = {
        'circle-radius': s.circleRadius ?? 6,
        'circle-color': color,
        'circle-opacity': opacity * baseOpacity,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1.5,
      };
      if (provider === 'open-meteo') {
        pointPaint['circle-color'] = [
          'interpolate',
          ['linear'],
          ['coalesce', ['get', 'temperature_c'], 10],
          -10,
          '#1d4ed8',
          0,
          '#0ea5e9',
          10,
          '#eab308',
          20,
          '#f97316',
          30,
          '#dc2626',
        ];
        pointPaint['circle-radius'] = 7;
      } else if (provider === 'usgs-earthquakes') {
        pointPaint['circle-radius'] = [
          'interpolate',
          ['linear'],
          ['coalesce', ['get', 'magnitude'], 1],
          0,
          4,
          4,
          8,
          7,
          18,
        ];
        pointPaint['circle-color'] = '#dc2626';
        pointPaint['circle-opacity'] = 0.72 * opacity;
      }
      map.addLayer({
        id: `nasmap-lyr-${layer.id}-point`,
        type: 'circle',
        source: sourceId,
        filter: ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]],
        layout: { visibility: visible ? 'visible' : 'none' },
        paint: pointPaint,
      } as any);
      // Larger transparent target so small points remain easy to select.
      map.addLayer({
        id: `nasmap-lyr-${layer.id}-hit`,
        type: 'circle',
        source: sourceId,
        filter: ['in', ['geometry-type'], ['literal', ['Point', 'MultiPoint']]],
        layout: { visibility: visible ? 'visible' : 'none' },
        paint: {
          'circle-radius': Math.max(14, (s.circleRadius ?? 6) + 8),
          'circle-color': '#000000',
          'circle-opacity': 0.001,
        },
      } as any);
    }

    const selected = current.selectedFeature;
    if (selected?.geometry) {
      map.addSource('nasmap-selection', {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: selected.geometry } as any,
      });
      map.addLayer({
        id: 'nasmap-selection-line',
        type: 'line',
        source: 'nasmap-selection',
        paint: { 'line-color': '#f59e0b', 'line-width': 5, 'line-opacity': 0.8 },
      } as any);
      map.addLayer({
        id: 'nasmap-selection-point',
        type: 'circle',
        source: 'nasmap-selection',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': 10,
          'circle-color': '#f59e0b',
          'circle-opacity': 0.35,
          'circle-stroke-color': '#f59e0b',
          'circle-stroke-width': 2,
        },
      } as any);
    }
    if (current.editable && current.selectedFeature) {
      map.addSource('nasmap-edit-handles', { type: 'geojson', data: handlesData(current.selectedFeature) as any });
      map.addLayer({
        id: 'nasmap-edit-handles',
        type: 'circle',
        source: 'nasmap-edit-handles',
        paint: {
          'circle-radius': 6,
          'circle-color': '#ffffff',
          'circle-stroke-color': '#0f172a',
          'circle-stroke-width': 2,
        },
      } as any);
    }
    map.addSource('nasmap-preview', { type: 'geojson', data: emptyCollection as any });
    map.addLayer({
      id: 'nasmap-preview-line',
      type: 'line',
      source: 'nasmap-preview',
      filter: ['in', ['geometry-type'], ['literal', ['LineString', 'Polygon']]],
      paint: { 'line-color': '#f59e0b', 'line-width': 2.5, 'line-dasharray': [2, 1] },
    } as any);
    map.addLayer({
      id: 'nasmap-preview-fill',
      type: 'fill',
      source: 'nasmap-preview',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.15 },
    } as any);
    map.addSource('nasmap-draft-vertices', { type: 'geojson', data: emptyCollection as any });
    map.addLayer({
      id: 'nasmap-draft-vertices',
      type: 'circle',
      source: 'nasmap-draft-vertices',
      paint: {
        'circle-radius': 5,
        'circle-color': '#ffffff',
        'circle-stroke-color': '#0f172a',
        'circle-stroke-width': 1.75,
      },
    } as any);
    drawLayer(toolRef.current);
  }, [drawLayer]);

  const setStyle = useCallback(
    async (basemap: 'remote' | 'local') => {
      const map = mapRef.current;
      if (!map) return;
      let style: any = remoteStyle(latest.current.osmTileUrl, latest.current.osmAttribution);
      if (basemap === 'local') {
        try {
          const tileserver = latest.current.tileserverUrl.replace(/\/$/, '');
          const response = await fetch(`${tileserver}/styles/nasmap/style.json`);
          if (response.ok) {
            style = await response.json();
            // TileServer GL uses mbtiles://{id} references. Resolve them to
            // TileJSON URLs under the public /tiles prefix so MapLibre can
            // fetch them through Caddy.
            for (const source of Object.values<any>(style.sources ?? {})) {
              if (typeof source?.url === 'string' && source.url.startsWith('mbtiles://')) {
                const id = source.url.replace('mbtiles://', '').replace(/[{}]/g, '');
                source.url = `${tileserver}/data/${id}.json`;
              }
            }
          }
        } catch {
          style = remoteStyle(latest.current.osmTileUrl, latest.current.osmAttribution);
        }
      }
      map.setStyle(style, { diff: false });
      map.once('style.load', syncOverlays);
    },
    [syncOverlays],
  );

  useEffect(() => {
    if (initialized.current || !containerRef.current) return;
    initialized.current = true;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: remoteStyle(props.osmTileUrl, props.osmAttribution),
      center: [4.9, 20],
      zoom: 1.8,
      attributionControl: { compact: true },
      transformRequest: (url, resourceType) => {
        const token = getAccessToken();
        if (token && (url.startsWith('/api/') || url.includes('/api/v1/'))) {
          return { url, headers: { Authorization: `Bearer ${token}` }, resourceType } as any;
        }
        return { url, resourceType } as any;
      },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    map.addControl(
      new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: false,
        showAccuracyCircle: true,
        fitBoundsOptions: { maxZoom: 15 },
      }),
      'top-right',
    );
    map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
    map.on('load', () => {
      syncOverlays();
      props.onMapReady?.(map);
    });
    if (props.basemap === 'local') void setStyle('local');
    return () => {
      map.remove();
      mapRef.current = null;
      initialized.current = false;
    };
    // Map is intentionally created once; config changes update overlays.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (props.basemap === 'local') void setStyle('local');
    else void setStyle('remote');
  }, [props.basemap, setStyle]);

  useEffect(() => {
    syncOverlays();
  }, [props.layerData, props.layers, props.visible, props.opacity, props.selectedFeature, props.editable, syncOverlays]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const active = props.tool;
    if (active === 'pan') {
      draft.current = [];
      cursor.current = null;
      setDraftCount(0);
      drawLayer('pan');
      map.getCanvas().style.cursor = '';
      return;
    }
    map.doubleClickZoom.disable();
    map.getCanvas().style.cursor = 'crosshair';
    draft.current = [];
    cursor.current = null;
    setDraftCount(0);
    drawLayer(active);
    latest.current.onMeasure(null);

    const onClick = (event: maplibregl.MapMouseEvent) => {
      const coord: LngLat = [event.lngLat.lng, event.lngLat.lat];
      if (active === 'point') {
        if (latest.current.activeLayerId) {
          void latest.current.onCreateFeature(latest.current.activeLayerId, {
            type: 'Point',
            coordinates: coord,
          });
        }
        return;
      }
      if (active === 'polygon' && draft.current.length >= 3) {
        const first = map.project(draft.current[0]);
        if (Math.hypot(event.point.x - first.x, event.point.y - first.y) < 12) {
          void finishDraft();
          return;
        }
      }
      draft.current = [...draft.current, coord];
      setDraftCount(draft.current.length);
      drawLayer(active);
      updateMeasure(active, draft.current);
    };
    const onMove = (event: maplibregl.MapMouseEvent) => {
      if (active === 'point') return;
      cursor.current = [event.lngLat.lng, event.lngLat.lat];
      drawLayer(active);
    };
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(target.tagName)) return;
      if (event.key === 'Escape') {
        clearDraft();
        latest.current.onToolComplete?.();
      } else if (event.key === 'Backspace') {
        event.preventDefault();
        undoDraft();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        void finishDraft();
      }
    };
    map.on('click', onClick);
    map.on('mousemove', onMove);
    document.addEventListener('keydown', onKey);
    return () => {
      map.off('click', onClick);
      map.off('mousemove', onMove);
      document.removeEventListener('keydown', onKey);
      map.doubleClickZoom.enable();
      map.getCanvas().style.cursor = '';
    };
  }, [props.tool, drawLayer, clearDraft, undoDraft, finishDraft, updateMeasure]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const onFeatureClick = (event: any) => {
      if (toolRef.current !== 'pan') return;
      const features = map.queryRenderedFeatures(event.point).filter((f) =>
        f.layer.id.startsWith('nasmap-lyr-'),
      );
      const hit =
        features.find((f) => f.layer.id.endsWith('-hit')) ||
        features.find((f) => f.layer.id.endsWith('-point')) ||
        features.find((f) => f.layer.id.endsWith('-line')) ||
        features.find((f) => f.layer.id.endsWith('-fill'));
      if (!hit) {
        latest.current.onSelectFeature('', null);
        return;
      }
      const layerId = String(hit.layer.id)
        .replace('nasmap-lyr-', '')
        .replace(/-(fill|line|point|hit)$/, '');
      const id = hit.properties?.__nasmap_id ?? hit.properties?.id ?? hit.id;
      const collection = latest.current.layerData[layerId];
      const feature =
        collection?.features.find((f) => String(f.id) === String(id)) ??
        (typeof hit.id === 'number' ? collection?.features[hit.id] : undefined);
      if (feature) latest.current.onSelectFeature(layerId, feature);
    };

    const onHandleDown = (event: any) => {
      const feature = latest.current.selectedFeature;
      if (!feature || !latest.current.editable || toolRef.current !== 'pan') return;
      const handle = map.queryRenderedFeatures(event.point, { layers: ['nasmap-edit-handles'] })[0];
      if (!handle) return;
      event.preventDefault?.();
      drag.current = {
        feature,
        index: Number(handle.properties?.index ?? 0),
        moved: false,
        geometry: feature.geometry,
      };
      map.dragPan.disable();
      map.getCanvas().style.cursor = 'grabbing';
    };

    const onMove = (event: any) => {
      if (!drag.current) return;
      drag.current.moved = true;
      const geometry = moveVertex(
        drag.current.feature.geometry,
        drag.current.index,
        [event.lngLat.lng, event.lngLat.lat],
      );
      drag.current.geometry = geometry;
      const source = map.getSource('nasmap-edit-handles') as maplibregl.GeoJSONSource | undefined;
      const movedFeature = { ...drag.current.feature, geometry };
      source?.setData(handlesData(movedFeature) as any);
      const selection = map.getSource('nasmap-selection') as maplibregl.GeoJSONSource | undefined;
      selection?.setData({ type: 'Feature', properties: {}, geometry } as any);
    };

    const onUp = async () => {
      if (!drag.current) return;
      const { feature, moved, geometry } = drag.current;
      drag.current = null;
      map.dragPan.enable();
      map.getCanvas().style.cursor = '';
      if (!moved) return;
      await latest.current.onUpdateGeometry(feature, geometry);
    };

    const onHover = (event: any) => {
      if (toolRef.current !== 'pan' || drag.current) return;
      const hit = map.queryRenderedFeatures(event.point).some(
        (f) =>
          f.layer.id.startsWith('nasmap-lyr-') &&
          (f.layer.id.endsWith('-hit') ||
            f.layer.id.endsWith('-fill') ||
            f.layer.id.endsWith('-line') ||
            f.layer.id.endsWith('-point')),
      );
      map.getCanvas().style.cursor = hit ? 'pointer' : '';
    };

    map.on('click', onFeatureClick);
    map.on('mousedown', 'nasmap-edit-handles', onHandleDown);
    map.on('mousemove', onMove);
    map.on('mousemove', onHover);
    map.on('mouseup', onUp);
    return () => {
      map.off('click', onFeatureClick);
      map.off('mousedown', 'nasmap-edit-handles', onHandleDown);
      map.off('mousemove', onMove);
      map.off('mousemove', onHover);
      map.off('mouseup', onUp);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    try {
      map.setLayoutProperty(
        'nasmap-edit-handles',
        'visibility',
        props.tool === 'pan' ? 'visible' : 'none',
      );
    } catch {
      /* handles may not exist yet */
    }
  }, [props.tool, props.selectedFeature, props.editable]);

  const drawing = props.tool !== 'pan';
  const measuring = props.tool === 'measure-distance' || props.tool === 'measure-area';
  const labels: Record<MapTool, string> = {
    pan: 'Select',
    point: 'Point',
    line: 'Line',
    polygon: 'Polygon',
    'measure-distance': 'Distance',
    'measure-area': 'Area',
  };
  const help: Record<MapTool, string> = {
    pan: '',
    point: 'Click the map to place points. The tool stays active for more points.',
    line: 'Click to add vertices. Drag to pan. Press Enter or Finish to complete.',
    polygon:
      'Click to add vertices. Click the first point, press Enter, or use Finish to close it.',
    'measure-distance': 'Click to add measurement points. Drag to pan.',
    'measure-area': 'Click to outline an area. Drag to pan.',
  };
  const minimum = props.tool === 'line' || props.tool === 'measure-distance' ? 2 : 3;
  const canFinish =
    props.tool === 'point' || (draftCount >= minimum && (measuring || Boolean(props.activeLayerId)));

  return (
    <div className="map-view">
      <div ref={containerRef} className="map-canvas" />
      {drawing && (
        <div className="draw-hud" role="status">
          <div className="draw-hud-head">
            <strong>{labels[props.tool]}</strong>
            {props.tool !== 'point' && (
              <span>
                {draftCount} {draftCount === 1 ? 'vertex' : 'vertices'}
              </span>
            )}
          </div>
          <p>{help[props.tool]}</p>
          <div className="draw-hud-actions">
            {props.tool !== 'point' && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={undoDraft}
                disabled={draftCount === 0}
              >
                Undo
              </button>
            )}
            {props.tool === 'point' ? (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => props.onToolComplete?.()}
              >
                Done
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void finishDraft()}
                disabled={!canFinish}
              >
                {measuring ? 'Finish measurement' : 'Finish'}
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                clearDraft();
                props.onToolComplete?.();
              }}
            >
              Cancel
            </button>
          </div>
          <p className="draw-hud-keys">
            {props.tool !== 'point' && <span>Backspace: undo</span>}
            <span>Esc: cancel</span>
            {props.tool !== 'point' && <span>Enter: finish</span>}
          </p>
        </div>
      )}
    </div>
  );
}
