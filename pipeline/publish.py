"""Publishes derived artifacts to S3.

Caching strategy, which matters more than it looks:

  - Derived Parquet is IMMUTABLE. Its path carries the derived version, dataset,
    geography, and year, so a given URL's contents never change. Cache forever.
  - catalog.json is MUTABLE and is the entry point for everything. Cache briefly,
    so a data refresh becomes visible without a CDN invalidation.

Content-Type is set explicitly because S3 guesses
``application/x-www-form-urlencoded`` for .parquet, which is wrong and confuses
strict clients.
"""

from __future__ import annotations

import time
from pathlib import Path

import boto3
from rich.console import Console

from . import config
from .catalog import CATALOG_FILENAME

console = Console()

IMMUTABLE = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300, must-revalidate"

CONTENT_TYPES = {
    ".parquet": "application/octet-stream",
    ".json": "application/json",
    ".pmtiles": "application/octet-stream",
}


def publish(
    bucket: str,
    build_dir: Path | None = None,
    distribution_id: str | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Upload derived artifacts and the catalog, then invalidate the catalog."""
    build_dir = build_dir or (config.REPO_ROOT / ".build")
    # Constructed lazily: a dry run must work on a machine with no AWS config.
    s3 = None if dry_run else boto3.client("s3")
    uploaded: list[str] = []

    for path in sorted(build_dir.rglob("*")):
        if not path.is_file() or "_ledger" in path.parts:
            continue
        key = path.relative_to(build_dir).as_posix()
        # Parquet at a versioned path never changes. The catalog and the name
        # lookups can be rewritten in place, so they get a short TTL.
        mutable = path.name == CATALOG_FILENAME or "_names" in path.parts
        extra = {
            "ContentType": CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
            "CacheControl": SHORT if mutable else IMMUTABLE,
        }
        if dry_run:
            console.print(f"[dim]would upload {key} ({path.stat().st_size / 1e6:.1f} MB)[/dim]")
        else:
            s3.upload_file(str(path), bucket, key, ExtraArgs=extra)
            console.print(f"uploaded [green]{key}[/green] ({path.stat().st_size / 1e6:.1f} MB)")
        uploaded.append(key)

    if distribution_id and not dry_run:
        _invalidate(distribution_id, uploaded)

    return uploaded


def _invalidate(distribution_id: str, uploaded: list[str]) -> None:
    """Invalidate what we just replaced.

    Derived Parquet is served ``immutable``, which is correct almost always —
    a partition's contents rarely change once built. But a pipeline change that
    alters the physical layout (say, sorting rows so Parquet row-group pruning
    works) rewrites those files in place, and edges would otherwise keep serving
    the old bytes for a year while the catalog advertises a new sha256.

    Invalidating precisely what was uploaded keeps the rest of the cache warm.
    Past a threshold that stops being worth the request count, and a wildcard is
    both cheaper to submit and billed as a single path.
    """
    cf = boto3.client("cloudfront")
    paths = [f"/{k}" for k in uploaded]
    if len(paths) > 50:
        paths = ["/*"]
        console.print(f"invalidating [yellow]/*[/yellow] ({len(uploaded)} objects changed)")
    else:
        console.print(f"invalidating {len(paths)} path(s)")

    cf.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": f"geif-{time.time_ns()}",
        },
    )
