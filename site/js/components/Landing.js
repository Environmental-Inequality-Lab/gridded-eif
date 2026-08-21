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
    { label: 'Browse all files', patch: { v: 'data' } },
  ];

  return html`
    <div>
      <section class="section" style="padding-top:56px">
        <div class="wrap">
          <p class="eyebrow">Experimental Census data, made usable</p>
          <h1 style="max-width:20ch">Gridded EIF Explorer</h1>
          <p class="lead">
            Population by age, race, sex, and income — aggregated from a 0.01°
            grid to the geographies you actually work with. No 70 MB downloads,
            no spatial joins.
          </p>

          <div style="max-width:640px;margin-top:28px;position:relative">
            <label for="q">Search a place, or a variable</label>
            <input
              id="q" type="search" autocomplete="off"
              placeholder="Wayne County, MI · California · population 65+"
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
              <p class="small muted">Annual coverage, updated from administrative records
              more current than ACS five-year tables.</p>
            </div>
            <div>
              <h3>${geographies(cat).map((g) => g.label).join(' · ')}</h3>
              <p class="small muted">Pre-aggregated. Each level is built independently
              from the same grid cells and reconciles exactly.</p>
            </div>
            <div>
              <h3 class="num">${count(totalRows)}</h3>
              <p class="small muted">Rows published, queryable directly in your browser —
              no server, no sign-in.</p>
            </div>
          </div>
        </div>
      </section>

      <section class="section">
        <div class="wrap">
          <div class="grid2">
            <div class="card">
              <p class="eyebrow">Read this first</p>
              <h3>Two measures, not one</h3>
              <p class="small muted">
                Every count ships in two versions. <code>n_noise</code> is unbiased but
                can be negative; <code>n_noise_postprocessed</code> is non-negative but
                shifts mass between demographic categories. The right choice depends on
                how big your geography is — this site picks a default and shows you which.
              </p>
            </div>
            <div class="card">
              <p class="eyebrow">Read this too</p>
              <h3>Privacy noise is real</h3>
              <p class="small muted">
                Counts carry deliberate noise so individuals cannot be identified.
                It cancels out as you aggregate, which is why this site serves
                counties and states rather than raw grid cells.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;
}
