"""Command-line interface.

    geif validate  --dataset ageracesex --year 2022
    geif crosswalk --geography county
    geif build     --geography county --year 2022
    geif catalog   --base-url https://d2l6ob0rkxsi9o.cloudfront.net
    geif publish   --bucket eil-gridded-eif-data
    geif refresh   --year 2024          # the annual one-command path
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from . import aggregate, config, crosswalk, validate
from . import boundaries as boundaries_mod
from . import catalog as catalog_mod
from . import publish as publish_mod

app = typer.Typer(add_completion=False, help="Gridded EIF data pipeline")
console = Console()
BUILD_DIR = config.REPO_ROOT / ".build"


@app.command()
def datasets() -> None:
    """List datasets and geographies known to the registry."""
    t = Table(title="Datasets")
    t.add_column("name"); t.add_column("label"); t.add_column("years"); t.add_column("dimensions")
    for ds in config.datasets().values():
        yrs = f"{min(ds.years)}-{max(ds.years)}"
        if ds.preliminary_years:
            yrs += f" (+{', '.join(map(str, ds.preliminary_years))} prelim)"
        t.add_row(ds.name, ds.label, yrs, ", ".join(ds.dimensions))
    console.print(t)

    g = Table(title="Geographies")
    g.add_column("name"); g.add_column("label"); g.add_column("phase"); g.add_column("units")
    for geo in config.geographies().values():
        spec = config.registry()["geographies"][geo.name]
        g.add_row(geo.name, geo.label, str(geo.phase), f"{spec.get('approx_units', '?'):,}"
                  if isinstance(spec.get("approx_units"), int) else "?")
    console.print(g)


@app.command()
def validate_source(
    dataset: str = typer.Option(..., "--dataset"),
    year: str = typer.Option(..., "--year", help="Year, range, or list. See `build`."),
    invariants: bool = typer.Option(True, help="Also check statistical invariants (slower)"),
) -> None:
    """Check source files against the pinned schema contract.

    Goes through the same year resolution as `build`, so excluded years are
    rejected here too rather than leaving a side door open.
    """
    for y in config.parse_years(year, dataset):
        rep = validate.validate_source(dataset, y)
        for w in rep.warnings:
            console.print(f"[yellow]{dataset} {y} warning:[/yellow] {w}")
        rep.raise_if_failed()
        console.print(f"[green]{dataset} {y} schema OK[/green] — {rep.rows:,} rows")

        if invariants:
            inv = validate.check_invariants(dataset, y)
            inv.raise_if_failed()
            console.print(f"[green]{dataset} {y} invariants OK[/green] — total {inv.rows:,}")


@app.command()
def build_crosswalk(
    geography: str = typer.Option("county", "--geography"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Build the grid-to-geography crosswalk."""
    crosswalk.build(geography, force=force)


@app.command()
def build(
    geography: str = typer.Option("county", "--geography", help="Comma-separated levels"),
    year: str = typer.Option(
        ...,
        "--year",
        help="Year, range, or list: 2022 | 2000-2024 | 2018,2020-2022 | all",
    ),
    dataset: str = typer.Option(None, "--dataset", help="Default: all enabled datasets"),
    skip_validation: bool = typer.Option(False, "--skip-validation"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Aggregate one or more years to one or more geography levels."""
    names = dataset.split(",") if dataset else list(config.datasets())
    levels = [g.strip() for g in geography.split(",") if g.strip()]

    # Resolve every year up front so a typo fails before any work is done,
    # rather than twenty minutes into a backfill.
    plan: list[tuple[str, str, int]] = []
    for level in levels:
        for name in names:
            for y in config.parse_years(year, name):
                plan.append((name, level, y))

    if len(plan) > 1:
        console.print(
            f"[bold]{len(plan)} partitions[/bold]: {', '.join(levels)} × "
            f"{', '.join(names)} × {len(config.parse_years(year, names[0]))} years"
        )

    crosswalks = {level: crosswalk.build(level) for level in levels}

    for i, (name, level, y) in enumerate(plan, 1):
        prefix = f"[dim][{i}/{len(plan)}][/dim] " if len(plan) > 1 else ""
        console.print(f"{prefix}", end="")
        if not skip_validation:
            validate.validate_source(name, y).raise_if_failed()
        aggregate.build(name, level, y, crosswalks[level], force=force)


@app.command()
def combine(
    geography: str = typer.Option(None, "--geography", help="Default: every level built"),
    dataset: str = typer.Option(None, "--dataset", help="Default: all enabled datasets"),
    base_url: str = typer.Option(None, "--base-url", envvar="GEIF_BASE_URL"),
) -> None:
    """Build all-years files from the per-year partitions already on disk.

    Cheap — reads local Parquet, never the source data.
    """
    names = dataset.split(",") if dataset else list(config.datasets())
    if geography:
        levels = [g.strip() for g in geography.split(",")]
    else:
        led = BUILD_DIR / "_ledger"
        levels = sorted({p.parent.name for p in led.rglob("*.json") if p.parent.name != "_combined"})
    # Pull the published catalog so years not rebuilt in this run are included
    # from the CDN rather than silently dropped.
    published = catalog_mod.fetch_published(base_url) if base_url else None
    for name in names:
        for level in levels:
            aggregate.combine(name, level, published=published)


@app.command()
def names(
    geography: str = typer.Option(None, "--geography", help="Default: every level built"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Build geo_id -> display-name lookups so places are searchable by name."""
    if geography:
        levels = [g.strip() for g in geography.split(",")]
    else:
        led = BUILD_DIR / "_ledger"
        levels = sorted({p.parent.name for p in led.rglob("*.json") if p.parent.name != "_combined"})
    for level in levels:
        src = crosswalk.build_names(level, force=force)
        dest = BUILD_DIR / config.names_key(level)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text())


@app.command()
def boundaries(
    geography: str = typer.Option(None, "--geography", help="Default: every level built"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Build simplified boundary GeoJSON for the map."""
    if geography:
        levels = [g.strip() for g in geography.split(",")]
    else:
        led = BUILD_DIR / "_ledger"
        levels = sorted({p.parent.name for p in led.rglob("*.json") if p.parent.name != "_combined"})
    for level in levels:
        src = boundaries_mod.build(level, force=force)
        dest = BUILD_DIR / config.boundaries_key(level)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text())


@app.command()
def catalog(
    base_url: str = typer.Option(..., "--base-url", envvar="GEIF_BASE_URL"),
    merge_published: bool = typer.Option(
        True,
        help="Merge with the currently published catalog. Keep this ON in CI, where "
             "the local build directory holds only the partitions built this run.",
    ),
) -> None:
    """Regenerate catalog.json, preserving partitions built elsewhere."""
    parts = []
    for led in sorted((BUILD_DIR / "_ledger").rglob("*.json")):
        if "_combined" in led.parts:      # those are Combined, not Partition
            continue
        parts.append(aggregate.Partition(**json.loads(led.read_text())))
    if not parts:
        raise typer.BadParameter("nothing built yet — run `geif build` first")

    combined = []
    combined_dir = BUILD_DIR / "_ledger" / "_combined"
    if combined_dir.exists():
        for led in sorted(combined_dir.glob("*.json")):
            combined.append(aggregate.Combined(**json.loads(led.read_text())))

    published = catalog_mod.fetch_published(base_url) if merge_published else None
    cat = catalog_mod.build(parts, base_url, merge_with=published, combined=combined)
    path = catalog_mod.write(cat, BUILD_DIR / catalog_mod.CATALOG_FILENAME)

    carried = len(cat["entries"]) - len(parts)
    console.print(
        f"[green]{path.name}[/green]: {len(cat['entries'])} partitions "
        f"({len(parts)} built here"
        + (f", {carried} carried from the published catalog" if carried > 0 else "")
        + f"), {len(cat['combined'])} all-years files, "
        f"{len(cat['datasets'])} datasets, {path.stat().st_size / 1024:.1f} KB"
    )


@app.command()
def publish(
    bucket: str = typer.Option(..., "--bucket", envvar="GEIF_BUCKET"),
    distribution_id: str = typer.Option(None, "--distribution-id", envvar="GEIF_DISTRIBUTION_ID"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Upload built artifacts to S3 and invalidate the catalog."""
    keys = publish_mod.publish(bucket, BUILD_DIR, distribution_id, dry_run)
    console.print(f"[green]{len(keys)} objects[/green]{' (dry run)' if dry_run else ''}")


@app.command()
def refresh(
    year: str = typer.Option(..., "--year", help="Year, range, or list. See `build`."),
    geography: str = typer.Option("county", "--geography"),
    base_url: str = typer.Option(..., "--base-url", envvar="GEIF_BASE_URL"),
    bucket: str = typer.Option(None, "--bucket", envvar="GEIF_BUCKET"),
    distribution_id: str = typer.Option(None, "--distribution-id", envvar="GEIF_DISTRIBUTION_ID"),
    skip_validation: bool = typer.Option(False, "--skip-validation"),
) -> None:
    """The annual path: validate, build, catalog, publish — one command.

    Catalog and publish run once at the end. If a year fails mid-run nothing is
    published, so the CDN never serves a half-finished refresh; re-run the
    failing subrange and the catalog merge folds it in alongside what is already
    live.
    """
    build(
        geography=geography,
        year=year,
        dataset=None,
        skip_validation=skip_validation,
        force=False,
    )
    names(geography=geography)
    combine(geography=geography, dataset=None, base_url=base_url)
    catalog(base_url=base_url, merge_published=True)
    if bucket:
        publish(bucket=bucket, distribution_id=distribution_id, dry_run=False)


if __name__ == "__main__":
    app()
