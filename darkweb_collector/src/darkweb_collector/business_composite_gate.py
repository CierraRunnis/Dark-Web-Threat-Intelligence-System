from __future__ import annotations

import math
import statistics
from typing import Any

from darkweb_collector.postgres_write_gate import WORKLOADS


SECTION_FORMAT = "dwti-business-composite-v2"
SECTION_VERSION = 2
BACKENDS = ("sqlite", "postgresql")
CONCURRENCY = 8
WARMUPS_PER_WORKER = 5
ITERATIONS_PER_WORKER = 100
ROUNDS = 3
BATCH_SIZE = 5
MEASURED_CYCLES = CONCURRENCY * ITERATIONS_PER_WORKER
TOTAL_CYCLES = CONCURRENCY * (WARMUPS_PER_WORKER + ITERATIONS_PER_WORKER)
TPS_RATIO_MIN = 2.0


def backend_order(round_index: int) -> tuple[str, str]:
    """Return the code-owned alternating engine order for a zero-based round."""

    if round_index % 2 == 0:
        return BACKENDS
    return tuple(reversed(BACKENDS))


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _exact_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        if float(value) != parsed:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed


def _contracts_pass(contracts: Any) -> bool:
    if not isinstance(contracts, dict):
        return False
    equivalence = contracts.get("equivalence")
    if not isinstance(equivalence, dict) or equivalence.get("equivalent") is not True:
        return False
    for backend in BACKENDS:
        suite = contracts.get(backend)
        workloads = suite.get("workloads") if isinstance(suite, dict) else None
        if not isinstance(workloads, dict) or set(workloads) != set(WORKLOADS):
            return False
        if any(
            not isinstance(workloads[name], dict)
            or workloads[name].get("passed") is not True
            for name in WORKLOADS
        ):
            return False
    return True


def _source_checks(section: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    binding = section.get("source_binding")
    integrity = section.get("source_integrity")
    benchmark_id = str(section.get("benchmark_id") or "")
    if not isinstance(binding, dict) or not isinstance(integrity, dict):
        return False, ["source_binding"]
    if not benchmark_id or str(binding.get("benchmark_id") or "") != benchmark_id:
        failures.append("source_binding.benchmark_id")

    sqlite_binding = binding.get("sqlite")
    sqlite_integrity = integrity.get("sqlite")
    if not isinstance(sqlite_binding, dict) or not isinstance(sqlite_integrity, dict):
        failures.append("source_binding.sqlite")
    else:
        digest = str(sqlite_binding.get("sha256") or "")
        before = str(sqlite_integrity.get("sha256_before") or "")
        after = str(sqlite_integrity.get("sha256_after") or "")
        if not digest or digest != before or before != after:
            failures.append("source_binding.sqlite.sha256")

    postgres_binding = binding.get("postgresql")
    postgres_integrity = integrity.get("postgresql")
    if not isinstance(postgres_binding, dict) or not isinstance(postgres_integrity, dict):
        failures.append("source_binding.postgresql")
    else:
        digest = str(postgres_binding.get("schema_snapshot_sha256") or "")
        before = str(postgres_integrity.get("sha256_before") or "")
        after = str(postgres_integrity.get("sha256_after") or "")
        if not digest or digest != before or before != after:
            failures.append("source_binding.postgresql.schema_snapshot_sha256")
        if str(postgres_binding.get("schema_version") or "") != "0006_postgres_read_paths":
            failures.append("source_binding.postgresql.schema_version")
        if not str(postgres_binding.get("schema") or ""):
            failures.append("source_binding.postgresql.schema")
        if not str(postgres_binding.get("schema_fingerprint") or ""):
            failures.append("source_binding.postgresql.schema_fingerprint")
    return not failures, failures


def _cleanup_pass(temporary_targets: Any) -> bool:
    if not isinstance(temporary_targets, dict):
        return False
    sqlite = temporary_targets.get("sqlite")
    postgres = temporary_targets.get("postgresql")
    if not isinstance(sqlite, dict) or not isinstance(postgres, dict):
        return False
    sqlite_records = sqlite.get("records")
    postgres_records = postgres.get("records")
    if not isinstance(sqlite_records, list) or len(sqlite_records) < ROUNDS:
        return False
    if not isinstance(postgres_records, list) or len(postgres_records) < ROUNDS:
        return False
    sqlite_ok = all(
        isinstance(item, dict)
        and item.get("created") is True
        and item.get("removed") is True
        for item in sqlite_records
    )
    postgres_ok = all(
        isinstance(item, dict)
        and item.get("created") is True
        and item.get("dropped") is True
        and not str(item.get("cleanup_error") or "")
        for item in postgres_records
    )
    return (
        sqlite_ok
        and postgres_ok
        and sqlite.get("leftovers") in ([], ())
        and postgres.get("leftovers") in ([], ())
    )


def _parameters_pass(parameters: Any) -> bool:
    if not isinstance(parameters, dict):
        return False
    return (
        _exact_int(parameters.get("concurrency")) == CONCURRENCY
        and _exact_int(parameters.get("warmups_per_worker")) == WARMUPS_PER_WORKER
        and _exact_int(parameters.get("iterations_per_worker")) == ITERATIONS_PER_WORKER
        and _exact_int(parameters.get("rounds")) == ROUNDS
        and _exact_int(parameters.get("batch_size")) == BATCH_SIZE
        and parameters.get("workloads") == list(WORKLOADS)
        and parameters.get("cycle_model") == "one_each_in_workload_order"
        and parameters.get("source_databases_written") is False
    )


def _round_order_pass(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != ROUNDS:
        return False
    for round_index, item in enumerate(value):
        if not isinstance(item, dict):
            return False
        if _exact_int(item.get("round")) != round_index + 1:
            return False
        if item.get("backend_order") != list(backend_order(round_index)):
            return False
    return True


def _audit_pass(audit: Any) -> bool:
    if not isinstance(audit, dict) or audit.get("passed") is not True:
        return False
    if _exact_int(audit.get("total_cycles")) != TOTAL_CYCLES:
        return False
    workloads = audit.get("workloads")
    if not isinstance(workloads, dict) or set(workloads) != set(WORKLOADS):
        return False
    return all(
        isinstance(workloads[name], dict)
        and workloads[name].get("passed") is True
        for name in WORKLOADS
    )


def _raw_backend_summary(value: Any) -> dict[str, Any]:
    rounds = value.get("round_results") if isinstance(value, dict) else None
    if not isinstance(rounds, list):
        rounds = []
    valid = len(rounds) == ROUNDS
    throughputs: list[float] = []
    p95_values: list[float] = []
    errors = 0
    seen_rounds: set[int] = set()
    for item in rounds:
        if not isinstance(item, dict):
            valid = False
            continue
        round_number = _exact_int(item.get("round"))
        metrics = item.get("metrics")
        audit = item.get("audit")
        if round_number is None or round_number < 1 or round_number > ROUNDS:
            valid = False
        else:
            if round_number in seen_rounds:
                valid = False
            seen_rounds.add(round_number)
        if not isinstance(metrics, dict):
            valid = False
            continue
        throughput = _finite_float(metrics.get("throughput"))
        p50 = _finite_float(metrics.get("p50_ms"))
        p95 = _finite_float(metrics.get("p95_ms"))
        elapsed = _finite_float(metrics.get("elapsed_seconds"))
        item_errors = _exact_int(metrics.get("errors"))
        measurement_errors = _exact_int(metrics.get("measurement_errors"))
        warmup_errors = _exact_int(metrics.get("warmup_errors"))
        metric_shape = (
            _exact_int(metrics.get("concurrency")) == CONCURRENCY
            and _exact_int(metrics.get("warmups_per_worker")) == WARMUPS_PER_WORKER
            and _exact_int(metrics.get("iterations_per_worker")) == ITERATIONS_PER_WORKER
            and _exact_int(metrics.get("attempted_operations")) == MEASURED_CYCLES
            and _exact_int(metrics.get("successful_operations")) == MEASURED_CYCLES
        )
        numeric_shape = (
            throughput is not None
            and throughput > 0
            and p50 is not None
            and p50 >= 0
            and p95 is not None
            and p95 >= 0
            and elapsed is not None
            and elapsed > 0
            and item_errors == 0
            and measurement_errors == 0
            and warmup_errors == 0
        )
        if not metric_shape or not numeric_shape or not _audit_pass(audit):
            valid = False
        if throughput is not None:
            throughputs.append(throughput)
        if p95 is not None:
            p95_values.append(p95)
        if item_errors is not None and item_errors >= 0:
            errors += item_errors
        else:
            valid = False
    if seen_rounds != set(range(1, ROUNDS + 1)):
        valid = False
    if len(throughputs) != ROUNDS or len(p95_values) != ROUNDS:
        valid = False
    return {
        "valid": valid,
        "rounds": len(rounds),
        "median_tps": statistics.median(throughputs) if throughputs else 0.0,
        "median_p95_ms": statistics.median(p95_values) if p95_values else 0.0,
        "errors": errors,
    }


def evaluate_business_composite_v2(section: dict[str, Any]) -> dict[str, Any]:
    """Recompute the 2x gate from raw, source-bound v2 supercycle rounds."""

    if not isinstance(section, dict):
        return {"passed": False, "criteria": {}, "failures": ["section_missing"]}
    failures: list[str] = []
    if section.get("format") != SECTION_FORMAT or _exact_int(section.get("format_version")) != SECTION_VERSION:
        failures.append("format")
    if not _parameters_pass(section.get("parameters")):
        failures.append("parameters")
    if not _round_order_pass(section.get("round_order")):
        failures.append("round_order")
    if not _contracts_pass(section.get("contracts")):
        failures.append("contracts")
    source_passed, source_failures = _source_checks(section)
    if not source_passed:
        failures.extend(source_failures)
    if not _cleanup_pass(section.get("temporary_targets")):
        failures.append("temporary_target_cleanup")
    durability = section.get("durability")
    if not isinstance(durability, dict) or (
        durability.get("sqlite") != "FULL"
        or durability.get("postgresql") != "fsync=on,synchronous_commit=on"
    ):
        failures.append("durability")

    results = section.get("results")
    sqlite = _raw_backend_summary(results.get("sqlite") if isinstance(results, dict) else None)
    postgres = _raw_backend_summary(results.get("postgresql") if isinstance(results, dict) else None)
    if not sqlite["valid"]:
        failures.append("sqlite_raw_rounds")
    if not postgres["valid"]:
        failures.append("postgresql_raw_rounds")
    ratio = postgres["median_tps"] / sqlite["median_tps"] if sqlite["median_tps"] > 0 else 0.0
    performance_passed = (
        sqlite["valid"]
        and postgres["valid"]
        and sqlite["errors"] + postgres["errors"] == 0
        and ratio >= TPS_RATIO_MIN
    )
    if not performance_passed:
        failures.append(
            "write: "
            f"ratio={ratio:.6f}, cycles={MEASURED_CYCLES}, "
            f"errors={sqlite['errors'] + postgres['errors']}"
        )
    return {
        "passed": not failures,
        "criteria": {
            "format": SECTION_FORMAT,
            "format_version": SECTION_VERSION,
            "workload_order": list(WORKLOADS),
            "cycle_model": "one_each_in_workload_order",
            "rounds": ROUNDS,
            "concurrency": CONCURRENCY,
            "warmups_per_worker": WARMUPS_PER_WORKER,
            "iterations_per_worker": ITERATIONS_PER_WORKER,
            "measured_cycles_min": MEASURED_CYCLES,
            "postgresql_over_sqlite_tps_ratio_min": TPS_RATIO_MIN,
            "errors": 0,
            "raw_audits": True,
            "contracts": True,
            "source_binding": True,
            "temporary_target_cleanup": True,
        },
        "source_binding": dict(section.get("source_binding") or {}),
        "results": {
            "sqlite": {
                "rounds": sqlite["rounds"],
                "median_tps": sqlite["median_tps"],
                "median_p95_ms": sqlite["median_p95_ms"],
                "errors": sqlite["errors"],
                "valid": sqlite["valid"],
            },
            "postgresql": {
                "rounds": postgres["rounds"],
                "median_tps": postgres["median_tps"],
                "median_p95_ms": postgres["median_p95_ms"],
                "errors": postgres["errors"],
                "valid": postgres["valid"],
            },
        },
        "write_result": {
            "unit": "business_supercycle_v2",
            "sqlite_tps": sqlite["median_tps"],
            "postgres_tps": postgres["median_tps"],
            "ratio": ratio,
            # Keep this alias for existing API/report consumers. The unit is a
            # measured supercycle, not a database commit.
            "transactions": MEASURED_CYCLES,
            "measured_cycles": MEASURED_CYCLES,
            "errors": sqlite["errors"] + postgres["errors"],
            "passed": performance_passed,
        },
        "failures": failures,
    }


__all__ = [
    "BACKENDS",
    "BATCH_SIZE",
    "CONCURRENCY",
    "ITERATIONS_PER_WORKER",
    "MEASURED_CYCLES",
    "ROUNDS",
    "SECTION_FORMAT",
    "SECTION_VERSION",
    "TOTAL_CYCLES",
    "TPS_RATIO_MIN",
    "WARMUPS_PER_WORKER",
    "backend_order",
    "evaluate_business_composite_v2",
]
