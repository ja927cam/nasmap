import { useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../api/auth';
import { API_BASE, ApiError } from '../api/client';
import { usePublicConfig } from '../api/config';
import Icon from '../components/Icon';
import { ErrorBox } from '../components/ui';

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const config = usePublicConfig();
  const [params] = useSearchParams();
  const osmStatus = params.get('osm');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(
    osmStatus === 'no_account'
      ? 'No Strata account is linked to that OpenStreetMap account. Sign in normally, then connect OSM in Settings.'
      : osmStatus === 'disabled'
        ? 'That account is disabled.'
        : osmStatus
          ? 'OpenStreetMap sign-in did not complete.'
          : null,
  );
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not sign in');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark large">
            <Icon name="layers" size={22} strokeWidth={2} />
          </span>
          <div>
            <h1>Strata</h1>
            <p>Self-hosted geospatial data</p>
          </div>
        </div>
        <div className="auth-form-head">
          <h2>Sign in</h2>
          <p>Access your layers and imports.</p>
        </div>
        <form onSubmit={submit} className="stack">
          <label className="field">
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <ErrorBox message={error} />
          <button className="btn btn-primary btn-block" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        {config?.osm_oauth_enabled && (
          <a className="btn btn-secondary btn-block auth-alt-action" href={`${API_BASE}/osm/login?redirect_to=/`}>
            Sign in with OpenStreetMap
          </a>
        )}
        <p className="auth-footer">
          New here? <Link to="/register">Create an account</Link>
        </p>
      </div>
      <div className="auth-art">
        <div className="auth-panel-copy">
          <h2>Private geospatial data</h2>
          <p>
            This instance stores layers in PostgreSQL/PostGIS and serves them with MapLibre.
            Basemaps, imports and satellite embeddings stay on this server.
          </p>
          <ul>
            <li>Private vector and raster layers</li>
            <li>File, URL and server-side imports</li>
            <li>No third-party account required</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
