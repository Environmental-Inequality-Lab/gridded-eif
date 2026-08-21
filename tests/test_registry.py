"""Registry and contract consistency.

These run without network access. They guard the invariant that the registry is
the single source of truth: if these fail, config and contract have drifted
apart and the pipeline will build something nobody intended.
"""

from pipeline import config


def test_registry_loads():
    reg = config.registry()
    assert reg["registry_version"]
    assert reg["grid"]["crs"] == "EPSG:4326"


def test_enabled_datasets_are_the_two_population_files():
    assert set(config.datasets()) == {"ageracesex", "raceincome"}


def test_every_dataset_dimension_is_defined():
    dims = config.registry()["dimensions"]
    for ds in config.datasets().values():
        for d in ds.dimensions:
            assert d in dims, f"{ds.name} references undefined dimension {d!r}"


def test_registry_categories_match_the_contract():
    """The registry drives the UI; the contract validates the source. If they
    disagree, the site would offer a filter the data cannot satisfy."""
    contract = config.contract()["datasets"]
    for name, ds in config.datasets().items():
        for dim in ds.dimensions:
            declared = {v["code"] for v in config.registry()["dimensions"][dim]["values"]}
            expected = set(contract[name]["categories"][dim])
            assert declared == expected, f"{name}.{dim}: registry {declared} != contract {expected}"


def test_exactly_one_default_measure():
    assert config.default_measure() == "n_noise_postprocessed"


def test_derived_paths_are_version_prefixed():
    """Published URLs get cited. A MAJOR bump must write beside the old tree,
    never over it."""
    key = config.derived_key("ageracesex", "county", 2022)
    assert key.startswith("derived/v1/")
    assert key == "derived/v1/ageracesex/county/2022/part-00.parquet"


def test_block_group_is_not_offered():
    """A 0.01 degree cell is about the size of a median block group, so that
    level would imply precision the privacy noise cannot support."""
    assert "block_group" not in config.registry()["geographies"]
    assert "blockgroup" not in config.registry()["geographies"]


def test_population_datasets_are_marked_non_joinable():
    """No age-by-income cross exists; the UI relies on this to make an
    impossible query structurally unreachable."""
    ri = config.registry()["datasets"]["raceincome"]
    assert "ageracesex" in ri["not_joinable_with"]


def test_age_labels_are_verbatim():
    """We reproduce '19-65' exactly as published rather than inventing a
    corrected label, because the correct one is unconfirmed."""
    age = config.registry()["dimensions"]["age_group"]
    assert age["verbatim_from_source"] is True
    assert {v["code"] for v in age["values"]} >= {"Under 18", "19-65", "Over 65"}
    assert age["footnote"]


def test_catalog_merge_preserves_partitions_built_elsewhere():
    """A CI runner starts with an empty build directory, so a job that rebuilds
    one year knows about only that year. Without merging, publishing would
    replace a catalog describing every year with one describing a single year —
    the Parquet would remain in S3 but the site, which reads only the catalog,
    would stop seeing it.
    """
    from pipeline.catalog import _merge_entries

    published = [
        {"dataset": "ageracesex", "geography": "county", "year": 2021, "rows": 1},
        {"dataset": "ageracesex", "geography": "county", "year": 2022, "rows": 1},
    ]
    rebuilt = [
        {"dataset": "ageracesex", "geography": "county", "year": 2022, "rows": 999},
        {"dataset": "ageracesex", "geography": "county", "year": 2023, "rows": 1},
    ]
    merged = _merge_entries(published, rebuilt)

    assert [e["year"] for e in merged] == [2021, 2022, 2023], "2021 must survive the rebuild"
    by_year = {e["year"]: e for e in merged}
    assert by_year[2022]["rows"] == 999, "a rebuilt partition must win over the published one"


def test_parse_years_accepts_ranges_and_lists():
    from pipeline.config import parse_years

    assert parse_years("2022", "ageracesex") == [2022]
    assert parse_years("2018-2020", "ageracesex") == [2018, 2019, 2020]
    assert parse_years("2018,2020-2022", "ageracesex") == [2018, 2020, 2021, 2022]
    assert parse_years(" 2019 , 2021 ", "ageracesex") == [2019, 2021]
    assert parse_years("all", "ageracesex")[0] == 2000  # 1999 excluded


def test_parse_years_rejects_unavailable_years():
    """A typo in a backfill must fail immediately, not quietly build less than
    was asked for and leave a gap nobody notices."""
    import pytest

    from pipeline.config import parse_years

    with pytest.raises(ValueError, match="no data for"):
        parse_years("1990-1995", "ageracesex")
    # 1999 is deliberately excluded — asking for it must fail loudly rather than
    # quietly produce a series with an anomalous first year.
    with pytest.raises(ValueError, match="excludes"):
        parse_years("1999", "ageracesex")
    # ...including when it is merely swept up in a wider range.
    with pytest.raises(ValueError, match="excludes"):
        parse_years("1999-2005", "ageracesex")
    with pytest.raises(ValueError, match="runs backwards"):
        parse_years("2022-2018", "ageracesex")
    with pytest.raises(ValueError, match="bad year"):
        parse_years("twenty-twenty", "ageracesex")


def test_excluded_years_are_enforced_independently_of_the_declared_range():
    """The exclusion must not be an artifact of where `years:` happens to start.

    Someone widening the registry's year range later should not silently
    re-admit a year that was ruled out on purpose, so exclusions are checked
    separately rather than relying on the range to keep them out.
    """
    import pytest

    from pipeline.config import Dataset, parse_years

    ds = config.datasets()["ageracesex"]
    assert 1999 in ds.excluded_years
    assert ds.excluded_years[1999]                     # carries a reason
    assert 1999 not in ds.all_years()

    # Even a dataset whose declared range includes the excluded year keeps it out.
    widened = Dataset(
        name=ds.name, label=ds.label, enabled=True,
        file_pattern=ds.file_pattern, dimensions=ds.dimensions,
        years=tuple(range(1999, 2025)), preliminary_years=(),
        preliminary_file_pattern=None, unit=ds.unit,
        excluded_years=ds.excluded_years,
    )
    assert 1999 not in widened.all_years()

    with pytest.raises(ValueError, match="excludes"):
        parse_years("1999", "ageracesex")


def test_no_completeness_figures_are_published():
    """Completeness diagnostics were deliberately deferred. The registry should
    not carry unsourced reference populations that could be mistaken for
    authoritative, and the catalog should not emit a derived figure."""
    assert "completeness" not in config.registry()
    assert "coverage" not in config.registry()


def test_no_year_examples_reference_the_excluded_year():
    """Copy-pasteable examples must not name a year that will be rejected.

    Help text, docs, and the workflow input description are all things someone
    copies verbatim; an example of "1999-2024" would fail immediately and look
    like a broken tool rather than a deliberate exclusion.
    """

    excluded = set(config.datasets()["ageracesex"].excluded_years)
    root = config.REPO_ROOT
    targets = [
        root / ".github" / "workflows" / "refresh-data.yml",
        root / "pipeline" / "cli.py",
        root / "README.md",
    ]
    for path in targets:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            # Only inspect lines that look like a usage example.
            if "--year" not in line and "Year, range, or list" not in line:
                continue
            for year in excluded:
                assert str(year) not in line, (
                    f"{path.name}:{lineno} uses excluded year {year} in an example: {line.strip()}"
                )


def test_catalog_carries_everything_the_ui_renders_from():
    """The site builds its facets, geography list, and measure guidance from the
    catalog rather than hardcoding them — that is what lets new data appear
    without a site rebuild. A missing key here does not fail the pipeline; it
    silently breaks the UI, which is how these went missing once already.
    """
    import json

    from pipeline import aggregate
    from pipeline import catalog as catalog_mod

    part = aggregate.Partition(
        dataset="ageracesex", geography="county", year=2022,
        path="derived/v1/ageracesex/county/2022/part-00.parquet",
        rows=1, bytes=1, sha256="x", preliminary=False,
        pipeline_version="test", total_raw=1.0, total_postprocessed=1.0, geo_units=1,
    )
    cat = catalog_mod.build([part], "https://example.test")

    for key in ("measures", "measure_selection_population_threshold",
                "dimensions", "geographies", "datasets", "entries",
                "combined", "source", "grid", "aggregation"):
        assert key in cat, f"catalog is missing {key!r}, which the UI depends on"

    # The dimensions actually referenced by a dataset must be described.
    for dim in cat["datasets"]["ageracesex"]["dimensions"]:
        assert dim in cat["dimensions"], f"dimension {dim!r} has no definition"
        assert cat["dimensions"][dim].get("values"), f"dimension {dim!r} has no values"

    # Every geography that appears in an entry must have a label.
    for e in cat["entries"]:
        assert e["geography"] in cat["geographies"], f"no metadata for {e['geography']}"
        assert cat["geographies"][e["geography"]].get("label")

    json.dumps(cat)   # must be serialisable


def test_preliminary_years_resolve_to_realtime_files():
    """2025 is a preliminary vintage published under a different filename.

    It must be reachable, correctly flagged, and resolve to the _realtime file —
    a mismatch here would either 404 or, worse, silently build a final-looking
    partition from preliminary data.
    """
    ds = config.datasets()["ageracesex"]
    assert 2025 in ds.preliminary_years
    assert config.parse_years("2025", "ageracesex") == [2025]
    assert ds.is_preliminary(2025)
    assert ds.filename(2025).endswith("_2025_realtime.parquet")
    assert not ds.is_preliminary(2024)
    assert ds.filename(2024).endswith("_2024.parquet")


def test_preliminary_years_are_excluded_from_the_final_range():
    """`years:` covers final vintages only, so a caller asking for the final
    range never silently picks up preliminary data."""
    for ds in config.datasets().values():
        overlap = set(ds.years) & set(ds.preliminary_years)
        assert not overlap, f"{ds.name}: {sorted(overlap)} declared both final and preliminary"


def test_partial_coverage_geographies_do_not_snap():
    """Snapping is only valid where a geography tiles the country.

    CBSAs cover metro and micropolitan areas only — about 94% of grid cells
    fall outside one. Snapping those to the nearest metro would move rural
    population hundreds of kilometres into a city that does not contain it, and
    the result would look entirely plausible: totals near the national figure,
    every unit populated. It inflated the CBSA total from 303.7M to 317.3M
    before this was caught.
    """
    geos = config.geographies()
    assert geos["cbsa"].complete_coverage is False
    assert geos["zcta"].complete_coverage is False

    # Geographies that do tile the country must keep snapping, or genuine
    # border cells would be dropped instead.
    for name in ("county", "state", "tract", "puma", "cd"):
        assert geos[name].complete_coverage is True, f"{name} should be complete-coverage"


def test_partial_coverage_geographies_carry_a_caveat():
    """A total that does not sum to the national figure needs saying so, or a
    user comparing CBSA to state totals will assume the data is broken."""
    reg = config.registry()["geographies"]
    for name, spec in reg.items():
        if spec.get("complete_coverage", True) is False:
            assert spec.get("caveat") or name == "zcta", f"{name} needs a caveat"
