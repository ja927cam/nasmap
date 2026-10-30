import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, download } from '../api/client';
import { useAuth } from '../api/auth';
import { usePublicConfig } from '../api/config';
import type { ImportJob, Layer, Paged } from '../api/types';
import Icon from '../components/Icon';
import JobProgress from '../components/JobProgress';
import TesseraForm from '../components/TesseraForm';
import { EmptyState, ErrorBox, Field, Spinner, formatDate } from '../components/ui';

type Provider = 'xyz' | 'tilejson' | 'wms' | 'vectortile' | 'cog' | 'tessera';

const providers: { id: Provider; label: string; hint: string }[] = [
  { id: 'xyz', label: 'XYZ / TMS', hint: 'Add any raster tile service with a {z}/{x}/{y} URL.' },
  { id: 'tilejson', label: 'TileJSON', hint: 'Use the raster tiles described by a TileJSON document.' },
  { id: 'wms', label: 'WMS', hint: 'Add an OGC Web Map Service layer.' },
  { id: 'vectortile', label: 'Vector tiles', hint: 'Render vector PBF tiles from a TileJSON document.' },
  { id: 'cog', label: 'GeoTIFF / COG', hint: 'Download a remote GeoTIFF or COG as a raster layer.' },
  { id: 'tessera', label: 'Tessera', hint: 'Import GeoTessera satellite embeddings.' },
];

interface Preset {
  id: string;
  label: string;
  provider: 'xyz' | 'wms';
  description: string;
  attribution: string;
  licence: string;
  config: Record<string, unknown>;
}

interface Dataset {
  id: string;
  layer_id: string;
  year: number;
  variant: string;
  tile_ids: unknown[];
  band_count: number;
  resolution: number;
  crs: string;
  licence: string;
  attribution: string;
  created_at: string;
}

export default function OverlaysPage() {
  const config = usePublicConfig();
  const { user } = useAuth();
  const canEdit = user?.role === 'admin' || user?.role === 'editor';
  const [provider, setProvider] = useState<Provider>('xyz');
  const [overlays, setOverlays] = useState<Layer[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [loading, setLoading] = useState(true);
  const [presetBusy, setPresetBusy] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [created, setCreated] = useState<Layer | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<Paged<Layer>>('/layers?limit=500');
      setOverlays(
        data.items.filter(
          (layer) =>
            (layer.geometry_type === 'raster' ||
              layer.metadata?.provider === 'vectortile') &&
            (layer.source_type === 'tessera' || layer.source_type === 'url'),
        ),
      );
      setPresets(await api<Preset[]>('/overlays/presets'));
      if (config?.tessera_enabled) {
        setDatasets(await api<Dataset[]>('/tessera/datasets'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load overlays');
    } finally {
      setLoading(false);
    }
  }, [config?.tessera_enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!config || loading) return <Spinner full />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Overlays</h1>
          <p className="page-subtitle">
            Add raster services or satellite embeddings on top of your layers.
          </p>
        </div>
      </header>

      {canEdit && (
      <section className="panel">
        <div className="panel-head">
          <h2>One-click overlays</h2>
        </div>
        <p className="hint">
          These presets use public services. Check each provider’s terms for production use.
        </p>
        <div className="preset-grid">
          {presets.map((preset) => (
            <div key={preset.id} className="preset-card">
              <div>
                <strong>{preset.label}</strong>
                <p>{preset.description}</p>
              </div>
              <button
                className="btn btn-secondary btn-xs"
                disabled={presetBusy === preset.id}
                onClick={async () => {
                  setPresetBusy(preset.id);
                  setError(null);
                  try {
                    const layer = await api<Layer>(
                      preset.provider === 'wms' ? '/overlays/wms' : '/overlays/xyz',
                      {
                        method: 'POST',
                        body: {
                          name: preset.label,
                          visibility: 'private',
                          attribution: preset.attribution,
                          licence: preset.licence,
                          ...preset.config,
                        },
                      },
                    );
                    setCreated(layer);
                    await load();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : 'Could not add preset');
                  } finally {
                    setPresetBusy(null);
                  }
                }}
              >
                {presetBusy === preset.id ? 'Adding…' : 'Add'}
              </button>
            </div>
          ))}
        </div>
      </section>
      )}

      {canEdit && (
      <section className="panel">
        <div className="panel-head">
          <h2>Add overlay</h2>
        </div>
        <div className="tabs">
          {providers
            .filter((item) => item.id !== 'tessera' || config.tessera_enabled)
            .map((item) => (
              <button
                key={item.id}
                className={provider === item.id ? 'tab active' : 'tab'}
                onClick={() => {
                  setProvider(item.id);
                  setCreated(null);
                  setError(null);
                }}
              >
                {item.label}
              </button>
            ))}
        </div>
        <p className="hint pad-x">{providers.find((item) => item.id === provider)?.hint}</p>

        {provider === 'tessera' ? (
          <TesseraForm config={config} onJob={(job: ImportJob) => setJobId(job.id)} />
        ) : (
          <AddOverlayForm
            provider={provider}
            onCreated={(layer) => {
              setCreated(layer);
              void load();
            }}
            onJob={(job) => setJobId(job.id)}
          />
        )}

        {created && (
          <div className="success-box">
            Added overlay “{created.name}”.{' '}
            <Link to={`/map?layer=${created.id}`}>Open on the map</Link>
          </div>
        )}

        <p className="hint">
          Vector overlays from GeoJSON, WFS or ArcGIS can be added from{' '}
          <Link to="/map?new=url">Map → Add layer → From URL</Link>.
        </p>
      </section>
      )}

      <section className="panel">
        <div className="panel-head">
          <h2>Your overlays</h2>
        </div>
        {overlays.length === 0 ? (
          <EmptyState title="No overlays yet">
            <p>Add an XYZ, TileJSON or WMS service above, or import a Tessera area.</p>
          </EmptyState>
        ) : (
          <div className="list">
            {overlays.map((layer) => (
              <div key={layer.id} className="list-row">
                <span className={`layer-glyph ${layer.geometry_type}`}>
                  <Icon name="image" size={15} />
                </span>
                <div className="grow">
                  <strong>{layer.name}</strong>
                  <small>
                    {providerLabel(layer)} · {layer.visibility} · {layer.attribution || 'No attribution'}
                  </small>
                </div>
                <Link className="btn btn-ghost btn-xs" to={`/map?layer=${layer.id}`}>
                  Open
                </Link>
              </div>
            ))}
          </div>
        )}
      </section>

      {config.tessera_enabled && datasets.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <h2>Tessera exports</h2>
          </div>
          <div className="dataset-grid">
            {datasets.map((dataset) => (
              <div key={dataset.id} className="dataset-card">
                <div className="dataset-top">
                  <strong>
                    {dataset.year} · {dataset.variant}
                  </strong>
                  <span className="badge">{dataset.tile_ids.length} tiles</span>
                </div>
                <dl className="kv">
                  <dt>Bands</dt>
                  <dd>{dataset.band_count}</dd>
                  <dt>Resolution</dt>
                  <dd>{dataset.resolution} m</dd>
                  <dt>Created</dt>
                  <dd>{formatDate(dataset.created_at)}</dd>
                </dl>
                <div className="button-row">
                  <Link className="btn btn-secondary btn-sm" to={`/map?layer=${dataset.layer_id}`}>
                    Open layer
                  </Link>
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() =>
                      download(
                        `/tessera/datasets/${dataset.id}/download`,
                        `tessera-${dataset.year}.zip`,
                      )
                    }
                  >
                    Download GeoTIFFs
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {jobId && (
        <JobProgress
          jobId={jobId}
          onClose={() => setJobId(null)}
          onComplete={() => {
            void load();
          }}
        />
      )}
      <ErrorBox message={error} />
    </div>
  );
}

function AddOverlayForm({
  provider,
  onCreated,
  onJob,
}: {
  provider: Exclude<Provider, 'tessera'>;
  onCreated: (layer: Layer) => void;
  onJob: (job: ImportJob) => void;
}) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [tileSize, setTileSize] = useState(256);
  const [minzoom, setMinzoom] = useState(0);
  const [maxzoom, setMaxzoom] = useState(20);
  const [scheme, setScheme] = useState<'xyz' | 'tms'>('xyz');
  const [wmsLayers, setWmsLayers] = useState('');
  const [wmsVersion, setWmsVersion] = useState('1.3.0');
  const [wmsFormat, setWmsFormat] = useState('image/png');
  const [wmsTransparent, setWmsTransparent] = useState(true);
  const [wmsOptions, setWmsOptions] = useState<{ name: string; title: string }[]>([]);
  const [wmsLoading, setWmsLoading] = useState(false);
  const [sourceLayer, setSourceLayer] = useState('');
  const [vectorColor, setVectorColor] = useState('#7c3aed');
  const [attribution, setAttribution] = useState('');
  const [licence, setLicence] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [boundsText, setBoundsText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const bounds = boundsText.trim()
        ? boundsText.split(',').map((value) => Number(value.trim()))
        : undefined;
      if (provider === 'cog') {
        const job = await api<ImportJob>('/imports/url', {
          method: 'POST',
          body: {
            url,
            name,
            kind: 'cog',
            visibility,
            attribution,
            licence,
          },
        });
        onJob(job);
        setName('');
        setUrl('');
        return;
      }
      let layer: Layer;
      if (provider === 'xyz') {
        layer = await api<Layer>('/overlays/xyz', {
          method: 'POST',
          body: {
            name,
            url_template: url,
            tile_size: tileSize,
            minzoom,
            maxzoom,
            scheme,
            attribution,
            licence,
            visibility,
            bounds,
          },
        });
      } else if (provider === 'tilejson') {
        layer = await api<Layer>('/overlays/tilejson', {
          method: 'POST',
          body: { name, tilejson_url: url, attribution, licence, visibility, bounds },
        });
      } else if (provider === 'vectortile') {
        layer = await api<Layer>('/overlays/vectortile', {
          method: 'POST',
          body: {
            name,
            tilejson_url: url,
            source_layer: sourceLayer,
            color: vectorColor,
            minzoom,
            maxzoom,
            attribution,
            licence,
            visibility,
            bounds,
          },
        });
      } else {
        layer = await api<Layer>('/overlays/wms', {
          method: 'POST',
          body: {
            name,
            url,
            layers: wmsLayers,
            version: wmsVersion,
            format: wmsFormat,
            transparent: wmsTransparent,
            attribution,
            licence,
            visibility,
            bounds,
          },
        });
      }
      onCreated(layer);
      setName('');
      setUrl('');
      setWmsLayers('');
      setBoundsText('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add overlay');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <div className="grid-2">
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label="Visibility">
          <select value={visibility} onChange={(e) => setVisibility(e.target.value as typeof visibility)}>
            <option value="private">Private</option>
            <option value="organisation">Internal</option>
            <option value="public">Public</option>
          </select>
        </Field>
      </div>

      <Field
        label={
          provider === 'wms'
            ? 'WMS endpoint'
            : provider === 'tilejson' || provider === 'vectortile'
              ? 'TileJSON URL'
              : provider === 'cog'
                ? 'GeoTIFF / COG URL'
                : 'Tile URL template'
        }
        help={
          provider === 'wms'
            ? 'WMS requests are proxied through Strata with EPSG:3857 tiles.'
            : provider === 'tilejson'
              ? 'TileJSON is fetched server-side; its first raster tile URL is used.'
              : provider === 'cog'
                ? 'The raster is downloaded and converted to a COG in the background.'
                : 'The URL must contain {z}, {x} and {y}. {s} is replaced with the subdomain a.'
        }
        hint={
          provider === 'xyz'
            ? 'Example: https://tiles.example.org/{z}/{x}/{y}.png'
            : provider === 'tilejson' || provider === 'vectortile'
              ? 'URL of a TileJSON document describing the tiles'
              : provider === 'cog'
                ? 'The file is downloaded and converted to a COG in the background.'
                : 'Base GetMap endpoint without parameters'
        }
      >
        <input
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setWmsOptions([]);
          }}
          placeholder={
            provider === 'xyz'
              ? 'https://tiles.example.org/{z}/{x}/{y}.png'
              : provider === 'tilejson' || provider === 'vectortile'
                ? 'https://example.org/tiles.json'
                : provider === 'cog'
                  ? 'https://example.org/elevation.tif'
                  : 'https://example.org/geoserver/wms'
          }
          required
        />
      </Field>

      {provider === 'wms' && (
        <div className="grid-2">
          <Field label="WMS layers" hint="Comma-separated layer names.">
            <div className="input-action">
              <input value={wmsLayers} onChange={(e) => setWmsLayers(e.target.value)} required />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={!url || wmsLoading}
                onClick={async () => {
                  setWmsLoading(true);
                  setError(null);
                  try {
                    const data = await api<{ version: string; layers: { name: string; title: string }[] }>(
                      '/overlays/wms/capabilities',
                      { method: 'POST', body: { url } },
                    );
                    setWmsOptions(data.layers);
                    if (data.layers.length === 1) setWmsLayers(data.layers[0].name);
                  } catch (err) {
                    setError(err instanceof Error ? err.message : 'Could not load WMS capabilities');
                  } finally {
                    setWmsLoading(false);
                  }
                }}
              >
                {wmsLoading ? 'Loading…' : 'Load layers'}
              </button>
            </div>
            {wmsOptions.length > 0 && (
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) setWmsLayers(e.target.value);
                }}
              >
                <option value="">Choose from capabilities…</option>
                {wmsOptions.map((option) => (
                  <option key={option.name} value={option.name}>
                    {option.title} ({option.name})
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Version">
            <select value={wmsVersion} onChange={(e) => setWmsVersion(e.target.value)}>
              <option value="1.3.0">1.3.0</option>
              <option value="1.1.1">1.1.1</option>
            </select>
          </Field>
          <Field label="Image format">
            <select value={wmsFormat} onChange={(e) => setWmsFormat(e.target.value)}>
              <option value="image/png">PNG</option>
              <option value="image/jpeg">JPEG</option>
            </select>
          </Field>
          <Field label="Transparency">
            <select
              value={wmsTransparent ? 'yes' : 'no'}
              onChange={(e) => setWmsTransparent(e.target.value === 'yes')}
            >
              <option value="yes">Transparent background</option>
              <option value="no">Opaque background</option>
            </select>
          </Field>
        </div>
      )}

      {provider === 'vectortile' && (
        <div className="grid-2">
          <Field label="Source layer" hint="The vector_layers id inside the tiles.">
            <input value={sourceLayer} onChange={(e) => setSourceLayer(e.target.value)} />
          </Field>
          <Field label="Colour">
            <input type="color" value={vectorColor} onChange={(e) => setVectorColor(e.target.value)} />
          </Field>
        </div>
      )}

      {(provider === 'xyz' || provider === 'vectortile') && (
        <div className="grid-2">
          {provider === 'xyz' && (
            <Field label="Tile size">
              <select value={tileSize} onChange={(e) => setTileSize(Number(e.target.value))}>
                <option value={256}>256 px</option>
                <option value={512}>512 px</option>
              </select>
            </Field>
          )}
          {provider === 'xyz' && (
            <Field label="Scheme">
              <select value={scheme} onChange={(e) => setScheme(e.target.value as 'xyz' | 'tms')}>
                <option value="xyz">XYZ</option>
                <option value="tms">TMS</option>
              </select>
            </Field>
          )}
          <Field label="Minimum zoom">
            <input
              type="number"
              min={0}
              max={22}
              value={minzoom}
              onChange={(e) => setMinzoom(Number(e.target.value))}
            />
          </Field>
          <Field label="Maximum zoom">
            <input
              type="number"
              min={0}
              max={22}
              value={maxzoom}
              onChange={(e) => setMaxzoom(Number(e.target.value))}
            />
          </Field>
        </div>
      )}

      <div className="grid-2">
        <Field label="Attribution">
          <input value={attribution} onChange={(e) => setAttribution(e.target.value)} />
        </Field>
        <Field label="Licence">
          <input value={licence} onChange={(e) => setLicence(e.target.value)} />
        </Field>
      </div>

      <Field label="Bounds (optional)" hint="west,south,east,north in EPSG:4326">
        <input value={boundsText} onChange={(e) => setBoundsText(e.target.value)} placeholder="-180,-85,180,85" />
      </Field>

      <ErrorBox message={error} />
      <div className="button-row end">
        <button className="btn btn-primary" disabled={busy || !name.trim() || !url.trim()}>
          {busy ? 'Adding…' : provider === 'cog' ? 'Start import' : 'Add overlay'}
        </button>
      </div>
    </form>
  );
}

function providerLabel(layer: Layer) {
  const provider = layer.metadata?.provider;
  if (provider) return String(provider);
  if (layer.source_type === 'tessera') return 'tessera';
  if (layer.metadata?.wms) return 'wms';
  if (layer.metadata?.xyz) return 'xyz';
  return 'raster';
}
