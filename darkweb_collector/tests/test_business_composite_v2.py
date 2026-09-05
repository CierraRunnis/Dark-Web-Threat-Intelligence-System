from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from threading import Lock

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"
for path in (SCRIPTS, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SCRIPT_PATH = SCRIPTS / "benchmark_business_composite_v2.py"
SPEC = importlib.util.spec_from_file_location("dwti_business_composite_v2", SCRIPT_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)

import _writebench_composite as composite
from _writebench_core import RunConfig, _shared_benchmark_module
from _writebench_targets import SQLiteTarget
from darkweb_collector import db
from darkweb_collector.business_composite_gate import (
    BACKENDS,
    BATCH_SIZE,
    CONCURRENCY,
    ITERATIONS_PER_WORKER,
    ROUNDS,
    SECTION_FORMAT,
    SECTION_VERSION,
    TOTAL_CYCLES,
    WARMUPS_PER_WORKER,
    backend_order,
    evaluate_business_composite_v2,
)
from darkweb_collector.postgres_write_gate import WORKLOADS


def _audit() -> dict:
    return {
        "passed": True,
        "total_cycles": TOTAL_CYCLES,
        "workloads": {name: {"passed": True} for name in WORKLOADS},
    }


def _round(round_number: int, tps: float, *, errors: int = 0) -> dict:
    return {
        "round": round_number,
        "metrics": {
            "concurrency": CONCURRENCY,
            "warmups_per_worker": WARMUPS_PER_WORKER,
            "iterations_per_worker": ITERATIONS_PER_WORKER,
            "attempted_operations": CONCURRENCY * ITERATIONS_PER_WORKER,
            "successful_operations": CONCURRENCY * ITERATIONS_PER_WORKER,
            "p50_ms": 4.0,
            "p95_ms": 8.0,
            "throughput": tps,
            "errors": errors,
            "measurement_errors": errors,
            "warmup_errors": 0,
            "elapsed_seconds": 8.0,
        },
        "audit": _audit(),
    }


def passing_section(sqlite_tps: float = 100.0, postgres_tps: float = 200.0) -> dict:
    contracts = {"equivalence": {"equivalent": True}}
    for backend in BACKENDS:
        contracts[backend] = {
            "workloads": {name: {"passed": True} for name in WORKLOADS}
        }
    return {
        "format": SECTION_FORMAT,
        "format_version": SECTION_VERSION,
        "benchmark_id": "benchmark-id",
        "parameters": {
            "concurrency": CONCURRENCY,
            "warmups_per_worker": WARMUPS_PER_WORKER,
            "iterations_per_worker": ITERATIONS_PER_WORKER,
            "rounds": ROUNDS,
            "batch_size": BATCH_SIZE,
            "workloads": list(WORKLOADS),
            "cycle_model": "one_each_in_workload_order",
            "source_databases_written": False,
        },
        "source_binding": {
            "benchmark_id": "benchmark-id",
            "sqlite": {"path": "/frozen/source.db", "sha256": "sqlite"},
            "postgresql": {
                "schema": "dwti_candidate",
                "schema_version": "0006_postgres_read_paths",
                "schema_fingerprint": "fingerprint",
                "schema_snapshot_sha256": "candidate",
            },
        },
        "source_integrity": {
            "sqlite": {
                "sha256_before": "sqlite",
                "sha256_after": "sqlite",
            },
            "postgresql": {
                "sha256_before": "candidate",
                "sha256_after": "candidate",
            },
        },
        "contracts": contracts,
        "durability": {
            "sqlite": "FULL",
            "postgresql": "fsync=on,synchronous_commit=on",
        },
        "round_order": [
            {
                "round": index + 1,
                "backend_order": list(backend_order(index)),
            }
            for index in range(ROUNDS)
        ],
        "results": {
            "sqlite": {
                "round_results": [
                    _round(index + 1, sqlite_tps) for index in range(ROUNDS)
                ]
            },
            "postgresql": {
                "round_results": [
                    _round(index + 1, postgres_tps) for index in range(ROUNDS)
                ]
            },
        },
        "temporary_targets": {
            "sqlite": {
                "records": [
                    {"round": index + 1, "created": True, "removed": True}
                    for index in range(ROUNDS)
                ],
                "leftovers": [],
            },
            "postgresql": {
                "records": [
                    {
                        "round": index + 1,
                        "created": True,
                        "dropped": True,
                        "cleanup_error": "",
                    }
                    for index in range(ROUNDS)
                ],
                "leftovers": [],
            },
        },
        # A submitted aggregate is deliberately ignored.
        "gate": {"passed": False, "write_result": {"ratio": 999}},
    }


def test_v2_evaluator_recomputes_exact_two_x_from_raw_rounds() -> None:
    section = passing_section()
    result = evaluate_business_composite_v2(section)

    assert result["passed"] is True
    assert result["write_result"]["ratio"] == pytest.approx(2.0)
    assert result["write_result"]["transactions"] == 800
    assert result["write_result"]["unit"] == "business_supercycle_v2"
    assert result["write_result"] is not section["gate"]["write_result"]


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("ratio", "write:"),
        ("rounds", "sqlite_raw_rounds"),
        ("errors", "postgresql_raw_rounds"),
        ("audit", "postgresql_raw_rounds"),
        ("cleanup", "temporary_target_cleanup"),
        ("binding", "source_binding.sqlite.sha256"),
        ("order", "round_order"),
        ("parameters", "parameters"),
        ("contracts", "contracts"),
    ],
)
def test_v2_evaluator_rejects_invalid_raw_evidence(
    mutation: str,
    failure: str,
) -> None:
    section = passing_section()
    if mutation == "ratio":
        for item in section["results"]["postgresql"]["round_results"]:
            item["metrics"]["throughput"] = 199.999
    elif mutation == "rounds":
        section["results"]["sqlite"]["round_results"].pop()
    elif mutation == "errors":
        item = section["results"]["postgresql"]["round_results"][0]
        item["metrics"]["errors"] = 1
        item["metrics"]["measurement_errors"] = 1
    elif mutation == "audit":
        section["results"]["postgresql"]["round_results"][0]["audit"]["passed"] = False
    elif mutation == "cleanup":
        section["temporary_targets"]["postgresql"]["records"][0]["dropped"] = False
    elif mutation == "binding":
        section["source_integrity"]["sqlite"]["sha256_after"] = "changed"
    elif mutation == "order":
        section["round_order"][1]["backend_order"] = list(BACKENDS)
    elif mutation == "parameters":
        section["parameters"]["iterations_per_worker"] = 99
    else:
        section["contracts"]["postgresql"]["workloads"]["detail"]["passed"] = False

    result = evaluate_business_composite_v2(section)
    assert result["passed"] is False
    assert any(failure in item for item in result["failures"])


def test_cli_defaults_are_the_formal_gate_shape(tmp_path: Path) -> None:
    args = benchmark.build_parser().parse_args(
        [
            "--sqlite-db",
            str(tmp_path / "source.db"),
            "--postgres-schema",
            "dwti_candidate",
            "--output",
            str(tmp_path / "report.json"),
        ]
    )
    assert (
        args.concurrency,
        args.warmups,
        args.iterations,
        args.rounds,
        args.batch_size,
    ) == (
        CONCURRENCY,
        WARMUPS_PER_WORKER,
        ITERATIONS_PER_WORKER,
        ROUNDS,
        BATCH_SIZE,
    )
    assert [backend_order(index) for index in range(3)] == [
        ("sqlite", "postgresql"),
        ("postgresql", "sqlite"),
        ("sqlite", "postgresql"),
    ]


def test_merge_downgrades_old_write_result_to_diagnostic(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    output = tmp_path / "merged.json"
    base.write_text(
        json.dumps(
            {
                "read_results": [{"scenario": "dashboard_overview"}],
                "write_result": {
                    "sqlite_tps": 100,
                    "postgres_tps": 999,
                    "transactions": 800,
                    "errors": 0,
                },
                "acceptance_preview": {"passed": True},
            }
        ),
        encoding="utf-8",
    )
    section = passing_section()
    merged = benchmark.merge_base_report(base, output, section)

    assert "write_result" not in merged
    assert "acceptance_preview" not in merged
    assert merged["legacy_diagnostic"]["acceptance_eligible"] is False
    assert merged["legacy_diagnostic"]["write_result"]["postgres_tps"] == 999
    assert merged["business_composite_v2"] is section


class _FakeConnection:
    def __init__(self, events: list[str], name: str = "primary") -> None:
        self.events = events
        self.name = name

    def commit(self) -> None:
        self.events.append(f"{self.name}:commit")

    def rollback(self) -> None:
        self.events.append(f"{self.name}:rollback")

    def close(self) -> None:
        self.events.append(f"{self.name}:close")


def test_job_lifecycle_uses_two_independent_checkouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connections = [
        _FakeConnection(events, "running"),
        _FakeConnection(events, "finished"),
    ]

    class Target:
        def connect(self):
            return connections.pop(0)

    def fake_upsert(connection, **kwargs):
        events.append(f"{connection.name}:{kwargs['status']}")

    monkeypatch.setattr(composite.db, "upsert_crawl_job", fake_upsert)
    composite._job_lifecycle(Target(), "job")

    assert events == [
        "running:running",
        "running:commit",
        "running:close",
        "finished:succeeded",
        "finished:commit",
        "finished:close",
    ]


def test_supercycle_keeps_profile_commits_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    class Paths:
        claim_calls = 0

        def mark_dirty(self, _connection):
            events.append("dirty")

        def claim(self, conn, *_args):
            self.claim_calls += 1
            events.append(f"claim:{self.claim_calls}")
            if self.claim_calls == 2:
                conn.rollback()
                return False
            return True

        def release(self, _connection, *_args):
            events.append("release")

    target = type("Target", (), {"paths": Paths()})()
    monkeypatch.setattr(
        composite, "_job_lifecycle", lambda _target, _key: events.append("job")
    )
    monkeypatch.setattr(
        composite,
        "_batch_transaction",
        lambda _connection, _paths, workload, _key, _size: events.append(
            workload
        ),
    )
    monkeypatch.setattr(
        composite,
        "victim_transaction",
        lambda *_args: events.append("victim"),
    )
    monkeypatch.setattr(
        composite,
        "topic_transaction",
        lambda *_args: events.append("topic"),
    )
    monkeypatch.setattr(
        composite,
        "detail_transaction",
        lambda *_args: events.append("detail"),
    )
    outcomes = {"true": 0, "false": 0}

    composite.execute_supercycle(
        connection,
        target,
        "cycle",
        outcomes,
        Lock(),
    )

    assert outcomes == {"true": 1, "false": 1}
    assert events == [
        "job",
        "dirty",
        "primary:commit",
        "claim:1",
        "primary:commit",
        "claim:2",
        "primary:rollback",
        "primary:commit",
        "release",
        "primary:commit",
        "vulnerability",
        "primary:commit",
        "ransomware",
        "primary:commit",
        "victim",
        "primary:commit",
        "topic",
        "primary:commit",
        "detail",
        "primary:commit",
    ]


def test_one_cycle_sqlite_smoke_preserves_all_audits(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    try:
        db._ensure_schema(connection)
        db.mark_normalized_intelligence_dirty(connection)
        connection.commit()
    finally:
        connection.close()

    benchmark_module = _shared_benchmark_module()
    target = SQLiteTarget(source, benchmark_module)
    with target:
        result = composite.run_business_composite(
            target,
            RunConfig(
                concurrency=1,
                warmups=0,
                iterations=1,
                rounds=1,
                batch_size=5,
            ),
            benchmark_module,
        )

    assert result["metrics"]["errors"] == 0
    assert result["metrics"]["successful_operations"] == 1
    assert result["audit"]["passed"] is True
    assert result["audit"]["revision_delta"] == 17
    assert result["audit"]["workloads"]["job_lifecycle"]["rows"] == [1, 1]
    assert target.temp_removed is True
