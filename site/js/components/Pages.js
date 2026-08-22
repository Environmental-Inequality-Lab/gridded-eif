import { html, useState } from '../h.js';
import { count, bytes } from '../format.js';
import { Notice } from './Chrome.js';

/* Bulk downloads. Our aggregates are hosted; the raw 0.01° grid is linked to
 * Census rather than rehosted — better provenance, and it keeps egress costs
 * off a small budget. */
export function DataPage({ cat }) {
  const [ds, setDs] = useState(Object.keys(cat.datasets)[0]);
  const entries = cat.entries.filter((e) => e.dataset === ds);
  const combined = (cat.combined || []).filter((c) => c.dataset === ds);
  const totalBytes = entries.reduce((s, e) => s + e.bytes, 0);

  return html`
    <div class="wrap section">
      <p class="eyebrow">Bulk download</p>
      <h1>Data</h1>
      <p class="lead">
        Every file this site queries, downloadable directly. Parquet, immutable,
        and versioned — safe to cite.
      </p>

      <div class="row" style="margin:20px 0">
        ${Object.entries(cat.datasets).map(([id, d]) => html`
          <button class=${'chip' + (ds === id ? ' on' : '')} onClick=${() => setDs(id)}>${d.label}</button>
        `)}
      </div>

      ${combined.length > 0 && html`
        <div class="card" style="margin-bottom:20px">
          <h3>All years, one file</h3>
          <p class="small muted">
            Prefer these for time series. Reading many per-year files means many
            round trips, which dominates load time.
          </p>
          <div class="table-scroll">
            <table class="data">
              <thead><tr><th>Geography</th><th>Years</th><th>Rows</th><th>Size</th><th></th></tr></thead>
              <tbody>
                ${combined.map((c) => html`
                  <tr>
                    <td>${cat.geographies[c.geography]?.label || c.geography}</td>
                    <td class="n">${c.years[0]}–${c.years[c.years.length - 1]}</td>
                    <td class="n">${count(c.rows)}</td>
                    <td class="n">${bytes(c.bytes)}</td>
                    <td><a href=${c.url}>Download</a></td>
                  </tr>`)}
              </tbody>
            </table>
          </div>
        </div>`}

      <div class="card">
        <div class="spread">
          <h3 style="margin:0">By year</h3>
          <span class="small muted">${count(entries.length)} files · ${bytes(totalBytes)}</span>
        </div>
        <div class="table-scroll" style="max-height:420px;overflow-y:auto;margin-top:10px">
          <table class="data">
            <thead><tr><th>Geography</th><th>Year</th><th>Rows</th><th>Size</th><th></th></tr></thead>
            <tbody>
              ${entries.map((e) => html`
                <tr>
                  <td>${cat.geographies[e.geography]?.label || e.geography}</td>
                  <td class="n">${e.year}${e.preliminary ? html` <span class="prelim">prelim</span>` : ''}</td>
                  <td class="n">${count(e.rows)}</td>
                  <td class="n">${bytes(e.bytes)}</td>
                  <td><a href=${e.url}>Download</a></td>
                </tr>`)}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="margin-top:20px">
        <h3>Raw grid data</h3>
        <p class="small muted">
          The underlying 0.01° grid files are published by the Census Bureau and are
          not rehosted here. Each is 45–80 MB per year.
        </p>
        <a class="btn btn-outline btn-sm" href=${cat.source.base_url}>Census file directory</a>
      </div>
    </div>
  `;
}

/* Methodology. Never gated, never abbreviated — this is what stops the data
 * being misused, so it has to be at least as reachable as the download button. */
export function DocsPage({ cat }) {
  const agg = cat.aggregation || {};
  return html`
    <div class="wrap section" style="max-width:820px">
      <p class="eyebrow">Methodology</p>
      <h1>Documentation</h1>

      <${Notice} kind="warn">
        <strong>This is an experimental Census Bureau product.</strong> Methods may be
        revised. Counts come from administrative records and will not match the
        Decennial Census or Population Estimates Program.
      <//>

      <h2 style="margin-top:34px">The two estimate versions</h2>
      <p>Every count is published twice, and the difference is not cosmetic.</p>
      ${Object.entries(cat.measures).map(([id, m]) => html`
        <div class="card" style="margin-bottom:12px">
          <h3>${m.label} <code style="font-family:var(--font-mono);font-size:.8rem">${id}</code></h3>
          <p class="small" style="margin:.4rem 0">${m.description}</p>
          <p class="small muted" style="margin:0">Recommended when ${m.recommended_when}.</p>
        </div>`)}
      <p class="small muted">
        This site defaults by geography size, at a threshold of${' '}
        ${cat.measure_selection_population_threshold?.toLocaleString()} people, and shows
        which version is in use. Never mix the two in one table — they are different
        estimators of the same quantity.
      </p>

      <h2 style="margin-top:34px">Privacy noise</h2>
      <p>
        Counts carry deliberate mean-zero noise so individuals cannot be identified.
        It averages out as you aggregate, which is why this site publishes counties and
        states rather than raw grid cells: a single 0.01° cell is roughly the size of a
        median block group, and the noise can exceed the count itself.
      </p>
      <p class="small muted">
        Block group is deliberately not offered. Aggregating to it would give no noise
        reduction while implying a precision the data cannot support.
      </p>

      <h2 style="margin-top:34px">How cells become geographies</h2>
      <ul class="small">
        <li><strong>Point-in-polygon on the cell centroid</strong> — each cell is assigned
            whole to the geography containing its centre.</li>
        ${agg.snap_unmatched_to_nearest && html`<li><strong>Border cells snap to the
            nearest geography.</strong> A few hundred cells straddle the Canadian and
            Mexican borders with centroids outside the country. Dropping them would
            systematically undercount border communities.</li>`}
        ${agg.residual_categories_visible && html`<li><strong>Residual categories stay
            visible.</strong> "Other/Unknown", "Missing Age", and "Not reported" are never
            silently folded into totals.</li>`}
      </ul>
      <p class="small muted">
        Each geography level is built independently from the same grid cells, and their
        totals reconcile exactly.
      </p>

      <h2 style="margin-top:34px">Coverage and comparability</h2>
      <ul class="small">
        <li>Coverage begins in <strong>2000</strong>. The 1999 file is anomalous and is
            excluded.</li>
        <li>Administrative-records coverage improves over time, so long count series mix
            population change with coverage change.</li>
        <li>Territories (Puerto Rico, USVI, Guam, American Samoa, Northern Marianas) are
            not covered by the source data.</li>
        <li>Preliminary vintages are marked throughout and will be revised.</li>
      </ul>

      <h2 style="margin-top:34px">Citation</h2>
      <p class="small">${cat.source.citation}</p>
      <p class="small muted">
        Please also acknowledge that the data undergoes privacy protection and is subject
        to revision as methods are refined.
      </p>
    </div>
  `;
}
