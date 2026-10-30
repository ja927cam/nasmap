import { useEffect, useState } from 'react';
import type { GeoFeature, Layer } from '../api/types';
import AttachmentGallery from './AttachmentGallery';
import Icon from './Icon';

export default function FeaturePanel({
  feature,
  layer,
  editable,
  onClose,
  onSave,
  onDelete,
  onOsm,
}: {
  feature: GeoFeature;
  layer: Layer;
  editable: boolean;
  onClose: () => void;
  onSave: (properties: Record<string, any>) => Promise<void>;
  onDelete: () => Promise<void>;
  onOsm: () => void;
}) {
  const visibleProperties = (props: Record<string, any>) =>
    Object.fromEntries(Object.entries(props || {}).filter(([key]) => !key.startsWith('_nasmap')));
  const [text, setText] = useState(JSON.stringify(visibleProperties(feature.properties), null, 2));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setText(JSON.stringify(visibleProperties(feature.properties), null, 2));
    setError(null);
  }, [feature.id, feature.properties]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Properties must be an object');
      const internal = Object.fromEntries(
        Object.entries(feature.properties || {}).filter(([key]) => key.startsWith('_nasmap')),
      );
      await onSave({ ...parsed, ...internal });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="feature-panel">
      <div className="panel-head">
        <h2 title={layer.name}>Feature</h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <Icon name="close" size={16} />
        </button>
      </div>
      <div className="feature-meta">
        <span className="mono">{feature.id.slice(0, 8)}…</span>
        <span className="muted">v{feature.version ?? 1}</span>
        <span className="muted">{feature.geometry?.type}</span>
      </div>
      <AttachmentGallery featureId={feature.id} editable={editable} />
      <label className="field">
        <span>Properties (JSON)</span>
        <textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} disabled={!editable} />
      </label>
      {error && <div className="error-box">{error}</div>}
      {editable ? (
        <div className="button-row">
          <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>
            Save properties
          </button>
          <button className="btn btn-danger btn-sm" onClick={onDelete} disabled={busy}>
            Delete
          </button>
          {feature.geometry?.type === 'Point' ? (
            <button className="btn btn-secondary btn-sm" onClick={onOsm}>
              Publish to OSM
            </button>
          ) : null}
        </div>
      ) : (
        <p className="muted">You have read-only access to this layer.</p>
      )}
      <p className="hint">Drag the white handles on the map to move vertices.</p>
    </div>
  );
}
