import { useEffect, useMemo, useState } from 'react';
import type { GeoFeature, Layer } from '../api/types';
import AttachmentGallery from './AttachmentGallery';
import { api } from '../api/client';
import Icon from './Icon';
import { formatDate } from './ui';

interface PropertyRow {
  key: string;
  value: string;
  type: 'string' | 'number' | 'boolean' | 'json';
}

function visibleProperties(props: Record<string, unknown>) {
  return Object.fromEntries(
    Object.entries(props || {}).filter(([key]) => !key.startsWith('_nasmap')),
  );
}

function toRows(props: Record<string, unknown>): PropertyRow[] {
  return Object.entries(props).map(([key, value]) => {
    if (typeof value === 'number') {
      return { key, value: String(value), type: 'number' as const };
    }
    if (typeof value === 'boolean') {
      return { key, value: String(value), type: 'boolean' as const };
    }
    if (value !== null && typeof value === 'object') {
      return { key, value: JSON.stringify(value, null, 2), type: 'json' as const };
    }
    return { key, value: value == null ? '' : String(value), type: 'string' as const };
  });
}

function parseRows(rows: PropertyRow[]) {
  const result: Record<string, unknown> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) continue;
    if (row.type === 'number') {
      const number = Number(row.value);
      result[key] = Number.isFinite(number) ? number : row.value;
    } else if (row.type === 'boolean') {
      result[key] = row.value === 'true';
    } else if (row.type === 'json') {
      try {
        result[key] = JSON.parse(row.value);
      } catch {
        result[key] = row.value;
      }
    } else {
      result[key] = row.value;
    }
  }
  return result;
}

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
  const props = useMemo(() => visibleProperties(feature.properties || {}), [feature.properties]);
  const [rows, setRows] = useState<PropertyRow[]>(() => toRows(props));
  const [text, setText] = useState(() => JSON.stringify(props, null, 2));
  const [mode, setMode] = useState<'fields' | 'json'>('fields');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [versions, setVersions] = useState<
    { version: number; change_type: string; created_at: string }[]
  >([]);

  useEffect(() => {
    setRows(toRows(props));
    setText(JSON.stringify(props, null, 2));
    setMode('fields');
    setShowHistory(false);
    setVersions([]);
    setError(null);
  }, [feature.id, props]);

  async function toggleHistory() {
    if (showHistory) {
      setShowHistory(false);
      return;
    }
    setShowHistory(true);
    try {
      setVersions(
        await api<{ version: number; change_type: string; created_at: string }[]>(
          `/features/${feature.id}/versions`,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load history');
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      let parsed: Record<string, unknown>;
      if (mode === 'json') {
        const value = JSON.parse(text);
        if (typeof value !== 'object' || Array.isArray(value) || value === null) {
          throw new Error('Properties must be a JSON object');
        }
        parsed = value;
      } else {
        parsed = parseRows(rows);
      }
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

  function updateRow(index: number, patch: Partial<PropertyRow>) {
    setRows((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)),
    );
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

      <div className="feature-props-head">
        <h3>Properties</h3>
        <div className="mini-tabs">
          <button className={showHistory ? 'mini-tab active' : 'mini-tab'} onClick={() => void toggleHistory()}>
            History
          </button>
          <button
            className={mode === 'fields' ? 'mini-tab active' : 'mini-tab'}
            onClick={() => {
              if (mode === 'json') {
                try {
                  const parsed = JSON.parse(text);
                  if (typeof parsed === 'object' && !Array.isArray(parsed) && parsed !== null) {
                    setRows(toRows(parsed));
                  }
                } catch {
                  /* keep field values if the JSON is incomplete */
                }
              }
              setShowHistory(false);
              setMode('fields');
            }}
          >
            Fields
          </button>
          <button
            className={mode === 'json' ? 'mini-tab active' : 'mini-tab'}
            onClick={() => {
              setText(JSON.stringify(parseRows(rows), null, 2));
              setShowHistory(false);
              setMode('json');
            }}
          >
            JSON
          </button>
        </div>
      </div>

      {showHistory ? (
        <div className="version-list">
          {versions.length === 0 ? (
            <p className="hint">No versions recorded yet.</p>
          ) : (
            versions.map((version) => (
              <div key={`${version.version}-${version.created_at}`} className="version-row">
                <strong>v{version.version}</strong>
                <span>{version.change_type}</span>
                <small>{formatDate(version.created_at)}</small>
              </div>
            ))
          )}
        </div>
      ) : mode === 'fields' ? (
        <div className="property-editor">
          <div className="property-head">
            <span>Key</span>
            <span>Value</span>
            <span />
          </div>
          {rows.map((row, index) => (
            <div key={index} className="property-row">
              <input
                value={row.key}
                onChange={(e) => updateRow(index, { key: e.target.value })}
                placeholder="key"
                disabled={!editable}
              />
              <input
                value={row.value}
                onChange={(e) => updateRow(index, { value: e.target.value })}
                placeholder="value"
                disabled={!editable}
              />
              {editable ? (
                <button
                  className="icon-btn"
                  aria-label="Remove property"
                  onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                >
                  <Icon name="close" size={12} />
                </button>
              ) : (
                <span />
              )}
            </div>
          ))}
          {rows.length === 0 && <p className="hint">No properties.</p>}
          {editable && (
            <button
              className="btn btn-ghost btn-xs"
              onClick={() => setRows((current) => [...current, { key: '', value: '', type: 'string' }])}
            >
              <Icon name="plus" size={12} />
              Add field
            </button>
          )}
        </div>
      ) : (
        <label className="field">
          <textarea
            rows={12}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!editable}
          />
        </label>
      )}

      {error && <div className="error-box">{error}</div>}
      {editable ? (
        <div className="button-row feature-actions">
          <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button className="btn btn-danger btn-sm" onClick={onDelete} disabled={busy}>
            Delete
          </button>
          {feature.geometry?.type === 'Point' && (
            <button className="btn btn-secondary btn-sm" onClick={onOsm}>
              Attach / publish to OSM
            </button>
          )}
        </div>
      ) : (
        <p className="muted">You have read-only access to this layer.</p>
      )}
      <p className="hint">Drag the handles on the map to move vertices.</p>
    </div>
  );
}
