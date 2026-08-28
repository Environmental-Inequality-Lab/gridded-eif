"""Front matter — what the product is, and what it contains.

Reference rather than verdict: this section carries no pass or fail. It exists
so a reader can tell what was validated without opening the registry, and so
that a citation of this document identifies a specific inventory of files and
a specific set of category codes.

Everything here is read from ``catalog/variables.yaml`` and the catalog at run
time. Like the checks, the prose is fixed and only the tables move — the
registry is the single source of truth for the pipeline, the site, and this
document alike, so a dataset added there appears here without anyone editing
prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from .registry import Context
from .types import Table


@dataclass
class Block:
    """One subsection of the front matter."""

    title: str
    prose: str
    tables: list[Table] = field(default_factory=list)


def build(ctx: Context) -> list[Block]:
    return [
        _source(),
        _datasets(),
        _dimensions(),
        _measures(),
        _geographies(),
        _files(ctx),
        _schema(ctx),
        _rules(),
    ]


def _source() -> Block:
    reg = config.registry()
    src, grid = reg["source"], reg["grid"]
    return Block(
        title="Source",
        prose=(
            "The Gridded Environmental Impacts Frame is an experimental Census Bureau "
            "product built from administrative records with privacy noise infused. Counts "
            "will not match the Decennial Census or the Population Estimates Program, and "
            "under- and over-coverage are both real. This report validates the "
            "pre-aggregated product built from it, not the source data itself."
        ),
        tables=[
            Table(
                caption="Source data",
                columns=["Property", "Value"],
                rows=[
                    ["Citation", " ".join(src["citation"].split())],
                    ["File directory", src["base_url"]],
                    ["Landing page", src["landing_page"]],
                    ["Source data version", src["data_version"]],
                    ["Experimental", "yes" if src.get("experimental") else "no"],
                    ["Grid resolution", f"{grid['resolution_deg']} degrees"],
                    ["Coordinate reference system", grid["crs"]],
                    ["Centroid offset", f"{grid['centroid_offset']} degrees"],
                    ["Key columns", ", ".join(grid["key_columns"])],
                    ["Key column type", grid["key_dtype"]],
                    ["Geographic coverage", ", ".join(grid["coverage"])],
                ],
                align="lp{0.62\\textwidth}",
                label="tab:inv-source",
            )
        ],
    )


def _datasets() -> Block:
    rows = []
    for name, spec in config.registry()["datasets"].items():
        years = spec.get("years") or {}
        span = f"{years['start']}--{years['end']}" if years else "—"
        prelim = ", ".join(str(y) for y in spec.get("preliminary_years", [])) or "—"
        rows.append([
            name,
            spec["label"],
            "yes" if spec.get("enabled") else "no",
            span,
            prelim,
            ", ".join(spec.get("dimensions", [])) or "—",
        ])
    return Block(
        title="Datasets",
        prose=(
            "Datasets not marked enabled are declared in the registry but not built. They "
            "are listed here because their presence is a deliberate decision --- adding one "
            "should be a configuration change rather than a code change --- and because a "
            "reader looking for pollution or housing data should be able to see that it is "
            "known about and not yet served. Preliminary years are built from partial "
            "administrative records, are subject to revision, and are never silently mixed "
            "into a range of final years."
        ),
        tables=[
            Table(
                caption="Datasets declared by the registry",
                columns=["Name", "Label", "Built", "Final years", "Prelim.",
                         "Dimensions"],
                rows=rows,
                align="lp{0.17\\textwidth}cllp{0.19\\textwidth}",
                label="tab:inv-datasets",
            )
        ],
    )


def _dimensions() -> Block:
    tables = []
    for name, spec in config.registry()["dimensions"].items():
        rows = [
            [str(v["code"]), v["label"], "yes" if v.get("residual") else ""]
            for v in spec["values"]
        ]
        tables.append(
            Table(
                caption=f"{spec['label']} — codes as stored, labels as displayed",
                columns=["Code in the data", "Label shown", "Residual"],
                rows=rows,
                align="lll",
                note=" ".join(spec["note"].split()) if spec.get("note") else None,
                label=f"tab:inv-dim-{name}",
            )
        )
    return Block(
        title="Dimensions and category codes",
        prose=(
            "The code is the literal string stored in the data and is what a query must "
            "match; the label is what the site displays. The two differ where a published "
            "code is misleading on its face --- the age groups are stored as \\texttt{Under 18}, "
            "\\texttt{19-65} and \\texttt{Over 65} but describe the bins under 18, 18--64 and 65 and "
            "over --- and the code is never changed to match the label, because doing so "
            "would break every query written against the source files. Residual categories "
            "are retained as visible values and never folded into totals or dropped from "
            "denominators; a share computed from these tables must state its denominator."
        ),
        tables=tables,
    )


def _measures() -> Block:
    reg = config.registry()
    rows = []
    for name, spec in reg["measures"].items():
        rows.append([
            name,
            spec["label"],
            "yes" if spec.get("non_negative") else "no",
            "yes" if spec.get("default") else "no",
            spec.get("recommended_when", "—"),
        ])
    return Block(
        title="Noise measures",
        prose=(
            "Two columns ship with every population dataset. They are different estimators "
            "of the same quantity, not alternative encodings of it, and are never summed "
            "together or mixed within a single table. The raw measure is unbiased but can "
            "be negative at cell level; the post-processed measure pools small noisy cells "
            "by race within each one-degree grid point, redistributes them, and clamps "
            "residual negatives to zero, which makes it non-negative at the cost of moving "
            "mass toward categories that are sparse at cell level."
        ),
        tables=[
            Table(
                caption="Noise measures",
                columns=["Column", "Label", "Non-negative", "Default", "Recommended when"],
                rows=rows,
                align="lllll",
                note=(
                    "The population threshold that selects the default measure is "
                    f"{reg['measure_selection_population_threshold']:,}. Below it the "
                    "post-processed measure has materially lower error; above it the raw "
                    "measure does."
                ),
                label="tab:inv-measures",
            )
        ],
    )


def _geographies() -> Block:
    rows = []
    for name, spec in config.registry()["geographies"].items():
        units = spec.get("approx_units")
        rows.append([
            name,
            spec["label"],
            "yes" if spec.get("enabled", True) else "no",
            f"{units:,}" if isinstance(units, int) else "—",
            "complete" if spec.get("complete_coverage", True) else "partial",
            "yes" if spec.get("map", True) else "no",
            str(spec.get("phase", "—")),
        ])
    caveats = [
        [name, " ".join(spec["caveat"].split())]
        for name, spec in config.registry()["geographies"].items()
        if spec.get("caveat")
    ]
    tables = [
        Table(
            caption="Geography levels declared by the registry",
            columns=["Name", "Label", "Built", "Units", "Coverage", "Map", "Phase"],
            rows=rows,
            align="lllrlll",
            label="tab:inv-geographies",
        )
    ]
    if caveats:
        tables.append(
            Table(
                caption="Geography caveats recorded in the registry",
                columns=["Level", "Caveat"],
                rows=caveats,
                align="lp{0.72\\textwidth}",
            )
        )
    return Block(
        title="Geography levels",
        prose=(
            "A level marked partial does not tile the country: cells outside every unit are "
            "dropped rather than snapped to a nearest one, so totals at that level do not "
            "sum to the national total. A level marked as not built is declared but "
            "deliberately not served, and the registry records the reason as data rather "
            "than as a comment so the decision cannot drift out of the file unnoticed. "
            "Block group is absent by design: a 0.01 degree cell is about the size of a "
            "median block group, so that level would imply precision the privacy noise "
            "cannot support."
        ),
        tables=tables,
    )


def _files(ctx: Context) -> Block:
    cat = ctx.catalog()
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for e in cat.get("entries", []):
        by_pair.setdefault((e["dataset"], e["geography"]), []).append(e)

    rows = []
    for (dataset, geography), entries in sorted(by_pair.items()):
        years = sorted(e["year"] for e in entries)
        rows.append([
            dataset,
            geography,
            f"{years[0]}--{years[-1]}",
            len(entries),
            sum(e["rows"] for e in entries),
            round(sum(e["bytes"] for e in entries) / 1e6, 1),
        ])

    other = [
        ["All-years files", len(cat.get("combined", [])),
         round(sum(c["bytes"] for c in cat.get("combined", [])) / 1e6, 1)],
        ["Grid-cell crosswalks", len(cat.get("crosswalks") or {}), None],
        ["Boundary files", len(cat.get("boundaries") or {}), None],
        ["Name lookups", len(cat.get("names") or {}), None],
    ]

    return Block(
        title="Published files",
        prose=(
            "One partition per dataset, geography and year, plus one all-years file per "
            "dataset and geography for time series --- the latter exists because latency on "
            "a multi-year query is dominated by per-file round trips rather than by bytes. "
            "Both contain identical values. Crosswalks map each grid cell to a unit at every "
            "level and are published so that users can aggregate the Census source grids "
            "this site does not serve. Boundaries carry an identifier and geometry only, "
            "with no data values, so a new year of data never requires regenerating them. "
            "Every derived path is versioned, so a breaking change publishes alongside the "
            "old tree rather than invalidating a cited URL."
        ),
        tables=[
            Table(
                caption="Published partitions by dataset and geography",
                columns=["Dataset", "Geography", "Years", "Files", "Rows", "Size (MB)"],
                rows=rows,
                align="lllrrr",
                numeric_columns=[3, 4, 5],
                note=(
                    "Read from the published catalog, which is what the site serves. When "
                    "the checks in this report were run against a local build rather than "
                    "the published product, this inventory still describes what is "
                    "published; the title page records which was validated."
                ),
                label="tab:inv-files",
            ),
            Table(
                caption="Other published artifacts",
                columns=["Kind", "Files", "Size (MB)"],
                rows=[[k, n, b] for k, n, b in other],
                align="lrr",
                numeric_columns=[1, 2],
                note=(
                    "Crosswalk, boundary and name file sizes are not recorded in the "
                    "catalog and are omitted rather than estimated."
                ),
            ),
        ],
    )


def _schema(ctx: Context) -> Block:
    """Column layout of the files a user actually downloads."""
    tables = []
    probes = [
        ("A derived partition", ctx.published("ageracesex", "county", 2022)),
        ("A published crosswalk", ctx.crosswalk_source("county")),
    ]
    for caption, target in probes:
        if not target:
            continue
        try:
            described = ctx.con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{target}')"
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 — a probe must not stop the report
            # Recorded in place of the table rather than swallowed: a missing
            # schema table would otherwise look like a file with no columns.
            tables.append(
                Table(
                    caption=f"{caption} — column layout could not be read",
                    columns=["Target", "Reason"],
                    rows=[[str(target), f"{type(exc).__name__}: {exc}"]],
                    align="lp{0.5\\textwidth}",
                )
            )
            continue
        tables.append(
            Table(
                caption=f"{caption} — column layout",
                columns=["Column", "Type"],
                rows=[[r[0], r[1]] for r in described],
                align="ll",
            )
        )

    return Block(
        title="File schemas",
        prose=(
            "Read from the files themselves rather than from documentation. A derived "
            "partition carries the geography identifier, one column per dimension of its "
            "dataset, both noise measures, and the number of grid cells the row was "
            "aggregated from --- that last column is what lets a user judge whether a figure "
            "rests on enough cells for the noise to have averaged out. Coordinates in the "
            "crosswalk are stored as strings because the join against the source files is an "
            "equality test and float equality silently drops rows. The \\texttt{snapped} flag "
            "marks cells whose centroid fell outside every unit and were assigned to the "
            "nearest one, so a user can see which assignments were inferred and decide for "
            "themselves."
        ),
        tables=tables,
    )


def _rules() -> Block:
    agg = config.registry()["aggregation"]
    rows = [
        ["Assignment method", str(agg["method"])],
        ["Crosswalk cell set", str(agg.get("crosswalk_cell_set", "—"))],
        ["Snap unmatched cells to nearest", "yes" if agg["snap_unmatched_to_nearest"] else "no"],
        ["Maximum snap distance", f"{agg['snap_max_distance_m']:,} m (measured in EPSG:5070)"],
        ["Residual categories visible", "yes" if agg["residual_categories_visible"] else "no"],
        ["Measures may be mixed in one table", "yes" if agg["mix_measures"] else "no"],
    ]
    return Block(
        title="Aggregation rules",
        prose=(
            "Cells are assigned whole to the geography containing their centroid, rather "
            "than apportioned by area. This is simple, reproducible, and matches what the "
            "source user guide's own examples do. Where a geography tiles the country, a "
            "cell whose centroid falls outside every unit is snapped to the nearest one: "
            "those cells are a systematic border artifact rather than scattered noise, and "
            "dropping them would undercount border communities specifically. Crosswalks are "
            "built from the union of populated cells across every published dataset-year, "
            "not from any single year, because the populated subset of the grid is not "
            "stable over time."
        ),
        tables=[
            Table(
                caption="Aggregation rules declared by the registry",
                columns=["Rule", "Value"],
                rows=rows,
                align="lp{0.55\\textwidth}",
                label="tab:inv-rules",
            )
        ],
    )
