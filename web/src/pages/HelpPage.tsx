export default function HelpPage() {
  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <h1>Help</h1>
          <p className="page-subtitle">The short version first, then the details.</p>
        </div>
      </header>

      <section className="panel">
        <h2>Basic workflow</h2>
        <ol className="help-steps">
          <li>
            <strong>Create a layer.</strong> Use <em>Blank layer</em> for your own data, or
            <em> Add data</em> to import a file, URL, folder, photos or OSM.
          </li>
          <li>
            <strong>Put it on the map.</strong> Choose the layer in the layer panel. Use the
            toolbar to select, draw, edit vertices, measure, search or filter.
          </li>
          <li>
            <strong>Inspect and refine.</strong> Click a feature to open its properties and
            photos. Use the attribute table for bulk browsing. Style controls live in the layer
            panel.
          </li>
        </ol>
      </section>

      <section className="panel">
        <h2>What each thing means</h2>
        <dl className="help-kv">
          <dt>Layer</dt>
          <dd>A table of editable features (points, lines, polygons or mixed geometry), or a raster layer.</dd>
          <dt>Overlay</dt>
          <dd>A raster service layered on top: XYZ/TMS, TileJSON, WMS, GeoTIFF/COG, weather radar or Tessera.</dd>
          <dt>Import job</dt>
          <dd>Background work for files, URLs, folders and OSM. Progress and errors appear in the job dialog.</dd>
          <dt>Photo layer</dt>
          <dd>Point features created from EXIF GPS, with the original image attached.</dd>
          <dt>Editable OSM</dt>
          <dd>A local copy of OSM data. You can edit it here; it is not written back to OpenStreetMap automatically.</dd>
          <dt>Public / internal / private</dt>
          <dd>Who can read a layer after signing in. Public and internal are read-only for non-owners unless granted editor access.</dd>
        </dl>
      </section>

      <section className="panel">
        <h2>Ways to add data</h2>
        <div className="table-scroll">
          <table className="help-table">
            <thead>
              <tr>
                <th>Data</th>
                <th>Where</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              <tr><td>GeoJSON, GPKG, Shapefile ZIP, KML/KMZ, GPX, CSV</td><td>Map → Add data → Upload</td><td>Reprojected to WGS84; invalid geometry reported.</td></tr>
              <tr><td>GeoTIFF / COG</td><td>Add data or Overlays</td><td>Converted to COG and served as tiles.</td></tr>
              <tr><td>WMS, WFS, ArcGIS, STAC</td><td>Add data → From URL</td><td>Remote services; WMS/WFS proxied by Strata.</td></tr>
              <tr><td>XYZ, TileJSON, WMS</td><td>Overlays</td><td>Live raster overlays without copying pixels.</td></tr>
              <tr><td>OSM area</td><td>Map → OSM data</td><td>Editable local copy, selected with a map rectangle.</td></tr>
              <tr><td>Geotagged photos</td><td>Add data → Photos</td><td>JPEG/TIFF/PNG/WebP/RAF; EXIF GPS required for automatic placement.</td></tr>
              <tr><td>NAS folder</td><td>Add data → Server / NAS</td><td>Bulk photos or geodata from a read-only mounted folder.</td></tr>
              <tr><td>Weather radar</td><td>Live</td><td>Live RainViewer precipitation overlay.</td></tr>
              <tr><td>Weather points / earthquakes</td><td>Live</td><td>Open-Meteo and USGS snapshots with refresh.</td></tr>
              <tr><td>Tessera embeddings</td><td>Overlays → Tessera</td><td>Background download; exports GeoTIFFs.</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>Map controls</h2>
        <ul className="help-list">
          <li><strong>Select</strong> — click features, drag vertices on the selected feature.</li>
          <li><strong>Point / Line / Polygon</strong> — draw into the active editable layer. Pan by dragging. Finish with the button, <kbd>Enter</kbd>, or by clicking the first polygon vertex.</li>
          <li><strong>Distance / Area</strong> — click points; the live result stays after finishing.</li>
          <li><strong>Backspace</strong> — remove the last vertex. <strong>Esc</strong> — cancel drawing.</li>
          <li><strong>Filter to view</strong> — only load features intersecting the current viewport.</li>
          <li><strong>Find a place</strong> — toolbar search flies to a place; the crosshair/geolocate control uses your browser location.</li>
          <li><strong>Layer filter</strong> — the box above the layer list narrows long layer lists by name.</li>
          <li><strong>Feature properties</strong> — edit the Fields view for normal tags; use JSON only for nested values. The table has its own row filter.</li>
        </ul>
      </section>

      <section className="panel">
        <h2>Common problems</h2>
        <dl className="help-kv">
          <dt>A photo was skipped</dt>
          <dd>It has no EXIF GPS. Create/select a point and use <em>Add photo</em> instead, or import a GPX track later.</dd>
          <dt>Clicking a point does nothing</dt>
          <dd>Make sure the <em>Select</em> tool is active, not a draw or measure tool, and that the layer is visible.</dd>
          <dt>An import is too large</dt>
          <dd>Use a smaller area, upload in batches, or raise the relevant limit in <code>.env</code>.</dd>
          <dt>OSM area import rejected</dt>
          <dd>The rectangle is larger than <code>OVERPASS_MAX_AREA_DEG2</code>. Zoom in or raise the limit.</dd>
          <dt>Overlay is blank</dt>
          <dd>Check the provider URL, permissions, attribution and the API logs. Private/LAN URLs require <code>ALLOW_PRIVATE_URL_IMPORTS=true</code>.</dd>
        </dl>
      </section>

      <section className="panel">
        <h2>Documentation</h2>
        <p className="muted">
          Detailed guides are in the repository: <code>docs/setup.md</code>,{' '}
          <code>docs/data-import.md</code>, <code>docs/overlays.md</code>,{' '}
          <code>docs/osm.md</code> and <code>docs/tessera.md</code>.
        </p>
      </section>
    </div>
  );
}
