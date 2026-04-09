from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Any

from darkweb_collector.config import get_site_config, load_site_configs, set_site_enabled
from darkweb_collector.db import get_active_crawl_job, get_db_connection, upsert_crawl_job
from darkweb_collector.orchestrator import run_site_once
from darkweb_collector.public_vulnerabilities import sync_public_vulnerability_feed
from darkweb_collector.queueing import queue_for_seed
from darkweb_collector.utils import utc_now_iso


STALE_RUNNING_MINUTES = 30
STALE_ENQUEUED_MINUTES = 10
CONTINUOUS_INTERVAL_SECONDS = 60
DEFAULT_VULNERABILITY_SYNC_INTERVAL_SECONDS = 3600
DEFAULT_VULNERABILITY_SYNC_LIMIT = 300


_continuous_lock = Lock()
_continuous_enabled = False
_continuous_started_at = ""
_continuous_last_tick_at = ""
_continuous_mode = "queue"
_continuous_stop_event: Event | None = None
_continuous_thread: Thread | None = None

_vulnerability_sync_lock = Lock()
_vulnerability_sync_enabled = False
_vulnerability_sync_started_at = ""
_vulnerability_sync_last_tick_at = ""
_vulnerability_sync_last_success_at = ""
_vulnerability_sync_last_error = ""
_vulnerability_sync_last_mode = ""
_vulnerability_sync_last_source = ""
_vulnerability_sync_last_ingested = 0
_vulnerability_sync_interval_seconds = DEFAULT_VULNERABILITY_SYNC_INTERVAL_SECONDS
_vulnerability_sync_limit = DEFAULT_VULNERABILITY_SYNC_LIMIT
_vulnerability_sync_running = False
_vulnerability_sync_stop_event: Event | None = None
_vulnerability_sync_thread: Thread | None = None


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
        enqueued_at = _parse_dt(active_job.get("enqueued_at"))
        if enqueued_at is None:
            return False
        return enqueued_at >= datetime.now(timezone.utc) - timedelta(minutes=STALE_ENQUEUED_MINUTES)
    if status != "running":
        return False
    started_at = _parse_dt(active_job.get("started_at"))
    if started_at is None:
        return False
    return started_at >= datetime.now(timezone.utc) - timedelta(minutes=STALE_RUNNING_MINUTES)


def _mark_stale_active_job(site_name: str, active_job: dict[str, Any] | None) -> None:
    if not active_job:
        return
    if active_job.get("status") not in {"enqueued", "running"}:
        return

    marker = _parse_dt(active_job.get("started_at") or active_job.get("enqueued_at"))
    if marker is None:
        return

    with get_db_connection() as connection:
        upsert_crawl_job(
            connection,
            job_id=str(active_job["job_id"]),
            site_name=site_name,
            job_type="seed",
            queue_name=str(active_job.get("queue_name") or ""),
            target=str(active_job.get("target") or site_name),
            status="stale",
            enqueued_at=active_job.get("enqueued_at"),
            started_at=active_job.get("started_at"),
            finished_at=utc_now_iso(),
            error_message="stale seed task auto-cleared",
        )
        connection.commit()


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

    _mark_stale_active_job(site_name, active_job)

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


def _run_vulnerability_sync(limit: int, prefer_live: bool = True) -> dict[str, Any]:
    global _vulnerability_sync_running
    global _vulnerability_sync_last_tick_at
    global _vulnerability_sync_last_success_at
    global _vulnerability_sync_last_error
    global _vulnerability_sync_last_mode
    global _vulnerability_sync_last_source
    global _vulnerability_sync_last_ingested
    with _vulnerability_sync_lock:
        _vulnerability_sync_running = True
        _vulnerability_sync_last_tick_at = utc_now_iso()
        _vulnerability_sync_last_error = ""
    try:
        result = sync_public_vulnerability_feed(limit=limit, prefer_live=prefer_live)
        with _vulnerability_sync_lock:
            _vulnerability_sync_last_success_at = utc_now_iso()
            _vulnerability_sync_last_mode = str(result.get("mode") or "")
            _vulnerability_sync_last_source = str(result.get("source") or "")
            _vulnerability_sync_last_ingested = int(result.get("ingested") or 0)
            _vulnerability_sync_last_error = ""
        return result
    except Exception as exc:
        with _vulnerability_sync_lock:
            _vulnerability_sync_last_error = str(exc)
        raise
    finally:
        with _vulnerability_sync_lock:
            _vulnerability_sync_running = False


def _run_vulnerability_sync_once_in_thread(limit: int) -> None:
    try:
        _run_vulnerability_sync(limit=limit)
    except Exception:
        return


def dispatch_run_vulnerability_sync_once(limit: int = DEFAULT_VULNERABILITY_SYNC_LIMIT) -> dict[str, Any]:
    global _vulnerability_sync_thread
    with _vulnerability_sync_lock:
        if _vulnerability_sync_running:
            return {
                **get_vulnerability_sync_status(),
                "message": "漏洞同步任务已在运行中",
            }
        thread = Thread(target=_run_vulnerability_sync_once_in_thread, args=(limit,), daemon=True)
        _vulnerability_sync_thread = thread
        thread.start()
    return {
        **get_vulnerability_sync_status(),
        "message": "已触发一次漏洞同步",
    }


def _vulnerability_sync_loop(stop_event: Event) -> None:
    global _vulnerability_sync_enabled
    while not stop_event.is_set():
        try:
            _run_vulnerability_sync(limit=_vulnerability_sync_limit)
        except Exception:
            pass
        if stop_event.wait(_vulnerability_sync_interval_seconds):
            break
    _vulnerability_sync_enabled = False


def start_vulnerability_sync_dispatch(
    interval_seconds: int = DEFAULT_VULNERABILITY_SYNC_INTERVAL_SECONDS,
    limit: int = DEFAULT_VULNERABILITY_SYNC_LIMIT,
) -> dict[str, Any]:
    global _vulnerability_sync_enabled
    global _vulnerability_sync_started_at
    global _vulnerability_sync_stop_event
    global _vulnerability_sync_thread
    global _vulnerability_sync_interval_seconds
    global _vulnerability_sync_limit
    if interval_seconds <= 0:
        interval_seconds = DEFAULT_VULNERABILITY_SYNC_INTERVAL_SECONDS
    if limit <= 0:
        limit = DEFAULT_VULNERABILITY_SYNC_LIMIT
    with _vulnerability_sync_lock:
        if _vulnerability_sync_enabled and _vulnerability_sync_thread and _vulnerability_sync_thread.is_alive():
            return {
                **get_vulnerability_sync_status(),
                "message": "漏洞自动同步已在运行",
            }
        stop_event = Event()
        thread = Thread(target=_vulnerability_sync_loop, args=(stop_event,), daemon=True)
        _vulnerability_sync_enabled = True
        _vulnerability_sync_started_at = utc_now_iso()
        _vulnerability_sync_interval_seconds = interval_seconds
        _vulnerability_sync_limit = limit
        _vulnerability_sync_stop_event = stop_event
        _vulnerability_sync_thread = thread
        thread.start()
    return {
        **get_vulnerability_sync_status(),
        "message": "已开始漏洞自动同步",
    }


def stop_vulnerability_sync_dispatch() -> dict[str, Any]:
    global _vulnerability_sync_enabled
    with _vulnerability_sync_lock:
        if not _vulnerability_sync_enabled or _vulnerability_sync_stop_event is None:
            return {
                **get_vulnerability_sync_status(),
                "message": "漏洞自动同步当前未运行",
            }
        _vulnerability_sync_stop_event.set()
        _vulnerability_sync_enabled = False
    return {
        **get_vulnerability_sync_status(),
        "message": "已停止漏洞自动同步",
    }


def get_vulnerability_sync_status() -> dict[str, Any]:
    thread_alive = bool(_vulnerability_sync_thread and _vulnerability_sync_thread.is_alive())
    return {
        "enabled": bool(_vulnerability_sync_enabled and thread_alive),
        "running": bool(_vulnerability_sync_running),
        "started_at": _vulnerability_sync_started_at,
        "last_tick_at": _vulnerability_sync_last_tick_at,
        "last_success_at": _vulnerability_sync_last_success_at,
        "last_error": _vulnerability_sync_last_error,
        "last_mode": _vulnerability_sync_last_mode,
        "last_source": _vulnerability_sync_last_source,
        "last_ingested": _vulnerability_sync_last_ingested,
        "interval_seconds": _vulnerability_sync_interval_seconds,
        "limit": _vulnerability_sync_limit,
    }


def update_site_enabled(site_name: str, enabled: bool) -> dict[str, Any]:
    config = set_site_enabled(site_name=site_name, enabled=enabled)
    return {
        "site_name": config.site_name,
        "enabled": config.enabled,
        "message": "已启用站点采集" if config.enabled else "已停用站点采集",
    }
