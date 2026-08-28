"""Figure rendering.

Figures are written as vector PDF and typeset by the same LaTeX engine as the
document, through matplotlib's PGF backend, so the type in a figure is the type
in the surrounding paragraph. A chart set in a different face than its caption
reads as pasted in from somewhere else, which is exactly the impression a
validation appendix should not give.

If the PGF backend is unavailable the module falls back to the ordinary PDF
backend with a serif stack. The figures are then slightly off-face but the
report still builds, which matters more.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence

import matplotlib
from rich.console import Console

console = Console()

_PGF_PREAMBLE = r"""
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath}
"""

_configured = False


def wanted(ctx) -> bool:
    """Whether figures are worth drawing at all.

    A --no-pdf run renders no document, so drawing figures for it is work whose
    only possible outcome is a failure.
    """
    return getattr(ctx, "render_figures", True)


def _configure() -> None:
    global _configured
    if _configured:
        return
    # Tested by looking for the binary, not by try/except around the backend
    # selection: matplotlib.use("pgf") succeeds perfectly well with no TeX
    # installed and defers the failure to savefig, so the guard that looked
    # right caught nothing and a data check failed on a missing font renderer.
    if shutil.which("pdflatex"):
        matplotlib.use("pgf")
        matplotlib.rcParams.update({
            "pgf.texsystem": "pdflatex",
            "pgf.rcfonts": False,
            "pgf.preamble": _PGF_PREAMBLE,
            "text.usetex": True,
        })
    else:
        matplotlib.use("pdf")
        matplotlib.rcParams.update({
            "text.usetex": False,
            "font.family": "serif",
            "font.serif": ["Latin Modern Roman", "CMU Serif", "DejaVu Serif"],
        })
    matplotlib.rcParams.update({
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 9,
        "legend.fontsize": 8,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.5,
        "axes.axisbelow": True,
        "lines.linewidth": 1.2,
        "figure.dpi": 200,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
    })
    _configured = True


# A restrained sequence — this is an appendix, not a dashboard. Ink is spent on
# the data, and the accent is reserved for whatever the figure is arguing.
INK = "#1a1a1a"
ACCENT = "#a4243b"
MUTED = "#8a8f98"
SECOND = "#2b5d7d"


def _save(fig, ctx, name: str) -> bool:
    """Write a figure, reporting failure rather than raising.

    A check's verdict must depend on the data and on nothing else. Whether a
    font renderer is installed on the runner is not evidence about the Gridded
    EIF, so a figure that cannot be drawn omits itself and lets the check stand.
    """
    import matplotlib.pyplot as plt

    try:
        fig.savefig(ctx.figure_dir / f"{name}.pdf")
        return True
    except Exception as exc:  # noqa: BLE001 — see docstring
        console.print(f"[yellow]figure {name} not drawn: {type(exc).__name__}: {exc}[/yellow]")
        return False
    finally:
        # Best effort: a failure while releasing the figure would propagate out
        # of the finally block and undo the guard above.
        try:
            plt.close(fig)
        except Exception:  # noqa: BLE001, S110
            pass


def coverage_loss_by_year(ctx, series: dict[str, list[tuple[int, float]]]) -> bool:
    """C1 — share of source population dropped, by year, per dataset."""
    _configure()
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.6, 2.6))
    for i, (label, pts) in enumerate(sorted(series.items())):
        years = [y for y, _ in pts]
        vals = [v for _, v in pts]
        ax.plot(
            years, vals,
            color=ACCENT if i == 0 else SECOND,
            marker="o", markersize=2.5,
            label=label,
            linestyle="-" if i == 0 else "--",
        )
    ax.axhline(0, color=INK, linewidth=0.6)
    ax.set_ylabel(r"population dropped (\%)" if matplotlib.rcParams["text.usetex"]
                  else "population dropped (%)")
    ax.set_xlabel("year")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, loc="upper right")

    # Mark the reference year, which is the whole explanation of the shape.
    zero_years = [y for pts in series.values() for y, v in pts if v == 0]
    if zero_years:
        ref = min(zero_years)
        ax.axvline(ref, color=MUTED, linewidth=0.6, linestyle=":")
        # The series descends from left to right, so the reliably empty region
        # is the bottom-left. Labelling the rule from there keeps the text off
        # the data rather than hunting for a gap beside the line itself.
        all_years = [y for pts in series.values() for y, _ in pts]
        ax.annotate(
            f"dotted rule: {ref}, the year the crosswalk was built from",
            xy=(min(all_years), 0), xytext=(2, 6), textcoords="offset points",
            ha="left", va="bottom", fontsize=7, color=MUTED,
        )
    return _save(fig, ctx, "c1-coverage-loss")


def loss_by_state(ctx, by_state, year: int) -> bool:
    """C8 — dropped population as a share of each state's published total."""
    _configure()
    import matplotlib.pyplot as plt

    df = by_state.iloc[::-1]  # largest at the top once barh flips the axis
    fig, ax = plt.subplots(figsize=(5.6, 0.24 * len(df) + 0.7))
    ax.barh(df["_geo_name"], df["share"], color=ACCENT, height=0.68)
    ax.set_xlabel(r"population dropped (\% of state total)"
                  if matplotlib.rcParams["text.usetex"]
                  else "population dropped (% of state total)")
    ax.grid(axis="y", visible=False)

    # Absolute counts alongside the share: a large share of a small state and a
    # small share of a large state are different problems.
    for y, (share, lost) in enumerate(zip(df["share"], df["lost"], strict=True)):
        ax.annotate(f"{lost:,.0f}", xy=(share, y), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=6.5, color=MUTED)
    ax.set_xlim(0, df["share"].max() * 1.22)
    return _save(fig, ctx, "c8-loss-by-state")


def cell_set_drift(ctx, rows: Sequence[tuple[int, int, int]], ref: int) -> bool:
    """C6 — populated cells per year, and how many the reference year lacks."""
    _configure()
    import matplotlib.pyplot as plt

    years = [r[0] for r in rows]
    total = [r[1] for r in rows]
    absent = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(5.6, 2.6))
    ax.bar(years, [t / 1e6 for t in total], color=MUTED, width=0.72,
           label="populated cells")
    ax.bar(years, [a / 1e6 for a in absent], color=ACCENT, width=0.72,
           label=f"absent from the {ref} crosswalk")
    ax.set_ylabel("grid cells (millions)")
    ax.set_xlabel("year")
    # Above the axes: the bars run the full height of the plot at every year,
    # so there is no interior position that does not sit on data.
    ax.legend(
        frameon=False, loc="lower left", bbox_to_anchor=(0, 1.01),
        ncol=2, borderaxespad=0,
    )
    return _save(fig, ctx, "c6-cell-drift")
