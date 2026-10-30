import { useState } from 'react';
import { api } from '../api/client';
import Icon from './Icon';

interface PlaceResult {
  name: string;
  lat: number | null;
  lon: number | null;
  bbox: [number, number, number, number] | null;
  type: string;
}

export default function MapPlaceSearch({
  onSelect,
}: {
  onSelect: (bbox: [number, number, number, number] | null, lon: number, lat: number) => void;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlaceResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ results: PlaceResult[] }>(
        `/tools/geocode?q=${encodeURIComponent(query.trim())}`,
      );
      setResults(data.results);
      if (!data.results.length) setError('No matching place.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Place search failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="place-search">
      <form onSubmit={submit}>
        <Icon name="search" size={14} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={busy ? 'Searching…' : 'Find a place…'}
          aria-label="Search for a place"
        />
      </form>
      {(results.length > 0 || error) && (
        <div className="place-results">
          {error && <p className="hint pad-x">{error}</p>}
          {results.map((result, index) => (
            <button
              key={`${result.name}-${index}`}
              type="button"
              onClick={() => {
                if (result.lon != null && result.lat != null) {
                  onSelect(result.bbox, result.lon, result.lat);
                  setResults([]);
                  setQuery(result.name.split(',')[0]);
                }
              }}
            >
              <strong>{result.name.split(',')[0]}</strong>
              <small>{result.name}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
