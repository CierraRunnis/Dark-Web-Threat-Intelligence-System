from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_databases.py"
SPEC = importlib.util.spec_from_file_location("dwti_benchmark_databases", SCRIPT_PATH)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


EXPECTED_SCENARIOS = {
    "dashboard_overview",
    "intelligence_search",
    "data_leak",
    "ransomware_vulnerability",
    "crawl_jobs",
    "code_document_monitoring",
    "ai_aggregation",
}


def _arguments(tmp_path: Path, *extra: str):
    return [
        "--sqlite-db",
        str(tmp_path / "collector.db"),
        "--postgres-url",
        "postgresql://user:secret@127.0.0.1:5432/dwti",
        "--postgres-schema",
        "dwti_release",
        "--output",
        str(tmp_path / "benchmark.json"),
        *extra,
    ]


def _passing_reads() -> list[dict]:
    results = []
    for scenario in sorted(EXPECTED_SCENARIOS):
        results.extend(
            [
                {
                    "scenario": scenario,
                    "concurrency": 1,
                    "sqlite_p95_ms": 100.0,
                    "postgres_p95_ms": 105.0,
                    "errors": 0,
                },
                {
                    "scenario": scenario,
                    "concurrency": 8,
                    "sqlite_p95_ms": 100.0,
                    "postgres_p95_ms": 75.0,
                    "errors": 0,
                },
            ]
        )
    return results


def test_fixed_scenarios_and_cli_defaults(tmp_path: Path) -> None:
    assert set(benchmark.SCENARIOS) == EXPECTED_SCENARIOS
    assert benchmark.READ_CONCURRENCIES == (1, 8)
    assert benchmark.WRITE_CONCURRENCY == 8

    parser = benchmark.build_parser()
    defaults = parser.parse_args(_arguments(tmp_path))
    assert defaults.warmups == 5
    assert defaults.iterations == 100
    assert defaults.iterations * benchmark.WRITE_CONCURRENCY == 800

    smoke = parser.parse_args(_arguments(tmp_path, "--warmups", "0", "--iterations", "2"))
    assert smoke.warmups == 0
    assert smoke.iterations == 2



def test_integral_float_and_decimal_have_identical_canonical_form() -> None:
    assert benchmark._canonical_value(51.0) == 51
    assert benchmark._canonical_value(Decimal("51")) == 51
    assert benchmark._canonical_json({"avg": 51.0}) == benchmark._canonical_json(
        {"avg": Decimal("51")}
    )
    assert benchmark._canonical_value(51.25) == 51.25

def test_search_pattern_is_discovered_from_existing_intelligence(tmp_path: Path) -> None:
    database = tmp_path / "search.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE normalized_intelligence_events (
                event_id TEXT PRIMARY KEY,
                title TEXT,
                victim TEXT,
                attacker TEXT,
                detail_text TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO normalized_intelligence_events VALUES (?, ?, ?, ?, ?)",
            ("event-1", "AcmeCredentialLeak", "Acme", "actor", "selective-token"),
        )
        connection.commit()
    finally:
        connection.close()

    pattern = benchmark.discover_search_pattern(benchmark.SQLiteReadBackend(database))
    assert pattern.startswith("%") and pattern.endswith("%")
    assert pattern != "%"
    assert pattern.strip("%")
    assert pattern.strip("%").casefold() in "AcmeCredentialLeak Acme actor selective-token".casefold()


def test_sqlite_write_benchmark_uses_disposable_backup(tmp_path: Path) -> None:
    source = tmp_path / "collector.db"
    connection = sqlite3.connect(source)
    try:
        connection.executescript(
            """
            CREATE TABLE source_marker(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO source_marker(value) VALUES ('original');
            CREATE TABLE crawl_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL UNIQUE,
                site_name TEXT NOT NULL,
                job_type TEXT NOT NULL,
                queue_name TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                enqueued_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                duration_ms INTEGER,
                error_message TEXT
            );
            CREATE INDEX idx_crawl_jobs_site_type_status
            ON crawl_jobs(site_name, job_type, status);
            CREATE INDEX idx_crawl_jobs_finished_at ON crawl_jobs(finished_at);
            CREATE TABLE normalized_intelligence_cache_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                source_signature TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                refreshed_at TEXT NOT NULL,
                source_revision INTEGER NOT NULL DEFAULT 0,
                applied_revision INTEGER NOT NULL DEFAULT 0,
                dirty_since TEXT NOT NULL DEFAULT '',
                dirty_at TEXT NOT NULL DEFAULT '',
                last_started_at TEXT NOT NULL DEFAULT '',
                last_finished_at TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                last_error_at TEXT NOT NULL DEFAULT '',
                normalization_version TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE ai_aggregation_schedule_claims (
                profile_id TEXT NOT NULL,
                scheduled_for TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (profile_id, scheduled_for)
            );
            """
        )
        connection.commit()
    finally:
        connection.close()

    source_before = source.read_bytes()
    temporary_path = None
    with benchmark.SQLiteWriteTarget(source) as target:
        temporary_path = target.database_path
        assert temporary_path is not None and temporary_path != source
        durability_connection = target.connect()
        try:
            assert durability_connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        finally:
            durability_connection.close()
        metrics = benchmark.run_concurrent(
            target.connect,
            target.operation,
            concurrency=2,
            warmups=1,
            iterations=3,
        )
        assert metrics["attempted_operations"] == 6
        assert metrics["successful_operations"] == 6
        assert metrics["errors"] == 0

        copied = sqlite3.connect(temporary_path)
        try:
            assert copied.execute("SELECT value FROM source_marker").fetchone()[0] == "original"
            assert copied.execute("SELECT COUNT(*) FROM crawl_jobs").fetchone()[0] == 0
            assert copied.execute(
                "SELECT COUNT(*) FROM ai_aggregation_schedule_claims"
            ).fetchone()[0] == 0
            revision = copied.execute(
                "SELECT source_revision FROM normalized_intelligence_cache_state WHERE id=1"
            ).fetchone()[0]
            assert revision >= 6
        finally:
            copied.close()

    assert temporary_path is not None and not temporary_path.exists()
    assert source.read_bytes() == source_before
    original = sqlite3.connect(source)
    try:
        tables = {
            row[0]
            for row in original.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        original.close()
    assert tables == {"source_marker", *benchmark.WRITE_TABLES}


def test_concurrent_measurement_records_latency_throughput_and_errors() -> None:
    class Connection:
        def close(self) -> None:
            pass

        def rollback(self) -> None:
            pass

    def operation(_connection, _worker: int, sequence: int) -> None:
        if sequence == 1:
            raise RuntimeError("expected failure")

    metrics = benchmark.run_concurrent(
        Connection,
        operation,
        concurrency=2,
        warmups=0,
        iterations=3,
    )
    assert metrics["attempted_operations"] == 6
    assert metrics["successful_operations"] == 4
    assert metrics["errors"] == 2
    assert metrics["p50_ms"] >= 0
    assert metrics["p95_ms"] >= metrics["p50_ms"]
    assert metrics["throughput"] > 0
    assert metrics["error_samples"] == ["RuntimeError: expected failure"]


def test_semantic_comparison_reports_named_mismatches() -> None:
    sqlite_snapshot = {
        "checks": {
            "pagination_total": 20,
            "ordering_sha256": "same",
            "json_country_sha256": "sqlite",
        },
        "scenarios": {
            "dashboard_overview": {"rows": 2, "sha256": "same"},
        },
    }
    postgres_snapshot = {
        "checks": {
            "pagination_total": 20,
            "ordering_sha256": "same",
            "json_country_sha256": "postgres",
        },
        "scenarios": {
            "dashboard_overview": {"rows": 2, "sha256": "same"},
        },
    }
    result = benchmark.compare_semantics(sqlite_snapshot, postgres_snapshot)
    assert result["passed"] is False
    assert result["mismatches"] == 1
    failed = [item for item in result["checks"] if not item["passed"]]
    assert [item["check"] for item in failed] == ["json_country_sha256"]


def test_report_matches_migration_performance_contract(tmp_path: Path) -> None:
    reads = _passing_reads()
    write = {
        "sqlite_tps": 100.0,
        "postgres_tps": 220.0,
        "transactions": 800,
        "errors": 0,
    }
    semantic = {"passed": True, "mismatches": 0, "checks": []}
    report = benchmark.build_report(
        sqlite_path=tmp_path / "collector.db",
        postgres_schema="dwti_release",
        warmups=5,
        iterations=100,
        read_results=reads,
        write_result=write,
        semantic=semantic,
        snapshots={"sqlite": {}, "postgresql": {}},
    )

    assert len(report["read_results"]) == 14
    assert report["write_result"]["transactions"] == 800
    assert report["semantic_equivalence"]["passed"] is True
    assert report["acceptance_preview"]["passed"] is True
    assert report["parameters"]["source_databases_written"] is False
    assert report["parameters"]["durability"] == {
        "sqlite": "FULL",
        "postgresql": "synchronous_commit=on",
    }

    output = tmp_path / "nested" / "report.json"
    benchmark.write_report(output, report)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["format"] == benchmark.REPORT_FORMAT
    assert persisted["read_results"] == reads


def test_script_does_not_discover_or_write_active_release() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "active_release" not in source
    assert "DARKWEB_COLLECTOR_DATABASE_URL" not in source
    assert "DROP SCHEMA" in source
    assert "TemporaryDirectory" in source
    assert "benchmark_transactions" not in source
    assert "(LIKE {}.{} INCLUDING ALL)" in source
    assert '("%",)' not in source
    assert "SET search_path TO {}, pg_catalog" in source
    for table_name in benchmark.WRITE_TABLES:
        assert table_name in source
