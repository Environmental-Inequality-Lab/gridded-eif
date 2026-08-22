import { html, useState, useMemo } from '../h.js';
import { datasets } from '../catalog.js';
import { Lattice } from './Lattice.js';

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

  // Driven by the catalog, so publishing a dataset surfaces it here with no
  // code change.
  const starts = datasets(cat).map((d) => ({
    label: d.label,
    patch: { v: 'explore', d: d.id, g: 'county' },
  }));

  return html`
    <div>
      <section class="section" style="padding-top:56px">
        <div class="wrap">
          <div class="hero-grid">
            <div>
          <p class="eyebrow">U.S. Census Bureau experimental data product</p>
          <h1 class="hero-title">Explore Gridded EIF Data</h1>
          <p class="lead">
            A publicly accessible data product that aggregates the Census
            Environmental Impacts Frame in ways that preserve privacy and maintain
            analytical consistency — counts of the population by race and ethnicity,
            sex, and age, and by race/ethnicity and household income decile.
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

            <div class="hero-art"><${Lattice} /></div>
          </div>
        </div>
      </section>

      <section class="section section-soft">
        <div class="wrap">
          <p class="eyebrow">Why gridded data</p>
          <div class="grid3">
            <div>
              <h3>Intersectional</h3>
              <p class="small muted">
                The data enable distributional analysis by intersectional
                characteristics, such as by race <em>and</em> income — not one
                dimension at a time.
              </p>
            </div>
            <div>
              <h3>Timely</h3>
              <p class="small muted">
                The underlying administrative records are updated more frequently
                than most aggregate demographic data. American Community Survey
                5-year tables draw on survey responses from several years back.
              </p>
            </div>
            <div>
              <h3>Flexible</h3>
              <p class="small muted">
                Most individuals in the frame are geocoded to precise latitude and
                longitude, allowing aggregation to any geographic unit — not only
                those the Census Bureau defines.
              </p>
            </div>
          </div>
          <p class="small muted" style="margin-top:20px;max-width:74ch">
            Aggregating to units of fixed size, such as a geographic grid, rather
            than fixed population, such as census tracts, can help when analysing
            hazards that do not align with administrative boundaries.
          </p>
        </div>
      </section>

      <section class="section">
        <div class="wrap">
          <div class="grid2">
            <div class="card">
              <h3>Noise infusion</h3>
              <p class="small muted">
                Grid points represent very small geographic locations, so a small
                amount of noise is added to each statistic. It can be thought of as
                "on the order of rounding" — a degree of coarsening similar to the
                rounding schemes used for official Census tabulations. The noise
                typically nets out when aggregating grid points to larger
                geographies.
              </p>
            </div>
            <div class="card">
              <h3>Two published counts</h3>
              <p class="small muted">
                Both raw noisy counts and postprocessed counts are provided,
                allowing users to apply alternative postprocessing algorithms if
                they wish. This site selects a default by the size of the geography
                and reports which is in use.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;
}
