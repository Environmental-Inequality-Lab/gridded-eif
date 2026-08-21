# Changelog

Code changes — pipeline and site. Data releases are in
[`CHANGELOG-DATA.md`](CHANGELOG-DATA.md); the two have different audiences, and
a researcher checking whether their numbers moved should not have to read UI
release notes.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Derived partitions are now sorted by `geo_id` and written with 8,000-row row
  groups. Parquet stores min/max statistics per row group, so a contiguous sort
  lets a single-place query skip the rest of the file. Measured on county 2024:
  15 row groups with tight ranges, and a one-county lookup touches **1 of 15**
  (~7% of the file) instead of scanning all of it. Sorting also improved
  compression — files got *smaller* despite the smaller groups (1.3 MB → 1.2 MB).
- `geif publish` now invalidates the data paths it replaced, not just the
  catalog. Derived Parquet is served `immutable`, which is right almost always,
  but a layout change rewrites files in place and edges would otherwise serve
  stale bytes for a year while the catalog advertised a new sha256. Falls back
  to a wildcard past 50 objects, which is billed as a single path.

### Added
- **Choropleth map.** MapLibre, loaded lazily since it is the heaviest
  dependency and most visits never open it. Geometry and values stay strictly
  separate: boundary GeoJSON carries `geo_id` and nothing else, and query
  results are joined to features at render time via feature-state. A new year
  of data therefore needs no new geometry, and one boundary file serves every
  measure, year, and filter.
- **Simplified boundary GeoJSON** (`geif boundaries`), topology-preserving via
  `topojson` so adjacent units keep shared borders — per-polygon simplification
  tears gaps that read as missing data. Counties compress from 204 MB of raw
  TIGER geometry to 3.2 MB. Plain GeoJSON rather than vector tiles because no
  tiling toolchain is available here or in CI, and at these feature counts it
  is small enough to serve directly.
- Quantile class breaks. Population is heavily skewed, so equal-interval breaks
  would paint nearly everything the lightest shade.

### Fixed
- One failing query no longer blanks the other views. The table, time series,
  and map read different files; `Promise.all` meant an unavailable all-years
  file took the table and map down with it. Now `allSettled`, with the series
  reporting its own failure in place.
- All-years files (`derived/v1/{dataset}/{geography}/all/`), one per dataset and
  geography, listed in the catalog's new `combined` array.

  Measured, 25-year national series, 5 trials each with a fresh engine:

  | CDN state | 25 per-year files | 1 combined file |
  |---|---:|---:|
  | Cold edge | ~5,000 ms | ~350 ms (est.) |
  | Warm edge | 415 ms | 348 ms |

  The steady-state gain is modest (~16%). The real case is a cold edge, where
  25 files mean 25 origin fetches. CloudFront edges cache independently across
  hundreds of locations, so for a low-traffic research site most requests arrive
  at an edge that has not seen these files — cold is the common case, not the
  exception.

  Per-year partitions are kept — they remain the right shape for single-year
  queries and bulk download, and stay the unit built incrementally.
- `geif combine`, wired into `refresh` and the workflow. It takes `--base-url`
  and pulls years not rebuilt in the current run from the published catalog, so
  a single-year refresh cannot produce a one-year "all-years" file. Same failure
  mode as the catalog clobbering, and just as invisible — the file would look
  perfectly valid.
- `state` and `nation` geography levels. Nation is declared as a `constant`
  source — every cell maps to one id — which keeps a single aggregation path
  instead of adding a second one that sums state partitions. Both give the same
  answer, since after nearest-polygon snapping every populated cell belongs to
  exactly one state.
- Cross-level consistency tests: nation, state, and county totals must agree.
  Each level is built independently from the same grid cells, so a cell dropped
  by one crosswalk but kept by another surfaces here, where a single-level test
  would see nothing wrong.
### Added
- Pipeline: fetch, contract validation, crosswalk, aggregation, catalog, publish.
- `catalog/variables.yaml` as the single declarative registry.
- `catalog/contracts/source-schema-v5.json`, derived empirically from the 2022
  source files rather than from the user guide, whose code examples are stale.
- County crosswalk with nearest-polygon snapping for border cells.
- GitHub Actions: data refresh via OIDC, plus CI including a weekly contract
  check against the live source.
- Regression tests pinning verified 2022 national totals.
