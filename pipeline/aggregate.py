"""Aggregates gridded source data to a geography level.

One partition per (dataset, geography, year). Both noise measures are carried
side by side so the UI can switch between them, but they are never summed
together — they are different estimators of the same quantity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
from rich.console import Console

from . import config
from .__version__ import __version__

console = Console()
BUILD_DIR = config.REPO_ROOT / ".build"


@dataclass
class Partition:
    dataset: str
    geography: str
    year: int
    path: str
    rows: int
    bytes: int
    sha256: str
    preliminary: bool
    pipeline_version: str
    total_raw: float
    total_postprocessed: float
    geo_units: int


def build(
    dataset: str,
    geography: str,
    year: int,
    crosswalk_path: Path,
    force: bool = False,
) -> Partition:
    """Aggregate one (dataset, geography, year) partition."""
    ds = config.datasets()[dataset]
    out_dir = BUILD_DIR / config.derived_key(dataset, geography, year)
    out_path = out_dir.parent / f"{out_dir.name}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ledger = _ledger_path(dataset, geography, year)
    if out_path.exists() and ledger.exists() and not force:
        recorded = json.loads(ledger.read_text())
        if recorded.get("pipeline_version") == __version__:
            console.print(f"[dim]{dataset}/{geography}/{year}: up to date[/dim]")
            return Partition(**recorded)

    url = config.source_url(dataset, year)
    measures = config.measure_columns()
    measure_sql = ", ".join(f"sum(d.{m}) AS {m}" for m in measures)

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    # income_decile ships as DOUBLE; cast so the output is a clean integer.
    select_dims = ", ".join(
        f"CAST(d.{d} AS INTEGER) AS {d}" if d == "income_decile" else f"d.{d}"
        for d in ds.dimensions
    )
    group_dims = ", ".join(str(i + 2) for i in range(len(ds.dimensions)))

    con.execute(f"""
        CREATE TABLE part AS
        SELECT x.geo_id, {select_dims}, {measure_sql}, count(*) AS n_cells
        FROM read_parquet('{url}') d
        JOIN read_parquet('{crosswalk_path.as_posix()}') x
          ON d.grid_lon = x.grid_lon AND d.grid_lat = x.grid_lat
        GROUP BY 1, {group_dims}
        -- Sorting by geo_id is what makes Parquet row-group statistics useful:
        -- each row group then covers a contiguous span of geographies, so a
        -- query filtered to one place can skip the rest of the file. Unsorted,
        -- every row group spans nearly every geography and nothing is skippable.
        ORDER BY geo_id, {group_dims}
    """)

    # Small row groups so pruning is fine-grained. At ~117k rows a 100k group
    # size yields two groups and prunes almost nothing; 8k yields ~15 groups,
    # and a single-county lookup touches one or two of them. The compression
    # cost is a few percent — worth it for interactive single-place queries,
    # which are the common case.
    con.execute(f"""
        COPY part TO '{out_path.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 8000)
    """)

    rows, units, total_raw, total_pp = con.execute("""
        SELECT count(*), count(DISTINCT geo_id),
               sum(n_noise), sum(n_noise_postprocessed) FROM part
    """).fetchone()

    part = Partition(
        dataset=dataset,
        geography=geography,
        year=year,
        path=config.derived_key(dataset, geography, year),
        rows=int(rows),
        bytes=out_path.stat().st_size,
        sha256=_sha256(out_path),
        preliminary=ds.is_preliminary(year),
        pipeline_version=__version__,
        total_raw=float(total_raw),
        total_postprocessed=float(total_pp),
        geo_units=int(units),
    )

    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(asdict(part), indent=2))
    console.print(
        f"[green]{dataset}/{geography}/{year}[/green]: "
        f"{part.rows:,} rows, {part.geo_units:,} units, "
        f"{part.bytes / 1e6:.1f} MB, total {part.total_raw:,.0f}"
    )
    return part


def _ledger_path(dataset: str, geography: str, year: int) -> Path:
    return BUILD_DIR / "_ledger" / dataset / geography / f"{year}.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Combined:
    """An all-years file for one (dataset, geography)."""

    dataset: str
    geography: str
    path: str
    years: list[int]
    rows: int
    bytes: int
    sha256: str
    pipeline_version: str


def combine(
    dataset: str,
    geography: str,
    published: dict | None = None,
    force: bool = False,
) -> Combined | None:
    """Concatenate a geography's per-year partitions into one file.

    Why this exists: latency for multi-year queries is dominated by per-file
    round trips, not bytes. A 25-year national time series reads 66 KB spread
    over 25 files and takes ~5 seconds in a browser — one HTTP handshake and
    footer read per file. Collapsing to a single file makes it one round trip.

    Per-year partitions are kept as well. They remain the right shape for
    single-year queries and for bulk download, and they stay the unit the
    pipeline builds incrementally. This file is derived from them cheaply, with
    no re-read of the source data.

    The trade-off against the partition design is real: adding a year rewrites
    this file rather than only writing new leaves. It is one small file per
    (dataset, geography), rebuilt from local Parquet in seconds, which is a fair
    price for turning a 5-second default view into one request.
    """
    ledgers = sorted((_ledger_path(dataset, geography, 0).parent).glob("*.json"))
    local = {}
    for led in ledgers:
        p = Partition(**json.loads(led.read_text()))
        path = BUILD_DIR / config.derived_key(dataset, geography, p.year)
        if path.exists():
            local[p.year] = path.as_posix()

    # Years already published but not rebuilt in this run are read straight from
    # the CDN. Without this, a CI run that refreshes a single year would produce
    # an all-years file containing only that year — the same failure mode as the
    # catalog clobbering itself, and just as invisible, since the file would look
    # perfectly valid.
    remote = {}
    for e in (published or {}).get("entries", []):
        if e["dataset"] == dataset and e["geography"] == geography and e["year"] not in local:
            remote[e["year"]] = e["url"]

    sources_by_year = {**remote, **local}   # locally rebuilt wins
    if not sources_by_year:
        return None
    years = sorted(sources_by_year)
    sources = [sources_by_year[y] for y in years]
    if remote:
        console.print(
            f"[dim]{dataset}/{geography}: {len(local)} local + "
            f"{len(remote)} from the published catalog[/dim]"
        )

    out_path = BUILD_DIR / config.combined_key(dataset, geography)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")   # some sources may be remote
    # filename=true recovers the year from the path, so no schema change is
    # needed in the per-year partitions themselves.
    con.execute(f"""
        CREATE TABLE combined AS
        SELECT CAST(regexp_extract(filename, '/(\\d{{4}})/', 1) AS INTEGER) AS year, * EXCLUDE (filename)
        FROM read_parquet({sources!r}, filename=true)
        ORDER BY geo_id, year
    """)
    con.execute(f"""
        COPY combined TO '{out_path.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 8000)
    """)
    rows = con.execute("SELECT count(*) FROM combined").fetchone()[0]

    result = Combined(
        dataset=dataset,
        geography=geography,
        path=config.combined_key(dataset, geography),
        years=years,
        rows=int(rows),
        bytes=out_path.stat().st_size,
        sha256=_sha256(out_path),
        pipeline_version=__version__,
    )
    ledger = BUILD_DIR / "_ledger" / "_combined" / f"{dataset}__{geography}.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(asdict(result), indent=2))
    console.print(
        f"[green]{dataset}/{geography}/all[/green]: {result.rows:,} rows, "
        f"{len(years)} years, {result.bytes / 1e6:.1f} MB"
    )
    return result
