"""Grid cell to geography crosswalks.

Built once per geography level and cached, since the grid is fixed and TIGER
boundaries change rarely. Generic over TIGER/Line: adding a level is a registry
block plus a shapefile URL, not new code.

Assignment is point-in-polygon on the cell centroid, with unmatched populated
cells snapped to the nearest polygon. The snap is required, not cosmetic — see
222 cells holding 14,214 people fall outside every county polygon because
they straddle the US-Mexico border and their centroids land in Mexico. They
cluster in Calexico, El Paso, and Laredo, so dropping them would systematically
undercount border communities.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import requests
from rich.console import Console

from . import config

console = Console()
CACHE = config.REPO_ROOT / ".cache"
BUILD_DIR_FOR_PUBLISH = config.REPO_ROOT / ".build"
GRID_CRS = "EPSG:4326"


def build(geography: str, force: bool = False) -> Path:
    """Build (or reuse) the crosswalk for one geography level."""
    CACHE.mkdir(exist_ok=True)
    out = CACHE / f"xwalk_{geography}.parquet"
    if out.exists() and not force:
        console.print(f"[dim]crosswalk {geography}: cached[/dim]")
        return out

    geo = config.geographies()[geography]
    cells = _cell_union()
    console.print(f"crosswalk {geography}: {len(cells):,} grid cells")

    if geo.built_from:
        return _build_from_parent(geography, geo, out)

    if geo.source == "constant":
        # No spatial work: every cell belongs to the single unit by definition.
        result = pd.DataFrame({
            "grid_lon": cells.grid_lon.values,
            "grid_lat": cells.grid_lat.values,
            "geo_id": geo.constant_id,
            "snapped": False,
        })
        result.to_parquet(out, index=False, compression="zstd")
        console.print(
            f"[green]crosswalk {geography}: {len(result):,} cells -> "
            f"{geo.constant_id}[/green]"
        )
        return out

    shapes = _load_boundaries(geo)
    console.print(f"crosswalk {geography}: {len(shapes):,} polygons")

    pts = gpd.GeoDataFrame(
        cells,
        geometry=gpd.points_from_xy(
            cells.grid_lon.astype(float), cells.grid_lat.astype(float)
        ),
        crs=GRID_CRS,
    ).to_crs(shapes.crs)

    joined = gpd.sjoin(pts, shapes, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]  # cells on a shared edge

    unmatched = joined[joined["_geo_id"].isna()]
    snap = geo.complete_coverage and config.registry()["aggregation"]["snap_unmatched_to_nearest"]
    if len(unmatched) and not snap:
        console.print(
            f"[dim]crosswalk {geography}: {len(unmatched):,} cells outside any unit, "
            f"dropped (partial-coverage geography)[/dim]"
        )
    if len(unmatched) and snap:
        console.print(
            f"[yellow]crosswalk {geography}: {len(unmatched):,} unmatched, "
            f"snapping to nearest polygon[/yellow]"
        )
        # Nearest-neighbour distance must be computed in a PROJECTED CRS. In
        # degrees, a longitude degree is ~85 km at the Mexican border and ~40 km
        # in Alaska, so "nearest" in degree-space can pick the wrong polygon.
        # EPSG:5070 (CONUS Albers Equal Area) is accurate across the lower 48
        # and adequate for a sub-25 km snap in AK/HI.
        metric = config.registry()["aggregation"]["snap_max_distance_m"]
        snapped = gpd.sjoin_nearest(
            pts.loc[unmatched.index].to_crs("EPSG:5070"),
            shapes.to_crs("EPSG:5070"),
            how="left",
            max_distance=metric,
        )
        snapped = snapped[~snapped.index.duplicated(keep="first")]
        joined.loc[snapped.index, "_geo_id"] = snapped["_geo_id"]
        joined.loc[snapped.index, "_geo_name"] = snapped["_geo_name"]
        joined.loc[snapped.index, "_snapped"] = True

    still = int(joined["_geo_id"].isna().sum())
    matched = len(joined) - still
    pct = 100 * matched / len(joined)
    # A complete-coverage geography that loses cells is a bug; a partial one
    # losing them is expected and worth stating plainly either way.
    colour = "red" if (geo.complete_coverage and still) else "dim"
    console.print(
        f"crosswalk {geography}: matched {matched:,}/{len(joined):,} ({pct:.3f}%)"
        + (f", [{colour}]{still:,} outside any unit[/{colour}]" if still else "")
    )

    result = pd.DataFrame({
        "grid_lon": joined["grid_lon"].values,
        "grid_lat": joined["grid_lat"].values,
        "geo_id": joined["_geo_id"].values,
        "snapped": joined.get("_snapped", pd.Series(False, index=joined.index)).fillna(False).values,
    })
    result = result[result.geo_id.notna()]
    result.to_parquet(out, index=False, compression="zstd")
    console.print(f"[green]crosswalk {geography}: wrote {out.name}[/green]")
    return out


def names(geography: str) -> pd.DataFrame:
    """Geography id to display name lookup, for the UI's place picker."""
    geo = config.geographies()[geography]
    if geo.source == "constant":
        return pd.DataFrame({"geo_id": [geo.constant_id], "name": [geo.constant_name]})
    shapes = _load_boundaries(geo)
    return pd.DataFrame({
        "geo_id": shapes["_geo_id"].values,
        "name": shapes["_geo_name"].values,
    }).drop_duplicates("geo_id")


def _cell_union(force: bool = False) -> pd.DataFrame:
    """Every grid cell populated in ANY published dataset-year.

    Deliberately NOT from eif_grid_topology.rda, which is CONUS-only and would
    silently drop Alaska and Hawaii — 1.45M people.

    Deliberately NOT from a single reference year either. That is what this
    used to do, and it was wrong: the grid is fixed but the *populated* subset
    of it is not. Cells appear and disappear as administrative-records coverage
    changes and as people move, so a crosswalk built from one year cannot
    assign the cells another year has. Aggregation inner-joins against the
    crosswalk, so every such cell was silently dropped along with its
    population — between 0.05% and 0.43% of every published year except the
    reference year itself, where the loss was necessarily zero and no test
    could see it. See validation checks C1 and C6.

    Scanning all published source files costs one pass over two columns. The
    result is cached because it is the same for every geography level.

    NOTE: this covers the datasets this pipeline publishes. The pollutant and
    extreme-weather grids are not included — they are not enabled in the
    registry and their cell coverage differs again. Enabling them must extend
    this union, or the published crosswalk will understate its own coverage for
    exactly the use the site recommends it for.
    """
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / "grid_cells_union.parquet"
    if cached.exists() and not force:
        return pd.read_parquet(cached)

    sources = [
        config.source_url(ds.name, year)
        for ds in config.datasets().values()
        for year in ds.all_years()
    ]
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    console.print(f"[dim]grid cells: scanning {len(sources)} source files for the union[/dim]")
    cells = con.execute(
        f"SELECT DISTINCT grid_lon, grid_lat FROM read_parquet({sources!r})"
    ).df()
    cells.to_parquet(cached, index=False, compression="zstd")
    console.print(f"[green]grid cells: {len(cells):,} distinct across all published years[/green]")
    return cells


def _load_boundaries(geo: config.Geography, keep_extra: bool = False) -> gpd.GeoDataFrame:
    """Fetch and normalize a TIGER/Line layer to _geo_id / _geo_name / geometry."""
    if geo.per_state:
        gdf = _load_per_state(geo, keep_extra=keep_extra)
        return _select_columns(gdf, geo, keep_extra)
    if not geo.tiger_url:
        raise NotImplementedError(f"{geo.name} is not TIGER-backed (built_from={geo.built_from})")

    local = _download(geo.tiger_url, CACHE / f"tiger_{geo.name}")
    shp = next(local.glob("*.shp"))
    gdf = gpd.read_file(shp)
    return _select_columns(gdf, geo, keep_extra)


def _select_columns(gdf, geo: config.Geography, keep_extra: bool) -> gpd.GeoDataFrame:
    # ZCTAs have no name distinct from their code, so id_field and name_field
    # are the same column. Keyed by source column, that collapses to a single
    # entry and _geo_id is never produced — so copy instead of renaming.
    if geo.id_field == geo.name_field:
        out = gdf[[geo.id_field, "geometry"]].rename(columns={geo.id_field: "_geo_id"})
        out["_geo_name"] = out["_geo_id"]
        return gpd.GeoDataFrame(out, geometry="geometry", crs=gdf.crs)

    cols = {geo.id_field: "_geo_id", geo.name_field: "_geo_name"}
    if keep_extra:
        # Fields the name builder needs but the spatial join does not.
        for src, dst in (("NAMELSAD", "_namelsad"), ("NAMELSAD20", "_namelsad"),
                         ("STUSPS", "_stusps")):
            if src in gdf.columns and dst not in cols.values():
                cols[src] = dst
    return gdf[[*cols, "geometry"]].rename(columns=cols)


def build_names(geography: str, force: bool = False) -> Path:
    """Write a geo_id -> display name lookup for one geography level.

    The site needs real names to be searchable: a county picker listing "26163"
    is unusable, and a search box cannot match "Wayne" against a FIPS code.
    Names live in their own small file rather than being repeated in every
    yearly partition, since they do not vary by year.

    Kept under the derived version prefix because names are tied to a TIGER
    vintage — a boundary change should publish alongside, not overwrite.
    """
    CACHE.mkdir(exist_ok=True)
    out = CACHE / f"names_{geography}.json"
    if out.exists() and not force:
        return out

    geo = config.geographies()[geography]
    if geo.source == "constant":
        out.write_text(json.dumps({geo.constant_id: geo.constant_name}))
        console.print(f"[green]names {geography}: 1 entry[/green]")
        return out

    if geo.built_from:
        _, labels = _load_id_crosswalk(geo)
        out.write_text(json.dumps(labels, sort_keys=True))
        console.print(f"[green]names {geography}: {len(labels):,} entries[/green]")
        return out

    # Restrict to units that actually carry data. TIGER includes Puerto Rico,
    # the USVI, Guam, American Samoa, and the Northern Marianas, none of which
    # the source data covers — listing them would offer a searchable place that
    # returns nothing.
    with_data = None
    xwalk = CACHE / f"xwalk_{geography}.parquet"
    if xwalk.exists():
        with_data = set(
            duckdb.connect()
            .execute(f"SELECT DISTINCT geo_id FROM read_parquet('{xwalk.as_posix()}')")
            .df()["geo_id"]
        )

    shapes = _load_boundaries(geo, keep_extra=True)
    if with_data is not None:
        shapes = shapes[shapes["_geo_id"].isin(with_data)]
    labels = {}
    if geography == "state":
        for _, r in shapes.iterrows():
            labels[r["_geo_id"]] = r["_geo_name"]
    elif geo.state_prefixed:
        # "Wayne County, MI" — the form people search for. NAMELSAD carries the
        # unit type ("County", "Parish", "Borough"), which matters outside the
        # lower 48. The state suffix disambiguates the 30-odd Wayne Counties.
        abbr = _state_abbreviations()
        for _, r in shapes.iterrows():
            st = abbr.get(str(r["_geo_id"])[:2], "")
            full = r.get("_namelsad") or r["_geo_name"]
            labels[r["_geo_id"]] = f"{full}, {st}" if st else full
    else:
        for _, r in shapes.iterrows():
            labels[r["_geo_id"]] = r.get("_namelsad") or r["_geo_name"]

    out.write_text(json.dumps(labels, sort_keys=True))
    console.print(f"[green]names {geography}: {len(labels):,} entries[/green]")
    return out


def _state_abbreviations() -> dict[str, str]:
    geo = config.geographies().get("state")
    if not geo or not geo.tiger_url:
        return {}
    shapes = _load_boundaries(geo, keep_extra=True)
    return dict(zip(shapes["_geo_id"], shapes.get("_stusps", shapes["_geo_name"])))


def _download(url: str, dest: Path) -> Path:
    """Fetch and unpack a TIGER archive, cached on disk."""
    CACHE.mkdir(exist_ok=True)
    if dest.exists() and any(dest.glob("*.shp")):
        return dest
    console.print(f"[dim]downloading {url.rsplit('/', 1)[-1]}[/dim]")
    resp = requests.get(url, timeout=1800)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(dest)
    return dest


def _states_with_data() -> list[str]:
    """State FIPS codes that carry data, from the state crosswalk.

    Restricting to these avoids downloading shapefiles for territories the
    source data does not cover — 5 fewer archives per per-state geography.
    """
    xwalk = CACHE / "xwalk_state.parquet"
    if not xwalk.exists():
        build("state")
    ids = (
        duckdb.connect()
        .execute(f"SELECT DISTINCT geo_id FROM read_parquet('{xwalk.as_posix()}') ORDER BY 1")
        .df()["geo_id"]
    )
    return [str(x) for x in ids]


def _load_per_state(geo: config.Geography, keep_extra: bool = False) -> gpd.GeoDataFrame:
    """Concatenate a geography that TIGER publishes one file per state.

    Tract, PUMA, and congressional district are all shipped this way. Fetching
    only the states that have data keeps this to ~51 small archives rather than
    the full national set including territories.
    """
    frames = []
    states = _states_with_data()
    console.print(f"[dim]{geo.name}: fetching {len(states)} state files[/dim]")
    for fips in states:
        url = geo.tiger_url_pattern.format(state_fips=fips)
        try:
            local = _download(url, CACHE / f"tiger_{geo.name}" / fips)
        except requests.HTTPError as exc:
            # Some states have no units for some geographies (e.g. a state with
            # a single at-large district may still publish, but not always).
            console.print(f"[yellow]{geo.name} {fips}: {exc.response.status_code}, skipped[/yellow]")
            continue
        shp = next(local.glob("*.shp"), None)
        if shp:
            frames.append(gpd.read_file(shp))
    if not frames:
        raise RuntimeError(f"{geo.name}: no shapefiles could be loaded")
    gdf = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs=frames[0].crs)


def _load_id_crosswalk(geo: config.Geography) -> tuple[dict[str, str], dict[str, str]]:
    """Fetch a parent-id -> child-id mapping, plus child-id -> name."""
    CACHE.mkdir(exist_ok=True)
    local = CACHE / f"xw_src_{geo.name}.csv"
    if not local.exists():
        console.print(f"[dim]downloading {geo.crosswalk_url.rsplit('/', 1)[-1]}[/dim]")
        resp = requests.get(geo.crosswalk_url, timeout=600)
        resp.raise_for_status()
        local.write_bytes(resp.content)

    df = pd.read_csv(local, dtype={geo.crosswalk_key_field: str})
    # Zero-pad so ids sort correctly as strings and stay stable in URLs.
    width = len(str(int(df[geo.crosswalk_value_field].max())))
    def to_id(v):
        return str(int(v)).zfill(width)

    mapping = {
        str(r[geo.crosswalk_key_field]): to_id(r[geo.crosswalk_value_field])
        for _, r in df.iterrows()
    }
    names = {}
    if geo.crosswalk_name_field and geo.crosswalk_name_field in df.columns:
        names = {
            to_id(r[geo.crosswalk_value_field]): str(r[geo.crosswalk_name_field])
            for _, r in df.iterrows()
        }
    return mapping, names


def _build_from_parent(geography: str, geo: config.Geography, out: Path) -> Path:
    """Derive a crosswalk by remapping a parent geography's ids.

    Commuting zones group whole counties, so no spatial join is needed — the
    county crosswalk already assigns every cell, and each county belongs to
    exactly one CZ. Deriving rather than re-joining also guarantees the two
    levels stay consistent: a CZ total is exactly the sum of its counties.
    """
    parent_path = build(geo.built_from)
    mapping, _ = _load_id_crosswalk(geo)

    con = duckdb.connect()
    parent = con.execute(f"SELECT * FROM read_parquet('{parent_path.as_posix()}')").df()
    parent["geo_id"] = parent["geo_id"].astype(str).map(mapping)

    unmapped = int(parent["geo_id"].isna().sum())
    if unmapped:
        # A parent unit missing from the crosswalk would silently drop its
        # population, so fail rather than publish a quietly short total.
        raise ValueError(
            f"{geography}: {unmapped:,} cells have a {geo.built_from} with no "
            f"mapping in {geo.crosswalk_url}. Refusing to publish a partial crosswalk."
        )

    parent.to_parquet(out, index=False, compression="zstd")
    console.print(
        f"[green]crosswalk {geography}: {len(parent):,} cells -> "
        f"{parent.geo_id.nunique():,} units (derived from {geo.built_from})[/green]"
    )
    return out


def publish_copy(geography: str) -> Path:
    """Rewrite a cached crosswalk into the publishable build tree.

    Kept separate from `build` so the published file can carry documentation
    columns that the internal join does not need. The `snapped` flag travels
    with it: a user aggregating their own data should be able to see which
    cells were reassigned from outside the geography and decide for themselves.
    """
    src = build(geography)
    dest = BUILD_DIR_FOR_PUBLISH / config.crosswalk_key(geography)
    dest.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT grid_lon, grid_lat, geo_id, snapped
            FROM read_parquet('{src.as_posix()}')
            ORDER BY geo_id, grid_lon, grid_lat
        ) TO '{dest.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
    """)
    rows, units, snapped = con.execute(f"""
        SELECT count(*), count(DISTINCT geo_id), sum(CASE WHEN snapped THEN 1 ELSE 0 END)
        FROM read_parquet('{dest.as_posix()}')
    """).fetchone()
    console.print(
        f"[green]crosswalk {geography}[/green]: {rows:,} cells -> {units:,} units, "
        f"{snapped:,} snapped, {dest.stat().st_size / 1e6:.1f} MB"
    )
    return dest
