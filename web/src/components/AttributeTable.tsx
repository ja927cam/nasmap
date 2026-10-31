import { useMemo, useState } from 'react';
import type { GeoFeature } from '../api/types';
import Icon from './Icon';

export default function AttributeTable({
  features,
  onSelect,
  activeId,
}: {
  features: GeoFeature[];
  onSelect: (feature: GeoFeature) => void;
  activeId?: string | null;
}) {
  const columns = useMemo(() => {
    const keys = new Set<string>();
    for (const feature of features.slice(0, 200)) {
      Object.keys(feature.properties || {})
        .filter((key) => !key.startsWith('_nasmap'))
        .forEach((key) => keys.add(key));
    }
    return Array.from(keys).slice(0, 12);
  }, [features]);
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState('');
  const pageSize = 25;
  const filtered = useMemo(() => {
    const value = query.trim().toLowerCase();
    if (!value) return features;
    return features.filter((feature) => JSON.stringify(feature.properties || {}).toLowerCase().includes(value));
  }, [features, query]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = filtered.slice(page * pageSize, page * pageSize + pageSize);

  return (
    <div className="attribute-table">
      <div className="table-tools">
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
          placeholder="Filter rows…"
          aria-label="Filter table rows"
        />
      </div>
      {filtered.length === 0 ? (
        <div className="table-empty">
          {query
            ? `No features match “${query}”.`
            : 'No features here yet. Draw one on the map, or import data into this layer.'}
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {current.map((feature) => (
                <tr
                  key={feature.id}
                  className={activeId === feature.id ? 'selected' : ''}
                  onClick={() => onSelect(feature)}
                >
                  {columns.map((column) => (
                    <td key={column}>{formatValue(feature.properties?.[column])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-footer">
        <span className="muted">
          {filtered.length.toLocaleString()} of {features.length.toLocaleString()} feature
          {features.length === 1 ? '' : 's'}
          {columns.length === 0 ? ' · no attributes' : ''}
        </span>
        <div className="pager">
          <button
            className="btn btn-ghost btn-xs"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            aria-label="Previous page"
          >
            <Icon name="chevron-left" size={13} />
          </button>
          <span>
            {page + 1} / {totalPages}
          </span>
          <button
            className="btn btn-ghost btn-xs"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            aria-label="Next page"
          >
            <Icon name="chevron-right" size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

function formatValue(value: unknown) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
