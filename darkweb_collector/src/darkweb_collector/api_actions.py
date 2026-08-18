from __future__ import annotations

from threading import Event, Lock, Thread
import time
from typing import Any

from darkweb_collector.config import get_site_config, load_site_configs, set_site_enabled
from darkweb_collector.db import (
    get_active_crawl_job,
    get_db_connection,
    get_ransomware_live_sync_state,
    upsert_crawl_job,
)
from darkweb_collector.code_monitoring import list_code_watchlists_payload, scan_code_watchlist_once
from darkweb_collector.document_exposure import list_watchlists_payload, scan_watchlist_once
from darkweb_collector.job_status import (
    has_recent_running_job_in_queue,
    is_active_job_blocking,
    mark_stale_active_job,
)
from darkweb_collector.orchestrator import run_site_once
from darkweb_collector.public_vulnerabilities import sync_public_vulnerability_feed
from darkweb_collector.queueing import queue_for_seed
from darkweb_collector.ransomware_live import get_ransomware_live_api_key, sync_ransomware_live_victims
from darkweb_collector.utils import utc_now_iso


CONTINUOUS_INTERVAL_SECONDS = 60
DEFAULT_VULNERABILITY_SYNC_INTERVAL_SECONDS = 3600
DEFAULT_VULNERABILITY_SYNC_LIMIT = 300
DEFAULT_RANSOMWARE_SYNC_INTERVAL_SECONDS = 3600
DEFAULT_RANSOMWARE_SYNC_LIMIT = 0
DEFAULT_CODE_MONITORING_INTERVAL_SECONDS = 3600
DEFAULT_CODE_MONITORING_CONTINUOUS_SEARCH_PAGE_LIMIT = 2
DEFAULT_CODE_MONITORING_CONTINUOUS_MAX_RESULTS_PER_TERM = 5
DEFAULT_CODE_MONITORING_LOCK_RETRY_SECONDS = 15
DEFAULT_NETDISK_MONITORING_INTERVAL_SECONDS = 3600
WORKER_QUEUE_CACHE_TTL_SECONDS = 5


_continuous_lock = Lock()
_continuous_enabled = False
_continuous_started_at = ""
_continuous_last_tick_at = ""
_continuous_last_error = ""
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

_ransomware_sync_lock = Lock()
_ransomware_sync_enabled = False
_ransomware_sync_started_at = ""
_ransomware_sync_last_tick_at = ""
_ransomware_sync_last_success_at = ""
_ransomware_sync_last_error = ""
_ransomware_sync_last_source = ""
_ransomware_sync_last_ingested = 0
_ransomware_sync_interval_seconds = DEFAULT_RANSOMWARE_SYNC_INTERVAL_SECONDS
_ransomware_sync_limit = DEFAULT_RANSOMWARE_SYNC_LIMIT
_ransomware_sync_running = False
_ransomware_sync_stop_event: Event | None = None
_ransomware_sync_thread: Thread | None = None

_code_monitoring_lock = Lock()
_code_monitoring_enabled = False
_code_monitoring_started_at = ""
_code_monitoring_last_tick_at = ""
_code_monitoring_last_success_at = ""
_code_monitoring_last_error = ""
_code_monitoring_interval_seconds = DEFAULT_CODE_MONITORING_INTERVAL_SECONDS
_code_monitoring_running = False
_code_monitoring_last_watchlist_count = 0
_code_monitoring_last_candidate_count = 0
_code_monitoring_last_hit_count = 0
_code_monitoring_last_clue_hit_count = 0
_code_monitoring_last_sensitive_hit_count = 0
_code_monitoring_target_watchlist_id = 0
_code_monitoring_target_watchlist_name = ""
_code_monitoring_stop_event: Event | None = None
_code_monitoring_thread: Thread | None = None
_code_monitoring_tasks: dict[int, dict[str, Any]] = {}

_netdisk_monitoring_lock = Lock()
_netdisk_monitoring_once_running = False
_netdisk_monitoring_once_thread: Thread | None = None
_netdisk_monitoring_tasks: dict[int, dict[str, Any]] = {}

_worker_queue_cache_lock = Lock()
_worker_queue_cache_checked_at = 0.0
_worker_queue_cache: set[str] = set()



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


def _refresh_worker_queue_cache() -> set[str]:
    try:
        from darkweb_collector.celery_app import app as celery_app
    except Exception:
        return set()

    inspect = celery_app.control.inspect(timeout=0.8)
    try:
        active_queues = inspect.active_queues() or {}
    except Exception:
        active_queues = {}
    queue_names: set[str] = set()
    for worker_queues in active_queues.values():
        for queue in worker_queues or []:
            name = str((queue or {}).get("name") or "").strip()
            if name:
                queue_names.add(name)
    return queue_names


def _has_queue_worker(queue_name: str) -> bool:
    global _worker_queue_cache_checked_at, _worker_queue_cache
    now = time.monotonic()
    with _worker_queue_cache_lock:
        if (now - _worker_queue_cache_checked_at) > WORKER_QUEUE_CACHE_TTL_SECONDS:
            _worker_queue_cache = _refresh_worker_queue_cache()
            _worker_queue_cache_checked_at = now
        return queue_name in _worker_queue_cache


def _run_site_in_thread(site_name: str) -> None:
    # Local import keeps api_actions import-time cheap (no playwright pull-in
    # for API processes that never touch browser_client).
    from darkweb_collector.browser_client import close_browser_client

    try:
        run_site_once(site_name)
    except Exception:
        # run_site_once already records failed jobs in crawl_jobs.
        return
    finally:
        # Each dispatch spawns a fresh daemon thread. Playwright's sync API
        # binds its driver greenlets to the thread that created them, so the
        # thread MUST close its own client before exiting — otherwise the
        # next thread inherits a dead reference and dies with
        # "cannot switch to a different thread (which happens to have exited)".
        try:
            close_browser_client()
        except Exception as exc:
            print(f"[api_actions] close_browser_client after {site_name} failed (ignored): {exc}")


def dispatch_run_site(site_name: str, force: bool = True) -> dict[str, Any]:
    config = get_site_config(site_name)
    with get_db_connection() as connection:
        active_job = get_active_crawl_job(connection, site_name=site_name, job_type="seed")
        queue_has_recent_running = has_recent_running_job_in_queue(
            connection,
            str((active_job or {}).get("queue_name") or ""),
            exclude_job_id=str((active_job or {}).get("job_id") or ""),
        )
    if is_active_job_blocking(active_job, queue_has_recent_running=queue_has_recent_running):
        return {
            "site_name": site_name,
            "dispatch_mode": "skipped",
            "message": "该站点已有运行中的种子任务",
            "job_id": active_job.get("job_id") if active_job else "",
        }

    if active_job:
        with get_db_connection() as connection:
            mark_stale_active_job(connection, site_name=site_name, job_type="seed", active_job=active_job)
            connection.commit()

    queue_name = queue_for_seed(config.seed_fetch_mode)
    if not _has_queue_worker(queue_name):
        thread = Thread(target=_run_site_in_thread, args=(site_name,), daemon=True)
        thread.start()
        return {
            "site_name": site_name,
            "dispatch_mode": "thread",
            "message": "未检测到可消费该队列的 worker，已在本地线程触发单次运行",
            "job_id": "",
        }
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
    global _continuous_last_tick_at, _continuous_enabled, _continuous_last_error
    while not stop_event.is_set():
        _continuous_last_tick_at = utc_now_iso()
        try:
            dispatch_run_all_enabled_sites(force=False)
            _continuous_last_error = ""
        except Exception as exc:
            _continuous_last_error = f"{type(exc).__name__}: {exc}"
            print(f"[api_actions] continuous dispatch failed (will retry): {_continuous_last_error}")
        if stop_event.wait(CONTINUOUS_INTERVAL_SECONDS):
            break
    _continuous_enabled = False


def start_continuous_dispatch() -> dict[str, Any]:
    global _continuous_enabled, _continuous_started_at, _continuous_last_tick_at, _continuous_last_error, _continuous_stop_event, _continuous_thread
    with _continuous_lock:
        if _continuous_enabled and _continuous_thread and _continuous_thread.is_alive():
            return {
                "enabled": True,
                "started_at": _continuous_started_at,
                "last_tick_at": _continuous_last_tick_at,
                "last_error": _continuous_last_error,
                "mode": _continuous_mode,
                "message": "持久运行已在运行",
            }

        stop_event = Event()
        thread = Thread(target=_continuous_loop, args=(stop_event,), daemon=True)
        _continuous_enabled = True
        _continuous_started_at = utc_now_iso()
        _continuous_last_tick_at = ""
        _continuous_last_error = ""
        _continuous_stop_event = stop_event
        _continuous_thread = thread
        thread.start()

        return {
            "enabled": True,
            "started_at": _continuous_started_at,
            "last_tick_at": _continuous_last_tick_at,
            "last_error": _continuous_last_error,
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
                "last_error": _continuous_last_error,
                "mode": _continuous_mode,
                "message": "当前未运行持久调度",
            }

        _continuous_stop_event.set()
        _continuous_enabled = False
        return {
            "enabled": False,
            "started_at": _continuous_started_at,
            "last_tick_at": _continuous_last_tick_at,
            "last_error": _continuous_last_error,
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
        "last_error": _continuous_last_error,
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


def _run_ransomware_sync(limit: int) -> dict[str, Any]:
    global _ransomware_sync_running
    global _ransomware_sync_last_tick_at
    global _ransomware_sync_last_success_at
    global _ransomware_sync_last_error
    global _ransomware_sync_last_source
    global _ransomware_sync_last_ingested
    with _ransomware_sync_lock:
        _ransomware_sync_running = True
        _ransomware_sync_last_tick_at = utc_now_iso()
        _ransomware_sync_last_error = ""
    try:
        result = sync_ransomware_live_victims(limit=limit, refresh_normalized=True)
        with _ransomware_sync_lock:
            _ransomware_sync_last_success_at = utc_now_iso()
            _ransomware_sync_last_source = str(result.get("source") or "")
            _ransomware_sync_last_ingested = int(result.get("ingested") or 0)
            _ransomware_sync_last_error = ""
        return result
    except Exception as exc:
        with _ransomware_sync_lock:
            _ransomware_sync_last_error = str(exc)
        raise
    finally:
        with _ransomware_sync_lock:
            _ransomware_sync_running = False


def _run_ransomware_sync_once_in_thread(limit: int) -> None:
    try:
        _run_ransomware_sync(limit=limit)
    except Exception:
        return


def dispatch_run_ransomware_sync_once(limit: int = DEFAULT_RANSOMWARE_SYNC_LIMIT) -> dict[str, Any]:
    global _ransomware_sync_thread
    with _ransomware_sync_lock:
        if _ransomware_sync_running:
            return {
                **get_ransomware_sync_status(),
                "message": "ransomware.live 同步任务已在运行中",
            }
        thread = Thread(target=_run_ransomware_sync_once_in_thread, args=(limit,), daemon=True)
        _ransomware_sync_thread = thread
        thread.start()
    return {
        **get_ransomware_sync_status(),
        "message": "已触发一次 ransomware.live 同步",
    }


def _ransomware_sync_loop(stop_event: Event) -> None:
    global _ransomware_sync_enabled
    while not stop_event.is_set():
        try:
            _run_ransomware_sync(limit=_ransomware_sync_limit)
        except Exception:
            pass
        if stop_event.wait(_ransomware_sync_interval_seconds):
            break
    _ransomware_sync_enabled = False


def start_ransomware_sync_dispatch(
    interval_seconds: int = DEFAULT_RANSOMWARE_SYNC_INTERVAL_SECONDS,
    limit: int = DEFAULT_RANSOMWARE_SYNC_LIMIT,
) -> dict[str, Any]:
    global _ransomware_sync_enabled
    global _ransomware_sync_started_at
    global _ransomware_sync_stop_event
    global _ransomware_sync_thread
    global _ransomware_sync_interval_seconds
    global _ransomware_sync_limit
    if interval_seconds <= 0:
        interval_seconds = DEFAULT_RANSOMWARE_SYNC_INTERVAL_SECONDS
    with _ransomware_sync_lock:
        if _ransomware_sync_enabled and _ransomware_sync_thread and _ransomware_sync_thread.is_alive():
            return {
                **get_ransomware_sync_status(),
                "message": "ransomware.live 自动同步已在运行",
            }
        stop_event = Event()
        thread = Thread(target=_ransomware_sync_loop, args=(stop_event,), daemon=True)
        _ransomware_sync_enabled = True
        _ransomware_sync_started_at = utc_now_iso()
        _ransomware_sync_interval_seconds = interval_seconds
        _ransomware_sync_limit = limit
        _ransomware_sync_stop_event = stop_event
        _ransomware_sync_thread = thread
        thread.start()
    return {
        **get_ransomware_sync_status(),
        "message": "已开始 ransomware.live 自动同步",
    }


def stop_ransomware_sync_dispatch() -> dict[str, Any]:
    global _ransomware_sync_enabled
    with _ransomware_sync_lock:
        if not _ransomware_sync_enabled or _ransomware_sync_stop_event is None:
            return {
                **get_ransomware_sync_status(),
                "message": "ransomware.live 自动同步当前未运行",
            }
        _ransomware_sync_stop_event.set()
        _ransomware_sync_enabled = False
    return {
        **get_ransomware_sync_status(),
        "message": "已停止 ransomware.live 自动同步",
    }


def get_ransomware_sync_status() -> dict[str, Any]:
    thread_alive = bool(_ransomware_sync_thread and _ransomware_sync_thread.is_alive())
    with get_db_connection() as connection:
        sync_state = get_ransomware_live_sync_state(connection)
    last_error = _ransomware_sync_last_error
    if get_ransomware_live_api_key() and "RANSOMWARE_LIVE_API_KEY" in last_error and "not set" in last_error.lower():
        last_error = ""
    return {
        "enabled": bool(_ransomware_sync_enabled and thread_alive),
        "running": bool(_ransomware_sync_running),
        "started_at": _ransomware_sync_started_at,
        "last_tick_at": _ransomware_sync_last_tick_at,
        "last_success_at": _ransomware_sync_last_success_at,
        "last_error": last_error,
        "last_source": _ransomware_sync_last_source,
        "last_ingested": _ransomware_sync_last_ingested,
        "interval_seconds": _ransomware_sync_interval_seconds,
        "limit": _ransomware_sync_limit,
        "record_count": int(sync_state.get("count") or 0),
        "latest_disclosure_time": str(sync_state.get("latest_disclosure_time") or ""),
    }


def _remaining_interval_seconds(interval_seconds: int, loop_started_at: float) -> float:
    elapsed_seconds = max(0.0, time.monotonic() - loop_started_at)
    return max(0.0, float(interval_seconds) - elapsed_seconds)


def _is_sqlite_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _run_code_monitoring_once() -> dict[str, Any]:
    return _run_code_monitoring_once_for_watchlist(None)


def _resolve_code_monitoring_watchlist_name(watchlist_id: int) -> str:
    if watchlist_id <= 0:
        return ""
    for item in list_code_watchlists_payload():
        if int(item.get("id") or 0) == int(watchlist_id):
            return str(item.get("name") or "")
    return ""


def _code_monitoring_task_snapshot(
    watchlist_id: int,
    *,
    watchlist_name: str = "",
    enabled: bool = False,
    running: bool = False,
    started_at: str = "",
    last_tick_at: str = "",
    last_success_at: str = "",
    last_error: str = "",
    interval_seconds: int = DEFAULT_CODE_MONITORING_INTERVAL_SECONDS,
    watchlist_count: int = 0,
    candidate_count: int = 0,
    hit_count: int = 0,
    clue_hit_count: int = 0,
    sensitive_hit_count: int = 0,
    stop_event: Event | None = None,
    thread: Thread | None = None,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "running": bool(running),
        "started_at": started_at,
        "last_tick_at": last_tick_at,
        "last_success_at": last_success_at,
        "last_error": last_error,
        "interval_seconds": int(interval_seconds or DEFAULT_CODE_MONITORING_INTERVAL_SECONDS),
        "watchlist_count": int(watchlist_count or 0),
        "candidate_count": int(candidate_count or 0),
        "hit_count": int(hit_count or 0),
        "clue_hit_count": int(clue_hit_count or 0),
        "sensitive_hit_count": int(sensitive_hit_count or 0),
        "target_watchlist_id": int(watchlist_id or 0),
        "target_watchlist_name": watchlist_name,
        "stop_event": stop_event,
        "thread": thread,
    }


def _active_code_monitoring_task_count() -> int:
    return sum(
        1
        for task in _code_monitoring_tasks.values()
        if bool(task.get("enabled")) and bool(task.get("thread")) and task["thread"].is_alive()
    )


def _code_monitoring_task_status_payload(watchlist_id: int, task: dict[str, Any] | None = None) -> dict[str, Any]:
    task = task or _code_monitoring_tasks.get(int(watchlist_id or 0)) or _code_monitoring_task_snapshot(
        int(watchlist_id or 0),
        watchlist_name=_resolve_code_monitoring_watchlist_name(int(watchlist_id or 0)),
    )
    thread_alive = bool(task.get("thread") and task["thread"].is_alive())
    return {
        "enabled": bool(task.get("enabled") and thread_alive),
        "running": bool(task.get("running")),
        "started_at": str(task.get("started_at") or ""),
        "last_tick_at": str(task.get("last_tick_at") or ""),
        "last_success_at": str(task.get("last_success_at") or ""),
        "last_error": str(task.get("last_error") or ""),
        "interval_seconds": int(task.get("interval_seconds") or DEFAULT_CODE_MONITORING_INTERVAL_SECONDS),
        "watchlist_count": int(task.get("watchlist_count") or 0),
        "candidate_count": int(task.get("candidate_count") or 0),
        "hit_count": int(task.get("hit_count") or 0),
        "clue_hit_count": int(task.get("clue_hit_count") or 0),
        "sensitive_hit_count": int(task.get("sensitive_hit_count") or 0),
        "target_watchlist_id": int(task.get("target_watchlist_id") or 0),
        "target_watchlist_name": str(task.get("target_watchlist_name") or ""),
        "active_watchlist_count": _active_code_monitoring_task_count(),
    }


def _positive_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _code_monitoring_continuous_scan_options(watchlist: dict[str, Any]) -> dict[str, Any]:
    search_page_limit = _positive_int(watchlist.get("search_page_limit"))
    max_results_per_term = _positive_int(watchlist.get("max_results_per_term"))
    return {
        "search_page_limit": search_page_limit if search_page_limit > 0 else DEFAULT_CODE_MONITORING_CONTINUOUS_SEARCH_PAGE_LIMIT,
        "max_results_per_term": max_results_per_term if max_results_per_term > 0 else DEFAULT_CODE_MONITORING_CONTINUOUS_MAX_RESULTS_PER_TERM,
        "detail_fetch": False,
        "browser_fallback": False,
    }


def _run_code_monitoring_once_for_watchlist(watchlist_id: int | None) -> dict[str, Any]:
    global _code_monitoring_running
    global _code_monitoring_last_tick_at
    global _code_monitoring_last_success_at
    global _code_monitoring_last_error
    global _code_monitoring_last_watchlist_count
    global _code_monitoring_last_candidate_count
    global _code_monitoring_last_hit_count
    global _code_monitoring_last_clue_hit_count
    global _code_monitoring_last_sensitive_hit_count
    selected_watchlist_id = int(watchlist_id or 0)
    with _code_monitoring_lock:
        if selected_watchlist_id > 0:
            existing_task = _code_monitoring_tasks.get(selected_watchlist_id)
            _code_monitoring_tasks[selected_watchlist_id] = {
                **(existing_task or _code_monitoring_task_snapshot(selected_watchlist_id, watchlist_name=_resolve_code_monitoring_watchlist_name(selected_watchlist_id))),
                "running": True,
                "last_tick_at": utc_now_iso(),
                "last_error": "",
            }
        else:
            _code_monitoring_running = True
            _code_monitoring_last_tick_at = utc_now_iso()
            _code_monitoring_last_error = ""
    try:
        watchlists = [item for item in list_code_watchlists_payload() if bool(item.get("enabled"))]
        if selected_watchlist_id:
            watchlists = [item for item in watchlists if int(item.get("id") or 0) == selected_watchlist_id]
            if not watchlists:
                raise ValueError(f"watchlist:{selected_watchlist_id}:not_found_or_disabled")
        aggregate = {
            "watchlist_count": len(watchlists),
            "candidate_count": 0,
            "hit_count": 0,
            "clue_hit_count": 0,
            "sensitive_hit_count": 0,
            "errors": [],
            "results": [],
        }
        for watchlist in watchlists:
            try:
                scan_options = _code_monitoring_continuous_scan_options(watchlist)
                result = scan_code_watchlist_once(
                    int(watchlist["id"]),
                    platforms=list(watchlist.get("platforms") or []),
                    file_extensions=list(watchlist.get("file_extensions") or []),
                    search_page_limit=scan_options["search_page_limit"],
                    max_results_per_term=scan_options["max_results_per_term"],
                    detail_fetch=scan_options["detail_fetch"],
                    browser_fallback=scan_options["browser_fallback"],
                    enabled_rule_keys=list(watchlist.get("enabled_rule_keys") or []),
                )
                aggregate["candidate_count"] += int(result.get("candidates") or 0)
                aggregate["hit_count"] += int(result.get("hits") or 0)
                aggregate["clue_hit_count"] += int(result.get("clue_hits") or 0)
                aggregate["sensitive_hit_count"] += int(result.get("sensitive_hits") or 0)
                aggregate["errors"].extend(result.get("errors") or [])
                aggregate["results"].append(result)
            except Exception as exc:
                aggregate["errors"].append(f"watchlist:{watchlist.get('id')}:{exc}")
        if aggregate["errors"] and not aggregate["results"]:
            raise RuntimeError("；".join(str(item) for item in aggregate["errors"][:3]))
        with _code_monitoring_lock:
            if selected_watchlist_id > 0:
                existing_task = _code_monitoring_tasks.get(selected_watchlist_id) or _code_monitoring_task_snapshot(
                    selected_watchlist_id,
                    watchlist_name=_resolve_code_monitoring_watchlist_name(selected_watchlist_id),
                )
                _code_monitoring_tasks[selected_watchlist_id] = {
                    **existing_task,
                    "last_success_at": utc_now_iso(),
                    "last_error": "",
                    "watchlist_count": aggregate["watchlist_count"],
                    "candidate_count": aggregate["candidate_count"],
                    "hit_count": aggregate["hit_count"],
                    "clue_hit_count": aggregate["clue_hit_count"],
                    "sensitive_hit_count": aggregate["sensitive_hit_count"],
                }
            else:
                _code_monitoring_last_success_at = utc_now_iso()
                _code_monitoring_last_watchlist_count = aggregate["watchlist_count"]
                _code_monitoring_last_candidate_count = aggregate["candidate_count"]
                _code_monitoring_last_hit_count = aggregate["hit_count"]
                _code_monitoring_last_clue_hit_count = aggregate["clue_hit_count"]
                _code_monitoring_last_sensitive_hit_count = aggregate["sensitive_hit_count"]
                _code_monitoring_last_error = ""
        return aggregate
    except Exception as exc:
        with _code_monitoring_lock:
            if selected_watchlist_id > 0:
                existing_task = _code_monitoring_tasks.get(selected_watchlist_id) or _code_monitoring_task_snapshot(
                    selected_watchlist_id,
                    watchlist_name=_resolve_code_monitoring_watchlist_name(selected_watchlist_id),
                )
                _code_monitoring_tasks[selected_watchlist_id] = {
                    **existing_task,
                    "last_error": str(exc),
                }
            else:
                _code_monitoring_last_error = str(exc)
        raise
    finally:
        with _code_monitoring_lock:
            if selected_watchlist_id > 0:
                existing_task = _code_monitoring_tasks.get(selected_watchlist_id)
                if existing_task is not None:
                    _code_monitoring_tasks[selected_watchlist_id] = {**existing_task, "running": False}
            else:
                _code_monitoring_running = False


def _run_code_monitoring_once_in_thread(watchlist_id: int | None = None) -> None:
    try:
        _run_code_monitoring_once_for_watchlist(watchlist_id)
    except Exception:
        return


def dispatch_run_code_monitoring_once() -> dict[str, Any]:
    global _code_monitoring_thread
    with _code_monitoring_lock:
        if _code_monitoring_running:
            return {
                **get_code_monitoring_continuous_status(),
                "message": "代码监测任务已在运行中",
            }
        thread = Thread(target=_run_code_monitoring_once_in_thread, daemon=True)
        _code_monitoring_thread = thread
        thread.start()
    return {
        **get_code_monitoring_continuous_status(),
        "message": "已触发一次代码监测持续扫描",
    }


def _code_monitoring_loop(watchlist_id: int, stop_event: Event) -> None:
    while not stop_event.is_set():
        loop_started_at = time.monotonic()
        try:
            _run_code_monitoring_once_for_watchlist(watchlist_id)
        except Exception as exc:
            if _is_sqlite_locked_error(exc):
                if stop_event.wait(DEFAULT_CODE_MONITORING_LOCK_RETRY_SECONDS):
                    break
                continue
        with _code_monitoring_lock:
            task = _code_monitoring_tasks.get(watchlist_id) or {}
            interval_seconds = int(task.get("interval_seconds") or DEFAULT_CODE_MONITORING_INTERVAL_SECONDS)
        if stop_event.wait(_remaining_interval_seconds(interval_seconds, loop_started_at)):
            break
    with _code_monitoring_lock:
        task = _code_monitoring_tasks.get(watchlist_id)
        if task is not None:
            _code_monitoring_tasks[watchlist_id] = {**task, "enabled": False, "running": False, "stop_event": None}


def start_code_monitoring_dispatch(
    interval_seconds: int = DEFAULT_CODE_MONITORING_INTERVAL_SECONDS,
    *,
    watchlist_id: int | None = None,
) -> dict[str, Any]:
    if interval_seconds <= 0:
        interval_seconds = DEFAULT_CODE_MONITORING_INTERVAL_SECONDS
    selected_watchlist_id = int(watchlist_id or 0)
    if selected_watchlist_id <= 0:
        raise ValueError("watchlist_id is required for code monitoring continuous scan")
    target_watchlist_name = ""
    enabled_watchlists = [item for item in list_code_watchlists_payload() if bool(item.get("enabled"))]
    target_watchlist = next((item for item in enabled_watchlists if int(item.get("id") or 0) == selected_watchlist_id), None)
    if target_watchlist is None:
        raise ValueError(f"watchlist not found or disabled: {selected_watchlist_id}")
    target_watchlist_name = str(target_watchlist.get("name") or "")
    with _code_monitoring_lock:
        existing_task = _code_monitoring_tasks.get(selected_watchlist_id)
        if existing_task and bool(existing_task.get("enabled")) and bool(existing_task.get("thread")) and existing_task["thread"].is_alive():
            _code_monitoring_tasks[selected_watchlist_id] = {
                **existing_task,
                "interval_seconds": interval_seconds,
                "target_watchlist_name": target_watchlist_name,
            }
            return {
                **_code_monitoring_task_status_payload(selected_watchlist_id),
                "message": "该监测对象的长期任务已在运行",
            }
        stop_event = Event()
        thread = Thread(target=_code_monitoring_loop, args=(selected_watchlist_id, stop_event), daemon=True)
        _code_monitoring_tasks[selected_watchlist_id] = {
            **(existing_task or _code_monitoring_task_snapshot(selected_watchlist_id, watchlist_name=target_watchlist_name)),
            "enabled": True,
            "running": False,
            "started_at": utc_now_iso(),
            "last_tick_at": "",
            "last_error": "",
            "interval_seconds": interval_seconds,
            "target_watchlist_id": selected_watchlist_id,
            "target_watchlist_name": target_watchlist_name,
            "stop_event": stop_event,
            "thread": thread,
        }
        thread.start()
    return {
        **_code_monitoring_task_status_payload(selected_watchlist_id),
        "message": "已开启该监测对象的代码长期后台扫描",
    }


def stop_code_monitoring_dispatch(*, watchlist_id: int | None = None) -> dict[str, Any]:
    selected_watchlist_id = int(watchlist_id or 0)
    if selected_watchlist_id <= 0:
        raise ValueError("watchlist_id is required for code monitoring continuous stop")
    with _code_monitoring_lock:
        existing_task = _code_monitoring_tasks.get(selected_watchlist_id)
        if existing_task is None or not bool(existing_task.get("enabled")) or existing_task.get("stop_event") is None:
            return {
                **_code_monitoring_task_status_payload(selected_watchlist_id),
                "message": "该监测对象的长期任务当前未运行",
            }
        stop_event = existing_task.get("stop_event")
        if stop_event is not None:
            stop_event.set()
        _code_monitoring_tasks[selected_watchlist_id] = {
            **existing_task,
            "enabled": False,
        }
    return {
        **_code_monitoring_task_status_payload(selected_watchlist_id),
        "message": "已停止该监测对象的代码长期后台扫描",
    }


def get_code_monitoring_continuous_status(*, watchlist_id: int | None = None) -> dict[str, Any]:
    selected_watchlist_id = int(watchlist_id or 0)
    if selected_watchlist_id > 0:
        with _code_monitoring_lock:
            task = _code_monitoring_tasks.get(selected_watchlist_id)
            return _code_monitoring_task_status_payload(selected_watchlist_id, task)
    with _code_monitoring_lock:
        active_tasks = [
            task for task in _code_monitoring_tasks.values()
            if bool(task.get("enabled")) and bool(task.get("thread")) and task["thread"].is_alive()
        ]
        if active_tasks:
            task = sorted(active_tasks, key=lambda item: str(item.get("started_at") or ""), reverse=True)[0]
            payload = _code_monitoring_task_status_payload(int(task.get("target_watchlist_id") or 0), task)
            payload["target_watchlist_name"] = task.get("target_watchlist_name") or "多个监测对象"
            return payload
    return _code_monitoring_task_status_payload(0)
def _run_netdisk_monitoring_once() -> dict[str, Any]:
    return _run_netdisk_monitoring_once_for_watchlist(None)


def _netdisk_watchlist_source_families(watchlist: dict[str, Any]) -> list[str]:
    families = watchlist.get("source_families")
    if not isinstance(families, list):
        return []
    return [str(item) for item in families if str(item)]


def _is_netdisk_monitoring_watchlist(watchlist: dict[str, Any]) -> bool:
    families = _netdisk_watchlist_source_families(watchlist)
    return not families or "netdisk_aggregator" in families


def _enabled_netdisk_monitoring_watchlists() -> list[dict[str, Any]]:
    return [
        item
        for item in list_watchlists_payload()
        if bool(item.get("enabled")) and _is_netdisk_monitoring_watchlist(item)
    ]


def _resolve_netdisk_monitoring_watchlist_name(watchlist_id: int) -> str:
    if watchlist_id <= 0:
        return ""
    for item in list_watchlists_payload():
        if int(item.get("id") or 0) == int(watchlist_id):
            return str(item.get("name") or "")
    return ""


def _netdisk_monitoring_task_snapshot(
    watchlist_id: int,
    *,
    watchlist_name: str = "",
    enabled: bool = False,
    running: bool = False,
    started_at: str = "",
    last_tick_at: str = "",
    last_success_at: str = "",
    last_error: str = "",
    interval_seconds: int = DEFAULT_NETDISK_MONITORING_INTERVAL_SECONDS,
    watchlist_count: int = 0,
    candidate_count: int = 0,
    hit_count: int = 0,
    error_count: int = 0,
    stop_event: Event | None = None,
    thread: Thread | None = None,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "running": bool(running),
        "started_at": started_at,
        "last_tick_at": last_tick_at,
        "last_success_at": last_success_at,
        "last_error": last_error,
        "interval_seconds": int(interval_seconds or DEFAULT_NETDISK_MONITORING_INTERVAL_SECONDS),
        "watchlist_count": int(watchlist_count or 0),
        "candidate_count": int(candidate_count or 0),
        "hit_count": int(hit_count or 0),
        "error_count": int(error_count or 0),
        "target_watchlist_id": int(watchlist_id or 0),
        "target_watchlist_name": watchlist_name,
        "stop_event": stop_event,
        "thread": thread,
    }


def _active_netdisk_monitoring_task_count() -> int:
    return sum(
        1
        for task in _netdisk_monitoring_tasks.values()
        if bool(task.get("enabled")) and bool(task.get("thread")) and task["thread"].is_alive()
    )


def _netdisk_monitoring_task_status_payload(watchlist_id: int, task: dict[str, Any] | None = None) -> dict[str, Any]:
    task = task or _netdisk_monitoring_tasks.get(int(watchlist_id or 0)) or _netdisk_monitoring_task_snapshot(
        int(watchlist_id or 0),
        watchlist_name=_resolve_netdisk_monitoring_watchlist_name(int(watchlist_id or 0)),
    )
    thread_alive = bool(task.get("thread") and task["thread"].is_alive())
    return {
        "enabled": bool(task.get("enabled") and thread_alive),
        "running": bool(task.get("running")),
        "started_at": str(task.get("started_at") or ""),
        "last_tick_at": str(task.get("last_tick_at") or ""),
        "last_success_at": str(task.get("last_success_at") or ""),
        "last_error": str(task.get("last_error") or ""),
        "interval_seconds": int(task.get("interval_seconds") or DEFAULT_NETDISK_MONITORING_INTERVAL_SECONDS),
        "watchlist_count": int(task.get("watchlist_count") or 0),
        "candidate_count": int(task.get("candidate_count") or 0),
        "hit_count": int(task.get("hit_count") or 0),
        "error_count": int(task.get("error_count") or 0),
        "target_watchlist_id": int(task.get("target_watchlist_id") or 0),
        "target_watchlist_name": str(task.get("target_watchlist_name") or ""),
        "active_watchlist_count": _active_netdisk_monitoring_task_count(),
    }


def _run_netdisk_monitoring_once_for_watchlist(watchlist_id: int | None) -> dict[str, Any]:
    global _netdisk_monitoring_once_running
    selected_watchlist_id = int(watchlist_id or 0)
    tick_at = utc_now_iso()
    with _netdisk_monitoring_lock:
        if selected_watchlist_id > 0:
            existing_task = _netdisk_monitoring_tasks.get(selected_watchlist_id)
            _netdisk_monitoring_tasks[selected_watchlist_id] = {
                **(
                    existing_task
                    or _netdisk_monitoring_task_snapshot(
                        selected_watchlist_id,
                        watchlist_name=_resolve_netdisk_monitoring_watchlist_name(selected_watchlist_id),
                    )
                ),
                "running": True,
                "last_tick_at": tick_at,
                "last_error": "",
            }
        else:
            _netdisk_monitoring_once_running = True
    try:
        watchlists = _enabled_netdisk_monitoring_watchlists()
        if selected_watchlist_id:
            watchlists = [item for item in watchlists if int(item.get("id") or 0) == selected_watchlist_id]
            if not watchlists:
                raise ValueError(f"watchlist:{selected_watchlist_id}:not_found_disabled_or_not_netdisk")
        aggregate = {
            "watchlist_count": len(watchlists),
            "candidate_count": 0,
            "hit_count": 0,
            "error_count": 0,
            "errors": [],
            "results": [],
        }
        for watchlist in watchlists:
            try:
                result = scan_watchlist_once(
                    int(watchlist["id"]),
                    source_families=["netdisk_aggregator"],
                    file_types=list(watchlist.get("file_types") or []),
                    detail_fetch=False,
                )
                errors = list(result.get("errors") or [])
                aggregate["candidate_count"] += int(result.get("candidates") or 0)
                aggregate["hit_count"] += int(result.get("hits") or 0)
                aggregate["error_count"] += len(errors)
                aggregate["errors"].extend(errors)
                aggregate["results"].append(result)
            except Exception as exc:
                aggregate["error_count"] += 1
                aggregate["errors"].append(f"watchlist:{watchlist.get('id')}:{exc}")
        last_error = "；".join(str(item) for item in aggregate["errors"][:3])
        with _netdisk_monitoring_lock:
            if selected_watchlist_id > 0:
                existing_task = _netdisk_monitoring_tasks.get(selected_watchlist_id) or _netdisk_monitoring_task_snapshot(
                    selected_watchlist_id,
                    watchlist_name=_resolve_netdisk_monitoring_watchlist_name(selected_watchlist_id),
                )
                _netdisk_monitoring_tasks[selected_watchlist_id] = {
                    **existing_task,
                    "last_success_at": utc_now_iso(),
                    "last_error": last_error,
                    "watchlist_count": aggregate["watchlist_count"],
                    "candidate_count": aggregate["candidate_count"],
                    "hit_count": aggregate["hit_count"],
                    "error_count": aggregate["error_count"],
                }
        return aggregate
    except Exception as exc:
        with _netdisk_monitoring_lock:
            if selected_watchlist_id > 0:
                existing_task = _netdisk_monitoring_tasks.get(selected_watchlist_id) or _netdisk_monitoring_task_snapshot(
                    selected_watchlist_id,
                    watchlist_name=_resolve_netdisk_monitoring_watchlist_name(selected_watchlist_id),
                )
                _netdisk_monitoring_tasks[selected_watchlist_id] = {
                    **existing_task,
                    "last_error": str(exc),
                }
        raise
    finally:
        with _netdisk_monitoring_lock:
            if selected_watchlist_id > 0:
                existing_task = _netdisk_monitoring_tasks.get(selected_watchlist_id)
                if existing_task is not None:
                    _netdisk_monitoring_tasks[selected_watchlist_id] = {**existing_task, "running": False}
            else:
                _netdisk_monitoring_once_running = False


def _run_netdisk_monitoring_once_in_thread(watchlist_id: int | None = None) -> None:
    try:
        _run_netdisk_monitoring_once_for_watchlist(watchlist_id)
    except Exception:
        return


def dispatch_run_netdisk_monitoring_once() -> dict[str, Any]:
    global _netdisk_monitoring_once_running
    global _netdisk_monitoring_once_thread
    with _netdisk_monitoring_lock:
        if _netdisk_monitoring_once_running:
            return {
                **_netdisk_monitoring_task_status_payload(0),
                "message": "网盘监测任务已在运行中",
            }
        thread = Thread(target=_run_netdisk_monitoring_once_in_thread, daemon=True)
        _netdisk_monitoring_once_running = True
        _netdisk_monitoring_once_thread = thread
        thread.start()
        payload = _netdisk_monitoring_task_status_payload(0)
    return {
        **payload,
        "message": "已触发一次网盘监测持续扫描",
    }


def _netdisk_monitoring_loop(watchlist_id: int, stop_event: Event) -> None:
    while not stop_event.is_set():
        loop_started_at = time.monotonic()
        try:
            _run_netdisk_monitoring_once_for_watchlist(watchlist_id)
        except Exception:
            pass
        with _netdisk_monitoring_lock:
            task = _netdisk_monitoring_tasks.get(watchlist_id) or {}
            interval_seconds = int(task.get("interval_seconds") or DEFAULT_NETDISK_MONITORING_INTERVAL_SECONDS)
        if stop_event.wait(_remaining_interval_seconds(interval_seconds, loop_started_at)):
            break
    with _netdisk_monitoring_lock:
        task = _netdisk_monitoring_tasks.get(watchlist_id)
        if task is not None:
            _netdisk_monitoring_tasks[watchlist_id] = {**task, "enabled": False, "running": False, "stop_event": None}


def start_netdisk_monitoring_dispatch(
    interval_seconds: int = DEFAULT_NETDISK_MONITORING_INTERVAL_SECONDS,
    *,
    watchlist_id: int | None = None,
) -> dict[str, Any]:
    if interval_seconds <= 0:
        interval_seconds = DEFAULT_NETDISK_MONITORING_INTERVAL_SECONDS
    selected_watchlist_id = int(watchlist_id or 0)
    if selected_watchlist_id <= 0:
        raise ValueError("watchlist_id is required for netdisk monitoring continuous scan")
    enabled_watchlists = _enabled_netdisk_monitoring_watchlists()
    target_watchlist = next((item for item in enabled_watchlists if int(item.get("id") or 0) == selected_watchlist_id), None)
    if target_watchlist is None:
        raise ValueError(f"watchlist not found, disabled, or not netdisk enabled: {selected_watchlist_id}")
    target_watchlist_name = str(target_watchlist.get("name") or "")
    with _netdisk_monitoring_lock:
        existing_task = _netdisk_monitoring_tasks.get(selected_watchlist_id)
        if existing_task and bool(existing_task.get("enabled")) and bool(existing_task.get("thread")) and existing_task["thread"].is_alive():
            _netdisk_monitoring_tasks[selected_watchlist_id] = {
                **existing_task,
                "interval_seconds": interval_seconds,
                "target_watchlist_name": target_watchlist_name,
            }
            return {
                **_netdisk_monitoring_task_status_payload(selected_watchlist_id),
                "message": "该监测对象的网盘长期任务已在运行",
            }
        stop_event = Event()
        thread = Thread(target=_netdisk_monitoring_loop, args=(selected_watchlist_id, stop_event), daemon=True)
        _netdisk_monitoring_tasks[selected_watchlist_id] = {
            **(existing_task or _netdisk_monitoring_task_snapshot(selected_watchlist_id, watchlist_name=target_watchlist_name)),
            "enabled": True,
            "running": False,
            "started_at": utc_now_iso(),
            "last_tick_at": "",
            "last_error": "",
            "interval_seconds": interval_seconds,
            "target_watchlist_id": selected_watchlist_id,
            "target_watchlist_name": target_watchlist_name,
            "stop_event": stop_event,
            "thread": thread,
        }
        thread.start()
        payload = _netdisk_monitoring_task_status_payload(selected_watchlist_id)
    return {
        **payload,
        "message": "已开启该监测对象的网盘长期后台扫描",
    }


def stop_netdisk_monitoring_dispatch(*, watchlist_id: int | None = None) -> dict[str, Any]:
    selected_watchlist_id = int(watchlist_id or 0)
    if selected_watchlist_id <= 0:
        raise ValueError("watchlist_id is required for netdisk monitoring continuous stop")
    with _netdisk_monitoring_lock:
        existing_task = _netdisk_monitoring_tasks.get(selected_watchlist_id)
        if existing_task is None or not bool(existing_task.get("enabled")) or existing_task.get("stop_event") is None:
            return {
                **_netdisk_monitoring_task_status_payload(selected_watchlist_id),
                "message": "该监测对象的网盘长期任务当前未运行",
            }
        stop_event = existing_task.get("stop_event")
        if stop_event is not None:
            stop_event.set()
        _netdisk_monitoring_tasks[selected_watchlist_id] = {
            **existing_task,
            "enabled": False,
        }
        payload = _netdisk_monitoring_task_status_payload(selected_watchlist_id)
    return {
        **payload,
        "message": "已停止该监测对象的网盘长期后台扫描",
    }


def get_netdisk_monitoring_continuous_status(*, watchlist_id: int | None = None) -> dict[str, Any]:
    selected_watchlist_id = int(watchlist_id or 0)
    if selected_watchlist_id > 0:
        with _netdisk_monitoring_lock:
            task = _netdisk_monitoring_tasks.get(selected_watchlist_id)
            return _netdisk_monitoring_task_status_payload(selected_watchlist_id, task)
    with _netdisk_monitoring_lock:
        active_tasks = [
            task for task in _netdisk_monitoring_tasks.values()
            if bool(task.get("enabled")) and bool(task.get("thread")) and task["thread"].is_alive()
        ]
        if active_tasks:
            task = sorted(active_tasks, key=lambda item: str(item.get("started_at") or ""), reverse=True)[0]
            payload = _netdisk_monitoring_task_status_payload(int(task.get("target_watchlist_id") or 0), task)
            payload["target_watchlist_name"] = task.get("target_watchlist_name") or "多个监测对象"
            return payload
    return _netdisk_monitoring_task_status_payload(0)


def update_site_enabled(site_name: str, enabled: bool) -> dict[str, Any]:
    config = set_site_enabled(site_name=site_name, enabled=enabled)
    return {
        "site_name": config.site_name,
        "enabled": config.enabled,
        "message": "已启用站点采集" if config.enabled else "已停用站点采集",
    }
