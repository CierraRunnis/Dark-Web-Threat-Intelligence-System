"""Compatibility imports for callers of the original benchmark-only module."""

from darkweb_collector.postgres_write_gate import (
    OPTIMIZED_WORKLOADS,
    REGRESSION_WORKLOADS,
    WORKLOADS,
    evaluate_postgres_write_paths,
)

__all__ = [
    "OPTIMIZED_WORKLOADS",
    "REGRESSION_WORKLOADS",
    "WORKLOADS",
    "evaluate_postgres_write_paths",
]
