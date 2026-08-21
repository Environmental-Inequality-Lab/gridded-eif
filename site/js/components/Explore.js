import { html, useState, useEffect, useMemo } from '../h.js';
import { query, buildQuery, q } from '../duck.js';
import { entryUrl, combinedUrl, yearsFor, isPreliminary, dimension, defaultMeasure } from '../catalog.js';
import { QueryPanel } from './QueryPanel.js';
import { ResultsTable, TimeSeries, exportCsv } from './Results.js';
import { Notice, Spinner } from './Chrome.js';
import { count, toCsv, download } from '../format.js';

export function Explore({ cat, state, go, toggleFacet, places }) {
  const [rows, setRows] = useState([]);
  const [series, setSeries] = useState([]);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState(null);
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

    Promise.all([query(tableSql), seriesSql ? query(seriesSql) : Promise.resolve([])])
      .then(([t, s]) => {
        if (cancelled) return;
        setRows(t); setSeries(s.map((r) => ({ year: Number(r.year), value: r.value })));
        setMs(Math.round(performance.now() - t0));
      })
      .catch((e) => !cancelled && setErr(String(e.message || e)))
      .finally(() => !cancelled && setBusy(false));

    return () => { cancelled = true; };
  }, [url, seriesUrl, measure, state.p, state.g, state.d, year, JSON.stringify(state.facets)]);

  const placeName = useMemo(
    () => places?.find((p) => p.geo_id === state.p)?.name,
    [places, state.p]
  );

  const columns = useMemo(() => {
    const base = groupBy.includes('geo_id') ? ['name', ...groupBy.filter((c) => c !== 'geo_id')] : [...groupBy];
    return [...base, 'value'];
  }, [groupBy]);

  const nameFor = useMemo(() => {
    const m = new Map((places || []).map((p) => [p.geo_id, p.name]));
    return (id) => m.get(id) || id;
  }, [places]);

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
               : ms != null && html`<span class="small muted num">${ms} ms</span>`}
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
            <button class=${'tab' + (state.tab === 'code' ? ' on' : '')}
                    onClick=${() => go({ tab: 'code' })}>Get the data</button>
          </div>

          ${state.tab === 'table' && html`
            <${ResultsTable}
              rows=${display} columns=${columns} labels=${labels}
              note=${`${cat.measures[measure].label.toLowerCase()} estimates`}
              onExport=${() => exportCsv(display, columns,
                `gridded-eif_${state.d}_${state.g}_${year}.csv`)} />`}

          ${state.tab === 'series' && html`
            <div>
              ${series.length > 1 && html`
                <div style="padding:12px 16px 0">
                  <${Notice}>
                    Counts across years reflect changes in administrative-records
                    coverage as well as population. Read long trends with care.
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

          ${state.tab === 'code' && html`<${CodeTab} cat=${cat} url=${url}
              seriesUrl=${seriesUrl} measure=${measure} state=${state} year=${year} />`}
        </div>
      </div>
    </div>
  `;
}

/* Stable URLs plus copy-paste snippets. This is a headline feature for a
 * research audience, and it makes clear the site is a convenience layer over
 * data people can always reach directly. */
function CodeTab({ cat, url, seriesUrl, measure, state, year }) {
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
  };

  const copy = (k) => { navigator.clipboard.writeText(snippets[k]); setCopied(k); setTimeout(() => setCopied(null), 1400); };

  return html`
    <div class="panel-body stack" style="--gap:18px">
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
