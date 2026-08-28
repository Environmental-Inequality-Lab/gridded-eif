# Changelog

Code changes — pipeline and site. Data releases are in
[`CHANGELOG-DATA.md`](CHANGELOG-DATA.md); the two have different audiences, and
a researcher checking whether their numbers moved should not have to read UI
release notes.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `C1` no longer passes merely because nothing was dropped. It adjudicates each
  dropped cell geometrically: a cell is a legitimate exclusion only if it lies
  further from every US polygon than the declared snap radius, so the pipeline
  was offered the chance to recover it and correctly declined. This surfaced a
  single cell at −171.285, 55.955 — open Bering Sea, ~130 km from the
  Pribilofs — carrying 17 people in 2024 and 2025. It is excluded
  deliberately, and any *other* cell dropped from inside the country now fails
  the check. Adjudicating geometrically rather than against a list is what stops
  the check decaying into an allowlist.
- `C6` is reported as a characterisation (`info`) rather than a failure. It
  measures drift in the populated cell set, which is a property of the source
  data rather than a defect — Census is not doing anything wrong by
  publishing a moving cell set. It was a failure only while the pipeline assumed
  otherwise; `C1` and `C7` are the checks that fail if it ever does again.
- `geif validate-report --local` validates the local build tree instead of the
  published product, for checking a fix before it goes out. The report states on
  its title page which of the two it read, since a green report against
  unpublished artifacts says nothing about what users are receiving.

- **The data refresh now validates before it publishes.** `refresh-data` runs the
  crosswalk checks against the build tree and stops the run if any fail, so a
  defect cannot reach the CDN, then re-validates the published product
  afterwards. A new `validation` workflow produces the typeset report monthly
  and on demand. `ci` installs the validation extra — the package imports
  jinja2 and matplotlib at module level, so collecting the tests needs them.
- `test_dependencies` scans `pipeline/` recursively and counts optional extras
  as declared. It previously scanned only the top level, which is how the
  validation package's imports went unnoticed by the very test written to catch
  exactly that.
- Report prose no longer varies with the outcome. A check's `claim`, `method`
  and `interpretation` are fixed strings on its registration, printed the same
  whether it passes or fails; results contribute a status, a metrics table,
  evidence tables and figures, and no sentences. Enforced by a test that rejects
  a format placeholder in any prose field. Prose assembled at runtime reads
  fluently while going quietly out of date, and nobody rereads a paragraph that
  still scans.
- The report opens with a generated inventory — source, datasets, dimension
  codes against display labels, measures, geography levels, published files,
  file schemas read from the files themselves, and aggregation rules — so a
  citation identifies a specific set of files and category codes.
- A full build fetches each source file once and joins it to every geography,
  instead of re-reading it per level. A seven-level backfill drops from 364
  remote reads of a 45–80 MB file to 52.
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
- **Validation harness** (`geif validate-report`, `pipeline/validation/`). An
  executable registry of checks that runs against the *published* artifacts and
  renders a typeset PDF. The registry also drives `pytest`, so a claim cannot
  appear in the report without being enforced in CI, and the report cannot drift
  from what the pipeline does. Sections A (provenance) and C (crosswalk) are
  implemented; B, D, E, F are declared and appear in the document as explicitly
  empty rather than silently absent. Checks are tiered by what they read — 0
  configuration, 1 local build tree, 2 published product and Census sources, 3
  external benchmarks — and tiers 0–1 run on every push.
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
- **The crosswalk dropped population in every year except 2022** (found by
  validation check `C1`). `crosswalk.build()` took its populated-cell list from
  a single reference year and reused it for all years, on the assumption that
  the grid is fixed. The grid is; the *populated* subset of it is not (`C6`).
  Aggregation inner-joins each year's source against the crosswalk, so cells a
  year contained that 2022 did not were silently discarded with their
  population — 0.05% to 0.43% per year, and zero in 2022 alone, which is
  exactly why `test_aggregation_is_lossless` never caught it. The loss was
  spatially concentrated: Hawaii was short 3.90% of its 2024 population
  (`C8`). Crosswalks are now built from the union of populated cells across
  every published dataset-year — 3,021,990 cells rather than 2,611,734 —
  which also fixes `C7`, the published crosswalks having covered only the 2022
  cell set. **Pipeline version bumped to 1.0.0**, per the MAJOR rule in
  `__version__.py`: aggregation changed such that previously published numbers
  change, and the bump is what forces every partition to rebuild rather than
  leaving stale ones that still look finished. See `CHANGELOG-DATA.md`.
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

### Added — initial build
- Pipeline: fetch, contract validation, crosswalk, aggregation, catalog, publish.
- `catalog/variables.yaml` as the single declarative registry.
- `catalog/contracts/source-schema-v5.json`, derived empirically from the 2022
  source files rather than from the user guide, whose code examples are stale.
- County crosswalk with nearest-polygon snapping for border cells.
- GitHub Actions: data refresh via OIDC, plus CI including a weekly contract
  check against the live source.
- Regression tests pinning verified 2022 national totals.
