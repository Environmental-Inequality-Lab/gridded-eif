# Data changelog

Changes to the **published aggregates**. If you have cited a number from this
site, this is the file to check.

Versions are SemVer applied to the data, treating the consuming analyst as the
API client:

| Bump | Means | Examples |
|---|---|---|
| **MAJOR** | Existing queries may now return different or invalid results | Column renamed or removed; category values changed; aggregation method changed; geography vintage shifts unit IDs |
| **MINOR** | Purely additive; existing queries unaffected | New year, new geography level, new dataset, new column |
| **PATCH** | Corrections with no structural change | Recomputed values after an upstream fix or pipeline bug |

**MAJOR bumps publish alongside the previous version** at a new path
(`derived/v2/...`). Previously published URLs keep resolving and keep returning
the numbers they always returned.

## [Unreleased] — v1

Initial build. Source data version 5.0 (Census).

### Added
- `ageracesex` and `raceincome` at county, state, and nation level, 2000–2024.
- All-years files per dataset and geography, in the catalog's `combined` array.
  Use these for time series; use the per-year `entries` for a single year or for
  bulk download. Both contain identical values.
- Both noise measures (`n_noise`, `n_noise_postprocessed`) in every partition.

### Known characteristics
- **1999 is excluded**; coverage begins in 2000. Its national total is far
  outside the range of every other year and it is not used in practice.
  Requesting it fails loudly rather than silently producing a series with an
  anomalous first year.
- Administrative-records completeness is not constant across years, which
  matters for long count series. Per-year diagnostics are deferred to a later
  release rather than shipped with unsourced reference figures.
- Aggregation is lossless: county totals reproduce source national totals exactly.
- 222 grid cells (14,214 people in 2022) sit outside all county polygons because
  they straddle the US–Canada and US–Mexico borders with centroids abroad. These
  are snapped to the nearest county rather than dropped.
- Territories (PR, VI, GU, AS, MP) have no data; the source does not cover them.
- Post-processing inflates the `Over 65` count by ~1.5% nationally. This is a
  property of the upstream algorithm, not of this pipeline.
