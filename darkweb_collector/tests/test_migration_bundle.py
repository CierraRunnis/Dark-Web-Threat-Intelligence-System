from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace
import zipfile

import pytest
from fastapi import HTTPException

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
)
from darkweb_collector.db import _ensure_schema
import darkweb_collector.migration_api as migration_api_module
import darkweb_collector.migration_bundle as migration_bundle_module
from darkweb_collector.migration_api import _require_admin
from darkweb_collector.postgres_write_gate import WORKLOADS
from darkweb_collector.migration_bundle import (
    EXPECTED_BUSINESS_TABLES,
    PERFORMANCE_READ_SCENARIOS,
    PORTABLE_ARTIFACT_PATH_PREFIX,
    MigrationBundleError,
    _ArtifactPathIndex,
    _portable_artifact_row,
    _sanitized_row,
    activate_import,
    evaluate_performance_report,
    exclusive_file_lock,
    export_bundle,
    performance_acceptance_passed,
    preflight_bundle,
)


def _empty_current_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        _ensure_schema(connection)
        # Keep this fixture representative of the pre-migration local 38-table database,
        # even after the runtime schema starts creating the new probe table itself.
        connection.execute("DROP TABLE IF EXISTS site_connectivity_probes")
        connection.commit()
    finally:
        connection.close()


def _insert_legacy_ai_profile(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO ai_aggregation_profiles(
                id, name, keyword, prompt_template, keywords_json, enabled,
                search_window_days, sources_json, language, schedule_enabled,
                cron, timezone, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-profile",
                "Legacy profile",
                "legacy-keyword",
                "search {{keywords}}",
                "[]",
                1,
                7,
                "[]",
                "zh-CN",
                0,
                None,
                "Asia/Shanghai",
                "2026-08-01T00:00:00+00:00",
                "2026-08-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _raw_write_round(tps: float, p95: float) -> dict:
    return {
        "metrics": {"throughput": tps, "p95_ms": p95, "p50_ms": p95 / 2, "errors": 0},
        "audit": {"passed": True},
    }


def _passing_postgres_write_section() -> dict:
    contracts = {
        "equivalence": {"equivalent": True},
    }
    for backend in ("sqlite", "baseline", "candidate"):
        contracts[backend] = {
            "workloads": {name: {"passed": True} for name in WORKLOADS},
        }
    baseline = {
        name: {"round_results": [_raw_write_round(100, 10) for _ in range(3)]}
        for name in WORKLOADS
    }
    candidate = {
        name: {"round_results": [_raw_write_round(116, 9) for _ in range(3)]}
        for name in WORKLOADS
    }
    return {
        "parameters": {
            "postgres_rounds": 3,
            "workloads": list(WORKLOADS),
        },
        "contracts": contracts,
        "source_integrity": {
            "sqlite": {"sha256_before": "sqlite", "sha256_after": "sqlite"},
            "postgresql": {
                "baseline": {"sha256_before": "baseline", "sha256_after": "baseline"},
                "candidate": {"sha256_before": "candidate", "sha256_after": "candidate"},
            },
        },
        "results": {
            "baseline": baseline,
            "candidate": candidate,
        },
        "temporary_schemas": {
            "records": [
                {"created": True, "dropped": True, "cleanup_error": ""}
                for _ in range(6)
            ],
            "leftovers": [],
        },
    }


def _passing_business_composite_section(
    sqlite_tps: float = 100.0,
    postgres_tps: float = 210.0,
) -> dict:
    contracts = {"equivalence": {"equivalent": True}}
    for backend in BACKENDS:
        contracts[backend] = {
            "workloads": {name: {"passed": True} for name in WORKLOADS}
        }

    def raw_round(round_number: int, throughput: float) -> dict:
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
                "throughput": throughput,
                "errors": 0,
                "measurement_errors": 0,
                "warmup_errors": 0,
                "elapsed_seconds": 8.0,
            },
            "audit": {
                "passed": True,
                "total_cycles": TOTAL_CYCLES,
                "workloads": {
                    name: {"passed": True} for name in WORKLOADS
                },
            },
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
                    raw_round(index + 1, sqlite_tps)
                    for index in range(ROUNDS)
                ]
            },
            "postgresql": {
                "round_results": [
                    raw_round(index + 1, postgres_tps)
                    for index in range(ROUNDS)
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
    }


def _passing_performance_report() -> dict:
    reads = []
    for scenario in sorted(PERFORMANCE_READ_SCENARIOS):
        reads.extend(
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
    return {
        "read_results": reads,
        "write_result": {
            "sqlite_tps": 100.0,
            "postgres_tps": 210.0,
            "transactions": 800,
            "errors": 0,
        },
        "semantic_equivalence": {"passed": True, "mismatches": 0},
        "postgres_write_paths": _passing_postgres_write_section(),
        "business_composite_v2": _passing_business_composite_section(),
    }


def test_export_upgrades_local_38_tables_to_required_39_table_bundle(tmp_path: Path) -> None:
    database = tmp_path / "collector.db"
    artifacts = tmp_path / "output"
    bundle = tmp_path / "snapshot.dwti"
    artifacts.mkdir()
    _empty_current_database(database)

    before = sqlite3.connect(database)
    try:
        source_tables = {
            row[0]
            for row in before.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        before.close()
    assert len(source_tables) == 38
    assert "site_connectivity_probes" not in source_tables

    report = export_bundle(database, artifacts, bundle)
    preflight = preflight_bundle(bundle)

    assert report["tables"] == 39
    assert preflight["tables"] == 39
    manifest = preflight["manifest"]
    assert {table["name"] for table in manifest["schema"]["tables"]} == EXPECTED_BUSINESS_TABLES
    assert manifest["tables"]["site_connectivity_probes"]["stats"]["rows"] == 0

    with zipfile.ZipFile(bundle) as archive:
        assert "manifest.json" in archive.namelist()
        assert "checksums.sha256" in archive.namelist()
        embedded = json.loads(archive.read("manifest.json"))
    assert embedded["source"]["quick_check"] == "ok"


def test_ai_delivery_credentials_are_removed_and_targets_disabled() -> None:
    columns = ["id", "profile_id", "enabled", "config_json"]
    values = ["target-1", "profile-1", 1, '{"webhook":"https://secret","token":"abc"}']

    sanitized, fields = _sanitized_row(
        "ai_aggregation_delivery_targets",
        columns,
        values,
    )

    assert sanitized[columns.index("enabled")] == 0
    assert sanitized[columns.index("config_json")] == "{}"
    assert "ai_aggregation_delivery_targets.enabled" in fields
    assert "ai_aggregation_delivery_targets.config_json" in fields

    attempt_columns = ["id", "target_config_json", "last_error"]
    attempt, attempt_fields = _sanitized_row(
        "ai_aggregation_delivery_attempts",
        attempt_columns,
        ["attempt-1", '{"webhook":"https://secret"}', "request included token abc"],
    )
    assert attempt == ["attempt-1", "{}", ""]
    assert set(attempt_fields) == {
        "ai_aggregation_delivery_attempts.target_config_json",
        "ai_aggregation_delivery_attempts.last_error",
    }


def test_ai_report_path_is_rewritten_to_portable_artifact() -> None:
    relative = "ai-aggregation/reports/run-1.md"
    index = _ArtifactPathIndex({relative: relative})
    columns = ["id", "run_id", "file_path", "sha256"]

    values, rewritten = _portable_artifact_row(
        "ai_aggregation_reports",
        columns,
        ["report-1", "run-1", f"/srv/output/{relative}", "digest"],
        index,
    )

    assert values[2] == PORTABLE_ARTIFACT_PATH_PREFIX + relative
    assert rewritten == ["ai_aggregation_reports.file_path"]


def test_performance_acceptance_enforces_all_thresholds() -> None:
    report = _passing_performance_report()
    report["postgres_write_paths"]["gate"] = {"passed": False, "failures": ["forged"]}
    report["business_composite_v2"]["gate"] = {"passed": False, "failures": ["forged"]}
    accepted = evaluate_performance_report(report)
    assert accepted["passed"] is True
    assert accepted["write_result"]["ratio"] == pytest.approx(2.1)
    assert len(accepted["read_results"]) == len(PERFORMANCE_READ_SCENARIOS) * 2
    assert accepted["postgres_write_paths"]["passed"] is True
    assert accepted["postgres_write_paths"] is not report["postgres_write_paths"]["gate"]
    assert accepted["business_composite_v2"]["passed"] is True
    assert accepted["business_composite_v2"] is not report["business_composite_v2"]["gate"]

    failed = _passing_performance_report()
    failed["read_results"][1]["postgres_p95_ms"] = 81.0
    with pytest.raises(MigrationBundleError, match="验收未通过"):
        evaluate_performance_report(failed)

    incomplete = _passing_performance_report()
    incomplete["read_results"].pop()
    with pytest.raises(MigrationBundleError, match="缺少读取场景"):
        evaluate_performance_report(incomplete)

    legacy_only = _passing_performance_report()
    legacy_only["write_result"]["postgres_tps"] = 0.001
    accepted = evaluate_performance_report(legacy_only)
    assert accepted["write_result"]["ratio"] == pytest.approx(2.1)
    assert accepted["legacy_diagnostic"]["acceptance_eligible"] is False
    assert accepted["legacy_diagnostic"]["write_result"]["postgres_tps"] == 0.001

    composite_regression = _passing_performance_report()
    rounds = composite_regression["business_composite_v2"]["results"]["postgresql"]["round_results"]
    for item in rounds:
        item["metrics"]["throughput"] = 199.9
    with pytest.raises(MigrationBundleError, match="business_composite_v2"):
        evaluate_performance_report(composite_regression)


def test_performance_acceptance_requires_and_recomputes_write_path_section() -> None:
    no_composite = _passing_performance_report()
    no_composite.pop("business_composite_v2")
    with pytest.raises(MigrationBundleError, match="business_composite_v2"):
        evaluate_performance_report(no_composite)

    historical = _passing_performance_report()
    historical.pop("postgres_write_paths")
    with pytest.raises(MigrationBundleError, match="旧版报告不能用于 0005"):
        evaluate_performance_report(historical)

    forged = _passing_performance_report()
    forged["postgres_write_paths"]["gate"] = {"passed": True, "failures": []}
    rounds = forged["postgres_write_paths"]["results"]["candidate"]["dirty"]["round_results"]
    for item in rounds:
        item["metrics"]["throughput"] = 114
    with pytest.raises(MigrationBundleError, match="postgres_write_paths"):
        evaluate_performance_report(forged)


def test_activation_rejects_historical_required_acceptance_without_write_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = {"required": True, "passed": True}
    assert performance_acceptance_passed(historical) is False
    assert performance_acceptance_passed({"required": False, "passed": True}) is True
    with pytest.raises(MigrationBundleError, match="尚未通过"):
        activate_import({"performance_acceptance": historical}, "postgresql://unused")

    monkeypatch.setenv("DARKWEB_API_AUTH_DISABLED", "0")
    monkeypatch.setattr(
        migration_api_module,
        "_read_state",
        lambda _job_id: {
            "status": "ready",
            "report": {"performance_acceptance": historical},
        },
    )
    request = SimpleNamespace(state=SimpleNamespace(current_user={"role": "admin"}))
    with pytest.raises(HTTPException) as caught:
        migration_api_module.activate_migration("historical", request)
    assert caught.value.status_code == 409


def test_migration_admin_authorization_uses_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DARKWEB_API_AUTH_DISABLED", raising=False)
    admin = SimpleNamespace(state=SimpleNamespace(current_user={"username": "someone", "role": "admin"}))
    _require_admin(admin)

    configured_username_without_role = SimpleNamespace(
        state=SimpleNamespace(current_user={"username": "admin", "role": "viewer"})
    )
    with pytest.raises(HTTPException) as caught:
        _require_admin(configured_username_without_role)
    assert caught.value.status_code == 403


def test_export_upgrades_existing_ai_rows_without_mutating_source(tmp_path: Path) -> None:
    database = tmp_path / "collector.db"
    artifacts = tmp_path / "output"
    bundle = tmp_path / "ai-existing.dwti"
    artifacts.mkdir()
    _empty_current_database(database)
    _insert_legacy_ai_profile(database)

    report = export_bundle(database, artifacts, bundle)
    assert report["tables"] == 39
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        table = manifest["tables"]["ai_aggregation_profiles"]
        columns = list(table["columns"])
        rows = [
            json.loads(line)
            for line in archive.read(table["path"]).decode("utf-8").splitlines()
            if line
        ]
    assert len(rows) == 1
    exported = dict(zip(columns, rows[0]))
    assert json.loads(exported["keywords_json"]) == ["legacy-keyword"]

    source = sqlite3.connect(database)
    try:
        assert source.execute(
            "SELECT keywords_json FROM ai_aggregation_profiles WHERE id='legacy-profile'"
        ).fetchone()[0] == "[]"
    finally:
        source.close()


def test_export_failure_removes_partial_bundle_and_temporary_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "collector.db"
    artifacts = tmp_path / "output"
    bundle = tmp_path / "must-not-remain.dwti"
    artifacts.mkdir()
    _empty_current_database(database)
    _insert_legacy_ai_profile(database)

    def fail_on_first_row(*_args, **_kwargs):
        raise MigrationBundleError("injected export failure")

    monkeypatch.setattr(migration_bundle_module, "_sanitized_row", fail_on_first_row)
    with pytest.raises(MigrationBundleError, match="injected export failure"):
        export_bundle(database, artifacts, bundle)

    assert not bundle.exists()
    assert not list(tmp_path.glob(".dwti-export-*"))
    source = sqlite3.connect(database)
    try:
        assert source.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert source.execute(
            "SELECT COUNT(*) FROM ai_aggregation_profiles WHERE id='legacy-profile'"
        ).fetchone()[0] == 1
    finally:
        source.close()


@pytest.mark.skipif(os.name == "nt", reason="Unix flock and mode semantics")
def test_exclusive_file_lock_enters_conflicts_and_uses_private_permissions(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "migration.lock"
    with exclusive_file_lock(lock_path):
        assert lock_path.exists()
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
        with pytest.raises(MigrationBundleError, match="正在运行"):
            with exclusive_file_lock(lock_path):
                pytest.fail("conflicting lock unexpectedly entered")

    with exclusive_file_lock(lock_path):
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600

