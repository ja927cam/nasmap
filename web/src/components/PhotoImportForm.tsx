import { useState } from 'react';
import { api } from '../api/client';
import { usePublicConfig } from '../api/config';
import type { Layer, PhotoImportResult } from '../api/types';
import { ErrorBox, Field } from './ui';

const PHOTO_ACCEPT =
  'image/jpeg,image/tiff,image/png,image/webp,image/x-fujifilm-raf,' +
  '.jpg,.JPG,.jpeg,.JPEG,.jfif,.JFIF,.tif,.TIF,.tiff,.TIFF,.png,.PNG,.webp,.WEBP,.raf,.RAF';

export default function PhotoImportForm({
  layers,
  onDone,
}: {
  layers: Layer[];
  onDone: (layerId: string | null) => void;
}) {
  const config = usePublicConfig();
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState('');
  const [layerId, setLayerId] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [matchExisting, setMatchExisting] = useState(false);
  const [radius, setRadius] = useState(60);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PhotoImportResult | null>(null);

  const pointLayers = layers.filter((layer) =>
    ['point', 'geometry'].includes(layer.geometry_type),
  );

  async function submit() {
    if (!files.length) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      files.forEach((file) => form.append('files', file));
      if (name.trim()) form.append('name', name.trim());
      if (layerId) form.append('layer_id', layerId);
      form.append('visibility', visibility);
      form.append('match_existing', String(matchExisting && Boolean(layerId)));
      form.append('match_radius_m', String(radius));
      const response = await api<PhotoImportResult>('/photos/import', {
        method: 'POST',
        body: form,
      });
      setResult(response);
      if (response.layer_id && (response.created_features > 0 || response.attached_photos > 0)) {
        onDone(response.layer_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not import photos');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <p className="muted">
        Select JPEG, TIFF, PNG, WebP or Fujifilm RAF files from your phone or camera. Strata reads
        the EXIF GPS position, stores the original as an attachment and creates a point feature for
        each geotagged photo. Photos without GPS are listed and skipped rather than placed at 0,0.
        Per-photo limit: {config?.max_photo_mb ?? 100} MB.
      </p>

      <label className="file-drop">
        <input
          type="file"
          accept={PHOTO_ACCEPT}
          multiple
          onChange={(e) => {
            setFiles(Array.from(e.target.files ?? []));
            setResult(null);
          }}
        />
        <strong>{files.length ? `${files.length} photo(s) selected` : 'Choose photos'}</strong>
        <small>JPEG, TIFF, PNG, WebP or RAF · EXIF GPS required</small>
      </label>

      {files.length > 0 && (
        <div className="file-summary">
          {files.slice(0, 8).map((file) => (
            <span key={file.name}>
              {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
            </span>
          ))}
          {files.length > 8 && <span>+{files.length - 8} more</span>}
        </div>
      )}

      <div className="grid-2">
        <Field label="Add to existing layer" hint="Only point or mixed-geometry layers." help="Leave empty to create a photo layer. Appending adds one point per geotagged photo.">
          <select
            value={layerId}
            onChange={(e) => {
              setLayerId(e.target.value);
              if (!e.target.value) setMatchExisting(false);
            }}
          >
            <option value="">Create a new photo layer</option>
            {pointLayers.map((layer) => (
              <option key={layer.id} value={layer.id}>
                {layer.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="New layer name" hint="Used when creating a new layer.">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Field photos"
            disabled={Boolean(layerId)}
          />
        </Field>
      </div>

      {!layerId && (
        <Field label="Visibility">
          <select value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)}>
            <option value="private">Private</option>
            <option value="organisation">Internal</option>
            <option value="public">Public</option>
          </select>
        </Field>
      )}

      {layerId && (
        <div className="photo-match">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={matchExisting}
              onChange={(e) => setMatchExisting(e.target.checked)}
            />
            <span>
              Attach photos to the nearest existing point instead of always creating a new point
              (useful for photos of a surveyed object).
            </span>
          </label>
          {matchExisting && (
            <Field label="Matching radius (metres)" help="A photo is attached to the nearest existing point within this distance instead of creating a new point.">
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

      <ErrorBox message={error} />

      {result && (
        <div className="stack">
          <div className="success-box">
            {result.message ||
              `Imported ${result.created_features} new photo point(s) and attached ${result.attached_photos} photo(s) to existing features.`}
          </div>
          {result.skipped.length > 0 && (
            <details open>
              <summary>{result.skipped.length} photo(s) skipped</summary>
              <ul className="skip-list">
                {result.skipped.map((item) => (
                  <li key={item.filename}>
                    <strong>{item.filename}</strong> — {item.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="button-row end">
        <button className="btn btn-primary" disabled={!files.length || busy} onClick={submit}>
          {busy ? 'Reading EXIF and importing…' : 'Scan and import photos'}
        </button>
      </div>
    </div>
  );
}
