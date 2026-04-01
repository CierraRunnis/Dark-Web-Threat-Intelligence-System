from __future__ import annotations

import time

from darkweb_collector.celery_app import app
from darkweb_collector.models import DetailTask, SiteConfig
from darkweb_collector.orchestrator import execute_detail_job, execute_seed_job, mark_job_finished, mark_job_running
from darkweb_collector.queueing import MAX_RETRIES, queue_for_detail, retry_backoff_seconds
from darkweb_collector.state_store import get_state_store


def _queue_name_from_request(task) -> str:
    delivery_info = getattr(task.request, "delivery_info", {}) or {}
    routing_key = delivery_info.get("routing_key")
    if routing_key:
        return str(routing_key)
    return "unknown"


def _enqueue_detail_task(config: SiteConfig, detail_task: DetailTask) -> str | None:
    queue_name = queue_for_detail(config.detail_fetch_mode)
    async_result = crawl_detail.apply_async(
        kwargs={
            "site_name": config.site_name,
            "detail_task_payload": detail_task.to_dict(),
        },
        queue=queue_name,
    )
    return str(async_result.id)


@app.task(bind=True, name="darkweb_collector.tasks.crawl_seed")
def crawl_seed(self, site_name: str, force: bool = False) -> dict[str, object]:
    queue_name = _queue_name_from_request(self)
    start_perf = time.perf_counter()
    mark_job_running(
        job_id=self.request.id,
        site_name=site_name,
        job_type="seed",
        queue_name=queue_name,
        target=site_name,
    )
    try:
        result = execute_seed_job(
            site_name=site_name,
            queue_name=queue_name,
            force=force,
            state_store=get_state_store(prefer_redis=True),
            detail_dispatcher=_enqueue_detail_task,
            attempt=self.request.retries,
            job_id=self.request.id,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        if self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=retry_backoff_seconds(self.request.retries))
        mark_job_finished(
            job_id=self.request.id,
            site_name=site_name,
            job_type="seed",
            queue_name=queue_name,
            target=site_name,
            status="failed",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise
    duration_ms = int((time.perf_counter() - start_perf) * 1000)
    mark_job_finished(
        job_id=self.request.id,
        site_name=site_name,
        job_type="seed",
        queue_name=queue_name,
        target=site_name,
        status="succeeded",
        duration_ms=duration_ms,
    )
    return result


@app.task(bind=True, name="darkweb_collector.tasks.crawl_detail")
def crawl_detail(self, site_name: str, detail_task_payload: dict[str, object]) -> dict[str, object]:
    detail_task = DetailTask.from_dict(detail_task_payload)
    queue_name = _queue_name_from_request(self)
    start_perf = time.perf_counter()
    mark_job_running(
        job_id=self.request.id,
        site_name=site_name,
        job_type="detail",
        queue_name=queue_name,
        target=detail_task.target_url,
    )
    try:
        result = execute_detail_job(
            site_name=site_name,
            detail_task=detail_task,
            queue_name=queue_name,
            attempt=self.request.retries,
            job_id=self.request.id,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        if self.request.retries < MAX_RETRIES:
            raise self.retry(exc=exc, countdown=retry_backoff_seconds(self.request.retries))
        mark_job_finished(
            job_id=self.request.id,
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
        job_id=self.request.id,
        site_name=site_name,
        job_type="detail",
        queue_name=queue_name,
        target=detail_task.target_url,
        status="succeeded",
        duration_ms=duration_ms,
    )
    return result
