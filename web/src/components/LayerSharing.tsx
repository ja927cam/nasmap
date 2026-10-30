import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Layer, User } from '../api/types';
import { ErrorBox, Field, Modal } from './ui';

interface Permission {
  id: string;
  role: 'editor' | 'viewer';
  user: User;
  created_at: string;
}

export default function LayerSharing({
  layer,
  onClose,
}: {
  layer: Layer;
  onClose: () => void;
}) {
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'editor' | 'viewer'>('viewer');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setPermissions(await api<Permission[]>(`/layers/${layer.id}/permissions`));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load sharing settings');
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer.id]);

  async function grant(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/layers/${layer.id}/permissions`, {
        method: 'POST',
        body: { email, role },
      });
      setEmail('');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not share layer');
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    try {
      await api(`/layers/${layer.id}/permissions/${id}`, { method: 'DELETE' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revoke access');
    }
  }

  return (
    <Modal title={`Share · ${layer.name}`} onClose={onClose}>
      <div className="stack">
        <p className="muted">
          Visibility is <strong>{layer.visibility}</strong>. Explicit grants add access to this
          layer only. Layer editors must also have a global editor or admin role.
        </p>
        <form onSubmit={grant} className="stack">
          <div className="grid-2">
            <Field label="User email">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="colleague@example.org"
                required
              />
            </Field>
            <Field label="Layer role">
              <select value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
              </select>
            </Field>
          </div>
          <button className="btn btn-secondary" disabled={busy}>
            {busy ? 'Sharing…' : 'Grant access'}
          </button>
        </form>
        <ErrorBox message={error} />
        <div className="list">
          {permissions.length === 0 ? (
            <p className="muted">No explicit grants. The owner and admins always have access.</p>
          ) : (
            permissions.map((permission) => (
              <div key={permission.id} className="list-row">
                <div className="grow">
                  <strong>{permission.user.display_name || permission.user.email}</strong>
                  <small>
                    {permission.user.email} · {permission.user.role}
                  </small>
                </div>
                <span className="badge badge-info">{permission.role}</span>
                <button className="btn btn-ghost btn-xs danger" onClick={() => revoke(permission.id)}>
                  Remove
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </Modal>
  );
}
