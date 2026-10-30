import { useState } from 'react';
import { api } from '../api/client';
import type { Layer, LayerStyle } from '../api/types';
import { Modal } from './ui';

export default function LayerStyler({
  layer,
  onClose,
  onSaved,
}: {
  layer: Layer;
  onClose: () => void;
  onSaved: (layer: Layer) => void;
}) {
  const [style, setStyle] = useState<LayerStyle>({
    color: layer.style?.color || '#2563eb',
    fillColor: layer.style?.fillColor || '#2563eb',
    fillOpacity: layer.style?.fillOpacity ?? 0.25,
    lineWidth: layer.style?.lineWidth ?? 2.5,
    opacity: layer.style?.opacity ?? 1,
    circleRadius: layer.style?.circleRadius ?? 6,
    bands: layer.style?.bands || [1, 2, 3],
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isRaster = layer.geometry_type === 'raster';

  function update<K extends keyof LayerStyle>(key: K, value: LayerStyle[K]) {
    setStyle((prev) => ({ ...prev, [key]: value }));
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api<Layer>(`/layers/${layer.id}`, { method: 'PATCH', body: { style } });
      onSaved(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save style');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Style · ${layer.name}`} onClose={onClose}>
      <div className="stack">
        {isRaster ? (
          <>
            <p className="muted">
              Raster styling is applied server-side when tiles are rendered. Choose up to three
              bands for RGB display (Tessera embeddings have 128 channels).
            </p>
            <label className="field">
              <span>RGB bands</span>
              <div className="button-row">
                {[0, 1, 2].map((index) => (
                  <input
                    key={index}
                    type="number"
                    min={1}
                    max={128}
                    className="small-input"
                    value={style.bands?.[index] ?? index + 1}
                    onChange={(e) => {
                      const bands = [...(style.bands || [1, 2, 3])];
                      bands[index] = Number(e.target.value);
                      update('bands', bands);
                    }}
                  />
                ))}
              </div>
            </label>
          </>
        ) : (
          <>
            <div className="grid-2">
              <label className="field">
                <span>Line / point colour</span>
                <input type="color" value={style.color} onChange={(e) => update('color', e.target.value)} />
              </label>
              <label className="field">
                <span>Fill colour</span>
                <input
                  type="color"
                  value={style.fillColor}
                  onChange={(e) => update('fillColor', e.target.value)}
                />
              </label>
            </div>
            <label className="field">
              <span>Fill opacity · {(style.fillOpacity ?? 0.25).toFixed(2)}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={style.fillOpacity}
                onChange={(e) => update('fillOpacity', Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span>Line width · {style.lineWidth}</span>
              <input
                type="range"
                min={0.5}
                max={12}
                step={0.5}
                value={style.lineWidth}
                onChange={(e) => update('lineWidth', Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span>Point radius · {style.circleRadius}</span>
              <input
                type="range"
                min={2}
                max={24}
                step={1}
                value={style.circleRadius}
                onChange={(e) => update('circleRadius', Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span>Layer opacity · {(style.opacity ?? 1).toFixed(2)}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={style.opacity}
                onChange={(e) => update('opacity', Number(e.target.value))}
              />
            </label>
          </>
        )}
        {error && <div className="error-box">{error}</div>}
        <div className="button-row end">
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save style'}
          </button>
        </div>
      </div>
    </Modal>
  );
}
