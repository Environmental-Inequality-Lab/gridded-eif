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
        is_catalog = path.name == CATALOG_FILENAME
        extra = {
            "ContentType": CONTENT_TYPES.get(path.suffix, "application/octet-stream"),
            "CacheControl": SHORT if is_catalog else IMMUTABLE,
        }
        if dry_run:
            console.print(f"[dim]would upload {key} ({path.stat().st_size / 1e6:.1f} MB)[/dim]")
        else:
            s3.upload_file(str(path), bucket, key, ExtraArgs=extra)
            console.print(f"uploaded [green]{key}[/green] ({path.stat().st_size / 1e6:.1f} MB)")
        uploaded.append(key)

    # Only the catalog needs invalidating — everything else is immutable, so a
    # blanket /* invalidation would just cost money and evict warm cache.
    if distribution_id and not dry_run:
        boto3.client("cloudfront").create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": [f"/{CATALOG_FILENAME}"]},
                "CallerReference": str(Path(build_dir).stat().st_mtime_ns),
            },
        )
        console.print(f"invalidated /{CATALOG_FILENAME}")

    return uploaded
