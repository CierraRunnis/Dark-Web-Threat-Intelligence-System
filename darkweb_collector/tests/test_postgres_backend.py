from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import postgres_backend, runtime
from darkweb_collector.db import (
    SOURCE_SQLITE_TABLES,
    TARGET_POSTGRES_TABLES,
    connect,
    connect_readonly,
    database_health_payload,
    execute_insert_get_id,
    sql_case_insensitive_like,
    sql_case_insensitive_order,
    sql_scalar_min,
)
from darkweb_collector.postgres_backend import (
    CompatRow,
    PostgresConnection,
    _PoolEntry,
    connect_postgres,
    translate_sql,
)


class FakeCursor:
    def __init__(self, raw):
        self.raw = raw
        self.description = []
        self.rows = []
        self.rowcount = 0
        self.closed = False

    def execute(self, sql, parameters=()):
        sql_text = str(sql)
        self.raw.executed.append((sql_text, tuple(parameters or ())))
        if not self.raw.autocommit:
            self.raw.transaction_status = postgres_backend._TX_INTRANS
        if "FROM schema_migrations" in sql_text:
            self.description = [
                ("version",), ("source_schema_fingerprint",),
            ]
            self.rows = list(self.raw.migrations)
            self.rowcount = len(self.rows)
        elif "information_schema.columns" in sql_text:
            self.description = [("table_name",)]
            self.rows = [("items",)]
            self.rowcount = 1
        elif "current_schema()" in sql_text:
            self.description = [("current_schema",)]
            self.rows = [("dwti_fixture",)]
            self.rowcount = 1
        elif "RETURNING id" in sql_text:
            self.description = [("id",)]
            self.rows = [(17,)]
            self.rowcount = 1
        else:
            self.description = [("id",), ("name",)]
            self.rows = [(1, "alpha"), (2, "beta")]
            self.rowcount = 2
        return self

    def executemany(self, sql, parameters):
        self.raw.executed.append((str(sql), list(parameters)))
        if not self.raw.autocommit:
            self.raw.transaction_status = postgres_backend._TX_INTRANS
        self.rowcount = len(parameters)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchmany(self, size=1):
        result, self.rows = self.rows[:size], self.rows[size:]
        return result

    def fetchall(self):
        result, self.rows = self.rows, []
        return result

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeRawConnection:
    def __init__(self):
        self.executed = []
        self.closed = False
        self.autocommit = False
        self.sessions = []
        self.commits = 0
        self.rollbacks = 0
        self.migrations = [
            ("0001_baseline", "fixture"),
            ("0005_postgres_write_paths", "fixture"),
            ("0006_postgres_read_paths", "fixture"),
        ]
        self.transaction_status = postgres_backend._TX_IDLE

    def cursor(self):
        return FakeCursor(self)

    def get_transaction_status(self):
        return self.transaction_status

    def set_session(self, **kwargs):
        self.sessions.append(kwargs)

    def commit(self):
        self.commits += 1
        self.transaction_status = postgres_backend._TX_IDLE

    def rollback(self):
        self.rollbacks += 1
        self.transaction_status = postgres_backend._TX_IDLE

    def close(self):
        self.closed = True
        self.transaction_status = postgres_backend._TX_UNKNOWN


class FakePool:
    def __init__(self, raw=None):
        self.raw = raw or FakeRawConnection()
        self.returned = []
        self.closed = False

    def getconn(self):
        return self.raw

    def putconn(self, connection, close=False):
        self.returned.append((connection, close))

    def closeall(self):
        self.closed = True


class PostgreSQLCompatibilityTests(unittest.TestCase):
    def test_qmarks_ignore_literals_identifiers_and_comments(self) -> None:
        source = "SELECT '?' AS value, \"?\" AS name FROM t WHERE id = ? -- ?\nAND x = ?"
        translated = translate_sql(source)
        self.assertIn("SELECT '?' AS value", translated)
        self.assertIn('\"?\" AS name', translated)
        self.assertIn("id = %s -- ?", translated)
        self.assertIn("AND x = %s", translated)

    def test_literal_percent_signs_are_escaped_for_psycopg2(self) -> None:
        source = (
            "SELECT '%telegram%' AS pattern, '100%' AS label, score % 10 "
            "FROM items WHERE id = ? -- 50%"
        )
        translated = translate_sql(source)
        self.assertIn("'%%telegram%%'", translated)
        self.assertIn("'100%%'", translated)
        self.assertIn("score %% 10", translated)
        self.assertIn("id = %s", translated)
        self.assertIn("-- 50%%", translated)
        rendered = translated % (7,)
        self.assertIn("'%telegram%'", rendered)
        self.assertIn("score % 10", rendered)
        self.assertEqual(
            "SELECT '%%s' AS literal, %s AS parameter",
            translate_sql("SELECT '%s' AS literal, ? AS parameter"),
        )

    def test_insert_ignore_and_compat_row(self) -> None:
        translated = translate_sql("INSERT OR IGNORE INTO items(name) VALUES (?)")
        self.assertEqual(
            "INSERT INTO items(name) VALUES (%s) ON CONFLICT DO NOTHING",
            translated,
        )
        row = CompatRow(("id", "score"), (7, 3.5))
        self.assertEqual(7, row[0])
        self.assertEqual(3.5, row["score"])
        self.assertEqual({"id": 7, "score": 3.5}, dict(row))

    def test_cursor_iteration_lastrowid_and_pool_return(self) -> None:
        raw = FakeRawConnection()
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset({"items"}),
            read_only=False,
        )
        cursor = connection.execute(
            "INSERT INTO items(name) VALUES (?)", ("a",), return_identity=True
        )
        self.assertEqual(17, cursor.lastrowid)
        self.assertIn("RETURNING id", raw.executed[-1][0])

        rows = list(connection.execute("SELECT id, name FROM items"))
        self.assertEqual([1, 2], [row["id"] for row in rows])
        connection.close()
        self.assertEqual([(raw, False)], pool.returned)

    def test_execute_insert_get_id_is_explicit_only_on_postgres(self) -> None:
        import sqlite3

        sqlite_connection = sqlite3.connect(":memory:")
        try:
            sqlite_connection.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
            )
            self.assertEqual(
                1,
                execute_insert_get_id(
                    sqlite_connection,
                    "INSERT INTO items(name) VALUES (?)",
                    ("sqlite",),
                ),
            )
        finally:
            sqlite_connection.close()

        raw = FakeRawConnection()
        pool = FakePool(raw)
        postgres_connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset({"items"}),
            read_only=False,
        )
        self.assertEqual(
            17,
            execute_insert_get_id(
                postgres_connection,
                "INSERT INTO items(name) VALUES (?)",
                ("postgresql",),
            ),
        )
        self.assertIn("RETURNING id", raw.executed[-1][0])
        postgres_connection.close()

    def test_connect_sets_readonly_after_validation(self) -> None:
        raw = FakeRawConnection()
        entry = _PoolEntry(FakePool(raw))
        session_calls = []

        def set_session(_raw, schema, *, read_only):
            session_calls.append((schema, read_only))

        with patch.object(postgres_backend, "_pool_entry", return_value=entry), patch.object(
            postgres_backend, "_set_session", side_effect=set_session
        ), patch.object(
            postgres_backend, "_validate_release", return_value=frozenset({"items"})
        ):
            connection = connect_postgres(
                "postgresql://runtime@localhost/darkweb",
                schema="dwti_fixture",
                expected_fingerprint="fixture",
                read_only=True,
            )
        self.assertTrue(connection.read_only)
        self.assertEqual(
            [("dwti_fixture", False), ("dwti_fixture", True)],
            session_calls,
        )
        connection.close()

    def test_first_validation_is_cached_across_write_read_write(self) -> None:
        raw = FakeRawConnection()
        entry = _PoolEntry(FakePool(raw))
        session_calls = []

        def set_session(_raw, schema, *, read_only):
            session_calls.append((schema, read_only))

        with patch.object(
            postgres_backend, "_pool_entry", return_value=entry
        ), patch.object(postgres_backend, "_set_session", side_effect=set_session):
            for read_only in (False, True, False):
                connection = connect_postgres(
                    "postgresql://runtime@localhost/darkweb",
                    schema="dwti_fixture",
                    expected_fingerprint="fixture",
                    read_only=read_only,
                )
                self.assertEqual(frozenset({"items"}), connection.identity_tables)
                connection.close()

        self.assertEqual(
            [
                ("dwti_fixture", False),
                ("dwti_fixture", False),
                ("dwti_fixture", False),
                ("dwti_fixture", True),
                ("dwti_fixture", False),
                ("dwti_fixture", False),
            ],
            session_calls,
        )
        migration_queries = [
            sql for sql, _ in raw.executed if "FROM schema_migrations" in sql
        ]
        identity_queries = [
            sql for sql, _ in raw.executed if "information_schema.columns" in sql
        ]
        self.assertEqual(1, len(migration_queries))
        self.assertEqual(1, len(identity_queries))
        self.assertEqual(1, raw.rollbacks)

    def test_two_schemas_keep_session_and_identity_metadata_separate(self) -> None:
        raw = FakeRawConnection()
        entry = _PoolEntry(FakePool(raw))
        sessions = []

        def set_session(_raw, schema, *, read_only):
            sessions.append((schema, read_only))

        def validate(_entry, _raw, *, schema, **_kwargs):
            return frozenset({f"identity_{schema}"})

        with patch.object(
            postgres_backend, "_pool_entry", return_value=entry
        ), patch.object(
            postgres_backend, "_set_session", side_effect=set_session
        ), patch.object(
            postgres_backend, "_validate_release", side_effect=validate
        ):
            first = connect_postgres(
                "postgresql://runtime@localhost/darkweb",
                schema="dwti_first",
            )
            first.close()
            second = connect_postgres(
                "postgresql://runtime@localhost/darkweb",
                schema="dwti_second",
                read_only=True,
            )
            second.close()

        self.assertEqual(
            [
                ("dwti_first", False),
                ("dwti_first", False),
                ("dwti_second", False),
                ("dwti_second", True),
            ],
            sessions,
        )
        self.assertEqual(frozenset({"identity_dwti_first"}), first.identity_tables)
        self.assertEqual(frozenset({"identity_dwti_second"}), second.identity_tables)

    def test_identity_returning_defaults_to_auto_with_explicit_overrides(self) -> None:
        raw = FakeRawConnection()
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset({"items"}),
            read_only=False,
        )

        automatic = connection.execute(
            "INSERT INTO items(name) VALUES (?)",
            ("automatic-id",),
        )
        self.assertEqual(17, automatic.lastrowid)
        self.assertIn("RETURNING id", raw.executed[-1][0])

        no_identity = connection.execute(
            "INSERT INTO items(name) VALUES (?)",
            ("without-id",),
            return_identity=False,
        )
        self.assertIsNone(no_identity.lastrowid)
        self.assertNotIn("RETURNING id", raw.executed[-1][0])

        identity = connection.execute(
            "INSERT INTO items(name) VALUES (?)",
            ("with-id",),
            return_identity=True,
        )
        self.assertEqual(17, identity.lastrowid)
        self.assertIn("RETURNING id", raw.executed[-1][0])

        non_identity = connection.execute(
            "INSERT INTO audit_log(message) VALUES (?)",
            ("default-no-id",),
        )
        self.assertIsNone(non_identity.lastrowid)
        self.assertNotIn("RETURNING id", raw.executed[-1][0])

        with self.assertRaises(postgres_backend.PostgreSQLBackendError):
            connection.execute(
                "INSERT INTO audit_log(message) VALUES (?)",
                ("not-an-identity",),
                return_identity=True,
            )
        connection.close()

    def test_execute_values_is_explicit_and_does_not_change_executemany(self) -> None:
        raw = FakeRawConnection()
        connection = PostgresConnection(
            raw,
            _PoolEntry(FakePool(raw)),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        rows = ((1, "alpha"), (2, "beta"))

        with patch.object(postgres_backend, "_driver_execute_values") as batch:
            cursor = connection.execute_values(
                "INSERT INTO items(id, name) VALUES ?",
                rows,
                template="(?, ?)",
                page_size=2,
            )
        self.assertIsNone(cursor.lastrowid)
        batch.assert_called_once_with(
            cursor._cursor,
            "INSERT INTO items(id, name) VALUES %s",
            rows,
            template="(%s, %s)",
            page_size=2,
        )

        connection.executemany(
            "INSERT INTO items(id, name) VALUES (?, ?)", rows
        )
        self.assertEqual(list(rows), raw.executed[-1][1])
        with self.assertRaises(postgres_backend.PostgreSQLBackendError):
            connection.execute_values(
                "INSERT INTO items(id, name) VALUES ?", rows, page_size=0
            )
        connection.close()

    def test_set_session_only_rolls_back_dirty_connections(self) -> None:
        idle = FakeRawConnection()
        postgres_backend._set_session(idle, "", read_only=True)
        self.assertEqual(0, idle.rollbacks)
        self.assertEqual(
            [{"readonly": True, "autocommit": False}], idle.sessions
        )

        failed = FakeRawConnection()
        failed.transaction_status = postgres_backend._TX_INERROR
        postgres_backend._set_session(failed, "", read_only=False)
        self.assertEqual(1, failed.rollbacks)
        self.assertEqual(
            [{"readonly": False, "autocommit": False}], failed.sessions
        )

        unknown = FakeRawConnection()
        unknown.transaction_status = postgres_backend._TX_UNKNOWN
        with self.assertRaises(postgres_backend.PostgreSQLOperationalError):
            postgres_backend._set_session(unknown, "", read_only=False)

    def test_context_manager_finishes_each_transaction_exactly_once(self) -> None:
        raw = FakeRawConnection()
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        with connection as current:
            current.execute("SELECT 1")
        self.assertEqual(1, raw.commits)
        self.assertEqual(0, raw.rollbacks)
        self.assertEqual([(raw, False)], pool.returned)

        raw = FakeRawConnection()
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        with connection as current:
            current.execute("SELECT 1")
            current.commit()
        self.assertEqual(1, raw.commits)
        self.assertEqual(0, raw.rollbacks)
        self.assertEqual([(raw, False)], pool.returned)

        raw = FakeRawConnection()
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        with self.assertRaisesRegex(ValueError, "business failure"):
            with connection as current:
                current.execute("SELECT 1")
                raise ValueError("business failure")
        self.assertEqual(0, raw.commits)
        self.assertEqual(1, raw.rollbacks)
        self.assertEqual([(raw, False)], pool.returned)

    def test_close_rolls_back_dirty_once_and_leaves_idle_alone(self) -> None:
        idle = FakeRawConnection()
        idle_pool = FakePool(idle)
        PostgresConnection(
            idle,
            _PoolEntry(idle_pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        ).close()
        self.assertEqual(0, idle.rollbacks)
        self.assertEqual([(idle, False)], idle_pool.returned)

        dirty = FakeRawConnection()
        dirty_pool = FakePool(dirty)
        dirty_connection = PostgresConnection(
            dirty,
            _PoolEntry(dirty_pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        dirty_connection.execute("SELECT 1")
        dirty_connection.close()
        self.assertEqual(1, dirty.rollbacks)
        self.assertEqual([(dirty, False)], dirty_pool.returned)

    def test_unknown_connection_is_discarded_without_masking_business_error(self) -> None:
        raw = FakeRawConnection()
        raw.transaction_status = postgres_backend._TX_UNKNOWN
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        with self.assertRaisesRegex(ValueError, "original failure"):
            with connection:
                raise ValueError("original failure")
        self.assertEqual([(raw, True)], pool.returned)

        raw = FakeRawConnection()
        raw.transaction_status = postgres_backend._TX_UNKNOWN
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        with self.assertRaises(postgres_backend.PostgreSQLOperationalError):
            with connection:
                pass
        self.assertEqual([(raw, True)], pool.returned)

    def test_aborted_transaction_rolls_back_once_and_is_not_reused_dirty(self) -> None:
        raw = FakeRawConnection()
        raw.transaction_status = postgres_backend._TX_INERROR
        pool = FakePool(raw)
        connection = PostgresConnection(
            raw,
            _PoolEntry(pool),
            schema="dwti_fixture",
            identity_tables=frozenset(),
            read_only=False,
        )
        with self.assertRaisesRegex(
            postgres_backend.PostgreSQLBackendError, "aborted"
        ):
            with connection:
                pass
        self.assertEqual(1, raw.rollbacks)
        self.assertEqual([(raw, False)], pool.returned)

    def test_pool_error_and_failed_session_setup_are_operational(self) -> None:
        class PoolError(Exception):
            pass

        exhausted = FakePool()
        exhausted.getconn = lambda: (_ for _ in ()).throw(
            PoolError("pool exhausted")
        )
        with patch.object(
            postgres_backend, "_pool_entry", return_value=_PoolEntry(exhausted)
        ):
            with self.assertRaises(postgres_backend.PostgreSQLOperationalError):
                connect_postgres("postgresql://runtime@localhost/darkweb")

        raw = FakeRawConnection()
        pool = FakePool(raw)
        with patch.object(
            postgres_backend, "_pool_entry", return_value=_PoolEntry(pool)
        ), patch.object(
            postgres_backend,
            "_set_session",
            side_effect=postgres_backend.PostgreSQLOperationalError("setup failed"),
        ):
            with self.assertRaises(postgres_backend.PostgreSQLOperationalError):
                connect_postgres("postgresql://runtime@localhost/darkweb")
        self.assertEqual([(raw, True)], pool.returned)

        raw = FakeRawConnection()
        pool = FakePool(raw)
        with patch.object(
            postgres_backend, "_pool_entry", return_value=_PoolEntry(pool)
        ), patch.object(
            postgres_backend,
            "_set_session",
            side_effect=[
                None,
                postgres_backend.PostgreSQLOperationalError(
                    "final setup failed"
                ),
            ],
        ), patch.object(
            postgres_backend,
            "_validate_release",
            return_value=frozenset({"items"}),
        ):
            with self.assertRaises(postgres_backend.PostgreSQLOperationalError):
                connect_postgres("postgresql://runtime@localhost/darkweb")
        self.assertEqual([(raw, True)], pool.returned)

    def test_validation_failure_rolls_back_and_reuses_clean_connection(self) -> None:
        raw = FakeRawConnection()
        pool = FakePool(raw)

        def fail_validation(*_args, **_kwargs):
            raw.transaction_status = postgres_backend._TX_INTRANS
            raise postgres_backend.PostgreSQLBackendError("invalid release")

        with patch.object(
            postgres_backend, "_pool_entry", return_value=_PoolEntry(pool)
        ), patch.object(postgres_backend, "_set_session"), patch.object(
            postgres_backend, "_validate_release", side_effect=fail_validation
        ):
            with self.assertRaisesRegex(
                postgres_backend.PostgreSQLBackendError, "invalid release"
            ):
                connect_postgres("postgresql://runtime@localhost/darkweb")
        self.assertEqual(1, raw.rollbacks)
        self.assertEqual([(raw, False)], pool.returned)

    def test_pid_change_discards_inherited_pool_registry(self) -> None:
        old_pid = postgres_backend._POOL_PID
        old_pools = postgres_backend._POOLS
        inherited = FakePool()
        try:
            postgres_backend._POOL_PID = 10
            postgres_backend._POOLS = {("dsn", 1, 4, 5): _PoolEntry(inherited)}
            with patch.object(postgres_backend.os, "getpid", return_value=11):
                postgres_backend._discard_inherited_pools()
            self.assertEqual({}, postgres_backend._POOLS)
            self.assertFalse(inherited.closed)
        finally:
            postgres_backend._POOL_PID = old_pid
            postgres_backend._POOLS = old_pools


class RuntimeAndSQLiteTests(unittest.TestCase):
    def test_active_release_runtime_url_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "active-release.json"
            release.write_text(
                json.dumps(
                    {
                        "format": 1,
                        "runtime_database_url": "postgresql://runtime/db",
                        "database_schema": "dwti_fixture",
                        "schema_version": "0005_postgres_write_paths",
                        "output_root": str(root / "artifacts"),
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_ACTIVE_RELEASE_FILE": str(release),
                    "DARKWEB_COLLECTOR_DATABASE_URL": "",
                    "DARKWEB_COLLECTOR_DATABASE_SCHEMA": "",
                    "DARKWEB_COLLECTOR_SCHEMA_VERSION": "",
                    "DARKWEB_COLLECTOR_OUTPUT_ROOT": "",
                },
                clear=False,
            ):
                self.assertEqual("postgresql://runtime/db", runtime.configured_database_url())
                self.assertEqual("dwti_fixture", runtime.configured_database_schema())
                self.assertEqual(
                    "0005_postgres_write_paths",
                    runtime.configured_schema_version(),
                )
                self.assertEqual(root / "artifacts", runtime.output_root())

    def test_active_release_cannot_bypass_current_postgres_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "active-release.json"
            release.write_text(
                json.dumps(
                    {
                        "format": 1,
                        "runtime_database_url": "postgresql://runtime/db",
                        "database_schema": "dwti_fixture",
                        "schema_version": "0004_performance_indexes",
                    }
                ),
                encoding="utf-8",
            )
            raw = FakeRawConnection()
            raw.migrations = [
                ("0001_baseline", "fixture"),
                ("0004_performance_indexes", "fixture"),
            ]
            pool = FakePool(raw)
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_ACTIVE_RELEASE_FILE": str(release),
                    "DARKWEB_COLLECTOR_DATABASE_URL": "",
                    "DARKWEB_COLLECTOR_DATABASE_SCHEMA": "",
                    "DARKWEB_COLLECTOR_SCHEMA_FINGERPRINT": "",
                    "DARKWEB_COLLECTOR_SCHEMA_VERSION": "",
                },
                clear=False,
            ), patch.object(
                postgres_backend,
                "_pool_entry",
                return_value=_PoolEntry(pool),
            ), patch.object(
                postgres_backend,
                "_set_session",
            ):
                self.assertEqual(
                    "0004_performance_indexes",
                    runtime.configured_schema_version(),
                )
                with self.assertRaisesRegex(
                    postgres_backend.PostgreSQLBackendError,
                    "0006_postgres_read_paths",
                ):
                    connect(root / "unused.db")
            self.assertEqual(1, raw.rollbacks)
            self.assertEqual([(raw, False)], pool.returned)

    def test_sqlite_remains_default_and_health_uses_38_source_tables(self) -> None:
        self.assertEqual(38, len(SOURCE_SQLITE_TABLES))
        self.assertEqual(39, len(TARGET_POSTGRES_TABLES))
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "collector.db"
            missing_release = Path(directory) / "missing-release.json"
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_ACTIVE_RELEASE_FILE": str(missing_release),
                    "DARKWEB_COLLECTOR_DATABASE_URL": "",
                    "DARKWEB_COLLECTOR_SCHEMA_VERSION": "",
                },
                clear=False,
            ):
                connection = connect(db_path)
                self.assertEqual("sqlite", connection.backend_name)
                self.assertEqual(
                    "0006_postgres_read_paths",
                    runtime.configured_schema_version(),
                )
                connection.close()
                readonly = connect_readonly(db_path)
                health = database_health_payload(readonly)
                self.assertEqual("ok", health["status"])
                self.assertEqual(38, health["requiredBusinessTableCount"])
                self.assertTrue(readonly.read_only)
                readonly.close()

    def test_explicit_sql_helpers_preserve_backend_semantics(self) -> None:
        postgres = type("Connection", (), {"backend_name": "postgresql"})()
        self.assertIn(" LIKE ?", sql_case_insensitive_like(None, "title"))
        self.assertIn(" COLLATE NOCASE", sql_case_insensitive_like(None, "title"))
        self.assertIn(" ILIKE ?", sql_case_insensitive_like(postgres, "title"))
        self.assertEqual("LOWER(title)", sql_case_insensitive_order(postgres, "title"))
        self.assertEqual("LEAST(100, score)", sql_scalar_min(postgres, "100", "score"))


if __name__ == "__main__":
    unittest.main()
