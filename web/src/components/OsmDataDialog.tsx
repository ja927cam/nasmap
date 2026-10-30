import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { usePublicConfig } from '../api/config';
import type { ImportJob, Layer } from '../api/types';
import BBoxPicker from './BBoxPicker';
import GeoSearch from './GeoSearch';
import { ErrorBox, Field, Modal } from './ui';

interface CategoryInfo {
  id: string;
  label: string;
}

interface CategoryResponse {
  enabled: boolean;
  categories: CategoryInfo[];
  max_area_deg2: number;
  overpass_url: string;
}

export default function OsmDataDialog({
  initialBBox,
  layers,
  onClose,
  onJob,
}: {
  initialBBox: [number, number, number, number];
  layers: Layer[];
  onClose: () => void;
  onJob: (job: ImportJob) => void;
}) {
  const config = usePublicConfig();
  const [categories, setCategories] = useState<CategoryResponse | null>(null);
  const [bbox, setBbox] = useState<[number, number, number, number]>(initialBBox);
  const [category, setCategory] = useState('buildings');
  const [name, setName] = useState('OSM buildings');
  const [layerId, setLayerId] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<CategoryResponse>('/osm/data/categories')
      .then((data) => {
        setCategories(data);
        setCategory((current) =>
          data.categories.some((item) => item.id === current)
            ? current
            : (data.categories[0]?.id ?? current),
        );
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load OSM categories'));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await api<ImportJob>('/osm/import', {
        method: 'POST',
        body: {
          bbox,
          category,
          name,
          layer_id: layerId || undefined,
          visibility,
        },
      });
      onJob(job);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start OSM import');
    } finally {
      setBusy(false);
    }
  }

  const area = useMemo(
    () => Math.max(0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])),
    [bbox],
  );
  const tooLarge = Boolean(categories && area > categories.max_area_deg2);
  const vectorLayers = layers.filter((layer) =>
    ['point', 'line', 'polygon', 'geometry'].includes(layer.geometry_type),
  );

  return (
    <Modal title="Import OSM data" onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <div className="warning-box">
          Imports a local, editable copy of OpenStreetMap data. Changes stay in NasMap and are
          not uploaded back to OSM automatically.
        </div>

        {!categories ? (
          <p className="muted">Loading OSM categories…</p>
        ) : !categories.enabled ? (
          <div className="warning-box">OSM data import is disabled on this server.</div>
        ) : (
          <div className="osm-area-layout">
            <div className="stack">
              <Field label="OSM data">
                <select
                  value={category}
                  onChange={(e) => {
                    setCategory(e.target.value);
                    setName(`OSM ${e.target.value.replace('_', ' ')}`);
                  }}
                >
                  {categories.categories.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Layer name">
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </Field>
              <Field label="Append to existing layer" hint="Leave empty to create a new editable OSM layer.">
                <select value={layerId} onChange={(e) => setLayerId(e.target.value)}>
                  <option value="">Create a new layer</option>
                  {vectorLayers.map((layer) => (
                    <option key={layer.id} value={layer.id}>
                      {layer.name}
                    </option>
                  ))}
                </select>
              </Field>
              {!layerId && (
                <Field label="Visibility">
                  <select
                    value={visibility}
                    onChange={(e) => setVisibility(e.target.value as typeof visibility)}
                  >
                    <option value="private">Private</option>
                    <option value="organisation">Internal</option>
                    <option value="public">Public</option>
                  </select>
                </Field>
              )}
              <div className="bbox-readout">
                <span>W {bbox[0].toFixed(5)}</span>
                <span>S {bbox[1].toFixed(5)}</span>
                <span>E {bbox[2].toFixed(5)}</span>
                <span>N {bbox[3].toFixed(5)}</span>
              </div>
              <p className="hint">
                Selected area: {area.toFixed(5)} deg² · limit {categories.max_area_deg2} deg²
              </p>
              {tooLarge && (
                <div className="warning-box">
                  This area is too large. Zoom in or drag a smaller rectangle on the map.
                </div>
              )}
              <p className="hint">
                Data source: {categories.overpass_url}. Closed features become polygons, roads
                become lines, nodes become points. OSM tags and IDs are preserved.
              </p>
            </div>

            <div className="osm-area-map">
              <GeoSearch
                onSelect={(box) => setBbox([box[0], box[1], box[2], box[3]])}
              />
              <BBoxPicker
                bbox={bbox}
                osmTileUrl={config?.osm_tile_url ?? '/api/v1/basemap/osm/{z}/{x}/{y}.png'}
                attribution={config?.osm_tile_attribution ?? '© OpenStreetMap contributors'}
                onChange={setBbox}
                height={360}
              />
              <p className="hint">Drag a rectangle on the map, or search for a place above.</p>
            </div>
          </div>
        )}

        <ErrorBox message={error} />
        <div className="button-row end">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={busy || !categories?.enabled || !name.trim() || tooLarge}
          >
            {busy ? 'Starting…' : 'Import as editable layer'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
