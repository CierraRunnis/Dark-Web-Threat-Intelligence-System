from __future__ import annotations

import os
import re
import socket
import sys

from darkweb_collector.models import SiteConfig


SEED_HTTP_QUEUE = "seed_http"
DETAIL_HTTP_QUEUE = "detail_http"
BROWSER_RENDER_QUEUE = "browser_render"
BROWSER_PUBLIC_QUEUE = "browser_public"
BROWSER_ONION_QUEUE = "browser_onion"
BROWSER_ACTIVE_QUEUES = (BROWSER_PUBLIC_QUEUE, BROWSER_ONION_QUEUE)
BROWSER_QUEUES = (*BROWSER_ACTIVE_QUEUES, BROWSER_RENDER_QUEUE)

QUEUE_CONCURRENCY = {
    SEED_HTTP_QUEUE: 1,
    DETAIL_HTTP_QUEUE: 2,
    BROWSER_RENDER_QUEUE: 3,
    BROWSER_PUBLIC_QUEUE: 2,
    BROWSER_ONION_QUEUE: 1,
}

QUEUE_MAX_TASKS_PER_CHILD = {
    BROWSER_RENDER_QUEUE: 10,
    BROWSER_PUBLIC_QUEUE: 10,
    BROWSER_ONION_QUEUE: 10,
}

MAX_RETRIES = 3


def _positive_int_from_env(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(value, 1)


def browser_queue_concurrency(queue_name: str) -> int:
    configured_total = _positive_int_from_env(
        "DARKWEB_BROWSER_CONCURRENCY",
        QUEUE_CONCURRENCY[BROWSER_RENDER_QUEUE],
    )
    public_default = max((configured_total + 1) // 2, 1)
    onion_default = max(configured_total - public_default, 1)
    if queue_name == BROWSER_PUBLIC_QUEUE:
        return _positive_int_from_env("DARKWEB_BROWSER_PUBLIC_CONCURRENCY", public_default)
    if queue_name == BROWSER_ONION_QUEUE:
        return _positive_int_from_env("DARKWEB_BROWSER_ONION_CONCURRENCY", onion_default)
    if queue_name == BROWSER_RENDER_QUEUE:
        return configured_total
    raise ValueError(f"unsupported browser queue '{queue_name}'")


def browser_concurrency() -> int:
    return browser_queue_concurrency(BROWSER_PUBLIC_QUEUE) + browser_queue_concurrency(BROWSER_ONION_QUEUE)


def queue_concurrency(queue_name: str) -> int:
    if "," in queue_name:
        queue_names = [name.strip() for name in queue_name.split(",") if name.strip()]
        if not queue_names or any(name not in QUEUE_CONCURRENCY for name in queue_names):
            raise ValueError(f"unsupported queue list '{queue_name}'")
        return 1
    if queue_name in BROWSER_QUEUES:
        return browser_queue_concurrency(queue_name)
    if queue_name not in QUEUE_CONCURRENCY:
        raise ValueError(f"unsupported queue '{queue_name}'")
    return QUEUE_CONCURRENCY[queue_name]


def worker_hostname(queue_name: str) -> str:
    safe_queue = re.sub(r"[^A-Za-z0-9_-]+", "-", queue_name).strip("-") or "worker"
    host = re.sub(r"[^A-Za-z0-9_.-]+", "-", socket.gethostname()).strip(".-") or "host"
    return f"{safe_queue}-{os.getpid()}@{host}"


def _browser_queue(config: SiteConfig) -> str:
    queue_name = config.browser_queue
    if queue_name not in BROWSER_QUEUES:
        raise ValueError(f"unsupported browser queue '{queue_name}' for site '{config.site_name}'")
    return queue_name


def queue_for_seed(config: SiteConfig | str) -> str:
    if isinstance(config, str):
        return BROWSER_RENDER_QUEUE if config == "browser" else SEED_HTTP_QUEUE
    if config.seed_fetch_mode == "browser":
        return _browser_queue(config)
    return SEED_HTTP_QUEUE


def queue_for_detail(config: SiteConfig | str) -> str:
    if isinstance(config, str):
        return BROWSER_RENDER_QUEUE if config == "browser" else DETAIL_HTTP_QUEUE
    if config.detail_fetch_mode == "browser":
        return _browser_queue(config)
    return DETAIL_HTTP_QUEUE


def retry_backoff_seconds(retry_count: int) -> int:
    return min(60, 2 ** max(retry_count, 0))


def build_worker_command(queue_name: str) -> list[str]:
    queue_names = [name.strip() for name in queue_name.split(",") if name.strip()]
    if not queue_names or any(name not in QUEUE_CONCURRENCY for name in queue_names):
        raise ValueError(f"unsupported queue '{queue_name}'")

    command = [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "darkweb_collector.celery_app:app",
        "worker",
        "-Q",
        queue_name,
        "--concurrency",
        str(queue_concurrency(queue_name)),
        "--prefetch-multiplier",
        "1",
        "--hostname",
        worker_hostname(queue_name),
    ]
    max_tasks = 10 if any(name in BROWSER_QUEUES for name in queue_names) else None
    if max_tasks is not None:
        command.extend(["--max-tasks-per-child", str(max_tasks)])
    return command
