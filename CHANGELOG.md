# Changelog

Code changes — pipeline and site. Data releases are in
[`CHANGELOG-DATA.md`](CHANGELOG-DATA.md); the two have different audiences, and
a researcher checking whether their numbers moved should not have to read UI
release notes.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Pipeline: fetch, contract validation, crosswalk, aggregation, catalog, publish.
- `catalog/variables.yaml` as the single declarative registry.
- `catalog/contracts/source-schema-v5.json`, derived empirically from the 2022
  source files rather than from the user guide, whose code examples are stale.
- County crosswalk with nearest-polygon snapping for border cells.
- GitHub Actions: data refresh via OIDC, plus CI including a weekly contract
  check against the live source.
- Regression tests pinning verified 2022 national totals.
