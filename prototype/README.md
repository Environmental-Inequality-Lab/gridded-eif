# Phase 0 prototype

Throwaway scripts from the initial data reconnaissance (2026-08-21). Not the
pipeline — kept because they establish the approach and produced the validation
numbers the test suite now pins. Superseded by `pipeline/`.

| File | What it does |
|---|---|
| `build_xwalk.py` | Grid cell → county crosswalk via point-in-polygon against TIGER/Line 2024. ~9s for 2.6M cells. |
| `agg_county.py` | Aggregates the 2022 age×race×sex file to county and reconciles against verified national totals. |
| `county_ageracesex_2022.parquet` | Output: 117,146 rows, 3,144 counties, **1.3 MB**. Good candidate as the S3 CORS test file. |

## Setup

```bash
python3 -m venv venv && ./venv/bin/pip install duckdb pyarrow pandas geopandas
curl -O https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip
unzip tl_2024_us_county.zip -d counties
./venv/bin/python build_xwalk.py && ./venv/bin/python agg_county.py
```

Both read the source Parquet directly from census.gov over HTTPS via DuckDB `httpfs` —
no bulk download needed, since census.gov supports range requests (though not CORS,
which is why the site serves its own copy).

## Known gap

`build_xwalk.py` drops 222 border cells (14,214 people) whose centroids fall outside
the country. `pipeline/crosswalk.py` snaps these to the nearest county instead.
