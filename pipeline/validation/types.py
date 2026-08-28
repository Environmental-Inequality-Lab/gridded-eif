"""The record every validation check returns.

One check produces one :class:`Result`. That is deliberate: the report renders
one numbered subsection per result, so a check that wants to say three things
should either say them in three tables or be split into three checks. Letting a
check return a list would make the document's numbering depend on runtime data,
and a citable appendix cannot have section numbers that move between runs.

Results are serialisable to JSON without loss. The PDF is one renderer over
``results.json``; nothing in the document is authored by hand, so a figure in
the appendix and an assertion in CI cannot disagree about what the pipeline
does.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# `warn` is for a finding that is real but not a defect — a documented
# shortfall, an expected divergence. `info` carries no judgement at all and
# exists for manifests and characterisations. `skip` records that a check could
# not run (missing credential, unbuilt artifact) and must never be read as a
# pass: a report full of silent skips is the failure mode this whole exercise
# is meant to prevent.
Status = Literal["pass", "fail", "warn", "info", "skip"]

STATUS_ORDER: dict[str, int] = {"fail": 0, "warn": 1, "skip": 2, "info": 3, "pass": 4}


@dataclass
class Table:
    """Tabular evidence, rendered as a booktabs table.

    `align` is a LaTeX column spec ("lrrr"). Numeric columns should be right
    aligned and pass through siunitx, which is why numbers are carried as
    numbers here and formatted at render time rather than pre-formatted into
    strings by the check.
    """

    caption: str
    columns: list[str]
    rows: list[list[Any]]
    align: str | None = None
    note: str | None = None
    # Columns to render through siunitx's number formatting. Indices, not
    # names, so a renamed column heading cannot silently change alignment.
    numeric_columns: list[int] = field(default_factory=list)
    label: str | None = None


@dataclass
class Figure:
    caption: str
    path: str  # relative to the report output directory
    label: str
    width: str = r"\textwidth"


@dataclass
class Metric:
    """One measured quantity: a fixed label and a computed value.

    This is what replaces a written finding. The label is authored once and
    never varies; only the number moves. A metric with an `expected` renders it
    alongside, so a reader sees the target without a sentence explaining it.
    """

    label: str
    value: Any
    unit: str = ""
    expected: Any = None


@dataclass
class Result:
    """What one check measured.

    **No prose is produced here.** Every sentence in the report comes from the
    check's registration — `claim`, `method`, `interpretation` — and is written
    once, by hand, for all time. A result carries a verdict, numbers, tables and
    figures, and nothing else.

    That constraint is the point. Prose assembled at runtime from branching
    conditionals reads perfectly fluently while quietly going out of date: the
    branch that fires in 2029 may describe a situation that no longer holds, and
    nobody rereads a paragraph that still scans. Numbers cannot go stale that
    way — they are either measured this run or absent. So the document's words
    are fixed and only its figures move.
    """

    id: str  # "C1" — stable, citable, never renumbered
    section: str  # "C"
    title: str
    tier: int
    status: Status

    # Stamped from the registration by `run()`; never written by a check body.
    claim: str = ""
    method: str = ""
    interpretation: str = ""

    metrics: list[Metric] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    # Every query behind a number, reproduced verbatim in the appendix. A
    # reader who cannot re-run our arithmetic has to take it on trust, which
    # defeats the point of publishing a validation document at all.
    sql: list[str] = field(default_factory=list)

    # Set only when a check could not run at all. Free text by necessity — it is
    # a Python traceback — and rendered as such rather than as narrative.
    skipped_because: str | None = None

    runtime_s: float = 0.0
    error: str | None = None

    def metric(self, label: str) -> Any:
        for m in self.metrics:
            if m.label == label:
                return m.value
        raise KeyError(label)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunMetadata:
    """Provenance for the run itself, printed on the title page.

    Without the commit hash a validation report is an undated assertion about
    an unspecified version of the code.
    """

    generated_at: str
    commit: str
    commit_dirty: bool
    pipeline_version: str
    registry_version: str
    contract_version: str
    derived_version: str
    python_version: str
    duckdb_version: str
    platform: str
    tiers_run: list[int]
    sections_run: list[str]
    target: str
