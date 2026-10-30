import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../api/auth';
import { usePublicConfig } from '../api/config';
import type { ImportJob, Layer, Paged } from '../api/types';
import BlankLayerDialog from '../components/BlankLayerDialog';
import Icon from '../components/Icon';
import { Badge, EmptyState, Progress, Spinner, formatDate } from '../components/ui';

export default function DashboardPage() {
  const config = usePublicConfig();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [blankOpen, setBlankOpen] = useState(false);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [layerTotal, setLayerTotal] = useState(0);
  const [jobTotal, setJobTotal] = useState(0);
  const [loading, setLoading] = useState(true);

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
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spinner full />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="page-subtitle">Layers and import activity on this instance.</p>
        </div>
        <div className="head-actions">
          {(user?.role === 'admin' || user?.role === 'editor') && (
            <button className="btn btn-secondary" onClick={() => setBlankOpen(true)}>
              <Icon name="plus" size={15} />
              Blank layer
            </button>
          )}
          <Link to="/map?new=upload" className="btn btn-primary">
            <Icon name="upload" size={15} />
            Import data
          </Link>
        </div>
      </header>

      <section className="stat-grid">
        <div className="stat-card">
          <span>Layers</span>
          <strong>{layerTotal.toLocaleString()}</strong>
          <small>Visible to your account</small>
        </div>
        <div className="stat-card">
          <span>Import jobs</span>
          <strong>{jobTotal.toLocaleString()}</strong>
          <small>All time</small>
        </div>
        <div className="stat-card">
          <span>Basemap</span>
          <strong>{config?.basemap_mode === 'local' ? 'Local' : 'OSM'}</strong>
          <small>{config?.basemap_mode === 'local' ? 'Vector tiles' : 'Raster tiles'}</small>
        </div>
        <div className="stat-card">
          <span>Tessera</span>
          <strong>{config?.tessera_enabled ? 'On' : 'Off'}</strong>
          <small>Satellite embeddings</small>
        </div>
      </section>

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
                      {layer.source_type}
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
                      {job.job_type} · {job.status} · {formatDate(job.created_at)}
                    </small>
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

function geometryIcon(type: string): 'point' | 'line' | 'polygon' | 'layers' | 'table' | 'image' {
  if (type === 'point') return 'point';
  if (type === 'line') return 'line';
  if (type === 'polygon') return 'polygon';
  if (type === 'table') return 'table';
  if (type === 'raster') return 'image';
  return 'layers';
}
