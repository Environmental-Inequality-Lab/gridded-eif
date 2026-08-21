import { html, useState, useMemo } from '../h.js';
import { datasets, geographies } from '../catalog.js';
import { count } from '../format.js';

/* Search-first landing.
 *
 * One input that resolves places and variables, then hands over the full
 * workbench. Deliberately not map-first: at this data's native resolution a
 * single grid cell is noise-dominated, and a map invites people to read one.
 */
export function Landing({ cat, go, places }) {
  const [term, setTerm] = useState('');

  const matches = useMemo(() => {
    const t = term.trim().toLowerCase();
    if (t.length < 2) return [];
    const out = [];
    for (const p of places || []) {
      if (p.name.toLowerCase().includes(t) || p.geo_id.startsWith(t)) {
        out.push({ kind: 'place', ...p });
        if (out.length >= 8) break;
      }
    }
    for (const d of datasets(cat)) {
      if (d.label.toLowerCase().includes(t)) out.push({ kind: 'dataset', id: d.id, name: d.label });
    }
    return out.slice(0, 10);
  }, [term, places, cat]);

  const totalRows = cat.entries.reduce((s, e) => s + e.rows, 0);
  const years = cat.datasets.ageracesex?.years || [];

  const starts = [
    { label: 'Population by race, by county', patch: { v: 'explore', d: 'ageracesex', g: 'county' } },
    { label: 'Income distribution by state', patch: { v: 'explore', d: 'raceincome', g: 'state' } },
    { label: 'National trends since 2000', patch: { v: 'explore', d: 'ageracesex', g: 'nation', tab: 'series' } },
    { label: 'Download files', patch: { v: 'data' } },
  ];

  return html`
    <div>
      <section class="section" style="padding-top:56px">
        <div class="wrap">
          <p class="eyebrow">U.S. Census Bureau experimental data product</p>
          <h1 style="max-width:22ch">Explore Gridded EIF Data</h1>
          <p class="lead">
            Population counts by age, race, sex, and household income, aggregated
            from the 0.01° Gridded Environmental Impacts Frame to standard
            geographies.
          </p>

          <div style="max-width:640px;margin-top:28px;position:relative">
            <label for="q">Search for a place</label>
            <input
              id="q" type="search" autocomplete="off"
              placeholder="Wayne County, MI · California · United States"
              value=${term}
              onInput=${(e) => setTerm(e.target.value)}
            />
            ${matches.length > 0 && html`
              <div class="panel" style="position:absolute;z-index:20;width:100%;margin-top:4px;box-shadow:var(--shadow-lg)">
                ${matches.map((m) => html`
                  <button
                    class="btn btn-quiet"
                    style="width:100%;justify-content:space-between;border-radius:0"
                    onClick=${() => go(
                      m.kind === 'place'
                        ? { v: 'explore', g: m.level, p: m.geo_id }
                        : { v: 'explore', d: m.id }
                    )}>
                    <span>${m.name}</span>
                    <span class="tag">${m.kind === 'place' ? m.levelLabel : 'dataset'}</span>
                  </button>
                `)}
              </div>`}
          </div>

          <div class="row" style="margin-top:22px">
            ${starts.map((s) => html`
              <button class="btn btn-outline btn-sm" onClick=${() => go(s.patch)}>${s.label}</button>
            `)}
          </div>
        </div>
      </section>

      <section class="section section-soft">
        <div class="wrap">
          <div class="grid3">
            <div>
              <h3>${years.length ? `${years[0]}–${years[years.length - 1]}` : '—'}</h3>
              <p class="small muted">Annual coverage, derived from administrative records.</p>
            </div>
            <div>
              <h3>${geographies(cat).map((g) => g.label).join(' · ')}</h3>
              <p class="small muted">Each geography is aggregated independently from the
              same grid cells; totals reconcile across levels.</p>
            </div>
            <div>
              <h3 class="num">${count(totalRows)}</h3>
              <p class="small muted">Rows published, queried in the browser directly from
              the underlying Parquet files.</p>
            </div>
          </div>
        </div>
      </section>

      <section class="section">
        <div class="wrap">
          <div class="grid2">
            <div class="card">
              <h3>Two estimate versions</h3>
              <p class="small muted">
                Each count is published in two versions, which differ in how the
                infused noise is handled. The appropriate version depends on the size
                of the geography being analysed. This site selects a default and
                reports which is in use.
              </p>
            </div>
            <div class="card">
              <h3>Disclosure avoidance</h3>
              <p class="small muted">
                Counts are protected by noise infusion to preserve confidentiality.
                The noise averages out under aggregation, so estimates are published
                at standard geographies rather than at the native grid resolution.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;
}
