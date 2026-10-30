import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';

interface Props {
  bbox: [number, number, number, number] | null;
  osmTileUrl: string;
  attribution: string;
  onChange: (bbox: [number, number, number, number]) => void;
  height?: number;
  tileBoxes?: number[][];
}

function rectangle(bbox: [number, number, number, number] | null) {
  if (!bbox) return { type: 'FeatureCollection' as const, features: [] };
  const [w, s, e, n] = bbox;
  return {
    type: 'FeatureCollection' as const,
    features: [
      {
        type: 'Feature' as const,
        properties: {},
        geometry: {
          type: 'Polygon' as const,
          coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
      },
    ],
  };
}

function tilesCollection(boxes: number[][]) {
  return {
    type: 'FeatureCollection' as const,
    features: boxes.map(([w, s, e, n]) => ({
      type: 'Feature' as const,
      properties: {},
      geometry: {
        type: 'Polygon' as const,
        coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
      },
    })),
  };
}

export default function BBoxPicker({ bbox, osmTileUrl, attribution, onChange, height = 260, tileBoxes = [] }: Props) {
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const start = useRef<[number, number] | null>(null);
  const current = useRef<[number, number, number, number] | null>(bbox);

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          osm: { type: 'raster', tiles: [osmTileUrl], tileSize: 256, attribution, maxzoom: 19 },
        },
        layers: [
          { id: 'bg', type: 'background', paint: { 'background-color': '#e9eef2' } },
          { id: 'osm', type: 'raster', source: 'osm' },
        ],
      },
      center: bbox ? [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2] : [4.9, 20],
      zoom: bbox ? 7 : 1.8,
      attributionControl: { compact: true },
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.on('load', () => {
      map.addSource('tessera-tiles', { type: 'geojson', data: tilesCollection(tileBoxes) as any });
      map.addLayer({
        id: 'tessera-fill',
        type: 'fill',
        source: 'tessera-tiles',
        paint: { 'fill-color': '#22c55e', 'fill-opacity': 0.12 },
      });
      map.addLayer({
        id: 'tessera-line',
        type: 'line',
        source: 'tessera-tiles',
        paint: { 'line-color': '#16a34a', 'line-width': 1 },
      });
      map.addSource('bbox', { type: 'geojson', data: rectangle(current.current) as any });
      map.addLayer({
        id: 'bbox-fill',
        type: 'fill',
        source: 'bbox',
        paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.14 },
      });
      map.addLayer({
        id: 'bbox-line',
        type: 'line',
        source: 'bbox',
        paint: { 'line-color': '#2563eb', 'line-width': 2, 'line-dasharray': [2, 1] },
      });
    });
    map.on('mousedown', (event) => {
      start.current = [event.lngLat.lng, event.lngLat.lat];
      map.dragPan.disable();
      map.getCanvas().style.cursor = 'crosshair';
    });
    map.on('mousemove', (event) => {
      if (!start.current) return;
      const [w, s] = start.current;
      const e = event.lngLat.lng;
      const n = event.lngLat.lat;
      const box: [number, number, number, number] = [
        Math.min(w, e),
        Math.min(s, n),
        Math.max(w, e),
        Math.max(s, n),
      ];
      current.current = box;
      (map.getSource('bbox') as maplibregl.GeoJSONSource | undefined)?.setData(rectangle(box) as any);
    });
    const finish = () => {
      if (!start.current) return;
      start.current = null;
      map.dragPan.enable();
      map.getCanvas().style.cursor = '';
      const box = current.current;
      if (box && box[2] - box[0] > 0.0001 && box[3] - box[1] > 0.0001) onChange(box);
    };
    map.on('mouseup', finish);
    map.on('mouseout', () => {
      if (start.current) finish();
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    current.current = bbox;
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    (map.getSource('bbox') as maplibregl.GeoJSONSource | undefined)?.setData(rectangle(bbox) as any);
    if (bbox) map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 20, maxZoom: 12 });
  }, [bbox]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    (map.getSource('tessera-tiles') as maplibregl.GeoJSONSource | undefined)?.setData(
      tilesCollection(tileBoxes) as any,
    );
  }, [tileBoxes]);

  return <div ref={container} className="bbox-map" style={{ height }} />;
}
