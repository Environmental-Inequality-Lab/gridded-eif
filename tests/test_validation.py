"""The validation registry, enforced as tests.

The report and the test suite are two renderings of one set of facts. That is
the property worth protecting: a check that appears in a published appendix but
is not enforced anywhere is a claim nobody is checking, and a check enforced in
CI but absent from the appendix is work nobody can see.

Only tier 0 and 1 checks execute here. Tiers 2 and 3 read the network and
belong to `geif validate-report`, not to a test run that has to finish in
seconds.
"""

from __future__ import annotations

import re

import pytest

from pipeline.validation import registry
from pipeline.validation.registry import SECTIONS
from pipeline.validation.report import _render_table, render, tex_escape
from pipeline.validation.types import Metric, Result, Table

ALL = registry.all_checks()


def test_at_least_one_check_is_registered():
    assert ALL, "no checks registered — the import of a check module probably failed silently"


@pytest.mark.parametrize("c", ALL, ids=lambda c: c.id)
def test_check_metadata_is_well_formed(c):
    assert re.fullmatch(r"[A-F]\d+", c.id), f"{c.id} is not a citable id of the form A1"
    assert c.id[0] == c.section, f"{c.id} is filed under section {c.section}"
    assert c.section in SECTIONS
    assert 0 <= c.tier <= 3
    assert c.title and not c.title.endswith("."), "titles are noun phrases, not sentences"
    # The claim is printed above the result, so it has to read as an assertion
    # about the data, not as a description of the function.
    assert len(c.claim) > 40, f"{c.id} has no substantive claim"
    assert not c.claim.lower().startswith(("check", "test", "verif")), (
        f"{c.id}'s claim describes the code rather than asserting something about the data"
    )
    assert len(c.method) > 30, f"{c.id} does not say how it measures anything"
    assert len(c.interpretation) > 60, f"{c.id} does not say how to read its result"


@pytest.mark.parametrize("c", ALL, ids=lambda c: c.id)
def test_check_prose_does_not_depend_on_the_outcome(c):
    """The report's words are fixed; only its numbers move.

    Prose assembled at runtime reads fluently while quietly going out of date —
    the branch that fires in some future year may describe a situation that no
    longer holds, and nobody rereads a paragraph that still scans. The three
    prose fields are therefore plain strings on the registration, and this test
    exists to keep them that way.
    """
    for field in ("claim", "method", "interpretation"):
        text = getattr(c, field)
        assert isinstance(text, str)
        # LaTeX commands legitimately carry braces, so strip those first; a brace
        # surviving that is a format placeholder, which means a value was meant
        # to be interpolated into a sentence.
        bare = re.sub(r"\\[a-zA-Z]+\{[^{}]*\}", "", text)
        assert "{" not in bare and "}" not in bare, (
            f"{c.id}.{field} looks like a template — prose must not interpolate values"
        )


def test_ids_are_unique_and_ordered():
    ids = [c.id for c in ALL]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids, key=lambda i: (i[0], int(i[1:])))


def test_every_section_letter_is_declared():
    for c in ALL:
        assert c.section in SECTIONS


OFFLINE = [c for c in ALL if c.tier <= 1]


@pytest.mark.skipif(not OFFLINE, reason="no tier 0/1 checks are registered yet")
@pytest.mark.parametrize("c", OFFLINE or [None], ids=lambda c: c.id if c else "none")
def test_offline_checks_do_not_fail(c, tmp_path):
    """Tier 0 and 1 checks touch no network, so they run on every push.

    A `warn` is allowed through: it records a real finding that is not a defect,
    and turning warnings into failures is how a suite gets switched off.
    """
    ctx = registry.Context(out_dir=tmp_path, max_tier=1)
    result = registry.run([c], ctx)[0]
    assert result.status != "fail", result.skipped_because or "check failed"


def test_tier_zero_and_one_checks_touch_no_network():
    """The tier is a promise about what a check reads, not about how fast it is.

    Enforced by inspection rather than by sandboxing: a check that mentions the
    catalog or a URL is reaching past the local build tree, whatever its
    declared tier says.
    """
    import inspect

    for c in OFFLINE:
        src = inspect.getsource(c.fn)
        for reach in ("ctx.catalog(", "requests.", "http://", "https://"):
            assert reach not in src, (
                f"{c.id} is declared tier {c.tier} but reaches the network via {reach!r}"
            )


def test_head_lowercases_header_names(monkeypatch):
    """Regression: `dict(requests_headers)` keeps the server's casing.

    The mapping requests returns is case-insensitive; a plain dict of it is
    not. A lookup for `content-length` then misses a `Content-Length` and the
    caller concludes the header was absent — which reported 378 size
    mismatches against a CDN that was serving every file correctly.
    """
    import requests.structures

    from pipeline.validation import provenance

    class FakeResponse:
        status_code = 200
        headers = requests.structures.CaseInsensitiveDict({"Content-Length": "123"})

    monkeypatch.setattr(provenance.requests, "head", lambda *a, **k: FakeResponse())
    status, headers, err = provenance._head("https://example.invalid/x")
    assert (status, err) == (200, None)
    assert headers["content-length"] == "123"


# --- renderer -----------------------------------------------------------------


def test_tex_escape_neutralises_latex_metacharacters():
    assert tex_escape("St. Mary's & Co. #1_2 100%") == r"St. Mary's \& Co. \#1\_2 100\%"
    assert tex_escape(None) == "---"


def test_numeric_cells_render_through_siunitx():
    t = Table(
        caption="x", columns=["a", "b"], rows=[["Wayne County, MI", 1234567]],
        numeric_columns=[1],
    )
    out = _render_table(t)
    assert r"\num{1234567}" in out
    assert "Wayne County, MI" in out


def test_long_tables_become_longtables():
    rows = [[i, i] for i in range(60)]
    out = _render_table(Table(caption="x", columns=["a", "b"], rows=rows, numeric_columns=[0, 1]))
    assert "longtable" in out and "\\endhead" in out


def test_render_produces_a_complete_document(tmp_path):
    """The template must survive a result carrying every optional field, and one
    carrying none — the two shapes most likely to break it."""
    meta = registry.metadata(tiers=[0], sections=["A"])
    full = Result(
        id="A1", section="A", title="Something", tier=0, status="fail",
        claim="A claim long enough to look like a claim rather than a label.",
        method="How it was measured.",
        interpretation="What a departure would mean, and what it would not.",
        metrics=[Metric("Things counted", 3, expected=0, unit="things")],
        tables=[Table(caption="T", columns=["a"], rows=[["x_1"]], note="A note.")],
        sql=["SELECT 1"], error="Traceback...",
    )
    bare = Result(
        id="C1", section="C", title="Other", tier=0, status="skip",
        claim="Another claim, also long enough to pass the metadata assertions.",
        skipped_because="RuntimeError: nothing to read",
    )
    tex = render([full, bare], meta, tmp_path).read_text()
    assert r"\begin{document}" in tex and r"\end{document}" in tex
    assert r"\stfail" in tex and r"\stskip" in tex
    # Sections with no results must still appear, so an unimplemented section is
    # visible in the document rather than silently missing.
    for key in SECTIONS:
        assert f"\\label{{sec:{key}}}" in tex


# --- environment robustness ---------------------------------------------------


def test_base_url_prefers_the_environment(monkeypatch, tmp_path):
    """Regression: a fresh CI checkout has no committed catalog.

    `site/catalog.json` is gitignored, so the runner had no base URL and the
    report's inventory could not be built. GEIF_BASE_URL is what the pipeline
    and both workflows already use.
    """
    monkeypatch.setenv("GEIF_BASE_URL", "https://example.invalid/cdn/")
    ctx = registry.Context(out_dir=tmp_path)
    assert ctx._base_url() == "https://example.invalid/cdn"


def test_figures_fall_back_when_tex_is_absent(monkeypatch):
    """Regression: a data check failed because the runner had no LaTeX.

    `matplotlib.use("pgf")` succeeds with no TeX installed and defers the
    failure to savefig, so a try/except around backend selection caught nothing.
    The decision has to be made by looking for the binary.
    """
    import matplotlib

    from pipeline.validation import figures

    before = matplotlib.get_backend()
    monkeypatch.setattr(figures.shutil, "which", lambda _name: None)
    monkeypatch.setattr(figures, "_configured", False)
    try:
        figures._configure()
        assert matplotlib.rcParams["text.usetex"] is False
    finally:
        matplotlib.use(before)
        figures._configured = False


def test_a_failed_figure_does_not_fail_its_check(monkeypatch, tmp_path):
    """A verdict must rest on the data, not on the runner's font stack."""
    import matplotlib.pyplot as plt

    from pipeline.validation import figures

    fig = plt.figure()
    monkeypatch.setattr(
        fig, "savefig",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("'pdflatex' not found")),
    )
    monkeypatch.setattr(figures, "_configured", True)
    assert figures._save(fig, registry.Context(out_dir=tmp_path), "x") is False


def test_no_pdf_runs_skip_figure_rendering(tmp_path):
    """Drawing figures for a document nobody renders can only lose."""
    from pipeline.validation import figures

    assert figures.wanted(registry.Context(out_dir=tmp_path)) is True
    assert figures.wanted(registry.Context(out_dir=tmp_path, render_figures=False)) is False
