from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
import pytest
import darkweb_collector.migration_bundle as migration_bundle_module

from darkweb_collector import api_app, migration_api
from darkweb_collector.migration_bundle import (
    _apply_performance_indexes,
    MigrationBundleError,
    PERFORMANCE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    WRITE_SCHEMA_VERSION,
    SCHEMA_VERSIONS,
    _apply_postgres_write_paths,
    _apply_postgres_read_paths,
    _grant_runtime_permissions,
    _install_compatibility_functions,
    validate_postgres_schema,
)


ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = ROOT / "scripts" / "start_all_services_wsl.sh"
SETUP_SCRIPT = ROOT / "scripts" / "setup_postgresql_linux.sh"
EXPORT_SCRIPT = ROOT / "scripts" / "export_migration_bundle.py"


def _load_export_module():
    spec = importlib.util.spec_from_file_location("dwti_export_cli_test", EXPORT_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _health_payload(backend: str = "sqlite", status: str = "ok") -> dict:
    versions = (
        [
            "0001_baseline",
            "0002_sqlite_compat",
            "0003_local_postgres_compat",
            "0004_performance_indexes",
            "0005_postgres_write_paths",
            "0006_postgres_read_paths",
        ]
        if backend == "postgresql"
        else []
    )
    return {
        "status": status,
        "backend": backend,
        "database": "collector.db" if backend == "sqlite" else "darkweb_intelligence",
        "schema": "main" if backend == "sqlite" else "dwti_fixture",
        "schemaVersions": versions,
        "missingTables": [] if status == "ok" else ["crawl_jobs"],
        "missingSchemaVersions": [],
    }


def test_migration_router_is_registered_and_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = {route.path for route in api_app.app.routes}
    assert {
        "/api/migrations/config",
        "/api/migrations",
        "/api/migrations/upload",
        "/api/migrations/{job_id}",
        "/api/migrations/{job_id}/performance",
        "/api/migrations/{job_id}/activate",
    }.issubset(paths)

    monkeypatch.setenv("DARKWEB_API_AUTH_DISABLED", "0")
    viewer = SimpleNamespace(state=SimpleNamespace(current_user={"role": "viewer"}))
    with pytest.raises(HTTPException) as caught:
        migration_api.migration_config(viewer)
    assert caught.value.status_code == 403


@pytest.mark.parametrize(
    ("backend", "schema", "version"),
    [
        ("sqlite", "main", ""),
        ("postgresql", "dwti_fixture", "0006_postgres_read_paths"),
    ],
)
def test_health_exposes_controller_database_contract(
    backend: str,
    schema: str,
    version: str,
) -> None:
    with patch.object(api_app, "database_health_payload", return_value=_health_payload(backend)):
        payload = api_app.health()
    assert payload["status"] == "ok"
    assert payload["database_engine"] == backend
    assert payload["database_schema"] == schema
    assert payload["schema_version"] == version
    assert payload["database_ready"] is True
    assert payload["database"]["healthy"] is True


def test_health_returns_503_without_leaking_database_exception() -> None:
    secret = "postgresql://private_user:private_password@internal-host/database"
    with patch.object(api_app, "database_health_payload", side_effect=RuntimeError(secret)):
        with pytest.raises(HTTPException) as caught:
            api_app.health()
    assert caught.value.status_code == 503
    rendered = json.dumps(caught.value.detail, ensure_ascii=False)
    assert "RuntimeError" in rendered
    assert "private_password" not in rendered
    assert "internal-host" not in rendered

    with patch.object(
        api_app,
        "database_health_payload",
        return_value=_health_payload("postgresql", status="error"),
    ):
        with pytest.raises(HTTPException) as not_ready:
            api_app.health()
    assert not_ready.value.status_code == 503
    assert not_ready.value.detail["database"]["database_ready"] is False


def test_shutdown_always_closes_postgres_pools() -> None:
    with patch.object(api_app, "close_all_remote_browser_sessions") as close_browser, patch.object(
        api_app, "close_postgres_pools"
    ) as close_pools:
        api_app.close_runtime_resources_on_shutdown()
    close_browser.assert_called_once_with()
    close_pools.assert_called_once_with()

    with patch.object(
        api_app,
        "close_all_remote_browser_sessions",
        side_effect=RuntimeError("browser shutdown failed"),
    ), patch.object(api_app, "close_postgres_pools") as close_pools:
        with pytest.raises(RuntimeError):
            api_app.close_runtime_resources_on_shutdown()
    close_pools.assert_called_once_with()


def test_compatibility_sql_is_complete_immutable_and_index_aligned() -> None:
    statements: list[str] = []

    class Cursor:
        def execute(self, statement, parameters=None):
            statements.append(str(statement))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    connection = SimpleNamespace(cursor=lambda: Cursor())
    _install_compatibility_functions(connection)
    ddl = "\n".join(statements)
    assert "LANGUAGE plpgsql IMMUTABLE AS $dwti$" in ddl
    assert "CREATE OR REPLACE FUNCTION datetime(value TEXT)" in ddl
    assert "RETURN normalized::DATE::TIMESTAMP WITHOUT TIME ZONE" in ddl
    assert "TIMESTAMPTZ AT TIME ZONE 'UTC'" in ddl
    assert "DATE_TRUNC('second', REPLACE(normalized, 'T', ' ')" in ddl
    assert "DATE_TRUNC('second', normalized::TIMESTAMPTZ AT TIME ZONE 'UTC')" in ddl
    assert "DATE_TRUNC('second', LOCALTIMESTAMP)" in ddl
    assert "LANGUAGE plpgsql STABLE AS $dwti_modifier$" in ddl
    indexes = inspect.getsource(_apply_performance_indexes)
    assert "event_type, datetime(COALESCE(NULLIF(disclosure_time, ''), updated_at))" in indexes
    assert "UPPER(cve_id), datetime(COALESCE(NULLIF(disclosure_time, ''), last_seen_at))" in indexes
    canary = inspect.getsource(validate_postgres_schema)
    assert "INSERT INTO collection_runs" in canary
    assert "INSERT INTO ai_aggregation_schedule_claims" in canary
    assert "RETURNING id" in canary
    assert "SELECT COUNT(*) FROM collection_runs WHERE source_url=%s" in canary


def test_export_cli_detects_actual_wsl_service_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_export_module()
    commands = [
        "python scripts/serve_api.py",
        "python -m celery -A darkweb_collector.celery_app:app worker -Q seed_http",
        "python scripts/crawl.py worker --queue browser_render",
        "python scripts/crawl.py enqueue-due",
        "python scripts/crawl.py sync-public-vulns --limit 300",
        "python scripts/crawl.py normalizer --poll-seconds 5",
    ]
    monkeypatch.setattr(
        module,
        "_linux_processes",
        lambda: iter((9000 + index, command) for index, command in enumerate(commands)),
    )
    found = module.running_writer_services()
    assert len(found) == len(commands)
    assert all(item["markers"] for item in found)


def test_wsl_scripts_parse_and_contain_postgres_runtime_guards() -> None:
    subprocess.run(["bash", "-n", str(START_SCRIPT)], check=True)
    subprocess.run(["bash", "-n", str(SETUP_SCRIPT)], check=True)
    text = START_SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "DARKWEB_ACTIVE_RELEASE_FILE",
        "DARKWEB_MIGRATION_TARGET_DATABASE_URL",
        "DARKWEB_MIGRATION_RUNTIME_DATABASE_URL",
        "DARKWEB_POSTGRES_POOL_MIN",
        "DARKWEB_POSTGRES_POOL_MAX",
        "DARKWEB_POSTGRES_CONNECT_TIMEOUT_SECONDS",
        "active database is PostgreSQL; skipped SQLite source synchronization",
        "ensure_postgresql_target",
        "psycopg2",
    ):
        assert marker in text
    setup = SETUP_SCRIPT.read_text(encoding="utf-8")
    assert "SHOW server_version_num" in setup
    assert "version_num >= 160000 && version_num < 170000" in setup


def test_active_postgres_release_exports_runtime_environment_without_sqlite(
    tmp_path: Path,
) -> None:
    script_dir = tmp_path / "darkweb_collector" / "scripts"
    script_dir.mkdir(parents=True)
    (tmp_path / "threat-intelligence-dashboard").mkdir()
    helper = script_dir / "start-helpers.sh"
    source = START_SCRIPT.read_text(encoding="utf-8")
    helper.write_text(source.rsplit("\nmain ", 1)[0] + "\n", encoding="utf-8")
    active = tmp_path / "active-release.json"
    active.write_text(
        json.dumps(
            {
                "format": 1,
                "database_engine": "postgresql",
                "database_url": "postgresql://runtime:secret@127.0.0.1/db",
                "database_schema": "dwti_fixture",
                "schema_fingerprint": "abc123",
                "schema_version": "0006_postgres_read_paths",
                "output_root": str(tmp_path / "artifacts"),
            }
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "DARKWEB_ACTIVE_RELEASE_FILE": str(active),
        "DARKWEB_POSTGRESQL_AUTO_INSTALL": "0",
        "DARKWEB_MIGRATION_TARGET_DATABASE_URL": "postgresql://migrator:x@127.0.0.1/db",
        "DARKWEB_MIGRATION_RUNTIME_DATABASE_URL": "postgresql://runtime:y@127.0.0.1/db",
    }
    completed = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; load_active_release; printf "%s\n" "$ACTIVE_DATABASE_ENGINE" '
            '"$ACTIVE_DATABASE_SCHEMA"; build_env_exports',
            "bash",
            str(helper),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "postgresql\ndwti_fixture\n" in completed.stdout
    assert "DARKWEB_ACTIVE_RELEASE_FILE=" in completed.stdout
    assert "DARKWEB_MIGRATION_TARGET_DATABASE_URL=" in completed.stdout
    assert "DARKWEB_POSTGRES_POOL_MAX=" in completed.stdout
    assert "DARKWEB_COLLECTOR_OUTPUT_ROOT=" in completed.stdout
    assert "DARKWEB_COLLECTOR_DB_PATH=" not in completed.stdout



def test_performance_index_count_query_parameterizes_like_pattern() -> None:
    calls: list[tuple[object, object]] = []

    class Cursor:
        def __init__(self):
            self.last_statement = ""

        def execute(self, statement, parameters=None):
            self.last_statement = str(statement)
            calls.append((statement, parameters))

        def fetchone(self):
            if "FROM pg_extension" in self.last_statement:
                return ("public",)
            return (17,)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    result = _apply_performance_indexes(SimpleNamespace(cursor=lambda: Cursor()), "dwti_fixture")
    query, parameters = next(
        (statement, parameters)
        for statement, parameters in calls
        if "FROM pg_indexes" in str(statement)
    )
    assert query == (
        "SELECT COUNT(*) FROM pg_indexes "
        "WHERE schemaname=%s AND indexname LIKE %s"
    )
    assert parameters == ("dwti_fixture", "idx_pgperf_%")
    assert result["performance_indexes"] == 17
    assert result["extensions"] == ["public.pg_trgm"]
    assert result["version"] == PERFORMANCE_SCHEMA_VERSION
    rendered = "\n".join(str(statement) for statement, _parameters in calls)
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public" in rendered
    assert "idx_pgperf_events_search_trgm" in rendered
    assert "public.gin_trgm_ops" in rendered
    extension_sql = next(
        str(statement)
        for statement, _parameters in calls
        if str(statement).startswith("CREATE EXTENSION")
    )
    index_sql = [
        str(statement)
        for statement, _parameters in calls
        if str(statement).startswith("CREATE INDEX")
    ]
    version_parameters = next(
        parameters for statement, parameters in calls if "INSERT INTO schema_migrations" in str(statement)
    )
    assert version_parameters[0] == PERFORMANCE_SCHEMA_VERSION
    assert "COALESCE(detail_text, '')" in rendered


def test_postgres_write_paths_are_versioned_idempotent_and_business_preserving() -> None:
    calls: list[tuple[object, object]] = []

    class Cursor:
        def __init__(self):
            self.one = None

        def execute(self, statement, parameters=None):
            rendered = str(statement)
            calls.append((statement, parameters))
            if "GROUP BY site_name, source_url, name" in rendered:
                self.one = None
            elif parameters == ("dwti_fixture", "idx_pgwrite_%"):
                self.one = (2,)
            elif parameters == ("dwti_fixture", "idx_pgperf_%"):
                self.one = (19,)
            else:
                self.one = None

        def fetchone(self):
            return self.one

        def fetchall(self):
            return [
                ("legacy_victims_unique", None),
                ("legacy_victims_constraint_index", "legacy_victims_constraint"),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    result = _apply_postgres_write_paths(
        SimpleNamespace(cursor=lambda: Cursor()),
        "dwti_fixture",
    )

    assert PERFORMANCE_SCHEMA_VERSION == "0004_performance_indexes"
    assert WRITE_SCHEMA_VERSION == "0005_postgres_write_paths"
    assert SCHEMA_VERSION == "0006_postgres_read_paths"
    assert SCHEMA_VERSIONS[-3:] == (PERFORMANCE_SCHEMA_VERSION, WRITE_SCHEMA_VERSION, SCHEMA_VERSION)
    assert result == {
        "version": WRITE_SCHEMA_VERSION,
        "write_path_indexes": 2,
        "performance_indexes": 19,
        "victim_legacy_unique_indexes_removed": 2,
        "analyzed": True,
    }

    rendered = "\n".join(str(statement) for statement, _parameters in calls)
    assert "LOCK TABLE" in rendered
    assert "GROUP BY site_name, source_url, name, COALESCE(domain, '')" in rendered
    assert "idx_pgwrite_victims_business_key" in rendered
    assert "legacy_victims_unique" in rendered
    assert "legacy_victims_constraint" in rendered
    assert "idx_pgwrite_forum_victims_detail" in rendered
    write_paths_source = inspect.getsource(_apply_postgres_write_paths)
    drop_new = "DROP INDEX IF EXISTS {}.idx_pgwrite_jobs_active_site_type_time"
    restore_old = "CREATE INDEX IF NOT EXISTS idx_pgperf_jobs_status_queue"
    assert drop_new in write_paths_source
    assert restore_old in write_paths_source
    assert write_paths_source.index(drop_new) < write_paths_source.index(restore_old)
    assert "DROP INDEX IF EXISTS {}.idx_pgperf_jobs_status_queue" not in write_paths_source
    assert (
        "CREATE INDEX IF NOT EXISTS idx_pgwrite_jobs_active_site_type_time"
        not in write_paths_source
    )
    assert "WHERE status IN ('queued', 'running')" in write_paths_source
    assert "CREATE OR REPLACE FUNCTION" in rendered
    assert "dwti_mark_normalized_dirty" in rendered
    assert "dwti_upsert_victim" in rendered
    assert "dwti_upsert_forum_topic" in rendered
    assert "dwti_upsert_forum_detail" in rendered
    assert "SECURITY INVOKER" in rendered
    assert "SET search_path = pg_catalog" in rendered
    assert "WITH ORDINALITY" in rendered
    assert "REVOKE ALL ON ALL FUNCTIONS" in rendered
    assert "ON CONFLICT(version) DO UPDATE" in rendered

    migration_parameters = next(
        parameters
        for statement, parameters in calls
        if "INSERT INTO" in str(statement) and "schema_migrations" in str(statement)
    )
    expected_signature = "\n".join((
        "dwti_mark_normalized_dirty(text)-security-invoker-v1",
        "victims(site_name,source_url,name,coalesce(domain,''),status)-unique-v1",
        "forum_victims(forum_detail_id)-index-v1",
        "drop-rejected-idx_pgwrite_jobs_active_site_type_time-v1",
        "restore-idx_pgperf_jobs_status_queue-where-queued-running-v1",
        "dwti_upsert_victim(bigint,text...)-v1",
        "dwti_upsert_forum_topic(text...)-v1",
        "dwti_upsert_forum_detail(text...,victims_json,text)-v1",
    ))
    assert migration_parameters == (
        WRITE_SCHEMA_VERSION, hashlib.sha256(expected_signature.encode("utf-8")).hexdigest(),
    )

    grant_source = inspect.getsource(_grant_runtime_permissions)
    assert "REVOKE ALL ON ALL FUNCTIONS" in grant_source
    assert "GRANT EXECUTE ON ALL FUNCTIONS" in grant_source
    finalize_source = inspect.getsource(migration_bundle_module._finalize_postgres_release)
    assert finalize_source.index("_apply_performance_indexes") < finalize_source.index(
        "_apply_postgres_write_paths"
    )
    assert finalize_source.index("_apply_postgres_write_paths") < finalize_source.index(
        "_apply_postgres_read_paths"
    )
    assert finalize_source.index("_apply_postgres_read_paths") < finalize_source.index(
        "_grant_runtime_permissions"
    )



def test_postgres_read_paths_are_versioned_idempotent_and_exact() -> None:
    calls: list[tuple[object, object]] = []

    class Cursor:
        def __init__(self):
            self.one = None

        def execute(self, statement, parameters=None):
            rendered = str(statement)
            calls.append((statement, parameters))
            if "SELECT indexdef" in rendered:
                self.one = (
                    "CREATE INDEX idx_pgread_jobs_recency_expr "
                    "ON dwti_fixture.crawl_jobs USING btree "
                    "(COALESCE(finished_at, started_at, enqueued_at) DESC)",
                )
            elif parameters == ("dwti_fixture", "idx_pgread_%"):
                self.one = (1,)
            else:
                self.one = None

        def fetchone(self):
            return self.one

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    connection = SimpleNamespace(cursor=lambda: Cursor())
    first = _apply_postgres_read_paths(connection, "dwti_fixture")
    second = _apply_postgres_read_paths(connection, "dwti_fixture")

    expected = {
        "version": SCHEMA_VERSION,
        "read_path_indexes": 1,
        "crawl_jobs_recency_index": "idx_pgread_jobs_recency_expr",
        "analyzed": True,
    }
    assert first == second == expected
    rendered = "\n".join(str(statement) for statement, _parameters in calls)
    assert rendered.count("SET LOCAL search_path TO") == 2
    assert rendered.count("CREATE OR REPLACE FUNCTION datetime(value TEXT)") == 2
    assert rendered.count("CREATE INDEX IF NOT EXISTS idx_pgread_jobs_recency_expr") == 2
    assert "((COALESCE(finished_at, started_at, enqueued_at)) DESC)" in rendered
    assert "INCLUDE" not in rendered.upper()
    assert rendered.count("ANALYZE") == 2
    migration_parameters = [
        parameters
        for statement, parameters in calls
        if "schema_migrations" in str(statement)
    ]
    expected_signature = "\n".join(
        (
            "sqlite-datetime-second-precision-v1",
            "idx_pgread_jobs_recency_expr-btree-coalesce-finished-started-enqueued-desc-v1",
            "analyze-crawl_jobs-v1",
        )
    )
    assert migration_parameters == [
        (
            SCHEMA_VERSION,
            hashlib.sha256(expected_signature.encode("utf-8")).hexdigest(),
        ),
        (
            SCHEMA_VERSION,
            hashlib.sha256(expected_signature.encode("utf-8")).hexdigest(),
        ),
    ]

def test_postgres_write_paths_reject_duplicate_normalized_victim_keys_before_ddl() -> None:
    calls: list[str] = []

    class Cursor:
        def execute(self, statement, parameters=None):
            calls.append(str(statement))

        def fetchone(self):
            return (1,)

        def fetchall(self):
            raise AssertionError("legacy indexes must not be inspected after failed preflight")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    with pytest.raises(MigrationBundleError, match="duplicate business keys"):
        _apply_postgres_write_paths(
            SimpleNamespace(cursor=lambda: Cursor()),
            "dwti_fixture",
        )

    rendered = "\n".join(calls)
    assert "GROUP BY site_name, source_url, name, COALESCE(domain, '')" in rendered
    assert "CREATE UNIQUE INDEX" not in rendered
    assert "schema_migrations" not in rendered




def test_post_import_failure_invokes_schema_and_release_cleanup(tmp_path: Path) -> None:
    report = {
        "job_id": "a" * 32,
        "database_schema": "dwti_fixture",
        "output_root": str(tmp_path / "release" / "artifacts"),
        "schema_fingerprint": "fingerprint",
    }

    @contextmanager
    def unlocked(_database_url):
        yield

    with patch.object(
        migration_bundle_module,
        "migration_operation_lock",
        unlocked,
    ), patch.object(
        migration_bundle_module,
        "_import_bundle_core",
        return_value=report,
    ), patch.object(
        migration_bundle_module,
        "_finalize_postgres_release",
        side_effect=IndexError("injected finalize failure"),
    ), patch.object(
        migration_bundle_module,
        "_cleanup_import_release",
    ) as cleanup:
        with pytest.raises(IndexError, match="injected finalize failure"):
            migration_bundle_module.import_bundle(
                tmp_path / "unused.dwti",
                "postgresql://migrator:x@127.0.0.1/db",
                "a" * 32,
                runtime_database_url="postgresql://runtime:y@127.0.0.1/db",
            )

    cleanup.assert_called_once_with(
        "postgresql://migrator:x@127.0.0.1/db",
        report,
    )

