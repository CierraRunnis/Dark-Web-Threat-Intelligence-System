from __future__ import annotations

from typing import Any
import uuid

from darkweb_collector import db

from _writebench_profiles import (
    detail_payload,
    ransomware_payload,
    topic_payload,
    victim_payload,
    vulnerability_payload,
)


def _state(connection) -> tuple[Any, ...]:
    row = connection.execute(
        "SELECT source_signature, source_revision, applied_revision, dirty_since, dirty_at "
        "FROM normalized_intelligence_cache_state WHERE id=1"
    ).fetchone()
    return tuple(row[index] for index in range(len(row)))


def _dirty_contract(target) -> dict[str, Any]:
    connection = target.connect()
    try:
        initial = _state(connection)
        first = target.paths.mark_dirty(connection, "2001-01-01T00:00:00+00:00")
        connection.commit()
        after_first = _state(connection)
        second = target.paths.mark_dirty(connection, "2001-01-02T00:00:00+00:00")
        connection.commit()
        after_second = _state(connection)
        before_rollback = _state(connection)
        target.paths.mark_dirty(connection, "2001-01-03T00:00:00+00:00")
        connection.rollback()
        rollback = _state(connection) == before_rollback
    finally:
        connection.close()
    first_since = (
        initial[3]
        if int(initial[1]) > int(initial[2]) and str(initial[3] or "")
        else "2001-01-01T00:00:00+00:00"
    )
    passed = (
        first == int(initial[1]) + 1
        and second == int(initial[1]) + 2
        and after_first[0] == initial[0] == after_second[0]
        and after_first[2] == initial[2] == after_second[2]
        and after_first[3] == first_since == after_second[3]
        and after_first[4] == "2001-01-01T00:00:00+00:00"
        and after_second[4] == "2001-01-02T00:00:00+00:00"
        and rollback
    )
    return {
        "passed": passed,
        "revision_deltas": [first - int(initial[1]), second - first],
        "source_signature_preserved": after_second[0] == initial[0],
        "applied_revision_preserved": after_second[2] == initial[2],
        "first_dirty_since_preserved": after_second[3] == first_since,
        "latest_dirty_at": after_second[4] == "2001-01-02T00:00:00+00:00",
        "rollback": rollback,
    }


def _claim_contract(target) -> dict[str, Any]:
    token = "__writebench_claim_contract_" + uuid.uuid4().hex
    slot = "2030-01-01T00:00:00+00:00"
    connection = target.connect()
    try:
        first = target.paths.claim(connection, token, slot, "2002-01-01T00:00:00+00:00")
        connection.commit()
        second = target.paths.claim(connection, token, slot, "2002-01-02T00:00:00+00:00")
        connection.commit()
        row = connection.execute(
            "SELECT created_at FROM ai_aggregation_schedule_claims WHERE profile_id=? AND scheduled_for=?",
            (token, slot),
        ).fetchone()
        preserved = row is not None and row[0] == "2002-01-01T00:00:00+00:00"
        target.paths.release(connection, token, slot)
        connection.commit()
        released = connection.execute(
            "SELECT 1 FROM ai_aggregation_schedule_claims WHERE profile_id=? AND scheduled_for=?",
            (token, slot),
        ).fetchone() is None
        third = target.paths.claim(connection, token, slot, "2002-01-03T00:00:00+00:00")
        connection.commit()
        target.paths.claim(connection, token + "_rollback", slot, "2002-01-04T00:00:00+00:00")
        connection.rollback()
        rolled_back = connection.execute(
            "SELECT 1 FROM ai_aggregation_schedule_claims WHERE profile_id=? AND scheduled_for=?",
            (token + "_rollback", slot),
        ).fetchone() is None
    finally:
        connection.close()
    passed = [first, second, third] == [True, False, True] and preserved and released and rolled_back
    return {
        "passed": passed, "outcomes": [first, second, third],
        "created_at_preserved": preserved, "release_reclaim": released and third,
        "rollback": rolled_back,
    }


def _job_contract(target) -> dict[str, Any]:
    token = "__writebench_job_contract_" + uuid.uuid4().hex
    running = target.connect()
    try:
        db.upsert_crawl_job(
            running, job_id=token, site_name="contract", job_type="seed", queue_name="seed",
            target="contract", status="running", started_at="2003-01-01T00:00:00+00:00",
        )
        running.commit()
    finally:
        running.close()
    observer = target.connect()
    try:
        visible = observer.execute("SELECT status FROM crawl_jobs WHERE job_id=?", (token,)).fetchone()
        running_visible = visible is not None and visible[0] == "running"
        db.upsert_crawl_job(
            observer, job_id=token, site_name="contract", job_type="seed", queue_name="seed",
            target="contract", status="succeeded", finished_at="2003-01-01T00:01:00+00:00",
            duration_ms=1, error_message=None,
        )
        observer.commit()
    finally:
        observer.close()
    failed_token = token + "_failed"
    failure = target.connect()
    try:
        db.upsert_crawl_job(
            failure, job_id=failed_token, site_name="contract", job_type="seed", queue_name="seed",
            target="contract", status="running", started_at="2003-01-01T00:00:00+00:00",
        )
        failure.commit()
        db.upsert_crawl_job(
            failure, job_id=failed_token, site_name="contract", job_type="seed", queue_name="seed",
            target="contract", status="failed", finished_at="2003-01-01T00:01:00+00:00",
            duration_ms=1, error_message="expected",
        )
        failure.commit()
        rows = failure.execute(
            "SELECT job_id, status FROM crawl_jobs WHERE job_id IN (?, ?) ORDER BY job_id",
            (token, failed_token),
        ).fetchall()
    finally:
        failure.close()
    statuses = sorted(str(row[1]) for row in rows)
    passed = running_visible and statuses == ["failed", "succeeded"]
    return {
        "passed": passed, "running_visible_across_connections": running_visible,
        "two_independent_commits": True, "success_and_failure_audit_rows": statuses,
    }


def _record_contract(target, workload: str) -> dict[str, Any]:
    token = f"__writebench_{workload}_contract_{uuid.uuid4().hex}"
    payload_factory = vulnerability_payload if workload == "vulnerability" else ransomware_payload
    upsert = target.paths.upsert_vulnerability if workload == "vulnerability" else target.paths.upsert_ransomware
    table = "vulnerability_records" if workload == "vulnerability" else "ransomware_live_victims"
    key_column = "cve_id" if workload == "vulnerability" else "victim_id"
    connection = target.connect()
    try:
        initial = _state(connection)
        first_id = upsert(connection, payload_factory(token, 1))
        target.paths.mark_dirty(connection)
        connection.commit()
        second_id = upsert(connection, payload_factory(token, 2))
        target.paths.mark_dirty(connection)
        connection.commit()
        persisted = connection.execute(
            f"SELECT id FROM {table} WHERE {key_column}=?", (token,)
        ).fetchone()
        before = _state(connection)
        upsert(connection, payload_factory(token + "_rollback", 3))
        target.paths.mark_dirty(connection)
        connection.rollback()
        rollback_absent = connection.execute(
            f"SELECT 1 FROM {table} WHERE {key_column}=?", (token + "_rollback",)
        ).fetchone() is None
        rollback_state = _state(connection) == before
    finally:
        connection.close()
    passed = (
        first_id == second_id == int(persisted[0])
        and int(before[1]) - int(initial[1]) == 2
        and rollback_absent and rollback_state
    )
    return {
        "passed": passed, "stable_id": first_id == second_id,
        "revision_delta": int(before[1]) - int(initial[1]),
        "rollback": rollback_absent and rollback_state,
    }


def _victim_contract(target) -> dict[str, Any]:
    token = "__writebench_victim_contract_" + uuid.uuid4().hex
    connection = target.connect()
    try:
        run1 = db.insert_collection_run(connection, {
            "site_name": token, "source_url": "x", "collected_at_utc": "t1", "victim_count": 1,
        })
        first = victim_payload(token, 0, with_detail=False)
        first["domain"] = ""
        first["last_detail_fetch_status"] = "old"
        first_id = target.paths.upsert_victim(connection, run1, first)
        connection.commit()
        run2 = db.insert_collection_run(connection, {
            "site_name": token, "source_url": "x", "collected_at_utc": "t2", "victim_count": 1,
        })
        second = dict(first)
        second["domain"] = None
        second["display_label"] = "更新"
        second["last_detail_fetch_status"] = None
        second_id = target.paths.upsert_victim(connection, run2, second)
        connection.commit()
        row = connection.execute(
            "SELECT first_seen_run_id, last_seen_run_id, last_detail_fetch_status, display_label "
            "FROM victims WHERE id=?", (first_id,),
        ).fetchone()
        before = _state(connection)
        run3 = db.insert_collection_run(connection, {
            "site_name": token, "source_url": "x", "collected_at_utc": "t3", "victim_count": 1,
        })
        target.paths.upsert_victim(connection, run3, victim_payload(token, 9, with_detail=False))
        connection.rollback()
        rollback = _state(connection) == before and connection.execute(
            "SELECT 1 FROM collection_runs WHERE id=?", (run3,),
        ).fetchone() is None
    finally:
        connection.close()
    passed = (
        first_id == second_id and int(row[0]) == run1 and int(row[1]) == run2
        and row[2] == "old" and row[3] == "更新" and rollback
    )
    return {
        "passed": passed, "null_empty_same_id": first_id == second_id,
        "first_seen_preserved": int(row[0]) == run1, "last_seen_updated": int(row[1]) == run2,
        "null_status_preserved": row[2] == "old", "rollback": rollback,
    }


def _topic_contract(target) -> dict[str, Any]:
    token = "__writebench_topic_contract_" + uuid.uuid4().hex
    connection = target.connect()
    try:
        base = int(_state(connection)[1])
        payload = topic_payload(token, 0)
        first_id = target.paths.upsert_topic(connection, payload)
        connection.commit()
        r1 = int(_state(connection)[1])
        payload.update(replies="2", views="3", collected_at_utc="t2")
        second_id = target.paths.upsert_topic(connection, payload)
        connection.commit()
        r2 = int(_state(connection)[1])
        payload.update(title="changed", collected_at_utc="t3")
        target.paths.upsert_topic(connection, payload)
        connection.commit()
        r3 = int(_state(connection)[1])
        payload.update(content_hash="changed-hash", collected_at_utc="t4")
        target.paths.upsert_topic(connection, payload)
        connection.commit()
        r4 = int(_state(connection)[1])
        before = _state(connection)
        payload.update(title="rollback", collected_at_utc="t5")
        target.paths.upsert_topic(connection, payload)
        connection.rollback()
        rollback = _state(connection) == before
    finally:
        connection.close()
    deltas = [r1 - base, r2 - r1, r3 - r2, r4 - r3]
    passed = first_id == second_id and deltas == [1, 0, 1, 1] and rollback
    return {"passed": passed, "stable_id": first_id == second_id, "revision_deltas": deltas, "rollback": rollback}


def _children(connection, detail_id: int) -> list[tuple[Any, ...]]:
    rows = connection.execute(
        "SELECT victim_name, industry, region FROM forum_victims "
        "WHERE forum_detail_id=? ORDER BY id", (detail_id,),
    ).fetchall()
    return [tuple(row[index] for index in range(len(row))) for row in rows]


def _detail_contract(target) -> dict[str, Any]:
    token = "__writebench_detail_contract_" + uuid.uuid4().hex
    victims = [
        {"name": "dup" if index in (0, 1) else f"v{index}",
         "industry": None if index % 2 == 0 else "i", "region": None}
        for index in range(5)
    ]
    connection = target.connect()
    try:
        first_payload = detail_payload(token, 0, victims)
        first_payload.update(content="one", content_hash="one")
        first_id = target.paths.upsert_detail(connection, first_payload)
        connection.commit()
        rows1 = _children(connection, first_id)
        empty_payload = detail_payload(token, 0, [])
        empty_payload.update(content="two", content_hash="two")
        second_id = target.paths.upsert_detail(connection, empty_payload)
        connection.commit()
        empty = _children(connection, first_id)
        restore_payload = detail_payload(token, 0, victims)
        restore_payload.update(content="three", content_hash="three")
        third_id = target.paths.upsert_detail(connection, restore_payload)
        connection.commit()
        rows3 = _children(connection, first_id)
    finally:
        connection.close()

    target.install_detail_failure()
    failed = target.connect()
    try:
        before_state = _state(failed)
        before_parent = tuple(failed.execute(
            "SELECT content, content_hash, raw_json FROM forum_details WHERE id=?", (first_id,),
        ).fetchone())
        before_children = _children(failed, first_id)
        bad = detail_payload(token, 0, [
            {"name": "__dwti_injected_failure__", "industry": None, "region": None}
        ])
        bad.update(content="rollback", content_hash="rollback")
        try:
            target.paths.upsert_detail(failed, bad)
        except Exception:
            failed.rollback()
        else:
            failed.rollback()
            raise AssertionError("detail failure injection did not fail")
        after_parent = tuple(failed.execute(
            "SELECT content, content_hash, raw_json FROM forum_details WHERE id=?", (first_id,),
        ).fetchone())
        rollback = (
            _state(failed) == before_state
            and after_parent == before_parent
            and _children(failed, first_id) == before_children
        )
    finally:
        failed.close()
        target.remove_detail_failure()
    passed = (
        first_id == second_id == third_id and empty == [] and rows1 == rows3
        and len(rows3) == 5 and rows3[0][0] == rows3[1][0]
        and any(row[1] is None for row in rows3) and rollback
    )
    return {
        "passed": passed, "stable_id": first_id == second_id == third_id,
        "replace_5_to_0_to_5": empty == [] and rows1 == rows3,
        "duplicates_preserved": len(rows3) == 5 and rows3[0][0] == rows3[1][0],
        "nulls_preserved": any(row[1] is None for row in rows3),
        "input_order_preserved": rows1 == rows3, "fault_injection_rollback": rollback,
    }


def run_contracts(target) -> dict[str, Any]:
    contracts = {
        "job_lifecycle": _job_contract(target),
        "dirty": _dirty_contract(target),
        "claim": _claim_contract(target),
        "vulnerability": _record_contract(target, "vulnerability"),
        "ransomware": _record_contract(target, "ransomware"),
        "victim": _victim_contract(target),
        "topic": _topic_contract(target),
        "detail": _detail_contract(target),
    }
    return {"passed": all(item.get("passed") is True for item in contracts.values()), "workloads": contracts}


def compare_contracts(*contracts: dict[str, Any]) -> dict[str, Any]:
    passed = all(item.get("passed") is True for item in contracts)
    normalized = [item.get("workloads") for item in contracts]
    equivalent = all(item == normalized[0] for item in normalized[1:]) if normalized else False
    return {"passed": passed and equivalent, "equivalent": equivalent}

