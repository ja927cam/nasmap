import { useState } from 'react';
import { api } from '../api/client';
import type { ImportJob, Layer, PublicConfig } from '../api/types';
import { Field, Modal } from './ui';
import PhotoImportForm from './PhotoImportForm';
import ServerIngestForm from './ServerIngestForm';
import TesseraForm from './TesseraForm';

type Tab = 'upload' | 'url' | 'photos' | 'ingest' | 'manual' | 'tessera';

const tabs: { id: Tab; label: string }[] = [
  { id: 'upload', label: 'Upload file' },
  { id: 'url', label: 'From URL' },
  { id: 'photos', label: 'Photos' },
  { id: 'ingest', label: 'Server / NAS' },
  { id: 'manual', label: 'Blank layer' },
  { id: 'tessera', label: 'Tessera' },
];

export default function ImportWizard({
  config,
  layers,
  initialTab = 'upload',
  onClose,
  onLayerCreated,
  onJob,
  onPhotosImported,
}: {
  config: PublicConfig;
  layers: Layer[];
  initialTab?: Tab;
  onClose: () => void;
  onLayerCreated: (layer: Layer) => void;
  onJob: (job: ImportJob) => void;
  onPhotosImported: (layerId: string | null) => void;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [geometryType, setGeometryType] = useState('point');
  const [appendTo, setAppendTo] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [licence, setLicence] = useState('');
  const [attribution, setAttribution] = useState('');
  const [url, setUrl] = useState('');
  const [kind, setKind] = useState('auto');
  const [wmsLayers, setWmsLayers] = useState('');
  const [refreshDays, setRefreshDays] = useState('');

  async function createManual() {
    setBusy(true);
    setError(null);
    try {
      const layer = await api<Layer>('/layers', {
        method: 'POST',
        body: {
          name,
          description,
          visibility,
          geometry_type: geometryType,
          source_type: 'manual',
        },
      });
      onLayerCreated(layer);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create layer');
    } finally {
      setBusy(false);
    }
  }

  async function uploadFile() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append('file', file);
      if (name) form.append('name', name);
      if (appendTo) form.append('layer_id', appendTo);
      form.append('visibility', appendTo ? 'private' : visibility);
      form.append('licence', licence);
      form.append('attribution', attribution);
      const job = await api<ImportJob>('/uploads', { method: 'POST', body: form });
      onJob(job);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setBusy(false);
    }
  }

  async function importUrl() {
    setBusy(true);
    setError(null);
    try {
      const job = await api<ImportJob>('/imports/url', {
        method: 'POST',
        body: {
          url,
          name: name || undefined,
          kind,
          layer_id: appendTo || undefined,
          visibility,
          licence,
          attribution,
          refresh_interval_seconds: refreshDays ? Math.round(Number(refreshDays) * 86400) : undefined,
          wms_layers: kind === 'wms' ? wmsLayers : undefined,
        },
      });
      onJob(job);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'URL import failed');
    } finally {
      setBusy(false);
    }
  }

  const vectorLayers = layers.filter((layer) => !['raster', 'table'].includes(layer.geometry_type));

  return (
    <Modal title="Add layer" onClose={onClose} wide>
      <div className="tabs">
        {tabs.map((item) => (
          <button
            key={item.id}
            className={tab === item.id ? 'tab active' : 'tab'}
            onClick={() => {
              setTab(item.id);
              setError(null);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'manual' && (
        <div className="stack">
          <p className="muted">
            Create an empty layer, then draw points, lines or polygons on the map.
          </p>
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Field survey" />
          </Field>
          <Field label="Description">
            <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <div className="grid-2">
            <Field label="Geometry type">
              <select value={geometryType} onChange={(e) => setGeometryType(e.target.value)}>
                <option value="point">Point</option>
                <option value="line">Line</option>
                <option value="polygon">Polygon</option>
                <option value="geometry">Mixed geometry</option>
              </select>
            </Field>
            <Field label="Visibility">
              <select value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)}>
                <option value="private">Private</option>
                <option value="organisation">Internal</option>
                <option value="public">Public</option>
              </select>
            </Field>
          </div>
          <div className="button-row end">
            <button className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={createManual}>
              {busy ? 'Creating…' : 'Create layer'}
            </button>
          </div>
        </div>
      )}

      {tab === 'upload' && (
        <div className="stack">
          <p className="muted">
            GeoJSON, GeoPackage, Shapefile ZIP, KML/KMZ, GPX, CSV (lat/lon, WKT or GeoJSON) and
            GeoTIFF/COG up to {config.max_upload_mb} MB.
          </p>
          <label className="file-drop">
            <input
              type="file"
              accept=".geojson,.json,.gpkg,.zip,.shp,.kml,.kmz,.gpx,.csv,.tif,.tiff"
              onChange={(e) => {
                const selected = e.target.files?.[0] ?? null;
                setFile(selected);
                if (selected && !name) setName(selected.name.replace(/\.[^.]+$/, ''));
              }}
            />
            <strong>{file ? file.name : 'Choose a file'}</strong>
            <small>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : 'click to browse'}</small>
          </label>
          <div className="grid-2">
            <Field label="Layer name">
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Append to existing layer" hint="Leave empty to create a new layer.">
              <select value={appendTo} onChange={(e) => setAppendTo(e.target.value)}>
                <option value="">Create new layer</option>
                {vectorLayers.map((layer) => (
                  <option key={layer.id} value={layer.id}>
                    {layer.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {!appendTo && (
            <div className="grid-2">
              <Field label="Visibility">
                <select value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)}>
                  <option value="private">Private</option>
                  <option value="organisation">Internal</option>
                  <option value="public">Public</option>
                </select>
              </Field>
              <Field label="Licence">
                <input value={licence} onChange={(e) => setLicence(e.target.value)} placeholder="ODbL, CC-BY…" />
              </Field>
            </div>
          )}
          <Field label="Attribution">
            <input value={attribution} onChange={(e) => setAttribution(e.target.value)} />
          </Field>
          <div className="button-row end">
            <button className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!file || busy} onClick={uploadFile}>
              {busy ? 'Uploading…' : 'Upload and import'}
            </button>
          </div>
        </div>
      )}

      {tab === 'url' && (
        <div className="stack">
          <p className="muted">
            Remote files and OGC/ArcGIS/STAC services. Private and link-local addresses are
            blocked; downloads are capped at {config.max_url_import_mb} MB.
          </p>
          <Field label="URL">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.org/data.geojson"
            />
          </Field>
          <div className="grid-2">
            <Field label="Type">
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="auto">Auto-detect</option>
                <option value="geojson">GeoJSON</option>
                <option value="gpkg">GeoPackage</option>
                <option value="cog">GeoTIFF / COG</option>
                <option value="wms">WMS</option>
                <option value="wfs">WFS</option>
                <option value="arcgis">ArcGIS Feature Service</option>
                <option value="stac">STAC item</option>
                <option value="url">Other file URL</option>
              </select>
            </Field>
            <Field label="Layer name">
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
          </div>
          {kind === 'wms' && (
            <Field label="WMS layers" hint="Comma separated layer names from the WMS capabilities.">
              <input value={wmsLayers} onChange={(e) => setWmsLayers(e.target.value)} />
            </Field>
          )}
          <div className="grid-2">
            <Field label="Append to existing layer">
              <select value={appendTo} onChange={(e) => setAppendTo(e.target.value)}>
                <option value="">Create new layer</option>
                {vectorLayers.map((layer) => (
                  <option key={layer.id} value={layer.id}>
                    {layer.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Refresh interval (days)" hint="Optional scheduled refresh for compatible URLs.">
              <input
                type="number"
                min={0}
                value={refreshDays}
                onChange={(e) => setRefreshDays(e.target.value)}
              />
            </Field>
          </div>
          <div className="grid-2">
            <Field label="Licence">
              <input value={licence} onChange={(e) => setLicence(e.target.value)} />
            </Field>
            <Field label="Attribution">
              <input value={attribution} onChange={(e) => setAttribution(e.target.value)} />
            </Field>
          </div>
          <div className="button-row end">
            <button className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!url.startsWith('http') || busy} onClick={importUrl}>
              {busy ? 'Starting…' : 'Start import'}
            </button>
          </div>
        </div>
      )}

      {tab === 'ingest' && (
        <ServerIngestForm
          layers={layers}
          onJob={(job) => {
            onJob(job);
            onClose();
          }}
        />
      )}

      {tab === 'photos' && (
        <PhotoImportForm
          layers={layers}
          onDone={(layerId) => {
            onPhotosImported(layerId);
            if (layerId) onClose();
          }}
        />
      )}

      {tab === 'tessera' && (
        <TesseraForm
          config={config}
          onJob={(job) => {
            onJob(job);
            onClose();
          }}
        />
      )}

      {error && <div className="error-box">{error}</div>}
    </Modal>
  );
}
