#!/usr/bin/env python3
"""Run isolated PostgreSQL write-path ablations on disposable schemas.

Every compared pair is cloned from the same source schema and differs in one
connector or business-SQL choice. The source schema is never written.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
from threading import Lock
from typing import Any
import statistics
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
SRC = ROOT / "src"
for path in (SCRIPT_DIR, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from benchmark_postgres_write_paths import load_database_urls  # noqa: E402
from darkweb_collector import db  # noqa: E402
from darkweb_collector.postgres_backend import (  # noqa: E402
    _insert_table,
    _set_session,
    close_postgres_pools,
    connect_postgres,
)
from _writebench_core import (  # noqa: E402
    BASELINE_VERSION,
    DEFAULT_CONCURRENCY,
    DEFAULT_ITERATIONS,
    DEFAULT_ROUNDS,
    DEFAULT_WARMUPS,
    RunConfig,
    WriteBenchmarkError,
    _median_summary,
    _non_negative_int,
    _positive_int,
    _shared_benchmark_module,
    _source_identifier,
    _utc_now,
    variant_order,
)
from _writebench_paths import LegacyPostgresPaths, ProductionPaths  # noqa: E402
from _writebench_targets import (  # noqa: E402
    CleanupRegistry,
    PostgresTarget,
    connection_info,
    list_disposable_schemas,
    source_schema_snapshot,
)
from _writebench_targets_base import _connect_raw, _driver  # noqa: E402


ABLATIONS = (
    "checkout_session",
    "job_identity",
    "claim_sql",
    "crawl_jobs_index",
    "crawl_jobs_drop_wrong",
    "crawl_jobs_read_index",
)
VARIANTS = {
    "checkout_session": ("double_session", "single_session"),
    "job_identity": ("auto_returning", "no_returning"),
    "claim_sql": ("exception_rollback", "on_conflict_returning"),
    "crawl_jobs_index": ("old_index", "new_index"),
    "crawl_jobs_drop_wrong": ("old_index", "drop_only"),
    "crawl_jobs_read_index": ("without_recency_index", "recency_index"),
}
OLD_JOB_INDEX = "idx_pgperf_jobs_status_queue"
NEW_JOB_INDEX = "idx_pgwrite_jobs_active_site_type_time"
RECENCY_JOB_INDEX = "idx_crawl_jobs_recency_expr"


class _DummyConnection:
    def close(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class _AutoIdentityConnection:
    """Add only the pre-0005 implicit RETURNING id behavior."""

    backend_name = "postgresql"

    def __init__(self, connection) -> None:
        self._connection = connection
        self.identity_tables = connection.identity_tables
        self.schema = connection.schema
        self.read_only = connection.read_only

    def execute(self, sql_text, parameters=None, *, return_identity=None):
        capture = return_identity
        if capture is None:
            capture = _insert_table(sql_text) in self.identity_tables
        return self._connection.execute(
            sql_text,
            parameters,
            return_identity=bool(capture),
        )

    def executemany(self, sql_text, parameters):
        return self._connection.executemany(sql_text, parameters)

    def execute_values(self, sql_text, parameters, *, template=None, page_size=500):
        return self._connection.execute_values(
            sql_text, parameters, template=template, page_size=page_size
        )

    def cursor(self):
        return self._connection.cursor()

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    @property
    def closed(self) -> bool:
        return self._connection.closed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._connection.__exit__(exc_type, exc_value, traceback)


class _TargetView:
    """Select connector behavior without changing the cloned schema."""

    def __init__(
        self,
        target: PostgresTarget,
        *,
        extra_session: bool = False,
        auto_identity: bool = False,
    ) -> None:
        self.target = target
        self.extra_session = extra_session
        self.auto_identity = auto_identity
        self.connections_opened = 0
        self._lock = Lock()

    def connect(self):
        connection = connect_postgres(
            self.target.runtime_url,
            schema=self.target.schema,
            expected_fingerprint=self.target.fingerprint,
            expected_version=self.target.expected_version,
            read_only=False,
        )
        if self.extra_session:
            _set_session(connection._raw, self.target.schema, read_only=False)
        result = _AutoIdentityConnection(connection) if self.auto_identity else connection
        with self._lock:
            self.connections_opened += 1
        return result


def _selected_ablations(value: str) -> tuple[str, ...]:
    selected = tuple(item.strip() for item in str(value or "").split(",") if item.strip())
    unknown = sorted(set(selected) - set(ABLATIONS))
    if not selected or unknown:
        raise argparse.ArgumentTypeError(
            "ablations must be a comma-separated subset of " + ",".join(ABLATIONS)
        )
    return selected


def _source_fingerprint(snapshot: dict[str, Any], source_version: str) -> str:
    migrations = {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in snapshot.get("summary", {}).get("migrations", [])
    }
    if source_version not in migrations:
        raise WriteBenchmarkError(f"source schema is missing {source_version}")
    fingerprint = migrations.get("0001_baseline", ("", ""))[1]
    if not fingerprint:
        raise WriteBenchmarkError("source schema has no baseline fingerprint")
    return fingerprint


def _query_count(view: _TargetView, sql_text: str, parameters: tuple[Any, ...]) -> int:
    connection = view.connect()
    try:
        row = connection.execute(sql_text, parameters).fetchone()
        return int(row[0]) if row is not None else 0
    finally:
        connection.close()


def _run_checkout(view: _TargetView, config: RunConfig, benchmark_module) -> dict[str, Any]:
    before = view.connections_opened

    def operation(_connection, _worker: int, _sequence: int) -> None:
        checkout = view.connect()
        checkout.close()

    metrics = benchmark_module.run_concurrent(
        _DummyConnection,
        operation,
        concurrency=config.concurrency,
        warmups=config.warmups,
        iterations=config.iterations,
    )
    opened = view.connections_opened - before
    expected = config.total_calls
    return {
        "metrics": metrics,
        "audit": {
            "connections_opened": opened,
            "expected_connections_opened": expected,
            "passed": opened == expected,
        },
    }


def _run_job_identity(
    view: _TargetView,
    config: RunConfig,
    benchmark_module,
    *,
    label: str,
) -> dict[str, Any]:
    prefix = f"__ab_{label}_{uuid.uuid4().hex}"
    total = config.total_calls

    def operation(connection, worker: int, sequence: int) -> None:
        key = f"{prefix}:{worker}:{sequence}:{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        db.upsert_crawl_job(
            connection,
            job_id=key,
            site_name="writebench",
            job_type="seed",
            queue_name="seed",
            target="writebench",
            status="running",
            started_at=now,
        )
        connection.commit()
        db.upsert_crawl_job(
            connection,
            job_id=key,
            site_name="writebench",
            job_type="seed",
            queue_name="seed",
            target="writebench",
            status="succeeded",
            finished_at=now,
            duration_ms=1,
            error_message=None,
        )
        connection.commit()

    metrics = benchmark_module.run_concurrent(
        view.connect,
        operation,
        concurrency=config.concurrency,
        warmups=config.warmups,
        iterations=config.iterations,
    )
    count = _query_count(
        view,
        "SELECT COUNT(*) FROM crawl_jobs WHERE SUBSTR(job_id, 1, ?) = ?",
        (len(prefix), prefix),
    )
    return {
        "metrics": metrics,
        "audit": {
            "rows": count,
            "expected_rows": total,
            "two_commits_per_job": True,
            "same_single_session_connector": True,
            "passed": count == total,
        },
    }


def _run_claim(
    view: _TargetView,
    config: RunConfig,
    benchmark_module,
    *,
    label: str,
    legacy: bool,
) -> dict[str, Any]:
    prefix = f"__ab_{label}_{uuid.uuid4().hex}"
    paths = LegacyPostgresPaths() if legacy else ProductionPaths()
    total = config.total_calls
    outcomes = {"true": 0, "false": 0}
    outcome_lock = Lock()

    def operation(connection, worker: int, sequence: int) -> None:
        key = f"{prefix}:{worker}:{sequence}:{uuid.uuid4().hex}"
        created = datetime.now(timezone.utc).isoformat()
        first = paths.claim(connection, key, key, created)
        connection.commit()
        second = paths.claim(connection, key, key, created + "-conflict")
        connection.commit()
        paths.release(connection, key, key)
        connection.commit()
        with outcome_lock:
            outcomes["true" if first else "false"] += 1
            outcomes["true" if second else "false"] += 1

    metrics = benchmark_module.run_concurrent(
        view.connect,
        operation,
        concurrency=config.concurrency,
        warmups=config.warmups,
        iterations=config.iterations,
    )
    remaining = _query_count(
        view,
        "SELECT COUNT(*) FROM ai_aggregation_schedule_claims "
        "WHERE SUBSTR(profile_id, 1, ?) = ?",
        (len(prefix), prefix),
    )
    expected = {"true": total, "false": total}
    return {
        "metrics": metrics,
        "audit": {
            "outcomes": outcomes,
            "expected_outcomes": expected,
            "remaining_rows": remaining,
            "same_single_session_connector": True,
            "passed": outcomes == expected and remaining == 0,
        },
    }



def _configure_job_index(target: PostgresTarget, variant: str) -> dict[str, str]:
    """Install one compared crawl_jobs index, or drop the known-wrong one."""

    if variant not in {"old_index", "new_index", "drop_only"}:
        raise WriteBenchmarkError(f"unknown crawl_jobs index variant: {variant}")
    close_postgres_pools()
    _, sql = _driver()
    connection = _connect_raw(target.migration_url, "dwti-ablation-index-ddl")
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            schema = sql.Identifier(target.schema)
            cursor.execute(
                sql.SQL("DROP INDEX IF EXISTS {}.{}").format(
                    schema, sql.Identifier(OLD_JOB_INDEX)
                )
            )
            cursor.execute(
                sql.SQL("DROP INDEX IF EXISTS {}.{}").format(
                    schema, sql.Identifier(NEW_JOB_INDEX)
                )
            )
            if variant == "old_index":
                cursor.execute(
                    sql.SQL(
                        "CREATE INDEX {} ON {}.crawl_jobs(status, enqueued_at, id) "
                        "WHERE status IN ('queued', 'running')"
                    ).format(sql.Identifier(OLD_JOB_INDEX), schema)
                )
            elif variant == "new_index":
                cursor.execute(
                    sql.SQL(
                        "CREATE INDEX {} ON {}.crawl_jobs("
                        "site_name, job_type, "
                        "COALESCE(started_at, enqueued_at) DESC, id DESC"
                        ") WHERE status IN ('enqueued', 'running')"
                    ).format(sql.Identifier(NEW_JOB_INDEX), schema)
                )
            cursor.execute(sql.SQL("ANALYZE {}.crawl_jobs").format(schema))
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname=%s AND tablename='crawl_jobs'
                  AND indexname IN (%s, %s)
                ORDER BY indexname
                """,
                (target.schema, OLD_JOB_INDEX, NEW_JOB_INDEX),
            )
            definitions = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
        connection.commit()
        return definitions
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _analyze_crawl_jobs(target: PostgresTarget) -> None:
    close_postgres_pools()
    _, sql = _driver()
    connection = _connect_raw(target.migration_url, "dwti-ablation-index-analyze")
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ANALYZE {}.crawl_jobs").format(sql.Identifier(target.schema))
            )
    finally:
        connection.close()


def _plan_index_names(value: Any) -> list[str]:
    names: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            name = item.get("Index Name")
            if name:
                names.add(str(name))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(names)


def _seed_and_explain_active_query(
    view: _TargetView,
    *,
    explain_rows: int,
) -> dict[str, Any]:
    prefix = f"__ab_explain_{uuid.uuid4().hex}"
    site_count = max(16, min(128, max(explain_rows // 4, 1)))
    timestamp = datetime.now(timezone.utc).isoformat()
    connection = view.connect()
    try:
        for index in range(explain_rows):
            status = "enqueued" if index % 2 == 0 else "running"
            db.upsert_crawl_job(
                connection,
                job_id=f"{prefix}:{index}",
                site_name=f"{prefix}:site:{index % site_count}",
                job_type="seed",
                queue_name="seed",
                target="writebench",
                status=status,
                enqueued_at=timestamp,
                started_at=timestamp if status == "running" else None,
            )
        connection.commit()
    finally:
        connection.close()

    _analyze_crawl_jobs(view.target)
    connection = view.connect()
    try:
        row = connection.execute(
            """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT job_id, status, queue_name, target, started_at, enqueued_at,
                   finished_at, error_message
            FROM crawl_jobs
            WHERE site_name=? AND job_type=?
              AND status IN ('enqueued', 'running')
            ORDER BY COALESCE(started_at, enqueued_at) DESC
            LIMIT 1
            """,
            (f"{prefix}:site:0", "seed"),
        ).fetchone()
        if row is None:
            raise WriteBenchmarkError("active-job EXPLAIN returned no plan")
        plan = row[0]
        if isinstance(plan, str):
            plan = json.loads(plan)
    finally:
        connection.close()
    return {
        "seed_rows": explain_rows,
        "natural_plan_index_names": _plan_index_names(plan),
        "plan": plan,
    }


def _run_job_index(
    target: PostgresTarget,
    variant: str,
    config: RunConfig,
    benchmark_module,
    *,
    explain_rows: int,
) -> dict[str, Any]:
    definitions = _configure_job_index(target, variant)
    view = _TargetView(target)
    result = _run_job_identity(
        view,
        config,
        benchmark_module,
        label=f"index_{variant}",
    )
    explain = _seed_and_explain_active_query(view, explain_rows=explain_rows)
    expected_name = (
        OLD_JOB_INDEX
        if variant == "old_index"
        else NEW_JOB_INDEX if variant == "new_index" else None
    )
    expected_names = set() if expected_name is None else {expected_name}
    layout_passed = set(definitions) == expected_names
    result["audit"].update({
        "same_single_session_connector": True,
        "no_identity_returning": True,
        "index_definitions": definitions,
        "expected_index_name": expected_name,
        "index_layout_passed": layout_passed,
        "active_query_explain": explain,
        "passed": bool(result["audit"]["passed"] and layout_passed),
    })
    return result


_RECENCY_READ_QUERIES = {
    "jobs_payload_300": """
        SELECT site_name, job_type, status, queue_name, target,
               enqueued_at, started_at, finished_at, error_message
        FROM crawl_jobs
        ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
        LIMIT 300
    """,
    "intelligence_payload_100": """
        SELECT site_name, job_type, status, target,
               enqueued_at, started_at, finished_at, error_message
        FROM crawl_jobs
        ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
        LIMIT 100
    """,
    "list_crawl_jobs_20": """
        SELECT job_id, site_name, job_type, queue_name, target, status,
               enqueued_at, started_at, finished_at, duration_ms, error_message
        FROM crawl_jobs
        ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
        LIMIT 20
    """,
    "latest_job_marker": """
        SELECT MAX(COALESCE(finished_at, started_at, enqueued_at)) AS latest
        FROM crawl_jobs
    """,
}


def _rows_hash(rows: list[Any]) -> str:
    payload = json.dumps(
        [list(row) for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _configure_recency_job_index(
    target: PostgresTarget,
    variant: str,
) -> dict[str, str]:
    if variant not in {"without_recency_index", "recency_index"}:
        raise WriteBenchmarkError(f"unknown recency index variant: {variant}")
    close_postgres_pools()
    _, sql = _driver()
    connection = _connect_raw(target.migration_url, "dwti-recency-index-ddl")
    connection.autocommit = False
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname=%s AND tablename='crawl_jobs' ORDER BY indexname",
                (target.schema,),
            )
            before = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
            equivalent = {
                name: definition for name, definition in before.items()
                if "coalesce(finished_at, started_at, enqueued_at)" in definition.lower()
            }
            if equivalent:
                raise WriteBenchmarkError(
                    "source clone already has recency index: " + ",".join(sorted(equivalent))
                )
            if variant == "recency_index":
                cursor.execute(
                    sql.SQL(
                        "CREATE INDEX {} ON {}.crawl_jobs "
                        "((COALESCE(finished_at, started_at, enqueued_at)) DESC)"
                    ).format(
                        sql.Identifier(RECENCY_JOB_INDEX),
                        sql.Identifier(target.schema),
                    )
                )
            cursor.execute(
                sql.SQL("ANALYZE {}.crawl_jobs").format(sql.Identifier(target.schema))
            )
            cursor.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname=%s AND tablename='crawl_jobs' ORDER BY indexname",
                (target.schema,),
            )
            definitions = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
        connection.commit()
        return definitions
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _explain_recency_query(view: _TargetView, query: str) -> dict[str, Any]:
    connection = view.connect()
    try:
        row = connection.execute(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query
        ).fetchone()
        if row is None:
            raise WriteBenchmarkError("recency EXPLAIN returned no plan")
        plan = row[0]
        if isinstance(plan, str):
            plan = json.loads(plan)
        return {
            "natural_plan_index_names": _plan_index_names(plan),
            "plan": plan,
        }
    finally:
        connection.close()


def _run_recency_read(
    view: _TargetView,
    config: RunConfig,
    benchmark_module,
    query: str,
) -> dict[str, Any]:
    hashes: set[str] = set()
    hashes_lock = Lock()

    def operation(connection, _worker: int, _sequence: int) -> None:
        output_hash = _rows_hash(connection.execute(query).fetchall())
        with hashes_lock:
            hashes.add(output_hash)

    metrics = benchmark_module.run_concurrent(
        view.connect,
        operation,
        concurrency=1,
        warmups=config.warmups,
        iterations=config.iterations,
    )
    return {
        "metrics": metrics,
        "output_hashes": sorted(hashes),
        "stable_output": len(hashes) == 1,
        "explain_analyze_buffers": _explain_recency_query(view, query),
    }


def _seed_and_audit_recency_ties(view: _TargetView) -> dict[str, Any]:
    prefix = "__ab_recency_tie__"
    timestamp = "2100-01-01T00:00:00+00:00"
    connection = view.connect()
    try:
        for index in range(384):
            db.upsert_crawl_job(
                connection,
                job_id=f"{prefix}:{index:05d}",
                site_name=prefix,
                job_type="tie_audit",
                queue_name="tie_audit",
                target=f"{prefix}:target:{index:05d}",
                status="succeeded",
                enqueued_at=timestamp,
                started_at=timestamp,
                finished_at=timestamp,
                duration_ms=1,
                error_message=None,
            )
        connection.commit()
    finally:
        connection.close()
    _analyze_crawl_jobs(view.target)

    audits: dict[str, Any] = {}
    for limit in (20, 300):
        query = f"""
            SELECT site_name, job_type, status, queue_name, target,
                   enqueued_at, started_at, finished_at, error_message
            FROM crawl_jobs
            ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
            LIMIT {limit}
        """
        connection = view.connect()
        try:
            results = [connection.execute(query).fetchall() for _ in range(20)]
        finally:
            connection.close()
        hashes = [_rows_hash(rows) for rows in results]
        canonical_set = sorted(
            json.dumps(list(row), ensure_ascii=False, default=str, separators=(",", ":"))
            for row in results[0]
        )
        audits[f"limit_{limit}"] = {
            "ordered_output_hash": hashes[0],
            "row_set_hash": hashlib.sha256(
                json.dumps(canonical_set, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "stable_across_20_repeats": len(set(hashes)) == 1,
            "first_targets": [str(row[4]) for row in results[0][:10]],
            "last_targets": [str(row[4]) for row in results[0][-10:]],
            "all_rows_are_seed_ties": all(
                str(row[4]).startswith(prefix) for row in results[0]
            ),
            "explain_analyze_buffers": _explain_recency_query(view, query),
        }

    connection = view.connect()
    try:
        cursor = connection.execute(
            "DELETE FROM crawl_jobs WHERE SUBSTR(job_id, 1, ?) = ?",
            (len(prefix), prefix),
        )
        deleted = int(cursor.rowcount)
        connection.commit()
    finally:
        connection.close()
    _analyze_crawl_jobs(view.target)
    audits["deleted_rows"] = deleted
    return audits


def _run_job_read_index(
    target: PostgresTarget,
    variant: str,
    config: RunConfig,
    benchmark_module,
) -> dict[str, Any]:
    definitions = _configure_recency_job_index(target, variant)
    view = _TargetView(target)
    reads = {
        name: _run_recency_read(view, config, benchmark_module, query)
        for name, query in _RECENCY_READ_QUERIES.items()
    }
    ties = _seed_and_audit_recency_ties(view)
    result = _run_job_identity(
        view,
        config,
        benchmark_module,
        label=f"recency_{variant}",
    )
    expected_index = variant == "recency_index"
    layout_passed = (RECENCY_JOB_INDEX in definitions) is expected_index
    read_errors = sum(item["metrics"]["errors"] for item in reads.values())
    tie_passed = all(
        ties[f"limit_{limit}"]["stable_across_20_repeats"]
        and ties[f"limit_{limit}"]["all_rows_are_seed_ties"]
        for limit in (20, 300)
    )
    result["read_queries"] = reads
    result["same_timestamp_ordering"] = ties
    result["audit"].update({
        "index_definitions": definitions,
        "expected_recency_index": expected_index,
        "index_layout_passed": layout_passed,
        "production_read_errors": read_errors,
        "production_read_outputs_stable": all(
            item["stable_output"] for item in reads.values()
        ),
        "same_timestamp_local_stability": tie_passed,
        "tie_rows_deleted": ties["deleted_rows"],
        "expected_tie_rows_deleted": 384,
        "same_single_session_connector": True,
        "no_identity_returning": True,
        "passed": bool(
            result["audit"]["passed"]
            and layout_passed
            and read_errors == 0
            and tie_passed
            and ties["deleted_rows"] == 384
        ),
    })
    return result


def _run_variant(
    ablation: str,
    variant: str,
    target: PostgresTarget,
    config: RunConfig,
    benchmark_module,
    *,
    explain_rows: int,
) -> dict[str, Any]:
    if ablation == "checkout_session":
        view = _TargetView(target, extra_session=variant == "double_session")
        return _run_checkout(view, config, benchmark_module)
    if ablation == "job_identity":
        view = _TargetView(target, auto_identity=variant == "auto_returning")
        return _run_job_identity(view, config, benchmark_module, label=variant)
    if ablation == "claim_sql":
        view = _TargetView(target)
        return _run_claim(
            view,
            config,
            benchmark_module,
            label=variant,
            legacy=variant == "exception_rollback",
        )
    if ablation in {"crawl_jobs_index", "crawl_jobs_drop_wrong"}:
        return _run_job_index(
            target,
            variant,
            config,
            benchmark_module,
            explain_rows=explain_rows,
        )
    if ablation == "crawl_jobs_read_index":
        return _run_job_read_index(
            target,
            variant,
            config,
            benchmark_module,
        )
    raise WriteBenchmarkError(f"unknown ablation: {ablation}")


def _pair_targets(
    stack: ExitStack,
    *,
    migration_url: str,
    runtime_url: str,
    source_schema: str,
    fingerprint: str,
    registry: CleanupRegistry,
) -> dict[str, PostgresTarget]:
    return {
        role: stack.enter_context(PostgresTarget(
            migration_url=migration_url,
            runtime_url=runtime_url,
            source_schema=source_schema,
            variant="baseline",
            fingerprint=fingerprint,
            registry=registry,
        ))
        for role in ("baseline", "candidate")
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    source_schema = _source_identifier(args.source_schema, "--source-schema")
    migration_url, runtime_url, config_source = load_database_urls(args)
    config = RunConfig(
        concurrency=args.concurrency,
        warmups=args.warmups,
        iterations=args.iterations,
        rounds=args.rounds,
        batch_size=1,
    )
    current_pool_max = int(os.environ.get("DARKWEB_POSTGRES_POOL_MAX", "4"))
    os.environ["DARKWEB_POSTGRES_POOL_MIN"] = "1"
    os.environ["DARKWEB_POSTGRES_POOL_MAX"] = str(max(current_pool_max, config.concurrency + 4))
    progress = lambda message: print(
        f"[write-ablation] {message}", file=sys.stderr, flush=True
    )

    leftovers_before = list_disposable_schemas(migration_url)
    if leftovers_before:
        raise WriteBenchmarkError(
            "pre-existing disposable schemas require manual review; none were deleted: "
            + ", ".join(leftovers_before)
        )
    setup_info = connection_info(migration_url, "dwti-ablation-setup-info")
    runtime_info = connection_info(runtime_url, "dwti-ablation-runtime-info")
    if setup_info["database"] != runtime_info["database"]:
        raise WriteBenchmarkError("setup and runtime URLs point to different databases")
    if (
        setup_info["fsync"].lower() != "on"
        or setup_info["synchronous_commit"].lower() != "on"
        or runtime_info["synchronous_commit"].lower() != "on"
    ):
        raise WriteBenchmarkError("PostgreSQL durability settings must remain enabled")
    source_before = source_schema_snapshot(migration_url, source_schema)
    fingerprint = _source_fingerprint(source_before, args.source_version)
    benchmark_module = _shared_benchmark_module()
    registry = CleanupRegistry()
    raw: dict[str, dict[str, list[dict[str, Any]]]] = {
        ablation: {variant: [] for variant in VARIANTS[ablation]}
        for ablation in args.ablations
    }
    order_log: list[dict[str, Any]] = []

    try:
        for round_index in range(config.rounds):
            for ablation_index, ablation in enumerate(args.ablations):
                baseline_variant, candidate_variant = VARIANTS[ablation]
                role_order = variant_order(round_index, ablation_index)
                order_log.append({
                    "round": round_index + 1,
                    "ablation": ablation,
                    "variant_order": [
                        baseline_variant if role == "baseline" else candidate_variant
                        for role in role_order
                    ],
                })
                progress(
                    f"round {round_index + 1}/{config.rounds} {ablation}: "
                    + " -> ".join(order_log[-1]["variant_order"])
                )
                with ExitStack() as stack:
                    targets = _pair_targets(
                        stack,
                        migration_url=migration_url,
                        runtime_url=runtime_url,
                        source_schema=source_schema,
                        fingerprint=fingerprint,
                        registry=registry,
                    )
                    for role in role_order:
                        variant = baseline_variant if role == "baseline" else candidate_variant
                        raw[ablation][variant].append(
                            _run_variant(
                                ablation,
                                variant,
                                targets[role],
                                config,
                                benchmark_module,
                                explain_rows=args.explain_rows,
                            )
                        )
    finally:
        close_postgres_pools()

    leftovers_after = list_disposable_schemas(migration_url)
    source_after = source_schema_snapshot(migration_url, source_schema)
    records = registry.snapshot()
    results = {
        ablation: {
            variant: _median_summary(rounds)
            for variant, rounds in variants.items()
        }
        for ablation, variants in raw.items()
    }
    comparisons: dict[str, Any] = {}
    for ablation, (baseline_variant, candidate_variant) in VARIANTS.items():
        if ablation not in results:
            continue
        baseline = results[ablation][baseline_variant]
        candidate = results[ablation][candidate_variant]
        comparisons[ablation] = {
            "baseline_variant": baseline_variant,
            "candidate_variant": candidate_variant,
            "baseline_tps": baseline["median_tps"],
            "candidate_tps": candidate["median_tps"],
            "tps_ratio": round(
                candidate["median_tps"] / baseline["median_tps"], 6
            ) if baseline["median_tps"] else 0.0,
            "baseline_p95_ms": baseline["median_p95_ms"],
            "candidate_p95_ms": candidate["median_p95_ms"],
            "p95_ratio": round(
                candidate["median_p95_ms"] / baseline["median_p95_ms"], 6
            ) if baseline["median_p95_ms"] else 0.0,
            "errors": baseline["errors"] + candidate["errors"],
            "audits_passed": all(
                item["audit"].get("passed") is True
                for summary in (baseline, candidate)
                for item in summary["round_results"]
            ),
        }
    cleanup = {
        "created": sum(1 for item in records if item.get("created")),
        "dropped": sum(1 for item in records if item.get("dropped")),
        "records": records,
        "leftovers": leftovers_after,
    }
    return {
        "format": "dwti-postgres-write-ablation",
        "format_version": 1,
        "generated_at": _utc_now(),
        "parameters": {
            "source_schema": source_schema,
            "source_version": args.source_version,
            "concurrency": config.concurrency,
            "warmups_per_worker": config.warmups,
            "iterations_per_worker": config.iterations,
            "rounds": config.rounds,
            "explain_rows": args.explain_rows,
            "ablations": list(args.ablations),
            "source_schema_written": False,
        },
        "connection": {
            "config_source": config_source,
            "setup": setup_info,
            "runtime": runtime_info,
            "pool_min": int(os.environ["DARKWEB_POSTGRES_POOL_MIN"]),
            "pool_max": int(os.environ["DARKWEB_POSTGRES_POOL_MAX"]),
            "credentials_in_report": False,
        },
        "durability": {"postgresql": "fsync=on,synchronous_commit=on"},
        "source_integrity": {
            "passed": source_before["sha256"] == source_after["sha256"],
            "sha256_before": source_before["sha256"],
            "sha256_after": source_after["sha256"],
        },
        "results": results,
        "comparisons": comparisons,
        "round_order": order_log,
        "temporary_schemas": cleanup,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated PostgreSQL write-candidate ablations",
    )
    parser.add_argument("--source-schema", required=True)
    parser.add_argument("--source-version", default=BASELINE_VERSION)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--postgres-config",
        type=Path,
        default=Path.home() / ".local/share/darkweb-threat-intel/postgresql-target.json",
    )
    parser.add_argument("--migration-url")
    parser.add_argument("--runtime-url")
    parser.add_argument(
        "--ablations",
        type=_selected_ablations,
        default=ABLATIONS,
        help="comma-separated subset: " + ",".join(ABLATIONS),
    )
    parser.add_argument("--concurrency", type=_positive_int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--warmups", type=_non_negative_int, default=DEFAULT_WARMUPS)
    parser.add_argument("--iterations", type=_positive_int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--rounds", type=_positive_int, default=DEFAULT_ROUNDS)
    parser.add_argument("--explain-rows", type=_positive_int, default=512)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_benchmark(args)
        _write_json(args.output, report)
    except (WriteBenchmarkError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"[write-ablation] ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[write-ablation] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "output": str(args.output.expanduser().resolve()),
        "comparisons": report["comparisons"],
        "source_integrity": report["source_integrity"]["passed"],
        "temporary_schema_leftovers": report["temporary_schemas"]["leftovers"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
