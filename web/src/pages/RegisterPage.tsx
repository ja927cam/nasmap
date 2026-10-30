import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../api/auth';
import { ApiError } from '../api/client';
import Icon from '../components/Icon';
import { ErrorBox } from '../components/ui';

export default function RegisterPage() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register(email, password, displayName);
      navigate('/');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create account');
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
            <h1>NasMap</h1>
            <p>Self-hosted geospatial data</p>
          </div>
        </div>
        <div className="auth-form-head">
          <h2>Create account</h2>
          <p>The first account becomes the administrator.</p>
        </div>
        <form onSubmit={submit} className="stack">
          <label className="field">
            <span>Display name</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </label>
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
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <small>At least 8 characters.</small>
          </label>
          <ErrorBox message={error} />
          <button className="btn btn-primary btn-block" disabled={busy}>
            {busy ? 'Creating account…' : 'Create account'}
          </button>
        </form>
        <p className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
      <div className="auth-art">
        <div className="auth-panel-copy">
          <h2>First-time setup</h2>
          <p>Create the administrator account, then import data or connect an external source.</p>
          <ul>
            <li>PostGIS-backed layers</li>
            <li>Local or remote OSM basemaps</li>
            <li>Backups and audit history included</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
