from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import uuid
from typing import Callable

from darkweb_collector.adapters.registry import get_adapter
from darkweb_collector.config import get_site_config, load_site_configs
from darkweb_collector.db import (
    get_active_crawl_job,
    get_db_connection,
    get_last_successful_crawl_job,
    list_crawl_jobs,
    upsert_crawl_job,
)
from darkweb_collector.models import DetailTask, RunContext, SiteConfig
from darkweb_collector.queueing import queue_for_detail, queue_for_seed
from darkweb_collector.state_store import StateStore
from darkweb_collector.utils import utc_now_iso


def new_job_id(job_type: str, site_name: str) -> str:
    return f"local-{job_type}-{site_name}-{uuid.uuid4().hex[:12]}"


def mark_job_running(job_id: str, site_name: str, job_type: str, queue_name: str, target: str) -> None:
    started_at = utc_now_iso()
    with get_db_connection() as connection:
        upsert_crawl_job(
            connection,
            job_id=job_id,
            site_name=site_name,
            job_type=job_type,
            queue_name=queue_name,
            target=target,
            status="running",
            started_at=started_at,
        )
        connection.commit()


def mark_job_finished(
    job_id: str,
    site_name: str,
    job_type: str,
    queue_name: str,
    target: str,
    status: str,
    duration_ms: int,
    error_message: str | None = None,
) -> None:
    with get_db_connection() as connection:
        upsert_crawl_job(
            connection,
            job_id=job_id,
            site_name=site_name,
            job_type=job_type,
            queue_name=queue_name,
            target=target,
            status=status,
            finished_at=utc_now_iso(),
            duration_ms=duration_ms,
            error_message=error_message,
        )
        connection.commit()


def is_site_due(config: SiteConfig, finished_at_utc: str | None) -> bool:
    if not finished_at_utc:
        return True
    finished_at = datetime.fromisoformat(finished_at_utc)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    next_due = finished_at + timedelta(seconds=config.effective_interval_seconds)
    return datetime.now(timezone.utc) >= next_due


def _dispatch_detail_jobs(
    config: SiteConfig,
    detail_tasks: list[DetailTask],
    state_store: StateStore,
    detail_dispatcher: Callable[[SiteConfig, DetailTask], str | None] | None,
) -> tuple[list[str], int]:
    dispatched: list[str] = []
    failed = 0
    if detail_dispatcher is None:
        return dispatched, failed

    detail_ttl = max(config.dedupe_window_minutes * 60, 60)
    for detail_task in detail_tasks:
        if not state_store.claim_detail(config.site_name, detail_task.target_url, detail_ttl):
            continue
        try:
            job_id = detail_dispatcher(config, detail_task)
        except Exception:
            failed += 1
            continue
        if job_id:
            dispatched.append(job_id)
    return dispatched, failed


def execute_seed_job(
    site_name: str,
    queue_name: str,
    force: bool,
    state_store: StateStore,
    detail_dispatcher: Callable[[SiteConfig, DetailTask], str | None] | None,
    attempt: int = 0,
    job_id: str | None = None,
    config_path: Path | None = None,
) -> dict[str, object]:
    config = get_site_config(site_name, config_path)
    run_ctx = RunContext(
        job_id=job_id or new_job_id("seed", site_name),
        job_type="seed",
        queue_name=queue_name,
        target=site_name,
        started_at_utc=utc_now_iso(),
        force=force,
        attempt=attempt,
    )
    adapter = get_adapter(site_name)
    seed_result = adapter.collect_seed(config, run_ctx)
    detail_tasks = adapter.plan_details(seed_result, config)
    adapter.persist(config=config, run_ctx=run_ctx, seed_result=seed_result)
    dispatched_job_ids, failed_detail_jobs = _dispatch_detail_jobs(
        config, detail_tasks, state_store, detail_dispatcher
    )
    return {
        "site_name": site_name,
        "seed_job_id": run_ctx.job_id,
        "detail_job_ids": dispatched_job_ids,
        "detail_task_count": len(detail_tasks),
        "detail_failed_count": failed_detail_jobs,
        "collected_at_utc": seed_result.collected_at_utc,
    }


def execute_detail_job(
    site_name: str,
    detail_task: DetailTask,
    queue_name: str,
    attempt: int = 0,
    job_id: str | None = None,
    config_path: Path | None = None,
) -> dict[str, object]:
    config = get_site_config(site_name, config_path)
    run_ctx = RunContext(
        job_id=job_id or new_job_id("detail", site_name),
        job_type="detail",
        queue_name=queue_name,
        target=detail_task.target_url,
        started_at_utc=utc_now_iso(),
        attempt=attempt,
    )
    adapter = get_adapter(site_name)
    detail_result = adapter.collect_detail(detail_task, config, run_ctx)
    if detail_result is not None:
        adapter.persist(config=config, run_ctx=run_ctx, detail_results=[detail_result])
    return {
        "site_name": site_name,
        "detail_job_id": run_ctx.job_id,
        "target_url": detail_task.target_url,
    }


def run_detail_job_once(site_name: str, detail_task: DetailTask, config_path: Path | None = None) -> str:
    queue_name = queue_for_detail(get_site_config(site_name, config_path).detail_fetch_mode)
    job_id = new_job_id("detail", site_name)
    mark_job_running(
        job_id=job_id,
        site_name=site_name,
        job_type="detail",
        queue_name=queue_name,
        target=detail_task.target_url,
    )
    start_perf = time.perf_counter()
    try:
        execute_detail_job(
            site_name=site_name,
            detail_task=detail_task,
            queue_name=queue_name,
            job_id=job_id,
            config_path=config_path,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_job_finished(
            job_id=job_id,
            site_name=site_name,
            job_type="detail",
            queue_name=queue_name,
            target=detail_task.target_url,
            status="failed",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise
    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    mark_job_finished(
        job_id=job_id,
        site_name=site_name,
        job_type="detail",
        queue_name=queue_name,
        target=detail_task.target_url,
        status="succeeded",
        duration_ms=duration_ms,
    )
    return job_id


def run_site_once(site_name: str, config_path: Path | None = None, state_store: StateStore | None = None) -> dict[str, object]:
    from darkweb_collector.state_store import InMemoryStateStore

    config = get_site_config(site_name, config_path)
    seed_queue = queue_for_seed(config.seed_fetch_mode)
    job_id = new_job_id("seed", site_name)
    mark_job_running(
        job_id=job_id,
        site_name=site_name,
        job_type="seed",
        queue_name=seed_queue,
        target=site_name,
    )
    start_perf = time.perf_counter()
    selected_state_store = state_store or InMemoryStateStore()

    def inline_dispatcher(dispatched_config: SiteConfig, detail_task: DetailTask) -> str | None:
        return run_detail_job_once(site_name=dispatched_config.site_name, detail_task=detail_task, config_path=config_path)

    try:
        result = execute_seed_job(
            site_name=site_name,
            queue_name=seed_queue,
            force=True,
            state_store=selected_state_store,
            detail_dispatcher=inline_dispatcher,
            job_id=job_id,
            config_path=config_path,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_job_finished(
            job_id=job_id,
            site_name=site_name,
            job_type="seed",
            queue_name=seed_queue,
            target=site_name,
            status="failed",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise

    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    mark_job_finished(
        job_id=job_id,
        site_name=site_name,
        job_type="seed",
        queue_name=seed_queue,
        target=site_name,
        status="succeeded",
        duration_ms=duration_ms,
    )
    return result


def enqueue_due_sites(
    seed_dispatcher: Callable[[SiteConfig], str | None],
    state_store: StateStore,
    config_path: Path | None = None,
) -> list[dict[str, str]]:
    dispatched: list[dict[str, str]] = []
    with get_db_connection() as connection:
        for config in load_site_configs(config_path):
            if not config.enabled:
                continue
            if get_active_crawl_job(connection, site_name=config.site_name, job_type="seed"):
                continue
            last_success = get_last_successful_crawl_job(connection, site_name=config.site_name, job_type="seed")
            last_finished = last_success["finished_at"] if last_success else None
            if not is_site_due(config, last_finished):
                continue
            if not state_store.claim_seed_slot(config.site_name, max(config.effective_interval_seconds, 300)):
                continue
            queue_name = queue_for_seed(config.seed_fetch_mode)
            job_id = seed_dispatcher(config)
            if not job_id:
                continue
            upsert_crawl_job(
                connection,
                job_id=job_id,
                site_name=config.site_name,
                job_type="seed",
                queue_name=queue_name,
                target=config.site_name,
                status="enqueued",
                enqueued_at=utc_now_iso(),
            )
            dispatched.append({"site_name": config.site_name, "job_id": job_id, "queue_name": queue_name})
        connection.commit()
    return dispatched


def show_runs(limit: int) -> list[dict[str, object]]:
    with get_db_connection() as connection:
        return list_crawl_jobs(connection, limit=limit)
