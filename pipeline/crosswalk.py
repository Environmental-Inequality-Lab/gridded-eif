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
GRID_CRS = "EPSG:4326"


def build(
    geography: str,
    reference_dataset: str = "ageracesex",
    reference_year: int = 2022,
    force: bool = False,
) -> Path:
    """Build (or reuse) the crosswalk for one geography level."""
    CACHE.mkdir(exist_ok=True)
    out = CACHE / f"xwalk_{geography}.parquet"
    if out.exists() and not force:
        console.print(f"[dim]crosswalk {geography}: cached[/dim]")
        return out

    geo = config.geographies()[geography]
    cells = _distinct_cells(reference_dataset, reference_year)
    console.print(f"crosswalk {geography}: {len(cells):,} grid cells")

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
    if len(unmatched) and config.registry()["aggregation"]["snap_unmatched_to_nearest"]:
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
    console.print(
        f"crosswalk {geography}: matched {matched:,}/{len(joined):,} "
        f"({100 * matched / len(joined):.3f}%)"
        + (f", [red]{still:,} still unmatched[/red]" if still else "")
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


def _distinct_cells(dataset: str, year: int) -> pd.DataFrame:
    """Distinct populated grid cells, taken from the data itself.

    Deliberately NOT from eif_grid_topology.rda, which is CONUS-only and would
    silently drop Alaska and Hawaii — 1.45M people.
    """
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    url = config.source_url(dataset, year)
    return con.execute(
        f"SELECT DISTINCT grid_lon, grid_lat FROM read_parquet('{url}')"
    ).df()


def _load_boundaries(geo: config.Geography, keep_extra: bool = False) -> gpd.GeoDataFrame:
    """Fetch and normalize a TIGER/Line layer to _geo_id / _geo_name / geometry."""
    if geo.per_state:
        raise NotImplementedError(
            f"{geo.name} ships one shapefile per state; needs the per-state loader (Phase 3)"
        )
    if not geo.tiger_url:
        raise NotImplementedError(f"{geo.name} is not TIGER-backed (built_from={geo.built_from})")

    CACHE.mkdir(exist_ok=True)
    local = CACHE / f"tiger_{geo.name}"
    if not local.exists():
        console.print(f"[dim]downloading {geo.tiger_url}[/dim]")
        resp = requests.get(geo.tiger_url, timeout=600)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(local)

    shp = next(local.glob("*.shp"))
    gdf = gpd.read_file(shp)
    cols = {geo.id_field: "_geo_id", geo.name_field: "_geo_name"}
    if keep_extra:
        # Fields the name builder needs but the spatial join does not.
        for src, dst in (("NAMELSAD", "_namelsad"), ("STUSPS", "_stusps")):
            if src in gdf.columns:
                cols[src] = dst
    gdf = gdf[[*cols, "geometry"]].rename(columns=cols)
    return gdf


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
    elif geography == "county":
        # "Wayne County, MI" — the form people actually search for. NAMELSAD
        # carries the type ("County", "Parish", "Borough"), which matters
        # outside the lower 48.
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
