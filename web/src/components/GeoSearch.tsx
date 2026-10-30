import { useState } from 'react';
import { api } from '../api/client';

interface Result {
  name: string;
  lat: number;
  lon: number;
  bbox: [number, number, number, number] | null;
  type: string;
}

export default function GeoSearch({
  onSelect,
}: {
  onSelect: (bbox: [number, number, number, number], name: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Result[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api<{ results: Result[] }>(`/tools/geocode?q=${encodeURIComponent(query)}`);
      setResults(data.results);
      if (!data.results.length) setError('No matching place found.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="geo-search">
      <form onSubmit={search} className="inline-form">
        <input
          placeholder="Search a place, town or region…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="btn btn-secondary" disabled={busy}>
          {busy ? 'Searching…' : 'Search'}
        </button>
      </form>
      {error && <small className="muted">{error}</small>}
      {results.length > 0 && (
        <ul className="geo-results">
          {results.map((result, index) => (
            <li key={`${result.name}-${index}`}>
              <button
                type="button"
                className="geo-result"
                onClick={() => {
                  if (result.bbox) onSelect(result.bbox, result.name);
                  setResults([]);
                }}
              >
                <strong>{result.name.split(',')[0]}</strong>
                <small>{result.name}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
