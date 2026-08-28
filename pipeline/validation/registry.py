"""Check registration and the context a check runs in.

Checks declare themselves with ``@check(...)``. The registry is the single
source of truth for what the report contains and what CI asserts — pytest
parametrises over the same objects the renderer walks, so a check cannot exist
in the document without also being enforced, or vice versa.

Ordering is by id (A1, A2, ... C1), not by import order or definition order, so
the appendix numbering is stable no matter how the modules are refactored.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from .. import config
from ..__version__ import __version__
from .types import Figure, Result, RunMetadata

SECTIONS: dict[str, str] = {
    "A": "Provenance and integrity",
    "B": "Boundaries and geometry",
    "C": "Crosswalk and cell assignment",
    "D": "Numerical reconciliation",
    "E": "External benchmarks",
    "F": "Published claims and delivery",
}

TIER_NAMES: dict[int, str] = {
    0: "Local — registry and configuration only",
    1: "Local artifacts — reads the build tree on disk, no network",
    2: "Published product — reads the published catalog and the Census source files",
    3: "External benchmarks — downloads independent published data",
}


@dataclass
class Context:
    """Everything a check needs to run, and nowhere else to get it from.

    Passing this explicitly rather than reaching for module globals is what
    lets the same check run against a scratch build in a test and the real
    build tree in a report.

    **The published catalog is authoritative, not the local build tree.** The
    site fetches ``catalog.json`` from the CDN at runtime, so what a user
    actually receives is whatever was last published — which can be newer than
    ``.build`` (a CI refresh) or older (an unpublished local rebuild). A report
    that validated ``.build`` would be describing a build nobody is using. Tier
    1 checks read local files where that is the only place a thing exists;
    everything about the data product itself reads the published artifacts.
    """

    out_dir: Path
    build_dir: Path = field(default_factory=lambda: config.REPO_ROOT / ".build")
    cache_dir: Path = field(default_factory=lambda: config.REPO_ROOT / ".cache")
    census_api_key: str | None = field(default_factory=lambda: os.environ.get("CENSUS_API_KEY"))
    catalog_url: str | None = None
    max_tier: int = 3
    # Validate the local build tree instead of the published product. For
    # checking a fix before it goes out — the report states plainly which mode
    # it ran in, because a green report against unpublished artifacts says
    # nothing about what users are currently receiving.
    prefer_local: bool = False
    # False for a --no-pdf run: no document is rendered, so drawing figures
    # is work whose only possible outcome is a failure.
    render_figures: bool = True
    _con: duckdb.DuckDBPyConnection | None = None
    _catalog: dict | None = None

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        """A shared DuckDB connection with httpfs loaded.

        Shared on purpose: httpfs keeps its HTTP connections warm, and a report
        run issues hundreds of range reads against the same handful of hosts.
        """
        if self._con is None:
            self._con = duckdb.connect()
            self._con.execute("INSTALL httpfs; LOAD httpfs;")
        return self._con

    @property
    def figure_dir(self) -> Path:
        d = self.out_dir / "figures"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def figure(self, name: str, caption: str, width: str = r"\textwidth") -> Figure:
        """Declare a figure. The file is written by the check via `figures.py`."""
        return Figure(caption=caption, path=f"figures/{name}.pdf", label=f"fig:{name}", width=width)

    def derived(self, dataset: str, geography: str, year: int) -> Path:
        return self.build_dir / config.derived_key(dataset, geography, year)

    def combined(self, dataset: str, geography: str) -> Path:
        return self.build_dir / config.combined_key(dataset, geography)

    def crosswalk(self, geography: str) -> Path:
        """The cached working crosswalk, which is what aggregation actually joins against."""
        return self.cache_dir / f"xwalk_{geography}.parquet"

    def built_years(self, dataset: str, geography: str) -> list[int]:
        led = self.build_dir / "_ledger" / dataset / geography
        if not led.exists():
            return []
        return sorted(int(p.stem) for p in led.glob("*.json") if p.stem.isdigit())

    # --- the published product -------------------------------------------------

    def catalog(self) -> dict:
        """The live catalog, fetched once per run and cached on disk.

        Cached so a report run is reproducible against a single snapshot: a
        refresh landing mid-run would otherwise leave half the checks
        describing one catalog and half another.
        """
        if self._catalog is None:
            import requests

            url = self.catalog_url or f"{self._base_url()}/catalog.json"
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            self._catalog = resp.json()
            (self.out_dir / "catalog-snapshot.json").write_text(resp.text)
        return self._catalog

    def _base_url(self) -> str:
        """The CDN origin: environment first, then the committed catalog.

        GEIF_BASE_URL is what the pipeline and both workflows already use, so it
        is the authoritative answer wherever it is set. The committed
        ``site/catalog.json`` is only a development convenience and is
        gitignored — which meant a fresh CI checkout had no base URL at all and
        the report's inventory could not be built.
        """
        env = os.environ.get("GEIF_BASE_URL")
        if env:
            return env.rstrip("/")

        local = config.REPO_ROOT / "site" / "catalog.json"
        if local.exists():
            import json as _json

            base = _json.loads(local.read_text()).get("base_url")
            if base:
                return base.rstrip("/")
        raise RuntimeError(
            "no base_url available — set GEIF_BASE_URL or pass --catalog-url"
        )

    def published(self, dataset: str, geography: str, year: int) -> str | None:
        """Where to read a partition from — local build if asked, else published."""
        if self.prefer_local:
            path = self.derived(dataset, geography, year)
            return path.as_posix() if path.exists() else None
        for e in self.catalog().get("entries", []):
            if e["dataset"] == dataset and e["geography"] == geography and e["year"] == year:
                return e["url"]
        return None

    def crosswalk_source(self, geography: str) -> str | None:
        """Where to read a crosswalk from — local build if asked, else published.

        Local resolution prefers the publishable copy in the build tree over
        the working copy in the cache. They should be identical in content, but
        the build tree is what would actually go out, and that is the thing
        worth validating.
        """
        if self.prefer_local:
            for path in (
                self.build_dir / config.crosswalk_key(geography),
                self.crosswalk(geography),
            ):
                if path.exists():
                    return path.as_posix()
            return None
        return (self.catalog().get("crosswalks") or {}).get(geography)

    def crosswalk_geographies(self) -> list[str]:
        if self.prefer_local:
            return sorted(
                g for g in config.geographies() if self.crosswalk_source(g) is not None
            )
        return sorted(self.catalog().get("crosswalks") or {})

    def published_entries(
        self, dataset: str | None = None, geography: str | None = None
    ) -> list[dict]:
        return [
            e
            for e in self.catalog().get("entries", [])
            if (dataset is None or e["dataset"] == dataset)
            and (geography is None or e["geography"] == geography)
        ]

    def published_geographies(self) -> list[str]:
        return sorted({e["geography"] for e in self.catalog().get("entries", [])})

    def published_years(self, dataset: str, geography: str) -> list[int]:
        return sorted(e["year"] for e in self.published_entries(dataset, geography))


@dataclass
class Check:
    """A registered check and the fixed prose that describes it.

    `claim`, `method` and `interpretation` are the entirety of the report's
    narrative for this check. They are authored once here and never computed, so
    the document says the same thing in 2029 as it does today whatever the
    numbers turn out to be.
    """

    id: str
    section: str
    title: str
    tier: int
    claim: str
    method: str
    interpretation: str
    fn: Callable[[Context], Result]

    @property
    def sort_key(self) -> tuple[str, int]:
        m = re.match(r"([A-Z]+)(\d+)", self.id)
        return (m.group(1), int(m.group(2))) if m else (self.id, 0)


_REGISTRY: dict[str, Check] = {}


def check(
    *,
    id: str,
    section: str,
    title: str,
    tier: int,
    claim: str,
    method: str,
    interpretation: str,
):
    """Register a validation check.

    The three prose fields are the whole of what the report says about this
    check, and all three must hold regardless of the outcome:

    `claim` — the assertion under test, written for a reader rather than as a
    description of the code. "The crosswalk covers every populated cell in every
    published year" is right; "checks crosswalk coverage" is not.

    `method` — how it is measured, so a reader can judge whether the measurement
    supports the claim.

    `interpretation` — how to read the result, including what a departure would
    mean and what it would not. This must be written to be true whether the
    check passes or fails, because it is printed either way. If you find
    yourself wanting to write "the loss is concentrated", that belongs in a
    metric or a table, not in a sentence.
    """

    def deco(fn: Callable[[Context], Result]) -> Callable[[Context], Result]:
        if id in _REGISTRY:
            raise ValueError(f"duplicate check id {id!r} — ids are citable and must be unique")
        if section not in SECTIONS:
            raise ValueError(f"unknown section {section!r}")
        _REGISTRY[id] = Check(
            id=id, section=section, title=title, tier=tier,
            claim=claim, method=method, interpretation=interpretation, fn=fn,
        )
        return fn

    return deco


def all_checks() -> list[Check]:
    _load_check_modules()
    return sorted(_REGISTRY.values(), key=lambda c: c.sort_key)


def select(sections: Iterable[str] | None = None, max_tier: int = 3) -> list[Check]:
    wanted = {s.upper() for s in sections} if sections else set(SECTIONS)
    return [c for c in all_checks() if c.section in wanted and c.tier <= max_tier]


def _load_check_modules() -> None:
    """Import every check module so their decorators run.

    Import errors are fatal rather than skipped. A section that silently
    vanishes from the report because of a typo would look exactly like a
    section that passed.
    """
    from . import benchmarks, claims, crosswalk, geometry, provenance, reconcile  # noqa: F401


def run(checks: list[Check], ctx: Context) -> list[Result]:
    """Execute checks, converting an unhandled exception into a failed result.

    A check that raises must not abort the run: a report that stops at the
    first problem tells you about one defect, where the whole point is to
    survey all of them at once.
    """
    from rich.console import Console

    console = Console()
    results: list[Result] = []
    for c in checks:
        t0 = time.perf_counter()
        console.print(f"[dim]{c.id}[/dim] {c.title} …", end="")
        try:
            res = c.fn(ctx)
        except Exception as exc:  # noqa: BLE001 — deliberate: see docstring
            res = Result(
                id=c.id,
                section=c.section,
                title=c.title,
                tier=c.tier,
                status="fail",
                skipped_because=f"{type(exc).__name__}: {exc}",
                error=traceback.format_exc(limit=8),
            )
        # Identity comes from the registration, never from the check body, so a
        # copy-pasted check cannot end up filed under the wrong id or carrying a
        # claim that no longer describes what it tests.
        res.id, res.section, res.title, res.tier = c.id, c.section, c.title, c.tier
        res.claim, res.method, res.interpretation = c.claim, c.method, c.interpretation
        res.runtime_s = time.perf_counter() - t0
        colour = {"pass": "green", "fail": "red", "warn": "yellow", "skip": "dim", "info": "cyan"}[
            res.status
        ]
        console.print(f" [{colour}]{res.status.upper()}[/{colour}] [dim]{res.runtime_s:.1f}s[/dim]")
        results.append(res)
    return results


def metadata(tiers: list[int], sections: list[str], target: str = "published") -> RunMetadata:
    commit, dirty = _git_state()
    return RunMetadata(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        commit=commit,
        commit_dirty=dirty,
        pipeline_version=__version__,
        registry_version=str(config.registry()["registry_version"]),
        contract_version=config.contract()["contract_version"],
        derived_version=config.DERIVED_VERSION,
        python_version=sys.version.split()[0],
        duckdb_version=duckdb.__version__,
        platform=f"{sys.platform}",
        tiers_run=tiers,
        sections_run=sections,
        target=target,
    )


def _git_state() -> tuple[str, bool]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=config.REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    try:
        return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown", False
