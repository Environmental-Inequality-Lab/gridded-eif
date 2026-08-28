"""Renders executed check results into a typeset PDF.

The document is a pure function of ``results.json`` plus the figures the checks
wrote. Nothing is authored here, which is the property that keeps the appendix
honest: to change what the report says you have to change what the pipeline
does.

**Escaping convention.** Prose authored by hand --- a check's ``claim``,
``method`` and ``interpretation``, and a table's ``caption`` and ``note`` --- is
written *as LaTeX*, so it may contain ``\\%`` or ``---`` and mean it. Everything
derived from data --- table cells, metric labels and values, identifiers,
platform strings --- is escaped through the ``tex`` filter. Mixing the two
conventions is how a report ends up with a stray backslash in a county name, so
the split is by field, not by guesswork.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .registry import SECTIONS, TIER_NAMES
from .types import Metric, Result, RunMetadata, Table

TEMPLATE_DIR = Path(__file__).parent / "templates"

_TEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def tex_escape(value: Any) -> str:
    if value is None:
        return "---"
    return "".join(_TEX_ESCAPES.get(ch, ch) for ch in str(value))


def _fmt(value: Any) -> str:
    """Format a scalar for LaTeX, routing numbers through siunitx."""
    if value is None:
        return "---"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return rf"\num{{{value}}}"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return rf"\num{{{int(value)}}}"
        return rf"\num{{{value:.3f}}}"
    return tex_escape(value)


_STATUS_MACROS = {
    "pass": r"\stpass",
    "fail": r"\stfail",
    "warn": r"\stwarn",
    "skip": r"\stskip",
    "info": r"\stinfo",
}

# Above this many rows a table is set as a longtable so it breaks across pages
# instead of being silently floated to the end of the document or overflowing.
LONGTABLE_THRESHOLD = 24


def _render_table(t: Table | dict) -> str:
    if isinstance(t, dict):
        t = Table(**t)
    ncols = len(t.columns)
    # Fixed-width columns are declared as p{} at the call site and rendered as
    # the ragged-right P{} variant, so no check has to remember the distinction.
    align = (t.align or ("l" + "r" * (ncols - 1))).replace("p{", "P{")
    # A year is an integer but not a quantity: siunitx would set 2000 as
    # "2,000". Suppressed here as well as at the declaration site so the next
    # check to tabulate a year does not have to remember.
    never_grouped = {i for i, c in enumerate(t.columns) if c.strip().lower() == "year"}
    header = " & ".join(rf"\textbf{{{c}}}" for c in t.columns) + r" \\"

    body_lines = []
    for row in t.rows:
        cells = []
        for i, cell in enumerate(row):
            declared_numeric = (
                i in (t.numeric_columns or [])
                and isinstance(cell, (int, float))
                and not isinstance(cell, bool)
            )
            # A float is routed through siunitx whether or not the column was
            # declared numeric: an unformatted 0.4142857 in a table of
            # percentages is a typesetting bug, not a judgement call.
            if i in never_grouped:
                cells.append(tex_escape(cell))
            elif declared_numeric or isinstance(cell, float):
                cells.append(_fmt(cell))
            else:
                cells.append(tex_escape(cell))
        body_lines.append(" & ".join(cells) + r" \\")
    body = "\n".join(body_lines)

    label = f"\\label{{{t.label}}}" if t.label else ""
    note = ""
    if t.note:
        note = (
            "\n\\begin{tablenotes}\n\\footnotesize\n\\item "
            + t.note
            + "\n\\end{tablenotes}"
        )

    if len(t.rows) > LONGTABLE_THRESHOLD:
        # threeparttable does not cooperate with longtable, so the note is set
        # as a trailing paragraph instead of a real table note.
        trailing = f"\n\n\\noindent{{\\footnotesize {t.note}}}\n" if t.note else "\n"
        return (
            f"\\begin{{longtable}}{{@{{}}{align}@{{}}}}\n"
            f"\\caption{{{t.caption}}}{label}\\\\\n"
            f"\\toprule\n{header}\n\\midrule\n\\endfirsthead\n"
            f"\\toprule\n{header}\n\\midrule\n\\endhead\n"
            f"\\midrule\n\\multicolumn{{{ncols}}}{{r@{{}}}}{{\\footnotesize continued}}\\\\\n"
            f"\\endfoot\n\\bottomrule\n\\endlastfoot\n"
            f"{body}\n\\end{{longtable}}{trailing}"
        )

    return (
        "\\begin{table}[htbp]\n\\centering\n\\begin{threeparttable}\n"
        f"\\caption{{{t.caption}}}{label}\n"
        f"\\begin{{tabular}}{{@{{}}{align}@{{}}}}\n"
        f"\\toprule\n{header}\n\\midrule\n{body}\n\\bottomrule\n"
        f"\\end{{tabular}}{note}\n\\end{{threeparttable}}\n\\end{{table}}\n"
    )



def _render_metrics(metrics: list[Metric | dict]) -> str:
    """The measured quantities, as a compact table rather than a sentence.

    Labels are authored once and fixed; only the values move. An `expected`
    column appears only if some metric declares one, so checks that merely
    characterise something are not given a column of dashes to explain.
    """
    ms = [Metric(**m) if isinstance(m, dict) else m for m in metrics]
    show_expected = any(m.expected is not None for m in ms)

    lines = []
    for m in ms:
        cells = [tex_escape(m.label), _fmt(m.value) + (f"\\,{tex_escape(m.unit)}" if m.unit else "")]
        if show_expected:
            cells.append(_fmt(m.expected) if m.expected is not None else "---")
        lines.append(" & ".join(cells) + r" \\")

    align = "@{}lr" + ("r" if show_expected else "") + "@{}"
    header = r"\textbf{Quantity} & \textbf{Measured}"
    if show_expected:
        header += r" & \textbf{Expected}"
    return (
        "\\begin{center}\n\\small\n"
        f"\\begin{{tabular}}{{{align}}}\n"
        f"\\toprule\n{header} \\\\\n\\midrule\n"
        + "\n".join(lines)
        + "\n\\bottomrule\n\\end{tabular}\n\\end{center}\n"
    )


def _environment() -> Environment:
    # LaTeX-safe delimiters: the defaults collide with TeX's own braces.
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        line_statement_prefix="%%",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=StrictUndefined,
    )
    env.filters["tex"] = tex_escape
    return env


def write_results(results: list[Result], meta: RunMetadata, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "results.json"
    path.write_text(
        json.dumps(
            {"metadata": asdict(meta), "results": [r.to_dict() for r in results]},
            indent=2,
            default=str,
        )
    )
    return path


def render(
    results: list[Result],
    meta: RunMetadata,
    out_dir: Path,
    inventory: list | None = None,
) -> Path:
    """Write ``appendix.tex`` next to the figures the checks produced."""
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE_DIR / "preamble.tex", out_dir / "preamble.tex")

    by_section = []
    for key, title in SECTIONS.items():
        rs = [r for r in results if r.section == key]
        by_section.append({"key": key, "title": title, "results": rs})

    counts = {s: sum(1 for r in results if r.status == s) for s in
              ("pass", "fail", "warn", "info", "skip")}

    sql_blocks = [(r.id, r.title, r.sql) for r in results if r.sql]

    tex = _environment().get_template("appendix.tex.j2").render(
        meta=meta,
        results=results,
        sections=by_section,
        counts=counts,
        tier_names=sorted(TIER_NAMES.items()),
        status_macro=lambda s: _STATUS_MACROS[s],
        render_table=_render_table,
        render_metrics=_render_metrics,
        fmt=_fmt,
        total_runtime=sum(r.runtime_s for r in results),
        sql_blocks=sql_blocks,
        inventory=inventory or [],
    )
    path = out_dir / "gridded-eif-validation.tex"
    path.write_text(tex)
    return path


class LatexNotFound(RuntimeError):
    pass


def compile_pdf(tex_path: Path, engine: str = "pdflatex") -> Path:
    """Typeset the document, twice, so cross-references resolve."""
    if shutil.which("latexmk") is None and shutil.which(engine) is None:
        raise LatexNotFound(
            f"neither latexmk nor {engine} is on PATH — install a TeX distribution, "
            f"or run with --no-pdf to stop after writing appendix.tex"
        )

    cwd = tex_path.parent
    if shutil.which("latexmk"):
        cmd = ["latexmk", f"-{engine}", "-interaction=nonstopmode", "-halt-on-error",
               "-file-line-error", tex_path.name]
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    else:
        for _ in range(2):
            proc = subprocess.run(
                [engine, "-interaction=nonstopmode", "-halt-on-error",
                 "-file-line-error", tex_path.name],
                cwd=cwd, capture_output=True, text=True, check=False,
            )

    pdf = tex_path.with_suffix(".pdf")
    if not pdf.exists():
        log = (cwd / f"{tex_path.stem}.log")
        tail = ""
        if log.exists():
            lines = log.read_text(errors="replace").splitlines()
            errs = [ln for ln in lines if ":" in ln and ("Error" in ln or "error" in ln)]
            tail = "\n".join(errs[-15:] or lines[-30:])
        raise RuntimeError(
            f"LaTeX did not produce a PDF.\n--- log ---\n{tail}\n--- stdout ---\n"
            f"{proc.stdout[-2000:]}"
        )
    return pdf
