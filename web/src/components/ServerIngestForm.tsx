import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ImportJob, Layer } from '../api/types';
import { ErrorBox, Field, formatBytes } from './ui';

interface Root {
  path: string;
  exists: boolean;
  readable: boolean;
}

interface RootsResponse {
  enabled: boolean;
  roots: Root[];
  message?: string;
  max_scan_files: number;
  max_files_per_job: number;
}

interface ScanFile {
  path: string;
  relative_path: string;
  name: string;
  kind: 'photo' | 'vector' | 'raster';
  size: number;
  modified: string;
}

interface ScanResponse {
  path: string;
  counts: Record<string, number>;
  total: number;
  truncated: boolean;
  files: ScanFile[];
  errors: { path: string; error: string }[];
}

export default function ServerIngestForm({
  layers,
  onJob,
}: {
  layers: Layer[];
  onJob: (job: ImportJob) => void;
}) {
  const [meta, setMeta] = useState<RootsResponse | null>(null);
  const [root, setRoot] = useState('');
  const [folder, setFolder] = useState('');
  const [recursive, setRecursive] = useState(true);
  const [mode, setMode] = useState<'photos' | 'geodata'>('photos');
  const [name, setName] = useState('');
  const [layerId, setLayerId] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [matchExisting, setMatchExisting] = useState(false);
  const [radius, setRadius] = useState(60);
  const [licence, setLicence] = useState('');
  const [attribution, setAttribution] = useState('');
  const [scan, setScan] = useState<ScanResponse | null>(null);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<RootsResponse>('/ingest/roots')
      .then((data) => {
        setMeta(data);
        const usable = data.roots.find((item) => item.exists && item.readable) ?? data.roots[0];
        if (usable) setRoot(usable.path);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not read ingest roots'));
  }, []);

  const absolutePath = folder.trim()
    ? `${root.replace(/\/$/, '')}/${folder.trim().replace(/^\/+/, '')}`
    : root;
  const pointLayers = layers.filter((layer) => ['point', 'geometry'].includes(layer.geometry_type));

  async function runScan() {
    setScanning(true);
    setError(null);
    setScan(null);
    try {
      const data = await api<ScanResponse>('/ingest/scan', {
        method: 'POST',
        body: {
          path: absolutePath,
          recursive,
          kind: mode === 'photos' ? 'photos' : 'geodata',
          limit: 500,
        },
      });
      setScan(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setScanning(false);
    }
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const job = await api<ImportJob>('/ingest', {
        method: 'POST',
        body: {
          path: absolutePath,
          mode,
          recursive,
          name,
          layer_id: mode === 'photos' && layerId ? layerId : undefined,
          visibility,
          match_existing: mode === 'photos' ? matchExisting && Boolean(layerId) : false,
          match_radius_m: radius,
          licence,
          attribution,
        },
      });
      onJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start ingest job');
    } finally {
      setBusy(false);
    }
  }

  if (!meta) return <p className="muted">Checking configured server folders…</p>;
  if (!meta.enabled) {
    return (
      <div className="warning-box">
        {meta.message ||
          'Server-side ingestion is disabled. Set INGEST_ENABLED=true and configure INGEST_ROOTS.'}
      </div>
    );
  }

  return (
    <div className="stack">
      <p className="muted">
        Process files already on the server or NAS without uploading them through the browser.
        The folder is mounted read-only at {meta.roots.map((item) => item.path).join(', ') || '/ingest'}.
        Server paths are restricted to the configured roots.
      </p>

      <div className="grid-2">
        <Field label="Configured root" help="Only folders under INGEST_ROOTS are visible. The source mount is read-only.">
          <select
            value={root}
            onChange={(e) => {
              setRoot(e.target.value);
              setScan(null);
            }}
          >
            {meta.roots.map((item) => (
              <option key={item.path} value={item.path}>
                {item.path} {item.exists ? '' : '(missing)'} {item.readable ? '' : '(not readable)'}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Subfolder" hint="Relative to the selected root; leave empty for the whole root." help="Example: 2026/spring. Hidden folders and NAS metadata folders are skipped.">
          <input
            value={folder}
            onChange={(e) => {
              setFolder(e.target.value);
              setScan(null);
            }}
            placeholder="2026/holiday"
          />
        </Field>
      </div>

      <div className="grid-2">
        <Field label="Import type" help="Photos require EXIF GPS. Geodata creates one child import job and layer per supported file.">
          <select
            value={mode}
            onChange={(e) => {
              setMode(e.target.value as 'photos' | 'geodata');
              setScan(null);
            }}
          >
            <option value="photos">Geotagged photos (JPEG, TIFF, PNG, WebP, RAF)</option>
            <option value="geodata">Geodata files</option>
          </select>
        </Field>
        <Field label="Recursive" help="Include files in subfolders. Turn off to process only the selected folder.">
          <select
            value={recursive ? 'yes' : 'no'}
            onChange={(e) => {
              setRecursive(e.target.value === 'yes');
              setScan(null);
            }}
          >
            <option value="yes">Include subfolders</option>
            <option value="no">Top folder only</option>
          </select>
        </Field>
      </div>

      <div className="button-row">
        <button className="btn btn-secondary" onClick={runScan} disabled={scanning}>
          {scanning ? 'Scanning…' : 'Scan folder'}
        </button>
        <span className="hint">
          Scan limit: {meta.max_scan_files.toLocaleString()} files · job limit:{' '}
          {meta.max_files_per_job.toLocaleString()}
        </span>
      </div>

      {scan && (
        <div className="scan-result">
          <div className="scan-summary">
            <strong>{scan.total.toLocaleString()} supported file(s)</strong>
            <span>
              {scan.counts.photo ?? 0} photos · {scan.counts.vector ?? 0} vector ·{' '}
              {scan.counts.raster ?? 0} raster
            </span>
          </div>
          {scan.truncated && <div className="warning-box">Preview truncated at the scan limit.</div>}
          {scan.errors.length > 0 && (
            <div className="warning-box">{scan.errors.length} unreadable path(s) skipped.</div>
          )}
          <div className="scan-files">
            {scan.files.slice(0, 40).map((file) => (
              <div key={file.path} className="scan-file">
                <span className={`badge badge-${file.kind === 'photo' ? 'info' : 'default'}`}>
                  {file.kind}
                </span>
                <span className="grow">{file.relative_path}</span>
                <small>{formatBytes(file.size)}</small>
              </div>
            ))}
          </div>
        </div>
      )}

      {mode === 'photos' ? (
        <>
          <div className="grid-2">
            <Field label="Add to existing photo layer" hint="Leave empty to create a new layer.">
              <select value={layerId} onChange={(e) => setLayerId(e.target.value)}>
                <option value="">Create a new photo layer</option>
                {pointLayers.map((layer) => (
                  <option key={layer.id} value={layer.id}>
                    {layer.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="New layer name">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="NAS photos"
                disabled={Boolean(layerId)}
              />
            </Field>
          </div>
          {layerId && (
            <div className="photo-match">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={matchExisting}
                  onChange={(e) => setMatchExisting(e.target.checked)}
                />
                <span>Attach photos to the nearest existing point within the radius.</span>
              </label>
              {matchExisting && (
                <Field label="Matching radius (metres)">
                  <input
                    type="number"
                    min={1}
                    max={5000}
                    value={radius}
                    onChange={(e) => setRadius(Number(e.target.value))}
                  />
                </Field>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="grid-2">
          <Field label="Layer name prefix" hint="Each file becomes its own layer.">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="NAS import" />
          </Field>
          <Field label="Licence">
            <input value={licence} onChange={(e) => setLicence(e.target.value)} />
          </Field>
          <Field label="Attribution">
            <input value={attribution} onChange={(e) => setAttribution(e.target.value)} />
          </Field>
        </div>
      )}

      {!layerId && (
        <Field label="Visibility">
          <select value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)}>
            <option value="private">Private</option>
            <option value="organisation">Internal</option>
            <option value="public">Public</option>
          </select>
        </Field>
      )}

      <ErrorBox message={error} />

      <div className="button-row end">
        <button className="btn btn-primary" onClick={start} disabled={busy || !scan || scan.total === 0}>
          {busy ? 'Starting…' : scan?.truncated ? 'Process folder' : `Process ${scan?.total ?? ''} file(s)`}
        </button>
      </div>

      <p className="hint">
        Photo attachments reference the original NAS files. Keep the mounted folder in place for
        images to remain accessible; thumbnails are cached in Strata storage.
      </p>
    </div>
  );
}
