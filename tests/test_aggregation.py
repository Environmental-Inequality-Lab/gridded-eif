"""Regression tests against verified 2022 figures.

These numbers were established by direct inspection of the source files and are
verified against the source files. If a pipeline change moves them, that is either a bug
or a deliberate MAJOR version bump — never a silent adjustment.

Marked `network` because they read the built artifacts; skipped when absent.
"""


from pathlib import Path

import duckdb
import pytest

from pipeline import config

BUILT = config.REPO_ROOT / ".build" / config.derived_key("ageracesex", "county", 2022)

# Verified national totals, raw measure, 2022.
EXPECTED_2022 = {
    "White": 181_814_741,
    "Hispanic": 50_773_661,
    "Black": 38_020_972,
    "Other/Unknown": 33_192_479,
    "Asian": 13_380_040,
    "AIAN": 2_749_175,
}
EXPECTED_TOTAL = sum(EXPECTED_2022.values())


@pytest.fixture(scope="module")
def county_2022() -> duckdb.DuckDBPyConnection:
    if not BUILT.exists():
        pytest.skip("not built: run `geif build --geography county --year 2022`")
    con = duckdb.connect()
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{BUILT.as_posix()}')")
    return con


def test_aggregation_is_lossless(county_2022):
    """Every person in the source must land in exactly one county.

    This is the border-cell guard: 222 cells straddle the US-Canada and
    US-Mexico borders with centroids outside the country, and without the
    nearest-polygon snap they would silently vanish.
    """
    total = county_2022.execute("SELECT sum(n_noise) FROM t").fetchone()[0]
    assert round(total) == EXPECTED_TOTAL


def test_race_totals_match_source(county_2022):
    got = dict(county_2022.execute(
        "SELECT race_ethnicity, round(sum(n_noise)) FROM t GROUP BY 1"
    ).fetchall())
    for race, expected in EXPECTED_2022.items():
        assert int(got[race]) == expected, f"{race} drifted"


def test_all_counties_present_and_no_territories(county_2022):
    """3,144 counties have data; the 91 TIGER units without any are Puerto Rico,
    USVI, Guam, American Samoa, and the Marianas, which the product excludes."""
    n = county_2022.execute("SELECT count(DISTINCT geo_id) FROM t").fetchone()[0]
    assert n == 3144
    territories = county_2022.execute(
        "SELECT count(*) FROM t WHERE substr(geo_id,1,2) IN ('72','78','66','60','69')"
    ).fetchone()[0]
    assert territories == 0


def test_postprocessed_is_never_negative(county_2022):
    n = county_2022.execute("SELECT count(*) FROM t WHERE n_noise_postprocessed < 0").fetchone()[0]
    assert n == 0


def test_postprocessing_preserves_race_totals(county_2022):
    """Redistribution happens within race groups, so race margins must survive."""
    for race, raw, pp in county_2022.execute(
        "SELECT race_ethnicity, sum(n_noise), sum(n_noise_postprocessed) FROM t GROUP BY 1"
    ).fetchall():
        assert abs(raw - pp) < 1000, f"{race}: {raw:,.0f} vs {pp:,.0f}"


def test_postprocessing_shifts_the_age_margin(county_2022):
    """Documents a real, undocumented property rather than asserting it away.

    Post-processing moves roughly 800k people into 'Over 65' nationally (~1.5%),
    because it redistributes evenly across cell-sparse categories and the
    elderly are sparse in exactly that way. If this ever stops
    being true, Census changed the algorithm and our guidance needs revisiting.
    """
    raw, pp = county_2022.execute(
        "SELECT sum(n_noise), sum(n_noise_postprocessed) FROM t WHERE age_group = 'Over 65'"
    ).fetchone()
    assert pp > raw, "expected post-processing to inflate the 65+ count"
    assert 0.005 < (pp - raw) / raw < 0.05, f"shift {(pp - raw) / raw:.3%} outside documented range"


def test_alaska_and_hawaii_are_present(county_2022):
    """Guards against ever using eif_grid_topology.rda as the grid definition —
    it is CONUS-only and would silently delete 1.45M people."""
    for fips, name in [("02", "Alaska"), ("15", "Hawaii")]:
        pop = county_2022.execute(
            f"SELECT sum(n_noise) FROM t WHERE substr(geo_id,1,2) = '{fips}'"
        ).fetchone()[0]
        assert pop and pop > 100_000, f"{name} missing or implausibly small: {pop}"


@pytest.fixture(scope="module")
def all_levels() -> dict[str, Path]:
    """Built partitions for every geography level available locally."""
    found = {}
    for level in ("nation", "state", "county"):
        path = config.REPO_ROOT / ".build" / config.derived_key("ageracesex", level, 2022)
        if path.exists():
            found[level] = path
    if len(found) < 2:
        pytest.skip("need at least two geography levels built for 2022")
    return found


def test_totals_agree_across_geography_levels(all_levels):
    """Aggregating to a coarser geography must not create or lose people.

    Every level is built independently from the same grid cells, so agreement is
    a genuine end-to-end check on the crosswalks: a cell dropped by one level's
    spatial join but kept by another would show up here as a mismatch, where a
    single-level test would see nothing wrong.
    """
    con = duckdb.connect()
    totals = {
        level: con.execute(
            f"SELECT round(sum(n_noise)) FROM read_parquet('{path.as_posix()}')"
        ).fetchone()[0]
        for level, path in all_levels.items()
    }
    distinct = set(totals.values())
    assert len(distinct) == 1, f"levels disagree: {totals}"
    assert distinct.pop() == EXPECTED_TOTAL


def test_geography_unit_counts_are_plausible(all_levels):
    con = duckdb.connect()
    expected = {"nation": 1, "state": 51, "county": 3144}  # 51 = 50 states + DC
    for level, path in all_levels.items():
        n = con.execute(
            f"SELECT count(DISTINCT geo_id) FROM read_parquet('{path.as_posix()}')"
        ).fetchone()[0]
        assert n == expected[level], f"{level}: {n} units, expected {expected[level]}"


@pytest.fixture(scope="module")
def combined_county() -> Path:
    path = config.REPO_ROOT / ".build" / config.combined_key("ageracesex", "county")
    if not path.exists():
        pytest.skip("run `geif combine --geography county` first")
    return path


def test_combined_file_matches_its_per_year_partitions(combined_county):
    """The all-years file must be a faithful concatenation.

    It exists purely as a latency optimisation — a 25-year national series reads
    66 KB across 25 files and takes ~5s in a browser, dominated by per-file round
    trips. An optimisation that changed the numbers would be far worse than the
    latency it saves, so every year present locally is checked against its
    source partition.
    """
    con = duckdb.connect()
    years = [
        r[0] for r in con.execute(
            f"SELECT DISTINCT year FROM read_parquet('{combined_county.as_posix()}') ORDER BY 1"
        ).fetchall()
    ]
    assert len(years) >= 2, "combined file should span multiple years"

    checked = 0
    for year in years:
        per_year = config.REPO_ROOT / ".build" / config.derived_key("ageracesex", "county", year)
        if not per_year.exists():
            continue  # that year came from the CDN, not rebuilt locally
        a = con.execute(
            f"SELECT round(sum(n_noise)) FROM read_parquet('{combined_county.as_posix()}') "
            f"WHERE year = {year}"
        ).fetchone()[0]
        b = con.execute(
            f"SELECT round(sum(n_noise)) FROM read_parquet('{per_year.as_posix()}')"
        ).fetchone()[0]
        assert a == b, f"{year}: combined {a:,.0f} != per-year {b:,.0f}"
        checked += 1
    assert checked, "no locally built years available to compare"


def test_combined_file_stays_prunable(combined_county):
    """Sorting by geo_id must survive concatenation.

    Without it the combined file would trade one problem for another: a single
    round trip, but scanning tens of megabytes to answer a one-county question.
    """
    con = duckdb.connect()
    groups = con.execute(f"""
        SELECT row_group_id, min(stats_min) lo, max(stats_max) hi
        FROM parquet_metadata('{combined_county.as_posix()}')
        WHERE path_in_schema = 'geo_id' GROUP BY 1
    """).df()
    hits = groups[(groups.lo <= "26163") & (groups.hi >= "26163")]
    assert len(groups) > 10, "too few row groups for pruning to help"
    assert len(hits) / len(groups) < 0.1, (
        f"one county touches {len(hits)}/{len(groups)} row groups — sort order lost"
    )
