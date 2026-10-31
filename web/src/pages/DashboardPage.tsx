import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../api/auth';
import { usePublicConfig } from '../api/config';
import type { ImportJob, Layer, Paged } from '../api/types';
import BlankLayerDialog from '../components/BlankLayerDialog';
import Icon from '../components/Icon';
import { Badge, EmptyState, ErrorBox, Progress, Spinner, formatDate } from '../components/ui';

export default function DashboardPage() {
  const config = usePublicConfig();
  const { user } = useAuth();
  const canWrite = user?.role === 'admin' || user?.role === 'editor';
  const navigate = useNavigate();
  const [blankOpen, setBlankOpen] = useState(false);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [layerTotal, setLayerTotal] = useState(0);
  const [jobTotal, setJobTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<Paged<Layer>>('/layers?limit=6'),
      api<Paged<ImportJob>>('/imports?limit=6'),
    ])
      .then(([layerData, jobData]) => {
        setLayers(layerData.items);
        setJobs(jobData.items);
        setLayerTotal(layerData.meta.total);
        setJobTotal(jobData.meta.total);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load the dashboard'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner full />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="page-subtitle">Start a task, or pick up where you left off.</p>
        </div>
      </header>

      <ErrorBox message={error} />

      <section className={`task-grid ${canWrite ? '' : 'two'}`} aria-label="Common tasks">
        {canWrite && (
          <>
            <Link to="/map?new=upload" className="task-card primary">
              <span className="task-icon"><Icon name="upload" size={19} /></span>
              <strong>Import data</strong>
              <span>Files, URLs, folders, photos or OSM</span>
            </Link>
            <button className="task-card" onClick={() => setBlankOpen(true)}>
              <span className="task-icon"><Icon name="plus" size={19} /></span>
              <strong>Draw a layer</strong>
              <span>Add points, lines or polygons on the map</span>
            </button>
          </>
        )}
        <Link to="/live" className="task-card">
          <span className="task-icon"><Icon name="weather" size={19} /></span>
          <strong>{canWrite ? 'Add live data' : 'Live data'}</strong>
          <span>Weather radar, forecasts and earthquakes</span>
        </Link>
        <Link to="/map" className="task-card">
          <span className="task-icon"><Icon name="map" size={19} /></span>
          <strong>Open the map</strong>
          <span>Explore layers and find a place</span>
        </Link>
      </section>

      <div className="glance">
        <span><strong>{layerTotal.toLocaleString()}</strong> layers visible to you</span>
        <span><strong>{jobTotal.toLocaleString()}</strong> imports all time</span>
        <span><strong>{config?.basemap_mode === 'local' ? 'Local tiles' : 'OSM raster'}</strong> basemap</span>
        <span>Signed in as <strong>{user?.role}</strong></span>
      </div>

      <div className="two-col">
        <section className="panel">
          <div className="panel-head">
            <h2>Recent layers</h2>
            <Link to="/map" className="link">
              Open map
            </Link>
          </div>
          {layers.length === 0 ? (
            <EmptyState title="No layers yet">
              <p>Import a file, connect a URL, or draw a new layer on the map.</p>
            </EmptyState>
          ) : (
            <div className="list">
              {layers.map((layer) => (
                <Link key={layer.id} to={`/map?layer=${layer.id}`} className="list-row">
                  <span className={`layer-glyph ${layer.geometry_type}`}>
                    <Icon name={geometryIcon(layer.geometry_type)} size={15} />
                  </span>
                  <div className="grow">
                    <strong>{layer.name}</strong>
                    <small>
                      {layer.feature_count.toLocaleString()} {layer.geometry_type === 'raster' ? 'raster' : 'features'} ·{' '}
                      {sourceLabel(layer.source_type)}
                    </small>
                  </div>
                  {layer.visibility !== 'private' && (
                    <Badge tone={layer.visibility === 'public' ? 'success' : 'info'}>
                      {visibilityLabel(layer.visibility)}
                    </Badge>
                  )}
                </Link>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Recent imports</h2>
            <Link to="/jobs" className="link">
              All imports
            </Link>
          </div>
          {jobs.length === 0 ? (
            <EmptyState title="No imports yet">
              <p>Upload a file or start an import from a URL or server folder.</p>
            </EmptyState>
          ) : (
            <div className="list">
              {jobs.map((job) => (
                <div key={job.id} className="list-row">
                  <div className="job-status-dot" data-status={job.status} />
                  <div className="grow">
                    <strong>{job.options?.name || job.job_type}</strong>
                    <small>
                      {jobTypeLabel(job.job_type)} · {job.status} · {formatDate(job.created_at)}
                    </small>
                    {job.status === 'running' && job.message && (
                      <small className="job-message">{job.message}</small>
                    )}
                    {job.status === 'failed' && job.error && (
                      <small className="job-message danger">{job.error}</small>
                    )}
                    {job.status === 'running' && <Progress value={job.progress} />}
                  </div>
                  {job.layer_id && (
                    <Link className="link" to={`/map?layer=${job.layer_id}`}>
                      View
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {blankOpen && (
        <BlankLayerDialog
          onClose={() => setBlankOpen(false)}
          onCreated={(layer) => navigate(`/map?layer=${layer.id}`)}
        />
      )}
    </div>
  );
}

function visibilityLabel(value: string) {
  if (value === 'public') return 'Public';
  if (value === 'organisation') return 'Internal';
  return 'Private';
}

function sourceLabel(value: string) {
  if (value === 'manual') return 'Drawn';
  if (value === 'upload') return 'File';
  if (value === 'url') return 'Link';
  if (value === 'osm') return 'OSM';
  if (value === 'tessera') return 'Tessera';
  if (value === 'api') return 'Live';
  return value;
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

function geometryIcon(type: string): 'point' | 'line' | 'polygon' | 'layers' | 'table' | 'image' {
  if (type === 'point') return 'point';
  if (type === 'line') return 'line';
  if (type === 'polygon') return 'polygon';
  if (type === 'table') return 'table';
  if (type === 'raster') return 'image';
  return 'layers';
}
