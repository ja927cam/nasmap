import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { Paged, User } from '../api/types';
import { Badge, Spinner, formatDate } from '../components/ui';

interface Overview {
  counts: Record<string, number>;
  active_jobs: number;
  recent_jobs: { id: string; type: string; status: string; progress: number; created_at: string }[];
  server_time: string;
}

interface AuditEntry {
  id: number;
  user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, any>;
  created_at: string;
}

export default function AdminPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'users' | 'jobs' | 'audit'>('users');

  const load = useCallback(async () => {
    try {
      const [overviewData, userData, auditData] = await Promise.all([
        api<Overview>('/admin/overview'),
        api<Paged<User>>('/admin/users?limit=200'),
        api<AuditEntry[]>('/admin/audit?limit=100'),
      ]);
      setOverview(overviewData);
      setUsers(userData.items);
      setAudit(auditData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load admin data');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function updateUser(user: User, changes: Record<string, any>) {
    try {
      const updated = await api<User>(`/admin/users/${user.id}`, { method: 'PATCH', body: changes });
      setUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update user');
    }
  }

  if (!overview) return <Spinner full />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Administration</h1>
          <p className="page-subtitle">Users, import jobs and audit activity.</p>
        </div>
      </header>

      {error && <div className="error-box">{error}</div>}

      <section className="stat-grid">
        <div className="stat-card">
          <span>Users</span>
          <strong>{overview.counts.users ?? 0}</strong>
        </div>
        <div className="stat-card">
          <span>Layers</span>
          <strong>{overview.counts.layers ?? 0}</strong>
        </div>
        <div className="stat-card">
          <span>Features</span>
          <strong>{(overview.counts.features ?? 0).toLocaleString()}</strong>
        </div>
        <div className="stat-card">
          <span>Active jobs</span>
          <strong>{overview.active_jobs}</strong>
        </div>
      </section>

      <section className="panel">
        <div className="tabs">
          <button className={tab === 'users' ? 'tab active' : 'tab'} onClick={() => setTab('users')}>
            Users
          </button>
          <button className={tab === 'jobs' ? 'tab active' : 'tab'} onClick={() => setTab('jobs')}>
            Jobs
          </button>
          <button className={tab === 'audit' ? 'tab active' : 'tab'} onClick={() => setTab('audit')}>
            Audit log
          </button>
        </div>

        {tab === 'users' && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Name</th>
                  <th>Role</th>
                  <th>Active</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.email}</td>
                    <td>{user.display_name}</td>
                    <td>
                      <select
                        value={user.role}
                        onChange={(e) => updateUser(user, { role: e.target.value })}
                      >
                        <option value="admin">admin</option>
                        <option value="editor">editor</option>
                        <option value="viewer">viewer</option>
                      </select>
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        checked={user.is_active}
                        onChange={(e) => updateUser(user, { is_active: e.target.checked })}
                      />
                    </td>
                    <td>{formatDate(user.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'jobs' && (
          <div className="list">
            {overview.recent_jobs.map((job) => (
              <div key={job.id} className="list-row">
                <div className="job-status-dot" data-status={job.status} />
                <div className="grow">
                  <strong>{job.type}</strong>
                  <small>
                    {job.id.slice(0, 8)}… · {formatDate(job.created_at)} · {job.progress}%
                  </small>
                </div>
                <Badge tone={job.status === 'failed' ? 'danger' : job.status === 'succeeded' ? 'success' : 'default'}>
                  {job.status}
                </Badge>
              </div>
            ))}
          </div>
        )}

        {tab === 'audit' && (
          <div className="list">
            {audit.map((entry) => (
              <div key={entry.id} className="list-row">
                <div className="grow">
                  <strong>{entry.action}</strong>
                  <small>
                    {entry.entity_type} {entry.entity_id?.slice(0, 12) ?? ''} · {formatDate(entry.created_at)}
                  </small>
                </div>
                <details>
                  <summary className="link">details</summary>
                  <pre className="code-block small">{JSON.stringify(entry.details, null, 2)}</pre>
                </details>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
