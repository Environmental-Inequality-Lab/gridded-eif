/* Choropleth map.
 *
 * Geometry and values are kept strictly separate. Boundary GeoJSON carries
 * `geo_id` and nothing else; query results are joined to features at render
 * time via MapLibre feature-state. So a new year of data needs no new
 * geometry, and one boundary file serves every measure, year, and filter.
 *
 * MapLibre is loaded lazily. It is the heaviest dependency on the site and
 * most visits never open the map.
 */
import { html, useEffect, useRef, useState } from '../h.js';
import { Spinner, Notice } from './Chrome.js';
import { count, compact } from '../format.js';

const MAPLIBRE_JS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js';
const MAPLIBRE_CSS = 'https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css';

/* Sequential ramp, light to brand maroon. It varies monotonically in
 * lightness, so it survives greyscale printing and every common form of colour
 * vision deficiency: hue is never the sole carrier of meaning. */
const RAMP = ['#f6f0f0', '#e4cdcd', '#d0a2a2', '#b97575', '#9f4a4a', '#7e282a', '#601215'];
const NO_DATA = '#eceef1';

let maplibrePromise = null;

function loadMaplibre() {
  if (maplibrePromise) return maplibrePromise;
  maplibrePromise = new Promise((resolve, reject) => {
    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = MAPLIBRE_CSS;
    document.head.appendChild(css);
    const s = document.createElement('script');
    s.src = MAPLIBRE_JS;
    s.onload = () => resolve(window.maplibregl);
    s.onerror = () => reject(new Error('Could not load the map library.'));
    document.head.appendChild(s);
  });
  return maplibrePromise;
}

/* Quantile breaks. Population is heavily skewed, a few very large units and
 * many small ones, so equal-interval breaks would paint nearly everything the
 * lightest shade and show nothing. */
function quantileBreaks(values, n) {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (v.length < n) return [...new Set(v)];
  const out = [];
  for (let i = 1; i < n; i++) out.push(v[Math.floor((i / n) * v.length)]);
  return [...new Set(out)];
}

function colorExpression(breaks) {
  // Reads feature-state, so recolouring never touches the geometry source.
  const step = ['step', ['feature-state', 'v'], RAMP[0]];
  breaks.forEach((b, i) => step.push(b, RAMP[Math.min(i + 1, RAMP.length - 1)]));
  return ['case', ['==', ['feature-state', 'v'], null], NO_DATA, step];
}

export function MapView({ rows, geography, boundariesUrl, names, valueLabel, selected, onPick }) {
  const holder = useRef(null);
  const map = useRef(null);
  const loadedFor = useRef(null);
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState(null);
  const [hover, setHover] = useState(null);
  const [breaks, setBreaks] = useState([]);

  // Create the map once.
  useEffect(() => {
    let dead = false;
    let ro = null;
    loadMaplibre()
      .then((maplibregl) => {
        if (dead || !holder.current) return;
        const m = new maplibregl.Map({
          container: holder.current,
          style: {
            version: 8,
            sources: {},
            layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#fcfcfd' } }],
          },
          center: [-98.5, 39.5],
          zoom: 3.05,
          maxZoom: 11,
          attributionControl: false,
        });
        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
        m.on('load', () => {
          if (dead) return;
          map.current = m;
          setReady(true);
          // MapLibre measures its container once at construction. The map is
          // inside a tab panel, so at that moment the container has not always
          // reached its final height, leaving the canvas short and the map
          // clipped until something else forces a redraw.
          m.resize();
        });
        if (typeof ResizeObserver !== 'undefined') {
          ro = new ResizeObserver(() => m.resize());
          ro.observe(holder.current);
        }
      })
      .catch((e) => {
        if (!dead) setErr(e.message);
      });
    return () => {
      dead = true;
      if (ro) ro.disconnect();
      if (map.current) map.current.remove();
      map.current = null;
    };
  }, []);

  // Swap geometry when the geography changes.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !boundariesUrl) return;
    if (loadedFor.current === geography) return;
    loadedFor.current = geography;

    for (const id of ['fill', 'line', 'sel']) {
      if (m.getLayer(id)) m.removeLayer(id);
    }
    if (m.getSource('geo')) m.removeSource('geo');

    m.addSource('geo', {
      type: 'geojson',
      data: boundariesUrl,
      // Lets feature-state be keyed by geo_id rather than an array index.
      promoteId: 'geo_id',
    });
    m.addLayer({
      id: 'fill',
      type: 'fill',
      source: 'geo',
      paint: { 'fill-color': NO_DATA, 'fill-opacity': 0.92 },
    });
    m.addLayer({
      id: 'line',
      type: 'line',
      source: 'geo',
      paint: { 'line-color': '#ffffff', 'line-width': 0.4, 'line-opacity': 0.7 },
    });
    m.addLayer({
      id: 'sel',
      type: 'line',
      source: 'geo',
      paint: { 'line-color': '#111111', 'line-width': 2 },
      filter: ['==', ['get', 'geo_id'], '__none__'],
    });

    m.on('mousemove', 'fill', (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      m.getCanvas().style.cursor = 'pointer';
      setHover({ id: String(f.id), v: f.state && f.state.v != null ? f.state.v : null, x: e.point.x, y: e.point.y });
    });
    m.on('mouseleave', 'fill', () => {
      m.getCanvas().style.cursor = '';
      setHover(null);
    });
    m.on('click', 'fill', (e) => {
      const f = e.features && e.features[0];
      if (f && onPick) onPick(String(f.id));
    });
  }, [ready, geography, boundariesUrl]);

  // Push values in as feature-state and recolour.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !m.getSource('geo')) return;

    const apply = () => {
      m.removeFeatureState({ source: 'geo' });
      const vals = [];
      for (const r of rows) {
        const v = Number(r.value);
        if (!Number.isFinite(v)) continue;
        vals.push(v);
        m.setFeatureState({ source: 'geo', id: String(r.geo_id) }, { v });
      }
      const b = quantileBreaks(vals, RAMP.length);
      setBreaks(b);
      if (m.getLayer('fill')) m.setPaintProperty('fill', 'fill-color', colorExpression(b));
    };

    // A GeoJSON source cannot accept feature-state until it has parsed.
    if (m.isSourceLoaded('geo')) {
      apply();
      return undefined;
    }
    const onData = (e) => {
      if (e.sourceId === 'geo' && m.isSourceLoaded('geo')) {
        m.off('sourcedata', onData);
        apply();
      }
    };
    m.on('sourcedata', onData);
    return () => m.off('sourcedata', onData);
  }, [ready, rows, geography]);

  // Outline the selected unit.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !m.getLayer('sel')) return;
    m.setFilter('sel', ['==', ['get', 'geo_id'], selected || '__none__']);
  }, [ready, selected, geography]);

  const hoverName = hover ? (names && names[hover.id]) || hover.id : null;

  return html`
    <div class="map-wrap">
      <div ref=${holder} class="map"></div>

      ${err && html`<div class="map-overlay"><${Notice} kind="warn">${err}<//></div>`}
      ${!err && !ready && html`<div class="map-overlay"><${Spinner} label="Loading map" /></div>`}

      ${hover &&
      html`<div class="map-tip" style=${`left:${hover.x + 14}px; top:${hover.y + 14}px`}>
        <strong>${hoverName}</strong>
        <span>${hover.v == null ? 'No data' : count(hover.v)}</span>
      </div>`}

      ${breaks.length > 0 &&
      html`<div class="map-legend">
        <div class="map-legend-label">${valueLabel}</div>
        <div class="map-legend-bar">${RAMP.map((c) => html`<span style=${`background:${c}`}></span>`)}</div>
        <div class="map-legend-ends">
          <span>${compact(breaks[0])}</span>
          <span>${compact(breaks[breaks.length - 1])}</span>
        </div>
        <div class="map-legend-note">Quantile breaks. Click a unit to select it.</div>
      </div>`}
    </div>`;
}
