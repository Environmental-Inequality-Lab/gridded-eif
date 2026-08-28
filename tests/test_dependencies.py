"""Every third-party import must be declared as a dependency.

Caught the hard way: `topojson` was pip-installed locally and imported by
pipeline/boundaries.py, but never added to pyproject. Everything passed here
and the workflow died on ModuleNotFoundError at the first step that imports
the CLI — after the user had already dispatched a long run.

Runs without network access and takes milliseconds.
"""

from __future__ import annotations

import ast
import tomllib

from pipeline import config

# Import name to distribution name, where they differ.
IMPORT_TO_PACKAGE = {
    "yaml": "pyyaml",
    "matplotlib": "matplotlib",
    "jinja2": "jinja2",
    "duckdb": "duckdb",
    "geopandas": "geopandas",
    "topojson": "topojson",
}

STDLIB_OK = {
    "__future__", "ast", "collections", "concurrent", "dataclasses", "datetime",
    "functools", "hashlib", "io", "json", "os", "pathlib", "re", "shutil",
    "subprocess", "sys", "time", "tomllib", "traceback", "typing", "zipfile",
}


def _declared() -> set[str]:
    """Base dependencies plus every optional extra.

    An extra counts as declared: the validation report legitimately imports
    matplotlib, and requiring it in the base install would make every CI job
    that only builds data pull a plotting stack. What matters is that the
    package is named somewhere in pyproject, so the job that needs it can
    install it — and that whoever adds an import is forced to say so.
    """
    data = tomllib.loads((config.REPO_ROOT / "pyproject.toml").read_text())
    specs = list(data["project"]["dependencies"])
    for extra in data["project"].get("optional-dependencies", {}).values():
        specs.extend(extra)
    names = set()
    for spec in specs:
        # Strip version constraints and inline comments.
        name = spec.split(";")[0].split("#")[0].strip()
        for sep in (">=", "==", "<=", "~=", ">", "<", "["):
            name = name.split(sep)[0]
        names.add(name.strip().lower())
    return names


def _imported() -> set[str]:
    found = set()
    # rglob, not glob: pipeline/validation/ is a subpackage, and scanning only
    # the top level is how matplotlib and jinja2 became module-level imports
    # that no CI job installed.
    for path in (config.REPO_ROOT / "pipeline").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name.split(".")[0])
            # level > 0 is a relative import within this package.
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return {m for m in found if m not in STDLIB_OK and m != "pipeline"}


def test_every_import_is_declared():
    declared = _declared()
    missing = []
    for mod in sorted(_imported()):
        pkg = IMPORT_TO_PACKAGE.get(mod, mod).lower()
        if pkg not in declared:
            missing.append(f"{mod} (install name: {pkg})")
    assert not missing, (
        "imported but not declared in pyproject.toml: "
        + ", ".join(missing)
        + ". CI installs only what pyproject declares, so this fails there, not here."
    )
