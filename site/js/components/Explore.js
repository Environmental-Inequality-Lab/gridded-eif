import { html, useState, useEffect, useMemo } from '../h.js';
import { query, buildQuery, q } from '../duck.js';
import { CATALOG_URL } from '../config.js';
import { entryUrl, combinedUrl, yearsFor, isPreliminary, dimension, defaultMeasure } from '../catalog.js';
import { QueryPanel } from './QueryPanel.js';
import { ResultsTable, TimeSeries, exportCsv } from './Results.js';
import { MapView } from './MapView.js';
import { Notice, Spinner } from './Chrome.js';
import { count, toCsv, download } from '../format.js';

export function Explore({ cat, state, go, toggleFacet, places }) {
  const [rows, setRows] = useState([]);
  const [mapRows, setMapRows] = useState([]);
  const [series, setSeries] = useState([]);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState(null);
  const [seriesErr, setSeriesErr] = useState(null);
  const [ms, setMs] = useState(null);

  const ds = cat.datasets[state.d];
  const years = yearsFor(cat, state.d, state.g);
  const year = state.y ?? years[years.length - 1];
  const prelim = isPreliminary(cat, state.d, year);
  const preliminaryYears = ds?.preliminary_years || [];

  // Measure defaults by geography size rather than a fixed choice: the
  // published guidance is post-processed below ~600k population, raw above.
  const nationTotal = useMemo(() => {
    const e = cat.entries.find((x) => x.dataset === state.d && x.geography === 'nation' && x.year === year);
    return e?.totals?.n_noise;
  }, [cat, state.d, year]);
  const auto = state.m == null;
  const measure = state.m || defaultMeasure(cat, state.g === 'nation' ? nationTotal : 0);

  const placeNames = useMemo(() => {
    const out = {};
    for (const p of places) if (p.level === state.g) out[p.geo_id] = p.name;
    return out;
  }, [places, state.g]);

  /* code -> published label, per dimension. The table shows the label; the
   * query and the CSV keep the code, which is what the source files contain. */
  const valueLabels = useMemo(() => {
    const out = {};
    for (const dimId of ds?.dimensions || []) {
      const d = dimension(cat, dimId);
      if (!d) continue;
      out[dimId] = Object.fromEntries(d.values.map((v) => [v.code, v.label]));
    }
    out.geo_id = placeNames;
    return out;
  }, [cat, ds, placeNames]);

  const groupBy = state.p || state.g === 'nation' ? (ds?.dimensions || []) : ['geo_id'];
  const url = entryUrl(cat, state.d, state.g, year);
  const seriesUrl = combinedUrl(cat, state.d, state.g);

  useEffect(() => {
    let cancelled = false;
    if (!url) { setErr('No published data for this combination.'); setBusy(false); return; }
    setBusy(true); setErr(null);
    const t0 = performance.now();

    const filters = { ...state.facets };
    if (state.p) filters.geo_id = [state.p];

    const tableSql = buildQuery({ url, measure, groupBy, filters });

    const seriesSql = seriesUrl
      ? buildQuery({ url: seriesUrl, measure, groupBy: ['year'], filters }).replace(
          'ORDER BY value DESC', 'ORDER BY year')
      : null;

    // The map always shows every unit, so it drops the single-place filter
    // that the table applies. Only run it for levels that have geometry, and
    // never for nation, where a one-feature choropleth says nothing.
    const wantMap = state.tab === 'map' && cat.boundaries?.[state.g] && state.g !== 'nation';
    const mapFilters = { ...state.facets };
    const mapSql = wantMap
      ? buildQuery({ url, measure, groupBy: ['geo_id'], filters: mapFilters })
      : null;

    // allSettled, not all: the three views read different files, and one
    // being unavailable should not blank the other two. A missing all-years
    // file must not take the table and map down with it.
    Promise.allSettled([
      query(tableSql),
      seriesSql ? query(seriesSql) : Promise.resolve([]),
      mapSql ? query(mapSql) : Promise.resolve(null),
    ])
      .then(([t, s, mp]) => {
        if (cancelled) return;
        if (t.status === 'fulfilled') setRows(t.value);
        if (s.status === 'fulfilled') {
          setSeries(s.value.map((r) => ({ year: Number(r.year), value: r.value })));
          setSeriesErr(null);
        } else {
          setSeries([]);
          setSeriesErr(String(s.reason?.message || s.reason));
        }
        if (mp.status === 'fulfilled' && mp.value) setMapRows(mp.value);
        setMs(Math.round(performance.now() - t0));
        // Only the table failing is fatal — it is what every other view hangs off.
        setErr(t.status === 'rejected' ? String(t.reason?.message || t.reason) : null);
      })
      .finally(() => !cancelled && setBusy(false));

    return () => { cancelled = true; };
  }, [url, seriesUrl, measure, state.p, state.g, state.d, year, state.tab, JSON.stringify(state.facets)]);

  const placeName = useMemo(
    () => places?.find((p) => p.geo_id === state.p && p.level === state.g)?.name,
    [places, state.p, state.g]
  );

  const columns = useMemo(() => {
    const base = groupBy.includes('geo_id') ? ['name', ...groupBy.filter((c) => c !== 'geo_id')] : [...groupBy];
    return [...base, 'value'];
  }, [groupBy]);

  const nameFor = useMemo(() => {
    const m = new Map(
      (places || []).filter((p) => p.level === state.g).map((p) => [p.geo_id, p.name])
    );
    return (id) => m.get(id) || id;
  }, [places, state.g]);

  const display = useMemo(
    () => rows.map((r) => ({ ...r, name: r.geo_id ? nameFor(r.geo_id) : undefined })),
    [rows, nameFor]
  );

  const labels = useMemo(() => {
    const l = { value: cat.measures[measure].label + ' — people', name: 'Place', year: 'Year' };
    for (const d of ds?.dimensions || []) l[d] = dimension(cat, d)?.label || d;
    return l;
  }, [cat, measure, ds]);

  const title = [
    placeName || (state.g === 'nation' ? 'United States' : `All ${cat.geographies[state.g]?.label || state.g}`),
    year,
  ].join(' · ');

  return html`
    <div class="wrap section">
      <div class="spread" style="margin-bottom:18px">
        <div>
          <p class="eyebrow">${ds?.label}</p>
          <h1 style="margin:0">${title}</h1>
        </div>
        ${busy ? html`<${Spinner} label="Querying…" />`
               : ms != null && html`
                 <span class="small muted" title="Time to run the query and render the result">
                   Query time <span class="num">${ms} ms</span>
                 </span>`}
      </div>

      ${prelim && html`
        <div style="margin-bottom:14px">
          <${Notice} kind="warn">
            <strong>${year} is preliminary.</strong> This vintage is built from the most
            recent tax filings and will be revised. It is not comparable to the final
            years without care, and should not be cited as settled.
          <//>
        </div>`}

      ${err && html`<div style="margin-bottom:14px"><${Notice} kind="warn">${err}<//></div>`}

      <div class="workbench">
        <${QueryPanel} cat=${cat} state=${{ ...state, y: year }} go=${go}
                       toggleFacet=${toggleFacet} places=${places}
                       measure=${measure} measureAuto=${auto} />

        <div class="panel">
          <div class="tabs" style="padding:0 8px">
            <button class=${'tab' + (state.tab === 'table' ? ' on' : '')}
                    onClick=${() => go({ tab: 'table' })}>Table</button>
            <button class=${'tab' + (state.tab === 'series' ? ' on' : '')}
                    onClick=${() => go({ tab: 'series' })}>Time series</button>
            ${cat.boundaries?.[state.g] && state.g !== 'nation' && html`
              <button class=${'tab' + (state.tab === 'map' ? ' on' : '')}
                      onClick=${() => go({ tab: 'map' })}>Map</button>`}
            <button class=${'tab' + (state.tab === 'code' ? ' on' : '')}
                    onClick=${() => go({ tab: 'code' })}>Get the data</button>
          </div>

          ${state.tab === 'table' && html`
            <${ResultsTable}
              rows=${display} columns=${columns} labels=${labels}
              valueLabels=${valueLabels}
              note=${`${cat.measures[measure].label.toLowerCase()} estimates`}
              onExport=${() => exportCsv(display, columns,
                `gridded-eif_${state.d}_${state.g}_${year}.csv`, valueLabels)} />`}

          ${state.tab === 'series' && html`
            <div>
              ${series.length > 1 && html`
                <div style="padding:12px 16px 0">
                  <${Notice}>
                    Counts across years reflect changes in administrative-records
                    coverage as well as population. Read long trends with care.
                  <//>
                </div>`}
              ${seriesErr && html`
                <div style="padding:0 16px 12px">
                  <${Notice} kind="warn">
                    <strong>The year-by-year file could not be read.</strong> ${seriesErr}
                    ${' '}The table and map above are unaffected.
                  <//>
                </div>`}
              <${TimeSeries} series=${series} preliminaryYears=${preliminaryYears}
                label=${`${placeName || 'United States'} — ${cat.measures[measure].label.toLowerCase()}`} />
              <div style="padding:0 16px 16px">
                <button class="btn btn-outline btn-sm"
                  onClick=${() => download(`gridded-eif_${state.d}_${state.g}_series.csv`,
                                           toCsv(series, ['year', 'value']))}>
                  Download series CSV
                </button>
              </div>
            </div>`}

          ${state.tab === 'map' && !cat.boundaries?.[state.g] && html`
            <div style="padding:16px">
              <${Notice}>
                <strong>No map for ${cat.geographies[state.g]?.label || state.g}.</strong>
                ${' '}Boundary geometry is not published for this level. The table,
                time series, and downloads are unaffected.
              <//>
            </div>`}

          ${state.tab === 'map' && cat.boundaries?.[state.g] && html`
            <div style="padding:8px">
              <${MapView}
                rows=${mapRows}
                geography=${state.g}
                boundariesUrl=${cat.boundaries?.[state.g]}
                referenceUrl=${state.g === 'state' || state.g === 'nation'
                                 ? null : cat.boundaries?.state}
                names=${placeNames}
                valueLabel=${`${ds?.label || ''} · ${year}`}
                selected=${state.p}
                onPick=${(id) => go({ p: state.p === id ? null : id })} />
              <p class="small muted" style="margin-top:10px">
                Colour shows ${measure === 'n_noise' ? 'raw' : 'post-processed'} counts for
                the current filters. Units with no data are grey.
              </p>
            </div>`}

          ${state.tab === 'code' && html`<${CodeTab} valueLabels=${valueLabels} cat=${cat} url=${url}
              seriesUrl=${seriesUrl} measure=${measure} state=${state} year=${year}
              rows=${display} columns=${columns} series=${series} />`}
        </div>
      </div>
    </div>
  `;
}

/* Stable URLs plus copy-paste snippets. This is a headline feature for a
 * research audience, and it makes clear the site is a convenience layer over
 * data people can always reach directly. */
function CodeTab({ cat, url, seriesUrl, measure, state, year, rows, columns, series, valueLabels }) {
  const [copied, setCopied] = useState(null);
  const filters = Object.entries(state.facets)
    .filter(([, v]) => v?.length)
    .map(([k, v]) => `${k} IN (${v.map((c) => (typeof c === 'number' ? c : `'${c}'`)).join(', ')})`);
  const where = [state.p && `geo_id = '${state.p}'`, ...filters].filter(Boolean);
  const whereSql = where.length ? `\nWHERE ${where.join('\n  AND ')}` : '';

  const snippets = {
    SQL: `-- DuckDB\nSELECT geo_id, sum(${measure}) AS value\nFROM read_parquet('${url}')${whereSql}\nGROUP BY 1\nORDER BY value DESC;`,
    R: `library(arrow); library(dplyr)\n\nread_parquet("${url}") |>\n  ${where.length ? `filter(${where.map((w) => w.replace(/ = /, ' == ').replace(/ IN \(/, ' %in% c(')).join(', ')}) |>\n  ` : ''}group_by(geo_id) |>\n  summarise(value = sum(${measure}))`,
    Python: `import duckdb\n\nduckdb.sql("""\n  SELECT geo_id, sum(${measure}) AS value\n  FROM read_parquet('${url}')${whereSql}\n  GROUP BY 1\n""").df()`,
    Stata: `* Stata 19+ reads Parquet natively.\n* For 16-18: ssc install pq, then use pq_read.\nimport parquet using "${url}", clear\n${where.length ? where.map((w) => '* keep if ' + w.replace(/ = /, ' == ')).join('\\n') + '\\n' : ''}collapse (sum) ${measure}, by(geo_id)\ngsort -${measure}`,
  };

  const copy = (k) => { navigator.clipboard.writeText(snippets[k]); setCopied(k); setTimeout(() => setCopied(null), 1400); };

  return html`
    <div class="panel-body stack" style="--gap:18px">
      <div>
        <h4>Download</h4>
        <p class="small muted">The current selection, as shown in the table.</p>
        <div class="row">
          <button class="btn btn-primary btn-sm"
                  onClick=${() => exportCsv(rows, columns,
                    `gridded-eif_${state.d}_${state.g}_${year}.csv`, valueLabels)}>
            Download CSV
          </button>
          ${series?.length > 1 && html`
            <button class="btn btn-outline btn-sm"
                    onClick=${() => download(`gridded-eif_${state.d}_${state.g}_series.csv`,
                                             toCsv(series, ['year', 'value']))}>
              Download time series CSV
            </button>`}
        </div>
      </div>

      <div>
        <h4>Stable file URLs</h4>
        <p class="small muted">
          These are the exact files this page queries. They are immutable and versioned —
          safe to cite in a paper.
        </p>
        <div class="small mono" style="word-break:break-all;background:var(--surface-inset);
             border:1px solid var(--line);border-radius:var(--radius-sm);padding:10px">
          <div><strong>${year}:</strong> ${url}</div>
          ${seriesUrl && html`<div style="margin-top:6px"><strong>All years:</strong> ${seriesUrl}</div>`}
        </div>
      </div>

      <div style="margin-top:22px">
        <h4>Machine-readable catalog</h4>
        <p class="small muted" style="max-width:74ch">
          Every file on this site is listed in one JSON document. Read it and you
          have the whole corpus — no scraping, no hardcoded paths. It is how this
          page finds its own data, so it cannot drift from what is published.
        </p>
        <div class="small mono" style="word-break:break-all;background:var(--surface-inset);
             border:1px solid var(--line);border-radius:var(--radius-sm);padding:10px">
          ${CATALOG_URL}
        </div>
        <table class="data small" style="margin-top:10px">
          <thead><tr><th>Key</th><th>What it holds</th></tr></thead>
          <tbody>
            <tr><td class="mono">entries</td><td>One record per dataset × geography × year, with URL, rows, bytes, and sha256</td></tr>
            <tr><td class="mono">combined</td><td>All-years files, one per dataset × geography. Use these for time series</td></tr>
            <tr><td class="mono">crosswalks</td><td>Grid cell to geography assignments</td></tr>
            <tr><td class="mono">names</td><td>geo_id to display name, per geography</td></tr>
            <tr><td class="mono">boundaries</td><td>Simplified GeoJSON, geo_id only</td></tr>
            <tr><td class="mono">dimensions</td><td>Category codes and published labels</td></tr>
            <tr><td class="mono">measures</td><td>The two estimate versions and when each applies</td></tr>
          </tbody>
        </table>
        <p class="small muted" style="margin-top:8px">
          <code>pipeline_version</code> and <code>generated_at</code> identify the
          build. Data files are immutable; the catalog is not, so re-read it
          rather than caching URLs indefinitely.
        </p>
      </div>
      ${Object.entries(snippets).map(([k, v]) => html`
        <div>
          <div class="spread" style="margin-bottom:.3rem">
            <h4 style="margin:0">${k}</h4>
            <button class="btn btn-quiet btn-sm" onClick=${() => copy(k)}>
              ${copied === k ? 'Copied' : 'Copy'}
            </button>
          </div>
          <pre class="small mono" style="margin:0;overflow-x:auto;background:var(--surface-inset);
               border:1px solid var(--line);border-radius:var(--radius-sm);padding:12px">${v}</pre>
        </div>`)}
    </div>
  `;
}
