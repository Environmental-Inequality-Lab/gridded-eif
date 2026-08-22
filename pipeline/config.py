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
    complete_coverage: bool
    state_prefixed: bool
    crosswalk_url: str | None
    crosswalk_key_field: str | None
    crosswalk_value_field: str | None
    crosswalk_name_field: str | None


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
def geographies(max_phase: int | None = None, include_disabled: bool = False) -> dict[str, Geography]:
    """Geography levels this pipeline will build.

    `enabled: false` in the registry excludes a level entirely — it was
    previously ignored here, so disabling something silently did nothing. Pass
    `include_disabled` only to inspect the full declared set; the raw registry
    is still reachable via `registry()["geographies"]`.
    """
    out: dict[str, Geography] = {}
    for name, spec in registry()["geographies"].items():
        if max_phase is not None and spec.get("phase", 99) > max_phase:
            continue
        if not include_disabled and spec.get("enabled", True) is False:
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
            # Most geographies tile the country; those that do not must not have
            # unmatched cells snapped into them.
            complete_coverage=spec.get("complete_coverage", True),
            state_prefixed=spec.get("state_prefixed", False),
            crosswalk_url=spec.get("crosswalk_url"),
            crosswalk_key_field=spec.get("crosswalk_key_field"),
            crosswalk_value_field=spec.get("crosswalk_value_field"),
            crosswalk_name_field=spec.get("crosswalk_name_field"),
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


def crosswalk_key(geography: str) -> str:
    """S3 key for a published grid-cell to geography crosswalk.

    Publishing these is the point of the project stated plainly: the expensive,
    fiddly part of using the Gridded EIF is the spatial join, and a crosswalk
    lets anyone reuse ours — for the pollution and weather files we do not
    serve, or for geographies we do not offer.
    """
    return f"derived/{DERIVED_VERSION}/_crosswalks/{geography}.parquet"


def boundaries_key(geography: str) -> str:
    """S3 key for a geography's simplified GeoJSON.

    Version-prefixed alongside the data. Boundaries carry only `geo_id`, never
    values, so geometry and data update independently.
    """
    return f"derived/{DERIVED_VERSION}/_boundaries/{geography}.geojson"


def names_key(geography: str) -> str:
    """S3 key for a geography's id -> name lookup. Version-prefixed with the
    rest of the derived data, since names follow a TIGER boundary vintage."""
    return f"derived/{DERIVED_VERSION}/_names/{geography}.json"


class GeographyDisabled(Exception):
    """Raised when a deliberately disabled geography level is requested."""


def resolve_geography(name: str) -> Geography:
    """Look up a level, refusing disabled ones with the reason attached.

    Without this a disabled level surfaces as a bare KeyError, which reads like
    a typo rather than a decision and invites someone to just re-enable it.
    """
    geos = geographies()
    if name in geos:
        return geos[name]

    spec = registry()["geographies"].get(name)
    if spec is None:
        raise GeographyDisabled(
            f"Unknown geography {name!r}. Available: {', '.join(geos)}"
        )
    reason = spec.get("disabled_reason", "No reason recorded.")
    raise GeographyDisabled(
        f"{name!r} is disabled deliberately, not missing.\n\n{reason}\n\n"
        f"Re-enabling it means setting `enabled: true` in catalog/variables.yaml "
        f"and having new evidence that the objection no longer holds."
    )


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
