#!/usr/bin/env python3
"""Benchmark production read APIs against frozen SQLite and PostgreSQL data.

The benchmark starts two single-worker Uvicorn processes running the same app.
Every database connection in the child processes is forced through the
project's read-only connection path, lifespan hooks are disabled, and the
request set is a fixed GET-only allowlist.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from threading import Barrier
import time
from typing import Any, Iterable, Sequence
from urllib.parse import quote, urlencode, urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RAW_BENCHMARK_PATH = Path(__file__).with_name("benchmark_databases.py")
REPORT_FORMAT = "dwti-api-read-benchmark"
REPORT_VERSION = 2
DEFAULT_WARMUPS = 5
DEFAULT_ITERATIONS = 100
CONCURRENCIES = (1, 8)
SAFE_METHOD = "GET"
PATH_VALUE_KEYS = {
    "file_path",
    "html_path",
    "screenshot_path",
    "raw_artifact_path",
}
DYNAMIC_RESPONSE_KEYS = {"generatedAt"}
JOBS_RUNTIME_DB_IDENTITY_KEYS = {
    "runtime_db_path",
    "source_db_path",
    "using_runtime_db",
    "runtime_db_exists",
    "source_db_exists",
    "runtime_db_updated_at",
    "runtime_db_size_mb",
    "meta_exists",
}


class ApiBenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApiScenario:
    name: str
    path: str
    report_path: str


@dataclass(frozen=True)
class RequestResult:
    latency_ms: float
    status_code: int
    payload_bytes: int
    semantic_sha256: str


def _load_raw_benchmark_module():
    spec = importlib.util.spec_from_file_location(
        "dwti_api_raw_benchmark",
        RAW_BENCHMARK_PATH,
    )
    if spec is None or spec.loader is None:
        raise ApiBenchmarkError("unable to load benchmark_databases.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RAW_BENCHMARK = _load_raw_benchmark_module()


def _canonical_response(value: Any, *, scenario_name: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key in DYNAMIC_RESPONSE_KEYS:
                continue
            if (
                scenario_name == "jobs"
                and normalized_key == "runtime_db"
                and isinstance(item, dict)
            ):
                result[normalized_key] = {
                    str(runtime_key): _canonical_response(
                        runtime_value,
                        scenario_name=scenario_name,
                    )
                    for runtime_key, runtime_value in item.items()
                    if str(runtime_key) not in JOBS_RUNTIME_DB_IDENTITY_KEYS
                }
            elif (
                normalized_key in PATH_VALUE_KEYS
                and isinstance(item, str)
                and item
            ):
                result[normalized_key] = item.replace("\\", "/").rsplit("/", 1)[-1]
            else:
                result[normalized_key] = _canonical_response(
                    item,
                    scenario_name=scenario_name,
                )
        return result
    if isinstance(value, list):
        return [
            _canonical_response(item, scenario_name=scenario_name)
            for item in value
        ]
    return RAW_BENCHMARK._canonical_value(value)


def _canonical_json(value: Any, *, scenario_name: str = "") -> str:
    return json.dumps(
        _canonical_response(value, scenario_name=scenario_name),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _semantic_sha256(value: Any, *, scenario_name: str = "") -> str:
    return hashlib.sha256(
        _canonical_json(value, scenario_name=scenario_name).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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
    return ordered[lower] + (
        ordered[upper] - ordered[lower]
    ) * (rank - lower)


def backend_order(scenario_index: int, round_index: int) -> tuple[str, str]:
    if (scenario_index + round_index) % 2 == 0:
        return ("sqlite", "postgresql")
    return ("postgresql", "sqlite")


def fixed_scenarios(search_term: str, report_run_id: str) -> tuple[ApiScenario, ...]:
    term = str(search_term or "").strip()
    run_id = str(report_run_id or "").strip()
    if not term:
        raise ApiBenchmarkError("a non-empty discovered search term is required")
    if not run_id:
        raise ApiBenchmarkError("an AI run with a report is required")

    filtered_query = urlencode(
        {
            "page": 1,
            "page_size": 20,
            "types": "data_leak,ransomware",
            "keyword": term,
            "days": 36500,
            "min_risk_score": 0,
            "sort": "risk_desc",
        }
    )
    report_filtered_query = urlencode(
        {
            "page": 1,
            "page_size": 20,
            "types": "data_leak,ransomware",
            "keyword": "__discovered__",
            "days": 36500,
            "min_risk_score": 0,
            "sort": "risk_desc",
        }
    )
    return (
        ApiScenario(
            "dashboard_overview",
            "/api/dashboard/overview?days=30",
            "/api/dashboard/overview?days=30",
        ),
        ApiScenario(
            "intelligence_home",
            "/api/intelligence/search?page=1&page_size=20&sort=risk_desc",
            "/api/intelligence/search?page=1&page_size=20&sort=risk_desc",
        ),
        ApiScenario(
            "intelligence_deep_page",
            "/api/intelligence/search?page=1000&page_size=20&sort=risk_desc",
            "/api/intelligence/search?page=1000&page_size=20&sort=risk_desc",
        ),
        ApiScenario(
            "intelligence_filtered_sorted",
            "/api/intelligence/search?" + filtered_query,
            "/api/intelligence/search?" + report_filtered_query,
        ),
        ApiScenario(
            "data_leak",
            "/api/intelligence/data-leak?page=1&page_size=20&sort=risk_desc",
            "/api/intelligence/data-leak?page=1&page_size=20&sort=risk_desc",
        ),
        ApiScenario(
            "ransomware",
            "/api/intelligence/ransomware?page=1&page_size=20&sort=risk_desc",
            "/api/intelligence/ransomware?page=1&page_size=20&sort=risk_desc",
        ),
        ApiScenario(
            "vulnerability",
            "/api/vulnerabilities?page=1&page_size=20&sort=risk_desc",
            "/api/vulnerabilities?page=1&page_size=20&sort=risk_desc",
        ),
        ApiScenario("jobs", "/api/jobs", "/api/jobs"),
        ApiScenario(
            "code_summary",
            "/api/code-monitoring/summary",
            "/api/code-monitoring/summary",
        ),
        ApiScenario(
            "code_hits",
            "/api/code-monitoring/hits?limit=100",
            "/api/code-monitoring/hits?limit=100",
        ),
        ApiScenario(
            "document_summary",
            "/api/document-exposures/summary",
            "/api/document-exposures/summary",
        ),
        ApiScenario(
            "document_hits",
            "/api/document-exposures?limit=100",
            "/api/document-exposures?limit=100",
        ),
        ApiScenario(
            "ai_profiles",
            "/api/ai-aggregation/profiles",
            "/api/ai-aggregation/profiles",
        ),
        ApiScenario(
            "ai_runs",
            "/api/ai-aggregation/runs?limit=20&offset=0",
            "/api/ai-aggregation/runs?limit=20&offset=0",
        ),
        ApiScenario(
            "ai_report_detail",
            "/api/ai-aggregation/runs/" + quote(run_id, safe=""),
            "/api/ai-aggregation/runs/__report_run__",
        ),
    )


def _validate_scenarios(scenarios: Iterable[ApiScenario]) -> None:
    names: set[str] = set()
    for scenario in scenarios:
        if not scenario.name or scenario.name in names:
            raise ApiBenchmarkError("API benchmark scenario names must be unique")
        names.add(scenario.name)
        split = urlsplit(scenario.path)
        if (
            not split.path.startswith("/api/")
            or split.scheme
            or split.netloc
            or split.fragment
        ):
            raise ApiBenchmarkError(
                f"unsafe API benchmark path: {scenario.report_path}"
            )


def discover_inputs(sqlite_path: Path) -> tuple[str, str]:
    backend = RAW_BENCHMARK.SQLiteReadBackend(sqlite_path)
    pattern = RAW_BENCHMARK.discover_search_pattern(backend)
    term = pattern.strip("%").strip()
    connection = backend.connect()
    try:
        row = connection.execute(
            """
            SELECT runs.id
            FROM ai_aggregation_runs AS runs
            JOIN ai_aggregation_reports AS reports ON reports.run_id = runs.id
            ORDER BY reports.generated_at DESC, reports.id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ApiBenchmarkError(
            "frozen SQLite has no AI aggregation run with a report"
        )
    return term, str(row[0])


def create_sqlite_backup(source: Path, destination: Path) -> None:
    resolved = source.expanduser().resolve(strict=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(
        resolved.as_uri() + "?mode=ro",
        uri=True,
        timeout=30.0,
    )
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(
            destination_connection,
            pages=4096,
            sleep=0.01,
        )
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def sqlite_summary(database_path: Path) -> dict[str, Any]:
    backend = RAW_BENCHMARK.SQLiteReadBackend(database_path)
    connection = backend.connect()
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        row_counts = {
            table_name: int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table_name}"'
                ).fetchone()[0]
            )
            for table_name in tables
        }
        state = connection.execute(
            """
            SELECT source_revision, applied_revision, source_signature,
                   event_count, refreshed_at
            FROM normalized_intelligence_cache_state
            WHERE id = 1
            """
        ).fetchone()
        payload = {
            "row_counts": row_counts,
            "normalization_state": list(state) if state is not None else None,
        }
        return {
            "table_count": len(tables),
            "total_rows": sum(row_counts.values()),
            "sha256": _semantic_sha256(payload),
            "row_counts": row_counts,
        }
    finally:
        connection.close()


def postgres_summary(database_url: str, schema: str) -> dict[str, Any]:
    backend = RAW_BENCHMARK.PostgreSQLReadBackend(database_url, schema)
    connection = backend.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            read_only = str(cursor.fetchone()[0]).casefold() == "on"
            cursor.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version"
            )
            migrations = [
                {"version": str(row[0]), "checksum": str(row[1])}
                for row in cursor.fetchall()
            ]
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (schema,),
            )
            tables = [str(row[0]) for row in cursor.fetchall()]
            row_counts: dict[str, int] = {}
            for table_name in tables:
                cursor.execute(
                    backend.sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                        backend.sql.Identifier(schema),
                        backend.sql.Identifier(table_name),
                    )
                )
                row_counts[table_name] = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT source_revision, applied_revision, source_signature,
                       event_count, refreshed_at
                FROM normalized_intelligence_cache_state
                WHERE id = 1
                """
            )
            state = cursor.fetchone()
        payload = {
            "migrations": migrations,
            "row_counts": row_counts,
            "normalization_state": list(state) if state is not None else None,
        }
        return {
            "read_only": read_only,
            "table_count": len(tables),
            "total_rows": sum(row_counts.values()),
            "schema_version_0006": any(
                item["version"] == "0006_postgres_read_paths"
                for item in migrations
            ),
            "sha256": _semantic_sha256(payload),
            "row_counts": row_counts,
            "migrations": migrations,
        }
    finally:
        connection.close()


def _safe_environment(
    *,
    user_data_root: Path,
    output_root: Path,
) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("DARKWEB_")
        and not key.startswith("FLOCKS_")
    }
    environment.update(
        {
            "PYTHONPATH": str(SRC),
            "PYTHONUNBUFFERED": "1",
            "DARKWEB_API_AUTH_DISABLED": "1",
            "DARKWEB_BASIC_AUTH_ENABLED": "0",
            "DARKWEB_SKIP_API_WARMUP": "1",
            "DARKWEB_API_AUTO_RELOAD": "0",
            "DARKWEB_USER_DATA_ROOT": str(user_data_root),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_root),
            "DARKWEB_ACTIVE_RELEASE_FILE": str(
                user_data_root / "missing-active-release.json"
            ),
            "DARKWEB_AUTH_ACCOUNTS_DB": str(
                user_data_root / "auth-accounts.db"
            ),
            "DARKWEB_POSTGRES_POOL_MIN": "1",
            "DARKWEB_POSTGRES_POOL_MAX": "4",
            "DARKWEB_POSTGRES_POOL_WAIT_TIMEOUT_SECONDS": "30",
            "DARKWEB_POSTGRES_CONNECT_TIMEOUT_SECONDS": "15",
            "DARKWEB_AI_AGGREGATION_MODE": "mock",
            "DARKWEB_AI_AGGREGATION_DELIVERY_MODE": "mock",
            "DARKWEB_AI_AGGREGATION_SCHEDULER_POLL_SECONDS": "3600",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    return environment


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class ApiServer:
    def __init__(
        self,
        *,
        backend: str,
        database_path: Path,
        schema: str,
        working_root: Path,
        secrets: Sequence[str],
    ) -> None:
        if backend not in {"sqlite", "postgresql"}:
            raise ApiBenchmarkError("unsupported API benchmark backend")
        self.backend = backend
        self.database_path = database_path
        self.schema = schema
        self.working_root = working_root
        self.secrets = tuple(value for value in secrets if value)
        self.port = _free_port()
        self.process: subprocess.Popen[str] | None = None
        self._log_handle = None
        self.log_path = working_root / "uvicorn.log"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.working_root.mkdir(parents=True, exist_ok=True)
        environment = _safe_environment(
            user_data_root=self.working_root / "user-data",
            output_root=self.working_root / "output",
        )
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "_serve",
            "--backend",
            self.backend,
            "--port",
            str(self.port),
            "--database-path",
            str(self.database_path),
            "--schema",
            self.schema,
            "--user-data-root",
            str(self.working_root / "user-data"),
            "--output-root",
            str(self.working_root / "output"),
        ]
        self._log_handle = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._wait_until_ready()

    def _safe_log_tail(self) -> str:
        try:
            text = self.log_path.read_text(
                encoding="utf-8",
                errors="replace",
            )[-4000:]
        except OSError:
            return ""
        for secret in self.secrets:
            text = text.replace(secret, "<redacted>")
        return text.replace("\n", " ")[:1000]

    def _wait_until_ready(self, timeout: float = 90.0) -> None:
        import httpx

        deadline = time.monotonic() + timeout
        expected_engine = "sqlite" if self.backend == "sqlite" else "postgresql"
        with httpx.Client(
            timeout=2.0,
            trust_env=False,
            headers={"Accept": "application/json"},
        ) as client:
            while time.monotonic() < deadline:
                if self.process is not None and self.process.poll() is not None:
                    raise ApiBenchmarkError(
                        f"{self.backend} API exited during startup: "
                        + self._safe_log_tail()
                    )
                try:
                    response = client.get(self.base_url + "/api/health")
                    if response.status_code == 200:
                        payload = response.json()
                        if str(payload.get("engine")) != expected_engine:
                            raise ApiBenchmarkError(
                                f"{self.backend} health returned wrong engine"
                            )
                        if (
                            self.backend == "postgresql"
                            and str(payload.get("schema")) != self.schema
                        ):
                            raise ApiBenchmarkError(
                                "PostgreSQL health returned wrong schema"
                            )
                        return
                except ApiBenchmarkError:
                    raise
                except Exception:
                    pass
                time.sleep(0.1)
        raise ApiBenchmarkError(
            f"{self.backend} API did not become ready: "
            + self._safe_log_tail()
        )

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def __enter__(self) -> "ApiServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.stop()
        return False


def _request_once(
    client: Any,
    path: str,
    *,
    scenario_name: str = "",
) -> RequestResult:
    started = time.perf_counter()
    try:
        response = client.request(SAFE_METHOD, path)
    except Exception as exc:
        raise ApiBenchmarkError(
            f"HTTP request failed: {type(exc).__name__}: {str(exc)[:300]}"
        ) from exc
    latency_ms = (time.perf_counter() - started) * 1000.0
    if response.status_code != 200:
        detail = response.text.replace("\n", " ")[:500]
        raise ApiBenchmarkError(
            f"GET {urlsplit(path).path} returned {response.status_code}: {detail}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiBenchmarkError(
            f"GET {urlsplit(path).path} did not return JSON"
        ) from exc
    return RequestResult(
        latency_ms=latency_ms,
        status_code=int(response.status_code),
        payload_bytes=len(response.content),
        semantic_sha256=_semantic_sha256(
            payload,
            scenario_name=scenario_name,
        ),
    )


def _run_backend_batch(
    executor: ThreadPoolExecutor,
    clients: Sequence[Any],
    path: str,
    *,
    scenario_name: str = "",
) -> tuple[list[RequestResult], float]:
    barrier = Barrier(len(clients))

    def operation(client: Any) -> RequestResult:
        barrier.wait(timeout=30)
        return _request_once(
            client,
            path,
            scenario_name=scenario_name,
        )

    started = time.perf_counter()
    futures = [
        executor.submit(operation, client)
        for client in clients
    ]
    results = [future.result() for future in futures]
    return results, max(time.perf_counter() - started, 1e-9)


def _metrics(
    results: Sequence[RequestResult],
    active_seconds: float,
    *,
    concurrency: int,
    warmups: int,
    iterations: int,
) -> dict[str, Any]:
    latencies = [item.latency_ms for item in results]
    statuses = Counter(str(item.status_code) for item in results)
    digests = Counter(item.semantic_sha256 for item in results)
    return {
        "concurrency": concurrency,
        "warmups_per_worker": warmups,
        "iterations_per_worker": iterations,
        "attempted_requests": concurrency * iterations,
        "successful_requests": len(results),
        "p50_ms": round(_percentile(latencies, 0.50), 6),
        "p95_ms": round(_percentile(latencies, 0.95), 6),
        "throughput": round(len(results) / max(active_seconds, 1e-9), 6),
        "status_counts": dict(sorted(statuses.items())),
        "errors": concurrency * iterations - len(results),
        "average_payload_bytes": round(
            sum(item.payload_bytes for item in results) / max(len(results), 1),
            3,
        ),
        "semantic_hashes": dict(sorted(digests.items())),
        "semantic_stable": len(digests) == 1,
        "active_seconds": round(active_seconds, 6),
    }


def benchmark_scenario(
    scenario: ApiScenario,
    *,
    scenario_index: int,
    base_urls: dict[str, str],
    concurrency: int,
    warmups: int,
    iterations: int,
    request_timeout: float,
) -> dict[str, Any]:
    import httpx

    clients = {
        backend: [
            httpx.Client(
                base_url=base_url,
                timeout=request_timeout,
                trust_env=False,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "Connection": "keep-alive",
                },
            )
            for _ in range(concurrency)
        ]
        for backend, base_url in base_urls.items()
    }
    executors = {
        backend: ThreadPoolExecutor(max_workers=concurrency)
        for backend in base_urls
    }
    measured: dict[str, list[RequestResult]] = {
        "sqlite": [],
        "postgresql": [],
    }
    active_seconds = {"sqlite": 0.0, "postgresql": 0.0}
    try:
        total_rounds = warmups + iterations
        for round_index in range(total_rounds):
            measured_round = round_index >= warmups
            for backend in backend_order(scenario_index, round_index):
                try:
                    batch, elapsed = _run_backend_batch(
                        executors[backend],
                        clients[backend],
                        scenario.path,
                        scenario_name=scenario.name,
                    )
                except ApiBenchmarkError as exc:
                    raise ApiBenchmarkError(f"{backend}: {exc}") from exc
                if measured_round:
                    measured[backend].extend(batch)
                    active_seconds[backend] += elapsed
    finally:
        for executor in executors.values():
            executor.shutdown(wait=True)
        for backend_clients in clients.values():
            for client in backend_clients:
                client.close()

    sqlite_metrics = _metrics(
        measured["sqlite"],
        active_seconds["sqlite"],
        concurrency=concurrency,
        warmups=warmups,
        iterations=iterations,
    )
    postgres_metrics = _metrics(
        measured["postgresql"],
        active_seconds["postgresql"],
        concurrency=concurrency,
        warmups=warmups,
        iterations=iterations,
    )
    sqlite_hashes = set(sqlite_metrics["semantic_hashes"])
    postgres_hashes = set(postgres_metrics["semantic_hashes"])
    semantic_passed = (
        sqlite_metrics["semantic_stable"]
        and postgres_metrics["semantic_stable"]
        and sqlite_hashes == postgres_hashes
    )
    sqlite_p95 = float(sqlite_metrics["p95_ms"])
    postgres_p95 = float(postgres_metrics["p95_ms"])
    p95_ratio = postgres_p95 / sqlite_p95 if sqlite_p95 > 0 else math.inf
    limit = 1.10 if concurrency == 1 else 0.80
    return {
        "scenario": scenario.name,
        "path": scenario.report_path,
        "method": SAFE_METHOD,
        "concurrency": concurrency,
        "sqlite": sqlite_metrics,
        "postgresql": postgres_metrics,
        "sqlite_p50_ms": sqlite_metrics["p50_ms"],
        "sqlite_p95_ms": sqlite_metrics["p95_ms"],
        "sqlite_throughput": sqlite_metrics["throughput"],
        "postgres_p50_ms": postgres_metrics["p50_ms"],
        "postgres_p95_ms": postgres_metrics["p95_ms"],
        "postgres_throughput": postgres_metrics["throughput"],
        "p95_ratio": round(p95_ratio, 6),
        "p95_limit": limit,
        "performance_passed": p95_ratio <= limit,
        "semantic_passed": semantic_passed,
        "errors": sqlite_metrics["errors"] + postgres_metrics["errors"],
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
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


def _read_target(path: Path) -> tuple[str, tuple[str, ...]]:
    payload = json.loads(path.expanduser().resolve(strict=True).read_text(
        encoding="utf-8"
    ))
    database_url = str(payload.get("runtime_database_url") or "").strip()
    if not database_url.lower().startswith(("postgres://", "postgresql://")):
        raise ApiBenchmarkError(
            "PostgreSQL target has no runtime_database_url"
        )
    secrets = tuple(
        str(payload.get(key) or "")
        for key in (
            "runtime_database_url",
            "runtime_password",
            "migration_database_url",
            "migration_password",
        )
        if str(payload.get(key) or "")
    )
    return database_url, secrets


def _run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    sqlite_source = args.sqlite_db.expanduser().resolve(strict=True)
    target_path = args.postgres_target.expanduser().resolve(strict=True)
    output_path = args.output.expanduser().resolve()
    if output_path in {sqlite_source, target_path}:
        raise ApiBenchmarkError("output cannot overwrite an input")
    if output_path.exists():
        raise ApiBenchmarkError("output report already exists")

    database_url, secrets = _read_target(target_path)
    sqlite_sha_before = _file_sha256(sqlite_source)
    search_term, report_run_id = discover_inputs(sqlite_source)
    scenarios = fixed_scenarios(search_term, report_run_id)
    _validate_scenarios(scenarios)
    postgres_before = postgres_summary(
        database_url,
        args.postgres_schema,
    )
    if not postgres_before["read_only"]:
        raise ApiBenchmarkError("PostgreSQL summary connection is not read-only")
    if not postgres_before["schema_version_0006"]:
        raise ApiBenchmarkError("PostgreSQL candidate is missing 0006")

    generated_at = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(
        prefix="dwti-api-read-benchmark-"
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        sqlite_backup = temporary_root / "sqlite" / "collector.db"
        create_sqlite_backup(sqlite_source, sqlite_backup)
        sqlite_backup_sha_before = _file_sha256(sqlite_backup)
        sqlite_summary_before = sqlite_summary(sqlite_backup)

        sqlite_server = ApiServer(
            backend="sqlite",
            database_path=sqlite_backup,
            schema="",
            working_root=temporary_root / "sqlite-server",
            secrets=secrets,
        )
        postgres_server = ApiServer(
            backend="postgresql",
            database_path=target_path,
            schema=args.postgres_schema,
            working_root=temporary_root / "postgres-server",
            secrets=secrets,
        )
        results: list[dict[str, Any]] = []
        try:
            sqlite_server.start()
            postgres_server.start()
            base_urls = {
                "sqlite": sqlite_server.base_url,
                "postgresql": postgres_server.base_url,
            }
            for scenario_index, scenario in enumerate(scenarios):
                for concurrency in CONCURRENCIES:
                    print(
                        "[api-read] "
                        f"{scenario.name} concurrency={concurrency}",
                        file=sys.stderr,
                        flush=True,
                    )
                    results.append(
                        benchmark_scenario(
                            scenario,
                            scenario_index=scenario_index,
                            base_urls=base_urls,
                            concurrency=concurrency,
                            warmups=args.warmups,
                            iterations=args.iterations,
                            request_timeout=args.request_timeout,
                        )
                    )
        finally:
            postgres_server.stop()
            sqlite_server.stop()

        sqlite_backup_sha_after = _file_sha256(sqlite_backup)
        sqlite_summary_after = sqlite_summary(sqlite_backup)

    sqlite_sha_after = _file_sha256(sqlite_source)
    postgres_after = postgres_summary(
        database_url,
        args.postgres_schema,
    )
    source_integrity = {
        "sqlite_source_sha256_before": sqlite_sha_before,
        "sqlite_source_sha256_after": sqlite_sha_after,
        "sqlite_source_unchanged": sqlite_sha_before == sqlite_sha_after,
        "sqlite_backup_sha256_before": sqlite_backup_sha_before,
        "sqlite_backup_sha256_after": sqlite_backup_sha_after,
        "sqlite_backup_unchanged": (
            sqlite_backup_sha_before == sqlite_backup_sha_after
        ),
        "sqlite_summary_sha256_before": sqlite_summary_before["sha256"],
        "sqlite_summary_sha256_after": sqlite_summary_after["sha256"],
        "sqlite_summary_unchanged": (
            sqlite_summary_before["sha256"] == sqlite_summary_after["sha256"]
        ),
        "postgres_summary_sha256_before": postgres_before["sha256"],
        "postgres_summary_sha256_after": postgres_after["sha256"],
        "postgres_summary_unchanged": (
            postgres_before["sha256"] == postgres_after["sha256"]
        ),
    }
    integrity_passed = all(
        (
            source_integrity["sqlite_source_unchanged"],
            source_integrity["sqlite_backup_unchanged"],
            source_integrity["sqlite_summary_unchanged"],
            source_integrity["postgres_summary_unchanged"],
        )
    )
    semantic_passed = all(item["semantic_passed"] for item in results)
    no_errors = all(int(item["errors"]) == 0 for item in results)
    performance_passed = all(
        item["performance_passed"] for item in results
    )
    report = {
        "format": REPORT_FORMAT,
        "format_version": REPORT_VERSION,
        "generated_at": generated_at,
        "parameters": {
            "sqlite_database": str(sqlite_source),
            "postgres_schema": args.postgres_schema,
            "warmups_per_worker": args.warmups,
            "iterations_per_worker": args.iterations,
            "concurrencies": list(CONCURRENCIES),
            "uvicorn_workers": 1,
            "backend_order": "alternating_by_scenario_and_round",
            "api_auth_disabled": True,
            "basic_auth_disabled": True,
            "lifespan": "off",
            "database_connections_forced_read_only": True,
            "writes_executed": False,
            "raw_database_report_role": "diagnostic_only",
            "request_timeout_seconds": args.request_timeout,
            "search_term_sha256": hashlib.sha256(
                search_term.encode("utf-8")
            ).hexdigest(),
        },
        "scenarios": [
            {
                "name": scenario.name,
                "method": SAFE_METHOD,
                "path": scenario.report_path,
            }
            for scenario in scenarios
        ],
        "results": results,
        "source_integrity": source_integrity,
        "sqlite_summary_before": sqlite_summary_before,
        "sqlite_summary_after": sqlite_summary_after,
        "postgres_summary_before": postgres_before,
        "postgres_summary_after": postgres_after,
        "semantic_passed": semantic_passed,
        "performance_passed": performance_passed,
        "no_errors": no_errors,
        "integrity_passed": integrity_passed,
        "acceptance_passed": (
            semantic_passed
            and performance_passed
            and no_errors
            and integrity_passed
        ),
    }
    _write_report(output_path, report)
    if not integrity_passed:
        raise ApiBenchmarkError(
            "a source database changed during the API read benchmark"
        )
    if not semantic_passed:
        raise ApiBenchmarkError(
            "SQLite/PostgreSQL API response semantics differ"
        )
    if not no_errors:
        raise ApiBenchmarkError("API read benchmark recorded errors")
    return report


def _configure_child_environment(args: argparse.Namespace) -> None:
    user_data_root = args.user_data_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    user_data_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "DARKWEB_API_AUTH_DISABLED": "1",
            "DARKWEB_BASIC_AUTH_ENABLED": "0",
            "DARKWEB_SKIP_API_WARMUP": "1",
            "DARKWEB_API_AUTO_RELOAD": "0",
            "DARKWEB_USER_DATA_ROOT": str(user_data_root),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_root),
            "DARKWEB_ACTIVE_RELEASE_FILE": str(
                user_data_root / "missing-active-release.json"
            ),
            "DARKWEB_AUTH_ACCOUNTS_DB": str(
                user_data_root / "auth-accounts.db"
            ),
            "DARKWEB_COLLECTOR_SITES_FILE": str(
                (ROOT / "sites.yaml").resolve()
            ),
            "DARKWEB_POSTGRES_POOL_MIN": "1",
            "DARKWEB_POSTGRES_POOL_MAX": "4",
            "DARKWEB_POSTGRES_POOL_WAIT_TIMEOUT_SECONDS": "30",
            "DARKWEB_POSTGRES_CONNECT_TIMEOUT_SECONDS": "15",
            "DARKWEB_AI_AGGREGATION_MODE": "mock",
            "DARKWEB_AI_AGGREGATION_DELIVERY_MODE": "mock",
            "DARKWEB_AI_AGGREGATION_SCHEDULER_POLL_SECONDS": "3600",
        }
    )
    if args.backend == "sqlite":
        database_path = args.database_path.expanduser().resolve(strict=True)
        os.environ.update(
            {
                "DARKWEB_COLLECTOR_DATABASE_URL": "",
                "DARKWEB_COLLECTOR_DATABASE_SCHEMA": "",
                "DARKWEB_COLLECTOR_DB_PATH": str(database_path),
                "DARKWEB_COLLECTOR_SOURCE_DB_PATH": str(database_path),
                "DARKWEB_RUNTIME_DB_META_PATH": str(
                    database_path.with_suffix(".meta.json")
                ),
            }
        )
    else:
        database_url, _secrets = _read_target(args.database_path)
        os.environ.update(
            {
                "DARKWEB_COLLECTOR_DATABASE_URL": database_url,
                "DARKWEB_COLLECTOR_DATABASE_SCHEMA": args.schema,
                "DARKWEB_COLLECTOR_SCHEMA_VERSION": "0006_postgres_read_paths",
                "DARKWEB_COLLECTOR_DB_PATH": str(
                    user_data_root / "unused-postgres.db"
                ),
                "DARKWEB_COLLECTOR_SOURCE_DB_PATH": str(
                    user_data_root / "unused-postgres.db"
                ),
                "DARKWEB_RUNTIME_DB_META_PATH": str(
                    user_data_root / "unused-postgres.meta.json"
                ),
            }
        )


def _serve(args: argparse.Namespace) -> int:
    _configure_child_environment(args)
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    from darkweb_collector import db as database_module

    original_readonly_connect = database_module.connect_readonly

    def guarded_connect(database_path: Path):
        return original_readonly_connect(database_path)

    database_module.connect = guarded_connect

    from darkweb_collector.basic_auth_app import app

    @app.middleware("http")
    async def inject_benchmark_admin(request, call_next):
        request.state.current_user = {
            "username": "__api_benchmark__",
            "display_name": "API Benchmark",
            "role": "admin",
            "modules": [
                "threat_situation",
                "intelligence_search",
                "ransomware",
                "data_leak",
                "vulnerability_alerts",
                "file_monitoring",
                "ai_aggregation",
            ],
        }
        return await call_next(request)

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        workers=1,
        reload=False,
        lifespan="off",
        access_log=False,
        log_level="warning",
        proxy_headers=False,
    )
    return 0


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark production GET APIs on SQLite and PostgreSQL"
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--sqlite-db", required=True, type=Path)
    run_parser.add_argument("--postgres-target", required=True, type=Path)
    run_parser.add_argument("--postgres-schema", required=True)
    run_parser.add_argument("--output", required=True, type=Path)
    run_parser.add_argument(
        "--warmups",
        type=_non_negative_int,
        default=DEFAULT_WARMUPS,
    )
    run_parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=DEFAULT_ITERATIONS,
    )
    run_parser.add_argument(
        "--request-timeout",
        type=float,
        default=30.0,
    )

    serve_parser = subparsers.add_parser("_serve")
    serve_parser.add_argument(
        "--backend",
        choices=("sqlite", "postgresql"),
        required=True,
    )
    serve_parser.add_argument("--port", required=True, type=int)
    serve_parser.add_argument("--database-path", required=True, type=Path)
    serve_parser.add_argument("--schema", default="")
    serve_parser.add_argument("--user-data-root", required=True, type=Path)
    serve_parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "_serve":
        return _serve(args)
    if args.command != "run":
        parser.error("the run command is required")
    if args.request_timeout <= 0:
        parser.error("--request-timeout must be positive")
    try:
        report = _run_benchmark(args)
    except Exception as exc:
        print(
            f"API benchmark failed: {type(exc).__name__}: {str(exc)[:800]}",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "report": str(args.output.expanduser().resolve()),
                "acceptance_passed": report["acceptance_passed"],
                "semantic_passed": report["semantic_passed"],
                "performance_passed": report["performance_passed"],
                "integrity_passed": report["integrity_passed"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
