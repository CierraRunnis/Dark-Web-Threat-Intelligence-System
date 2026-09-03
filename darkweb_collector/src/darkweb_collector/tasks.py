from __future__ import annotations

import hashlib
import logging
import time
import uuid

from darkweb_collector.celery_app import app
from darkweb_collector.config import get_site_config
from darkweb_collector.models import DetailTask, SiteConfig
from darkweb_collector.orchestrator import (
    execute_detail_job,
    execute_seed_job,
    mark_job_enqueued,
    mark_job_finished,
    mark_job_running,
)
from darkweb_collector.queueing import MAX_RETRIES, queue_for_detail, retry_backoff_seconds
from darkweb_collector.site_auth import SiteAuthenticationRequired
from darkweb_collector.state_store import get_state_store


logger = logging.getLogger(__name__)


def _queue_name_from_request(task) -> str:
    delivery_info = getattr(task.request, "delivery_info", {}) or {}
    routing_key = delivery_info.get("routing_key")
    if routing_key:
        return str(routing_key)
    return "unknown"


def _enqueue_detail_task(config: SiteConfig, detail_task: DetailTask) -> str | None:
    queue_name = queue_for_detail(config)
    job_id = str(uuid.uuid4())
    mark_job_enqueued(
        job_id=job_id,
        site_name=config.site_name,
        job_type="detail",
        queue_name=queue_name,
        target=detail_task.target_url,
    )
    try:
        async_result = crawl_detail.apply_async(
            kwargs={
                "site_name": config.site_name,
                "detail_task_payload": detail_task.to_dict(),
                "fetch_attempt": 0,
            },
            queue=queue_name,
            task_id=job_id,
        )
    except Exception as exc:
        mark_job_finished(
            job_id=job_id,
            site_name=config.site_name,
            job_type="detail",
            queue_name=queue_name,
            target=detail_task.target_url,
            status="failed",
            duration_ms=0,
            error_message=str(exc),
        )
        raise
    return str(async_result.id)


def _slot_retry_seconds(config: SiteConfig, job_id: str) -> int:
    digest = hashlib.sha1(job_id.encode("utf-8")).digest()[0]
    return config.detail_slot_retry_seconds + digest % 5


def _mark_retry_enqueued(
    *,
    job_id: str,
    site_name: str,
    job_type: str,
    queue_name: str,
    target: str,
) -> None:
    try:
        mark_job_enqueued(
            job_id=job_id,
            site_name=site_name,
            job_type=job_type,
            queue_name=queue_name,
            target=target,
        )
    except Exception:
        logger.exception("failed to mark retrying %s job as enqueued", job_type)


@app.task(bind=True, name="darkweb_collector.tasks.crawl_seed")
def crawl_seed(self, site_name: str, force: bool = False) -> dict[str, object]:
    queue_name = _queue_name_from_request(self)
    start_perf = time.perf_counter()
    try:
        mark_job_running(
            job_id=self.request.id,
            site_name=site_name,
            job_type="seed",
            queue_name=queue_name,
            target=site_name,
        )
        result = execute_seed_job(
            site_name=site_name,
            queue_name=queue_name,
            force=force,
            state_store=get_state_store(prefer_redis=True),
            detail_dispatcher=_enqueue_detail_task,
            attempt=self.request.retries,
            job_id=self.request.id,
        )
    except SiteAuthenticationRequired as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_job_finished(
            job_id=self.request.id,
            site_name=site_name,
            job_type="seed",
            queue_name=queue_name,
            target=site_name,
            status="skipped",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        return {
            "site_name": site_name,
            "seed_job_id": self.request.id,
            "reason": "auth_required",
            "auth_platform": exc.platform,
        }
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        if self.request.retries < MAX_RETRIES:
            _mark_retry_enqueued(
                job_id=self.request.id,
                site_name=site_name,
                job_type="seed",
                queue_name=queue_name,
                target=site_name,
            )
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


@app.task(bind=True, name="darkweb_collector.tasks.crawl_detail", max_retries=None)
def crawl_detail(
    self,
    site_name: str,
    detail_task_payload: dict[str, object],
    fetch_attempt: int = 0,
) -> dict[str, object]:
    fetch_attempt = max(0, int(fetch_attempt))
    detail_task = DetailTask.from_dict(detail_task_payload)
    config = get_site_config(site_name)
    queue_name = _queue_name_from_request(self)
    state_store = get_state_store(prefer_redis=True)
    slot_owner = f"{self.request.id}:{getattr(self.request, 'hostname', '') or 'worker'}"
    try:
        slot_acquired = state_store.acquire_detail_slot(
            site_name,
            slot_owner,
            config.max_concurrent_details,
            config.detail_slot_ttl_seconds,
        )
    except Exception as exc:
        raise self.retry(
            exc=exc,
            countdown=_slot_retry_seconds(config, slot_owner),
            max_retries=None,
        )
    if not slot_acquired:
        raise self.retry(
            countdown=_slot_retry_seconds(config, slot_owner),
            max_retries=None,
        )
    start_perf = time.perf_counter()
    try:
        mark_job_running(
            job_id=self.request.id,
            site_name=site_name,
            job_type="detail",
            queue_name=queue_name,
            target=detail_task.target_url,
        )
        result = execute_detail_job(
            site_name=site_name,
            detail_task=detail_task,
            queue_name=queue_name,
            attempt=fetch_attempt,
            job_id=self.request.id,
        )
    except SiteAuthenticationRequired as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        mark_job_finished(
            job_id=self.request.id,
            site_name=site_name,
            job_type="detail",
            queue_name=queue_name,
            target=detail_task.target_url,
            status="skipped",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        return {
            "site_name": site_name,
            "detail_job_id": self.request.id,
            "target_url": detail_task.target_url,
            "reason": "auth_required",
            "auth_platform": exc.platform,
        }
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_perf) * 1000)
        if fetch_attempt < MAX_RETRIES:
            _mark_retry_enqueued(
                job_id=self.request.id,
                site_name=site_name,
                job_type="detail",
                queue_name=queue_name,
                target=detail_task.target_url,
            )
            raise self.retry(
                exc=exc,
                countdown=retry_backoff_seconds(fetch_attempt),
                kwargs={
                    "site_name": site_name,
                    "detail_task_payload": detail_task_payload,
                    "fetch_attempt": fetch_attempt + 1,
                },
                max_retries=None,
            )
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
    finally:
        try:
            state_store.release_detail_slot(site_name, slot_owner)
        except Exception:
            logger.exception("failed to release detail slot for %s", site_name)
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
