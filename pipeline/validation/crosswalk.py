"""Section C — crosswalk and cell assignment.

Every number this product publishes is the sum of a set of grid cells, chosen
by a crosswalk. If the crosswalk is wrong, nothing downstream can be right, and
the failure is invisible: a partition built from an incomplete crosswalk is a
perfectly valid Parquet file with perfectly plausible numbers in it.

Every sentence this module contributes to the report is written in the `@check`
registration and never varies. The check bodies produce numbers only.
"""

from __future__ import annotations

from .. import config
from . import figures
from .registry import Context, check
from .types import Metric, Result, Table

# Above this many disagreements, an upstream boundary quirk stops being a
# plausible explanation and the weight of evidence points at our own join.
_CONFLICT_ADJUDICATION_CAP = 500


def _crosswalk(ctx: Context, geography: str) -> str | None:
    return ctx.crosswalk_source(geography)


def _skipped(check_id: str, why: str) -> Result:
    return Result(id=check_id, section="C", title="", tier=2, status="skip", skipped_because=why)


def _adjudicate(ctx: Context, cells: set[tuple[str, str]]) -> tuple[int, int, float | None]:
    """Split dropped cells into those inside the country and those outside.

    A cell is a legitimate exclusion only if it lies further from every US
    polygon than the snap radius the registry declares — that is, the pipeline
    was offered the chance to recover it and correctly declined. A dropped cell
    nearer than that is inside the country in every sense that matters and its
    population has simply gone missing.

    Distances are measured in EPSG:5070, not degrees: a degree of longitude is
    ~85 km at the Mexican border and ~40 km in Alaska, so a degree-space
    threshold would adjudicate Alaska twice as strictly as Texas.

    Returns (inside, outside, farthest inside-cell distance in metres).
    """
    if not cells:
        return 0, 0, None

    import geopandas as gpd
    import pandas as pd

    from ..crosswalk import _load_boundaries

    radius = config.registry()["aggregation"]["snap_max_distance_m"]
    df = pd.DataFrame(sorted(cells), columns=["grid_lon", "grid_lat"])
    pts = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df.grid_lon.astype(float), df.grid_lat.astype(float)),
        crs="EPSG:4326",
    ).to_crs("EPSG:5070")
    shapes = _load_boundaries(config.geographies()["county"]).to_crs("EPSG:5070")

    joined = gpd.sjoin_nearest(pts, shapes, how="left", distance_col="_dist")
    joined = joined[~joined.index.duplicated(keep="first")]
    within = joined["_dist"] <= radius
    farthest = float(joined.loc[within, "_dist"].max()) if within.any() else None
    return int(within.sum()), int((~within).sum()), farthest


@check(
    id="C1",
    section="C",
    title="Crosswalk coverage of every published year",
    tier=2,
    claim=(
        "The crosswalk assigns a geography to every populated grid cell that lies within "
        "the United States, in every published year. Aggregation is therefore lossless "
        "except for cells that fall outside the country by more than the declared snap "
        "radius, which are excluded deliberately and counted separately."
    ),
    method=(
        "Each source file is aggregated to one row per populated grid cell and joined "
        "against the county crosswalk. Cells with no match are collected across all "
        "dataset-years and adjudicated geometrically: the distance from each to the nearest "
        "county polygon is measured in EPSG:5070, and a cell counts as a legitimate "
        "exclusion only if that distance exceeds the snap radius the registry declares."
    ),
    interpretation=(
        "Aggregation inner-joins each year's source against the crosswalk, so a cell the "
        "crosswalk lacks is discarded silently along with its population --- a partition "
        "built that way is a valid file with plausible numbers in it. Testing this on the "
        "year a crosswalk was built from cannot fail, which is why every published year is "
        "tested. Cells beyond the snap radius are outside the country and excluded on "
        "purpose; they are adjudicated by distance rather than against a list, so the check "
        "cannot be satisfied by a growing set of exceptions. Any unassigned cell inside the "
        "radius is population missing from the published totals."
    ),
)
def c1_cell_coverage(ctx: Context) -> Result:
    xw = _crosswalk(ctx, "county")
    if not xw:
        return _skipped("C1", "no county crosswalk available")

    sql = """
        WITH src AS (
            SELECT grid_lon, grid_lat, sum(n_noise) AS pop
            FROM read_parquet('{source}') GROUP BY 1, 2
        )
        SELECT count(*)                                        AS cells,
               sum(src.pop)                                    AS pop,
               count(*) FILTER (WHERE x.geo_id IS NULL)        AS cells_missing,
               coalesce(sum(src.pop) FILTER (WHERE x.geo_id IS NULL), 0) AS pop_missing
        FROM src LEFT JOIN read_parquet('{crosswalk}') x USING (grid_lon, grid_lat)
    """

    rows: list[list] = []
    series: dict[str, list[tuple[int, float]]] = {}
    dropped_cells: set[tuple[str, str]] = set()
    for ds in config.datasets().values():
        pts = []
        for year in ds.all_years():
            cells, pop, missing_cells, missing_pop = ctx.con.execute(
                sql.format(source=config.source_url(ds.name, year), crosswalk=xw)
            ).fetchone()
            pct = 100.0 * (missing_pop or 0) / pop if pop else 0.0
            rows.append([ds.name, year, cells, missing_cells, missing_pop, pct])
            pts.append((year, pct))
            if missing_cells:
                dropped_cells |= set(
                    ctx.con.execute(f"""
                        SELECT DISTINCT s.grid_lon, s.grid_lat
                        FROM read_parquet('{config.source_url(ds.name, year)}') s
                        LEFT JOIN read_parquet('{xw}') x USING (grid_lon, grid_lat)
                        WHERE x.geo_id IS NULL
                    """).fetchall()
                )
        series[ds.label] = pts

    inside, outside, farthest_inside = _adjudicate(ctx, dropped_cells)
    radius = config.registry()["aggregation"]["snap_max_distance_m"]
    worst = max(rows, key=lambda r: r[5])

    # The figure earns its place only when there is a shape worth looking at; a
    # flat near-zero series plotted at full height reads as a dramatic pattern
    # in what is actually nothing.
    figs = []
    if worst[5] > 0.01 and figures.wanted(ctx) and figures.coverage_loss_by_year(ctx, series):
        figs.append(
            ctx.figure(
                "c1-coverage-loss",
                "Share of each dataset-year's source population that the crosswalk cannot "
                "assign. A year at exactly zero amid non-zero years is the signature of a "
                "crosswalk built from that year's populated cell set alone.",
            )
        )

    return Result(
        id="C1", section="C", title="", tier=2,
        status="pass" if inside == 0 else "fail",
        metrics=[
            Metric("Published dataset-years checked", len(rows)),
            Metric("Dataset-years with unassigned cells", sum(1 for r in rows if r[3])),
            Metric("Distinct cells unassigned", inside + outside),
            Metric("…beyond the snap radius, excluded deliberately", outside),
            Metric("…inside the snap radius, unaccounted for", inside, expected=0),
            Metric("Snap radius", round(radius / 1000, 1), unit="km"),
            Metric(
                "Farthest unaccounted-for cell from a polygon",
                round(farthest_inside / 1000, 1) if farthest_inside is not None else "n/a",
                unit="km" if farthest_inside is not None else "",
            ),
            Metric("Largest single-year shortfall", max((r[4] or 0) for r in rows),
                   unit="people"),
            Metric("…as a share of that year's source total", round(worst[5], 6), unit="%"),
        ],
        tables=[
            Table(
                caption="Grid cells and population unassigned by the crosswalk",
                columns=[
                    "Dataset", "Year", "Cells in source", "Cells missing",
                    "People dropped", "Loss (\\%)",
                ],
                rows=rows,
                align="llrrrr",
                numeric_columns=[2, 3, 4, 5],
                note=(
                    "Loss is the share of that dataset-year's source national total that "
                    "never reaches any published partition."
                ),
                label="tab:c1-coverage",
            )
        ],
        figures=figs,
        sql=[sql.format(source="<source file>", crosswalk="<crosswalk>").strip()],
    )


@check(
    id="C2",
    section="C",
    title="Each grid cell is assigned to exactly one unit",
    tier=2,
    claim=(
        "No grid cell appears twice in a crosswalk. A duplicated cell would be counted "
        "once for each unit it appears under, inflating totals in a way that no total-"
        "preserving check would catch."
    ),
    method=(
        "For each crosswalk, the number of rows is compared against the number of distinct "
        "grid cells."
    ),
    interpretation=(
        "A cell whose centroid falls exactly on a shared polygon edge matches more than one "
        "unit in the spatial join; the pipeline resolves this by keeping the first match. "
        "This check confirms the resolution is applied consistently and that no duplicate "
        "survives into a published file. A duplicate would inflate the total of every "
        "geography it appears in while leaving the national total looking correct."
    ),
)
def c2_uniqueness(ctx: Context) -> Result:
    rows, dupes_total = [], 0
    for geography in ctx.crosswalk_geographies():
        url = ctx.crosswalk_source(geography)
        cells, distinct, units = ctx.con.execute(f"""
            SELECT count(*), count(DISTINCT (grid_lon || ',' || grid_lat)), count(DISTINCT geo_id)
            FROM read_parquet('{url}')
        """).fetchone()
        rows.append([geography, cells, distinct, units, cells - distinct])
        dupes_total += cells - distinct

    return Result(
        id="C2", section="C", title="", tier=2,
        status="pass" if dupes_total == 0 else "fail",
        metrics=[
            Metric("Crosswalks checked", len(rows)),
            Metric("Duplicate cell assignments", dupes_total, expected=0),
        ],
        tables=[
            Table(
                caption="Cell uniqueness by crosswalk",
                columns=["Geography", "Rows", "Distinct cells", "Units", "Duplicates"],
                rows=rows,
                align="lrrrr",
                numeric_columns=[1, 2, 3, 4],
                label="tab:c2-uniqueness",
            )
        ],
    )


@check(
    id="C3",
    section="C",
    title="Border-cell snapping, and how much population depends on it",
    tier=2,
    claim=(
        "Cells whose centroid falls outside every polygon of a complete-coverage geography "
        "are recovered by snapping to the nearest unit rather than dropped, and the amount "
        "of population this recovers is stated rather than assumed."
    ),
    method=(
        "The \\texttt{snapped} flag carried by each crosswalk is counted per geography. The "
        "population riding on it is measured by joining the 2022 source file to the county "
        "crosswalk and summing the raw measure over snapped cells."
    ),
    interpretation=(
        "Recorded rather than judged. Snapping applies only where a geography tiles the "
        "country completely, so an unmatched cell must belong somewhere; for partial-coverage "
        "geographies such as metropolitan areas an unmatched cell is a genuine absence and is "
        "dropped instead. The snapped cells are a systematic border artifact --- cells "
        "straddling the Canadian and Mexican frontiers whose centroids land abroad --- so "
        "dropping them would undercount border communities specifically, which for an "
        "environmental-inequality product are populations of interest."
    ),
)
def c3_snapping(ctx: Context) -> Result:
    rows, total_snapped = [], 0
    for geography in ctx.crosswalk_geographies():
        geo = config.geographies().get(geography)
        if geo is None:
            continue
        url = ctx.crosswalk_source(geography)
        cells, snapped = ctx.con.execute(f"""
            SELECT count(*), sum(CASE WHEN snapped THEN 1 ELSE 0 END)
            FROM read_parquet('{url}')
        """).fetchone()
        snapped = int(snapped or 0)
        rows.append([
            geography,
            "complete" if geo.complete_coverage else "partial",
            cells,
            snapped,
            100.0 * snapped / cells if cells else 0.0,
        ])
        total_snapped += snapped

    xw = _crosswalk(ctx, "county")
    snap_pop = 0
    if xw:
        snap_pop = ctx.con.execute(f"""
            SELECT coalesce(sum(d.n_noise), 0)
            FROM read_parquet('{config.source_url("ageracesex", 2022)}') d
            JOIN read_parquet('{xw}') x
              ON d.grid_lon = x.grid_lon AND d.grid_lat = x.grid_lat
            WHERE x.snapped
        """).fetchone()[0]

    return Result(
        id="C3", section="C", title="", tier=2, status="info",
        metrics=[
            Metric("Snapped cell assignments, all crosswalks", total_snapped),
            Metric("Population recovered at county level, 2022", round(snap_pop or 0),
                   unit="people"),
            Metric("Snap radius",
                   round(config.registry()["aggregation"]["snap_max_distance_m"] / 1000, 1),
                   unit="km"),
        ],
        tables=[
            Table(
                caption="Snapped cell assignments by crosswalk",
                columns=["Geography", "Coverage", "Cells", "Snapped", "Snapped (\\%)"],
                rows=rows,
                align="llrrr",
                numeric_columns=[2, 3, 4],
                label="tab:c3-snapping",
            )
        ],
    )


def _source_layers_conflict(
    ctx: Context, cells: list[tuple[str, str]], child: str, parent: str, width: int
) -> int:
    """How many disagreements the source shapefiles themselves account for.

    A cell can sit inside a child polygon and a parent polygon that disagree
    about which parent the child belongs to. TIGER publishes each layer
    separately and they are not guaranteed mutually consistent — along a river
    whose channel has moved since the boundary was drawn, the PUMA and state
    layers genuinely differ. When that happens both of our joins are correct
    with respect to their own input and the inconsistency is upstream, which is
    a different finding from a spatial join that has misplaced a cell.

    Determined by re-running containment against the shapefiles rather than
    inferred, so a disagreement is only excused when the source really is the
    cause.
    """
    if not cells:
        return 0

    import geopandas as gpd
    import pandas as pd

    from ..crosswalk import _load_boundaries

    df = pd.DataFrame(cells, columns=["grid_lon", "grid_lat"])
    pts = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df.grid_lon.astype(float), df.grid_lat.astype(float)),
        crs="EPSG:4326",
    )
    child_shapes = _load_boundaries(config.geographies()[child])
    parent_shapes = _load_boundaries(config.geographies()[parent])
    in_child = gpd.sjoin(pts.to_crs(child_shapes.crs), child_shapes, predicate="within",
                         how="left")
    in_child = in_child[~in_child.index.duplicated(keep="first")]
    in_parent = gpd.sjoin(pts.to_crs(parent_shapes.crs), parent_shapes, predicate="within",
                          how="left")
    in_parent = in_parent[~in_parent.index.duplicated(keep="first")]

    explained = 0
    for i in pts.index:
        c, pnt = in_child.loc[i, "_geo_id"], in_parent.loc[i, "_geo_id"]
        if isinstance(c, str) and isinstance(pnt, str) and c[:width] != pnt:
            explained += 1
    return explained


@check(
    id="C4",
    section="C",
    title="Hierarchical consistency between independently built crosswalks",
    tier=2,
    claim=(
        "A cell contained by a county or PUMA polygon is contained by that unit's state: "
        "the first two digits of its identifier equal its state FIPS code. The crosswalks "
        "come from separate spatial joins against separate shapefiles, so agreement is an "
        "independent check on both."
    ),
    method=(
        "Child and parent crosswalks are joined on grid cell and their identifiers compared. "
        "Disagreements are partitioned three ways: cells placed by containment in both "
        "crosswalks, cells where at least one placement came from nearest-polygon snapping, "
        "and cells where the source shapefiles themselves conflict --- the last confirmed by "
        "re-running containment against the TIGER geometry rather than inferred."
    ),
    interpretation=(
        "Containment is transitive and must nest: a cell inside a county polygon is inside "
        "that county's state as a matter of geometry, and a disagreement there means one of "
        "the two joins is wrong. Two other cases are not defects. Snapping is decided per "
        "level, so near a border the nearest PUMA and the nearest state may sit in different "
        "states without either result being incorrect. And TIGER's layers are published "
        "separately and are not guaranteed mutually consistent, most visibly along rivers "
        "whose channel has moved since the boundary was drawn; there both joins are correct "
        "with respect to their own input. Only the unexplained remainder counts against this "
        "check. Commuting zones are excluded entirely: they are derived by remapping county "
        "identifiers rather than by their own spatial join, so agreement with county is true "
        "by construction and would be evidence of nothing."
    ),
)
def c4_hierarchy(ctx: Context) -> Result:
    xws = {g: ctx.crosswalk_source(g) for g in ctx.crosswalk_geographies()}
    pairs = [("county", "state", 2), ("puma", "state", 2)]
    rows, failures, snapped_total, upstream = [], 0, 0, 0

    for child, parent, width in pairs:
        if child not in xws or parent not in xws:
            continue
        matched, contained_bad, snapped_bad = ctx.con.execute(f"""
            SELECT count(*),
                   count(*) FILTER (
                       WHERE substr(c.geo_id, 1, {width}) <> p.geo_id
                         AND NOT (c.snapped OR p.snapped)
                   ),
                   count(*) FILTER (
                       WHERE substr(c.geo_id, 1, {width}) <> p.geo_id
                         AND (c.snapped OR p.snapped)
                   )
            FROM read_parquet('{xws[child]}') c
            JOIN read_parquet('{xws[parent]}') p USING (grid_lon, grid_lat)
        """).fetchone()

        explained = 0
        if 0 < contained_bad <= _CONFLICT_ADJUDICATION_CAP:
            offenders = ctx.con.execute(f"""
                SELECT c.grid_lon, c.grid_lat
                FROM read_parquet('{xws[child]}') c
                JOIN read_parquet('{xws[parent]}') p USING (grid_lon, grid_lat)
                WHERE substr(c.geo_id, 1, {width}) <> p.geo_id
                  AND NOT (c.snapped OR p.snapped)
            """).fetchall()
            explained = _source_layers_conflict(ctx, offenders, child, parent, width)

        rows.append([f"{child} → {parent}", matched, contained_bad, explained, snapped_bad])
        failures += contained_bad - explained
        upstream += explained
        snapped_total += snapped_bad

    return Result(
        id="C4", section="C", title="", tier=2,
        status="pass" if failures == 0 else "fail",
        metrics=[
            Metric("Nesting relationships checked", len(rows)),
            Metric("Disagreements explained by the TIGER layers", upstream),
            Metric("Disagreements involving a snapped placement", snapped_total),
            Metric("Unexplained disagreements between contained cells", failures, expected=0),
        ],
        tables=[
            Table(
                caption="Nesting agreement between independently built crosswalks",
                columns=[
                    "Relationship", "Cells compared", "Contained, not nesting",
                    "Explained by TIGER", "Snapped, not nesting",
                ],
                rows=rows,
                align="lrrrr",
                numeric_columns=[1, 2, 3, 4],
                label="tab:c4-hierarchy",
            )
        ],
    )


@check(
    id="C5",
    section="C",
    title="Grid geometry is as documented",
    tier=2,
    claim=(
        "Grid cell coordinates are centroids on a 0.01 degree lattice offset by 0.005, "
        "stored as strings, spanning the continental United States plus Alaska and Hawaii "
        "and no territory."
    ),
    method=(
        "Coordinate column types are read from the source schema. Every distinct cell in the "
        "2022 file is tested arithmetically for the documented lattice offset, rather than by "
        "string suffix, so the test holds regardless of how many decimal places a file "
        "happens to print. Territory assignment is counted from the county crosswalk."
    ),
    interpretation=(
        "Coordinates are stored as strings deliberately: the join between source and "
        "crosswalk is an equality test, and float equality silently drops rows. A departure "
        "from the lattice would mean the grid is not what the registry describes and the "
        "centroid-assignment method rests on a false premise. The longitude range spans the "
        "Aleutian crossing of the antimeridian, so its extremes are not a contiguous "
        "interval."
    ),
)
def c5_grid_geometry(ctx: Context) -> Result:
    grid = config.registry()["grid"]
    xw = _crosswalk(ctx, "county")
    url = config.source_url("ageracesex", 2022)

    types = {r[0]: r[1] for r in ctx.con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchall()}
    key_types_ok = all(types.get(c) == "VARCHAR" for c in grid["key_columns"])

    off_lon, off_lat, n, min_lon, max_lon, min_lat, max_lat = ctx.con.execute(f"""
        WITH c AS (
            SELECT DISTINCT CAST(grid_lon AS DOUBLE) lon, CAST(grid_lat AS DOUBLE) lat
            FROM read_parquet('{url}')
        )
        SELECT count(*) FILTER (WHERE abs((lon * 1000) - round(lon * 1000)) > 1e-6
                                   OR abs(round(lon * 1000) % 10) <> 5),
               count(*) FILTER (WHERE abs((lat * 1000) - round(lat * 1000)) > 1e-6
                                   OR abs(round(lat * 1000) % 10) <> 5),
               count(*), min(lon), max(lon), min(lat), max(lat)
        FROM c
    """).fetchone()

    territories = None
    if xw:
        territories = ctx.con.execute(f"""
            SELECT count(*) FROM read_parquet('{xw}')
            WHERE substr(geo_id, 1, 2) IN ('72', '78', '66', '60', '69')
        """).fetchone()[0]

    rows = [
        ["Coordinate storage type", "VARCHAR",
         ", ".join(f"{c}={types.get(c, 'absent')}" for c in grid["key_columns"])],
        ["Longitude off the 0.005 lattice", "0 cells", f"{off_lon:,} cells"],
        ["Latitude off the 0.005 lattice", "0 cells", f"{off_lat:,} cells"],
        ["Longitude range", "CONUS + AK + HI", f"{min_lon:.3f} to {max_lon:.3f}"],
        ["Latitude range", "CONUS + AK + HI", f"{min_lat:.3f} to {max_lat:.3f}"],
        ["Cells assigned to a territory", "0",
         f"{territories:,}" if territories is not None else "not measured"],
    ]

    problems = off_lon + off_lat + (0 if key_types_ok else 1) + (territories or 0)
    return Result(
        id="C5", section="C", title="", tier=2,
        status="pass" if problems == 0 else "fail",
        metrics=[
            Metric("Distinct populated cells, 2022", n),
            Metric("Grid resolution", grid["resolution_deg"], unit="degrees"),
            Metric("Declared centroid offset", grid["centroid_offset"], unit="degrees"),
            Metric("Departures from the documented specification", problems, expected=0),
        ],
        tables=[
            Table(
                caption="Grid geometry against its documented specification",
                columns=["Property", "Documented", "Observed"],
                rows=rows,
                align="lll",
                label="tab:c5-grid",
            )
        ],
    )


@check(
    id="C6",
    section="C",
    title="Drift in the populated cell set across years",
    tier=2,
    claim=(
        "The grid is fixed, but the populated subset of it is not: cells appear and "
        "disappear as administrative-records coverage changes and as people move. A "
        "crosswalk built from any single year therefore cannot assign another year's cells. "
        "This check measures how far the populated set drifts."
    ),
    method=(
        "For each published year of the age-race-sex dataset, the set of populated cells is "
        "compared against the 2022 file in both directions: cells that year has and 2022 "
        "does not, and cells 2022 has and that year does not. 2022 is a fixed point of "
        "comparison only; no year is privileged in the crosswalk itself."
    ),
    interpretation=(
        "Reported as a characterisation, not a pass or fail. Drift is a property of the "
        "source data --- the Census Bureau is not doing anything wrong by publishing a "
        "moving cell set --- and becomes a defect only if a pipeline assumes otherwise. "
        "Because the drift runs in both directions, no single year is a superset of the "
        "others, which is why crosswalks are built from the union of all published "
        "dataset-years. C1 and C7 are the checks that fail if that ever stops being true."
    ),
)
def c6_grid_stability(ctx: Context) -> Result:
    ds = config.datasets()["ageracesex"]
    ref = 2022
    ref_url = config.source_url(ds.name, ref)

    rows = []
    for year in ds.all_years():
        url = config.source_url(ds.name, year)
        n, only_here, only_ref = ctx.con.execute(f"""
            WITH a AS (SELECT DISTINCT grid_lon, grid_lat FROM read_parquet('{url}')),
                 b AS (SELECT DISTINCT grid_lon, grid_lat FROM read_parquet('{ref_url}'))
            SELECT (SELECT count(*) FROM a),
                   (SELECT count(*) FROM (SELECT * FROM a EXCEPT SELECT * FROM b)),
                   (SELECT count(*) FROM (SELECT * FROM b EXCEPT SELECT * FROM a))
        """).fetchone()
        rows.append([year, n, only_here, only_ref])

    figs = []
    if figures.wanted(ctx) and figures.cell_set_drift(
        ctx, [(r[0], r[1], r[2]) for r in rows], ref
    ):
        figs.append(
            ctx.figure(
                "c6-cell-drift",
                "Populated grid cells by year. The dark band is the number of cells present "
                "in that year but absent from the 2022 file. A crosswalk built from the union "
                "of all years has no such band.",
            )
        )

    return Result(
        id="C6", section="C", title="", tier=2, status="info",
        metrics=[
            Metric("Years compared", len(rows)),
            Metric("Reference year for comparison", ref),
            Metric("Most cells absent from the reference in one year",
                   max(r[2] for r in rows), unit="cells"),
            Metric("Most cells present only in the reference",
                   max(r[3] for r in rows), unit="cells"),
        ],
        tables=[
            Table(
                caption="Populated cell set by year, compared with the reference year",
                columns=["Year", "Populated cells", "Absent from 2022", "Present in 2022 only"],
                rows=rows,
                align="lrrr",
                numeric_columns=[1, 2, 3],
                note=(
                    "A cell is populated in a given year if the source file contains any row "
                    "for it. Drift runs in both directions, so no single year contains all "
                    "the others."
                ),
                label="tab:c6-drift",
            )
        ],
        figures=figs,
    )


@check(
    id="C7",
    section="C",
    title="Fitness of the published crosswalk for its advertised purpose",
    tier=2,
    claim=(
        "The site offers the crosswalk so users can aggregate the Census source grids it "
        "does not serve. It should therefore cover the union of populated cells across "
        "every published dataset-year, not the cells of any one year."
    ),
    method=(
        "The distinct cells of every published source file are unioned in a single scan and "
        "joined against the county crosswalk. Cells with no match are adjudicated by "
        "distance to the nearest county polygon, on the same basis as C1."
    ),
    interpretation=(
        "A user following the site's own instructions aggregates the raw grid with this "
        "file, so any cell it cannot assign is population that silently disappears from "
        "their analysis rather than ours. The pollutant and extreme-weather grids are not "
        "included in the union: they are not yet enabled in the registry and their cell "
        "coverage differs again, so a shortfall measured here is a lower bound on what a "
        "user of those files would encounter."
    ),
)
def c7_crosswalk_fitness(ctx: Context) -> Result:
    xw = _crosswalk(ctx, "county")
    if not xw:
        return _skipped("C7", "no county crosswalk available")

    # One scan over the whole file list rather than a 52-way UNION of DISTINCTs:
    # the union form makes DuckDB deduplicate pairwise, 52 times over, where
    # read_parquet over a list is a single scan and a single aggregation.
    sources = [
        config.source_url(ds.name, year)
        for ds in config.datasets().values()
        for year in ds.all_years()
    ]

    total, covered = ctx.con.execute(f"""
        WITH u AS (SELECT DISTINCT grid_lon, grid_lat FROM read_parquet({sources!r}))
        SELECT count(*), count(x.geo_id)
        FROM u LEFT JOIN read_parquet('{xw}') x USING (grid_lon, grid_lat)
    """).fetchone()
    missing = total - covered

    unassigned = set()
    if missing:
        unassigned = set(ctx.con.execute(f"""
            WITH u AS (SELECT DISTINCT grid_lon, grid_lat FROM read_parquet({sources!r}))
            SELECT u.grid_lon, u.grid_lat
            FROM u LEFT JOIN read_parquet('{xw}') x USING (grid_lon, grid_lat)
            WHERE x.geo_id IS NULL
        """).fetchall())
    inside, outside, _ = _adjudicate(ctx, unassigned)

    xw_rows = ctx.con.execute(f"SELECT count(*) FROM read_parquet('{xw}')").fetchone()[0]

    return Result(
        id="C7", section="C", title="", tier=2,
        status="pass" if inside == 0 else "fail",
        metrics=[
            Metric("Union of populated cells, all datasets and years", total, unit="cells"),
            Metric("Rows in the county crosswalk", xw_rows, unit="cells"),
            Metric("Union cells the crosswalk cannot assign", missing, unit="cells"),
            Metric("…beyond the snap radius, outside the country", outside, unit="cells"),
            Metric("…inside the snap radius, a genuine gap", inside, unit="cells", expected=0),
        ],
    )


@check(
    id="C8",
    section="C",
    title="Spatial concentration of any dropped population",
    tier=2,
    claim=(
        "Population the crosswalk fails to assign is reported by state, so that a national "
        "figure cannot conceal a loss falling heavily on one place."
    ),
    method=(
        "Cells unassigned in the most recent final year are located by point-in-polygon "
        "against the state boundaries and aggregated. The share is computed against what "
        "each state's total would have been had no cell been dropped, using the published "
        "state partition as the denominator."
    ),
    interpretation=(
        "A national loss expressed as a fraction of a percent invites the reading that it is "
        "a rounding error, which holds only if the loss is diffuse. This check makes the "
        "distribution visible: a loss concentrated in particular states distorts the "
        "geographic pattern the product exists to describe whatever its national magnitude, "
        "and grid cells vary enormously in population, so a small number of dropped cells can "
        "carry a large number of people. Where every dropped cell falls outside all state "
        "polygons there is no distribution to report, and whether excluding those cells is "
        "correct is adjudicated in C1 rather than here."
    ),
)
def c8_loss_concentration(ctx: Context) -> Result:
    import geopandas as gpd

    xw = _crosswalk(ctx, "county")
    if not xw:
        return _skipped("C8", "no county crosswalk available")

    year = 2024
    dropped = ctx.con.execute(f"""
        WITH src AS (
            SELECT grid_lon, grid_lat, sum(n_noise) AS pop
            FROM read_parquet('{config.source_url("ageracesex", year)}') GROUP BY 1, 2
        )
        SELECT src.grid_lon, src.grid_lat, src.pop
        FROM src LEFT JOIN read_parquet('{xw}') x USING (grid_lon, grid_lat)
        WHERE x.geo_id IS NULL
    """).df()

    base = [Metric("Year examined", year)]
    if dropped.empty:
        return Result(
            id="C8", section="C", title="", tier=2, status="pass",
            metrics=base + [
                Metric("Cells dropped", 0),
                Metric("People dropped", 0),
                Metric("States affected", 0, expected=0),
            ],
        )

    state_url = ctx.published("ageracesex", "state", year)
    if not state_url:
        # A partial refresh may not have built this level, and there is no
        # denominator without it. Skipping is honest; guessing one is not.
        return _skipped(
            "C8", f"no state partition for {year} to use as a denominator"
        )
    totals = ctx.con.execute(
        f"SELECT geo_id, sum(n_noise) AS pop FROM read_parquet('{state_url}') GROUP BY 1"
    ).df().set_index("geo_id")["pop"].to_dict()

    from ..crosswalk import _load_boundaries

    states = _load_boundaries(config.geographies()["state"])
    pts = gpd.GeoDataFrame(
        dropped,
        geometry=gpd.points_from_xy(
            dropped.grid_lon.astype(float), dropped.grid_lat.astype(float)
        ),
        crs="EPSG:4326",
    ).to_crs(states.crs)
    joined = gpd.sjoin(pts, states, how="left", predicate="within")

    by_state = (
        joined.groupby(["_geo_id", "_geo_name"])
        .agg(cells=("pop", "size"), lost=("pop", "sum"))
        .reset_index()
    )

    metrics = base + [
        Metric("Cells dropped", len(dropped)),
        Metric("People dropped", round(float(dropped["pop"].sum()))),
        Metric("Heaviest single dropped cell", round(float(dropped["pop"].max())),
               unit="people"),
        Metric("Cells falling outside every state polygon",
               int(joined["_geo_id"].isna().sum())),
        Metric("States affected", len(by_state), expected=0),
    ]

    if by_state.empty:
        return Result(id="C8", section="C", title="", tier=2, status="pass", metrics=metrics)

    by_state["published"] = by_state["_geo_id"].map(totals)
    by_state["share"] = 100 * by_state["lost"] / (by_state["lost"] + by_state["published"])
    by_state = by_state.sort_values("share", ascending=False)
    metrics.append(
        Metric("Largest share lost by any one state",
               round(float(by_state.iloc[0]["share"]), 3), unit="%")
    )

    figs = []
    if figures.wanted(ctx) and figures.loss_by_state(ctx, by_state.head(15), year):
        figs.append(
            ctx.figure(
                "c8-loss-by-state",
                "Population the crosswalk could not assign, as a share of each state's "
                "published total. Absolute counts are annotated beside each bar.",
                width=r"0.92\textwidth",
            )
        )

    return Result(
        id="C8", section="C", title="", tier=2, status="fail",
        metrics=metrics,
        tables=[
            Table(
                caption="States most affected by dropped grid cells, ordered by share lost",
                columns=["State", "Cells dropped", "People dropped",
                         "Published total", "Lost (\\%)"],
                rows=[
                    [r["_geo_name"], int(r["cells"]), float(r["lost"]),
                     float(r["published"]), float(r["share"])]
                    for _, r in by_state.head(15).iterrows()
                ],
                align="lrrrr",
                numeric_columns=[1, 2, 3, 4],
                note=(
                    "The published total is the figure the site currently reports for that "
                    "state. The lost share is computed against what the total would have "
                    "been had no cell been dropped."
                ),
                label="tab:c8-concentration",
            )
        ],
        figures=figs,
    )
