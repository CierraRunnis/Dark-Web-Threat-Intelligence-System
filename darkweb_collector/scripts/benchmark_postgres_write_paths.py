#!/usr/bin/env python3
"""Run the isolated PostgreSQL 0004/0005 real-business write benchmark."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
import sys
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
SRC = ROOT / "src"
for path in (SCRIPT_DIR, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _writebench_contracts import compare_contracts, run_contracts  # noqa: E402
from _writebench_core import (  # noqa: E402
    BASELINE_VERSION,
    CANDIDATE_VERSION,
    DEFAULT_BATCH_SIZE,
    DEFAULT_CONCURRENCY,
    DEFAULT_ITERATIONS,
    DEFAULT_ROUNDS,
    DEFAULT_WARMUPS,
    RECOVERED_SCRIPT_PROVENANCE,
    REPORT_FORMAT,
    REPORT_VERSION,
    RunConfig,
    WriteBenchmarkError,
    _median_summary,
    _non_negative_int,
    _positive_int,
    _sha256_file,
    _shared_benchmark_module,
    _source_identifier,
    _utc_now,
    variant_order,
)
from _writebench_profiles import run_profile  # noqa: E402
from _writebench_targets import (  # noqa: E402
    CleanupRegistry,
    PostgresTarget,
    SQLiteTarget,
    connection_info,
    list_disposable_schemas,
    source_schema_snapshot,
)
from darkweb_collector.migration_bundle import _runtime_role_from_url  # noqa: E402
from darkweb_collector.postgres_write_gate import (  # noqa: E402,F401
    WORKLOADS,
    evaluate_postgres_write_paths,
)
from darkweb_collector.postgres_backend import close_postgres_pools  # noqa: E402
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
            raise WriteBenchmarkError(f"cannot read PostgreSQL config: {config_path}") from exc
        if isinstance(parsed, dict):
            payload = parsed
    migration_url = str(args.migration_url or payload.get("migration_database_url") or "")
    runtime_url = str(args.runtime_url or payload.get("runtime_database_url") or "")
    migration_url = _postgres_url(migration_url, "migration URL")
    runtime_url = _postgres_url(runtime_url, "runtime URL")
    if _runtime_role_from_url(migration_url) == _runtime_role_from_url(runtime_url):
        raise WriteBenchmarkError("migration/setup and runtime PostgreSQL roles must be different")
    return migration_url, runtime_url, str(config_path)


def _migration_map(snapshot: dict[str, Any]) -> dict[str, tuple[str, str]]:
    rows = snapshot.get("summary", {}).get("migrations", [])
    return {str(row[0]): (str(row[1]), str(row[2])) for row in rows}


def validate_source_pair(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_version: str,
    candidate_version: str,
) -> str:
    baseline_migrations = _migration_map(baseline)
    candidate_migrations = _migration_map(candidate)
    if baseline_version not in baseline_migrations:
        raise WriteBenchmarkError(f"baseline schema is missing {baseline_version}")
    if candidate_version not in candidate_migrations:
        raise WriteBenchmarkError(f"candidate schema is missing {candidate_version}")
    baseline_fingerprint = baseline_migrations.get("0001_baseline", ("", ""))[1]
    candidate_fingerprint = candidate_migrations.get("0001_baseline", ("", ""))[1]
    if not baseline_fingerprint or baseline_fingerprint != candidate_fingerprint:
        raise WriteBenchmarkError("baseline and candidate schema fingerprints differ")
    return baseline_fingerprint


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


def merge_base_report(base_path: Path | None, output_path: Path, section: dict[str, Any]) -> dict[str, Any]:
    output = output_path.expanduser().resolve()
    if base_path is None:
        return {
            "format": REPORT_FORMAT,
            "format_version": REPORT_VERSION,
            "generated_at": _utc_now(),
            "postgres_write_paths": section,
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
    merged["postgres_write_paths"] = section
    return merged


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    sqlite_path = args.sqlite_db.expanduser().resolve(strict=True)
    if not sqlite_path.is_file():
        raise WriteBenchmarkError(f"SQLite source is not a file: {sqlite_path}")
    output_path = args.output.expanduser().resolve()
    if output_path == sqlite_path:
        raise WriteBenchmarkError("--output must not overwrite --sqlite-db")
    baseline_schema = _source_identifier(args.baseline_schema, "--baseline-schema")
    candidate_schema = _source_identifier(args.candidate_schema, "--candidate-schema")
    if baseline_schema == candidate_schema:
        raise WriteBenchmarkError("baseline and candidate schemas must differ")
    migration_url, runtime_url, config_source = load_database_urls(args)
    config = RunConfig(
        concurrency=args.concurrency,
        warmups=args.warmups,
        iterations=args.iterations,
        rounds=args.rounds,
        batch_size=args.batch_size,
    )
    current_pool_max = int(os.environ.get("DARKWEB_POSTGRES_POOL_MAX", "4"))
    os.environ["DARKWEB_POSTGRES_POOL_MIN"] = "1"
    os.environ["DARKWEB_POSTGRES_POOL_MAX"] = str(max(current_pool_max, config.concurrency + 4))

    progress = lambda message: print(f"[write-path-benchmark] {message}", file=sys.stderr, flush=True)
    progress("checking source hashes and PostgreSQL identities")
    sqlite_hash_before = _sha256_file(sqlite_path)
    setup_info = connection_info(migration_url, "dwti-writebench-setup-info")
    runtime_info = connection_info(runtime_url, "dwti-writebench-runtime-info")
    if setup_info["database"] != runtime_info["database"]:
        raise WriteBenchmarkError("setup and runtime URLs point to different databases")
    if setup_info["fsync"].lower() != "on" or setup_info["synchronous_commit"].lower() != "on":
        raise WriteBenchmarkError("PostgreSQL durability settings must remain enabled")
    if runtime_info["synchronous_commit"].lower() != "on":
        raise WriteBenchmarkError("runtime synchronous_commit must remain on")
    leftovers_before = list_disposable_schemas(migration_url)
    if leftovers_before:
        raise WriteBenchmarkError(
            "pre-existing disposable schemas require manual review; none were deleted: "
            + ", ".join(leftovers_before)
        )
    baseline_before = source_schema_snapshot(migration_url, baseline_schema)
    candidate_before = source_schema_snapshot(migration_url, candidate_schema)
    fingerprint = validate_source_pair(
        baseline_before,
        candidate_before,
        baseline_version=args.baseline_version,
        candidate_version=args.candidate_version,
    )

    benchmark_module = _shared_benchmark_module()
    sqlite_results: dict[str, Any] = {}
    progress("SQLite contracts and one isolated profile round")
    sqlite_target = SQLiteTarget(sqlite_path, benchmark_module)
    with sqlite_target:
        sqlite_contracts = run_contracts(sqlite_target)
        for workload in WORKLOADS:
            progress(f"SQLite {workload}")
            sqlite_results[workload] = _median_summary([
                run_profile(sqlite_target, workload, config, benchmark_module)
            ])

    registry = CleanupRegistry()
    postgres_rounds: dict[str, dict[str, list[dict[str, Any]]]] = {
        variant: {workload: [] for workload in WORKLOADS}
        for variant in ("baseline", "candidate")
    }
    order_log: list[dict[str, Any]] = []
    baseline_contracts: dict[str, Any] | None = None
    candidate_contracts: dict[str, Any] | None = None
    for round_index in range(config.rounds):
        progress(f"PostgreSQL round {round_index + 1}/{config.rounds}: cloning disposable schemas")
        with PostgresTarget(
            migration_url=migration_url, runtime_url=runtime_url,
            source_schema=baseline_schema, variant="baseline",
            fingerprint=fingerprint, registry=registry,
        ) as baseline_target, PostgresTarget(
            migration_url=migration_url, runtime_url=runtime_url,
            source_schema=candidate_schema, variant="candidate",
            fingerprint=fingerprint, registry=registry,
        ) as candidate_target:
            targets = {"baseline": baseline_target, "candidate": candidate_target}
            if round_index == 0:
                progress("running baseline and candidate business contracts")
                baseline_contracts = run_contracts(baseline_target)
                candidate_contracts = run_contracts(candidate_target)
            for workload_index, workload in enumerate(WORKLOADS):
                order = variant_order(round_index, workload_index)
                order_log.append({
                    "round": round_index + 1, "workload": workload, "variant_order": list(order),
                })
                for variant in order:
                    progress(f"round {round_index + 1} {variant} {workload}")
                    postgres_rounds[variant][workload].append(
                        run_profile(targets[variant], workload, config, benchmark_module)
                    )
            baseline_target._record["connections_opened"] = baseline_target.connections_opened
            candidate_target._record["connections_opened"] = candidate_target.connections_opened

    close_postgres_pools()
    leftovers_after = list_disposable_schemas(migration_url)
    sqlite_hash_after = _sha256_file(sqlite_path)
    baseline_after = source_schema_snapshot(migration_url, baseline_schema)
    candidate_after = source_schema_snapshot(migration_url, candidate_schema)
    source_integrity = {
        "passed": (
            sqlite_hash_before == sqlite_hash_after
            and baseline_before["sha256"] == baseline_after["sha256"]
            and candidate_before["sha256"] == candidate_after["sha256"]
        ),
        "sqlite": {"sha256_before": sqlite_hash_before, "sha256_after": sqlite_hash_after},
        "postgresql": {
            "baseline": {"sha256_before": baseline_before["sha256"], "sha256_after": baseline_after["sha256"]},
            "candidate": {"sha256_before": candidate_before["sha256"], "sha256_after": candidate_after["sha256"]},
        },
    }
    if baseline_contracts is None or candidate_contracts is None:
        raise WriteBenchmarkError("PostgreSQL contracts were not executed")
    equivalence = compare_contracts(sqlite_contracts, baseline_contracts, candidate_contracts)
    contracts = {
        "passed": equivalence["passed"],
        "equivalence": equivalence,
        "sqlite": sqlite_contracts,
        "baseline": baseline_contracts,
        "candidate": candidate_contracts,
    }
    records = registry.snapshot()
    cleanup = {
        "prefix": "dwti_writebench_",
        "created": sum(1 for item in records if item.get("created")),
        "dropped": sum(1 for item in records if item.get("dropped")),
        "records": records,
        "leftovers": leftovers_after,
    }
    results = {
        "sqlite": sqlite_results,
        "baseline": {key: _median_summary(value) for key, value in postgres_rounds["baseline"].items()},
        "candidate": {key: _median_summary(value) for key, value in postgres_rounds["candidate"].items()},
    }
    section = {
        "format_version": REPORT_VERSION,
        "generated_at": _utc_now(),
        "parameters": {
            "sqlite_database": str(sqlite_path),
            "baseline_schema": baseline_schema,
            "candidate_schema": candidate_schema,
            "baseline_version": args.baseline_version,
            "candidate_version": args.candidate_version,
            "concurrency": config.concurrency,
            "warmups_per_worker": config.warmups,
            "iterations_per_worker": config.iterations,
            "postgres_rounds": config.rounds,
            "batch_size": config.batch_size,
            "source_databases_written": False,
            "workloads": list(WORKLOADS),
        },
        "connection": {
            "config_source": config_source,
            "setup": setup_info,
            "runtime": runtime_info,
            "pool_min": int(os.environ["DARKWEB_POSTGRES_POOL_MIN"]),
            "pool_max": int(os.environ["DARKWEB_POSTGRES_POOL_MAX"]),
            "credentials_in_report": False,
        },
        "durability": {"sqlite": "FULL", "postgresql": "fsync=on,synchronous_commit=on"},
        "active_release_observed": {
            key: active_release_config().get(key)
            for key in ("database_engine", "database_schema", "schema_version", "schema_fingerprint")
        },
        "provenance": RECOVERED_SCRIPT_PROVENANCE,
        "source_integrity": source_integrity,
        "contracts": contracts,
        "results": results,
        "round_order": order_log,
        "sqlite_temporary_backup_removed": sqlite_target.temp_removed,
        "temporary_schemas": cleanup,
    }
    section["gate"] = evaluate_postgres_write_paths(section)
    return merge_base_report(args.base_report, output_path, section)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark 0004 versus 0005 business writes in disposable PostgreSQL schemas",
    )
    parser.add_argument("--sqlite-db", required=True, type=Path)
    parser.add_argument("--baseline-schema", required=True)
    parser.add_argument("--candidate-schema", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-report", type=Path)
    parser.add_argument(
        "--postgres-config", type=Path,
        default=Path.home() / ".local/share/darkweb-threat-intel/postgresql-target.json",
    )
    parser.add_argument("--migration-url", help="optional setup URL override; never written to reports")
    parser.add_argument("--runtime-url", help="optional runtime URL override; never written to reports")
    parser.add_argument("--baseline-version", default=BASELINE_VERSION)
    parser.add_argument("--candidate-version", default=CANDIDATE_VERSION)
    parser.add_argument("--concurrency", type=_positive_int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("--warmups", type=_non_negative_int, default=DEFAULT_WARMUPS)
    parser.add_argument("--iterations", type=_positive_int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--rounds", type=_positive_int, default=DEFAULT_ROUNDS)
    parser.add_argument("--batch-size", type=_positive_int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--enforce-gate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = args.output.expanduser().resolve()
        report = run_benchmark(args)
        _write_json(output, report)
    except (WriteBenchmarkError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"[write-path-benchmark] ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[write-path-benchmark] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    section = report["postgres_write_paths"]
    print(json.dumps({
        "output": str(args.output.expanduser().resolve()),
        "postgres_write_paths_passed": section["gate"]["passed"],
        "base_report_preserved": bool(args.base_report),
    }, ensure_ascii=False))
    if args.enforce_gate and section["gate"]["passed"] is not True:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

