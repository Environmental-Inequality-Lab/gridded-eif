"""Loads the declarative registry and schema contract.

Everything the pipeline knows about datasets, dimensions, and geographies comes
from ``catalog/variables.yaml``. Nothing here hardcodes a dataset name, a
category value, or a year range — adding data must be a config change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "catalog"
REGISTRY_PATH = CATALOG_DIR / "variables.yaml"

# Version prefix for derived data. Bumping this writes a NEW tree alongside the
# old one so previously published URLs keep resolving.
DERIVED_VERSION = "v1"


@dataclass(frozen=True)
class Dataset:
    name: str
    label: str
    enabled: bool
    file_pattern: str
    dimensions: tuple[str, ...]
    years: tuple[int, ...]
    preliminary_years: tuple[int, ...]
    preliminary_file_pattern: str | None
    unit: str
    excluded_years: dict[int, str]

    def all_years(self) -> tuple[int, ...]:
        years = (set(self.years) | set(self.preliminary_years)) - set(self.excluded_years)
        return tuple(sorted(years))

    def is_preliminary(self, year: int) -> bool:
        return year in self.preliminary_years

    def filename(self, year: int) -> str:
        if self.is_preliminary(year):
            if not self.preliminary_file_pattern:
                raise ValueError(f"{self.name} has no preliminary file pattern for {year}")
            return self.preliminary_file_pattern.format(year=year)
        return self.file_pattern.format(year=year)


@dataclass(frozen=True)
class Geography:
    name: str
    label: str
    phase: int
    id_field: str | None
    name_field: str | None
    tiger_url: str | None
    per_state: bool
    tiger_url_pattern: str | None
    built_from: str | None
    derived_from: str | None
    source: str | None
    constant_id: str | None
    constant_name: str | None


@cache
def registry() -> dict:
    with REGISTRY_PATH.open() as fh:
        return yaml.safe_load(fh)


@cache
def contract() -> dict:
    version = registry()["source"]["data_version"].split(".")[0]
    path = CATALOG_DIR / "contracts" / f"source-schema-v{version}.json"
    with path.open() as fh:
        return json.load(fh)


@cache
def datasets(enabled_only: bool = True) -> dict[str, Dataset]:
    out: dict[str, Dataset] = {}
    for name, spec in registry()["datasets"].items():
        if enabled_only and not spec.get("enabled", False):
            continue
        years_spec = spec.get("years", {})
        years = tuple(range(years_spec["start"], years_spec["end"] + 1)) if years_spec else ()
        out[name] = Dataset(
            name=name,
            label=spec["label"],
            enabled=spec.get("enabled", False),
            file_pattern=spec["file_pattern"],
            dimensions=tuple(spec.get("dimensions", [])),
            years=years,
            preliminary_years=tuple(spec.get("preliminary_years", [])),
            preliminary_file_pattern=spec.get("preliminary_file_pattern"),
            unit=spec.get("unit", "people"),
            excluded_years={int(k): v for k, v in (spec.get("excluded_years") or {}).items()},
        )
    return out


@cache
def geographies(max_phase: int | None = None) -> dict[str, Geography]:
    out: dict[str, Geography] = {}
    for name, spec in registry()["geographies"].items():
        if max_phase is not None and spec.get("phase", 99) > max_phase:
            continue
        out[name] = Geography(
            name=name,
            label=spec["label"],
            phase=spec.get("phase", 99),
            id_field=spec.get("id_field"),
            name_field=spec.get("name_field"),
            tiger_url=spec.get("tiger_url"),
            per_state=spec.get("per_state", False),
            tiger_url_pattern=spec.get("tiger_url_pattern"),
            built_from=spec.get("built_from"),
            derived_from=spec.get("derived_from"),
            source=spec.get("source"),
            constant_id=spec.get("constant_id"),
            constant_name=spec.get("constant_name"),
        )
    return out


def measures() -> dict[str, dict]:
    return registry()["measures"]


def measure_columns() -> list[str]:
    return list(registry()["measures"].keys())


def default_measure() -> str:
    for name, spec in registry()["measures"].items():
        if spec.get("default"):
            return name
    raise ValueError("no default measure declared in the registry")


def source_url(dataset: str, year: int) -> str:
    base = registry()["source"]["base_url"].rstrip("/")
    return f"{base}/{datasets()[dataset].filename(year)}"


def combined_key(dataset: str, geography: str) -> str:
    """S3 key for the all-years file of one (dataset, geography).

    Sits beside the per-year partitions under the same version prefix, using
    "all" where a year would go.
    """
    return f"derived/{DERIVED_VERSION}/{dataset}/{geography}/all/part-00.parquet"


def parse_years(spec: str, dataset: str | None = None) -> list[int]:
    """Parse a year specification into a sorted list.

    Accepts single years, inclusive ranges, and comma-separated combinations:

        "2022"              -> [2022]
        "2000-2024"         -> [2000, 2001, ..., 2024]
        "2018,2020-2022"    -> [2018, 2020, 2021, 2022]
        "all"               -> every year the dataset declares, preliminary included

    Years outside the dataset's declared range are rejected rather than silently
    dropped — a typo in a backfill should fail loudly, not quietly build less
    than asked.
    """
    ds = datasets()[dataset] if dataset else None
    available = set(ds.all_years()) if ds else None

    if spec.strip().lower() == "all":
        if available is None:
            raise ValueError("'all' requires a dataset")
        return sorted(available)

    years: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, _, end = chunk.partition("-")
            try:
                lo, hi = int(start), int(end)
            except ValueError:
                raise ValueError(f"bad year range {chunk!r}; expected e.g. 2000-2024") from None
            if lo > hi:
                raise ValueError(f"range {chunk!r} runs backwards")
            years.update(range(lo, hi + 1))
        else:
            try:
                years.add(int(chunk))
            except ValueError:
                raise ValueError(f"bad year {chunk!r}") from None

    if ds is not None:
        # Excluded years are rejected with their reason, and checked separately
        # from the declared range so that widening `years:` in the registry
        # cannot quietly re-admit a year that was ruled out on purpose.
        excluded = years & set(ds.excluded_years)
        if excluded:
            reasons = "; ".join(f"{y}: {ds.excluded_years[y]}" for y in sorted(excluded))
            raise ValueError(f"{dataset} excludes {sorted(excluded)} — {reasons}")

        unknown = years - available
        if unknown:
            raise ValueError(
                f"{dataset} has no data for {sorted(unknown)}; "
                f"available: {min(available)}-{max(available)}"
            )
    return sorted(years)


def derived_key(dataset: str, geography: str, year: int, part: str = "part-00") -> str:
    """S3 key for a derived partition.

    Every axis is a path segment so adding a year, geography, or dataset writes
    new leaves and never rewrites an existing file.
    """
    return f"derived/{DERIVED_VERSION}/{dataset}/{geography}/{year}/{part}.parquet"
