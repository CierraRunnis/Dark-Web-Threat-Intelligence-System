from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sqlite3
import sys

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "benchmark_api_reads.py"
)
SPEC = importlib.util.spec_from_file_location(
    "dwti_benchmark_api_reads",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


EXPECTED_SCENARIOS = (
    "dashboard_overview",
    "intelligence_home",
    "intelligence_deep_page",
    "intelligence_filtered_sorted",
    "data_leak",
    "ransomware",
    "vulnerability",
    "jobs",
    "code_summary",
    "code_hits",
    "document_summary",
    "document_hits",
    "ai_profiles",
    "ai_runs",
    "ai_report_detail",
)


def test_fixed_scenarios_are_get_only_and_redact_dynamic_inputs() -> None:
    scenarios = benchmark.fixed_scenarios(
        "Acme secret search",
        "run/private value",
    )
    benchmark._validate_scenarios(scenarios)

    assert tuple(item.name for item in scenarios) == EXPECTED_SCENARIOS
    assert all(item.path.startswith("/api/") for item in scenarios)
    assert all(item.report_path.startswith("/api/") for item in scenarios)
    assert all(item.method == "GET" for item in [
        type("Entry", (), {"method": benchmark.SAFE_METHOD})()
        for _scenario in scenarios
    ])
    filtered = next(
        item
        for item in scenarios
        if item.name == "intelligence_filtered_sorted"
    )
    report_detail = next(
        item
        for item in scenarios
        if item.name == "ai_report_detail"
    )
    assert "Acme" in filtered.path
    assert "Acme" not in filtered.report_path
    assert "__discovered__" in filtered.report_path
    assert "run/private value" not in report_detail.report_path
    assert "__report_run__" in report_detail.report_path


@pytest.mark.parametrize(
    "path",
    (
        "http://example.invalid/api/jobs",
        "/outside-api",
        "/api/jobs#fragment",
    ),
)
def test_scenario_validation_rejects_non_local_api_paths(path: str) -> None:
    with pytest.raises(benchmark.ApiBenchmarkError):
        benchmark._validate_scenarios(
            (benchmark.ApiScenario("unsafe", path, path),)
        )


def test_backend_order_rotates_by_round_and_scenario() -> None:
    assert benchmark.backend_order(0, 0) == ("sqlite", "postgresql")
    assert benchmark.backend_order(0, 1) == ("postgresql", "sqlite")
    assert benchmark.backend_order(1, 0) == ("postgresql", "sqlite")
    assert benchmark.backend_order(1, 1) == ("sqlite", "postgresql")


def test_response_canonicalization_only_removes_declared_dynamic_values() -> None:
    payload = {
        "generatedAt": "changes every request",
        "generated_at": "persisted report timestamp",
        "report": {
            "file_path": r"C:\runtime\reports\report.md",
            "sha256": "same",
        },
        "items": [{"id": 1, "value": 2.0}],
    }
    canonical = benchmark._canonical_response(payload)

    assert "generatedAt" not in canonical
    assert canonical["generated_at"] == "persisted report timestamp"
    assert canonical["report"]["file_path"] == "report.md"
    assert canonical["items"] == [{"id": 1, "value": 2}]


def test_jobs_canonicalization_ignores_only_runtime_backend_identity() -> None:
    sqlite_payload = {
        "overall_status": "正常",
        "runtime_db": {
            "runtime_db_path": "/tmp/sqlite/collector.db",
            "source_db_path": "/tmp/sqlite/collector.db",
            "using_runtime_db": False,
            "runtime_db_exists": True,
            "source_db_exists": True,
            "runtime_db_updated_at": "2026-08-25 09:00:00",
            "runtime_db_size_mb": 42.5,
            "meta_exists": False,
            "prepared_at": "",
            "copied_counts": {},
            "skipped_tables": {},
        },
    }
    postgres_payload = {
        "overall_status": "正常",
        "runtime_db": {
            "runtime_db_path": "/tmp/postgres/unused.db",
            "source_db_path": "/tmp/postgres/unused.db",
            "using_runtime_db": True,
            "runtime_db_exists": False,
            "source_db_exists": False,
            "runtime_db_updated_at": "",
            "runtime_db_size_mb": 0,
            "meta_exists": True,
            "prepared_at": "",
            "copied_counts": {},
            "skipped_tables": {},
        },
    }

    assert benchmark._semantic_sha256(
        sqlite_payload, scenario_name="jobs"
    ) == benchmark._semantic_sha256(
        postgres_payload, scenario_name="jobs"
    )
    assert benchmark._semantic_sha256(
        sqlite_payload
    ) != benchmark._semantic_sha256(postgres_payload)

    postgres_payload["runtime_db"]["copied_counts"] = {"crawl_jobs": 1}
    assert benchmark._semantic_sha256(
        sqlite_payload, scenario_name="jobs"
    ) != benchmark._semantic_sha256(
        postgres_payload, scenario_name="jobs"
    )



def test_metrics_record_latency_throughput_status_and_semantics() -> None:
    results = [
        benchmark.RequestResult(
            latency_ms=1.0,
            status_code=200,
            payload_bytes=100,
            semantic_sha256="same",
        ),
        benchmark.RequestResult(
            latency_ms=3.0,
            status_code=200,
            payload_bytes=200,
            semantic_sha256="same",
        ),
    ]
    metrics = benchmark._metrics(
        results,
        0.01,
        concurrency=1,
        warmups=5,
        iterations=2,
    )

    assert metrics["attempted_requests"] == 2
    assert metrics["successful_requests"] == 2
    assert metrics["p50_ms"] == 2.0
    assert metrics["p95_ms"] == 2.9
    assert metrics["throughput"] == 200.0
    assert metrics["status_counts"] == {"200": 2}
    assert metrics["errors"] == 0
    assert metrics["average_payload_bytes"] == 150.0
    assert metrics["semantic_hashes"] == {"same": 2}
    assert metrics["semantic_stable"] is True


def test_child_environment_removes_inherited_database_and_flocks_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DARKWEB_COLLECTOR_DATABASE_URL",
        "postgresql://user:secret@localhost/db",
    )
    monkeypatch.setenv("DARKWEB_AUTH_PASSWORD", "secret")
    monkeypatch.setenv("FLOCKS_API_KEY", "secret")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))

    environment = benchmark._safe_environment(
        user_data_root=tmp_path / "user-data",
        output_root=tmp_path / "output",
    )

    assert environment["DARKWEB_API_AUTH_DISABLED"] == "1"
    assert environment["DARKWEB_BASIC_AUTH_ENABLED"] == "0"
    assert environment["DARKWEB_SKIP_API_WARMUP"] == "1"
    assert environment["DARKWEB_POSTGRES_POOL_WAIT_TIMEOUT_SECONDS"] == "30"
    assert environment["DARKWEB_USER_DATA_ROOT"] == str(
        tmp_path / "user-data"
    )
    assert "DARKWEB_COLLECTOR_DATABASE_URL" not in environment
    assert "DARKWEB_AUTH_PASSWORD" not in environment
    assert "FLOCKS_API_KEY" not in environment
    assert "postgresql://user:secret" not in repr(environment)


def test_sqlite_backup_uses_snapshot_and_never_changes_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "copy" / "collector.db"
    with sqlite3.connect(source) as connection:
        connection.executescript(
            """
            CREATE TABLE marker(id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO marker(value) VALUES ('original');
            CREATE TABLE normalized_intelligence_cache_state (
                id INTEGER PRIMARY KEY,
                source_revision INTEGER NOT NULL,
                applied_revision INTEGER NOT NULL,
                source_signature TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                refreshed_at TEXT NOT NULL
            );
            INSERT INTO normalized_intelligence_cache_state
            VALUES (1, 3, 2, 'signature', 1, 'now');
            """
        )

    source_hash = benchmark._file_sha256(source)
    benchmark.create_sqlite_backup(source, destination)

    assert benchmark._file_sha256(source) == source_hash
    with sqlite3.connect(destination) as connection:
        assert connection.execute(
            "SELECT value FROM marker"
        ).fetchone()[0] == "original"


def test_cli_defaults_and_report_version(tmp_path: Path) -> None:
    parser = benchmark.build_parser()
    args = parser.parse_args(
        [
            "run",
            "--sqlite-db",
            str(tmp_path / "collector.db"),
            "--postgres-target",
            str(tmp_path / "target.json"),
            "--postgres-schema",
            "dwti_candidate",
            "--output",
            str(tmp_path / "api-report.json"),
        ]
    )

    assert args.warmups == 5
    assert args.iterations == 100
    assert args.request_timeout == 30.0
    assert benchmark.CONCURRENCIES == (1, 8)
    assert benchmark.REPORT_FORMAT == "dwti-api-read-benchmark"
    assert benchmark.REPORT_VERSION == 2


def test_api_server_command_uses_target_path_not_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = benchmark.ApiServer(
        backend="postgresql",
        database_path=tmp_path / "postgresql-target.json",
        schema="dwti_candidate",
        working_root=tmp_path / "server",
        secrets=("postgresql://user:secret@localhost/db",),
    )

    assert str(server.database_path).endswith("postgresql-target.json")
    assert "postgresql://user:secret" not in str(server.database_path)
