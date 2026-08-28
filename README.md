# Gridded EIF Explorer

Pre-aggregated [Gridded Environmental Impacts Frame](https://www.census.gov/data/experimental-data-products/gridded-eif.html)
data, ready to download — no 70 MB grid files, no spatial joins.

An [Environmental Inequality Lab](https://environmental-inequality-lab.org) project.

> **Experimental data.** The Gridded EIF is an experimental Census Bureau product
> built from administrative records with privacy noise infused. Counts will not
> match the Decennial Census or Population Estimates Program. Read the caveats
> below before drawing conclusions.

---

## What this is

The Census Bureau publishes the Gridded EIF as annual Parquet files on a fixed
0.01° grid — about 2.6 million populated cells and 20 million rows per year.
Answering "how many people over 65 live in Wayne County" means downloading
~70 MB, running a spatial join, and knowing which of two noise measures to use.

This project does that once, for every standard geography and year, and serves
the results as small static files anyone can query directly.

## Architecture

Static. No server, no database.

```
GitHub                          AWS
├── pipeline/   ──build──▶      S3 ──▶ CloudFront
├── catalog/                          │
└── site/       ──deploy──▶ Pages ────┘  DuckDB-WASM queries
                                          Parquet in the browser
```

Derived aggregates are immutable Parquet at versioned paths. `catalog.json` is
**fetched at runtime**, so adding a year means running the pipeline and
uploading — the site is not rebuilt or redeployed.

## Quick start

```bash
python3 -m venv ~/.venvs/gridded-eif
~/.venvs/gridded-eif/bin/pip install -e ".[dev]"
```

```bash
geif datasets
```

```bash
geif validate-source --dataset ageracesex --year 2022
```

```bash
geif build --geography county --year 2022
```

`--year` takes a single year, an inclusive range, a comma-separated list, or
`all` — so a full backfill is one command:

```bash
geif build --geography county --year 2000-2024
```

```bash
geif catalog --base-url https://YOUR_DISTRIBUTION.cloudfront.net
```

The annual refresh is one command:

```bash
geif refresh --year 2025 --geography county,state
```

The whole plan resolves up front, so a bad year fails immediately rather than
twenty minutes into a backfill. Catalog and publish run once at the end: if a
year fails nothing is published, and re-running the failing subrange folds it in
alongside what is already live.

## Running the site locally

No build step — Preact and htm are vendored, DuckDB-WASM loads from a pinned
CDN. Any static server works; ES modules just need `http://` rather than
`file://`:

```bash
python3 -m http.server 8765 --directory site
```

Then open <http://localhost:8765>. To test against a locally built catalog
instead of the published one, append `?catalog=./catalog.json` after running
`geif catalog`.

## Layout

| Path | What it is |
|---|---|
| `catalog/variables.yaml` | **Single source of truth.** Datasets, dimensions, geographies. |
| `catalog/contracts/` | Pinned source schema, derived from the files themselves. |
| `pipeline/` | Fetch → validate → crosswalk → aggregate → catalog → publish. |
| `tests/` | Registry consistency and regression tests against verified figures. |
| `site/` | The explorer. Static files, no build step. |
| `prototype/` | Early reconnaissance scripts. Superseded by `pipeline/`. |

**Adding a dataset, year, or geography should mean editing `variables.yaml` only.**
If it requires touching a pipeline module or a UI component, that's a bug.

## Three notes

**Coverage starts in 2000, not 1999.** The 1999 file is anomalous — its national
total is far below every later year — and is excluded from the registry.
Requesting it fails loudly rather than silently producing a series with a bad
first year.


**Two noise measures, not one.** `n_noise` is unbiased but can be negative (8.3%
of grid rows in 2022). `n_noise_postprocessed` is non-negative but redistributes
mass within race groups — which inflates the 65+ count by ~1.5% nationally.
Never mix them in one table. Rule of thumb: post-processed below 600,000
population, raw above.

**Grid cells are noise-dominated.** A single 0.01° cell is roughly a median block
group, and injected noise (typically ±3) can exceed the true count. Aggregate to
tract or above. This is why block group is deliberately not offered.

## Validation

The data is validated by an executable registry of checks, not by prose. Each
check is a function returning a typed result; the registry drives both the test
suite and a typeset PDF report, so a claim cannot appear in the document without
also being enforced in CI.

```bash
pip install -e ".[validation]"
```

```bash
geif validate-report --section A,C --tier 2
```

Checks are tiered by what they read, not by how long they take:

| Tier | Reads |
|---|---|
| 0 | Registry and configuration only |
| 1 | The local build tree. No network. |
| 2 | The published catalog and the Census source files |
| 3 | Independent published data — PEP, Decennial, ACS |

Every check is currently tier 2 or 3 — sections A and C both read the published
product. `pytest` runs any tier 0–1 check on every push and asserts, by
inspection, that nothing at those tiers reaches the network. Tier 3 needs
`CENSUS_API_KEY` for the ACS comparisons and records itself as skipped when it is
absent, never as passing.

**Checks run against the published artifacts, not `.build`.** The site fetches
its catalog from the CDN at runtime, so what is published is what users receive;
a report about the local build tree would describe a build nobody has.

Output lands in `validation/`: `results.json` is tracked, so diffing it across
commits shows regressions in the *data* rather than in the code. The PDF and the
LaTeX intermediates are not.

### When it runs

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | every push, PR | Tests, lint, and the renderer against a synthetic result set |
| `refresh-data.yml` | manual, quarterly | **Gates the publish.** Validates the build tree before upload, then re-validates the published product after |
| `validation.yml` | manual, monthly | The typeset PDF against whatever is currently published, uploaded as an artifact |

The gate is the important one. It runs `--local` against what was just built, and
a failure stops the run before anything reaches the CDN — a validation step that
publishes anyway is a log line nobody reads. The monthly run catches what a
refresh-triggered check cannot: an object lost from the CDN, an upstream file
revised in place, or a published claim drifting away from what the data shows.
Nothing has to change for it to start failing, which is the point.

## Versioning

[SemVer](https://semver.org), on four independent lines: the site, the pipeline,
the schema contract, and the derived data. Derived data paths carry the version
(`derived/v1/...`) so a breaking change publishes alongside the old tree and
never invalidates a URL someone cited. See [`CHANGELOG-DATA.md`](CHANGELOG-DATA.md).

## Citation

> Voorheis, J., Colmer, J., Houghton, K., Lyubich, E., Munro, M., Scalera, C.,
> and Withrow, J. (2025). "The Public-Use Gridded Environmental Impacts Frame."

Source data: <https://www2.census.gov/ces/gridded_eif/>
