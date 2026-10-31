import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ImportJob, Layer, PublicConfig } from '../api/types';
import { Field, Modal } from './ui';
import PhotoImportForm from './PhotoImportForm';
import ServerIngestForm from './ServerIngestForm';
import TesseraForm from './TesseraForm';

type Tab = 'upload' | 'url' | 'photos' | 'ingest' | 'tessera';

const tabs: { id: Tab; label: string }[] = [
  { id: 'upload', label: 'Upload file' },
  { id: 'url', label: 'From URL' },
  { id: 'photos', label: 'Photos' },
  { id: 'ingest', label: 'Server / NAS' },
  { id: 'tessera', label: 'Tessera' },
];

export default function ImportWizard({
  config,
  layers,
  initialTab = 'upload',
  onClose,
  onJob,
  onPhotosImported,
}: {
  config: PublicConfig;
  layers: Layer[];
  initialTab?: Tab;
  onClose: () => void;
  onJob: (job: ImportJob) => void;
  onPhotosImported: (layerId: string | null) => void;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [appendTo, setAppendTo] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [licence, setLicence] = useState('');
  const [attribution, setAttribution] = useState('');
  const [url, setUrl] = useState('');
  const [kind, setKind] = useState('auto');
  const [wmsLayers, setWmsLayers] = useState('');
  const [refreshDays, setRefreshDays] = useState('');

  useEffect(() => {
    if (tab === 'tessera' && !config.tessera_enabled) setTab('upload');
  }, [tab, config.tessera_enabled]);

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
  const availableTabs = tabs.filter(
    (item) => item.id !== 'tessera' || config.tessera_enabled,
  );

  return (
    <Modal title="Add a layer" onClose={onClose} wide>
      <p className="modal-intro">
        Choose where your data is. Most people start with <strong>Upload file</strong>.
      </p>
      <div className="tabs">
        {availableTabs.map((item) => (
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

      {tab === 'upload' && (
        <div className="stack">
          <p className="muted">
            Choose a file and we will create a layer for it. GeoJSON, GeoPackage, Shapefile ZIP,
            KML/KMZ, GPX, CSV, FlatGeobuf, GML, DXF, GeoParquet and GeoTIFF/COG up to{' '}
            {config.max_upload_mb} MB.
          </p>
          <label className="file-drop">
            <input
              type="file"
              accept=".geojson,.json,.gpkg,.zip,.shp,.kml,.kmz,.gpx,.csv,.fgb,.gml,.dxf,.parquet,.tif,.tiff"
              onChange={(e) => {
                const selected = e.target.files?.[0] ?? null;
                setFile(selected);
                if (selected && !name) setName(selected.name.replace(/\.[^.]+$/, ''));
              }}
            />
            <strong>{file ? file.name : 'Choose a file'}</strong>
            <small>{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : 'click to browse'}</small>
          </label>
          <Field
            label="Layer name"
            hint={file ? 'Change it if you like — otherwise the filename is used.' : undefined}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Uses the filename"
            />
          </Field>
          <details className="advanced-options">
            <summary>Advanced options</summary>
            <div className="stack">
              <div className="grid-2">
                <Field
                  label="Add to an existing layer"
                  help="Adds the file’s features to an existing vector layer instead of creating a new one. The geometry type must be compatible."
                >
                  <select value={appendTo} onChange={(e) => setAppendTo(e.target.value)}>
                    <option value="">Create a new layer</option>
                    {vectorLayers.map((layer) => (
                      <option key={layer.id} value={layer.id}>
                        {layer.name}
                      </option>
                    ))}
                  </select>
                </Field>
                {!appendTo && (
                  <Field label="Visibility">
                    <select value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)}>
                      <option value="private">Private — only me</option>
                      <option value="organisation">Internal — everyone here</option>
                      <option value="public">Public — everyone here</option>
                    </select>
                  </Field>
                )}
              </div>
              <div className="grid-2">
                <Field label="Licence">
                  <input value={licence} onChange={(e) => setLicence(e.target.value)} placeholder="ODbL, CC-BY…" />
                </Field>
                <Field label="Attribution">
                  <input value={attribution} onChange={(e) => setAttribution(e.target.value)} />
                </Field>
              </div>
            </div>
          </details>
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
            Paste a direct file link or a WMS, WFS, ArcGIS or STAC service URL. Strata detects the
            type automatically when it can.
          </p>
          <Field label="URL" help="Use the direct data or service URL. WMS needs layer names; WFS can often discover its feature type.">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.org/data.geojson"
            />
          </Field>
          <div className="grid-2">
            <Field label="Type" help="Auto-detect uses the URL, response headers and extension. Choose a type manually if detection is ambiguous.">
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
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Optional — names it automatically"
              />
            </Field>
          </div>
          {kind === 'wms' && (
            <Field label="WMS layers" hint="Comma separated layer names from the WMS capabilities.">
              <input value={wmsLayers} onChange={(e) => setWmsLayers(e.target.value)} />
            </Field>
          )}
          <details className="advanced-options">
            <summary>Advanced options</summary>
            <div className="stack">
              <div className="grid-2">
                <Field
                  label="Add to an existing layer"
                  help="Adds the imported features to an existing vector layer instead of creating a new one."
                >
                  <select value={appendTo} onChange={(e) => setAppendTo(e.target.value)}>
                    <option value="">Create a new layer</option>
                    {vectorLayers.map((layer) => (
                      <option key={layer.id} value={layer.id}>
                        {layer.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label="Refresh automatically"
                  hint="Optional. Re-download this source on a schedule."
                  help="Strata re-downloads the source on this schedule and replaces features that came from it."
                >
                  <select value={refreshDays} onChange={(e) => setRefreshDays(e.target.value)}>
                    <option value="">Never</option>
                    <option value="1">Every day</option>
                    <option value="7">Every week</option>
                    <option value="30">Every month</option>
                  </select>
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
            </div>
          </details>
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
