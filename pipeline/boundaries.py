"""Simplified boundary geometry for the map.

Serves plain GeoJSON rather than vector tiles. That is a deliberate trade:
tippecanoe is not available here or in CI, and at these feature counts
topology-preserving simplification gets every level small enough to fetch
directly — 3,144 counties compress from 203 MB of raw TIGER geometry to about
1 MB on the wire.

**Boundaries carry no data values.** They hold `geo_id` and nothing else; the
site joins query results to features at render time. So a new year of data
never requires regenerating geometry, and a boundary update never invalidates
a data partition.

Simplification is topology-preserving (via `topojson`), so adjacent units keep
their shared borders. Plain per-polygon simplification tears gaps between
neighbours, which on a choropleth reads as missing data.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import topojson as tp
from rich.console import Console

from . import config
from .crosswalk import CACHE, _load_boundaries, _load_id_crosswalk

console = Console()

# Degrees. 0.005 is roughly 500 m at mid-latitudes — invisible at the zoom
# levels where a national or state choropleth is read, and it keeps every
# level around or under a megabyte compressed.
DEFAULT_TOLERANCE = 0.005

TERRITORIES = ("72", "78", "66", "60", "69")


class MapUnsupported(Exception):
    """Raised for a geography deliberately excluded from the map."""


def build(geography: str, force: bool = False) -> Path:
    """Write simplified GeoJSON for one geography level."""
    if config.registry()["geographies"][geography].get("map", True) is False:
        raise MapUnsupported(geography)

    out = CACHE / f"bounds_{geography}.geojson"
    if out.exists() and not force:
        console.print(f"[dim]boundaries {geography}: cached[/dim]")
        return out

    geo = config.geographies()[geography]
    spec = config.registry()["geographies"][geography]
    tol = spec.get("simplify_tolerance", DEFAULT_TOLERANCE)

    if geo.source == "constant":
        gdf = _dissolve_all(geo)
    elif geo.built_from:
        gdf = _dissolve_from_parent(geography, geo)
    else:
        gdf = _load_boundaries(geo)[["_geo_id", "geometry"]].rename(
            columns={"_geo_id": "geo_id"}
        )
        gdf = gdf[~gdf.geo_id.str[:2].isin(TERRITORIES)]

    gdf = gdf.to_crs(4326)
    before = len(gdf.to_json())

    topo = tp.Topology(gdf, prequantize=False, toposimplify=tol)
    simplified = topo.to_gdf()
    simplified = simplified[["geo_id", "geometry"]]
    # Simplification can collapse a sliver to nothing; drop rather than emit
    # an invalid feature the renderer will choke on.
    simplified = simplified[~simplified.geometry.is_empty & simplified.geometry.notna()]

    out.write_text(simplified.to_json())
    after = out.stat().st_size
    console.print(
        f"[green]boundaries {geography}[/green]: {len(simplified):,} features, "
        f"{before / 1e6:.0f} MB -> {after / 1e6:.2f} MB (tolerance {tol})"
    )
    return out


def _dissolve_all(geo: config.Geography) -> gpd.GeoDataFrame:
    """One feature for the whole country, dissolved from states."""
    states = _load_boundaries(config.geographies()["state"])
    states = states[~states["_geo_id"].str[:2].isin(TERRITORIES)]
    merged = states.dissolve()[["geometry"]]
    merged["geo_id"] = geo.constant_id
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=states.crs)


def _dissolve_from_parent(geography: str, geo: config.Geography) -> gpd.GeoDataFrame:
    """Build geometry for a derived level by dissolving its parent's units.

    Commuting zones have no published shapefile — they are defined as sets of
    counties, so their geometry is the union of those counties.
    """
    parent = _load_boundaries(config.geographies()[geo.built_from])
    parent = parent[~parent["_geo_id"].str[:2].isin(TERRITORIES)]
    mapping, _ = _load_id_crosswalk(geo)
    parent = parent.copy()
    parent["geo_id"] = parent["_geo_id"].astype(str).map(mapping)
    missing = int(parent["geo_id"].isna().sum())
    if missing:
        raise ValueError(f"{geography}: {missing} parent units missing from the crosswalk")
    return parent.dissolve(by="geo_id", as_index=False)[["geo_id", "geometry"]]
