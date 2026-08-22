"""Builds catalog.json — the runtime manifest.

This file is FETCHED BY THE SITE AT RUNTIME, never bundled into the JS build.
That single property is what lets a data refresh be "run the pipeline, upload"
with no site rebuild, no redeploy, and no cache purge.

Consequences to preserve:
  - The site must tolerate a catalog listing datasets or years its UI code
    predates. Unknown entries are rendered from the registry metadata carried
    here, not from hardcoded component logic.
  - Every entry carries the pipeline version and sha256 that produced it, so a
    published number is traceable to an exact build.
  - Cache-Control on this object must be SHORT (see publish.py); everything it
    points at is immutable and cached forever.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import requests
from rich.console import Console

from . import config
from .__version__ import __version__
from .aggregate import Partition

CATALOG_FILENAME = "catalog.json"
console = Console()


def fetch_published(base_url: str, timeout: int = 30) -> dict | None:
    """Fetch the currently published catalog, if any.

    Required for correctness in CI. A GitHub runner starts with an empty
    ``.build/_ledger``, so a job that rebuilds one year knows about only that
    year. Without merging, publishing would overwrite a catalog describing every
    year with one describing a single year — the Parquet would still be in S3 but
    the site, which reads only the catalog, would stop seeing it.
    """
    url = f"{base_url.rstrip('/')}/{CATALOG_FILENAME}"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        console.print(f"[yellow]could not fetch published catalog ({exc}); building fresh[/yellow]")
        return None
    if resp.status_code == 200:
        return resp.json()
    # OAC grants only s3:GetObject, so a missing object is 403 rather than 404.
    if resp.status_code in (403, 404):
        console.print("[dim]no published catalog yet; building fresh[/dim]")
        return None
    console.print(f"[yellow]published catalog returned {resp.status_code}; building fresh[/yellow]")
    return None


def _merge_combined(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Union of published and freshly built all-years files, newest winning."""
    def key(e):
        return (e["dataset"], e["geography"])

    merged = {key(e): e for e in existing}
    merged.update({key(e): e for e in fresh})
    return sorted(merged.values(), key=key)


def _merge_entries(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Union of published and newly built partitions, newest build winning."""
    def key(e):
        return (e["dataset"], e["geography"], e["year"])

    merged = {key(e): e for e in existing}
    merged.update({key(e): e for e in fresh})
    return sorted(merged.values(), key=key)


def build(
    partitions: list[Partition],
    base_url: str,
    merge_with: dict | None = None,
    combined: list | None = None,
) -> dict:
    reg = config.registry()

    fresh = [
        {
            "dataset": p.dataset,
            "geography": p.geography,
            "year": p.year,
            "url": f"{base_url.rstrip('/')}/{p.path}",
            "rows": p.rows,
            "bytes": p.bytes,
            "sha256": p.sha256,
            "geo_units": p.geo_units,
            "preliminary": p.preliminary,
            "pipeline_version": p.pipeline_version,
            "totals": {
                "n_noise": round(p.total_raw, 1),
                "n_noise_postprocessed": round(p.total_postprocessed, 1),
            },
        }
        for p in sorted(partitions, key=lambda x: (x.dataset, x.geography, x.year))
    ]
    entries = _merge_entries(merge_with.get("entries", []) if merge_with else [], fresh)

    datasets: dict[str, dict] = {}
    for ds in config.datasets().values():
        mine = [e for e in entries if e["dataset"] == ds.name]
        if not mine:
            continue
        datasets[ds.name] = {
            "label": ds.label,
            "unit": ds.unit,
            "dimensions": list(ds.dimensions),
            "not_joinable_with": reg["datasets"][ds.name].get("not_joinable_with", []),
            "years": sorted({e["year"] for e in mine if not e["preliminary"]}),
            "preliminary_years": sorted({e["year"] for e in mine if e["preliminary"]}),
            "geographies": sorted({e["geography"] for e in mine}),
        }

    fresh_combined = [
        {
            "dataset": c.dataset,
            "geography": c.geography,
            "url": f"{base_url.rstrip('/')}/{c.path}",
            "years": c.years,
            "rows": c.rows,
            "bytes": c.bytes,
            "sha256": c.sha256,
            "pipeline_version": c.pipeline_version,
        }
        for c in (combined or [])
    ]
    combined_entries = _merge_combined(
        (merge_with or {}).get("combined", []), fresh_combined
    )

    return {
        "catalog_version": "1.1.0",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pipeline_version": __version__,
        "registry_version": reg["registry_version"],
        "derived_version": config.DERIVED_VERSION,
        "base_url": base_url.rstrip("/"),
        "source": {
            "citation": reg["source"]["citation"].strip(),
            "landing_page": reg["source"]["landing_page"],
            "base_url": reg["source"]["base_url"],
            "data_version": reg["source"]["data_version"],
            "experimental": reg["source"]["experimental"],
        },
        "grid": reg["grid"],
        # Registry metadata the UI renders from. Without these the site cannot
        # label a facet, offer a geography, or explain a measure — it would have
        # to hardcode them, which is the exact coupling this design avoids.
        "measures": reg["measures"],
        "measure_selection_population_threshold": reg["measure_selection_population_threshold"],
        "dimensions": reg["dimensions"],
        "geographies": {
            name: {
                "label": spec["label"],
                "approx_units": spec.get("approx_units"),
                "caveat": spec.get("caveat"),
                # False where the geography does not tile the country, so the
                # UI can explain why its totals fall short of the national one.
                "complete_coverage": spec.get("complete_coverage", True),
            }
            for name, spec in reg["geographies"].items()
            if name in {e["geography"] for e in entries}
        },
        # geo_id -> display name, one file per geography. Small and
        # year-independent, so kept out of the yearly partitions.
        "names": {
            g: f"{base_url.rstrip('/')}/{config.names_key(g)}"
            for g in sorted({e["geography"] for e in entries})
        },
        # Simplified geometry for the map. Carries geo_id only — the site joins
        # values at render time, so geometry never rebuilds for new data.
        "boundaries": {
            g: f"{base_url.rstrip('/')}/{config.boundaries_key(g)}"
            for g in sorted({e["geography"] for e in entries})
            if reg["geographies"].get(g, {}).get("map", True) is not False
        },
        "datasets": datasets,
        "aggregation": reg["aggregation"],
        # Per-year partitions: the right shape for single-year queries and bulk
        # download, and the unit the pipeline builds incrementally.
        "entries": entries,
        # All-years files: one per (dataset, geography). Multi-year query
        # latency is dominated by per-file round trips rather than bytes — a
        # 25-year national series reads 66 KB across 25 files and takes ~5s in a
        # browser. Clients doing a time series should read these instead.
        "combined": combined_entries,
    }


def write(catalog: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2))
    return path
