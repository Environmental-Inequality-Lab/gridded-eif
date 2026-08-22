import { html } from '../h.js';
import { dimension, yearsFor, isPreliminary, datasets, geographies, defaultMeasure } from '../catalog.js';

/* The query panel. Dataset comes first deliberately: the two population
 * datasets are separate tabulations of the same people and cannot be crossed
 * on demographics — there is no age-by-income. Choosing the dataset first makes
 * the impossible query unreachable instead of an error message. */
export function QueryPanel({ cat, state, go, toggleFacet, places, measure, measureAuto, selectionTotal }) {
  const ds = cat.datasets[state.d];
  const years = yearsFor(cat, state.d, state.g);
  const geos = geographies(cat);

  return html`
    <div class="panel">
      <div class="panel-head">Query</div>
      <div class="panel-body">

        <div class="field">
          <label for="ds">Dataset</label>
          <select id="ds" value=${state.d}
                  onChange=${(e) => go({ d: e.target.value, facets: {} })}>
            ${datasets(cat).map((d) => html`<option value=${d.id}>${d.label}</option>`)}
          </select>
          ${ds?.not_joinable_with?.length > 0 && html`
            <p class="small muted" style="margin:.4rem 0 0">
              The two datasets are separate tabulations of the same population.
              They can be linked on grid cell but not on demographic categories;
              no age-by-income cross-tabulation exists.
            </p>`}
        </div>

        <div class="field">
          <label for="geo">Geography</label>
          <select id="geo" value=${state.g}
                  onChange=${(e) => go({ g: e.target.value, p: null })}>
            ${geos.map((g) => html`<option value=${g.id}>${g.label}</option>`)}
          </select>
          ${geos.find((g) => g.id === state.g)?.caveat && html`
            <p class="small muted" style="margin:.4rem 0 0">
              ${geos.find((g) => g.id === state.g).caveat}
            </p>`}
        </div>

        ${state.g !== 'nation' && html`
          <div class="field">
            <label for="place">Place</label>
            <select id="place" value=${state.p || ''}
                    onChange=${(e) => go({ p: e.target.value || null })}>
              <option value="">All ${geos.find((g) => g.id === state.g)?.label || ''}</option>
              ${(places || [])
                .filter((p) => p.level === state.g)
                .map((p) => html`<option value=${p.geo_id}>${p.name}</option>`)}
            </select>
          </div>`}

        <div class="field">
          <label for="yr">Year</label>
          <select id="yr" value=${String(state.y ?? years[years.length - 1] ?? '')}
                  onChange=${(e) => go({ y: Number(e.target.value) })}>
            ${years.map((y) => html`
              <option value=${y}>${y}${isPreliminary(cat, state.d, y) ? ' — preliminary' : ''}</option>
            `)}
          </select>
        </div>

        ${(ds?.dimensions || []).map((dimId) => {
          const dim = dimension(cat, dimId);
          if (!dim) return null;
          const sel = state.facets[dimId] || [];
          return html`
            <div class="field">
              <label>${dim.label}</label>
              <div class="chips">
                ${dim.values.map((v) => html`
                  <button
                    class=${'chip' + (sel.includes(v.code) ? ' on' : '') + (v.residual ? ' residual' : '')}
                    title=${v.residual ? 'Residual category — kept visible rather than folded into totals' : ''}
                    onClick=${() => toggleFacet(dimId, v.code)}>${v.label}</button>
                `)}
              </div>
              ${sel.length > 0 && html`
                <button class="btn btn-quiet btn-sm" style="margin-top:6px"
                        onClick=${() => go({ facets: { ...state.facets, [dimId]: [] } })}>
                  Clear ${dim.label.toLowerCase()}
                </button>`}
              ${dim.footnote && html`<p class="small muted" style="margin:.4rem 0 0">${dim.footnote}</p>`}
            </div>`;
        })}

        <div class="field">
          <label for="m">Estimate version</label>
          <select id="m" value=${state.m || measure}
                  onChange=${(e) => go({ m: e.target.value })}>
            ${Object.entries(cat.measures).map(([id, m]) => html`
              <option value=${id}>${m.label}</option>`)}
          </select>
          <div class="small muted" style="margin:.5rem 0 0">
            <p style="margin:0 0 .5rem">${cat.measures[measure]?.description}</p>
            ${(() => {
              /* Whether the choice fits what is actually on screen, not just
               * the general rule. Stating "recommended above 600,000" while a
               * 40,000-person county is displayed leaves the reader to do the
               * comparison, which is the part worth doing for them. */
              const threshold = cat.measure_selection_population_threshold;
              const advised = defaultMeasure(cat, selectionTotal);
              const fits = advised === measure;
              if (!threshold || !selectionTotal) return null;
              return html`<p style="margin:0 0 .5rem">
                This selection totals ${Math.round(selectionTotal).toLocaleString()},
                ${selectionTotal > threshold ? ' above ' : ' below '}
                the ${threshold.toLocaleString()} threshold, so${' '}
                <strong>${cat.measures[advised]?.label.toLowerCase()}</strong> is the
                recommended version${fits ? ' — the one in use.' : ' and this is not it.'}
              </p>`;
            })()}
            <p style="margin:0 0 .5rem">
              The two versions differ most for small geographies and for sparse
              categories — notably the oldest age group and the residual "not
              reported" categories, where the adjustment shifts a visible share of
              the total. They are different estimators of the same quantity and
              should not be combined in a single table.
            </p>
            ${(() => {
              const advised = defaultMeasure(cat, selectionTotal);
              const mismatch = selectionTotal > 0 && advised !== measure;
              if (mismatch) {
                return html`<p style="margin:0">
                  <button class="btn btn-quiet btn-sm" style="padding:0 .2rem"
                          onClick=${() => go({ m: advised })}>
                    Switch to ${cat.measures[advised]?.label.toLowerCase()}
                  </button>
                </p>`;
              }
              return measureAuto
                ? html`<p style="margin:0">${'Selected automatically at the '}
                    ${cat.measure_selection_population_threshold.toLocaleString()}
                    ${' population threshold.'}</p>`
                : html`<p style="margin:0">Set manually.
                    <button class="btn btn-quiet btn-sm" style="padding:0 .2rem"
                            onClick=${() => go({ m: null })}>Use the recommended version</button>
                  </p>`;
            })()}
          </div>
        </div>

      </div>
    </div>
  `;
}
