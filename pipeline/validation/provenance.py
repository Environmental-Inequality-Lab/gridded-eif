"""Section A — provenance and integrity.

Answers the most basic question a sceptical reader has: are the bytes we built
from, and the bytes we serve, the ones we say they are? Nothing downstream in
this report means anything if this section fails, which is why it runs first
and why the source manifest is recorded even when every check passes.

Every sentence this module contributes to the report is written in the `@check`
registration and never varies. The check bodies produce numbers only.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import requests

from .. import config, validate
from ..__version__ import __version__
from .registry import Context, check
from .types import Metric, Result, Table

# Metadata probes are latency-bound, not bandwidth-bound: several hundred HEAD
# requests issued one at a time take minutes and saturate nothing. Modest
# concurrency, because the point is to measure the CDN, not to load-test it.
_PROBE_WORKERS = 12


def _head(url: str) -> tuple[int | None, dict, str | None]:
    """(status, headers, error) for one HEAD request, never raising.

    Header names are lowercased on the way out. ``requests`` hands back a
    case-insensitive mapping, but a plain ``dict()`` of it keeps whatever
    casing the server used — so a lookup for ``content-length`` silently misses
    a ``Content-Length`` and the caller concludes the header was absent. That
    read as 378 size mismatches against a CDN that was serving correctly, which
    is the worst failure a validation harness can have: a confident false
    accusation.
    """
    try:
        r = requests.head(url, timeout=60, allow_redirects=True)
        return r.status_code, {k.lower(): v for k, v in r.headers.items()}, None
    except requests.RequestException as exc:
        return None, {}, type(exc).__name__


def _head_many(urls: list[str]) -> list[tuple[int | None, dict, str | None]]:
    with ThreadPoolExecutor(max_workers=_PROBE_WORKERS) as pool:
        return list(pool.map(_head, urls))


def _source_files() -> list[tuple[str, int, str]]:
    """(dataset, year, url) for every source file the published data draws on."""
    return [
        (ds.name, year, config.source_url(ds.name, year))
        for ds in config.datasets().values()
        for year in ds.all_years()
    ]


@check(
    id="A1",
    section="A",
    title="Source file manifest",
    tier=2,
    claim=(
        "Every Census source file this product is built from is identified by URL, size, "
        "and publication date, so any figure in this report can be traced to the exact "
        "bytes it came from."
    ),
    method=(
        "One HTTP HEAD request per source file named by the registry, recording the "
        "reported size and modification date."
    ),
    interpretation=(
        "This check records rather than judges: it fails only if a file the registry names "
        "cannot be retrieved at all. A file that has been modified since a previous run "
        "will show a later modification date here, which is worth noticing --- the Census "
        "Bureau revises these files --- but is not itself an error. Content hashes are in "
        "A5; the Census file server publishes no checksum, so size and date are the "
        "strongest fingerprint available without downloading every file."
    ),
)
def a1_source_manifest(ctx: Context) -> Result:
    files = _source_files()
    rows, unreachable = [], []
    total_bytes = 0
    for (dataset, year, url), (status, headers, err) in zip(
        files, _head_many([f[2] for f in files]), strict=True
    ):
        if err or status != 200:
            unreachable.append([dataset, year, url, err or str(status)])
            continue
        size = int(headers.get("content-length", 0))
        total_bytes += size
        rows.append(
            [dataset, year, size, headers.get("last-modified", "—"), url.rsplit("/", 1)[-1]]
        )

    tables = [
        Table(
            caption="Census source files consumed by the published product",
            columns=["Dataset", "Year", "Bytes", "Last modified", "File"],
            rows=rows,
            align="llrll",
            numeric_columns=[2],
            label="tab:a1-manifest",
        )
    ]
    if unreachable:
        tables.append(
            Table(
                caption="Source files that could not be reached",
                columns=["Dataset", "Year", "URL", "Reason"],
                rows=unreachable,
                align="llp{0.42\\textwidth}l",
            )
        )

    return Result(
        id="A1", section="A", title="", tier=2,
        status="fail" if unreachable else "info",
        metrics=[
            Metric("Source files named by the registry", len(files)),
            Metric("Reachable", len(rows), expected=len(files)),
            Metric("Total size", round(total_bytes / 1e9, 2), unit="GB"),
        ],
        tables=tables,
    )


@check(
    id="A2",
    section="A",
    title="Schema contract conformance",
    tier=2,
    claim=(
        "Every source file matches the pinned schema contract — column names, column types, "
        "and category values — in every published year, not only the year the contract was "
        "derived from."
    ),
    method=(
        "Each source file's schema is read and compared against "
        "\\texttt{catalog/contracts/source-schema-v5.json}: required columns present and of the "
        "declared type, row count within the declared range, and no category value outside "
        "the declared set."
    ),
    interpretation=(
        "A violation means the upstream schema has moved and the pipeline is building "
        "against an assumption that no longer holds. The correct response is to update the "
        "contract deliberately and bump its version, never to loosen the check until it "
        "passes. Warnings are a weaker signal: a category the contract declares but the "
        "data does not contain is usually a genuine absence in that year, and a column "
        "present in the data but absent from the contract may mean new data has become "
        "available."
    ),
)
def a2_schema_conformance(ctx: Context) -> Result:
    contract = config.contract()
    rows, failures, warnings = [], [], []
    for dataset, year, _ in _source_files():
        rep = validate.validate_source(dataset, year, con=ctx.con)
        rows.append([dataset, year, rep.rows, "pass" if rep.ok else "FAIL", len(rep.warnings)])
        failures.extend([dataset, year, e] for e in rep.errors)
        warnings.extend([dataset, year, w] for w in rep.warnings)

    tables = [
        Table(
            caption="Schema contract conformance by source file",
            columns=["Dataset", "Year", "Rows", "Result", "Warnings"],
            rows=rows,
            align="llrlr",
            numeric_columns=[2, 4],
            label="tab:a2-schema",
        )
    ]
    for caption, data in (
        ("Contract violations", failures),
        ("Contract warnings (non-fatal)", warnings),
    ):
        if data:
            tables.append(
                Table(
                    caption=caption,
                    columns=["Dataset", "Year", "Detail"],
                    rows=data,
                    align="llp{0.55\\textwidth}",
                )
            )

    bad_files = {(f[0], f[1]) for f in failures}
    return Result(
        id="A2", section="A", title="", tier=2,
        status="fail" if failures else ("warn" if warnings else "pass"),
        metrics=[
            Metric("Contract version", contract["contract_version"]),
            Metric("Describes source data version", contract["describes_data_version"]),
            Metric("Source files checked", len(rows)),
            Metric("Conforming", len(rows) - len(bad_files), expected=len(rows)),
            Metric("Violations", len(failures), expected=0),
            Metric("Warnings", len(warnings)),
        ],
        tables=tables,
    )


@check(
    id="A3",
    section="A",
    title="Statistical invariants of the source data",
    tier=2,
    claim=(
        "In every source file the national total falls in a plausible band, the "
        "post-processed measure is nowhere negative, and post-processing preserves race "
        "totals — the three properties the contract asserts about the numbers themselves "
        "rather than the schema."
    ),
    method=(
        "Each source file is aggregated to a national total for both noise measures and to "
        "race margins for each, then compared against the bands and tolerances declared in "
        "the schema contract. The bands are declared in the contract, not chosen here."
    ),
    interpretation=(
        "These catch a class of failure a column check cannot: the schema is intact but the "
        "numbers have moved. Post-processing redistributes population within race groups, "
        "so race margins must survive it; a departure means the upstream algorithm has "
        "changed and the guidance this site gives about choosing between the two measures "
        "needs revisiting."
    ),
)
def a3_invariants(ctx: Context) -> Result:
    rows, failures = [], []
    for dataset, year, _ in _source_files():
        rep = validate.check_invariants(dataset, year, con=ctx.con)
        rows.append([dataset, year, rep.rows, "pass" if rep.ok else "FAIL"])
        failures.extend([dataset, year, e] for e in rep.errors)

    inv = {i["id"]: i for i in config.contract()["invariants"]}
    band = inv["national_total_plausible"]
    tol = inv["postprocessing_preserves_race_totals"]["tolerance_abs"]

    tables = [
        Table(
            caption="Statistical invariants by source file",
            columns=["Dataset", "Year", "National total (raw)", "Result"],
            rows=rows,
            align="llrl",
            numeric_columns=[2],
            label="tab:a3-invariants",
        )
    ]
    if failures:
        tables.append(
            Table(
                caption="Invariant violations",
                columns=["Dataset", "Year", "Violation"],
                rows=failures,
                align="llp{0.55\\textwidth}",
            )
        )

    return Result(
        id="A3", section="A", title="", tier=2,
        status="fail" if failures else "pass",
        metrics=[
            Metric("Source files checked", len(rows)),
            Metric("Satisfying every invariant", len(rows) - len(failures), expected=len(rows)),
            Metric("Plausible national total, lower bound", band["min"], unit="people"),
            Metric("Plausible national total, upper bound", band["max"], unit="people"),
            Metric("Race-total preservation tolerance", tol, unit="people"),
        ],
        tables=tables,
    )


@check(
    id="A4",
    section="A",
    title="Published artifacts resolve and match their advertised size",
    tier=2,
    claim=(
        "Every file the published catalog advertises exists at the URL given, returns HTTP "
        "200, and is exactly the number of bytes the catalog claims."
    ),
    method=(
        "One HTTP HEAD request per catalog entry — per-year partitions, all-years files, and "
        "crosswalks — comparing the reported content length against the size recorded in the "
        "catalog."
    ),
    interpretation=(
        "The catalog is fetched by the site at runtime and is the only index of what exists. "
        "An entry that does not resolve is a broken download for a user; one whose size "
        "disagrees means the catalog and the object store have diverged, which usually "
        "indicates a publish that partially failed. A response carrying no content length is "
        "reported separately from a size mismatch, because that is a fact about the response "
        "rather than about the file."
    ),
)
def a4_catalog_resolves(ctx: Context) -> Result:
    cat = ctx.catalog()
    targets: list[tuple[str, str, int | None]] = [
        (f"{e['dataset']}/{e['geography']}/{e['year']}", e["url"], e["bytes"])
        for e in cat.get("entries", [])
    ]
    targets += [
        (f"{c['dataset']}/{c['geography']}/all", c["url"], c["bytes"])
        for c in cat.get("combined", [])
    ]
    targets += [
        (f"crosswalk/{geo}", url, None) for geo, url in (cat.get("crosswalks") or {}).items()
    ]

    problems, ok = [], 0
    for (name, _url, expected), (status, headers, err) in zip(
        targets, _head_many([t[1] for t in targets]), strict=True
    ):
        if err:
            problems.append([name, err, "—", "—"])
        elif status != 200:
            problems.append([name, f"HTTP {status}", "—", "—"])
        elif "content-length" not in headers:
            problems.append([name, "no content-length header", expected, "—"])
        elif expected is not None and int(headers["content-length"]) != expected:
            problems.append([name, "size mismatch", expected, int(headers["content-length"])])
        else:
            ok += 1

    tables = []
    if problems:
        tables.append(
            Table(
                caption="Published artifacts that do not match the catalog",
                columns=["Artifact", "Problem", "Catalog bytes", "Served bytes"],
                rows=problems,
                align="llrr",
                numeric_columns=[2, 3],
            )
        )

    return Result(
        id="A4", section="A", title="", tier=2,
        status="pass" if not problems else "fail",
        metrics=[
            Metric("Per-year partitions advertised", len(cat.get("entries", []))),
            Metric("All-years files advertised", len(cat.get("combined", []))),
            Metric("Crosswalks advertised", len(cat.get("crosswalks") or {})),
            Metric("Resolving at the advertised size", ok, expected=len(targets)),
        ],
        tables=tables,
    )


@check(
    id="A5",
    section="A",
    title="Published artifacts match their advertised checksum",
    tier=3,
    claim=(
        "The SHA-256 the catalog publishes for each partition is the SHA-256 of the bytes "
        "the CDN actually serves, so a citation of a checksum is a citation of content."
    ),
    method=(
        "Every published partition and all-years file is downloaded in full and hashed, and "
        "the digest compared against the one recorded in the catalog."
    ),
    interpretation=(
        "A mismatch means the bytes on the CDN are not the bytes the catalog describes, so a "
        "checksum published alongside a citation would not identify what a reader receives. "
        "This is the strongest integrity guarantee the report offers and the most expensive "
        "to produce, which is why it runs at the highest tier rather than on every refresh."
    ),
)
def a5_checksums(ctx: Context) -> Result:
    cat = ctx.catalog()
    entries = cat.get("entries", []) + cat.get("combined", [])
    mismatches, errors, verified, total_bytes = [], [], 0, 0
    for e in entries:
        name = f"{e['dataset']}/{e['geography']}/{e.get('year', 'all')}"
        try:
            h, size = hashlib.sha256(), 0
            with requests.get(e["url"], timeout=600, stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(1 << 20):
                    h.update(chunk)
                    size += len(chunk)
            total_bytes += size
            if h.hexdigest() != e["sha256"]:
                mismatches.append([name, e["sha256"][:16], h.hexdigest()[:16], size])
            else:
                verified += 1
        except requests.RequestException as exc:
            errors.append([name, type(exc).__name__])

    tables = []
    if mismatches:
        tables.append(
            Table(
                caption="Checksum mismatches between the catalog and the CDN",
                columns=["Artifact", "Catalog SHA-256", "Served SHA-256", "Bytes"],
                rows=mismatches,
                align="lllr",
                numeric_columns=[3],
                note="Digests truncated to 16 hex characters for display.",
            )
        )
    if errors:
        tables.append(
            Table(
                caption="Artifacts that could not be retrieved for hashing",
                columns=["Artifact", "Reason"], rows=errors, align="ll",
            )
        )

    return Result(
        id="A5", section="A", title="", tier=3,
        status="pass" if (not mismatches and not errors) else "fail",
        metrics=[
            Metric("Artifacts advertised", len(entries)),
            Metric("Hashing to their advertised digest", verified, expected=len(entries)),
            Metric("Mismatches", len(mismatches), expected=0),
            Metric("Unretrievable", len(errors), expected=0),
            Metric("Bytes read", round(total_bytes / 1e9, 2), unit="GB"),
        ],
        tables=tables,
    )


@check(
    id="A6",
    section="A",
    title="Version coherence across the four version lines",
    tier=2,
    claim=(
        "The site, pipeline, schema contract, and derived data versions recorded in the "
        "published catalog agree with the repository they are supposed to have been built "
        "from, and every derived URL sits under the declared derived version prefix."
    ),
    method=(
        "The four version fields in the published catalog are compared against the values "
        "the repository declares, and every entry URL is checked for the derived version "
        "prefix. The catalog committed to the repository is compared against the published "
        "one separately."
    ),
    interpretation=(
        "Disagreement means the published data was built from a different revision than the "
        "one being read, so nothing else in this report can be attributed to a known state "
        "of the code. The committed \\texttt{site/catalog.json} is a development fallback only --- "
        "the site fetches the live catalog at runtime --- so a difference there affects local "
        "development rather than users, but anyone testing with \\texttt{?catalog=./catalog.json} "
        "is validating against data that may no longer be published."
    ),
)
def a6_versions(ctx: Context) -> Result:
    cat = ctx.catalog()
    repo = {
        "pipeline version": __version__,
        "registry version": str(config.registry()["registry_version"]),
        "derived version": config.DERIVED_VERSION,
        "catalog version": cat.get("catalog_version", "—"),
    }
    published = {
        "pipeline version": cat.get("pipeline_version", "—"),
        "registry version": str(cat.get("registry_version", "—")),
        "derived version": cat.get("derived_version", "—"),
        "catalog version": cat.get("catalog_version", "—"),
    }
    rows, disagreements = [], 0
    for key, repo_value in repo.items():
        agree = repo_value == published[key]
        rows.append([key, repo_value, published[key], "yes" if agree else "NO"])
        disagreements += 0 if agree else 1

    prefix = f"derived/{published['derived version']}/"
    unversioned = sum(
        1
        for e in cat.get("entries", [])
        if ".net/" in e["url"] and not e["url"].split(".net/")[-1].startswith(prefix)
    )

    local_path = config.REPO_ROOT / "site" / "catalog.json"
    catalog_rows, stale = [], False
    if local_path.exists():
        local = json.loads(local_path.read_text())
        stale = local.get("generated_at") != cat.get("generated_at")
        catalog_rows = [
            ["Committed to the repository", local.get("generated_at", "—"),
             len(local.get("entries", []))],
            ["Published on the CDN", cat.get("generated_at", "—"), len(cat.get("entries", []))],
        ]

    tables = [
        Table(
            caption="Declared versions, repository against published catalog",
            columns=["Version line", "Repository", "Published catalog", "Agree"],
            rows=rows,
            align="llll",
            label="tab:a6-versions",
        )
    ]
    if catalog_rows:
        tables.append(
            Table(
                caption="Catalog generation, committed copy against published copy",
                columns=["Copy", "Generated", "Entries"],
                rows=catalog_rows,
                align="llr",
                numeric_columns=[2],
                note=(
                    "The site fetches the published catalog at runtime; the committed copy "
                    "is a development fallback reached only via \\texttt{?catalog=./catalog.json}."
                ),
            )
        )

    return Result(
        id="A6", section="A", title="", tier=2,
        status="pass" if not (disagreements or unversioned or stale) else "warn",
        metrics=[
            Metric("Version lines disagreeing", disagreements, expected=0),
            Metric("Entry URLs outside the derived version prefix", unversioned, expected=0),
            Metric("Committed catalog differs from published", "yes" if stale else "no",
                   expected="no"),
        ],
        tables=tables,
    )
