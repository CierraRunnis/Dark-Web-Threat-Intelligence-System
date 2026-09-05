#!/usr/bin/env python3
"""Run an isolated SQLite/PostgreSQL A/B benchmark for migration acceptance.

The source SQLite database and PostgreSQL release schema are opened read-only.
The write benchmark uses a SQLite backup in a temporary directory and a random,
disposable PostgreSQL schema that is always dropped on exit.
"""

from __future__ import annotations

from collections import Counter
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import sys
import tempfile
from threading import Barrier, BrokenBarrierError
import time
from typing import Any, Callable, Sequence
import uuid
from zoneinfo import ZoneInfo


REPORT_FORMAT = "dwti-database-benchmark"
REPORT_VERSION = 1
DEFAULT_WARMUPS = 5
DEFAULT_ITERATIONS = 100
READ_CONCURRENCIES = (1, 8)
WRITE_CONCURRENCY = 8
SEARCH_PATTERN_SENTINEL = "__DWTI_DISCOVERED_SEARCH_PATTERN__"
WRITE_TABLES = (
    "crawl_jobs",
    "normalized_intelligence_cache_state",
    "ai_aggregation_schedule_claims",
)
WRITE_TRANSACTION_FLOOR = 800
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SHANGHAI = ZoneInfo("Asia/Shanghai")


class BenchmarkError(RuntimeError):
    """Raised when the benchmark cannot run safely or completely."""


@dataclass(frozen=True)
class Query:
    sql: str
    parameters: tuple[Any, ...] = ()


SCENARIOS: dict[str, tuple[Query, ...]] = {
    "dashboard_overview": (
        Query(
            """
            SELECT event_type, severity, COUNT(*) AS total,
                   ROUND(COALESCE(AVG(risk_score), 0), 4) AS avg_risk
            FROM normalized_intelligence_events
            GROUP BY event_type, severity
            ORDER BY total DESC, event_type ASC, severity ASC
            LIMIT 100
            """
        ),
    ),
    "intelligence_search": (
        Query(
            """
            SELECT event_id, event_type, severity, risk_score, title, victim,
                   COALESCE(NULLIF(disclosure_time, ''), updated_at) AS event_time
            FROM normalized_intelligence_events
            WHERE LOWER(
                COALESCE(title, '') || ' ' ||
                COALESCE(victim, '') || ' ' ||
                COALESCE(attacker, '') || ' ' ||
                COALESCE(detail_text, '')
            ) LIKE ?
            ORDER BY risk_score DESC,
                     COALESCE(NULLIF(disclosure_time, ''), updated_at) DESC,
                     event_id DESC
            LIMIT 100
            """,
            (SEARCH_PATTERN_SENTINEL,),
        ),
    ),
    "data_leak": (
        Query(
            """
            SELECT id, site_name, section, topic_url, content_hash, fetched_at
            FROM forum_details
            ORDER BY id DESC
            LIMIT 100
            """
        ),
    ),
    "ransomware_vulnerability": (
        Query(
            """
            SELECT victim_id, group_name, victim_name, country_code,
                   COALESCE(NULLIF(attacked_at, ''), discovered_at) AS event_time
            FROM ransomware_live_victims
            ORDER BY COALESCE(NULLIF(attacked_at, ''), discovered_at) DESC, victim_id DESC
            LIMIT 100
            """
        ),
        Query(
            """
            SELECT cve_id, severity, cvss, is_exploited, disclosure_time
            FROM vulnerability_records
            ORDER BY disclosure_time DESC, cve_id DESC
            LIMIT 100
            """
        ),
    ),
    "crawl_jobs": (
        Query(
            """
            SELECT job_id, site_name, job_type, queue_name, status,
                   started_at, finished_at, duration_ms
            FROM crawl_jobs
            ORDER BY id DESC
            LIMIT 100
            """
        ),
    ),
    "code_document_monitoring": (
        Query(
            """
            SELECT id, platform, repository_name, file_path, severity,
                   risk_score, last_seen_at
            FROM code_hits
            ORDER BY risk_score DESC, last_seen_at DESC, id DESC
            LIMIT 100
            """
        ),
        Query(
            """
            SELECT id, platform, platform_type, title, severity,
                   risk_score, last_seen_at
            FROM document_hits
            ORDER BY risk_score DESC, last_seen_at DESC, id DESC
            LIMIT 100
            """
        ),
    ),
    "ai_aggregation": (
        Query(
            """
            SELECT id, profile_id, profile_name, analysis_status,
                   delivery_status, queued_at, completed_at
            FROM ai_aggregation_runs
            ORDER BY queued_at DESC, id DESC
            LIMIT 100
            """
        ),
    ),
}


def _validate_identifier(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise BenchmarkError(f"{label} must match {IDENTIFIER_PATTERN.pattern}")
    return normalized


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return round(float(value), 12)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer():
            return int(value)
        return round(value, 12)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return {"$binary": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _summary(value: Any) -> dict[str, Any]:
    payload = _canonical_json(value).encode("utf-8")
    row_count = 0
    if isinstance(value, list):
        row_count = sum(
            len(item.get("rows", [])) if isinstance(item, dict) else 1
            for item in value
        )
    return {
        "rows": row_count,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _postgres_sql(sql_text: str) -> str:
    # The fixed benchmark SQL contains no literal question marks.
    return sql_text.replace("?", "%s")


class SQLiteReadBackend:
    name = "sqlite"

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser().resolve(strict=True)
        if not self.database_path.is_file():
            raise BenchmarkError(f"SQLite database is not a file: {self.database_path}")

    def connect(self) -> sqlite3.Connection:
        uri = self.database_path.as_uri() + "?mode=ro"
        connection = sqlite3.connect(
            uri,
            uri=True,
            timeout=30.0,
            check_same_thread=False,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection


class PostgreSQLReadBackend:
    name = "postgresql"

    def __init__(self, database_url: str, schema: str) -> None:
        self.database_url = str(database_url or "").strip()
        if not self.database_url.lower().startswith(("postgres://", "postgresql://")):
            raise BenchmarkError("--postgres-url must be a PostgreSQL URL")
        self.schema = _validate_identifier(schema, "--postgres-schema")
        try:
            import psycopg2  # type: ignore
            from psycopg2 import sql  # type: ignore
        except ImportError as exc:
            raise BenchmarkError("psycopg2 is required for PostgreSQL benchmarking") from exc
        self.psycopg2 = psycopg2
        self.sql = sql

    def _raw_connection(self, application_name: str):
        return self.psycopg2.connect(
            self.database_url,
            application_name=application_name,
            connect_timeout=15,
        )

    def connect(self):
        connection = self._raw_connection("dwti-benchmark-read")
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                self.sql.SQL("SET search_path TO {}, pg_catalog").format(
                    self.sql.Identifier(self.schema)
                )
            )
            cursor.execute("SET default_transaction_read_only = on")
        return connection


def execute_scenario(
    connection,
    backend_name: str,
    scenario: str,
    search_pattern: str = "%__dwti_search_unavailable__%",
) -> list[dict[str, Any]]:
    queries = SCENARIOS.get(scenario)
    if not queries:
        raise BenchmarkError(f"unknown benchmark scenario: {scenario}")
    results: list[dict[str, Any]] = []
    for query_index, query in enumerate(queries):
        cursor = connection.cursor()
        try:
            sql_text = _postgres_sql(query.sql) if backend_name == "postgresql" else query.sql
            parameters = tuple(
                search_pattern if value == SEARCH_PATTERN_SENTINEL else value
                for value in query.parameters
            )
            cursor.execute(sql_text, parameters)
            columns = [str(item[0]) for item in (cursor.description or ())]
            rows = [
                [_canonical_value(value) for value in row]
                for row in cursor.fetchall()
            ]
            results.append(
                {
                    "query": query_index,
                    "columns": columns,
                    "rows": rows,
                }
            )
        finally:
            cursor.close()
    return results


def _rollback_quietly(connection) -> None:
    try:
        connection.rollback()
    except Exception:
        pass


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _error_text(exc: BaseException) -> str:
    rendered = f"{type(exc).__name__}: {exc}".replace("\n", " ").strip()
    return rendered[:300]


def run_concurrent(
    connection_factory: Callable[[], Any],
    operation: Callable[[Any, int, int], Any],
    *,
    concurrency: int,
    warmups: int,
    iterations: int,
) -> dict[str, Any]:
    connections = []
    try:
        for _ in range(concurrency):
            connections.append(connection_factory())
    except Exception:
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
        raise
    barrier = Barrier(concurrency)

    def worker(worker_id: int, connection) -> dict[str, Any]:
        warmup_errors: list[str] = []
        measurement_errors: list[str] = []
        latencies: list[float] = []
        for sequence in range(warmups):
            try:
                operation(connection, worker_id, -(sequence + 1))
            except Exception as exc:
                _rollback_quietly(connection)
                warmup_errors.append(_error_text(exc))
        try:
            barrier.wait(timeout=120)
        except BrokenBarrierError as exc:
            return {
                "latencies": [],
                "warmup_errors": warmup_errors,
                "measurement_errors": [_error_text(exc)],
                "started": time.perf_counter(),
                "finished": time.perf_counter(),
            }

        started = time.perf_counter()
        for sequence in range(iterations):
            operation_started = time.perf_counter()
            try:
                operation(connection, worker_id, sequence)
            except Exception as exc:
                _rollback_quietly(connection)
                measurement_errors.append(_error_text(exc))
            else:
                latencies.append((time.perf_counter() - operation_started) * 1000.0)
        finished = time.perf_counter()
        return {
            "latencies": latencies,
            "warmup_errors": warmup_errors,
            "measurement_errors": measurement_errors,
            "started": started,
            "finished": finished,
        }

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(worker, worker_id, connection)
                for worker_id, connection in enumerate(connections)
            ]
            worker_results = [future.result() for future in futures]
    finally:
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass

    latencies = [
        latency
        for result in worker_results
        for latency in result["latencies"]
    ]
    warmup_errors = [
        error
        for result in worker_results
        for error in result["warmup_errors"]
    ]
    measurement_errors = [
        error
        for result in worker_results
        for error in result["measurement_errors"]
    ]
    started = min(result["started"] for result in worker_results)
    finished = max(result["finished"] for result in worker_results)
    elapsed = max(finished - started, 1e-9)
    successful_operations = len(latencies)
    all_errors = warmup_errors + measurement_errors
    return {
        "concurrency": concurrency,
        "warmups_per_worker": warmups,
        "iterations_per_worker": iterations,
        "attempted_operations": concurrency * iterations,
        "successful_operations": successful_operations,
        "p50_ms": round(_percentile(latencies, 0.50), 6),
        "p95_ms": round(_percentile(latencies, 0.95), 6),
        "throughput": round(successful_operations / elapsed, 6),
        "errors": len(all_errors),
        "measurement_errors": len(measurement_errors),
        "warmup_errors": len(warmup_errors),
        "error_samples": list(dict.fromkeys(all_errors))[:5],
        "elapsed_seconds": round(elapsed, 6),
    }


def discover_search_pattern(sqlite_backend: SQLiteReadBackend) -> str:
    connection = sqlite_backend.connect()
    try:
        cursor = connection.execute(
            """
            SELECT title, victim, attacker, detail_text
            FROM normalized_intelligence_events
            WHERE LENGTH(TRIM(COALESCE(title, ''))) > 0
            ORDER BY event_id ASC
            LIMIT 500
            """
        )
        counts: Counter[str] = Counter()
        token_pattern = re.compile(r"[A-Za-z0-9]{4,}|[\u4e00-\u9fff]{2,}")
        stop_words = {"http", "https", "data", "this", "that", "with", "from", "威胁情报", "数据泄露"}
        for row in cursor.fetchall():
            for value in row:
                for match in token_pattern.findall(str(value or "")):
                    token = match.casefold()
                    if token not in stop_words:
                        counts[token] += 1
    finally:
        connection.close()
    if not counts:
        raise BenchmarkError(
            "unable to discover a stable non-empty intelligence search term"
        )
    token = min(counts, key=lambda item: (counts[item], -len(item), item))
    return f"%{token}%"

def benchmark_reads(
    sqlite_backend: SQLiteReadBackend,
    postgres_backend: PostgreSQLReadBackend,
    *,
    warmups: int,
    iterations: int,
    search_pattern: str,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        for concurrency in READ_CONCURRENCIES:
            if progress:
                progress(f"read {scenario} concurrency={concurrency}: SQLite")
            sqlite_metrics = run_concurrent(
                sqlite_backend.connect,
                lambda connection, _worker, _sequence: execute_scenario(
                    connection, "sqlite", scenario, search_pattern
                ),
                concurrency=concurrency,
                warmups=warmups,
                iterations=iterations,
            )
            if progress:
                progress(f"read {scenario} concurrency={concurrency}: PostgreSQL")
            postgres_metrics = run_concurrent(
                postgres_backend.connect,
                lambda connection, _worker, _sequence: execute_scenario(
                    connection, "postgresql", scenario, search_pattern
                ),
                concurrency=concurrency,
                warmups=warmups,
                iterations=iterations,
            )
            results.append(
                {
                    "scenario": scenario,
                    "concurrency": concurrency,
                    "sqlite_p50_ms": sqlite_metrics["p50_ms"],
                    "sqlite_p95_ms": sqlite_metrics["p95_ms"],
                    "sqlite_throughput": sqlite_metrics["throughput"],
                    "postgres_p50_ms": postgres_metrics["p50_ms"],
                    "postgres_p95_ms": postgres_metrics["p95_ms"],
                    "postgres_throughput": postgres_metrics["throughput"],
                    "errors": sqlite_metrics["errors"] + postgres_metrics["errors"],
                    "sqlite": sqlite_metrics,
                    "postgres": postgres_metrics,
                }
            )
    return results


class SQLiteWriteTarget(AbstractContextManager):
    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path.expanduser().resolve(strict=True)
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.database_path: Path | None = None

    def __enter__(self) -> "SQLiteWriteTarget":
        self._temporary = tempfile.TemporaryDirectory(prefix="dwti-sqlite-benchmark-")
        self.database_path = Path(self._temporary.name) / "collector-benchmark.db"
        source = sqlite3.connect(
            self.source_path.as_uri() + "?mode=ro",
            uri=True,
            timeout=30.0,
        )
        destination = sqlite3.connect(self.database_path)
        try:
            source.backup(destination, pages=4096, sleep=0.01)
            destination.execute("PRAGMA journal_mode=WAL")
            destination.execute("PRAGMA synchronous=FULL")
            destination.execute("PRAGMA busy_timeout=30000")
            existing = {
                str(row[0])
                for row in destination.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            missing = sorted(set(WRITE_TABLES) - existing)
            if missing:
                raise BenchmarkError(
                    "SQLite benchmark copy is missing required write tables: "
                    + ", ".join(missing)
                )
            destination.commit()
        finally:
            source.close()
            destination.close()
        return self

    def connect(self) -> sqlite3.Connection:
        if self.database_path is None:
            raise BenchmarkError("SQLite write target is not active")
        connection = sqlite3.connect(
            self.database_path,
            timeout=30.0,
            check_same_thread=False,
        )
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def operation(self, connection: sqlite3.Connection, worker_id: int, sequence: int) -> None:
        benchmark_key = f"__dwti_benchmark__:{worker_id}:{sequence}:{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO crawl_jobs (
                    job_id, site_name, job_type, queue_name, target, status,
                    enqueued_at, started_at, finished_at, duration_ms, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status,
                    started_at=excluded.started_at,
                    error_message=NULL
                """,
                (benchmark_key, "__benchmark__", "composite_write", "benchmark",
                 benchmark_key, "running", now, now),
            )
            connection.execute(
                "SELECT id, status FROM crawl_jobs WHERE job_id=?",
                (benchmark_key,),
            ).fetchone()
            connection.execute(
                "UPDATE crawl_jobs SET status='completed', finished_at=?, duration_ms=1 "
                "WHERE job_id=?",
                (now, benchmark_key),
            )
            connection.execute(
                """
                INSERT INTO normalized_intelligence_cache_state (
                    id, source_signature, event_count, refreshed_at,
                    source_revision, applied_revision, dirty_since, dirty_at,
                    last_started_at, last_finished_at, last_error,
                    last_error_at, normalization_version
                )
                VALUES (1, ?, 0, ?, 1, 0, ?, ?, '', '', '', '', 'benchmark')
                ON CONFLICT(id) DO UPDATE SET
                    source_signature=excluded.source_signature,
                    source_revision=normalized_intelligence_cache_state.source_revision + 1,
                    dirty_since=excluded.dirty_since,
                    dirty_at=excluded.dirty_at
                """,
                (benchmark_key, now, now, now),
            )
            connection.execute(
                """
                INSERT INTO ai_aggregation_schedule_claims (
                    profile_id, scheduled_for, created_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(profile_id, scheduled_for) DO UPDATE SET
                    created_at=excluded.created_at
                """,
                (benchmark_key, benchmark_key, now),
            )
            connection.execute(
                "SELECT created_at FROM ai_aggregation_schedule_claims "
                "WHERE profile_id=? AND scheduled_for=?",
                (benchmark_key, benchmark_key),
            ).fetchone()
            connection.execute(
                "DELETE FROM ai_aggregation_schedule_claims "
                "WHERE profile_id=? AND scheduled_for=?",
                (benchmark_key, benchmark_key),
            )
            connection.execute(
                "DELETE FROM crawl_jobs WHERE job_id=?",
                (benchmark_key,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._temporary is not None:
            self._temporary.cleanup()
        self.database_path = None
        return False


class PostgreSQLWriteTarget(AbstractContextManager):
    def __init__(self, backend: PostgreSQLReadBackend) -> None:
        self.backend = backend
        self.schema = f"dwti_bench_{uuid.uuid4().hex[:20]}"
        self._created = False

    def __enter__(self) -> "PostgreSQLWriteTarget":
        connection = self.backend._raw_connection("dwti-benchmark-setup")
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    self.backend.sql.SQL("CREATE SCHEMA {}").format(
                        self.backend.sql.Identifier(self.schema)
                    )
                )
                self._created = True
                for table_name in WRITE_TABLES:
                    cursor.execute(
                        self.backend.sql.SQL(
                            "CREATE TABLE {}.{} "
                            "(LIKE {}.{} INCLUDING ALL)"
                        ).format(
                            self.backend.sql.Identifier(self.schema),
                            self.backend.sql.Identifier(table_name),
                            self.backend.sql.Identifier(self.backend.schema),
                            self.backend.sql.Identifier(table_name),
                        )
                    )
        except Exception as setup_error:
            if self._created:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            self.backend.sql.SQL("DROP SCHEMA {} CASCADE").format(
                                self.backend.sql.Identifier(self.schema)
                            )
                        )
                except Exception as cleanup_error:
                    raise BenchmarkError(
                        f"failed to clean up PostgreSQL benchmark setup: {cleanup_error}"
                    ) from setup_error
                finally:
                    self._created = False
            raise
        finally:
            connection.close()
        return self

    def connect(self):
        connection = self.backend._raw_connection("dwti-benchmark-write")
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute(
                self.backend.sql.SQL("SET search_path TO {}, pg_catalog").format(
                    self.backend.sql.Identifier(self.schema)
                )
            )
            cursor.execute("SET synchronous_commit = on")
        connection.commit()
        return connection

    def operation(self, connection, worker_id: int, sequence: int) -> None:
        benchmark_key = f"__dwti_benchmark__:{worker_id}:{sequence}:{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).isoformat()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO crawl_jobs (
                        job_id, site_name, job_type, queue_name, target, status,
                        enqueued_at, started_at, finished_at, duration_ms, error_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL)
                    ON CONFLICT(job_id) DO UPDATE SET
                        status=EXCLUDED.status,
                        started_at=EXCLUDED.started_at,
                        error_message=NULL
                    """,
                    (benchmark_key, "__benchmark__", "composite_write", "benchmark",
                     benchmark_key, "running", now, now),
                )
                cursor.execute(
                    "SELECT id, status FROM crawl_jobs WHERE job_id=%s",
                    (benchmark_key,),
                )
                cursor.fetchone()
                cursor.execute(
                    "UPDATE crawl_jobs SET status='completed', finished_at=%s, duration_ms=1 "
                    "WHERE job_id=%s",
                    (now, benchmark_key),
                )
                cursor.execute(
                    """
                    INSERT INTO normalized_intelligence_cache_state (
                        id, source_signature, event_count, refreshed_at,
                        source_revision, applied_revision, dirty_since, dirty_at,
                        last_started_at, last_finished_at, last_error,
                        last_error_at, normalization_version
                    )
                    VALUES (1, %s, 0, %s, 1, 0, %s, %s, '', '', '', '', 'benchmark')
                    ON CONFLICT(id) DO UPDATE SET
                        source_signature=EXCLUDED.source_signature,
                        source_revision=normalized_intelligence_cache_state.source_revision + 1,
                        dirty_since=EXCLUDED.dirty_since,
                        dirty_at=EXCLUDED.dirty_at
                    """,
                    (benchmark_key, now, now, now),
                )
                cursor.execute(
                    """
                    INSERT INTO ai_aggregation_schedule_claims (
                        profile_id, scheduled_for, created_at
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT(profile_id, scheduled_for) DO UPDATE SET
                        created_at=EXCLUDED.created_at
                    """,
                    (benchmark_key, benchmark_key, now),
                )
                cursor.execute(
                    "SELECT created_at FROM ai_aggregation_schedule_claims "
                    "WHERE profile_id=%s AND scheduled_for=%s",
                    (benchmark_key, benchmark_key),
                )
                cursor.fetchone()
                cursor.execute(
                    "DELETE FROM ai_aggregation_schedule_claims "
                    "WHERE profile_id=%s AND scheduled_for=%s",
                    (benchmark_key, benchmark_key),
                )
                cursor.execute(
                    "DELETE FROM crawl_jobs WHERE job_id=%s",
                    (benchmark_key,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if not self._created:
            return False
        cleanup_error: Exception | None = None
        connection = None
        try:
            connection = self.backend._raw_connection("dwti-benchmark-cleanup")
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    self.backend.sql.SQL("DROP SCHEMA {} CASCADE").format(
                        self.backend.sql.Identifier(self.schema)
                    )
                )
        except Exception as exc:
            cleanup_error = exc
        finally:
            if connection is not None:
                connection.close()
        if cleanup_error is not None and exc_type is None:
            raise BenchmarkError(
                f"failed to drop disposable PostgreSQL schema {self.schema}: {cleanup_error}"
            ) from cleanup_error
        return False


def benchmark_writes(
    sqlite_backend: SQLiteReadBackend,
    postgres_backend: PostgreSQLReadBackend,
    *,
    warmups: int,
    iterations: int,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if progress:
        progress("write concurrency=8: temporary SQLite backup")
    with SQLiteWriteTarget(sqlite_backend.database_path) as sqlite_target:
        sqlite_metrics = run_concurrent(
            sqlite_target.connect,
            sqlite_target.operation,
            concurrency=WRITE_CONCURRENCY,
            warmups=warmups,
            iterations=iterations,
        )

    if progress:
        progress("write concurrency=8: disposable PostgreSQL schema")
    with PostgreSQLWriteTarget(postgres_backend) as postgres_target:
        postgres_metrics = run_concurrent(
            postgres_target.connect,
            postgres_target.operation,
            concurrency=WRITE_CONCURRENCY,
            warmups=warmups,
            iterations=iterations,
        )

    transactions = WRITE_CONCURRENCY * iterations
    return {
        "sqlite_tps": sqlite_metrics["throughput"],
        "postgres_tps": postgres_metrics["throughput"],
        "transactions": transactions,
        "errors": sqlite_metrics["errors"] + postgres_metrics["errors"],
        "sqlite_p50_ms": sqlite_metrics["p50_ms"],
        "sqlite_p95_ms": sqlite_metrics["p95_ms"],
        "postgres_p50_ms": postgres_metrics["p50_ms"],
        "postgres_p95_ms": postgres_metrics["p95_ms"],
        "sqlite": sqlite_metrics,
        "postgres": postgres_metrics,
        "isolated_targets": {
            "sqlite": "temporary_backup",
            "postgresql": "disposable_schema",
        },
    }


def _parse_datetime(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI).isoformat()


def _collect_country_values(value: Any, result: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).replace("-", "_").casefold()
            if normalized_key in {
                "country",
                "countries",
                "country_code",
                "country_codes",
                "countrycode",
            }:
                result.append(_canonical_json(item))
            _collect_country_values(item, result)
    elif isinstance(value, list):
        for item in value:
            _collect_country_values(item, result)


def semantic_snapshot(
    backend: SQLiteReadBackend | PostgreSQLReadBackend,
    search_pattern: str,
) -> dict[str, Any]:
    connection = backend.connect()
    try:
        scenario_summaries = {
            scenario: _summary(execute_scenario(connection, backend.name, scenario, search_pattern))
            for scenario in SCENARIOS
        }
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT event_id, title, victim, attacker, event_metadata_json,
                       disclosure_time, risk_score
                FROM normalized_intelligence_events
                ORDER BY risk_score DESC, disclosure_time DESC, event_id DESC
                LIMIT 200
                """
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()

        event_ids: list[str] = []
        casefold_values: list[str] = []
        country_values: list[str] = []
        shanghai_times: list[str] = []
        for row in rows:
            event_ids.append(str(row[0] or ""))
            casefold_values.extend(
                str(value or "").casefold()
                for value in row[1:4]
            )
            try:
                metadata = json.loads(str(row[4] or "{}"))
            except (TypeError, ValueError):
                metadata = {"$invalid_json": str(row[4] or "")}
            _collect_country_values(metadata, country_values)
            shanghai_times.append(_parse_datetime(row[5]))

        count_cursor = connection.cursor()
        try:
            count_cursor.execute("SELECT COUNT(*) FROM normalized_intelligence_events")
            total_events = int(count_cursor.fetchone()[0])
        finally:
            count_cursor.close()

        checks = {
            "scenario_results": hashlib.sha256(
                _canonical_json(scenario_summaries).encode("utf-8")
            ).hexdigest(),
            "pagination_total": total_events,
            "ordering_sha256": hashlib.sha256(
                _canonical_json(event_ids).encode("utf-8")
            ).hexdigest(),
            "casefold_sha256": hashlib.sha256(
                _canonical_json(casefold_values).encode("utf-8")
            ).hexdigest(),
            "json_country_sha256": hashlib.sha256(
                _canonical_json(sorted(country_values)).encode("utf-8")
            ).hexdigest(),
            "shanghai_time_sha256": hashlib.sha256(
                _canonical_json(shanghai_times).encode("utf-8")
            ).hexdigest(),
        }
        return {
            "scenarios": scenario_summaries,
            "checks": checks,
        }
    finally:
        connection.close()


def compare_semantics(
    sqlite_snapshot: dict[str, Any],
    postgres_snapshot: dict[str, Any],
) -> dict[str, Any]:
    names = sorted(
        set(sqlite_snapshot.get("checks", {}))
        | set(postgres_snapshot.get("checks", {}))
    )
    details = []
    for name in names:
        sqlite_value = sqlite_snapshot.get("checks", {}).get(name)
        postgres_value = postgres_snapshot.get("checks", {}).get(name)
        details.append(
            {
                "check": name,
                "passed": sqlite_value == postgres_value,
                "sqlite": sqlite_value,
                "postgres": postgres_value,
            }
        )
    scenario_names = sorted(
        set(sqlite_snapshot.get("scenarios", {}))
        | set(postgres_snapshot.get("scenarios", {}))
    )
    for scenario in scenario_names:
        sqlite_value = sqlite_snapshot.get("scenarios", {}).get(scenario)
        postgres_value = postgres_snapshot.get("scenarios", {}).get(scenario)
        details.append(
            {
                "check": f"scenario:{scenario}",
                "passed": sqlite_value == postgres_value,
                "sqlite": sqlite_value,
                "postgres": postgres_value,
            }
        )
    mismatches = sum(1 for item in details if not item["passed"])
    return {
        "passed": mismatches == 0,
        "mismatches": mismatches,
        "checks": details,
    }


def acceptance_preview(
    read_results: Sequence[dict[str, Any]],
    write_result: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    for item in read_results:
        sqlite_p95 = float(item.get("sqlite_p95_ms") or 0)
        postgres_p95 = float(item.get("postgres_p95_ms") or 0)
        concurrency = int(item.get("concurrency") or 0)
        ratio = postgres_p95 / sqlite_p95 if sqlite_p95 > 0 else math.inf
        limit = 1.10 if concurrency == 1 else 0.80
        if int(item.get("errors") or 0) != 0 or ratio > limit:
            failures.append(
                f"{item.get('scenario')}/{concurrency}: ratio={ratio:.4f}, limit={limit:.2f}"
            )
    sqlite_tps = float(write_result.get("sqlite_tps") or 0)
    postgres_tps = float(write_result.get("postgres_tps") or 0)
    write_ratio = postgres_tps / sqlite_tps if sqlite_tps > 0 else 0.0
    if (
        int(write_result.get("transactions") or 0) < WRITE_TRANSACTION_FLOOR
        or int(write_result.get("errors") or 0) != 0
        or write_ratio < 2.0
    ):
        failures.append(
            "write: "
            f"ratio={write_ratio:.4f}, "
            f"transactions={write_result.get('transactions')}, "
            f"errors={write_result.get('errors')}"
        )
    if semantic.get("passed") is not True:
        failures.append("semantic_equivalence")
    return {
        "passed": not failures,
        "failures": failures,
        "write_ratio": write_ratio,
    }


def build_report(
    *,
    sqlite_path: Path,
    postgres_schema: str,
    warmups: int,
    iterations: int,
    read_results: list[dict[str, Any]],
    write_result: dict[str, Any],
    semantic: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, Any]:
    preview = acceptance_preview(read_results, write_result, semantic)
    return {
        "format": REPORT_FORMAT,
        "format_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "sqlite_database": str(sqlite_path),
            "postgres_schema": postgres_schema,
            "warmups_per_worker": warmups,
            "iterations_per_worker": iterations,
            "read_concurrencies": list(READ_CONCURRENCIES),
            "write_concurrency": WRITE_CONCURRENCY,
            "default_contract_transactions": WRITE_CONCURRENCY * iterations,
            "source_databases_written": False,
            "durability": {
                "sqlite": "FULL",
                "postgresql": "synchronous_commit=on",
            },
        },
        "read_results": read_results,
        "write_result": write_result,
        "semantic_equivalence": semantic,
        "result_summaries": snapshots,
        "acceptance_preview": preview,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    sqlite_backend = SQLiteReadBackend(args.sqlite_db)
    postgres_backend = PostgreSQLReadBackend(
        args.postgres_url,
        args.postgres_schema,
    )

    def progress(message: str) -> None:
        print(f"[benchmark] {message}", file=sys.stderr, flush=True)
    progress("discovering a selective search term from SQLite")
    search_pattern = discover_search_pattern(sqlite_backend)

    read_results = benchmark_reads(
        sqlite_backend,
        postgres_backend,
        warmups=args.warmups,
        iterations=args.iterations,
        search_pattern=search_pattern,
        progress=progress,
    )
    write_result = benchmark_writes(
        sqlite_backend,
        postgres_backend,
        warmups=args.warmups,
        iterations=args.iterations,
        progress=progress,
    )
    progress("semantic equivalence: SQLite")
    sqlite_snapshot = semantic_snapshot(sqlite_backend, search_pattern)
    progress("semantic equivalence: PostgreSQL")
    postgres_snapshot = semantic_snapshot(postgres_backend, search_pattern)
    semantic = compare_semantics(sqlite_snapshot, postgres_snapshot)
    return build_report(
        sqlite_path=sqlite_backend.database_path,
        postgres_schema=postgres_backend.schema,
        warmups=args.warmups,
        iterations=args.iterations,
        read_results=read_results,
        write_result=write_result,
        semantic=semantic,
        snapshots={
            "sqlite": sqlite_snapshot,
            "postgresql": postgres_snapshot,
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the same migrated data on SQLite and PostgreSQL without "
            "writing either source schema."
        )
    )
    parser.add_argument(
        "--sqlite-db",
        required=True,
        type=Path,
        help="source SQLite collector database; opened read-only",
    )
    parser.add_argument(
        "--postgres-url",
        required=True,
        help=(
            "PostgreSQL URL with read access to the release schema and permission "
            "to create/drop a disposable benchmark schema"
        ),
    )
    parser.add_argument(
        "--postgres-schema",
        required=True,
        help="migrated PostgreSQL release schema; opened read-only",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="JSON report path",
    )
    parser.add_argument(
        "--warmups",
        type=_non_negative_int,
        default=DEFAULT_WARMUPS,
        help=f"warm-up operations per worker (default: {DEFAULT_WARMUPS})",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=DEFAULT_ITERATIONS,
        help=(
            "measured operations per worker; default 100 produces 800 write "
            "transactions at concurrency 8"
        ),
    )
    parser.add_argument(
        "--enforce-contract",
        action="store_true",
        help="exit non-zero when the migration performance thresholds are not met",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        sqlite_resolved = args.sqlite_db.expanduser().resolve(strict=True)
        output_resolved = args.output.expanduser().resolve()
        if sqlite_resolved == output_resolved:
            raise BenchmarkError("--output must not overwrite --sqlite-db")
        report = run_benchmark(args)
        write_report(args.output, report)
    except (BenchmarkError, OSError, sqlite3.Error) as exc:
        print(f"[benchmark] ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[benchmark] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    preview = report["acceptance_preview"]
    print(
        json.dumps(
            {
                "output": str(args.output.expanduser().resolve()),
                "acceptance_passed": preview["passed"],
                "semantic_passed": report["semantic_equivalence"]["passed"],
                "read_results": len(report["read_results"]),
                "write_transactions": report["write_result"]["transactions"],
            },
            ensure_ascii=False,
        )
    )
    if args.enforce_contract and not preview["passed"]:
        return 3
    if report["semantic_equivalence"]["passed"] is not True:
        return 4
    if any(int(item.get("errors") or 0) for item in report["read_results"]):
        return 5
    if int(report["write_result"].get("errors") or 0):
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
