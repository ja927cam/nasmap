import { useState } from 'react';
import type { Layer } from '../api/types';
import Icon, { type IconName } from './Icon';
import { Badge } from './ui';

interface Props {
  layers: Layer[];
  activeLayerId: string | null;
  visible: Record<string, boolean>;
  opacity: Record<string, number>;
  onSelect: (layer: Layer) => void;
  onToggle: (id: string, visible: boolean) => void;
  onOpacity: (id: string, value: number) => void;
  onFit: (layer: Layer) => void;
  onStyle: (layer: Layer) => void;
  onShare: (layer: Layer) => void;
  onExport: (layer: Layer, format: 'geojson' | 'gpkg' | 'kml' | 'csv') => void;
  onDelete: (layer: Layer) => void;
  onAdd: () => void;
  onAddBlank: () => void;
  canCreate: boolean;
  onClose?: () => void;
  open?: boolean;
}

function geometryIcon(type: string): IconName {
  if (type === 'point') return 'point';
  if (type === 'line') return 'line';
  if (type === 'polygon') return 'polygon';
  if (type === 'raster') return 'image';
  if (type === 'table') return 'table';
  return 'layers';
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

function geometryLabel(value: string) {
  if (value === 'geometry') return 'Mixed';
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function LayerPanel(props: Props) {
  const [filter, setFilter] = useState('');
  const visibleLayers = filter.trim()
    ? props.layers.filter((layer) =>
        layer.name.toLowerCase().includes(filter.trim().toLowerCase()),
      )
    : props.layers;
  return (
    <div className={`layer-panel ${props.open ? 'open' : ''}`}>
      <div className="panel-head">
        <h2>Layers</h2>
        <div className="layer-add-actions">
          {props.canCreate && (
            <>
              <button
                className="btn btn-ghost btn-sm"
                onClick={props.onAddBlank}
                title="Create an empty layer to draw points, lines or polygons"
              >
                <Icon name="plus" size={13} />
                New
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={props.onAdd}
                title="Import a file, URL, folder, photos or OSM data"
              >
                Import
              </button>
            </>
          )}
          {props.onClose && (
            <button
              className="icon-btn layer-panel-close"
              onClick={props.onClose}
              aria-label="Close layer panel"
            >
              <Icon name="close" size={16} />
            </button>
          )}
        </div>
      </div>
      {props.layers.length > 0 && (
        <div className="layer-filter">
          <Icon name="search" size={13} />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Find a layer…"
            aria-label="Filter layers by name"
          />
        </div>
      )}
      <div className="layer-list">
        {props.layers.length === 0 && (
          <div className="layer-empty">
            <span className="layer-empty-icon">
              <Icon name="layers" size={22} />
            </span>
            <strong>No layers yet</strong>
            <p>
              {props.canCreate
                ? 'Import data you already have, or create an empty layer and draw on the map.'
                : 'Nothing has been shared with you yet. Ask an administrator for access.'}
            </p>
            {props.canCreate && (
              <div className="layer-empty-actions">
                <button className="btn btn-primary btn-sm" onClick={props.onAdd}>
                  <Icon name="upload" size={13} />
                  Import data
                </button>
                <button className="btn btn-ghost btn-sm" onClick={props.onAddBlank}>
                  <Icon name="plus" size={13} />
                  Draw a layer
                </button>
              </div>
            )}
          </div>
        )}
        {props.layers.length > 0 && visibleLayers.length === 0 && (
          <p className="muted pad">No layer matches “{filter}”.</p>
        )}
        {visibleLayers.map((layer) => {
          const isVisible = props.visible[layer.id] !== false;
          const isActive = props.activeLayerId === layer.id;
          const isRaster = layer.geometry_type === 'raster';
          return (
            <div key={layer.id} className={`layer-item ${isActive ? 'active' : ''}`}>
              <div className="layer-top" onClick={() => props.onSelect(layer)}>
                <input
                  type="checkbox"
                  checked={isVisible}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => props.onToggle(layer.id, e.target.checked)}
                  aria-label={`Toggle ${layer.name}`}
                />
                <span className={`layer-glyph ${layer.geometry_type}`}>
                  <Icon name={geometryIcon(layer.geometry_type)} size={15} />
                </span>
                <div className="grow">
                  <strong>{layer.name}</strong>
                  <small>
                    {layer.feature_count.toLocaleString()} {isRaster ? 'raster' : 'features'} ·{' '}
                    {sourceLabel(layer.source_type)}
                  </small>
                </div>
                {layer.visibility !== 'private' && (
                  <Badge tone={layer.visibility === 'public' ? 'success' : 'info'}>
                    {visibilityLabel(layer.visibility)}
                  </Badge>
                )}
              </div>
              {isActive && (
                <div className="layer-controls">
                  <label className="slider-row">
                    <span>Opacity</span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={props.opacity[layer.id] ?? 1}
                      onChange={(e) => props.onOpacity(layer.id, Number(e.target.value))}
                    />
                    <small>{Math.round((props.opacity[layer.id] ?? 1) * 100)}%</small>
                  </label>
                  <div className="layer-detail">
                    <span>
                      {geometryLabel(layer.geometry_type)} · {visibilityLabel(layer.visibility)} ·{' '}
                      {sourceLabel(layer.source_type)}
                    </span>
                    {layer.metadata?.provider && (
                      <span>
                        Provider: {String(layer.metadata.provider)}
                        {layer.metadata?.category ? ` · ${String(layer.metadata.category)}` : ''}
                      </span>
                    )}
                    {layer.licence && <span>Licence: {layer.licence}</span>}
                    {layer.attribution && <span>{layer.attribution}</span>}
                    {layer.metadata?.tessera && (
                      <span>
                        Tessera {layer.metadata.tessera.year} ·{' '}
                        {layer.metadata.tessera.variant} · {layer.metadata.tessera.resolution} m ·{' '}
                        {layer.metadata.tessera.source_band_count ?? 128} channels
                      </span>
                    )}
                  </div>
                  <div className="layer-actions">
                    <button className="btn btn-ghost btn-xs" onClick={() => props.onFit(layer)}>
                      Zoom to
                    </button>
                    <button className="btn btn-ghost btn-xs" onClick={() => props.onStyle(layer)}>
                      Style
                    </button>
                    {layer.access_role === 'owner' && (
                      <button className="btn btn-ghost btn-xs" onClick={() => props.onShare(layer)}>
                        Share
                      </button>
                    )}
                    {!isRaster && (
                      <select
                        className="btn btn-ghost btn-xs"
                        defaultValue=""
                        onChange={(e) => {
                          const value = e.target.value as 'geojson' | 'gpkg' | 'kml' | 'csv';
                          if (value) props.onExport(layer, value);
                          e.target.value = '';
                        }}
                      >
                        <option value="" disabled>
                          Export…
                        </option>
                        <option value="geojson">GeoJSON</option>
                        <option value="gpkg">GeoPackage</option>
                        <option value="kml">KML</option>
                        <option value="csv">CSV</option>
                      </select>
                    )}
                    {layer.access_role === 'owner' && (
                      <button className="btn btn-ghost btn-xs danger" onClick={() => props.onDelete(layer)}>
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
