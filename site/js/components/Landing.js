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
            The Gridded Environmental Impacts Frame (Gridded EIF) is a publicly
            accessible data product that aggregates restricted Census microdata in
            ways that preserve privacy and maintain analytical consistency,
            providing counts of the population by race and ethnicity, sex, and age,
            as well as by race and ethnicity and household income decile.
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
          <p class="eyebrow">About the data</p>
          <p style="max-width:none;margin:0 0 26px;font-size:1.06rem">
            The Gridded EIF offers substantial benefits over traditional aggregated
            place-based data.
          </p>
          <div class="grid3">
            <div>
              <h3>Intersectional characteristics</h3>
              <p class="small muted">
                The Gridded EIF enables distributional analysis across intersectional
                characteristics for nearly the entire U.S. population. Restricted
                microdata are collapsed by race, sex, and age groups (under 18,
                18–64, and 65+), and by race <em>and</em> income deciles.
              </p>
            </div>
            <div>
              <h3>High-frequency temporal coverage</h3>
              <p class="small muted">
                The administrative records underlying the Gridded EIF are updated
                more frequently than most aggregated demographic data. American
                Community Survey 5-year tables, for example, draw on survey
                responses from several years back. Close to the entire population
                is covered by the restricted EIF residential history file.
              </p>
            </div>
            <div>
              <h3>Flexible aggregation</h3>
              <p class="small muted">
                Most individuals in the restricted EIF are geocoded to precise
                latitude and longitude, allowing aggregation to any geographic
                unit. The Gridded EIF assigns these individuals to a grid point on
                a fixed 0.01-degree grid, approximately 1 km² in North America.
              </p>
            </div>
          </div>
          <p class="small muted" style="margin-top:22px;max-width:78ch">
            This site does that aggregation for you. It takes the published grid and
            rolls it up to standard geographies — nation, state, county, metro area,
            PUMA, commuting zone, and ZIP code tabulation area — for every year and
            demographic breakdown, so you can query, filter, download, and cite
            without running a spatial join yourself. Start from${' '}
            <a href="?v=explore">Query Data</a>, take whole files from${' '}
            <a href="?v=data">Download Data</a>, or read how the aggregation works in
            the <a href="?v=docs">documentation</a>.
          </p>
        </div>
      </section>

      <section class="section">
        <div class="wrap">
          <p class="eyebrow">Working with these counts</p>
          <p style="max-width:78ch;margin:0 0 22px;font-size:1.06rem">
            Two features of the Gridded EIF shape every figure on this site. Both
            follow from the privacy protection applied before publication, and
            neither is a property of this aggregation.
          </p>
          <div class="grid2">
            <div class="card">
              <h3>Noise injection</h3>
              <p class="small muted">
                The grid points used in the Gridded EIF represent very small
                geographic areas, so a small amount of noise is added to each
                statistic. This noise, injected to protect the privacy of
                individuals in the underlying microdata, can be thought of as
                “on the order of rounding” — a degree of coarsening similar to the
                rounding schemes used for official Census tabulations. The noise
                typically nets out when grid points are aggregated to larger
                geographies.
              </p>
            </div>
            <div class="card">
              <h3>Two data options</h3>
              <p class="small muted">
                Both raw (noise-injected) counts and post-processed counts are
                provided. The raw counts can include negative cell values from the
                noise-injection process. The post-processing algorithm ensures that
                cell values are non-negative: small noisy cells are pooled by race
                within each 1-degree grid point and redistributed, and any residual
                negatives are set to zero. This site selects a default based on the
                size of the geography and reports which version is in use.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;
}
