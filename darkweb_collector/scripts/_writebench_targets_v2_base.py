from __future__ import annotations

import hashlib

from darkweb_collector.migration_bundle import (
    _apply_postgres_read_paths,
    _apply_postgres_write_paths,
    _grant_runtime_permissions,
    _install_compatibility_functions,
    _runtime_role_from_url,
)
from darkweb_collector.postgres_backend import connect_postgres

from _writebench_core import CANDIDATE_VERSION, CLONE_TABLES, WriteBenchmarkError
from _writebench_targets_base import (
    CleanupRegistry,
    PostgresTarget as _BasePostgresTarget,
    SQLiteTarget,
    _connect_raw,
    _driver,
    connection_info,
    list_disposable_schemas,
    source_schema_snapshot,
)


class PostgresTarget(_BasePostgresTarget):
    """Compare write paths while holding the production connector constant."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._record["connector_mode"] = (
            "production_double_session_auto_identity_returning"
        )
        self._record["baseline_candidate_marker_only"] = self.variant == "baseline"

    def __enter__(self):
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
                        sql.SQL(
                            "INSERT INTO {}.{} OVERRIDING SYSTEM VALUE SELECT * FROM {}.{}"
                        ).format(
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
                else:
                    cursor.execute(
                        sql.SQL(
                            "INSERT INTO {}.schema_migrations(version, checksum, source_schema_fingerprint) "
                            "VALUES(%s, %s, NULL) ON CONFLICT(version) DO UPDATE SET checksum=EXCLUDED.checksum"
                        ).format(sql.Identifier(self.schema)),
                        (
                            CANDIDATE_VERSION,
                            hashlib.sha256(
                                b"benchmark-only-marker-without-0005-write-or-0006-read-paths"
                            ).hexdigest(),
                        ),
                    )
                runtime_role = _runtime_role_from_url(self.runtime_url)
                _grant_runtime_permissions(connection, self.schema, runtime_role)
                for table in CLONE_TABLES:
                    cursor.execute(
                        sql.SQL("ANALYZE {}.{}").format(
                            sql.Identifier(self.schema), sql.Identifier(table)
                        )
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

    def connect(self):
        result = connect_postgres(
            self.runtime_url,
            schema=self.schema,
            expected_fingerprint=self.fingerprint,
            expected_version=self.expected_version,
            read_only=False,
        )
        with self._lock:
            self.connections_opened += 1
        return result


__all__ = [
    "CleanupRegistry",
    "PostgresTarget",
    "SQLiteTarget",
    "connection_info",
    "list_disposable_schemas",
    "source_schema_snapshot",
]

