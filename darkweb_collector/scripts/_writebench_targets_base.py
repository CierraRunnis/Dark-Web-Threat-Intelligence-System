from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any
import uuid

from darkweb_collector.migration_bundle import (
    _apply_postgres_read_paths,
    _apply_postgres_write_paths,
    _grant_runtime_permissions,
    _install_compatibility_functions,
    _runtime_role_from_url,
)
from darkweb_collector.postgres_backend import connect_postgres, close_postgres_pools

from _writebench_core import (
    BASELINE_VERSION,
    CANDIDATE_VERSION,
    CLONE_TABLES,
    DISPOSABLE_PATTERN,
    DISPOSABLE_PREFIX,
    WriteBenchmarkError,
    _canonical_json,
    _sha256_json,
)
from _writebench_paths import LegacyPostgresPaths, ProductionPaths


class CleanupRegistry:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._lock = Lock()

    def add(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.records.append(record)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.records]


def _driver():
    try:
        import psycopg2  # type: ignore
        from psycopg2 import sql  # type: ignore
    except ImportError as exc:
        raise WriteBenchmarkError("psycopg2 is required for PostgreSQL write benchmarking") from exc
    return psycopg2, sql


def _connect_raw(database_url: str, application_name: str):
    psycopg2, _ = _driver()
    return psycopg2.connect(database_url, application_name=application_name, connect_timeout=15)


def connection_info(database_url: str, application_name: str) -> dict[str, Any]:
    connection = _connect_raw(database_url, application_name)
    connection.set_session(readonly=True, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_user, current_setting('server_version'), "
                "current_setting('fsync'), current_setting('synchronous_commit'), "
                "current_setting('max_connections')"
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    return {
        "database": str(row[0]),
        "role": str(row[1]),
        "server_version": str(row[2]),
        "fsync": str(row[3]),
        "synchronous_commit": str(row[4]),
        "max_connections": int(row[5]),
    }


def source_schema_snapshot(database_url: str, schema_name: str) -> dict[str, Any]:
    """Return a compact, deterministic summary while holding a read-only session."""

    _, sql = _driver()
    connection = _connect_raw(database_url, "dwti-writebench-source-audit")
    connection.set_session(readonly=True, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema_name))
            )
            cursor.execute("SELECT version, checksum, source_schema_fingerprint FROM schema_migrations ORDER BY version")
            migrations = [tuple(str(value or "") for value in row) for row in cursor.fetchall()]
            tables: dict[str, dict[str, Any]] = {}
            for table in CLONE_TABLES:
                cursor.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema=%s AND table_name=%s AND column_name='id'
                    """,
                    (schema_name, table),
                )
                has_id = cursor.fetchone() is not None
                if has_id:
                    cursor.execute(
                        sql.SQL("SELECT COUNT(*), MIN(id), MAX(id) FROM {}.{}").format(
                            sql.Identifier(schema_name), sql.Identifier(table)
                        )
                    )
                    count, minimum, maximum = cursor.fetchone()
                    tables[table] = {"rows": int(count), "min_id": minimum, "max_id": maximum}
                else:
                    cursor.execute(
                        sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                            sql.Identifier(schema_name), sql.Identifier(table)
                        )
                    )
                    tables[table] = {"rows": int(cursor.fetchone()[0])}
            cursor.execute(
                "SELECT source_signature, event_count, source_revision, applied_revision, "
                "dirty_since, dirty_at FROM normalized_intelligence_cache_state WHERE id=1"
            )
            state_row = cursor.fetchone()
            state = list(state_row) if state_row is not None else None
    finally:
        connection.close()
    payload = {"schema": schema_name, "migrations": migrations, "tables": tables, "cache_state": state}
    return {"sha256": _sha256_json(payload), "summary": payload}


def list_disposable_schemas(database_url: str) -> list[str]:
    connection = _connect_raw(database_url, "dwti-writebench-leftover-audit")
    connection.set_session(readonly=True, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE %s ORDER BY schema_name",
                (DISPOSABLE_PREFIX + "%",),
            )
            return [str(row[0]) for row in cursor.fetchall()]
    finally:
        connection.close()


class SQLiteTarget:
    variant = "sqlite"
    expected_version = "sqlite"
    paths = ProductionPaths()

    def __init__(self, source_path: Path, benchmark_module) -> None:
        self.source_path = source_path
        self._delegate = benchmark_module.SQLiteWriteTarget(source_path)
        self.database_path: Path | None = None
        self.connections_opened = 0
        self._lock = Lock()
        self.temp_removed = False

    def __enter__(self) -> "SQLiteTarget":
        self._delegate.__enter__()
        self.database_path = self._delegate.database_path
        return self

    def connect(self):
        if self.database_path is None:
            raise WriteBenchmarkError("SQLite temporary target is not active")
        connection = sqlite3.connect(self.database_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        with self._lock:
            self.connections_opened += 1
        return connection

    def install_detail_failure(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(
                """
                DROP TRIGGER IF EXISTS dwti_writebench_fail_detail_child;
                CREATE TRIGGER dwti_writebench_fail_detail_child
                BEFORE INSERT ON forum_victims
                WHEN NEW.victim_name='__dwti_injected_failure__'
                BEGIN
                    SELECT RAISE(ABORT, 'injected detail child failure');
                END;
                """
            )
            connection.commit()
        finally:
            connection.close()

    def remove_detail_failure(self) -> None:
        connection = self.connect()
        try:
            connection.execute("DROP TRIGGER IF EXISTS dwti_writebench_fail_detail_child")
            connection.commit()
        finally:
            connection.close()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        path = self.database_path
        try:
            return self._delegate.__exit__(exc_type, exc_value, traceback)
        finally:
            self.temp_removed = bool(path is not None and not path.exists())
            self.database_path = None


class PostgresTarget:
    """A full-fidelity subset clone with guarded creation and cleanup."""

    def __init__(
        self,
        *,
        migration_url: str,
        runtime_url: str,
        source_schema: str,
        variant: str,
        fingerprint: str,
        registry: CleanupRegistry,
    ) -> None:
        if variant not in {"baseline", "candidate"}:
            raise WriteBenchmarkError(f"unknown PostgreSQL variant: {variant}")
        self.migration_url = migration_url
        self.runtime_url = runtime_url
        self.source_schema = source_schema
        self.variant = variant
        self.fingerprint = fingerprint
        self.registry = registry
        self.schema = DISPOSABLE_PREFIX + uuid.uuid4().hex[:20]
        self.expected_version = BASELINE_VERSION if variant == "baseline" else CANDIDATE_VERSION
        self.paths = LegacyPostgresPaths() if variant == "baseline" else ProductionPaths()
        self.owner = ""
        self.created = False
        self.dropped = False
        self.connections_opened = 0
        self._lock = Lock()
        self._record = {
            "schema": self.schema,
            "source_schema": source_schema,
            "variant": variant,
            "created": False,
            "dropped": False,
            "cleanup_error": "",
        }

    def _assert_disposable(self) -> None:
        if not DISPOSABLE_PATTERN.fullmatch(self.schema):
            raise WriteBenchmarkError(f"unsafe disposable schema name: {self.schema}")
        if self.schema == self.source_schema:
            raise WriteBenchmarkError("disposable schema equals source schema")

    def __enter__(self) -> "PostgresTarget":
        self._assert_disposable()
        _, sql = _driver()
        connection = _connect_raw(self.migration_url, "dwti-writebench-setup")
        connection.autocommit = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                self.owner = str(cursor.fetchone()[0])
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
                self.created = True
                self._record["created"] = True
                cursor.execute(
                    sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(self.schema))
                )
                for table in CLONE_TABLES:
                    cursor.execute(
                        sql.SQL("CREATE TABLE {}.{} (LIKE {}.{} INCLUDING ALL)").format(
                            sql.Identifier(self.schema), sql.Identifier(table),
                            sql.Identifier(self.source_schema), sql.Identifier(table),
                        )
                    )
                    cursor.execute(
                        sql.SQL("INSERT INTO {}.{} SELECT * FROM {}.{}").format(
                            sql.Identifier(self.schema), sql.Identifier(table),
                            sql.Identifier(self.source_schema), sql.Identifier(table),
                        )
                    )
                self._reset_identities(cursor, sql)
                self._copy_foreign_keys(cursor, sql)
                _install_compatibility_functions(connection)
                if self.variant == "candidate":
                    _apply_postgres_write_paths(connection, self.schema)
                    _apply_postgres_read_paths(connection, self.schema)
                runtime_role = _runtime_role_from_url(self.runtime_url)
                _grant_runtime_permissions(connection, self.schema, runtime_role)
                for table in CLONE_TABLES:
                    cursor.execute(
                        sql.SQL("ANALYZE {}.{}").format(sql.Identifier(self.schema), sql.Identifier(table))
                    )
                cursor.execute("SHOW fsync")
                if str(cursor.fetchone()[0]).lower() != "on":
                    raise WriteBenchmarkError("PostgreSQL fsync must remain on")
                cursor.execute("SHOW synchronous_commit")
                if str(cursor.fetchone()[0]).lower() != "on":
                    raise WriteBenchmarkError("PostgreSQL synchronous_commit must remain on")
            connection.commit()
        except Exception:
            connection.rollback()
            if self.created:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
                    )
                self.created = False
            raise
        finally:
            connection.close()
        self.registry.add(self._record)
        return self

    def _reset_identities(self, cursor, sql) -> None:
        for table in CLONE_TABLES:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema=%s AND table_name=%s AND is_identity='YES'
                """,
                (self.schema, table),
            )
            for (column,) in cursor.fetchall():
                cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", (f'{self.schema}."{table}"', column))
                sequence = cursor.fetchone()[0]
                cursor.execute(
                    sql.SQL("SELECT MAX({}) FROM {}.{}").format(
                        sql.Identifier(column), sql.Identifier(self.schema), sql.Identifier(table)
                    )
                )
                maximum = cursor.fetchone()[0]
                if sequence:
                    cursor.execute(
                        "SELECT setval(%s::regclass, %s, %s)",
                        (sequence, int(maximum or 1), maximum is not None),
                    )

    def _copy_foreign_keys(self, cursor, sql) -> None:
        cursor.execute(
            """
            SELECT source_table.relname, constraint_row.conname,
                   target_schema.nspname, target_table.relname,
                   pg_get_constraintdef(constraint_row.oid, true)
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS source_table ON source_table.oid=constraint_row.conrelid
            JOIN pg_namespace AS source_schema ON source_schema.oid=source_table.relnamespace
            JOIN pg_class AS target_table ON target_table.oid=constraint_row.confrelid
            JOIN pg_namespace AS target_schema ON target_schema.oid=target_table.relnamespace
            WHERE constraint_row.contype='f' AND source_schema.nspname=%s
            ORDER BY source_table.relname, constraint_row.conname
            """,
            (self.source_schema,),
        )
        selected = set(CLONE_TABLES)
        for table, name, target_schema, target_table, definition in cursor.fetchall():
            if table not in selected or target_schema != self.source_schema or target_table not in selected:
                continue
            rewritten = str(definition).replace(f'"{self.source_schema}".', "").replace(
                f"{self.source_schema}.", ""
            )
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} ADD CONSTRAINT {} {}").format(
                    sql.Identifier(self.schema), sql.Identifier(table), sql.Identifier(name), sql.SQL(rewritten)
                )
            )

    def connect(self):
        connection = connect_postgres(
            self.runtime_url,
            schema=self.schema,
            expected_fingerprint=self.fingerprint,
            expected_version=self.expected_version,
            read_only=False,
        )
        with self._lock:
            self.connections_opened += 1
        return connection

    def install_detail_failure(self) -> None:
        self._detail_constraint("ADD CONSTRAINT dwti_writebench_fail_detail_child "
                                "CHECK (victim_name <> '__dwti_injected_failure__')")

    def remove_detail_failure(self) -> None:
        self._detail_constraint("DROP CONSTRAINT IF EXISTS dwti_writebench_fail_detail_child")

    def _detail_constraint(self, operation: str) -> None:
        close_postgres_pools()
        _, sql = _driver()
        connection = _connect_raw(self.migration_url, "dwti-writebench-contract-ddl")
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.forum_victims ").format(sql.Identifier(self.schema))
                    + sql.SQL(operation)
                )
        finally:
            connection.close()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        close_postgres_pools()
        if not self.created:
            return False
        cleanup_error: Exception | None = None
        connection = None
        try:
            self._assert_disposable()
            _, sql = _driver()
            connection = _connect_raw(self.migration_url, "dwti-writebench-cleanup")
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname=%s",
                    (self.schema,),
                )
                row = cursor.fetchone()
                if row is None or str(row[0]) != self.owner:
                    raise WriteBenchmarkError("disposable schema owner changed; refusing cleanup")
                cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
            self.dropped = True
            self._record["dropped"] = True
        except Exception as exc:
            cleanup_error = exc
            self._record["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if connection is not None:
                connection.close()
        self.created = False
        if cleanup_error is not None and exc_type is None:
            raise WriteBenchmarkError(f"failed to clean disposable schema {self.schema}: {cleanup_error}")
        return False

