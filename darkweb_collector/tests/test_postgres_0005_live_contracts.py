from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
from dataclasses import dataclass, field
import os
import re
import secrets
from typing import Any, Iterator

import pytest

from darkweb_collector.migration_bundle import (
    SCHEMA_VERSION,
    WRITE_SCHEMA_VERSION,
    _apply_postgres_write_paths,
    _apply_postgres_read_paths,
    _grant_runtime_permissions,
    _runtime_role_from_url,
)


MIGRATION_URL_ENV = "DARKWEB_MIGRATION_TARGET_DATABASE_URL"
RUNTIME_URL_ENV = "DARKWEB_MIGRATION_RUNTIME_DATABASE_URL"
SOURCE_SCHEMA_ENV = "DARKWEB_POSTGRES_0005_TEST_SOURCE_SCHEMA"
_REQUIRED_ENV = (MIGRATION_URL_ENV, RUNTIME_URL_ENV, SOURCE_SCHEMA_ENV)
_MISSING_ENV = tuple(key for key in _REQUIRED_ENV if not os.environ.get(key, "").strip())

pytestmark = pytest.mark.skipif(
    bool(_MISSING_ENV),
    reason="live PostgreSQL 0005 contracts are opt-in; set " + ", ".join(_REQUIRED_ENV),
)

_FIXTURE_RE = re.compile(r"dwti_test_[0-9a-f]{20}\Z")
_SOURCE_RE = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_TABLES = (
    "schema_migrations",
    "normalized_intelligence_cache_state",
    "ai_aggregation_schedule_claims",
    "victims",
    "forum_topics",
    "forum_details",
    "forum_victims",
    "crawl_jobs",
)
_DATA_TABLES = tuple(table for table in _TABLES if table != "schema_migrations")


def _set_search_path(connection: Any, schema: str) -> None:
    from psycopg2 import sql  # type: ignore

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("SET SESSION search_path TO {}, pg_catalog").format(
                sql.Identifier(schema)
            )
        )
    connection.commit()


@dataclass(frozen=True)
class LivePostgresFixture:
    migration_url: str = field(repr=False)
    runtime_url: str = field(repr=False)
    source_schema: str
    schema: str
    owner: str
    runtime_role: str

    def connect_migration(self):
        import psycopg2  # type: ignore

        connection = psycopg2.connect(
            self.migration_url,
            application_name="dwti-0005-live-migration",
            connect_timeout=5,
        )
        _set_search_path(connection, self.schema)
        return connection

    def connect_runtime(self):
        import psycopg2  # type: ignore

        connection = psycopg2.connect(
            self.runtime_url,
            application_name="dwti-0005-live-runtime",
            connect_timeout=5,
        )
        _set_search_path(connection, self.schema)
        return connection


def _assert_fixture_name(schema: str) -> None:
    if _FIXTURE_RE.fullmatch(schema) is None or schema.startswith("dwti_bench"):
        raise AssertionError(f"unsafe PostgreSQL fixture schema: {schema!r}")


def _schema_owner(connection: Any, schema: str) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_catalog.pg_get_userbyid(namespace.nspowner)
            FROM pg_catalog.pg_namespace AS namespace
            WHERE namespace.nspname=%s
            """,
            (schema,),
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


def _drop_fixture(connection: Any, schema: str, expected_owner: str) -> None:
    from psycopg2 import sql  # type: ignore

    _assert_fixture_name(schema)
    connection.rollback()
    connection.autocommit = True
    actual_owner = _schema_owner(connection, schema)
    if actual_owner is None:
        return
    if actual_owner != expected_owner:
        raise AssertionError(
            f"refusing to drop fixture owned by {actual_owner!r}; "
            f"expected {expected_owner!r}"
        )
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _create_pre_0005_fixture(
    connection: Any,
    *,
    source_schema: str,
    fixture_schema: str,
) -> None:
    """Read column metadata from source, but create all objects in the fixture."""

    from psycopg2 import sql  # type: ignore

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema=%s AND table_type='BASE TABLE'
            """,
            (source_schema,),
        )
        missing = sorted(set(_TABLES) - {str(row[0]) for row in cursor.fetchall()})
        if missing:
            raise AssertionError(
                f"source schema {source_schema!r} lacks required tables: {missing}"
            )

        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(fixture_schema)))
        for table in _TABLES:
            cursor.execute(
                sql.SQL(
                    "CREATE TABLE {}.{} (LIKE {}.{} "
                    "INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY "
                    "INCLUDING CONSTRAINTS INCLUDING STORAGE INCLUDING COMMENTS)"
                ).format(
                    sql.Identifier(fixture_schema),
                    sql.Identifier(table),
                    sql.Identifier(source_schema),
                    sql.Identifier(table),
                )
            )

        constraints = (
            "ALTER TABLE {}.schema_migrations ADD PRIMARY KEY (version)",
            "ALTER TABLE {}.normalized_intelligence_cache_state ADD PRIMARY KEY (id)",
            "ALTER TABLE {}.ai_aggregation_schedule_claims "
            "ADD PRIMARY KEY (profile_id, scheduled_for)",
            "ALTER TABLE {}.victims ADD PRIMARY KEY (id)",
            "ALTER TABLE {}.forum_topics ADD PRIMARY KEY (id)",
            "ALTER TABLE {}.forum_topics ADD UNIQUE (site_name, section, url)",
            "ALTER TABLE {}.forum_details ADD PRIMARY KEY (id)",
            "ALTER TABLE {}.forum_details ADD UNIQUE (site_name, section, topic_url)",
            "ALTER TABLE {}.forum_victims ADD PRIMARY KEY (id)",
            "ALTER TABLE {}.crawl_jobs ADD PRIMARY KEY (id)",
            "ALTER TABLE {}.crawl_jobs ADD UNIQUE (job_id)",
        )
        for statement in constraints:
            cursor.execute(sql.SQL(statement).format(sql.Identifier(fixture_schema)))

        cursor.execute(
            sql.SQL(
                "CREATE UNIQUE INDEX legacy_victims_business_key "
                "ON {}.victims(site_name, source_url, name, domain, status)"
            ).format(sql.Identifier(fixture_schema))
        )
        cursor.execute(
            sql.SQL(
                "CREATE INDEX idx_pgperf_jobs_status_queue "
                "ON {}.crawl_jobs(status, enqueued_at, id) "
                "WHERE status IN ('queued', 'running')"
            ).format(sql.Identifier(fixture_schema))
        )
        cursor.execute(
            sql.SQL(
                "INSERT INTO {}.schema_migrations("
                "version, checksum, source_schema_fingerprint, applied_at) "
                "SELECT version, checksum, source_schema_fingerprint, applied_at "
                "FROM {}.schema_migrations WHERE version NOT IN (%s, %s)"
            ).format(
                sql.Identifier(fixture_schema),
                sql.Identifier(source_schema),
            ),
            (WRITE_SCHEMA_VERSION, SCHEMA_VERSION),
        )


@pytest.fixture(scope="module")
def live_postgres_fixture() -> Iterator[LivePostgresFixture]:
    psycopg2 = pytest.importorskip("psycopg2")

    migration_url = os.environ[MIGRATION_URL_ENV].strip()
    runtime_url = os.environ[RUNTIME_URL_ENV].strip()
    source_schema = os.environ[SOURCE_SCHEMA_ENV].strip()
    if _SOURCE_RE.fullmatch(source_schema) is None:
        raise AssertionError(f"invalid source schema: {source_schema!r}")
    if source_schema.startswith(("dwti_test_", "dwti_bench")):
        raise AssertionError("source schema must not be a test or benchmark schema")

    fixture_schema = f"dwti_test_{secrets.token_hex(10)}"
    _assert_fixture_name(fixture_schema)
    runtime_role = _runtime_role_from_url(runtime_url)
    migration = psycopg2.connect(
        migration_url,
        application_name="dwti-0005-live-setup",
        connect_timeout=5,
    )
    owner = ""
    try:
        with migration.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            migration_database, owner = map(str, cursor.fetchone())
        with psycopg2.connect(
            runtime_url,
            application_name="dwti-0005-live-preflight",
            connect_timeout=5,
        ) as runtime:
            with runtime.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                runtime_database, authenticated_runtime = map(str, cursor.fetchone())
        if migration_database != runtime_database:
            raise AssertionError("migration and runtime URLs target different databases")
        if authenticated_runtime != runtime_role:
            raise AssertionError("runtime URL user does not match authenticated role")

        _create_pre_0005_fixture(
            migration,
            source_schema=source_schema,
            fixture_schema=fixture_schema,
        )
        write_result = _apply_postgres_write_paths(migration, fixture_schema)
        read_result = _apply_postgres_read_paths(migration, fixture_schema)
        repeated_read_result = _apply_postgres_read_paths(migration, fixture_schema)
        _grant_runtime_permissions(migration, fixture_schema, runtime_role)
        migration.commit()
        assert write_result["version"] == WRITE_SCHEMA_VERSION
        assert read_result == repeated_read_result
        assert _schema_owner(migration, fixture_schema) == owner

        yield LivePostgresFixture(
            migration_url=migration_url,
            runtime_url=runtime_url,
            source_schema=source_schema,
            schema=fixture_schema,
            owner=owner,
            runtime_role=runtime_role,
        )
    finally:
        try:
            _drop_fixture(migration, fixture_schema, owner)
        finally:
            migration.close()


@pytest.fixture(autouse=True)
def empty_live_fixture(
    live_postgres_fixture: LivePostgresFixture,
) -> Iterator[None]:
    from psycopg2 import sql  # type: ignore

    with live_postgres_fixture.connect_migration() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(
                        sql.SQL("{}.{}").format(
                            sql.Identifier(live_postgres_fixture.schema),
                            sql.Identifier(table),
                        )
                        for table in _DATA_TABLES
                    )
                )
            )
    yield


def _source_revision(connection: Any) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_revision FROM normalized_intelligence_cache_state WHERE id=1"
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def _mark_dirty(connection: Any, changed_at: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT dwti_mark_normalized_dirty(%s::TEXT)",
            (changed_at,),
        )
        return int(cursor.fetchone()[0])




def test_0006_is_idempotent_exact_and_runtime_usable(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    results = []
    with live_postgres_fixture.connect_migration() as connection:
        results.append(
            _apply_postgres_read_paths(connection, live_postgres_fixture.schema)
        )
        results.append(
            _apply_postgres_read_paths(connection, live_postgres_fixture.schema)
        )
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*), MIN(checksum), MAX(checksum)
                FROM schema_migrations
                WHERE version=%s
                """,
                (SCHEMA_VERSION,),
            )
            migration_count, minimum_checksum, maximum_checksum = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*), MIN(indexdef), MAX(indexdef)
                FROM pg_indexes
                WHERE schemaname=%s
                  AND tablename='crawl_jobs'
                  AND indexname='idx_pgread_jobs_recency_expr'
                """,
                (live_postgres_fixture.schema,),
            )
            index_count, minimum_definition, maximum_definition = cursor.fetchone()
            cursor.execute(
                "SELECT has_schema_privilege(%s, %s, 'USAGE'), "
                "has_table_privilege(%s, %s, 'SELECT')",
                (
                    live_postgres_fixture.runtime_role,
                    live_postgres_fixture.schema,
                    live_postgres_fixture.runtime_role,
                    f"{live_postgres_fixture.schema}.crawl_jobs",
                ),
            )
            schema_usage, table_select = cursor.fetchone()

    assert results[0] == results[1]
    assert results[0]["version"] == SCHEMA_VERSION
    assert results[0]["read_path_indexes"] == 1
    assert int(migration_count) == 1
    assert str(minimum_checksum) == str(maximum_checksum)
    assert int(index_count) == 1
    assert str(minimum_definition) == str(maximum_definition)
    definition = str(minimum_definition)
    assert (
        "USING btree (COALESCE(finished_at, started_at, enqueued_at) DESC)"
        in definition
    )
    assert " INCLUDE " not in definition.upper()
    assert ", id" not in definition.lower()
    assert bool(schema_usage) is True
    assert bool(table_select) is True

    with live_postgres_fixture.connect_runtime() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan TO off")
            cursor.execute(
                """
                EXPLAIN
                SELECT site_name, job_type, status, queue_name, target,
                       enqueued_at, started_at, finished_at, error_message
                FROM crawl_jobs
                ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
                LIMIT 300
                """
            )
            plan = "\n".join(str(row[0]) for row in cursor.fetchall())
    assert "idx_pgread_jobs_recency_expr" in plan

def test_0005_reconciles_previously_developed_rejected_job_index(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    from psycopg2 import sql  # type: ignore

    old_index = "idx_pgperf_jobs_status_queue"
    rejected_index = "idx_pgwrite_jobs_active_site_type_time"
    with live_postgres_fixture.connect_migration() as connection:
        with connection.cursor() as cursor:
            schema = sql.Identifier(live_postgres_fixture.schema)
            cursor.execute(
                sql.SQL("DROP INDEX IF EXISTS {}.{}").format(
                    schema, sql.Identifier(old_index)
                )
            )
            cursor.execute(
                sql.SQL(
                    "CREATE INDEX {} ON {}.crawl_jobs("
                    "site_name, job_type, "
                    "COALESCE(started_at, enqueued_at) DESC, id DESC"
                    ") WHERE status IN ('enqueued', 'running')"
                ).format(sql.Identifier(rejected_index), schema)
            )
        result = _apply_postgres_write_paths(
            connection,
            live_postgres_fixture.schema,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname=%s AND indexname IN (%s, %s)
                ORDER BY indexname
                """,
                (live_postgres_fixture.schema, old_index, rejected_index),
            )
            rows = list(cursor.fetchall())

    assert result["write_path_indexes"] == 2
    assert [str(row[0]) for row in rows] == [old_index]
    assert "status" in str(rows[0][1])
    assert "'queued'::text" in str(rows[0][1])
    assert "'running'::text" in str(rows[0][1])

def test_runtime_role_executes_0005_functions_and_public_cannot(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    with live_postgres_fixture.connect_migration() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT procedure.proname,
                       has_function_privilege(%s, procedure.oid, 'EXECUTE'),
                       EXISTS (
                           SELECT 1
                           FROM aclexplode(COALESCE(
                               procedure.proacl,
                               acldefault('f', procedure.proowner)
                           )) AS function_acl
                           WHERE function_acl.grantee=0
                             AND function_acl.privilege_type='EXECUTE'
                       )
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace
                  ON namespace.oid=procedure.pronamespace
                WHERE namespace.nspname=%s AND procedure.proname LIKE 'dwti_%%'
                ORDER BY procedure.proname
                """,
                (live_postgres_fixture.runtime_role, live_postgres_fixture.schema),
            )
            rows = cursor.fetchall()

    assert [str(row[0]) for row in rows] == [
        "dwti_mark_normalized_dirty",
        "dwti_upsert_forum_detail",
        "dwti_upsert_forum_topic",
        "dwti_upsert_victim",
    ]
    assert all(bool(row[1]) for row in rows)
    assert not any(bool(row[2]) for row in rows)

    with live_postgres_fixture.connect_runtime() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            assert str(cursor.fetchone()[0]) == live_postgres_fixture.runtime_role


def test_dirty_revision_rollback_and_uncommitted_visibility(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    changed_at = "2026-08-24T08:00:00+00:00"
    rollback_at = "2026-08-24T08:01:00+00:00"
    writer = live_postgres_fixture.connect_runtime()
    observer = live_postgres_fixture.connect_runtime()
    try:
        with writer.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO normalized_intelligence_cache_state(
                    id, source_signature, event_count, refreshed_at,
                    source_revision, applied_revision, dirty_since, dirty_at
                ) VALUES (1, 'stable-signature', 9, 'refreshed', 5, 5, '', '')
                """
            )
        writer.commit()
        assert _source_revision(observer) == 5

        assert _mark_dirty(writer, changed_at) == 6
        assert _source_revision(observer) == 5
        writer.commit()
        assert _source_revision(observer) == 6
        with observer.cursor() as cursor:
            cursor.execute(
                """
                SELECT source_signature, event_count, refreshed_at,
                       applied_revision, dirty_since, dirty_at
                FROM normalized_intelligence_cache_state WHERE id=1
                """
            )
            assert cursor.fetchone() == (
                "stable-signature",
                9,
                "refreshed",
                5,
                changed_at,
                changed_at,
            )

        assert _mark_dirty(writer, rollback_at) == 7
        writer.rollback()
        assert _source_revision(observer) == 6
        with observer.cursor() as cursor:
            cursor.execute(
                "SELECT dirty_since, dirty_at "
                "FROM normalized_intelligence_cache_state WHERE id=1"
            )
            assert cursor.fetchone() == (changed_at, changed_at)
    finally:
        writer.close()
        observer.close()

def _claim_schedule(
    fixture: LivePostgresFixture,
    profile_id: str,
    scheduled_for: str,
    created_at: str,
) -> bool:
    from psycopg2 import IntegrityError  # type: ignore

    connection = fixture.connect_runtime()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ai_aggregation_schedule_claims(
                    profile_id, scheduled_for, created_at
                ) VALUES (%s, %s, %s)
                """,
                (profile_id, scheduled_for, created_at),
            )
        connection.commit()
        return True
    except IntegrityError:
        connection.rollback()
        return False
    finally:
        connection.close()


def test_claim_created_at_release_and_concurrent_single_winner(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    profile_id = "profile-created-at"
    scheduled_for = "2026-08-24T09:00:00+00:00"
    original_created_at = "2026-08-24T08:59:00+00:00"
    assert _claim_schedule(
        live_postgres_fixture,
        profile_id,
        scheduled_for,
        original_created_at,
    )
    assert not _claim_schedule(
        live_postgres_fixture,
        profile_id,
        scheduled_for,
        "2026-08-24T09:01:00+00:00",
    )
    with live_postgres_fixture.connect_runtime() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT created_at FROM ai_aggregation_schedule_claims
                WHERE profile_id=%s AND scheduled_for=%s
                """,
                (profile_id, scheduled_for),
            )
            assert str(cursor.fetchone()[0]) == original_created_at
            cursor.execute(
                """
                DELETE FROM ai_aggregation_schedule_claims
                WHERE profile_id=%s AND scheduled_for=%s
                """,
                (profile_id, scheduled_for),
            )
    assert _claim_schedule(
        live_postgres_fixture,
        profile_id,
        scheduled_for,
        "2026-08-24T09:02:00+00:00",
    )

    workers = 8
    barrier = Barrier(workers)

    def concurrent_claim(worker_index: int) -> bool:
        from psycopg2 import IntegrityError  # type: ignore

        connection = live_postgres_fixture.connect_runtime()
        try:
            barrier.wait(timeout=10)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_aggregation_schedule_claims(
                        profile_id, scheduled_for, created_at
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        "profile-concurrent",
                        "2026-08-24T10:00:00+00:00",
                        f"worker-{worker_index}",
                    ),
                )
            connection.commit()
            return True
        except IntegrityError:
            connection.rollback()
            return False
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(concurrent_claim, range(workers)))
    assert results.count(True) == 1
    assert results.count(False) == workers - 1

def _upsert_victim(
    connection: Any,
    *,
    run_id: int,
    domain: str | None,
    display_label: str,
    content_hash: str,
    detail_status: str | None,
) -> int:
    raw_json = json.dumps(
        {
            "run_id": run_id,
            "domain": domain,
            "display_label": display_label,
            "content_hash": content_hash,
        },
        separators=(",", ":"),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT dwti_upsert_victim(
                %s::BIGINT, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,
                %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,
                %s::DOUBLE PRECISION, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT
            )
            """,
            (
                run_id,
                "victim-site",
                "https://source.invalid/list",
                f"https://source.invalid/detail/{run_id}",
                "Acme",
                display_label,
                domain,
                "published",
                "2026-08-24T01:00:00+00:00",
                "10 GB",
                10.0,
                content_hash,
                detail_status,
                raw_json,
                f"2026-08-24T01:{run_id % 60:02d}:00+00:00",
            ),
        )
        return int(cursor.fetchone()[0])


def test_victim_null_empty_domain_stable_id_and_rollback(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    connection = live_postgres_fixture.connect_runtime()
    try:
        victim_id = _upsert_victim(
            connection,
            run_id=101,
            domain=None,
            display_label="Acme original",
            content_hash="hash-1",
            detail_status="ok",
        )
        connection.commit()
        first_revision = _source_revision(connection)

        repeated_id = _upsert_victim(
            connection,
            run_id=202,
            domain="",
            display_label="Acme updated",
            content_hash="hash-2",
            detail_status=None,
        )
        connection.commit()
        assert repeated_id == victim_id
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, domain, first_seen_run_id, last_seen_run_id,
                       last_detail_fetch_status, display_label, content_hash
                FROM victims
                """
            )
            assert cursor.fetchall() == [
                (
                    victim_id,
                    None,
                    101,
                    202,
                    "ok",
                    "Acme updated",
                    "hash-2",
                )
            ]
        assert _source_revision(connection) == first_revision + 1
        committed_revision = _source_revision(connection)

        assert _upsert_victim(
            connection,
            run_id=303,
            domain=None,
            display_label="must roll back",
            content_hash="hash-rollback",
            detail_status="failed",
        ) == victim_id
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT display_label, content_hash, last_seen_run_id "
                "FROM victims WHERE id=%s",
                (victim_id,),
            )
            assert cursor.fetchone() == ("Acme updated", "hash-2", 202)
        assert _source_revision(connection) == committed_revision
    finally:
        connection.close()

def _upsert_topic(
    connection: Any,
    *,
    title: str,
    content_hash: str,
    author: str,
    views: str,
    collected_at: str,
) -> tuple[int, bool]:
    raw_json = json.dumps(
        {"title": title, "content_hash": content_hash},
        separators=(",", ":"),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT topic_id, materially_changed
            FROM dwti_upsert_forum_topic(
                %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,
                %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,
                %s::TEXT, %s::TEXT, %s::TEXT
            )
            """,
            (
                "forum-site",
                "databases",
                title,
                "https://forum.invalid/topic/1",
                author,
                "2",
                views,
                "2026-08-24",
                "",
                content_hash,
                collected_at,
                raw_json,
                collected_at,
            ),
        )
        row = cursor.fetchone()
    return int(row[0]), bool(row[1])


def test_topic_only_title_or_hash_changes_dirty(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    connection = live_postgres_fixture.connect_runtime()
    try:
        topic_id, changed = _upsert_topic(
            connection,
            title="Original title",
            content_hash="topic-hash-1",
            author="alice",
            views="10",
            collected_at="2026-08-24T02:00:00+00:00",
        )
        connection.commit()
        assert changed is True
        first_revision = _source_revision(connection)

        repeated_id, changed = _upsert_topic(
            connection,
            title="Original title",
            content_hash="topic-hash-1",
            author="bob",
            views="99",
            collected_at="2026-08-24T03:00:00+00:00",
        )
        connection.commit()
        assert repeated_id == topic_id
        assert changed is False
        assert _source_revision(connection) == first_revision
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT author, views, last_seen_at FROM forum_topics WHERE id=%s",
                (topic_id,),
            )
            assert cursor.fetchone() == (
                "bob",
                "99",
                "2026-08-24T03:00:00+00:00",
            )

        _, changed = _upsert_topic(
            connection,
            title="Changed title",
            content_hash="topic-hash-1",
            author="bob",
            views="99",
            collected_at="2026-08-24T04:00:00+00:00",
        )
        connection.commit()
        assert changed is True
        assert _source_revision(connection) == first_revision + 1

        _, changed = _upsert_topic(
            connection,
            title="Changed title",
            content_hash="topic-hash-2",
            author="bob",
            views="99",
            collected_at="2026-08-24T05:00:00+00:00",
        )
        connection.commit()
        assert changed is True
        committed_revision = _source_revision(connection)

        _, changed = _upsert_topic(
            connection,
            title="must roll back",
            content_hash="topic-hash-2",
            author="mallory",
            views="100",
            collected_at="2026-08-24T06:00:00+00:00",
        )
        assert changed is True
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT title, author, content_hash FROM forum_topics WHERE id=%s",
                (topic_id,),
            )
            assert cursor.fetchone() == ("Changed title", "bob", "topic-hash-2")
        assert _source_revision(connection) == committed_revision
    finally:
        connection.close()

def _upsert_detail(
    connection: Any,
    *,
    content: str,
    content_hash: str,
    victims: list[dict[str, str | None]],
    collected_at: str,
) -> int:
    victims_summary = ", ".join(str(item.get("name") or "") for item in victims)
    raw_json = json.dumps(
        {"content": content, "content_hash": content_hash},
        separators=(",", ":"),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT dwti_upsert_forum_detail(
                %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,
                %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,
                %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT
            )
            """,
            (
                "forum-site",
                "databases",
                "https://forum.invalid/topic/1",
                content,
                "alice",
                "2026-08-24",
                "https://files.invalid/a.zip",
                victims_summary,
                "actor-a, actor-b",
                content_hash,
                collected_at,
                raw_json,
                json.dumps(victims, separators=(",", ":")),
                collected_at,
            ),
        )
        return int(cursor.fetchone()[0])


def _forum_children(
    connection: Any,
    detail_id: int,
) -> list[tuple[str, str | None, str | None]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT victim_name, industry, region
            FROM forum_victims
            WHERE forum_detail_id=%s
            ORDER BY id
            """,
            (detail_id,),
        )
        return [(str(row[0]), row[1], row[2]) for row in cursor.fetchall()]


def test_detail_5_0_5_order_null_duplicates_and_rollback(
    live_postgres_fixture: LivePostgresFixture,
) -> None:
    from psycopg2.errors import NotNullViolation  # type: ignore

    victims = [
        {"name": "Acme", "industry": None, "region": "CN"},
        {"name": "Acme", "industry": None, "region": "CN"},
        {"name": "Beta", "industry": "finance", "region": None},
        {"name": "Gamma"},
        {"name": "Delta", "industry": "", "region": ""},
    ]
    expected = [
        ("Acme", None, "CN"),
        ("Acme", None, "CN"),
        ("Beta", "finance", None),
        ("Gamma", None, None),
        ("Delta", "", ""),
    ]
    connection = live_postgres_fixture.connect_runtime()
    try:
        detail_id = _upsert_detail(
            connection,
            content="five children",
            content_hash="detail-hash-1",
            victims=victims,
            collected_at="2026-08-24T02:30:00+00:00",
        )
        connection.commit()
        first_revision = _source_revision(connection)
        assert _forum_children(connection, detail_id) == expected

        empty_id = _upsert_detail(
            connection,
            content="empty children",
            content_hash="detail-hash-empty",
            victims=[],
            collected_at="2026-08-24T03:30:00+00:00",
        )
        connection.commit()
        assert empty_id == detail_id
        assert _forum_children(connection, detail_id) == []
        assert _source_revision(connection) == first_revision + 1

        restored_id = _upsert_detail(
            connection,
            content="restored children",
            content_hash="detail-hash-restored",
            victims=victims,
            collected_at="2026-08-24T04:30:00+00:00",
        )
        connection.commit()
        assert restored_id == detail_id
        assert _forum_children(connection, detail_id) == expected
        assert _source_revision(connection) == first_revision + 2
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT content, content_hash, victims "
                "FROM forum_details WHERE id=%s",
                (detail_id,),
            )
            committed_parent = cursor.fetchone()
        committed_revision = _source_revision(connection)

        with pytest.raises(NotNullViolation):
            _upsert_detail(
                connection,
                content="must roll back",
                content_hash="detail-hash-rollback",
                victims=[
                    {
                        "name": "replacement",
                        "industry": "one",
                        "region": "A",
                    },
                    {"industry": None, "region": None},
                ],
                collected_at="2026-08-24T05:30:00+00:00",
            )
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT content, content_hash, victims "
                "FROM forum_details WHERE id=%s",
                (detail_id,),
            )
            assert cursor.fetchone() == committed_parent
        assert _forum_children(connection, detail_id) == expected
        assert _source_revision(connection) == committed_revision
    finally:
        connection.close()
