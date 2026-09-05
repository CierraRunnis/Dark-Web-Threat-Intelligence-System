from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"
for path in (SCRIPTS, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SCRIPT_PATH = SCRIPTS / "benchmark_postgres_write_paths.py"
SPEC = importlib.util.spec_from_file_location("dwti_writebench_main", SCRIPT_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)

from darkweb_collector import db
from _writebench_contracts import run_contracts
from _writebench_core import RunConfig, WriteBenchmarkError
from darkweb_collector.postgres_write_gate import (
    OPTIMIZED_WORKLOADS,
    REGRESSION_WORKLOADS,
    WORKLOADS,
    evaluate_postgres_write_paths,
)
from _writebench_paths import LegacyPostgresPaths, ProductionPaths
from _writebench_profiles import run_profile
from _writebench_targets import CleanupRegistry, PostgresTarget, SQLiteTarget


def _arguments(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--sqlite-db", str(tmp_path / "collector.db"),
        "--baseline-schema", "dwti_baseline",
        "--candidate-schema", "dwti_candidate",
        "--output", str(tmp_path / "output.json"),
        *extra,
    ]


def _raw_round(tps: float, p95: float, *, errors: int = 0, audit: bool = True) -> dict:
    return {
        "metrics": {"throughput": tps, "p95_ms": p95, "p50_ms": p95 / 2, "errors": errors},
        "audit": {"passed": audit},
    }


def _passing_section() -> dict:
    contracts = {
        "passed": False,
        "equivalence": {"passed": False, "equivalent": True},
    }
    for backend in ("sqlite", "baseline", "candidate"):
        contracts[backend] = {
            "passed": False,
            "workloads": {name: {"passed": True} for name in WORKLOADS},
        }
    baseline = {}
    candidate = {}
    for workload in WORKLOADS:
        baseline[workload] = {
            "rounds": 999,
            "median_tps": 999999,
            "median_p95_ms": 0.001,
            "errors": 999,
            "round_results": [_raw_round(100, 10) for _ in range(3)],
        }
        candidate[workload] = {
            "rounds": 0,
            "median_tps": 1,
            "median_p95_ms": 999999,
            "errors": 999,
            "round_results": [_raw_round(116, 9) for _ in range(3)],
        }
    records = [
        {"created": True, "dropped": True, "cleanup_error": ""}
        for _ in range(6)
    ]
    return {
        "parameters": {"postgres_rounds": 1},
        "contracts": contracts,
        "source_integrity": {
            "passed": False,
            "sqlite": {"sha256_before": "sqlite", "sha256_after": "sqlite"},
            "postgresql": {
                "baseline": {"sha256_before": "base", "sha256_after": "base"},
                "candidate": {"sha256_before": "cand", "sha256_after": "cand"},
            },
        },
        "results": {"baseline": baseline, "candidate": candidate},
        "temporary_schemas": {
            "created": 0, "dropped": 0, "records": records, "leftovers": [],
        },
    }


def test_cli_defaults_and_workloads(tmp_path: Path) -> None:
    args = benchmark.build_parser().parse_args(_arguments(tmp_path))
    assert args.concurrency == 8
    assert args.warmups == 5
    assert args.iterations == 100
    assert args.rounds == 3
    assert args.batch_size == 5
    assert tuple(WORKLOADS) == (
        "job_lifecycle", "dirty", "claim", "vulnerability",
        "ransomware", "victim", "topic", "detail",
    )


def test_variant_order_rotates_baseline_and_candidate() -> None:
    for workload_index in range(len(WORKLOADS)):
        orders = [benchmark.variant_order(round_index, workload_index) for round_index in range(3)]
        assert set(orders) == {("baseline", "candidate"), ("candidate", "baseline")}


def test_evaluator_uses_raw_rounds_not_aggregate_fields() -> None:
    section = _passing_section()
    result = benchmark.evaluate_postgres_write_paths(section)
    assert result["passed"] is True
    assert all(item["tps_ratio"] == 1.16 for item in result["checks"])
    assert all(item["baseline_p95_ms"] == 10 for item in result["checks"])
    assert all(item["candidate_p95_ms"] == 9 for item in result["checks"])
    assert result["criteria"]["optimized_workloads"] == list(OPTIMIZED_WORKLOADS)
    assert result["criteria"]["regression_workloads"] == list(REGRESSION_WORKLOADS)


def test_evaluator_uses_code_owned_optimized_and_regression_policies() -> None:
    regression = _passing_section()
    regression["parameters"]["optimized_workloads"] = list(WORKLOADS)
    for item in regression["results"]["candidate"]["job_lifecycle"]["round_results"]:
        item["metrics"]["throughput"] = 1
        item["metrics"]["p95_ms"] = 999
    result = benchmark.evaluate_postgres_write_paths(regression)
    assert result["passed"] is True
    job = next(item for item in result["checks"] if item["workload"] == "job_lifecycle")
    assert job["policy"] == "regression"
    assert job["performance_gate_applied"] is False
    assert job["tps_ratio"] == 0.01
    assert job["p95_ratio"] == 99.9
    assert job["required_tps_ratio"] is None

    optimized = _passing_section()
    optimized["parameters"]["regression_workloads"] = list(WORKLOADS)
    for item in optimized["results"]["candidate"]["dirty"]["round_results"]:
        item["metrics"]["throughput"] = 114
    result = benchmark.evaluate_postgres_write_paths(optimized)
    assert result["passed"] is False
    dirty = next(item for item in result["checks"] if item["workload"] == "dirty")
    assert dirty["policy"] == "optimized"
    assert dirty["performance_gate_applied"] is True
    assert dirty["required_tps_ratio"] == 1.15


@pytest.mark.parametrize("mutation", ["tps", "p95", "errors", "audit", "rounds"])
def test_evaluator_rejects_raw_performance_failures(mutation: str) -> None:
    section = _passing_section()
    rounds = section["results"]["candidate"]["dirty"]["round_results"]
    if mutation == "tps":
        for item in rounds:
            item["metrics"]["throughput"] = 114
    elif mutation == "p95":
        for item in rounds:
            item["metrics"]["p95_ms"] = 11
    elif mutation == "errors":
        rounds[1]["metrics"]["errors"] = 1
    elif mutation == "audit":
        rounds[1]["audit"]["passed"] = False
    else:
        del rounds[-1]
    assert benchmark.evaluate_postgres_write_paths(section)["passed"] is False


@pytest.mark.parametrize("mutation", ["errors", "audit", "rounds"])
def test_regression_workloads_still_require_valid_raw_rounds(mutation: str) -> None:
    section = _passing_section()
    rounds = section["results"]["candidate"]["claim"]["round_results"]
    if mutation == "errors":
        rounds[1]["metrics"]["errors"] = 1
    elif mutation == "audit":
        rounds[1]["audit"]["passed"] = False
    else:
        del rounds[-1]
    result = benchmark.evaluate_postgres_write_paths(section)
    assert result["passed"] is False
    claim = next(item for item in result["checks"] if item["workload"] == "claim")
    assert claim["performance_gate_applied"] is False
    assert claim["passed"] is False


def test_evaluator_recomputes_contract_integrity_and_cleanup() -> None:
    section = _passing_section()
    section["contracts"]["candidate"]["workloads"]["victim"]["passed"] = False
    assert benchmark.evaluate_postgres_write_paths(section)["passed"] is False

    section = _passing_section()
    section["source_integrity"]["postgresql"]["candidate"]["sha256_after"] = "changed"
    assert benchmark.evaluate_postgres_write_paths(section)["passed"] is False

    section = _passing_section()
    section["temporary_schemas"]["records"][0]["dropped"] = False
    assert benchmark.evaluate_postgres_write_paths(section)["passed"] is False


def test_base_report_merge_preserves_source_and_existing_gate(tmp_path: Path) -> None:
    source = tmp_path / "performance-report.json"
    source_payload = {
        "format": "dwti-database-benchmark",
        "read_results": [{"scenario": "dashboard_overview"}],
        "write_result": {"sqlite_tps": 100, "postgres_tps": 210},
        "semantic_equivalence": {"passed": True},
    }
    source.write_text(json.dumps(source_payload), encoding="utf-8")
    output = tmp_path / "merged.json"
    section = _passing_section()
    merged = benchmark.merge_base_report(source, output, section)
    assert merged["read_results"] == source_payload["read_results"]
    assert merged["write_result"] == source_payload["write_result"]
    assert merged["semantic_equivalence"] == source_payload["semantic_equivalence"]
    assert merged["postgres_write_paths"] is section
    assert json.loads(source.read_text(encoding="utf-8")) == source_payload
    with pytest.raises(WriteBenchmarkError, match="must not overwrite"):
        benchmark.merge_base_report(source, source, section)


def test_source_schema_names_cannot_use_cleanup_prefix() -> None:
    with pytest.raises(WriteBenchmarkError, match="disposable prefix"):
        benchmark._source_identifier("dwti_writebench_0123456789abcdef0123", "source")
    with pytest.raises(WriteBenchmarkError):
        benchmark._source_identifier("public;drop schema public", "source")


def test_core_has_one_evaluator_implementation() -> None:
    core = (SCRIPTS / "_writebench_core.py").read_text(encoding="utf-8")
    evaluator = (SCRIPTS / "_writebench_evaluator.py").read_text(encoding="utf-8")
    shared = (SRC / "darkweb_collector" / "postgres_write_gate.py").read_text(encoding="utf-8")
    assert "def evaluate_postgres_write_paths" not in core
    assert "WORKLOADS =" not in core
    assert "def evaluate_postgres_write_paths" not in evaluator
    assert shared.count("def evaluate_postgres_write_paths") == 1
    assert benchmark.evaluate_postgres_write_paths is evaluate_postgres_write_paths

def test_main_runtime_dependencies_are_imported() -> None:
    assert benchmark.sqlite3 is sqlite3
    assert callable(benchmark.close_postgres_pools)


class _BenchmarkClaimConnection:
    backend_name = "postgresql"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.rollbacks = 0

    def execute(self, sql_text: str, _parameters):
        self.calls.append(sql_text)
        if len(self.calls) == 2:
            raise db.PostgreSQLIntegrityError("duplicate claim")
        return object()

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.parametrize("paths_type", [LegacyPostgresPaths, ProductionPaths])
def test_benchmark_claim_paths_match_reverted_production(paths_type) -> None:
    connection = _BenchmarkClaimConnection()
    paths = paths_type()

    assert paths.claim(connection, "profile", "slot", "created") is True
    assert paths.claim(connection, "profile", "slot", "changed") is False
    assert connection.rollbacks == 1
    assert len(connection.calls) == 2
    assert all("ON CONFLICT" not in sql for sql in connection.calls)
    assert all("RETURNING" not in sql for sql in connection.calls)


def test_benchmark_variants_hold_reverted_connector_constant() -> None:
    registry = CleanupRegistry()
    modes = set()
    for variant in ("baseline", "candidate"):
        target = PostgresTarget(
            migration_url="postgresql://migration/db",
            runtime_url="postgresql://runtime/db",
            source_schema="dwti_source",
            variant=variant,
            fingerprint="fixture",
            registry=registry,
        )
        modes.add(target._record["connector_mode"])

    assert modes == {"production_double_session_auto_identity_returning"}


def test_sqlite_contracts_and_all_profiles_use_temporary_backup(tmp_path: Path) -> None:
    source = tmp_path / "collector.db"
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    try:
        db._ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO normalized_intelligence_cache_state(
                id, source_signature, event_count, refreshed_at,
                source_revision, applied_revision, dirty_since, dirty_at
            ) VALUES(1, 'fixture', 0, '', 0, 0, '', '')
            """
        )
        connection.commit()
    finally:
        connection.close()
    before = source.read_bytes()
    shared = benchmark._shared_benchmark_module()
    target = SQLiteTarget(source, shared)
    with target:
        temporary = target.database_path
        assert temporary is not None and temporary != source
        contracts = run_contracts(target)
        assert contracts["passed"] is True
        smoke = RunConfig(concurrency=1, warmups=0, iterations=1, rounds=1, batch_size=2)
        for workload in WORKLOADS:
            result = run_profile(target, workload, smoke, shared)
            assert result["metrics"]["errors"] == 0
            assert result["audit"]["passed"] is True
    assert target.temp_removed is True
    assert source.read_bytes() == before

