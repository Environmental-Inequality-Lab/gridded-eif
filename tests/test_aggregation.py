"""Regression tests against verified 2022 figures.

These numbers were established by direct inspection of the source files and are
verified against the source files. If a pipeline change moves them, that is either a bug
or a deliberate MAJOR version bump — never a silent adjustment.

Marked `network` because they read the built artifacts; skipped when absent.
"""


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
