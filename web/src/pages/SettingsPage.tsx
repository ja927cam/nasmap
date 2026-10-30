import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../api/auth';
import { api } from '../api/client';
import { usePublicConfig } from '../api/config';
import { ErrorBox, Field, Modal, formatDate } from '../components/ui';

interface OSMStatus {
  enabled: boolean;
  connected: boolean;
  username: string | null;
  osm_user_id: number | null;
  api_base_url: string;
  scopes: string[];
}

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export default function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const config = usePublicConfig();
  const [params, setParams] = useSearchParams();
  const [displayName, setDisplayName] = useState(user?.display_name ?? '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [osm, setOsm] = useState<OSMStatus | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [keyName, setKeyName] = useState('');
  const [keyModal, setKeyModal] = useState(false);

  useEffect(() => {
    api<OSMStatus>('/osm/status').then(setOsm).catch(() => undefined);
    api<ApiKey[]>('/auth/api-keys').then(setKeys).catch(() => undefined);
  }, []);

  useEffect(() => {
    const status = params.get('osm');
    if (status) {
      setMessage(status === 'connected' ? 'OpenStreetMap account connected.' : 'Could not connect OpenStreetMap.');
      setParams({}, { replace: true });
      api<OSMStatus>('/osm/status').then(setOsm).catch(() => undefined);
    }
  }, [params, setParams]);

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      await api('/auth/me', {
        method: 'PATCH',
        body: {
          display_name: displayName,
          current_password: currentPassword || undefined,
          new_password: newPassword || undefined,
        },
      });
      await refreshUser();
      setMessage('Profile updated.');
      setCurrentPassword('');
      setNewPassword('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update profile');
    }
  }

  async function connectOsm() {
    try {
      const data = await api<{ authorization_url: string }>('/osm/authorize', {
        method: 'POST',
        body: { redirect_to: '/settings' },
      });
      window.location.href = data.authorization_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start OSM sign-in');
    }
  }

  async function disconnectOsm() {
    await api('/osm/disconnect', { method: 'POST' });
    setOsm((prev) => (prev ? { ...prev, connected: false, username: null } : prev));
  }

  async function createKey() {
    try {
      const data = await api<{ key: string }>('/auth/api-keys', {
        method: 'POST',
        body: { name: keyName, expires_in_days: 365 },
      });
      setNewKey(data.key);
      setKeyName('');
      setKeyModal(false);
      setKeys(await api<ApiKey[]>('/auth/api-keys'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create API key');
    }
  }

  async function revokeKey(id: string) {
    await api(`/auth/api-keys/${id}`, { method: 'DELETE' });
    setKeys((prev) => prev.filter((key) => key.id !== id));
  }

  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="page-subtitle">Profile, OpenStreetMap connection and API keys.</p>
        </div>
      </header>

      {message && <div className="success-box">{message}</div>}
      <ErrorBox message={error} />

      <section className="panel">
        <h2>Profile</h2>
        <form className="stack" onSubmit={saveProfile}>
          <Field label="Email">
            <input value={user?.email ?? ''} disabled />
          </Field>
          <Field label="Display name">
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
          <Field label="Role">
            <input value={user?.role ?? ''} disabled />
          </Field>
          <h3>Change password</h3>
          <div className="grid-2">
            <Field label="Current password">
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
              />
            </Field>
            <Field label="New password" hint="Leave blank to keep the current password.">
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
          </div>
          <div className="button-row end">
            <button className="btn btn-primary">Save profile</button>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>OpenStreetMap</h2>
          {osm?.connected && <span className="badge badge-success">connected</span>}
        </div>
        {!config?.osm_oauth_enabled ? (
          <p className="muted">
            OSM OAuth is not configured on this server. Set OSM_OAUTH_ENABLED, OSM_CLIENT_ID and
            OSM_CLIENT_SECRET, then restart the stack.
          </p>
        ) : osm?.connected ? (
          <div className="stack">
            <p>
              Signed in as <strong>{osm.username}</strong> ({osm.osm_user_id}). Scopes: {osm.scopes.join(', ')}.
              API: <span className="mono">{osm.api_base_url}</span>
            </p>
            <button className="btn btn-ghost btn-sm" onClick={disconnectOsm}>
              Disconnect
            </button>
          </div>
        ) : (
          <div className="stack">
            <p className="muted">
              Connect your OSM account to preview and publish selected features. NasMap only
              requests {osm?.scopes.join(' and ') || 'read_prefs and write_api'}.
            </p>
            <button className="btn btn-secondary" onClick={connectOsm}>
              Connect OpenStreetMap
            </button>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>API keys</h2>
          <button className="btn btn-secondary btn-sm" onClick={() => setKeyModal(true)}>
            Create key
          </button>
        </div>
        <p className="muted">Use API keys with the <span className="mono">X-API-Key</span> header for scripts.</p>
        {keys.length === 0 ? (
          <p className="muted">No active API keys.</p>
        ) : (
          <div className="list">
            {keys.map((key) => (
              <div key={key.id} className="list-row">
                <div className="grow">
                  <strong>{key.name}</strong>
                  <small>
                    {key.key_prefix}… · created {formatDate(key.created_at)} ·{' '}
                    {key.expires_at ? `expires ${formatDate(key.expires_at)}` : 'no expiry'}
                  </small>
                </div>
                <button className="btn btn-ghost btn-xs danger" onClick={() => revokeKey(key.id)}>
                  Revoke
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {keyModal && (
        <Modal title="Create API key" onClose={() => setKeyModal(false)}>
          <div className="stack">
            <Field label="Key name">
              <input value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="QGIS upload script" />
            </Field>
            <button className="btn btn-primary" disabled={!keyName.trim()} onClick={createKey}>
              Create key
            </button>
          </div>
        </Modal>
      )}

      {newKey && (
        <Modal title="Copy your API key" onClose={() => setNewKey(null)}>
          <div className="stack">
            <div className="warning-box">This key is shown only once. Store it in a secret manager.</div>
            <pre className="code-block">{newKey}</pre>
            <button className="btn btn-primary" onClick={() => setNewKey(null)}>
              Done
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
