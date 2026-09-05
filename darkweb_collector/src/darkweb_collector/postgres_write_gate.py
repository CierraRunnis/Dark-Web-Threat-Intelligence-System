from __future__ import annotations

import math
import statistics
from typing import Any


WORKLOADS = (
    "job_lifecycle",
    "dirty",
    "claim",
    "vulnerability",
    "ransomware",
    "victim",
    "topic",
    "detail",
)

# These policies describe the code that is actually enabled in 0005. They are
# deliberately not read from the benchmark report: a submitted report must not
# be able to weaken its own acceptance criteria.
OPTIMIZED_WORKLOADS = (
    "dirty",
    "victim",
    "topic",
    "detail",
)
REGRESSION_WORKLOADS = (
    "job_lifecycle",
    "claim",
    "vulnerability",
    "ransomware",
)

RAW_POSTGRES_ROUNDS_MIN = 3
OPTIMIZED_TPS_RATIO_MIN = 1.15
CANDIDATE_P95_RATIO_MAX = 1.0


def _validate_policy() -> None:
    optimized = set(OPTIMIZED_WORKLOADS)
    regression = set(REGRESSION_WORKLOADS)
    workloads = set(WORKLOADS)
    if optimized & regression or optimized | regression != workloads:
        raise RuntimeError("PostgreSQL write gate policies must partition WORKLOADS")
    if len(workloads) != len(WORKLOADS):
        raise RuntimeError("PostgreSQL write gate workloads must be unique")


_validate_policy()


def _contracts_pass(contracts: Any) -> bool:
    if not isinstance(contracts, dict):
        return False
    equivalence = contracts.get("equivalence")
    if not isinstance(equivalence, dict) or equivalence.get("equivalent") is not True:
        return False
    for backend in ("sqlite", "baseline", "candidate"):
        suite = contracts.get(backend)
        workloads = suite.get("workloads") if isinstance(suite, dict) else None
        if not isinstance(workloads, dict) or set(workloads) != set(WORKLOADS):
            return False
        if any(
            not isinstance(workloads[name], dict) or workloads[name].get("passed") is not True
            for name in WORKLOADS
        ):
            return False
    return True


def _integrity_pass(integrity: Any) -> bool:
    if not isinstance(integrity, dict):
        return False
    sqlite = integrity.get("sqlite")
    postgres = integrity.get("postgresql")
    if not isinstance(sqlite, dict) or not isinstance(postgres, dict):
        return False
    sqlite_before = str(sqlite.get("sha256_before") or "")
    sqlite_after = str(sqlite.get("sha256_after") or "")
    if not sqlite_before or sqlite_before != sqlite_after:
        return False
    for variant in ("baseline", "candidate"):
        item = postgres.get(variant)
        if not isinstance(item, dict):
            return False
        before = str(item.get("sha256_before") or "")
        after = str(item.get("sha256_after") or "")
        if not before or before != after:
            return False
    return True


def _cleanup_pass(cleanup: Any) -> bool:
    if not isinstance(cleanup, dict) or cleanup.get("leftovers") not in ([], ()):
        return False
    records = cleanup.get("records")
    if not isinstance(records, list) or len(records) < 6:
        return False
    return all(
        isinstance(item, dict)
        and item.get("created") is True
        and item.get("dropped") is True
        and not str(item.get("cleanup_error") or "")
        for item in records
    )


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        if float(value) != parsed:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _raw_summary(value: Any) -> dict[str, Any]:
    rounds = value.get("round_results") if isinstance(value, dict) else None
    if not isinstance(rounds, list):
        rounds = []
    valid = len(rounds) >= RAW_POSTGRES_ROUNDS_MIN
    throughputs: list[float] = []
    p95_values: list[float] = []
    errors = 0
    for item in rounds:
        metrics = item.get("metrics") if isinstance(item, dict) else None
        audit = item.get("audit") if isinstance(item, dict) else None
        if not isinstance(metrics, dict) or not isinstance(audit, dict):
            valid = False
            continue
        throughput = _finite_float(metrics.get("throughput"))
        p95 = _finite_float(metrics.get("p95_ms"))
        item_errors = _non_negative_int(metrics.get("errors"))
        if throughput is None or p95 is None or item_errors is None:
            valid = False
            continue
        throughputs.append(throughput)
        p95_values.append(p95)
        errors += item_errors
        if throughput <= 0 or p95 < 0 or item_errors != 0 or audit.get("passed") is not True:
            valid = False
    if len(throughputs) != len(rounds) or len(p95_values) != len(rounds):
        valid = False
    return {
        "valid": valid,
        "rounds": len(rounds),
        "median_tps": statistics.median(throughputs) if throughputs else 0.0,
        "median_p95_ms": statistics.median(p95_values) if p95_values else 0.0,
        "errors": errors,
    }


def evaluate_postgres_write_paths(section: dict[str, Any]) -> dict[str, Any]:
    """Recompute the gate exclusively from raw contracts, hashes and rounds."""

    if not isinstance(section, dict):
        return {"passed": False, "criteria": {}, "checks": [], "failures": ["section_missing"]}
    failures: list[str] = []
    checks: list[dict[str, Any]] = []
    if not _contracts_pass(section.get("contracts")):
        failures.append("contracts")
    if not _integrity_pass(section.get("source_integrity")):
        failures.append("source_integrity")
    if not _cleanup_pass(section.get("temporary_schemas")):
        failures.append("temporary_schema_cleanup")
    results = section.get("results")
    baseline = results.get("baseline") if isinstance(results, dict) else None
    candidate = results.get("candidate") if isinstance(results, dict) else None
    optimized = set(OPTIMIZED_WORKLOADS)
    for workload in WORKLOADS:
        base = _raw_summary(baseline.get(workload) if isinstance(baseline, dict) else None)
        cand = _raw_summary(candidate.get(workload) if isinstance(candidate, dict) else None)
        ratio = cand["median_tps"] / base["median_tps"] if base["median_tps"] > 0 else 0.0
        p95_ratio = (
            cand["median_p95_ms"] / base["median_p95_ms"]
            if base["median_p95_ms"] > 0
            else 0.0
        )
        policy = "optimized" if workload in optimized else "regression"
        performance_gate_applied = policy == "optimized"
        required_tps_ratio = OPTIMIZED_TPS_RATIO_MIN if performance_gate_applied else None
        raw_passed = (
            base["valid"]
            and cand["valid"]
            and base["rounds"] >= RAW_POSTGRES_ROUNDS_MIN
            and cand["rounds"] >= RAW_POSTGRES_ROUNDS_MIN
            and base["errors"] + cand["errors"] == 0
        )
        performance_passed = not performance_gate_applied or (
            ratio >= OPTIMIZED_TPS_RATIO_MIN
            and base["median_p95_ms"] > 0
            and cand["median_p95_ms"] <= base["median_p95_ms"] * CANDIDATE_P95_RATIO_MAX
        )
        passed = raw_passed and performance_passed
        checks.append({
            "workload": workload,
            "policy": policy,
            "performance_gate_applied": performance_gate_applied,
            "passed": passed,
            "raw_rounds_and_audits_passed": base["valid"] and cand["valid"],
            "baseline_rounds": base["rounds"],
            "candidate_rounds": cand["rounds"],
            "baseline_tps": round(base["median_tps"], 6),
            "candidate_tps": round(cand["median_tps"], 6),
            "tps_ratio": round(ratio, 6),
            "required_tps_ratio": required_tps_ratio,
            "baseline_p95_ms": round(base["median_p95_ms"], 6),
            "candidate_p95_ms": round(cand["median_p95_ms"], 6),
            "p95_ratio": round(p95_ratio, 6),
            "errors": base["errors"] + cand["errors"],
        })
        if not passed:
            failures.append(
                f"{workload}: policy={policy}, raw={base['valid'] and cand['valid']}, "
                f"rounds={base['rounds']}/{cand['rounds']}, tps_ratio={ratio:.6f}, "
                f"p95={cand['median_p95_ms']:.6f}/{base['median_p95_ms']:.6f}, "
                f"errors={base['errors'] + cand['errors']}"
            )
    return {
        "passed": not failures,
        "criteria": {
            "raw_postgres_rounds_min": RAW_POSTGRES_ROUNDS_MIN,
            # Retained for report consumers written against the original gate.
            "candidate_tps_ratio_min": OPTIMIZED_TPS_RATIO_MIN,
            "optimized_candidate_tps_ratio_min": OPTIMIZED_TPS_RATIO_MIN,
            "regression_candidate_tps_ratio_min": None,
            "candidate_p95_ratio_max": CANDIDATE_P95_RATIO_MAX,
            "optimized_candidate_p95_ratio_max": CANDIDATE_P95_RATIO_MAX,
            "regression_candidate_p95_ratio_max": None,
            "errors": 0,
            "contracts": "all three backends and all workloads",
            "source_hashes_unchanged": True,
            "temporary_schema_leftovers": 0,
            "optimized_workloads": list(OPTIMIZED_WORKLOADS),
            "regression_workloads": list(REGRESSION_WORKLOADS),
            "workload_policy_source": "application_code",
        },
        "checks": checks,
        "failures": failures,
    }
