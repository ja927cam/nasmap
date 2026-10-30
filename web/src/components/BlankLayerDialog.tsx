import { useState } from 'react';
import { api } from '../api/client';
import type { Layer } from '../api/types';
import { ErrorBox, Field, Modal } from './ui';

export default function BlankLayerDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (layer: Layer) => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [geometryType, setGeometryType] = useState<'point' | 'line' | 'polygon' | 'geometry'>('point');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const layer = await api<Layer>('/layers', {
        method: 'POST',
        body: {
          name: name.trim(),
          description: description.trim(),
          geometry_type: geometryType,
          visibility,
          source_type: 'manual',
        },
      });
      onCreated(layer);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create layer');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="New blank layer" onClose={onClose}>
      <form className="stack" onSubmit={create}>
        <p className="muted">
          Creates an empty layer. After saving, draw points, lines or polygons with the map tools.
        </p>
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Untitled layer"
            autoFocus
            required
          />
        </Field>
        <Field label="Description">
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <div className="grid-2">
          <Field label="Geometry">
            <select
              value={geometryType}
              onChange={(e) => setGeometryType(e.target.value as typeof geometryType)}
            >
              <option value="point">Point</option>
              <option value="line">Line</option>
              <option value="polygon">Polygon</option>
              <option value="geometry">Mixed geometry</option>
            </select>
          </Field>
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
        </div>
        <ErrorBox message={error} />
        <div className="button-row end">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || !name.trim()}>
            {busy ? 'Creating…' : 'Create layer'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
