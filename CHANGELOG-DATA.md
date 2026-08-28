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

### Corrected — every year except 2022 has changed

**If you have cited a count from this site, recheck it.** Every published year
except 2022 was short, by between 0.05% and 0.43% of its national total. The
figures now match the source exactly.

Crosswalks were built from the populated grid cells of a single reference year
(2022) and reused for every year, on the assumption that the grid is fixed. The
grid is fixed; the *populated* subset of it is not. Aggregation inner-joins each
year's source file against the crosswalk, so any cell a year contained that 2022
did not was silently discarded along with its population. 2022 alone was exact,
by construction.

The loss was not evenly spread. In 2024 Hawaii was short by 3.90% of its
population — 48,169 people across 694 cells, one of which held over 16,000 —
followed by Montana at 0.83%, South Dakota at 0.70% and Wyoming at 0.70%. Two
distinct failure modes: dense cells whose presence in the data moves year to
year, and sparse rural cells in the mountain west.

Crosswalks are now built from the union of populated cells across every
published dataset-year: 3,021,990 cells rather than 2,611,734.

**Published in place, under `derived/v1/`.** This is a deliberate departure from
the MAJOR-bump rule above, which would ordinarily republish alongside at
`derived/v2/`. The rule exists so that a cited URL keeps returning the number it
always returned — but here that number was wrong, and preserving it would mean
serving a known undercount in perpetuity to anyone who had already cited it. The
data had been public for one week and no external citation was known. Correcting
in place was judged the lesser harm; the previous values are not recoverable
from the CDN.

### Also changed
- The published crosswalks now cover the union too. Previously they covered only
  the 2022 cell set — 13.6% of the cells ever populated could not be assigned
  with them, which mattered because the site recommends them for aggregating the
  Census source grids it does not serve.

### Initial build

Source data version 5.0 (Census).

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
- Aggregation is lossless for every cell inside the country: county totals
  reproduce source national totals exactly. The one exception is a single cell
  at −171.285, 55.955 — open Bering Sea, roughly 130 km from the Pribilofs and
  far beyond the 25 km snap radius. It appears only in 2024 and 2025 and carries
  17 people. It is excluded deliberately rather than snapped to a county it does
  not belong to, and validation check C1 fails if any *other* cell is ever
  dropped from inside the country.
- 286 grid cells sit outside all county polygons because they straddle the
  US–Canada and US–Mexico borders with centroids abroad. These are snapped to the
  nearest county rather than dropped; in 2022 they carry 14,214 people.
- Territories (PR, VI, GU, AS, MP) have no data; the source does not cover them.
- Post-processing inflates the `Over 65` count by ~1.5% nationally. This is a
  property of the upstream algorithm, not of this pipeline.
