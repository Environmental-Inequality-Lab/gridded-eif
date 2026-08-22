/* Map of the queried place.
 *
 * The question this answers is "where is this place, and what does it cover?"
 * — not "how does the country vary?" So the selected unit is the subject: the
 * map frames its extent and outlines it, with neighbouring units shaded behind
 * for context and a coarser boundary underneath for orientation. With nothing
 * selected it falls back to a national choropleth.
 *
 * Geometry and values stay strictly separate. Boundary GeoJSON carries
 * `geo_id` and nothing else; query results are joined to features at render
 * time via feature-state. A new year of data needs no new geometry, and one
 * boundary file serves every measure, year, and filter.
 *
 * MapLibre is loaded lazily — it is the heaviest dependency on the site and
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
const geojsonCache = new Map();

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

/* Fetched here rather than handed to MapLibre as a URL, so the parsed features
 * are available for bounding-box lookups. The browser serves the second
 * consumer from cache, so this costs one request either way. */
function loadGeojson(url) {
  if (!geojsonCache.has(url)) {
    geojsonCache.set(
      url,
      fetch(url).then((r) => {
        if (!r.ok) throw new Error(`Could not load boundaries (HTTP ${r.status}).`);
        return r.json();
      })
    );
  }
  return geojsonCache.get(url);
}

function bboxOf(geometry) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const walk = (coords) => {
    if (typeof coords[0] === 'number') {
      if (coords[0] < minX) minX = coords[0];
      if (coords[0] > maxX) maxX = coords[0];
      if (coords[1] < minY) minY = coords[1];
      if (coords[1] > maxY) maxY = coords[1];
      return;
    }
    for (const c of coords) walk(c);
  };
  walk(geometry.coordinates);
  return [minX, minY, maxX, maxY];
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
  const step = ['step', ['feature-state', 'v'], RAMP[0]];
  breaks.forEach((b, i) => step.push(b, RAMP[Math.min(i + 1, RAMP.length - 1)]));
  return ['case', ['==', ['feature-state', 'v'], null], NO_DATA, step];
}

export function MapView({
  rows,
  geography,
  boundariesUrl,
  referenceUrl,
  names,
  valueLabel,
  selected,
  onPick,
  mode = 'count',
  onModeChange,
  shareAvailable = false,
}) {
  const isShare = mode === 'share' && shareAvailable;
  const fmtValue = (v) => (isShare ? `${v.toFixed(1)}%` : count(v));
  const holder = useRef(null);
  const map = useRef(null);
  const loadedFor = useRef(null);
  const bboxes = useRef(new Map());
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState(null);
  const [hover, setHover] = useState(null);
  const [breaks, setBreaks] = useState([]);
  const [geomReady, setGeomReady] = useState(0);

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
          maxZoom: 12,
          attributionControl: false,
        });
        m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
        // Held immediately, not inside the load handler. If the component
        // unmounts before `load` fires, a handle set only in that handler is
        // still null at cleanup, so the map is never removed — it leaks, keeps
        // its canvas in the DOM, and the next mount can sit on "Loading map"
        // forever. Every other effect gates on `ready`, so an unloaded handle
        // here is harmless.
        map.current = m;

        const onLoad = () => {
          if (dead) return;
          setReady(true);
          // MapLibre measures its container once at construction. The map lives
          // in a tab panel, so at that moment the container has not always
          // reached its final height, leaving the canvas short and clipped.
          m.resize();
        };
        // The style is inline and has no external resources, so MapLibre can
        // finish loading during construction — before a listener attached on
        // the next line exists. Waiting on 'load' alone means missing it
        // permanently and sitting on the loading overlay forever.
        if (m.loaded()) onLoad();
        else m.on('load', onLoad);
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
    if (!ready || !m || !boundariesUrl) return undefined;
    if (loadedFor.current === geography) return undefined;
    loadedFor.current = geography;
    let dead = false;

    for (const id of ['fill', 'line', 'sel', 'ref']) {
      if (m.getLayer(id)) m.removeLayer(id);
    }
    for (const id of ['geo', 'reference']) {
      if (m.getSource(id)) m.removeSource(id);
    }
    setErr(null);

    Promise.all([
      loadGeojson(boundariesUrl),
      referenceUrl ? loadGeojson(referenceUrl).catch(() => null) : Promise.resolve(null),
    ])
      .then(([data, reference]) => {
        if (dead || !map.current) return;

        bboxes.current = new Map();
        for (const f of data.features) {
          if (f.geometry) bboxes.current.set(String(f.properties.geo_id), bboxOf(f.geometry));
        }

        // Orientation layer, added first so it sits beneath everything. Only
        // meaningful when the queried units are smaller than a state.
        if (reference) {
          m.addSource('reference', { type: 'geojson', data: reference });
          m.addLayer({
            id: 'ref',
            type: 'line',
            source: 'reference',
            paint: { 'line-color': '#98a0ab', 'line-width': 0.8, 'line-opacity': 0.6 },
          });
        }

        m.addSource('geo', { type: 'geojson', data, promoteId: 'geo_id' });
        m.addLayer({
          id: 'fill',
          type: 'fill',
          source: 'geo',
          paint: { 'fill-color': NO_DATA, 'fill-opacity': 0.9 },
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
          paint: { 'line-color': '#111111', 'line-width': 2.4 },
          filter: ['==', ['get', 'geo_id'], '__none__'],
        });

        m.on('mousemove', 'fill', (e) => {
          const f = e.features && e.features[0];
          if (!f) return;
          m.getCanvas().style.cursor = 'pointer';
          setHover({
            id: String(f.id),
            v: f.state && f.state.v != null ? f.state.v : null,
            x: e.point.x,
            y: e.point.y,
          });
        });
        m.on('mouseleave', 'fill', () => {
          m.getCanvas().style.cursor = '';
          setHover(null);
        });
        m.on('click', 'fill', (e) => {
          const f = e.features && e.features[0];
          if (f && onPick) onPick(String(f.id));
        });

        setGeomReady((n) => n + 1);
      })
      .catch((e) => {
        if (!dead) setErr(e.message);
      });

    return () => {
      dead = true;
    };
  }, [ready, geography, boundariesUrl, referenceUrl]);

  // Push values in as feature-state and recolour.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !m.getSource('geo')) return undefined;

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
  }, [ready, rows, geography, geomReady]);

  /* Frame the selected place. This is the point of the map: a county FIPS or a
   * CBSA code tells you nothing about where somewhere is or how far it reaches. */
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !m.getLayer('sel')) return;
    m.setFilter('sel', ['==', ['get', 'geo_id'], selected || '__none__']);

    const home = () => m.easeTo({ center: [-98.5, 39.5], zoom: 3.05, duration: 600 });
    if (!selected) {
      home();
      return;
    }
    const bb = bboxes.current.get(String(selected));
    if (!bb) return;
    // Alaska's Aleutian islands cross the antimeridian, producing a bbox that
    // spans the globe. Framing that would zoom out to the whole world, so fall
    // back to the national view rather than something actively misleading.
    if (bb[2] - bb[0] > 180) {
      home();
      return;
    }
    m.fitBounds(
      [[bb[0], bb[1]], [bb[2], bb[3]]],
      { padding: 56, duration: 800, maxZoom: 10 }
    );
  }, [ready, selected, geography, geomReady]);

  const hoverName = hover ? (names && names[hover.id]) || hover.id : null;

  return html`
    <div class="map-wrap">
      <div ref=${holder} class="map"></div>

      <div class="map-mode">
        <div class="map-mode-row">
          <button class=${'chip' + (!isShare ? ' on' : '')}
                  onClick=${() => onModeChange && onModeChange('count')}>Count</button>
          <button
            class=${'chip' + (isShare ? ' on' : '') + (shareAvailable ? '' : ' is-disabled')}
            aria-disabled=${!shareAvailable}
            onClick=${() => shareAvailable && onModeChange && onModeChange('share')}>Share</button>
        </div>
        ${!shareAvailable &&
        html`<div class="map-mode-hint">
          Add a race, age, sex, or income filter. With none, every unit is 100% of itself.
        </div>`}
      </div>

      ${err && html`<div class="map-overlay"><${Notice} kind="warn">${err}<//></div>`}
      ${!err && !ready && html`<div class="map-overlay"><${Spinner} label="Loading map" /></div>`}

      ${hover &&
      html`<div class="map-tip" style=${`left:${hover.x + 14}px; top:${hover.y + 14}px`}>
        <strong>${hoverName}</strong>
        <span>${hover.v == null ? 'No data' : fmtValue(hover.v)}</span>
      </div>`}

      ${breaks.length > 0 &&
      html`<div class="map-legend">
        <div class="map-legend-label">${valueLabel}</div>
        <div class="map-legend-bar">${RAMP.map((c) => html`<span style=${`background:${c}`}></span>`)}</div>
        <div class="map-legend-ends">
          <span>${isShare ? breaks[0].toFixed(1) + '%' : compact(breaks[0])}</span>
          <span>${isShare
            ? breaks[breaks.length - 1].toFixed(1) + '%'
            : compact(breaks[breaks.length - 1])}</span>
        </div>
        <div class="map-legend-note">
          ${isShare ? 'Share of each unit\u2019s total population. ' : ''}${
            selected ? 'Outlined area is the current selection.' : 'Click any area to select it.'}
        </div>
      </div>`}
    </div>`;
}
