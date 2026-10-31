import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../api/auth';
import type { ImportJob, Paged } from '../api/types';
import JobProgress from '../components/JobProgress';
import { Badge, EmptyState, Progress, Spinner, formatDate, formatJobStatus } from '../components/ui';

const statuses = ['all', 'queued', 'running', 'succeeded', 'failed', 'cancelled'] as const;

interface Source {
  id: string;
  kind: string;
  url: string;
  layer_id: string | null;
  refresh_interval_seconds: number | null;
  next_refresh_at: string | null;
  enabled: boolean;
}

function jobTypeLabel(value: string) {
  if (value === 'upload') return 'File import';
  if (value === 'url') return 'URL import';
  if (value === 'osm') return 'OSM import';
  if (value === 'ingest') return 'Folder import';
  if (value === 'raster') return 'Raster import';
  if (value === 'tessera') return 'Tessera';
  if (value === 'export') return 'Export';
  return value;
}

function sourceLabel(value: string) {
  if (value === 'url') return 'URL';
  if (value === 'upload') return 'File';
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatInterval(seconds: number) {
  if (seconds >= 86400) return `${Math.round(seconds / 86400)} day(s)`;
  if (seconds >= 3600) return `${Math.round(seconds / 3600)} hour(s)`;
  return `${Math.round(seconds / 60)} minute(s)`;
}

export default function JobsPage() {
  const { user } = useAuth();
  const canImport = user?.role === 'admin' || user?.role === 'editor';
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [status, setStatus] = useState<(typeof statuses)[number]>('all');
  const [loading, setLoading] = useState(true);
  const [openJob, setOpenJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const query = status === 'all' ? '' : `&status=${status}`;
      const [data, sourceData] = await Promise.all([
        api<Paged<ImportJob>>(`/imports?limit=100${query}`),
        api<Source[]>('/imports/sources'),
      ]);
      setJobs(data.items);
      setSources(sourceData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load jobs');
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Spinner full />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Imports & jobs</h1>
          <p className="page-subtitle">
            Everything Strata is processing, plus past imports, schedules and errors.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={() => void load()}>
          Refresh
        </button>
      </header>

      {error && <div className="error-box">{error}</div>}

      <div className="tabs">
        {statuses.map((item) => (
          <button
            key={item}
            className={status === item ? 'tab active' : 'tab'}
            onClick={() => setStatus(item)}
          >
            {item === 'all' ? 'All' : formatJobStatus(item)}
          </button>
        ))}
      </div>

      <section className="panel">
        {jobs.length === 0 ? (
          <EmptyState title="Nothing imported yet">
            <p>Imports and long-running background work will appear here with their progress.</p>
            {canImport && (
              <Link className="btn btn-primary btn-sm" to="/map?new=upload">
                Import data
              </Link>
            )}
          </EmptyState>
        ) : (
          <div className="list">
            {jobs.map((job) => (
              <div key={job.id} className="list-row job-row">
                <div className="job-status-dot" data-status={job.status} />
                <button className="job-name" onClick={() => setOpenJob(job.id)}>
                  <strong>{job.options?.name || job.job_type}</strong>
                  <small>
                    {jobTypeLabel(job.job_type)} · {formatDate(job.created_at)}
                  </small>
                  {job.status === 'running' && job.message && (
                    <small className="job-message">{job.message}</small>
                  )}
                  {job.status === 'failed' && job.error && (
                    <small className="job-message danger">{job.error}</small>
                  )}
                </button>
                {job.status === 'running' && (
                  <div className="job-progress-inline">
                    <Progress value={job.progress} />
                  </div>
                )}
                <Badge
                  tone={
                    job.status === 'failed'
                      ? 'danger'
                      : job.status === 'succeeded'
                        ? 'success'
                        : job.status === 'cancelled'
                          ? 'warning'
                          : 'info'
                  }
                >
                  {formatJobStatus(job.status)}
                </Badge>
                {job.layer_id && (
                  <Link className="btn btn-ghost btn-xs" to={`/map?layer=${job.layer_id}`}>
                    Open layer
                  </Link>
                )}
                {canImport && ['failed', 'cancelled'].includes(job.status) && (
                  <button
                    className="btn btn-ghost btn-xs"
                    onClick={async () => {
                      try {
                        await api(`/imports/${job.id}/retry`, { method: 'POST' });
                        await load();
                      } catch (err) {
                        setError(err instanceof Error ? err.message : 'Could not retry');
                      }
                    }}
                  >
                    Retry
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Scheduled sources</h2>
          <span className="muted small">Automatic URL refreshes</span>
        </div>
        {sources.length === 0 ? (
          <p className="muted">
            No automatic refreshes yet. When importing from a URL, open Advanced options and
            choose a refresh interval.
          </p>
        ) : (
          <div className="list">
            {sources.map((source) => (
              <div key={source.id} className="list-row">
                <div className="grow">
                  <strong>{sourceLabel(source.kind)} source</strong>
                  <small>
                    {source.url} ·{' '}
                    {source.refresh_interval_seconds
                      ? `every ${formatInterval(source.refresh_interval_seconds)}`
                      : 'no schedule'}
                    {source.next_refresh_at ? ` · next ${formatDate(source.next_refresh_at)}` : ''}
                  </small>
                </div>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={source.enabled}
                    disabled={!canImport}
                    onChange={async (e) => {
                      try {
                        await api(`/imports/sources/${source.id}`, {
                          method: 'PATCH',
                          body: { enabled: e.target.checked },
                        });
                        await load();
                      } catch (err) {
                        setError(err instanceof Error ? err.message : 'Could not update source');
                      }
                    }}
                  />
                  Enabled
                </label>
                {source.layer_id && (
                  <Link className="btn btn-ghost btn-xs" to={`/map?layer=${source.layer_id}`}>
                    Layer
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {openJob && (
        <JobProgress
          jobId={openJob}
          onClose={() => setOpenJob(null)}
          onComplete={() => void load()}
        />
      )}
    </div>
  );
}
