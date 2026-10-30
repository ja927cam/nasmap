import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ImportJob, PublicConfig, TesseraCoverage } from '../api/types';
import BBoxPicker from './BBoxPicker';
import GeoSearch from './GeoSearch';
import { ErrorBox } from './ui';

interface Meta {
  enabled: boolean;
  version: string;
  variants: string[];
  years: number[];
  max_tiles: number;
  band_count: number;
  resolution: string;
  licence: string;
  attribution: string;
}

export default function TesseraForm({
  config,
  onJob,
}: {
  config: PublicConfig;
  onJob: (job: ImportJob) => void;
}) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [bbox, setBbox] = useState<[number, number, number, number] | null>(null);
  const [year, setYear] = useState(2024);
  const [variant, setVariant] = useState('');
  const [name, setName] = useState('');
  const [bandsText, setBandsText] = useState('1,2,3');
  const [visibility, setVisibility] = useState<'private' | 'organisation' | 'public'>('private');
  const [coverage, setCoverage] = useState<TesseraCoverage | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [importing, setImporting] = useState(false);
  const [place, setPlace] = useState<string | null>(null);

  useEffect(() => {
    api<Meta>('/tessera/meta')
      .then((data) => {
        setMeta(data);
        if (data.years?.length) setYear(data.years[data.years.length - 1]);
        if (data.variants?.length) setVariant(data.variants[0]);
      })
      .catch((err) => setMetaError(err instanceof Error ? err.message : 'Tessera unavailable'));
  }, []);

  const tileBoxes = useMemo(() => coverage?.tiles.map((tile) => tile.bbox) ?? [], [coverage]);
  const bands = useMemo(() => {
    const parsed = bandsText
      .split(',')
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isInteger(value) && value >= 1 && value <= 128);
    return parsed.length ? parsed : null;
  }, [bandsText]);

  async function checkCoverage() {
    if (!bbox) return;
    setChecking(true);
    setCoverageError(null);
    setCoverage(null);
    try {
      const result = await api<TesseraCoverage>('/tessera/coverage', {
        method: 'POST',
        body: { bbox, year, variant: variant || undefined },
      });
      setCoverage(result);
    } catch (err) {
      setCoverageError(err instanceof Error ? err.message : 'Coverage check failed');
    } finally {
      setChecking(false);
    }
  }

  async function startImport() {
    if (!bbox) return;
    setImporting(true);
    setCoverageError(null);
    try {
      const job = await api<ImportJob>('/tessera/import', {
        method: 'POST',
        body: {
          bbox,
          year,
          variant: variant || undefined,
          name: name || undefined,
          visibility,
          bands,
        },
      });
      onJob(job);
    } catch (err) {
      setCoverageError(err instanceof Error ? err.message : 'Could not start import');
    } finally {
      setImporting(false);
    }
  }

  if (metaError) return <ErrorBox message={metaError} />;
  if (!meta) return <p className="muted">Loading Tessera registry…</p>;
  if (!meta.enabled) return <p className="muted">Tessera support is disabled on this server.</p>;

  return (
    <div className="tessera-form">
      <div className="grid-2">
        <div className="stack">
          <GeoSearch
            onSelect={(box, label) => {
              setBbox(box);
              setPlace(label);
              setCoverage(null);
            }}
          />
          <p className="muted small">
            {place ? `Selected: ${place}` : 'Search a place, or drag a rectangle on the map.'}
          </p>
          <div className="grid-2">
            <label className="field">
              <span>Year</span>
              <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
                {meta.years.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Variant</span>
              <select value={variant} onChange={(e) => setVariant(e.target.value)}>
                {meta.variants.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid-2">
            <label className="field">
              <span>Layer name</span>
              <input
                placeholder={`Tessera ${year}`}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="field">
              <span>Visibility</span>
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value as typeof visibility)}
              >
                <option value="private">Private</option>
                <option value="organisation">Internal</option>
                <option value="public">Public</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>Export bands</span>
            <input
              value={bandsText}
              onChange={(e) => setBandsText(e.target.value)}
              placeholder="1,2,3 (empty = all 128)"
            />
            <small>
              Default 1,2,3 keeps the web COG small. Leave empty to export all 128
              channels for GIS analysis (large).
            </small>
          </label>
          <div className="bbox-inputs">
            {bbox ? bbox.map((value, index) => <span key={index}>{value.toFixed(4)}</span>) : <span>No area selected</span>}
          </div>
          <div className="button-row">
            <button className="btn btn-secondary" onClick={checkCoverage} disabled={!bbox || checking}>
              {checking ? 'Checking…' : 'Check coverage'}
            </button>
            <button
              className="btn btn-primary"
              onClick={startImport}
              disabled={!coverage || !coverage.coverage_within_limit || importing}
            >
              {importing ? 'Starting…' : 'Import Tessera'}
            </button>
          </div>
          {coverage && (
            <div className="coverage-note">
              <strong>{coverage.tile_count} tile(s)</strong> for {coverage.year} · {coverage.variant} ·{' '}
              {coverage.resolution} · {coverage.band_count} bands
              {!coverage.coverage_within_limit && (
                <div className="error-box">
                  Area exceeds the {coverage.max_tiles} tile limit. Narrow the box or ask the admin
                  to raise TESSERA_MAX_TILES.
                </div>
              )}
            </div>
          )}
          <ErrorBox message={coverageError} />
          <p className="hint">
            Downloads run in the background. Cache: {config.tessera_enabled ? 'enabled' : 'disabled'} ·
            Licence: {meta.licence}
          </p>
        </div>
        <BBoxPicker
          bbox={bbox}
          osmTileUrl={config.osm_tile_url}
          attribution={config.osm_tile_attribution}
          onChange={(box) => {
            setBbox(box);
            setPlace(null);
            setCoverage(null);
          }}
          tileBoxes={tileBoxes}
          height={360}
        />
      </div>
    </div>
  );
}
