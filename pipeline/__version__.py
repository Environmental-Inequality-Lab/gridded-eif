"""Pipeline version — SemVer.

MAJOR: aggregation logic changes such that previously published numbers change.
MINOR: new capability that leaves existing outputs identical.
PATCH: bug fixes that do not alter correct outputs.

This value is written into every derived artifact's metadata and into
catalog.json, so any published number is traceable to the exact build that
produced it. Bumping MAJOR forces a rebuild of all partitions.
"""

__version__ = "1.0.0"
