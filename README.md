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
geif build --geography county --year 1999-2024
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

## Layout

| Path | What it is |
|---|---|
| `catalog/variables.yaml` | **Single source of truth.** Datasets, dimensions, geographies. |
| `catalog/contracts/` | Pinned source schema, derived from the files themselves. |
| `pipeline/` | Fetch → validate → crosswalk → aggregate → catalog → publish. |
| `tests/` | Registry consistency and regression tests against verified figures. |
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

## Versioning

[SemVer](https://semver.org), on four independent lines: the site, the pipeline,
the schema contract, and the derived data. Derived data paths carry the version
(`derived/v1/...`) so a breaking change publishes alongside the old tree and
never invalidates a URL someone cited. See [`CHANGELOG-DATA.md`](CHANGELOG-DATA.md).

## Citation

> Voorheis, J., Colmer, J., Houghton, K., Lyubich, E., Munro, M., Scalera, C.,
> and Withrow, J. (2025). "The Public-Use Gridded Environmental Impacts Frame."

Source data: <https://www2.census.gov/ces/gridded_eif/>
