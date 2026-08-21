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
    """)

    con.execute(f"""
        COPY part TO '{out_path.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
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
