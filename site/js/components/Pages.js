import { html, useState } from '../h.js';
import { count, bytes } from '../format.js';
import { Notice } from './Chrome.js';
import { SITE } from '../config.js';

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

      ${cat.crosswalks && Object.keys(cat.crosswalks).length > 0 && html`
        <div class="card" style="margin-top:20px">
          <h3>Crosswalks</h3>
          <p class="small muted" style="max-width:74ch">
            Which 0.01° grid cell belongs to which geography. The spatial join is
            the expensive part of using this data — these files let you skip it
            and aggregate the source grid yourself: the pollution and extreme
            weather files, or geographies not published here.
          </p>
          <p class="small muted" style="max-width:74ch">
            Columns are <code>grid_lon</code>, <code>grid_lat</code>,${' '}
            <code>geo_id</code>, and <code>snapped</code>. The coordinates match
            the source files exactly and are strings, so they join without
            floating-point trouble. <code>snapped</code> marks the cells whose
            centroid fell outside every unit and were assigned to the nearest
            one — border cells, mostly along the Canadian and Mexican frontiers.
          </p>
          <div class="table-scroll" style="margin-top:12px">
            <table class="data">
              <thead><tr><th>Geography</th><th class="n">Size</th><th></th></tr></thead>
              <tbody>
                ${Object.entries(cat.crosswalks).sort().map(([g, url]) => html`
                  <tr>
                    <td>${cat.geographies?.[g]?.label || g}</td>
                    <td class="n muted">parquet</td>
                    <td><a href=${url}>Download</a></td>
                  </tr>`)}
              </tbody>
            </table>
          </div>
        </div>`}

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
  const threshold = cat.measure_selection_population_threshold;
  const dims = cat.dimensions || {};
  const labels = (d) => (dims[d]?.values || []).map((v) => v.label).join(', ');

  return html`
    <div class="wrap section" style="max-width:820px">
      <h1>Documentation</h1>

      <p class="lead" style="margin-top:.4rem">
        The Gridded Environmental Impacts Frame (Gridded EIF) is a publicly accessible
        data product that aggregates restricted Census microdata in ways that preserve
        privacy and maintain analytical consistency, providing counts of the population
        by race and ethnicity, sex, and age, as well as by race and ethnicity and
        household income decile.
      </p>

      <${Notice}>
        This page summarizes the data as described by its authors. For the full
        treatment — construction, privacy protection, validation against the
        confidential microdata, and applications — see Voorheis, Colmer, Houghton,
        Lyubich, Munro, Scalera, and Withrow,${' '}
        <a href="https://doi.org/10.1086/742010">
          “The Census Environmental Impacts Frame,”</a>${' '}
        <em>Review of Environmental Economics and Policy</em> 20 (2): 304–312 (2026).
      <//>

      <${Notice} kind="warn">
        <strong>This is an experimental Census Bureau product.</strong> Methods may be
        revised. Because the EIF relies on administrative records, it may not always
        fully capture all subpopulations, so population totals may differ from those in
        the Decennial Census or Census Bureau population estimates.
      <//>

      <h2 style="margin-top:34px">Why gridded data</h2>
      <p>
        Providing the data in this form allows researchers to take advantage of certain
        features of the underlying microdata, offering substantial benefits over
        traditional analyses of aggregated place-based data.
      </p>
      <p>
        First, the data enable distributional analysis by intersectional characteristics,
        such as by race <em>and</em> income. Second, the underlying administrative
        records are updated more frequently than most aggregate demographic data, making
        the Gridded EIF more timely: American Community Survey 5-year tables draw on
        survey responses from several years back. Third, most individuals in the EIF can
        be geocoded to precise latitude and longitude, allowing for flexible aggregation
        to any geographic unit, not limited to those defined by the Census Bureau. This
        is particularly important when analyzing hazards that do not align with
        administrative boundaries; in these cases, aggregating to units of fixed size,
        such as a geographic grid, as opposed to fixed population, such as Census tracts,
        may enhance analysis.
      </p>

      <h2 style="margin-top:34px">Building the Gridded EIF</h2>
      <p>
        The Gridded EIF is an aggregation of the EIF microdata. All geocoded individuals
        are assigned to a grid point on a fixed, unprojected 0.01-degree grid, about
        1 km² in North America. The merged microdata are then collapsed by race, sex, and
        age groups (under 18, 18–64, and 65+), and by race and ethnicity and income
        deciles, within these grid points.
      </p>
      <p>
        Race and ethnicity categories are harmonized and mutually exclusive:${' '}
        ${labels('race_ethnicity')}. The residual group covers individuals without race
        information or who are some other race or multiracial. Individuals who cannot be
        matched to the demographic spine — for example, those without Social Security
        numbers — will not have age and sex information; the race-by-age-by-sex
        aggregations retain counts of these individuals as a separate group in each grid
        point.
      </p>
      <p class="small muted">
        The grid system is essentially identical in the North American domain to the
        widely used unprojected grid systems in atmospheric sciences, such as the
        satellite-derived data on fine particulate matter from van Donkelaar et al.
        (2021). This facilitates harmonizing external environmental data at the level of
        variation in socioeconomic characteristics.
      </p>

      <h2 style="margin-top:34px">Noise injection</h2>
      <p>
        The grid points used in the Gridded EIF represent very small geographic
        locations, which means it is not possible to publish raw tabulations under
        current Census Bureau disclosure avoidance guidelines without additional privacy
        protection. To protect the privacy of individuals in the underlying microdata, a
        small amount of noise is added to each statistic, using a noise infusion strategy
        inspired by the differential privacy methods used in the 2020 Decennial Census.
        Mean zero, discrete Gaussian noise is injected with a standard deviation tuned
        such that most drawn values fall between −3 and 3.
      </p>
      <p>
        This noise can be thought of as “on the order of rounding,” in that the degree of
        coarsening is similar to the rounding schemes used for official Census
        tabulations of the American Community Survey and other collections. It is infused
        only into demographic counts that actually exist in the underlying microdata for
        each grid point: if a particular race-by-income or race-by-sex-by-age group does
        not exist there, the count is treated as structurally zero. This approach differs
        slightly from strict differential privacy requirements and lacks a formal privacy
        guarantee.
      </p>
      <p>
        The noise typically nets out when aggregating grid points to larger geographies,
        yielding estimates consistent with the underlying microdata.
      </p>

      <h2 style="margin-top:34px">The two data options</h2>
      <p>
        Discrete Gaussian noise can generate negative values that sometimes exceed the
        original counts in magnitude, creating negative cell values in the final data
        set. Researchers may prefer strictly nonnegative demographic counts at the grid
        level, so both options are published and you can choose between them.
      </p>
      ${Object.entries(cat.measures).map(([id, m]) => html`
        <div class="card" style="margin-bottom:12px">
          <h3>${m.label} <code style="font-family:var(--font-mono);font-size:.8rem">${id}</code></h3>
          <p class="small" style="margin:.4rem 0">${m.description}</p>
          <p class="small muted" style="margin:0">Recommended when ${m.recommended_when}.</p>
        </div>`)}
      <p>
        The postprocessing algorithm exploits the nested structure of grids and the
        tendency for demographics and environmental hazards to be positively correlated
        within small geographic areas. Within each 1-degree grid point, small noisy cells
        are identified — those with raw noisy counts smaller than the absolute value of
        the most negative count in that grid point. Their sum is calculated by race group
        and redistributed evenly across them, which preserves ratio population
        distributions and forces most cells to be nonnegative. Any remaining negative
        values are set to zero.
      </p>
      <p>
        Which option is more accurate depends on the size of the geography. Compared with
        the confidential microdata, the unprocessed measure produces mean absolute errors
        roughly 65 percent larger than the postprocessed measure overall. For the
        smallest commuting zones, unprocessed errors are more than double; for the
        largest — the top 10 percent by population — the postprocessed measure has a mean
        absolute error about 25 percent larger. The crossover occurs near the population
        threshold where Census Bureau disclosure avoidance rules permit direct estimates
        from the confidential microdata.
      </p>
      <p class="small muted">
        This site follows that finding: it selects a default by the size of the geography,
        at a threshold of ${threshold?.toLocaleString()} people, and reports which option
        is in use. Never mix the two in one table — they are different estimators of the
        same quantity.
      </p>

      <h2 style="margin-top:34px">How this site aggregates</h2>
      <p>
        Everything above describes the published data. This section describes what this
        site adds: rolling the grid up to standard geographies so you do not have to run
        the spatial join yourself.
      </p>
      <p>
        Each grid point is assigned to the geographic unit containing its centroid, and
        counts are summed within that unit. Aggregation is lossless — national totals
        reproduce the source exactly.
      </p>
      <ul>
        <li>
          <strong>Border cells.</strong> A small number of populated cells have centroids
          that fall outside every unit, almost all along the Canadian and Mexican
          borders. Rather than drop them, they are assigned to the nearest unit, measured
          in a projected coordinate system. The published crosswalks flag these rows.
        </li>
        <li>
          <strong>Partial coverage.</strong> Metropolitan and micropolitan areas and ZIP
          Code Tabulation Areas do not cover the entire country. Cells outside every unit
          are excluded rather than snapped, so their totals do not sum to the national
          figure. The site states this wherever such a geography is selected.
        </li>
        <li>
          <strong>Residual categories.</strong> Groups such as the residual race category
          and unreported age or sex are kept visible and never folded into totals
          silently.
        </li>
        <li>
          <strong>Census tracts are not offered.</strong> Tracts approach the size of a
          single grid cell, and dense urban tracts can be smaller than one, so centroid
          assignment either finds no cell or finds one whose residents mostly live
          elsewhere. Anyone who needs tract-level data can build it from the published
          crosswalks.
        </li>
      </ul>

      <h2 style="margin-top:34px">Near-real-time estimates</h2>
      <p>
        Alongside the standard annual files, a “nowcast” version is produced for the most
        recent year. It starts from the most recent EIF residential histories and updates
        residential locations for individuals who had filed their most recent 1040 tax
        return when the file was created, providing the most up-to-date information on
        locations available in the administrative records.
      </p>
      <p class="small muted">
        Preliminary years are labelled as such throughout this site and are excluded from
        the headline year range. Treat them as provisional.
      </p>

      <h2 style="margin-top:34px">Limitations</h2>
      <p>
        The Gridded EIF allows researchers to explore correlations between environmental
        hazards and socioeconomic conditions in a manner consistent with the underlying
        microdata, but it will not address all use cases.
      </p>
      <ul>
        <li>
          Many population characteristics beyond race, age, sex, and income are not
          available.
        </li>
        <li>
          The 0.01-degree resolution means aggregation bias may still be an issue for
          environmental hazards that vary substantially within about 1 km².
        </li>
        <li>
          Grid-cell counts carry noise that has not averaged out. Inferences about small
          areas, rare demographic groups, or year-over-year change should be made at
          larger geographies.
        </li>
      </ul>
      <p class="small muted">
        Researchers who encounter these constraints should pursue projects in the Federal
        Statistical Research Data Centers, which provide access to the confidential
        underlying microdata.
      </p>

      <h2 style="margin-top:34px">Citation</h2>
      <p>
        Please cite both this site, which produced the aggregated figures, and the
        article introducing the underlying data.
      </p>
      <div class="card">
        <p class="small" style="margin:0 0 .6rem">
          Seiter, Grant M. ${new Date().getFullYear()}.${' '}
          <em>${SITE.name}</em>. ${SITE.org}.${' '}
          ${SITE.url}${cat.generated_at ? ` (accessed ${String(cat.generated_at).slice(0, 10)})` : ''}.
        </p>
        <p class="small" style="margin:0">
          Voorheis, John, Jonathan Colmer, Kendall Houghton, Eva Lyubich, Mary Munro,
          Cameron Scalera, and Jennifer Withrow. 2026. “The Census Environmental Impacts
          Frame.” <em>Review of Environmental Economics and Policy</em> 20 (2): 304–312.
        </p>
      </div>
      <p class="small muted" style="margin-top:14px">
        Source data:${' '}
        <a href=${cat.source?.base_url}>Census file directory</a> ·${' '}
        <a href=${cat.source?.landing_page}>Census product page</a> ·${' '}
        Aggregation code: <a href=${SITE.repo}>GitHub</a>
      </p>
    </div>
  `;
}
