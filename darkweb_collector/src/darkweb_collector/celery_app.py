from __future__ import annotations

import os

from celery import Celery


def _broker_url() -> str:
    return os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


app = Celery(
    "darkweb_collector",
    broker=_broker_url(),
    backend=_broker_url(),
)

app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_default_queue="seed_http",
)

app.autodiscover_tasks(["darkweb_collector"])
