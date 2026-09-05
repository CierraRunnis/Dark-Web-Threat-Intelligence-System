from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any
import uuid

from darkweb_collector import db
from darkweb_collector.postgres_write_gate import WORKLOADS

from _writebench_core import RunConfig, WriteBenchmarkError, _prefix_sql
from _writebench_profiles import (
    _batch_transaction,
    detail_transaction,
    topic_transaction,
    victim_transaction,
)


REVISION_INCREMENTS_PER_CYCLE = 17


def _state_revision(target) -> int:
    connection = target.connect()
    try:
        row = connection.execute(
            "SELECT source_revision FROM normalized_intelligence_cache_state WHERE id=1"
        ).fetchone()
        if row is None:
            raise WriteBenchmarkError("normalization state is missing")
        return int(row[0])
    finally:
        connection.close()


def _scalar(target, sql_text: str, parameters: tuple[Any, ...] = ()) -> int:
    connection = target.connect()
    try:
        row = connection.execute(sql_text, parameters).fetchone()
        return int(row[0]) if row is not None else 0
    finally:
        connection.close()


def _job_lifecycle(target, key: str) -> None:
    """Persist running and terminal audit states in two independent checkouts."""

    now = datetime.now(timezone.utc).isoformat()
    running = target.connect()
    try:
        db.upsert_crawl_job(
            running,
            job_id=key,
            site_name="writebench",
            job_type="seed",
            queue_name="seed",
            target="writebench",
            status="running",
            started_at=now,
        )
        running.commit()
    finally:
        running.close()

    finished = target.connect()
    try:
        db.upsert_crawl_job(
            finished,
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
        finished.commit()
    finally:
        finished.close()


def execute_supercycle(
    connection,
    target,
    key: str,
    outcomes: dict[str, int],
    outcome_lock: Lock,
    batch_size: int = 5,
) -> None:
    """Execute one of every real write profile without merging transactions."""

    # job_lifecycle: two independent connections and two durable audit commits.
    _job_lifecycle(target, f"{key}:job")

    # dirty: one revision and one caller-owned transaction.
    target.paths.mark_dirty(connection)
    connection.commit()

    # claim: a persistent first claim, a duplicate that rolls back only its own
    # failed transaction, and an independently committed release.
    claim_key = f"{key}:claim"
    created = datetime.now(timezone.utc).isoformat()
    first = target.paths.claim(connection, claim_key, claim_key, created)
    connection.commit()
    second = target.paths.claim(connection, claim_key, claim_key, created + "-conflict")
    connection.commit()
    target.paths.release(connection, claim_key, claim_key)
    connection.commit()
    with outcome_lock:
        outcomes["true" if first else "false"] += 1
        outcomes["true" if second else "false"] += 1

    # The remaining five profiles retain the exact batch and transaction
    # boundaries used by run_profile().
    _batch_transaction(
        connection, target.paths, "vulnerability", f"{key}:vulnerability", batch_size
    )
    connection.commit()
    _batch_transaction(
        connection, target.paths, "ransomware", f"{key}:ransomware", batch_size
    )
    connection.commit()
    victim_transaction(connection, target.paths, f"{key}:victim")
    connection.commit()
    topic_transaction(connection, target.paths, f"{key}:topic")
    connection.commit()
    detail_transaction(connection, target.paths, f"{key}:detail")
    connection.commit()


def _audit_supercycles(
    target,
    prefix: str,
    *,
    total_cycles: int,
    initial_revision: int,
    outcomes: dict[str, int],
    batch_size: int,
) -> dict[str, Any]:
    connection = target.connect()
    try:
        job = connection.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN status='succeeded' "
            f"AND started_at IS NOT NULL AND finished_at IS NOT NULL "
            f"AND duration_ms=1 AND error_message IS NULL THEN 1 ELSE 0 END) "
            f"FROM crawl_jobs WHERE {_prefix_sql('job_id')}",
            (len(prefix), prefix),
        ).fetchone()
        job_counts = [int(job[0]), int(job[1] or 0)]

        vulnerability_rows = int(
            connection.execute(
                f"SELECT COUNT(*) FROM vulnerability_records "
                f"WHERE {_prefix_sql('cve_id')}",
                (len(prefix), prefix),
            ).fetchone()[0]
        )
        ransomware_rows = int(
            connection.execute(
                f"SELECT COUNT(*) FROM ransomware_live_victims "
                f"WHERE {_prefix_sql('victim_id')}",
                (len(prefix), prefix),
            ).fetchone()[0]
        )
        victim_counts = [
            int(
                connection.execute(
                    f"SELECT COUNT(*) FROM collection_runs "
                    f"WHERE {_prefix_sql('site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]
            ),
            int(
                connection.execute(
                    f"SELECT COUNT(*) FROM victims WHERE {_prefix_sql('site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]
            ),
            int(
                connection.execute(
                    f"SELECT COUNT(*) FROM victim_details vd "
                    f"JOIN victims v ON v.id=vd.victim_id "
                    f"WHERE {_prefix_sql('v.site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]
            ),
        ]
        topic_rows = int(
            connection.execute(
                f"SELECT COUNT(*) FROM forum_topics WHERE {_prefix_sql('site_name')}",
                (len(prefix), prefix),
            ).fetchone()[0]
        )
        detail_counts = [
            int(
                connection.execute(
                    f"SELECT COUNT(*) FROM forum_details "
                    f"WHERE {_prefix_sql('site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]
            ),
            int(
                connection.execute(
                    f"SELECT COUNT(*) FROM forum_victims fv "
                    f"JOIN forum_details fd ON fd.id=fv.forum_detail_id "
                    f"WHERE {_prefix_sql('fd.site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]
            ),
        ]
        claim_rows = int(
            connection.execute(
                f"SELECT COUNT(*) FROM ai_aggregation_schedule_claims "
                f"WHERE {_prefix_sql('profile_id')}",
                (len(prefix), prefix),
            ).fetchone()[0]
        )
        revision_row = connection.execute(
            "SELECT source_revision FROM normalized_intelligence_cache_state WHERE id=1"
        ).fetchone()
        revision_delta = int(revision_row[0]) - initial_revision
    finally:
        connection.close()

    expected_claims = {"true": total_cycles, "false": total_cycles}
    expected_revision = total_cycles * REVISION_INCREMENTS_PER_CYCLE
    workloads = {
        "job_lifecycle": {
            "rows": job_counts,
            "expected_rows": [total_cycles, total_cycles],
            "two_independent_commits": True,
            "audit_rows_preserved": True,
            "passed": job_counts == [total_cycles, total_cycles],
        },
        "dirty": {
            "composite_revision_delta": revision_delta,
            "expected_composite_revision_delta": expected_revision,
            "passed": revision_delta == expected_revision,
        },
        "claim": {
            "outcomes": dict(outcomes),
            "expected_outcomes": expected_claims,
            "remaining_rows": claim_rows,
            "claim_conflict_release": True,
            "passed": outcomes == expected_claims and claim_rows == 0,
        },
        "vulnerability": {
            "rows": vulnerability_rows,
            "expected_rows": total_cycles * batch_size,
            "batch_size": batch_size,
            "passed": vulnerability_rows == total_cycles * batch_size,
        },
        "ransomware": {
            "rows": ransomware_rows,
            "expected_rows": total_cycles * batch_size,
            "batch_size": batch_size,
            "passed": ransomware_rows == total_cycles * batch_size,
        },
        "victim": {
            "rows": victim_counts,
            "expected_rows": [total_cycles, total_cycles * 5, total_cycles * 2],
            "batch_transaction": True,
            "passed": victim_counts
            == [total_cycles, total_cycles * 5, total_cycles * 2],
        },
        "topic": {
            "rows": topic_rows,
            "expected_rows": total_cycles * 5,
            "batch_transaction": True,
            "passed": topic_rows == total_cycles * 5,
        },
        "detail": {
            "rows": detail_counts,
            "expected_rows": [total_cycles * 2, total_cycles * 10],
            "batch_transaction": True,
            "passed": detail_counts == [total_cycles * 2, total_cycles * 10],
        },
    }
    return {
        "passed": all(item["passed"] is True for item in workloads.values()),
        "total_cycles": total_cycles,
        "revision_delta": revision_delta,
        "expected_revision_delta": expected_revision,
        "workload_order": list(WORKLOADS),
        "workloads": workloads,
    }


def run_business_composite(target, config: RunConfig, benchmark_module) -> dict[str, Any]:
    """Measure fixed one-each business supercycles and return a full raw audit."""

    prefix = f"__bcv2_{target.variant}_{uuid.uuid4().hex}"
    initial_revision = _state_revision(target)
    outcomes = {"true": 0, "false": 0}
    outcome_lock = Lock()

    def operation(connection, worker: int, sequence: int) -> None:
        key = f"{prefix}:{worker}:{sequence}:{uuid.uuid4().hex}"
        execute_supercycle(connection, target, key, outcomes, outcome_lock)

    metrics = benchmark_module.run_concurrent(
        target.connect,
        operation,
        concurrency=config.concurrency,
        warmups=config.warmups,
        iterations=config.iterations,
    )
    audit = _audit_supercycles(
        target,
        prefix,
        total_cycles=config.total_calls,
        initial_revision=initial_revision,
        outcomes=outcomes,
        batch_size=config.batch_size,
    )
    return {"metrics": metrics, "audit": audit}


__all__ = [
    "REVISION_INCREMENTS_PER_CYCLE",
    "execute_supercycle",
    "run_business_composite",
]
