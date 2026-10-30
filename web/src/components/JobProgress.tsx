import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { ImportJob } from '../api/types';
import { Modal, Progress } from './ui';

export default function JobProgress({
  jobId,
  onClose,
  onComplete,
}: {
  jobId: string;
  onClose: () => void;
  onComplete: (job: ImportJob) => void;
}) {
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    async function poll() {
      try {
        const next = await api<ImportJob>(`/imports/${jobId}`);
        if (!active) return;
        setJob(next);
        if (['succeeded', 'failed', 'cancelled'].includes(next.status)) {
          if (next.status === 'succeeded') onComplete(next);
          return;
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : 'Could not load job');
        return;
      }
      timer = window.setTimeout(poll, 1500);
    }
    void poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId, onComplete, attempt]);

  async function cancel() {
    try {
      await api(`/imports/${jobId}/cancel`, { method: 'POST' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel');
    }
  }

  async function retry() {
    setError(null);
    try {
      await api(`/imports/${jobId}/retry`, { method: 'POST' });
      setJob(null);
      setAttempt((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not retry');
    }
  }

  const done = job && ['succeeded', 'failed', 'cancelled'].includes(job.status);

  return (
    <Modal title="Import job" onClose={onClose}>
      {!job ? (
        <p className="muted">Loading job…</p>
      ) : (
        <div className="stack">
          <div className="job-summary">
            <div>
              <strong>{job.options?.name || job.job_type}</strong>
              <small className="muted">
                {job.job_type} · {job.status}
              </small>
            </div>
            <span className={`badge badge-${job.status}`}>{job.status}</span>
          </div>
          <Progress value={job.progress} />
          <p className="muted">{job.message}</p>
          {job.error && <div className="error-box">{job.error}</div>}
          {job.result?.feature_count !== undefined && (
            <div className="result-grid">
              <div>
                <span>Features</span>
                <strong>{job.result.feature_count.toLocaleString()}</strong>
              </div>
              <div>
                <span>Skipped</span>
                <strong>{(job.result.skipped_count ?? 0).toLocaleString()}</strong>
              </div>
              <div>
                <span>Invalid repaired</span>
                <strong>{(job.result.stats?.repaired_count ?? 0).toLocaleString()}</strong>
              </div>
            </div>
          )}
          {job.result?.tile_count !== undefined && (
            <p className="muted">{job.result.tile_count} Tessera tile(s) exported.</p>
          )}
          {job.job_type === 'ingest' && (
            <div className="result-grid">
              <div>
                <span>New features</span>
                <strong>{(job.result?.created_features ?? 0).toLocaleString()}</strong>
              </div>
              <div>
                <span>Attached</span>
                <strong>{(job.result?.attached_photos ?? 0).toLocaleString()}</strong>
              </div>
              <div>
                <span>Files</span>
                <strong>{job.result?.scanned ?? job.result?.succeeded ?? 0}</strong>
              </div>
            </div>
          )}
          {job.job_type === 'ingest' && job.result?.failed > 0 && (
            <p className="muted">{job.result.failed} file(s) failed. See the import list for child jobs.</p>
          )}
          {!done && (
            <button className="btn btn-ghost btn-sm" onClick={cancel}>
              Cancel import
            </button>
          )}
          {job.status === 'failed' || job.status === 'cancelled' ? (
            <button className="btn btn-secondary btn-sm" onClick={retry}>
              Retry import
            </button>
          ) : null}
          {job.status === 'succeeded' && job.layer_id && (
            <button className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          )}
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
    </Modal>
  );
}
