from __future__ import annotations

from datetime import datetime, timezone
import json
from threading import Lock
from typing import Any
import uuid

from darkweb_collector import db

from _writebench_core import RunConfig, WriteBenchmarkError, _prefix_sql


class _DummyConnection:
    def close(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def vulnerability_payload(key: str, version: int = 1) -> dict[str, Any]:
    return {
        "source_name": "__writebench_source__",
        "source_type": "public",
        "cve_id": key,
        "title": f"标题{version}",
        "vendor": "厂商",
        "product": "产品",
        "vulnerability_type": "RCE",
        "severity": "high",
        "cvss": 9.1,
        "is_exploited": True,
        "has_poc": True,
        "patch_available": False,
        "wide_impact": True,
        "disclosure_time": "2026-08-24T00:00:00+00:00",
        "affected_versions": ["1.0", "2.0"],
        "summary": f"摘要{version}",
        "advisory_url": "https://example.invalid/" + key,
        "reference_urls": ["https://ref.invalid/" + key],
        "last_seen_at": "2026-08-24T01:00:00+00:00",
        "extra_unicode": "测试",
    }


def ransomware_payload(key: str, version: int = 1) -> dict[str, Any]:
    return {
        "victim_id": key,
        "group_name": "group",
        "victim_name": f"受害者{version}",
        "website": "https://example.invalid",
        "country_code": "CN",
        "activity": "active",
        "discovered_at": "2026-08-24T00:00:00+00:00",
        "attacked_at": "2026-08-23T00:00:00+00:00",
        "post_url": "https://post.invalid/" + key,
        "permalink": "https://perma.invalid/" + key,
        "screenshot_url": "",
        "description": f"描述{version}",
        "press_url": "",
        "raw_json": {"id": key, "version": version},
        "last_seen_at": "2026-08-24T01:00:00+00:00",
    }


def victim_payload(prefix: str, index: int, *, with_detail: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "site_name": prefix,
        "source_url": "https://source.invalid/" + prefix,
        "detail_url": f"https://detail.invalid/{index}",
        "name": f"victim-{index}",
        "display_label": f"受害者{index}",
        "domain": "" if index % 2 == 0 else f"v{index}.invalid",
        "status": "published",
        "published_at_utc": "2026-08-24T00:00:00+00:00",
        "claimed_size": "1 GB",
        "claimed_size_gb": 1.0,
        "content_hash": f"{prefix}-{index}",
        "last_detail_fetch_status": "ok",
    }
    if with_detail:
        payload["detail"] = {
            "fetched_at_utc": "2026-08-24T01:00:00+00:00",
            "fetch_status": "ok",
            "page_title": "详情",
            "text_excerpt": "内容",
            "outbound_link_count": 1,
        }
    return payload


def topic_payload(prefix: str, index: int) -> dict[str, Any]:
    return {
        "site_name": prefix,
        "section": "databases",
        "title": f"主题{index}",
        "url": f"https://forum.invalid/{prefix}/{index}",
        "author": "作者",
        "replies": "1",
        "views": "2",
        "published_at": "2026-08-24",
        "last_reply_at": "2026-08-24",
        "content_hash": f"{prefix}-h{index}",
        "collected_at_utc": "2026-08-24T00:00:00+00:00",
    }


def detail_payload(prefix: str, index: int, victims: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    children = victims if victims is not None else [
        {
            "name": f"企业{child}",
            "industry": None if child % 2 == 0 else "制造",
            "region": None if child % 3 == 0 else "CN",
        }
        for child in range(5)
    ]
    return {
        "site_name": prefix,
        "section": "databases",
        "topic_url": f"https://forum.invalid/{prefix}/detail/{index}",
        "content": "正文",
        "authors": "作者",
        "timestamps": "时间",
        "attachments": "",
        "victims": children,
        "attackers": ["actor"],
        "content_hash": f"{prefix}-d{index}",
        "collected_at_utc": "2026-08-24T00:00:00+00:00",
    }


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


def victim_transaction(connection, paths, prefix: str) -> None:
    run_id = db.insert_collection_run(
        connection,
        {
            "site_name": prefix,
            "source_url": "https://source.invalid/" + prefix,
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "victim_count": 5,
        },
    )
    for index in range(5):
        payload = victim_payload(prefix, index, with_detail=index < 2)
        victim_id = paths.upsert_victim(connection, run_id, payload)
        if "detail" in payload:
            paths.insert_victim_detail(connection, victim_id, payload["detail"])


def topic_transaction(connection, paths, prefix: str) -> None:
    for index in range(5):
        paths.upsert_topic(connection, topic_payload(prefix, index))


def detail_transaction(connection, paths, prefix: str) -> None:
    for index in range(2):
        paths.upsert_detail(connection, detail_payload(prefix, index))


def _batch_transaction(connection, paths, workload: str, prefix: str, batch_size: int) -> None:
    if workload == "vulnerability":
        for index in range(batch_size):
            paths.upsert_vulnerability(connection, vulnerability_payload(f"{prefix}:{index}"))
        paths.mark_dirty(connection)
        return
    if workload == "ransomware":
        for index in range(batch_size):
            paths.upsert_ransomware(connection, ransomware_payload(f"{prefix}:{index}"))
        paths.mark_dirty(connection)
        return
    raise WriteBenchmarkError(f"not a batch workload: {workload}")


def run_profile(target, workload: str, config: RunConfig, benchmark_module) -> dict[str, Any]:
    """Run one workload and return latency metrics plus a post-commit audit."""

    if workload not in {
        "job_lifecycle", "dirty", "claim", "vulnerability", "ransomware",
        "victim", "topic", "detail",
    }:
        raise WriteBenchmarkError(f"unknown workload: {workload}")
    prefix = f"__wb_{target.variant}_{workload}_{uuid.uuid4().hex}"
    total = config.total_calls
    initial_revision = _state_revision(target) if workload in {
        "dirty", "vulnerability", "ransomware", "victim", "topic", "detail",
    } else None

    outcomes = {"true": 0, "false": 0}
    outcome_lock = Lock()

    if workload == "job_lifecycle":
        def operation(_dummy, worker: int, sequence: int) -> None:
            key = f"{prefix}:{worker}:{sequence}:{uuid.uuid4().hex}"
            now = datetime.now(timezone.utc).isoformat()
            first = target.connect()
            try:
                db.upsert_crawl_job(
                    first, job_id=key, site_name="writebench", job_type="seed",
                    queue_name="seed", target="writebench", status="running", started_at=now,
                )
                first.commit()
            finally:
                first.close()
            second = target.connect()
            try:
                db.upsert_crawl_job(
                    second, job_id=key, site_name="writebench", job_type="seed",
                    queue_name="seed", target="writebench", status="succeeded",
                    finished_at=now, duration_ms=1, error_message=None,
                )
                second.commit()
            finally:
                second.close()

        metrics = benchmark_module.run_concurrent(
            _DummyConnection, operation, concurrency=config.concurrency,
            warmups=config.warmups, iterations=config.iterations,
        )
        connection = target.connect()
        try:
            row = connection.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN status='succeeded' AND started_at IS NOT NULL "
                f"AND finished_at IS NOT NULL AND duration_ms=1 AND error_message IS NULL "
                f"THEN 1 ELSE 0 END) FROM crawl_jobs WHERE {_prefix_sql('job_id')}",
                (len(prefix), prefix),
            ).fetchone()
            actual = [int(row[0]), int(row[1] or 0)]
        finally:
            connection.close()
        audit = {
            "rows": actual[0], "succeeded_rows": actual[1], "expected_rows": total,
            "two_commits_per_job": True, "passed": actual == [total, total],
        }
        return {"metrics": metrics, "audit": audit}

    def operation(connection, worker: int, sequence: int) -> None:
        key = f"{prefix}:{worker}:{sequence}:{uuid.uuid4().hex}"
        if workload == "dirty":
            target.paths.mark_dirty(connection)
            connection.commit()
        elif workload == "claim":
            created = datetime.now(timezone.utc).isoformat()
            first = target.paths.claim(connection, key, key, created)
            connection.commit()
            second = target.paths.claim(connection, key, key, created + "-conflict")
            connection.commit()
            target.paths.release(connection, key, key)
            connection.commit()
            with outcome_lock:
                outcomes["true" if first else "false"] += 1
                outcomes["true" if second else "false"] += 1
        elif workload in {"vulnerability", "ransomware"}:
            _batch_transaction(connection, target.paths, workload, key, config.batch_size)
            connection.commit()
        elif workload == "victim":
            victim_transaction(connection, target.paths, key)
            connection.commit()
        elif workload == "topic":
            topic_transaction(connection, target.paths, key)
            connection.commit()
        else:
            detail_transaction(connection, target.paths, key)
            connection.commit()

    metrics = benchmark_module.run_concurrent(
        target.connect, operation, concurrency=config.concurrency,
        warmups=config.warmups, iterations=config.iterations,
    )
    audit: dict[str, Any]
    if workload == "dirty":
        delta = _state_revision(target) - int(initial_revision)
        audit = {"revision_delta": delta, "expected_revision_delta": total, "passed": delta == total}
    elif workload == "claim":
        remaining = _scalar(
            target,
            f"SELECT COUNT(*) FROM ai_aggregation_schedule_claims WHERE {_prefix_sql('profile_id')}",
            (len(prefix), prefix),
        )
        expected = {"true": total, "false": total}
        audit = {
            "outcomes": outcomes, "expected_outcomes": expected, "remaining_rows": remaining,
            "first_conflict_release_per_operation": True,
            "passed": outcomes == expected and remaining == 0,
        }
    elif workload in {"vulnerability", "ransomware"}:
        table = "vulnerability_records" if workload == "vulnerability" else "ransomware_live_victims"
        column = "cve_id" if workload == "vulnerability" else "victim_id"
        count = _scalar(
            target,
            f"SELECT COUNT(*) FROM {table} WHERE {_prefix_sql(column)}",
            (len(prefix), prefix),
        )
        delta = _state_revision(target) - int(initial_revision)
        audit = {
            "rows": count, "expected_rows": total * config.batch_size,
            "revision_delta": delta, "expected_revision_delta": total,
            "batch_size": config.batch_size,
            "passed": count == total * config.batch_size and delta == total,
        }
    elif workload == "victim":
        connection = target.connect()
        try:
            counts = [
                int(connection.execute(
                    f"SELECT COUNT(*) FROM collection_runs WHERE {_prefix_sql('site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]),
                int(connection.execute(
                    f"SELECT COUNT(*) FROM victims WHERE {_prefix_sql('site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]),
                int(connection.execute(
                    f"SELECT COUNT(*) FROM victim_details vd JOIN victims v ON v.id=vd.victim_id "
                    f"WHERE {_prefix_sql('v.site_name')}",
                    (len(prefix), prefix),
                ).fetchone()[0]),
            ]
        finally:
            connection.close()
        delta = _state_revision(target) - int(initial_revision)
        expected = [total, total * 5, total * 2]
        audit = {
            "rows": counts, "expected_rows": expected, "revision_delta": delta,
            "expected_revision_delta": total * 7, "batch_transaction": True,
            "passed": counts == expected and delta == total * 7,
        }
    elif workload == "topic":
        count = _scalar(
            target, f"SELECT COUNT(*) FROM forum_topics WHERE {_prefix_sql('site_name')}",
            (len(prefix), prefix),
        )
        delta = _state_revision(target) - int(initial_revision)
        audit = {
            "rows": count, "expected_rows": total * 5, "revision_delta": delta,
            "expected_revision_delta": total * 5, "batch_transaction": True,
            "passed": count == total * 5 and delta == total * 5,
        }
    else:
        connection = target.connect()
        try:
            parents = int(connection.execute(
                f"SELECT COUNT(*) FROM forum_details WHERE {_prefix_sql('site_name')}",
                (len(prefix), prefix),
            ).fetchone()[0])
            children = int(connection.execute(
                f"SELECT COUNT(*) FROM forum_victims fv JOIN forum_details fd "
                f"ON fd.id=fv.forum_detail_id WHERE {_prefix_sql('fd.site_name')}",
                (len(prefix), prefix),
            ).fetchone()[0])
        finally:
            connection.close()
        delta = _state_revision(target) - int(initial_revision)
        expected = [total * 2, total * 10]
        audit = {
            "rows": [parents, children], "expected_rows": expected,
            "revision_delta": delta, "expected_revision_delta": total * 2,
            "batch_transaction": True,
            "passed": [parents, children] == expected and delta == total * 2,
        }
    return {"metrics": metrics, "audit": audit}

