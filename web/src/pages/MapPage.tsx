import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, download } from '../api/client';
import { usePublicConfig } from '../api/config';
import { useAuth } from '../api/auth';
import type { FeatureCollection, GeoFeature, ImportJob, Layer, Paged } from '../api/types';
import AttributeTable from '../components/AttributeTable';
import BlankLayerDialog from '../components/BlankLayerDialog';
import FeaturePanel from '../components/FeaturePanel';
import ImportWizard from '../components/ImportWizard';
import JobProgress from '../components/JobProgress';
import LayerPanel from '../components/LayerPanel';
import LayerSharing from '../components/LayerSharing';
import LayerStyler from '../components/LayerStyler';
import Icon from '../components/Icon';
import MapPlaceSearch from '../components/MapPlaceSearch';
import MapView, { type MapTool } from '../components/MapView';
import OsmDataDialog from '../components/OsmDataDialog';
import OsmPublishDialog from '../components/OsmPublishDialog';
import { Spinner } from '../components/ui';
import type { Map as MapLibreMap } from 'maplibre-gl';

type Tool = MapTool;

export default function MapPage() {
  const config = usePublicConfig();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [layers, setLayers] = useState<Layer[]>([]);
  const [layerData, setLayerData] = useState<Record<string, FeatureCollection>>({});
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [opacity, setOpacity] = useState<Record<string, number>>({});
  const [activeLayerId, setActiveLayerId] = useState<string | null>(params.get('layer'));
  const [selectedFeature, setSelectedFeature] = useState<GeoFeature | null>(null);
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null);
  const [tool, setTool] = useState<Tool>('pan');
  const [basemap, setBasemap] = useState<'remote' | 'local'>('remote');
  const [measure, setMeasure] = useState<{ kind: string; value: number; label: string } | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [bboxFilter, setBboxFilter] = useState<string | null>(null);
  const [wizard, setWizard] = useState<
    null | 'upload' | 'url' | 'photos' | 'ingest' | 'manual' | 'tessera'
  >(null);
  const [blankOpen, setBlankOpen] = useState(false);
  const [osmOpen, setOsmOpen] = useState(false);
  const [osmBBox, setOsmBBox] = useState<[number, number, number, number]>([-180, -85, 180, 85]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [styleLayer, setStyleLayer] = useState<Layer | null>(null);
  const [shareLayer, setShareLayer] = useState<Layer | null>(null);
  const [osmFeature, setOsmFeature] = useState<GeoFeature | null>(null);
  const [showTable, setShowTable] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mapRef = useRef<MapLibreMap | null>(null);
  const loadedRef = useRef<Record<string, string>>({});

  const flash = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 4000);
  }, []);

  const loadLayers = useCallback(
    async (selectId?: string | null) => {
      try {
        const data = await api<Paged<Layer>>('/layers?limit=500&sort=updated');
        setLayers(data.items);
        setVisible((prev) => {
          const next = { ...prev };
          for (const layer of data.items) if (next[layer.id] === undefined) next[layer.id] = true;
          return next;
        });
        setOpacity((prev) => {
          const next = { ...prev };
          for (const layer of data.items) if (next[layer.id] === undefined) next[layer.id] = 1;
          return next;
        });
        const target = selectId ?? params.get('layer');
        if (target && data.items.some((layer) => layer.id === target)) setActiveLayerId(target);
        else if (!activeLayerId && data.items.length) setActiveLayerId(data.items[0].id);
      } catch (err) {
        flash(err instanceof Error ? err.message : 'Could not load layers');
      } finally {
        setLoading(false);
      }
    },
    [params, activeLayerId, flash],
  );

  useEffect(() => {
    if (!config) return;
    setBasemap(config.basemap_mode === 'local' ? 'local' : 'remote');
    void loadLayers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  useEffect(() => {
    if (params.get('new')) {
      const mode = params.get('new');
      if (
        mode === 'manual' ||
        mode === 'upload' ||
        mode === 'url' ||
        mode === 'photos' ||
        mode === 'ingest' ||
        mode === 'tessera'
      ) {
        setWizard(mode);
      }
      const next = new URLSearchParams(params);
      next.delete('new');
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!config) return;
    const controller = new AbortController();
    const vectorLayers = layers.filter(
      (layer) => !['raster', 'table'].includes(layer.geometry_type) && visible[layer.id] !== false,
    );
    const jobs = vectorLayers.map(async (layer) => {
      const params = new URLSearchParams({ limit: '2000' });
      if (bboxFilter) params.set('bbox', bboxFilter);
      if (searchQuery && layer.id === activeLayerId) params.set('q', searchQuery);
      const key = `${params.toString()}|${layer.updated_at}`;
      if (loadedRef.current[layer.id] === key) return;
      try {
        const data = await api<FeatureCollection>(`/layers/${layer.id}/features?${params}`, {
          signal: controller.signal,
        });
        loadedRef.current[layer.id] = key;
        setLayerData((prev) => ({ ...prev, [layer.id]: data }));
      } catch (err) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          console.warn('Could not load features', layer.id, err);
        }
      }
    });
    void Promise.all(jobs);
    return () => controller.abort();
  }, [layers, visible, bboxFilter, searchQuery, activeLayerId, config]);

  const activeLayer = useMemo(
    () => layers.find((layer) => layer.id === activeLayerId) ?? null,
    [layers, activeLayerId],
  );
  const canWriteGlobally = user?.role === 'admin' || user?.role === 'editor';
  const editable = Boolean(
    canWriteGlobally &&
      activeLayer &&
      !['raster', 'table'].includes(activeLayer.geometry_type) &&
      (activeLayer.access_role === 'owner' || activeLayer.access_role === 'editor'),
  );

  const refreshActiveFeatures = useCallback(
    async (layerId: string) => {
      try {
        const data = await api<FeatureCollection>(`/layers/${layerId}/features?limit=2000`);
        loadedRef.current[layerId] = '';
        setLayerData((prev) => ({ ...prev, [layerId]: data }));
      } catch (err) {
        flash(err instanceof Error ? err.message : 'Could not refresh features');
      }
    },
    [flash],
  );

  async function createFeature(layerId: string, geometry: any): Promise<boolean> {
    try {
      const feature = await api<GeoFeature>(`/layers/${layerId}/features`, {
        method: 'POST',
        body: { geometry, properties: {} },
      });
      await refreshActiveFeatures(layerId);
      setSelectedFeature(feature);
      setSelectedLayerId(layerId);
      flash('Feature created');
      return true;
    } catch (err) {
      flash(err instanceof Error ? err.message : 'Could not create feature');
      return false;
    }
  }

  async function updateGeometry(feature: GeoFeature, geometry: any) {
    try {
      const updated = await api<GeoFeature>(`/features/${feature.id}`, {
        method: 'PATCH',
        body: { geometry },
      });
      setSelectedFeature(updated);
      flash('Geometry updated');
      if (selectedLayerId) await refreshActiveFeatures(selectedLayerId);
    } catch (err) {
      flash(err instanceof Error ? err.message : 'Could not update geometry');
    }
  }

  async function saveProperties(properties: Record<string, any>) {
    if (!selectedFeature) return;
    const updated = await api<GeoFeature>(`/features/${selectedFeature.id}`, {
      method: 'PATCH',
      body: { properties, replace_properties: true },
    });
    setSelectedFeature(updated);
    flash('Properties saved');
    if (selectedLayerId) await refreshActiveFeatures(selectedLayerId);
  }

  async function deleteFeature() {
    if (!selectedFeature) return;
    if (!window.confirm('Delete this feature? History is retained in feature_versions.')) return;
    await api(`/features/${selectedFeature.id}`, { method: 'DELETE' });
    setSelectedFeature(null);
    flash('Feature deleted');
    if (selectedLayerId) await refreshActiveFeatures(selectedLayerId);
  }

  async function fitLayer(layer: Layer) {
    const map = mapRef.current;
    if (!map) return;
    const rasterInfo = layer.metadata?.raster;
    const bounds = rasterInfo?.bounds_wgs84 || layer.metadata?.bounds;
    if (Array.isArray(bounds) && bounds.length === 4) {
      map.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: 60, maxZoom: 16 });
      return;
    }
    try {
      const stats = await api<{ extent: string | null }>(`/layers/${layer.id}/stats`);
      const match = stats.extent?.match(/BOX\(([-\d.]+) ([-\d.]+),([-\d.]+) ([-\d.]+)\)/);
      if (match) {
        map.fitBounds(
          [
            [Number(match[1]), Number(match[2])],
            [Number(match[3]), Number(match[4])],
          ],
          { padding: 60, maxZoom: 16 },
        );
      } else {
        flash('Layer has no geometry yet');
      }
    } catch {
      flash('Could not read layer extent');
    }
  }

  function filterToView() {
    const map = mapRef.current;
    if (!map) return;
    const b = map.getBounds();
    setBboxFilter(`${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`);
  }

  async function deleteLayer(layer: Layer) {
    if (!window.confirm(`Soft-delete layer "${layer.name}"? The data remains in the database.`)) return;
    try {
      await api(`/layers/${layer.id}`, { method: 'DELETE' });
      setLayerData((prev) => {
        const next = { ...prev };
        delete next[layer.id];
        return next;
      });
      if (activeLayerId === layer.id) setActiveLayerId(null);
      if (selectedLayerId === layer.id) {
        setSelectedFeature(null);
        setSelectedLayerId(null);
      }
      await loadLayers(null);
      flash('Layer deleted');
    } catch (err) {
      flash(err instanceof Error ? err.message : 'Could not delete layer');
    }
  }

  function handleJobComplete(job: ImportJob) {
    void loadLayers(job.layer_id ?? undefined).then(() => {
      if (job.layer_id) {
        setActiveLayerId(job.layer_id);
        setVisible((prev) => ({ ...prev, [job.layer_id as string]: true }));
      }
    });
  }

  if (!config || loading) return <Spinner full />;

  const activeFeatures = activeLayerId ? layerData[activeLayerId]?.features ?? [] : [];

  return (
    <div className="map-page">
      <div className="map-toolbar">
        <div className="toolgroup">
          <button
            className={tool === 'pan' ? 'tool active' : 'tool'}
            onClick={() => setTool('pan')}
            title="Select and pan"
            aria-label="Select and pan"
          >
            <Icon name="cursor" size={15} />
            <span>Select</span>
          </button>
          <button
            className={tool === 'point' ? 'tool active' : 'tool'}
            onClick={() => {
              if (!editable) return flash('Select an editable vector layer first');
              setTool('point');
            }}
            title="Draw point"
            aria-label="Draw point"
          >
            <Icon name="point" size={15} />
            <span>Point</span>
          </button>
          <button
            className={tool === 'line' ? 'tool active' : 'tool'}
            onClick={() => {
              if (!editable) return flash('Select an editable vector layer first');
              setTool('line');
            }}
            title="Draw line"
            aria-label="Draw line"
          >
            <Icon name="line" size={15} />
            <span>Line</span>
          </button>
          <button
            className={tool === 'polygon' ? 'tool active' : 'tool'}
            onClick={() => {
              if (!editable) return flash('Select an editable vector layer first');
              setTool('polygon');
            }}
            title="Draw polygon"
            aria-label="Draw polygon"
          >
            <Icon name="polygon" size={15} />
            <span>Polygon</span>
          </button>
        </div>
        <div className="toolgroup">
          <button
            className={tool === 'measure-distance' ? 'tool active' : 'tool'}
            onClick={() => setTool(tool === 'measure-distance' ? 'pan' : 'measure-distance')}
            title="Measure distance"
            aria-label="Measure distance"
          >
            <Icon name="ruler" size={15} />
            <span>Distance</span>
          </button>
          <button
            className={tool === 'measure-area' ? 'tool active' : 'tool'}
            onClick={() => setTool(tool === 'measure-area' ? 'pan' : 'measure-area')}
            title="Measure area"
            aria-label="Measure area"
          >
            <Icon name="area" size={15} />
            <span>Area</span>
          </button>
        </div>
        <MapPlaceSearch
          onSelect={(box, lon, lat) => {
            const map = mapRef.current;
            if (!map) return;
            if (box) map.fitBounds([[box[0], box[1]], [box[2], box[3]]], { padding: 60, maxZoom: 15 });
            else map.flyTo({ center: [lon, lat], zoom: 13 });
          }}
        />
        <form
          className="map-search"
          onSubmit={(e) => {
            e.preventDefault();
            setSearchQuery(searchInput.trim());
          }}
        >
          <input
            placeholder="Search attributes…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <button className="tool" type="submit" title="Search" aria-label="Search">
            <Icon name="search" size={15} />
          </button>
          {searchQuery && (
            <button
              type="button"
              className="tool"
              onClick={() => {
                setSearchInput('');
                setSearchQuery('');
              }}
              title="Clear search"
              aria-label="Clear search"
            >
              <Icon name="close" size={14} />
            </button>
          )}
        </form>
        <button
          className={bboxFilter ? 'btn btn-secondary btn-sm' : 'btn btn-ghost btn-sm'}
          onClick={filterToView}
        >
          <Icon name="filter" size={14} />
          {bboxFilter ? 'Filtered to view' : 'Filter to view'}
        </button>
        {bboxFilter && (
          <button className="btn btn-ghost btn-sm" onClick={() => setBboxFilter(null)}>
            Clear
          </button>
        )}
        <div className="spacer" />
        <select
          className="select-sm"
          value={basemap}
          onChange={(e) => setBasemap(e.target.value as 'remote' | 'local')}
        >
          <option value="remote">OSM raster</option>
          <option value="local">Local vector tiles</option>
        </select>
        {canWriteGlobally && (
          <button className="btn btn-secondary btn-sm" onClick={() => setBlankOpen(true)}>
            <Icon name="plus" size={14} />
            Blank layer
          </button>
        )}
        {canWriteGlobally && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => {
              const bounds = mapRef.current?.getBounds();
              if (bounds) {
                setOsmBBox([
                  bounds.getWest(),
                  bounds.getSouth(),
                  bounds.getEast(),
                  bounds.getNorth(),
                ]);
              }
              setOsmOpen(true);
            }}
          >
            <Icon name="layers" size={14} />
            OSM data
          </button>
        )}
        {canWriteGlobally && (
          <button className="btn btn-primary btn-sm" onClick={() => setWizard('upload')}>
            <Icon name="upload" size={14} />
            Add data
          </button>
        )}
      </div>

      <div className="map-body">
        <LayerPanel
          layers={layers}
          activeLayerId={activeLayerId}
          visible={visible}
          opacity={opacity}
          onSelect={(layer) => {
            setActiveLayerId(layer.id);
            setParams({ layer: layer.id }, { replace: true });
            setSelectedFeature(null);
            setSelectedLayerId(null);
          }}
          onToggle={(id, value) => setVisible((prev) => ({ ...prev, [id]: value }))}
          onOpacity={(id, value) => setOpacity((prev) => ({ ...prev, [id]: value }))}
          onFit={fitLayer}
          onStyle={setStyleLayer}
          onShare={setShareLayer}
          onExport={(layer, format) =>
            download(`/layers/${layer.id}/export?format=${format}`, `${layer.name}.${format}`).catch((err) =>
              flash(err instanceof Error ? err.message : 'Export failed'),
            )
          }
          onDelete={deleteLayer}
          onAdd={() => setWizard('upload')}
          onAddBlank={() => setBlankOpen(true)}
          canCreate={canWriteGlobally}
          basemap={basemap}
        />

        <div className="map-stage">
          <MapView
            layers={layers}
            layerData={layerData}
            visible={visible}
            opacity={opacity}
            activeLayerId={activeLayerId}
            basemap={basemap}
            osmTileUrl={config.osm_tile_url}
            osmAttribution={config.osm_tile_attribution}
            tileserverUrl={config.tileserver_public_url}
            tool={tool}
            selectedFeature={selectedFeature}
            editable={editable}
            onSelectFeature={(layerId, feature) => {
              if (!feature) {
                setSelectedFeature(null);
                setSelectedLayerId(null);
                return;
              }
              setSelectedLayerId(layerId);
              setActiveLayerId(layerId);
              setSelectedFeature(feature);
            }}
            onCreateFeature={createFeature}
            onUpdateGeometry={updateGeometry}
            onMeasure={setMeasure}
            onMapReady={(map) => {
              mapRef.current = map;
            }}
            onToolComplete={() => setTool('pan')}
          />
          {measure && (
            <div className="measure-pill">
              {measure.kind === 'distance' ? 'Distance' : 'Area'}: <strong>{measure.label}</strong>
              <button className="icon-btn" onClick={() => setMeasure(null)} aria-label="Clear measurement">
                <Icon name="close" size={14} />
              </button>
            </div>
          )}
          {notice && <div className="toast">{notice}</div>}
          {selectedFeature && activeLayer && (
            <FeaturePanel
              feature={selectedFeature}
              layer={activeLayer}
              editable={editable}
              onClose={() => {
                setSelectedFeature(null);
                setSelectedLayerId(null);
              }}
              onSave={saveProperties}
              onDelete={deleteFeature}
              onOsm={() => setOsmFeature(selectedFeature)}
            />
          )}
          {activeLayer && !['raster', 'table'].includes(activeLayer.geometry_type) && showTable && (
            <div className="table-panel">
              <div className="table-head">
                <strong>{activeLayer.name}</strong>
                <button className="icon-btn" onClick={() => setShowTable(false)} aria-label="Close table">
                  <Icon name="close" size={15} />
                </button>
              </div>
              <AttributeTable
                features={activeFeatures}
                activeId={selectedFeature?.id}
                onSelect={(feature) => {
                  setSelectedFeature(feature);
                  setSelectedLayerId(activeLayer.id);
                }}
              />
            </div>
          )}
          {!showTable && activeLayer && (
            <button className="table-toggle" onClick={() => setShowTable(true)}>
              <Icon name="table" size={14} />
              Attribute table
            </button>
          )}
        </div>
      </div>

      {osmOpen && (
        <OsmDataDialog
          initialBBox={osmBBox}
          layers={layers}
          onClose={() => setOsmOpen(false)}
          onJob={(job) => setJobId(job.id)}
        />
      )}

      {blankOpen && (
        <BlankLayerDialog
          onClose={() => setBlankOpen(false)}
          onCreated={(layer) => {
            setLayers((prev) => [layer, ...prev]);
            setVisible((prev) => ({ ...prev, [layer.id]: true }));
            setOpacity((prev) => ({ ...prev, [layer.id]: 1 }));
            setActiveLayerId(layer.id);
            setParams({ layer: layer.id }, { replace: true });
            setBlankOpen(false);
            flash('Blank layer created');
          }}
        />
      )}

      {wizard && (
        <ImportWizard
          config={config}
          layers={layers}
          initialTab={wizard}
          onClose={() => setWizard(null)}
          onLayerCreated={(layer) => {
            setLayers((prev) => [layer, ...prev]);
            setVisible((prev) => ({ ...prev, [layer.id]: true }));
            setOpacity((prev) => ({ ...prev, [layer.id]: 1 }));
            setActiveLayerId(layer.id);
            setWizard(null);
            flash('Layer created');
          }}
          onJob={(job) => setJobId(job.id)}
          onPhotosImported={(layerId) => {
            if (layerId) {
              void loadLayers(layerId);
              setVisible((prev) => ({ ...prev, [layerId]: true }));
            }
          }}
        />
      )}
      {jobId && (
        <JobProgress
          jobId={jobId}
          onClose={() => setJobId(null)}
          onComplete={handleJobComplete}
        />
      )}
      {shareLayer && <LayerSharing layer={shareLayer} onClose={() => setShareLayer(null)} />}
      {styleLayer && (
        <LayerStyler
          layer={styleLayer}
          onClose={() => setStyleLayer(null)}
          onSaved={(updated) => {
            setLayers((prev) => prev.map((layer) => (layer.id === updated.id ? updated : layer)));
            setStyleLayer(null);
          }}
        />
      )}
      {osmFeature && activeLayer && (
        <OsmPublishDialog
          feature={osmFeature}
          layer={activeLayer}
          onClose={() => setOsmFeature(null)}
          onPublished={() => {
            if (selectedLayerId) void refreshActiveFeatures(selectedLayerId);
            void loadLayers(selectedLayerId);
          }}
        />
      )}
    </div>
  );
}
