"""Section B — boundaries and geometry.

Checks the artifacts that describe *where* a place is and *how big* it is, as
distinct from how many people are in it: the name lookups, the land and water
areas, and the simplified geometry the map serves.

Every sentence this module contributes to the report is written in the `@check`
registration and never varies. The check bodies produce numbers only.
"""

from __future__ import annotations

from .. import config
from .registry import Context, check
from .types import Metric, Result, Table

# US land area, 50 states plus the District of Columbia, as published by the
# Census Bureau. TIGER's per-polygon ALAND values are revised between vintages
# and do not reproduce it exactly, so this is a magnitude check, not an
# identity — the tolerance is wide enough to pass a boundary revision and
# narrow enough to fail a unit error or a dropped state.
US_LAND_AREA_KM2 = 9_147_593
US_LAND_TOLERANCE = 0.01  # 1%


@check(
    id="B1",
    section="B",
    title="Every named place has a positive land area",
    tier=2,
    claim=(
        "The name and area lookups describe the same set of places at every geography "
        "level, and every published land area is greater than zero."
    ),
    method=(
        "For each level the published name lookup and area lookup are read and their key "
        "sets compared in both directions. Land areas are then checked for values of zero "
        "or below."
    ),
    interpretation=(
        "These files are joined by identifier downstream: a consumer computing population "
        "density reads a count from a partition, a label from the name lookup, and a "
        "denominator from the area lookup. A place present in one and absent from the other "
        "therefore breaks silently at the join — a named place with no area yields no "
        "density, and an area with no name is a row nobody can label. A land area of zero "
        "is worse than missing, because it divides rather than drops: it produces an "
        "infinite density that will propagate through whatever is computed from it."
    ),
)
def b1_areas_cover_named_places(ctx: Context) -> Result:
    levels = ctx.lookup_geographies("names")
    if not levels:
        return Result(
            id="B1", section="B", title="", tier=2, status="skip",
            skipped_because="no name lookups are published",
        )
    # Areas absent everywhere means the artifact has not been published yet,
    # which is a state of the release rather than a defect in it. Areas present
    # for some levels and not others is a genuine failure and falls through.
    if not ctx.lookup_geographies("areas"):
        return Result(
            id="B1", section="B", title="", tier=2, status="skip",
            skipped_because="no area lookups are published yet",
        )

    rows, problems = [], []
    named_total = area_total = 0
    missing_total = extra_total = nonpositive_total = 0

    for geography in levels:
        names = ctx.lookup("names", geography)
        areas = ctx.lookup("areas", geography)
        if names is None or areas is None:
            problems.append([
                geography,
                "no area lookup published" if areas is None else "no name lookup published",
                "—",
            ])
            continue

        missing = sorted(set(names) - set(areas))
        extra = sorted(set(areas) - set(names))
        nonpositive = sorted(k for k, v in areas.items() if v.get("aland_m2", 0) <= 0)

        rows.append([geography, len(names), len(areas), len(missing), len(extra),
                     len(nonpositive)])
        named_total += len(names)
        area_total += len(areas)
        missing_total += len(missing)
        extra_total += len(extra)
        nonpositive_total += len(nonpositive)

        for ids, label in ((missing, "named, no area"),
                           (extra, "area, no name"),
                           (nonpositive, "land area <= 0")):
            for gid in ids[:10]:
                problems.append([geography, label, gid])
            if len(ids) > 10:
                problems.append([geography, label, f"... and {len(ids) - 10} more"])

    tables = [
        Table(
            caption="Name and area lookups compared, by geography level",
            columns=["Geography", "Named places", "Places with an area",
                     "Named, no area", "Area, no name", "Land area $\\leq 0$"],
            rows=rows,
            align="lrrrrr",
            numeric_columns=[1, 2, 3, 4, 5],
            label="tab:b1-areas",
        )
    ]
    if problems:
        tables.append(
            Table(
                caption="Places missing from one lookup, or with a non-positive land area",
                columns=["Geography", "Problem", "Identifier"],
                rows=problems,
                align="lll",
            )
        )

    return Result(
        id="B1", section="B", title="", tier=2,
        status="pass" if not problems else "fail",
        metrics=[
            Metric("Geography levels compared", len(rows)),
            Metric("Named places", named_total),
            Metric("Places with a published area", area_total, expected=named_total),
            Metric("Named places with no area", missing_total, expected=0),
            Metric("Areas with no name", extra_total, expected=0),
            Metric("Land areas of zero or below", nonpositive_total, expected=0),
        ],
        tables=tables,
    )


@check(
    id="B2",
    section="B",
    title="Land area totals are plausible and agree across geography levels",
    tier=2,
    claim=(
        "Every geography level that tiles the country reports the same total land area, "
        "and that total is within one percent of the figure the Census Bureau publishes "
        "for the fifty states and the District of Columbia."
    ),
    method=(
        "Published land areas are summed per level. Levels the registry marks as "
        "complete-coverage are compared against each other and against the Census figure; "
        "partial-coverage levels are reported but excluded from the comparison, since they "
        "are not expected to reach it."
    ),
    interpretation=(
        "Agreement between levels is stronger evidence than the magnitude check. County, "
        "PUMA and state areas are read from three separately published TIGER layers and "
        "commuting zones are summed from counties, so a level that disagrees points at a "
        "specific artifact rather than at a systematic error. The Census total is a "
        "magnitude check only: TIGER revises per-polygon areas between vintages and does "
        "not reproduce the published figure exactly, so the tolerance is set to pass a "
        "boundary revision while failing a unit error or a dropped state. Partial-coverage "
        "levels fall short by construction --- metropolitan areas do not cover rural land, "
        "and ZIP Code Tabulation Areas leave gaps over unpopulated terrain."
    ),
)
def b2_land_area_totals(ctx: Context) -> Result:
    levels = ctx.lookup_geographies("areas")
    if not levels:
        return Result(
            id="B2", section="B", title="", tier=2, status="skip",
            skipped_because="no area lookups are published",
        )

    reg = config.registry()["geographies"]
    rows, complete_totals = [], {}
    for geography in levels:
        areas = ctx.lookup("areas", geography)
        if not areas:
            continue
        land = sum(v.get("aland_m2", 0) for v in areas.values())
        water = sum(v.get("awater_m2", 0) for v in areas.values())
        complete = reg.get(geography, {}).get("complete_coverage", True)
        rows.append([
            geography,
            "complete" if complete else "partial",
            len(areas),
            land / 1e6,
            water / 1e6,
            100.0 * (land / 1e6) / US_LAND_AREA_KM2,
        ])
        if complete:
            complete_totals[geography] = land

    # Rounded to the square kilometre before comparing: these are integers in
    # square metres summed over thousands of polygons, and an exact-equality
    # test would fail on an arithmetic artifact rather than on a real
    # disagreement.
    distinct = {round(v / 1e6) for v in complete_totals.values()}
    agree = len(distinct) <= 1

    reference = round(next(iter(complete_totals.values())) / 1e6) if complete_totals else 0
    deviation = abs(reference - US_LAND_AREA_KM2) / US_LAND_AREA_KM2 if reference else 1.0
    plausible = deviation <= US_LAND_TOLERANCE

    return Result(
        id="B2", section="B", title="", tier=2,
        status="pass" if (agree and plausible) else "fail",
        metrics=[
            Metric("Complete-coverage levels compared", len(complete_totals)),
            Metric("Distinct land-area totals among them", len(distinct), expected=1),
            Metric("Land area reported", reference, unit="km2"),
            Metric("Census published figure", US_LAND_AREA_KM2, unit="km2"),
            Metric("Deviation", round(100 * deviation, 3), unit="%"),
            Metric("Tolerance", round(100 * US_LAND_TOLERANCE, 3), unit="%"),
        ],
        tables=[
            Table(
                caption="Published land and water area by geography level",
                columns=["Geography", "Coverage", "Places", "Land (km\\textsuperscript{2})",
                         "Water (km\\textsuperscript{2})", "Share of US land (\\%)"],
                rows=rows,
                align="llrrrr",
                numeric_columns=[2, 3, 4, 5],
                note=(
                    "Areas are TIGER's own ALAND and AWATER attributes, not measurements of "
                    "the simplified geometry this site serves for the map. Measuring the "
                    "simplified shapes would give areas for polygons nobody treats as "
                    "authoritative and would disagree with every other source quoting the "
                    "Census figure."
                ),
                label="tab:b2-land-area",
            )
        ],
    )
