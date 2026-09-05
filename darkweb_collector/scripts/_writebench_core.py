from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import statistics
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_FORMAT = "dwti-postgres-write-path-benchmark"
REPORT_VERSION = 1
DEFAULT_CONCURRENCY = 8
DEFAULT_WARMUPS = 5
DEFAULT_ITERATIONS = 100
DEFAULT_ROUNDS = 3
DEFAULT_BATCH_SIZE = 5
BASELINE_VERSION = "0004_performance_indexes"
CANDIDATE_VERSION = "0006_postgres_read_paths"
DISPOSABLE_PREFIX = "dwti_writebench_"
DISPOSABLE_PATTERN = re.compile(r"^dwti_writebench_[0-9a-f]{20}$")
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
CLONE_TABLES = (
    "schema_migrations",
    "normalized_intelligence_cache_state",
    "ai_aggregation_schedule_claims",
    "crawl_jobs",
    "vulnerability_records",
    "ransomware_live_victims",
    "collection_runs",
    "victims",
    "victim_details",
    "forum_topics",
    "forum_details",
    "forum_victims",
)
RECOVERED_SCRIPT_PROVENANCE = {
    "dirty_claim": {"ordinal": 5410, "sha256": "b3834165443e71bbcd7594355ff8982ff52a8706a831894316e81085cfa60d3f"},
    "job_vulnerability_ransomware": {"ordinal": 5638, "sha256": "88087cca31c42ec76482e231d0fc6b8cf336226577b32e6f4496997b207c50d8"},
    "victim_topic_detail": {"ordinal": 5788, "sha256": "3f8053a8192c3f5365e4f8a5a4ee2c0298e49717b5a2e4450e5db40e79ff3780"},
}


class WriteBenchmarkError(RuntimeError):
    pass


def _shared_benchmark_module():
    path = ROOT / "scripts" / "benchmark_databases.py"
    spec = importlib.util.spec_from_file_location("dwti_shared_benchmark_runtime", path)
    if spec is None or spec.loader is None:
        raise WriteBenchmarkError(f"cannot load benchmark helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def _source_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise WriteBenchmarkError(f"{label} must match {IDENTIFIER_PATTERN.pattern}")
    if DISPOSABLE_PATTERN.fullmatch(normalized):
        raise WriteBenchmarkError(f"{label} must not use the disposable prefix")
    return normalized


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prefix_sql(column: str) -> str:
    return f"SUBSTR({column}, 1, ?) = ?"


def variant_order(round_index: int, workload_index: int) -> tuple[str, str]:
    if (round_index + workload_index) % 2 == 0:
        return ("baseline", "candidate")
    return ("candidate", "baseline")


@dataclass(frozen=True)
class RunConfig:
    concurrency: int = DEFAULT_CONCURRENCY
    warmups: int = DEFAULT_WARMUPS
    iterations: int = DEFAULT_ITERATIONS
    rounds: int = DEFAULT_ROUNDS
    batch_size: int = DEFAULT_BATCH_SIZE

    @property
    def total_calls(self) -> int:
        return self.concurrency * (self.warmups + self.iterations)


def _median_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rounds": len(items),
        "median_tps": round(statistics.median(x["metrics"]["throughput"] for x in items), 6) if items else 0.0,
        "median_p50_ms": round(statistics.median(x["metrics"]["p50_ms"] for x in items), 6) if items else 0.0,
        "median_p95_ms": round(statistics.median(x["metrics"]["p95_ms"] for x in items), 6) if items else 0.0,
        "errors": sum(int(x["metrics"]["errors"]) for x in items),
        "round_results": items,
    }

