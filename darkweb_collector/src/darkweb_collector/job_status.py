from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from darkweb_collector.db import upsert_crawl_job
from darkweb_collector.utils import utc_now_iso


STALE_RUNNING_MINUTES = 30
STALE_ENQUEUED_MINUTES = 10
STALE_ENQUEUED_BUSY_QUEUE_MINUTES = 60
STALE_SEED_ERROR_MESSAGE = "stale seed task auto-cleared"


def parse_job_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def has_recent_running_job_in_queue(connection, queue_name: str, *, exclude_job_id: str = "") -> bool:
    if not queue_name:
        return False
    rows = connection.execute(
        """
        SELECT job_id, started_at, finished_at
        FROM crawl_jobs
        WHERE queue_name = ? AND status = 'running'
        """,
        (queue_name,),
    ).fetchall()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_MINUTES)
    for row in rows:
        job_id = str(row["job_id"] or "")
        if exclude_job_id and job_id == exclude_job_id:
            continue
        if row["finished_at"]:
            continue
        started_at = parse_job_datetime(row["started_at"])
        if started_at is not None and started_at >= cutoff:
            return True
    return False


def is_active_job_blocking(
    active_job: dict[str, Any] | None,
    *,
    queue_has_recent_running: bool = False,
) -> bool:
    if not active_job:
        return False
    status = active_job.get("status")
    if status == "enqueued":
        enqueued_at = parse_job_datetime(active_job.get("enqueued_at"))
        if enqueued_at is None:
            return False
        threshold_minutes = (
            STALE_ENQUEUED_BUSY_QUEUE_MINUTES if queue_has_recent_running else STALE_ENQUEUED_MINUTES
        )
        return enqueued_at >= datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)
    if status != "running":
        return False
    started_at = parse_job_datetime(active_job.get("started_at"))
    if started_at is None:
        return False
    return started_at >= datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_MINUTES)


def mark_stale_active_job(
    connection,
    *,
    site_name: str,
    job_type: str,
    active_job: dict[str, Any] | None,
) -> bool:
    if not active_job:
        return False
    if active_job.get("status") not in {"enqueued", "running"}:
        return False

    marker = parse_job_datetime(active_job.get("started_at") or active_job.get("enqueued_at"))
    if marker is None:
        return False

    upsert_crawl_job(
        connection,
        job_id=str(active_job["job_id"]),
        site_name=site_name,
        job_type=job_type,
        queue_name=str(active_job.get("queue_name") or ""),
        target=str(active_job.get("target") or site_name),
        status="stale",
        enqueued_at=active_job.get("enqueued_at"),
        started_at=active_job.get("started_at"),
        finished_at=utc_now_iso(),
        error_message=STALE_SEED_ERROR_MESSAGE,
    )
    return True
