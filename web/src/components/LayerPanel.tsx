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
  basemap: 'remote' | 'local';
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

export default function LayerPanel(props: Props) {
  return (
    <div className="layer-panel">
      <div className="panel-head">
        <h2>Layers</h2>
        {props.canCreate && (
          <div className="layer-add-actions">
            <button className="btn btn-ghost btn-sm" onClick={props.onAddBlank}>
              <Icon name="plus" size={13} />
              Blank
            </button>
            <button className="btn btn-primary btn-sm" onClick={props.onAdd}>
              Data
            </button>
          </div>
        )}
      </div>
      <div className="layer-list">
        {props.layers.length === 0 && <p className="muted pad">No layers yet. Add one to begin.</p>}
        {props.layers.map((layer) => {
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
                    {layer.source_type}
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
                      {layer.geometry_type} · {layer.visibility} · {layer.source_type}
                    </span>
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
      {props.basemap === 'remote' && (
        <p className="map-policy">
          Remote OSM tiles are intended for light personal use. Use local tiles for shared or
          public deployments.
        </p>
      )}
    </div>
  );
}
