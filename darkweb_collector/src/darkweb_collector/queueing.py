from __future__ import annotations

import sys


SEED_HTTP_QUEUE = "seed_http"
DETAIL_HTTP_QUEUE = "detail_http"
BROWSER_RENDER_QUEUE = "browser_render"

QUEUE_CONCURRENCY = {
    SEED_HTTP_QUEUE: 1,
    DETAIL_HTTP_QUEUE: 2,
    BROWSER_RENDER_QUEUE: 2,
}

QUEUE_MAX_TASKS_PER_CHILD = {
    BROWSER_RENDER_QUEUE: 10,
}

MAX_RETRIES = 3


def queue_for_seed(fetch_mode: str) -> str:
    if fetch_mode == "browser":
        return BROWSER_RENDER_QUEUE
    return SEED_HTTP_QUEUE


def queue_for_detail(fetch_mode: str) -> str:
    if fetch_mode == "browser":
        return BROWSER_RENDER_QUEUE
    return DETAIL_HTTP_QUEUE


def retry_backoff_seconds(retry_count: int) -> int:
    return min(60, 2 ** max(retry_count, 0))


def build_worker_command(queue_name: str) -> list[str]:
    if queue_name not in QUEUE_CONCURRENCY:
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
        str(QUEUE_CONCURRENCY[queue_name]),
        "--prefetch-multiplier",
        "1",
    ]
    max_tasks = QUEUE_MAX_TASKS_PER_CHILD.get(queue_name)
    if max_tasks is not None:
        command.extend(["--max-tasks-per-child", str(max_tasks)])
    return command
