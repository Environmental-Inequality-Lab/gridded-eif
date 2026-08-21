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


def _load_boundaries(geo: config.Geography) -> gpd.GeoDataFrame:
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
    gdf = gpd.read_file(shp)[[geo.id_field, geo.name_field, "geometry"]]
    gdf = gdf.rename(columns={geo.id_field: "_geo_id", geo.name_field: "_geo_name"})
    return gdf
