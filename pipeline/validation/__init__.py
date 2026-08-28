"""Validation harness for the Gridded EIF data product.

Produces a typeset report from executed checks rather than from prose. Every
number in the document is computed at build time by a registered check, so the
appendix and the test suite are two renderings of one set of facts.
"""

from __future__ import annotations

from .registry import Context, all_checks, metadata, run, select
from .types import Figure, Result, RunMetadata, Table

__all__ = [
    "Context",
    "Figure",
    "Result",
    "RunMetadata",
    "Table",
    "all_checks",
    "metadata",
    "run",
    "select",
]
