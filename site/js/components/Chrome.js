import { html } from '../h.js';
import { SITE, BASE } from '../config.js';

const NAV = [
  { v: 'explore', label: 'Query Data' },
  { v: 'data', label: 'Download Data' },
  { v: 'docs', label: 'Documentation' },
];

export function Header({ view, go }) {
  return html`
    <header class="site-header">
      <div class="wrap">
        <a class="brand" href="?" onClick=${(e) => { e.preventDefault(); go({ v: 'home' }); }}>
          <img class="brand-mark" src="${BASE}assets/eil-logo-white.webp"
               alt="Environmental Inequality Lab" width="600" height="200" />
        </a>
        <nav class="site-nav">
          ${NAV.map(
            (n) => html`
              <a
                href="?v=${n.v}"
                class=${view === n.v ? 'active' : ''}
                onClick=${(e) => { e.preventDefault(); go({ v: n.v }); }}
                >${n.label}</a
              >
            `
          )}
        </nav>
      </div>
    </header>
  `;
}

export function Footer({ cat }) {
  const src = cat?.source;
  return html`
    <footer class="site-footer">
      <div class="wrap">
        <div class="spread" style="align-items:flex-start;gap:28px">
          <div style="max-width:52ch">
            <strong>${SITE.name}</strong> — an ${' '}
            <a href=${SITE.orgUrl}>${SITE.org}</a> project, built by${' '}
            <a href=${SITE.authorUrl}>${SITE.author}</a>.
            <p class="small" style="margin-top:.6rem">
              Built from the U.S. Census Bureau's Gridded Environmental Impacts Frame,
              an experimental data product. Counts derive from administrative records
              and may not match the Decennial Census or Population Estimates Program.
            </p>
            <div style="margin-top:.6rem">
              <a href=${SITE.repo}>Source code</a>
              ${src && html` · <a href=${src.landing_page}>Census product page</a>`}
              ${src && html` · <a href=${src.base_url}>Raw data</a>`}
            </div>
          </div>
          <div class="small" style="max-width:52ch">
            <strong>Citation</strong>
            <p class="small muted" style="margin:.4rem 0 .5rem">
              Please cite both this site, which produced the aggregated figures, and
              the article introducing the underlying data.
            </p>
            <p class="small" style="margin:0 0 .5rem">
              Seiter, Grant M. ${new Date().getFullYear()}.${' '}
              <em>${SITE.name}</em>. ${SITE.org}.${' '}
              ${SITE.url}${cat ? ` (accessed ${String(cat.generated_at).slice(0, 10)})` : ''}.
            </p>
            <p class="small" style="margin:0">
              Voorheis, John, Jonathan Colmer, Kendall Houghton, Eva Lyubich, Mary Munro,
              Cameron Scalera, and Jennifer Withrow. 2026. “The Census Environmental
              Impacts Frame.”${' '}
              <em>Review of Environmental Economics and Policy</em> 20 (2): 304–312.
            </p>
            ${cat && html`
              <div class="muted" style="margin-top:.6rem">
                Data ${cat.derived_version} · pipeline ${cat.pipeline_version} ·
                updated ${String(cat.generated_at).slice(0, 10)}
              </div>`}
          </div>
        </div>
        <p class="small muted" style="margin:22px 0 0;padding-top:16px;
             border-top:1px solid var(--line);max-width:none">
          <strong>Disclaimer:</strong> This website presents and aggregates data from a
          U.S. Census Bureau data product. The presentation, analysis, and
          interpretation of these data are the responsibility of the site authors and
          do not reflect the views of the U.S. Census Bureau.
        </p>
      </div>
    </footer>
  `;
}

export function Notice({ kind = 'info', children }) {
  return html`<div class=${'notice' + (kind === 'warn' ? ' notice-warn' : '')}>${children}</div>`;
}

export function Spinner({ label }) {
  return html`<span class="row" style="gap:8px">
    <span class="spinner"></span><span class="small muted">${label || 'Working…'}</span>
  </span>`;
}
