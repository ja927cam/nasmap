import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { GeoFeature, Layer } from '../api/types';
import Icon from './Icon';
import { Field, Modal } from './ui';

interface Preview {
  action: string;
  osm_type: string;
  osm_id: number | null;
  osm_version: number | null;
  lat: number;
  lon: number;
  tags: Record<string, string>;
  changeset_xml: string;
  diff_xml: string;
  warning: string;
}

interface PublishResult {
  published?: boolean;
  dry_run?: boolean;
  changeset_id?: number;
  changeset_url?: string;
  osm_id?: number;
  diff_xml?: string;
  message?: string;
  result?: any;
}

export default function OsmPublishDialog({
  feature,
  layer,
  onClose,
  onPublished,
}: {
  feature: GeoFeature;
  layer: Layer;
  onClose: () => void;
  onPublished: () => void;
}) {
  const initialTags = useMemo(() => {
    const tags: Record<string, string> = {};
    for (const [key, value] of Object.entries(feature.properties || {})) {
      if (key.startsWith('_nasmap') || key.startsWith('osm_') || key === 'geometry_wkt') continue;
      if (value === null || typeof value === 'object') continue;
      tags[key] = String(value);
    }
    return tags;
  }, [feature]);

  const [tags, setTags] = useState<Record<string, string>>(initialTags);
  const [comment, setComment] = useState(`NasMap: update ${layer.name}`);
  const [source, setSource] = useState('NasMap survey');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<PublishResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void runPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function tagPayload() {
    return Object.fromEntries(Object.entries(tags).filter(([, value]) => value.trim()));
  }

  async function runPreview() {
    setBusy(true);
    setError(null);
    try {
      const data = await api<Preview>('/osm/preview', {
        method: 'POST',
        body: { feature_id: feature.id, comment, source, tags: tagPayload() },
      });
      setPreview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed');
    } finally {
      setBusy(false);
    }
  }

  async function publish(dryRun: boolean) {
    setBusy(true);
    setError(null);
    try {
      const data = await api<PublishResult>('/osm/publish', {
        method: 'POST',
        body: {
          feature_id: feature.id,
          comment,
          source,
          tags: tagPayload(),
          confirm: !dryRun,
          dry_run: dryRun,
        },
      });
      setResult(data);
      if (!dryRun && data.published) onPublished();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Publish failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Publish to OpenStreetMap" onClose={onClose} wide>
      <div className="stack">
        <div className="warning-box">
          OpenStreetMap edits are public and permanent. Changes are uploaded with your OSM
          account. Review the tags, geometry and changeset comment before confirming.
        </div>

        {preview && (
          <div className="grid-2">
            <div>
              <h3>Geometry</h3>
              <dl className="kv">
                <dt>Action</dt>
                <dd>{preview.action}</dd>
                <dt>Object</dt>
                <dd>
                  {preview.osm_type} {preview.osm_id ?? '(new)'}
                </dd>
                <dt>Coordinates</dt>
                <dd className="mono">
                  {preview.lat.toFixed(6)}, {preview.lon.toFixed(6)}
                </dd>
                <dt>Changeset</dt>
                <dd>{comment}</dd>
                <dt>Source</dt>
                <dd>{source}</dd>
              </dl>
            </div>
            <div>
              <h3>Tags ({Object.keys(tags).length})</h3>
              <div className="tag-editor">
                {Object.entries(tags).map(([key, value]) => (
                  <div key={key} className="tag-row">
                    <input
                      className="tag-key"
                      value={key}
                      onChange={(e) => {
                        const next = { ...tags };
                        delete next[key];
                        next[e.target.value] = value;
                        setTags(next);
                      }}
                    />
                    <input value={value} onChange={(e) => setTags({ ...tags, [key]: e.target.value })} />
                    <button
                      className="icon-btn"
                      aria-label="Remove tag"
                      onClick={() => {
                        const next = { ...tags };
                        delete next[key];
                        setTags(next);
                      }}
                    >
                      <Icon name="close" size={13} />
                    </button>
                  </div>
                ))}
                <button
                  className="btn btn-ghost btn-xs"
                  onClick={() => setTags({ ...tags, '': '' })}
                >
                  + Add tag
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="grid-2">
          <Field label="Changeset comment" hint="3–255 characters, describes why the edit was made.">
            <input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={255} />
          </Field>
          <Field label="Source">
            <input value={source} onChange={(e) => setSource(e.target.value)} />
          </Field>
        </div>

        <div className="button-row">
          <button className="btn btn-secondary btn-sm" onClick={runPreview} disabled={busy}>
            Refresh preview
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => publish(true)} disabled={busy}>
            Dry run
          </button>
        </div>

        {preview && (
          <details>
            <summary>Show OsmChange diff</summary>
            <pre className="code-block">{preview.diff_xml}</pre>
          </details>
        )}
        {preview && <p className="hint">{preview.warning}</p>}
        {error && <div className="error-box">{error}</div>}

        {result?.published && (
          <div className="success-box">
            Published to changeset{' '}
            <a href={result.changeset_url} target="_blank" rel="noreferrer">
              #{result.changeset_id}
            </a>
            . OSM object id: {result.osm_id}.
          </div>
        )}
        {result?.dry_run && (
          <div className="success-box">{result.message || 'Dry run complete; nothing uploaded.'}</div>
        )}

        {!result?.published && (
          <>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              I have reviewed the tags and understand this will create a public OSM edit.
            </label>
            <div className="button-row end">
              <button className="btn btn-ghost" onClick={onClose}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                disabled={!confirmed || busy || !comment.trim()}
                onClick={() => publish(false)}
              >
                {busy ? 'Publishing…' : 'Confirm and publish'}
              </button>
            </div>
          </>
        )}
        {result?.published && (
          <button className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        )}
      </div>
    </Modal>
  );
}
