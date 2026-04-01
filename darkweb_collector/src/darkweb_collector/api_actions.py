from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Any

from darkweb_collector.config import get_site_config, load_site_configs, set_site_enabled
from darkweb_collector.db import get_active_crawl_job, get_db_connection, upsert_crawl_job
from darkweb_collector.orchestrator import run_site_once
from darkweb_collector.queueing import queue_for_seed
from darkweb_collector.utils import utc_now_iso


STALE_RUNNING_MINUTES = 30
CONTINUOUS_INTERVAL_SECONDS = 60


_continuous_lock = Lock()
_continuous_enabled = False
_continuous_started_at = ""
_continuous_last_tick_at = ""
_continuous_mode = "queue"
_continuous_stop_event: Event | None = None
_continuous_thread: Thread | None = None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_active_job_blocking(active_job: dict[str, Any] | None) -> bool:
    if not active_job:
        return False
    status = active_job.get("status")
    if status == "enqueued":
        return True
    if status != "running":
        return False
    started_at = _parse_dt(active_job.get("started_at"))
    if started_at is None:
        return True
    return started_at >= datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_MINUTES)


def _enqueue_job_row(job_id: str, site_name: str, queue_name: str) -> None:
    with get_db_connection() as connection:
        upsert_crawl_job(
            connection,
            job_id=job_id,
            site_name=site_name,
            job_type="seed",
            queue_name=queue_name,
            target=site_name,
            status="enqueued",
            enqueued_at=utc_now_iso(),
        )
        connection.commit()


def _run_site_in_thread(site_name: str) -> None:
    try:
        run_site_once(site_name)
    except Exception:
        # run_site_once already records failed jobs in crawl_jobs.
        return


def dispatch_run_site(site_name: str, force: bool = True) -> dict[str, Any]:
    config = get_site_config(site_name)
    with get_db_connection() as connection:
        active_job = get_active_crawl_job(connection, site_name=site_name, job_type="seed")
    if _is_active_job_blocking(active_job):
        return {
            "site_name": site_name,
            "dispatch_mode": "skipped",
            "message": "该站点已有运行中的种子任务",
            "job_id": active_job.get("job_id") if active_job else "",
        }

    queue_name = queue_for_seed(config.seed_fetch_mode)
    try:
        from darkweb_collector.tasks import crawl_seed

        async_result = crawl_seed.apply_async(
            kwargs={"site_name": site_name, "force": force},
            queue=queue_name,
        )
        job_id = str(async_result.id)
        _enqueue_job_row(job_id=job_id, site_name=site_name, queue_name=queue_name)
        return {
            "site_name": site_name,
            "dispatch_mode": "queue",
            "message": "已提交到任务队列",
            "job_id": job_id,
        }
    except Exception:
        thread = Thread(target=_run_site_in_thread, args=(site_name,), daemon=True)
        thread.start()
        return {
            "site_name": site_name,
            "dispatch_mode": "thread",
            "message": "队列不可用，已在本地线程触发单次运行",
            "job_id": "",
        }


def dispatch_run_all_enabled_sites(force: bool = True) -> dict[str, Any]:
    results = []
    for config in load_site_configs():
        if not config.enabled:
            continue
        results.append(dispatch_run_site(config.site_name, force=force))
    return {
        "count": len(results),
        "results": results,
    }


def dispatch_run_all_enabled_sites_once(force: bool = True) -> dict[str, Any]:
    return dispatch_run_all_enabled_sites(force=force)


def _continuous_loop(stop_event: Event) -> None:
    global _continuous_last_tick_at, _continuous_enabled
    while not stop_event.is_set():
        _continuous_last_tick_at = utc_now_iso()
        dispatch_run_all_enabled_sites(force=False)
        if stop_event.wait(CONTINUOUS_INTERVAL_SECONDS):
            break
    _continuous_enabled = False


def start_continuous_dispatch() -> dict[str, Any]:
    global _continuous_enabled, _continuous_started_at, _continuous_last_tick_at, _continuous_stop_event, _continuous_thread
    with _continuous_lock:
        if _continuous_enabled and _continuous_thread and _continuous_thread.is_alive():
            return {
                "enabled": True,
                "started_at": _continuous_started_at,
                "last_tick_at": _continuous_last_tick_at,
                "mode": _continuous_mode,
                "message": "持久运行已在运行",
            }

        stop_event = Event()
        thread = Thread(target=_continuous_loop, args=(stop_event,), daemon=True)
        _continuous_enabled = True
        _continuous_started_at = utc_now_iso()
        _continuous_last_tick_at = ""
        _continuous_stop_event = stop_event
        _continuous_thread = thread
        thread.start()

        return {
            "enabled": True,
            "started_at": _continuous_started_at,
            "last_tick_at": _continuous_last_tick_at,
            "mode": _continuous_mode,
            "message": "已开始持久运行",
        }


def stop_continuous_dispatch() -> dict[str, Any]:
    global _continuous_enabled, _continuous_stop_event, _continuous_thread
    with _continuous_lock:
        if not _continuous_enabled or _continuous_stop_event is None:
            return {
                "enabled": False,
                "started_at": _continuous_started_at,
                "last_tick_at": _continuous_last_tick_at,
                "mode": _continuous_mode,
                "message": "当前未运行持久调度",
            }

        _continuous_stop_event.set()
        _continuous_enabled = False
        return {
            "enabled": False,
            "started_at": _continuous_started_at,
            "last_tick_at": _continuous_last_tick_at,
            "mode": _continuous_mode,
            "message": "已停止持久运行",
        }


def get_continuous_dispatch_status() -> dict[str, Any]:
    thread_alive = bool(_continuous_thread and _continuous_thread.is_alive())
    enabled = bool(_continuous_enabled and thread_alive)
    return {
        "enabled": enabled,
        "started_at": _continuous_started_at,
        "last_tick_at": _continuous_last_tick_at,
        "mode": _continuous_mode,
    }


def update_site_enabled(site_name: str, enabled: bool) -> dict[str, Any]:
    config = set_site_enabled(site_name=site_name, enabled=enabled)
    return {
        "site_name": config.site_name,
        "enabled": config.enabled,
        "message": "已启用站点采集" if config.enabled else "已停用站点采集",
    }
