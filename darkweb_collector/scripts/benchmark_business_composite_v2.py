#!/usr/bin/env python3
"""Run the source-bound PostgreSQL/SQLite business composite v2 gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
SRC = ROOT / "src"
for path in (SCRIPT_DIR, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _writebench_composite import run_business_composite  # noqa: E402
from _writebench_contracts import compare_contracts, run_contracts  # noqa: E402
from _writebench_core import (  # noqa: E402
    CANDIDATE_VERSION,
    RunConfig,
    WriteBenchmarkError,
    _non_negative_int,
    _positive_int,
    _sha256_file,
    _shared_benchmark_module,
    _source_identifier,
    _utc_now,
)
from _writebench_targets import (  # noqa: E402
    CleanupRegistry,
    PostgresTarget,
    SQLiteTarget,
    connection_info,
    list_disposable_schemas,
    source_schema_snapshot,
)
from darkweb_collector.business_composite_gate import (  # noqa: E402
    BATCH_SIZE,
    CONCURRENCY,
    ITERATIONS_PER_WORKER,
    ROUNDS,
    SECTION_FORMAT,
    SECTION_VERSION,
    WARMUPS_PER_WORKER,
    backend_order,
    evaluate_business_composite_v2,
)
from darkweb_collector.migration_bundle import _runtime_role_from_url  # noqa: E402
from darkweb_collector.postgres_backend import close_postgres_pools  # noqa: E402
from darkweb_collector.postgres_write_gate import WORKLOADS  # noqa: E402
from darkweb_collector.runtime import active_release_config  # noqa: E402


def _postgres_url(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.lower().startswith(("postgres://", "postgresql://")):
        raise WriteBenchmarkError(f"{label} must be a PostgreSQL URL")
    return normalized


def load_database_urls(args: argparse.Namespace) -> tuple[str, str, str]:
    config_path = args.postgres_config.expanduser().resolve()
    payload: dict[str, Any] = {}
    if config_path.exists():
        try:
            parsed = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WriteBenchmarkError(
                f"cannot read PostgreSQL config: {config_path}"
            ) from exc
        if isinstance(parsed, dict):
            payload = parsed
    migration_url = _postgres_url(
        str(args.migration_url or payload.get("migration_database_url") or ""),
        "migration URL",
    )
    runtime_url = _postgres_url(
        str(args.runtime_url or payload.get("runtime_database_url") or ""),
        "runtime URL",
    )
    if _runtime_role_from_url(migration_url) == _runtime_role_from_url(runtime_url):
        raise WriteBenchmarkError(
            "migration/setup and runtime PostgreSQL roles must be different"
        )
    return migration_url, runtime_url, str(config_path)


def _candidate_identity(snapshot: dict[str, Any]) -> str:
    rows = snapshot.get("summary", {}).get("migrations", [])
    migrations = {str(row[0]): tuple(str(value or "") for value in row) for row in rows}
    if CANDIDATE_VERSION not in migrations:
        raise WriteBenchmarkError(
            f"candidate schema is missing {CANDIDATE_VERSION}"
        )
    baseline = migrations.get("0001_baseline")
    fingerprint = baseline[2] if baseline and len(baseline) > 2 else ""
    if not fingerprint:
        raise WriteBenchmarkError(
            "candidate schema is missing the 0001 source fingerprint"
        )
    return fingerprint


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


def merge_base_report(
    base_path: Path | None,
    output_path: Path,
    section: dict[str, Any],
) -> dict[str, Any]:
    output = output_path.expanduser().resolve()
    if base_path is None:
        return {
            "format": SECTION_FORMAT,
            "format_version": SECTION_VERSION,
            "generated_at": _utc_now(),
            "business_composite_v2": section,
        }
    base = base_path.expanduser().resolve(strict=True)
    if base == output:
        raise WriteBenchmarkError("--output must not overwrite --base-report")
    try:
        payload = json.loads(base.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WriteBenchmarkError(f"invalid --base-report: {base}") from exc
    if not isinstance(payload, dict):
        raise WriteBenchmarkError("--base-report must contain a JSON object")

    merged = dict(payload)
    old_write = merged.pop("write_result", None)
    old_preview = merged.pop("acceptance_preview", None)
    previous_legacy = merged.get("legacy_diagnostic")
    if old_write is not None or old_preview is not None:
        legacy = (
            dict(previous_legacy)
            if isinstance(previous_legacy, dict)
            else {}
        )
        legacy.update(
            {
                "format": "dwti-legacy-composite-v1",
                "acceptance_eligible": False,
            }
        )
        if old_write is not None:
            legacy["write_result"] = old_write
        if old_preview is not None:
            legacy["acceptance_preview"] = old_preview
        merged["legacy_diagnostic"] = legacy
    merged["business_composite_v2"] = section
    return merged


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    sqlite_path = args.sqlite_db.expanduser().resolve(strict=True)
    if not sqlite_path.is_file():
        raise WriteBenchmarkError(f"SQLite source is not a file: {sqlite_path}")
    output_path = args.output.expanduser().resolve()
    if output_path == sqlite_path:
        raise WriteBenchmarkError("--output must not overwrite --sqlite-db")
    postgres_schema = _source_identifier(args.postgres_schema, "--postgres-schema")
    migration_url, runtime_url, config_source = load_database_urls(args)
    config = RunConfig(
        concurrency=args.concurrency,
        warmups=args.warmups,
        iterations=args.iterations,
        rounds=args.rounds,
        batch_size=args.batch_size,
    )
    # Each worker keeps its ordinary profile connection while job_lifecycle
    # temporarily checks out one additional connection.
    current_pool_max = int(os.environ.get("DARKWEB_POSTGRES_POOL_MAX", "4"))
    os.environ["DARKWEB_POSTGRES_POOL_MIN"] = "1"
    os.environ["DARKWEB_POSTGRES_POOL_MAX"] = str(
        max(current_pool_max, config.concurrency * 2 + 4)
    )

    progress = lambda message: print(
        f"[business-composite-v2] {message}", file=sys.stderr, flush=True
    )
    progress("checking source hashes, schema identity, and durability")
    benchmark_id = uuid.uuid4().hex
    sqlite_hash_before = _sha256_file(sqlite_path)
    setup_info = connection_info(migration_url, "dwti-business-v2-setup-info")
    runtime_info = connection_info(runtime_url, "dwti-business-v2-runtime-info")
    if setup_info["database"] != runtime_info["database"]:
        raise WriteBenchmarkError(
            "setup and runtime URLs point to different databases"
        )
    if setup_info["fsync"].lower() != "on":
        raise WriteBenchmarkError("PostgreSQL fsync must remain on")
    if (
        setup_info["synchronous_commit"].lower() != "on"
        or runtime_info["synchronous_commit"].lower() != "on"
    ):
        raise WriteBenchmarkError(
            "PostgreSQL synchronous_commit must remain on"
        )
    leftovers_before = list_disposable_schemas(migration_url)
    if leftovers_before:
        raise WriteBenchmarkError(
            "pre-existing disposable schemas require manual review; none were deleted: "
            + ", ".join(leftovers_before)
        )
    postgres_before = source_schema_snapshot(migration_url, postgres_schema)
    fingerprint = _candidate_identity(postgres_before)

    benchmark_module = _shared_benchmark_module()
    registry = CleanupRegistry()
    sqlite_cleanup: list[dict[str, Any]] = []
    raw_results: dict[str, list[dict[str, Any]]] = {
        "sqlite": [],
        "postgresql": [],
    }
    contracts: dict[str, dict[str, Any] | None] = {
        "sqlite": None,
        "postgresql": None,
    }
    order_log: list[dict[str, Any]] = []

    for round_index in range(config.rounds):
        order = backend_order(round_index)
        order_log.append(
            {"round": round_index + 1, "backend_order": list(order)}
        )
        for backend in order:
            progress(
                f"round {round_index + 1}/{config.rounds}: {backend} supercycles"
            )
            if backend == "sqlite":
                target = SQLiteTarget(sqlite_path, benchmark_module)
                with target:
                    if contracts["sqlite"] is None:
                        contracts["sqlite"] = run_contracts(target)
                    result = run_business_composite(
                        target, config, benchmark_module
                    )
                sqlite_cleanup.append(
                    {
                        "round": round_index + 1,
                        "created": True,
                        "removed": target.temp_removed,
                    }
                )
            else:
                target = PostgresTarget(
                    migration_url=migration_url,
                    runtime_url=runtime_url,
                    source_schema=postgres_schema,
                    variant="candidate",
                    fingerprint=fingerprint,
                    registry=registry,
                )
                with target:
                    if contracts["postgresql"] is None:
                        contracts["postgresql"] = run_contracts(target)
                    result = run_business_composite(
                        target, config, benchmark_module
                    )
            raw_results[backend].append(
                {
                    "round": round_index + 1,
                    "metrics": result["metrics"],
                    "audit": result["audit"],
                }
            )

    close_postgres_pools()
    leftovers_after = list_disposable_schemas(migration_url)
    sqlite_hash_after = _sha256_file(sqlite_path)
    postgres_after = source_schema_snapshot(migration_url, postgres_schema)
    sqlite_contracts = contracts["sqlite"]
    postgres_contracts = contracts["postgresql"]
    if not isinstance(sqlite_contracts, dict) or not isinstance(
        postgres_contracts, dict
    ):
        raise WriteBenchmarkError("business contracts were not executed")
    equivalence = compare_contracts(sqlite_contracts, postgres_contracts)
    cleanup_records = registry.snapshot()
    source_binding = {
        "benchmark_id": benchmark_id,
        "sqlite": {
            "path": str(sqlite_path),
            "sha256": sqlite_hash_before,
        },
        "postgresql": {
            "database": setup_info["database"],
            "schema": postgres_schema,
            "schema_version": CANDIDATE_VERSION,
            "schema_fingerprint": fingerprint,
            "schema_snapshot_sha256": postgres_before["sha256"],
        },
    }
    section = {
        "format": SECTION_FORMAT,
        "format_version": SECTION_VERSION,
        "benchmark_id": benchmark_id,
        "generated_at": _utc_now(),
        "parameters": {
            "sqlite_database": str(sqlite_path),
            "postgres_schema": postgres_schema,
            "concurrency": config.concurrency,
            "warmups_per_worker": config.warmups,
            "iterations_per_worker": config.iterations,
            "rounds": config.rounds,
            "batch_size": config.batch_size,
            "workloads": list(WORKLOADS),
            "cycle_model": "one_each_in_workload_order",
            "source_databases_written": False,
        },
        "source_binding": source_binding,
        "connection": {
            "config_source": config_source,
            "setup": setup_info,
            "runtime": runtime_info,
            "pool_min": int(os.environ["DARKWEB_POSTGRES_POOL_MIN"]),
            "pool_max": int(os.environ["DARKWEB_POSTGRES_POOL_MAX"]),
            "credentials_in_report": False,
        },
        "durability": {
            "sqlite": "FULL",
            "postgresql": "fsync=on,synchronous_commit=on",
        },
        "active_release_observed": {
            key: active_release_config().get(key)
            for key in (
                "database_engine",
                "database_schema",
                "schema_version",
                "schema_fingerprint",
            )
        },
        "source_integrity": {
            "passed": (
                sqlite_hash_before == sqlite_hash_after
                and postgres_before["sha256"] == postgres_after["sha256"]
            ),
            "sqlite": {
                "sha256_before": sqlite_hash_before,
                "sha256_after": sqlite_hash_after,
            },
            "postgresql": {
                "schema": postgres_schema,
                "sha256_before": postgres_before["sha256"],
                "sha256_after": postgres_after["sha256"],
            },
        },
        "contracts": {
            "passed": equivalence["passed"],
            "equivalence": equivalence,
            "sqlite": sqlite_contracts,
            "postgresql": postgres_contracts,
        },
        "results": {
            backend: {"round_results": raw_results[backend]}
            for backend in ("sqlite", "postgresql")
        },
        "round_order": order_log,
        "temporary_targets": {
            "sqlite": {
                "records": sqlite_cleanup,
                "leftovers": [],
            },
            "postgresql": {
                "records": cleanup_records,
                "leftovers": leftovers_after,
            },
        },
    }
    section["gate"] = evaluate_business_composite_v2(section)
    return merge_base_report(args.base_report, output_path, section)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark one-each real-business supercycles on SQLite and "
            "PostgreSQL 0005 disposable targets"
        )
    )
    parser.add_argument("--sqlite-db", required=True, type=Path)
    parser.add_argument("--postgres-schema", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-report", type=Path)
    parser.add_argument(
        "--postgres-config",
        type=Path,
        default=Path.home()
        / ".local/share/darkweb-threat-intel/postgresql-target.json",
    )
    parser.add_argument("--migration-url")
    parser.add_argument("--runtime-url")
    parser.add_argument("--concurrency", type=_positive_int, default=CONCURRENCY)
    parser.add_argument(
        "--warmups", type=_non_negative_int, default=WARMUPS_PER_WORKER
    )
    parser.add_argument(
        "--iterations", type=_positive_int, default=ITERATIONS_PER_WORKER
    )
    parser.add_argument("--rounds", type=_positive_int, default=ROUNDS)
    parser.add_argument("--batch-size", type=_positive_int, default=BATCH_SIZE)
    parser.add_argument("--enforce-gate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = args.output.expanduser().resolve()
        report = run_benchmark(args)
        _write_json(output, report)
    except (WriteBenchmarkError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"[business-composite-v2] ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"[business-composite-v2] ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    section = report["business_composite_v2"]
    print(
        json.dumps(
            {
                "output": str(output),
                "business_composite_v2_passed": section["gate"]["passed"],
                "base_report_preserved": bool(args.base_report),
            },
            ensure_ascii=False,
        )
    )
    if args.enforce_gate and section["gate"]["passed"] is not True:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
