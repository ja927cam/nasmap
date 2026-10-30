import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { ImportJob, Paged } from '../api/types';
import JobProgress from '../components/JobProgress';
import { Badge, EmptyState, Progress, Spinner, formatDate } from '../components/ui';

const statuses = ['all', 'queued', 'running', 'succeeded', 'failed', 'cancelled'] as const;

export default function JobsPage() {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [status, setStatus] = useState<(typeof statuses)[number]>('all');
  const [loading, setLoading] = useState(true);
  const [openJob, setOpenJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const query = status === 'all' ? '' : `&status=${status}`;
      const data = await api<Paged<ImportJob>>(`/imports?limit=100${query}`);
      setJobs(data.items);
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
          <h1>Jobs</h1>
          <p className="page-subtitle">File, URL, OSM, photo and folder imports.</p>
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
            {item === 'all' ? 'All' : item.charAt(0).toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>

      <section className="panel">
        {jobs.length === 0 ? (
          <EmptyState title="No jobs">
            <p>Imports and long-running background work appear here.</p>
          </EmptyState>
        ) : (
          <div className="list">
            {jobs.map((job) => (
              <div key={job.id} className="list-row job-row">
                <div className="job-status-dot" data-status={job.status} />
                <button className="job-name" onClick={() => setOpenJob(job.id)}>
                  <strong>{job.options?.name || job.job_type}</strong>
                  <small>
                    {job.job_type} · {formatDate(job.created_at)}
                  </small>
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
                  {job.status}
                </Badge>
                {job.layer_id && (
                  <Link className="btn btn-ghost btn-xs" to={`/map?layer=${job.layer_id}`}>
                    Open layer
                  </Link>
                )}
                {['failed', 'cancelled'].includes(job.status) && (
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
