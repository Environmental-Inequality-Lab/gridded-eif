"""Schema-contract validation.

The published user guide is not a reliable schema contract, so every source
file is checked against ``catalog/contracts/source-schema-v5.json`` before it is
used. Drift must fail loudly here rather than surface as quietly wrong numbers
three steps downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from . import config


class ContractViolation(Exception):
    """Raised when a source file does not match the pinned schema contract."""


@dataclass
class ValidationReport:
    dataset: str
    year: int
    url: str
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_failed(self) -> ValidationReport:
        if self.errors:
            detail = "\n  - ".join(self.errors)
            raise ContractViolation(
                f"{self.dataset} {self.year} violates the schema contract:\n  - {detail}\n"
                f"Source: {self.url}\n"
                f"If Census changed the schema, update the contract and bump its version "
                f"deliberately — do not loosen the check to make this pass."
            )
        return self


def validate_source(dataset: str, year: int, con: duckdb.DuckDBPyConnection | None = None) -> ValidationReport:
    """Check one source file's columns, types, categories, and row count."""
    con = con or _connection()
    url = config.source_url(dataset, year)
    spec = config.contract()["datasets"][dataset]
    rep = ValidationReport(dataset=dataset, year=year, url=url)

    # --- columns and types ---
    described = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchall()
    actual = {row[0]: row[1] for row in described}
    for col in spec["columns"]:
        if col["name"] not in actual:
            rep.errors.append(f"missing column {col['name']!r} (found: {sorted(actual)})")
        elif actual[col["name"]] != col["type"]:
            rep.errors.append(
                f"column {col['name']!r} is {actual[col['name']]}, contract says {col['type']}"
            )
    for extra in set(actual) - {c["name"] for c in spec["columns"]}:
        rep.warnings.append(f"unexpected column {extra!r} — new data may be available")

    # --- row count ---
    rep.rows = con.execute(f"SELECT count(*) FROM read_parquet('{url}')").fetchone()[0]
    if not spec["expected_rows_min"] <= rep.rows <= spec["expected_rows_max"]:
        rep.errors.append(
            f"row count {rep.rows:,} outside expected range "
            f"[{spec['expected_rows_min']:,}, {spec['expected_rows_max']:,}]"
        )

    # --- category values ---
    for dim, expected in spec.get("categories", {}).items():
        if dim not in actual:
            continue
        found = [r[0] for r in con.execute(
            f"SELECT DISTINCT {dim} FROM read_parquet('{url}') ORDER BY 1"
        ).fetchall()]
        if dim == "income_decile":
            found = [int(v) for v in found if v is not None]
        unknown = set(found) - set(expected)
        if unknown:
            rep.errors.append(f"{dim}: unexpected categories {sorted(unknown)}")
        absent = set(expected) - set(found)
        if absent:
            rep.warnings.append(f"{dim}: contract categories absent from data {sorted(absent)}")

    return rep


def check_invariants(dataset: str, year: int, con: duckdb.DuckDBPyConnection | None = None) -> ValidationReport:
    """Verify the statistical invariants the contract asserts.

    These catch a class of failure a column check cannot: the schema is intact
    but the numbers have moved.
    """
    con = con or _connection()
    url = config.source_url(dataset, year)
    rep = ValidationReport(dataset=dataset, year=year, url=url)
    inv = {i["id"]: i for i in config.contract()["invariants"]}

    total_raw, _total_pp, n_neg_pp = con.execute(f"""
        SELECT sum(n_noise), sum(n_noise_postprocessed),
               sum(CASE WHEN n_noise_postprocessed < 0 THEN 1 ELSE 0 END)
        FROM read_parquet('{url}')
    """).fetchone()

    spec = inv["national_total_plausible"]
    if not spec["min"] <= total_raw <= spec["max"]:
        rep.errors.append(
            f"national total {total_raw:,.0f} outside plausible range "
            f"[{spec['min']:,}, {spec['max']:,}]"
        )

    if n_neg_pp:
        rep.errors.append(f"{n_neg_pp:,} negative values in n_noise_postprocessed (must be zero)")

    # Post-processing redistributes within race, so race totals must survive it.
    tol = inv["postprocessing_preserves_race_totals"]["tolerance_abs"]
    for race, raw, pp in con.execute(f"""
        SELECT race_ethnicity, sum(n_noise), sum(n_noise_postprocessed)
        FROM read_parquet('{url}') GROUP BY 1
    """).fetchall():
        if abs(raw - pp) > tol:
            rep.errors.append(
                f"race {race!r}: raw {raw:,.0f} vs post-processed {pp:,.0f} "
                f"differ by {abs(raw - pp):,.0f}, tolerance {tol:,}"
            )

    rep.rows = int(total_raw)
    return rep


def _connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    return con
