import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import type { GeoFeature, Layer } from '../api/types';
import Icon from './Icon';
import { Field, Modal } from './ui';

interface NearbyNode {
  osm_id: number;
  osm_version: number;
  lat: number;
  lon: number;
  distance_m: number;
  tags: Record<string, string>;
  name?: string | null;
}

interface Preview {
  action: string;
  osm_type: string;
  osm_id: number | null;
  osm_version: number | null;
  lat: number;
  lon: number;
  tags: Record<string, string>;
  existing_tags: Record<string, string>;
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
      if (
        key.startsWith('_nasmap') ||
        key.startsWith('osm_') ||
        key.startsWith('photo_') ||
        key.startsWith('exif_') ||
        key.startsWith('camera_') ||
        key === 'geometry_wkt'
      ) {
        continue;
      }
      if (value === null || typeof value === 'object') continue;
      tags[key] = String(value);
    }
    return tags;
  }, [feature]);

  const [tags, setTags] = useState<Record<string, string>>(initialTags);
  const [comment, setComment] = useState(`Strata: update ${layer.name}`);
  const [source, setSource] = useState('Strata survey');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<PublishResult | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [nearby, setNearby] = useState<NearbyNode[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [radius, setRadius] = useState(50);
  const [selected, setSelected] = useState<NearbyNode | null>(null);
  const [forceCreate, setForceCreate] = useState(false);
  const previewSeq = useRef(0);

  useEffect(() => {
    void runPreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function tagPayload(values: Record<string, string> = tags) {
    return Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim()));
  }

  async function runPreview(
    osmId: number | undefined = selected?.osm_id,
    createNew = forceCreate,
    tagValues: Record<string, string> = tags,
  ) {
    const seq = previewSeq.current + 1;
    previewSeq.current = seq;
    setBusy(true);
    setError(null);
    try {
      const data = await api<Preview>('/osm/preview', {
        method: 'POST',
        body: {
          feature_id: feature.id,
          comment,
          source,
          tags: tagPayload(tagValues),
          osm_id: osmId,
          force_create: createNew,
        },
      });
      if (seq !== previewSeq.current) return;
      setPreview(data);
      setTags(data.tags);
    } catch (err) {
      if (seq === previewSeq.current) {
        setError(err instanceof Error ? err.message : 'Preview failed');
      }
    } finally {
      if (seq === previewSeq.current) setBusy(false);
    }
  }

  async function findNearby() {
    setSearching(true);
    setError(null);
    setNearby(null);
    try {
      const data = await api<{ nodes: NearbyNode[] }>('/osm/nearby', {
        method: 'POST',
        body: { feature_id: feature.id, radius_m: radius },
      });
      setNearby(data.nodes);
      if (data.nodes.length === 0) {
        setError('No tagged OSM points nearby. Try a larger search radius.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not search nearby OSM points');
    } finally {
      setSearching(false);
    }
  }

  function attachTo(node: NearbyNode) {
    const baseTags = selected?.osm_id === node.osm_id ? tags : initialTags;
    setSelected(node);
    setForceCreate(false);
    setResult(null);
    setConfirmed(false);
    if (selected?.osm_id !== node.osm_id) setTags(initialTags);
    void runPreview(node.osm_id, false, baseTags);
  }

  function publishAsNew() {
    setSelected(null);
    setForceCreate(true);
    setNearby(null);
    setResult(null);
    setConfirmed(false);
    setTags(initialTags);
    void runPreview(undefined, true, initialTags);
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
          osm_id: selected?.osm_id,
          force_create: forceCreate,
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
    <Modal title="Attach and publish to OpenStreetMap" onClose={onClose} wide>
      <div className="stack">
        <div className="warning-box">
          OpenStreetMap edits are public and permanent. Changes are uploaded with your OSM
          account. Review the tags, geometry and changeset comment before confirming.
        </div>

        <section className="osm-match">
          <div className="osm-match-head">
            <div>
              <h3>Attach to an existing OSM point</h3>
              <p className="hint">
                Find a nearby OpenStreetMap point and add your data to it instead of creating a
                duplicate. Photos and files stay attached in Strata; OSM stores text tags only.
              </p>
            </div>
            {preview?.osm_id && !selected && (
              <span className="badge badge-info">Linked to node #{preview.osm_id}</span>
            )}
          </div>
          <div className="osm-search-row">
            <select
              value={radius}
              onChange={(e) => setRadius(Number(e.target.value))}
              aria-label="Search radius"
            >
              <option value={10}>Within 10 m</option>
              <option value={25}>Within 25 m</option>
              <option value={50}>Within 50 m</option>
              <option value={100}>Within 100 m</option>
              <option value={200}>Within 200 m</option>
            </select>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => void findNearby()}
              disabled={searching}
            >
              {searching ? 'Searching…' : 'Find nearby OSM points'}
            </button>
          </div>
          {nearby && nearby.length > 0 && (
            <div className="osm-nodes">
              {nearby.map((node) => (
                <button
                  key={node.osm_id}
                  type="button"
                  className={`osm-node ${selected?.osm_id === node.osm_id ? 'selected' : ''}`}
                  onClick={() => attachTo(node)}
                >
                  <span className="osm-node-main">
                    <strong>{node.name || `OSM node ${node.osm_id}`}</strong>
                    <small>
                      {node.distance_m.toFixed(1)} m away · node #{node.osm_id}
                    </small>
                  </span>
                  <span className="osm-node-tags">
                    {Object.entries(node.tags)
                      .slice(0, 3)
                      .map(([key, value]) => `${key}=${value}`)
                      .join(' · ')}
                  </span>
                </button>
              ))}
            </div>
          )}
          {selected && (
            <div className="osm-selected">
              <div>
                <strong>
                  {selected.name || `OSM node ${selected.osm_id}`} will be updated
                </strong>
                <small>
                  Existing OSM tags are kept; the OSM point stays at its current position.
                </small>
              </div>
              <button type="button" className="btn btn-ghost btn-xs" onClick={publishAsNew}>
                Create a new point instead
              </button>
            </div>
          )}
          <p className="hint">
            To publish a photo link, add an <code>image</code> tag with a publicly reachable URL.
            The original photo remains attached to this Strata feature.
          </p>
        </section>

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
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => void runPreview(selected?.osm_id, forceCreate)}
            disabled={busy}
          >
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
        {preview && Object.keys(preview.existing_tags || {}).length > 0 && (
          <p className="hint">
            Existing OSM tags are preserved. Edit a value to change it; tags removed here cannot
            be deleted from OSM in this version.
          </p>
        )}
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
              I have reviewed the tags and understand this will make a public OSM edit.
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
