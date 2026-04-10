from __future__ import annotations

import logging
import os
from threading import Lock, Thread
import time

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from darkweb_collector.api_actions import (
    dispatch_run_all_enabled_sites_once,
    dispatch_run_site,
    dispatch_run_vulnerability_sync_once,
    get_continuous_dispatch_status,
    get_vulnerability_sync_status,
    start_continuous_dispatch,
    start_vulnerability_sync_dispatch,
    stop_continuous_dispatch,
    stop_vulnerability_sync_dispatch,
    update_site_enabled,
)
from darkweb_collector.api_data import build_behavior_payload, build_intelligence_payload, build_jobs_payload, warm_api_payloads
from darkweb_collector.api_data import build_event_detail, build_event_records, build_vulnerability_detail, build_vulnerability_records
from darkweb_collector.runtime import project_root


app = FastAPI(title="Darkweb Collector API", version="1.0.0")
logger = logging.getLogger("darkweb_collector.api")
_warmup_lock = Lock()
_warmup_started = False
collector_output_dir = (project_root() / "output").resolve()
collector_output_dir.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/collector-output",
    StaticFiles(directory=str(collector_output_dir), html=False),
    name="collector-output",
)


def _run_payload_warmup() -> None:
    started_at = time.perf_counter()
    try:
        warm_api_payloads()
    except Exception:
        logger.exception("API warmup failed")
        return
    logger.info("API warmup completed in %.2fs", time.perf_counter() - started_at)


@app.on_event("startup")
def warm_payloads_on_startup() -> None:
    global _warmup_started
    if os.environ.get("DARKWEB_SKIP_API_WARMUP") == "1":
        logger.info("skipping API warmup because DARKWEB_SKIP_API_WARMUP=1")
        return
    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True
    Thread(target=_run_payload_warmup, name="api-payload-warmup", daemon=True).start()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/intelligence")
def intelligence() -> dict:
    return build_intelligence_payload()


@app.get("/api/jobs")
def jobs() -> dict:
    return build_jobs_payload()


@app.get("/api/behavior")
def behavior() -> dict:
    return build_behavior_payload()


@app.get("/api/events")
def events() -> list[dict]:
    return build_event_records()


@app.get("/api/events/{event_id}")
def event_detail(event_id: str, translate_detail: bool = False) -> dict:
    payload = build_event_detail(event_id, translate_detail=translate_detail)
    if payload is None:
        raise HTTPException(status_code=404, detail="event not found")
    return payload


@app.get("/api/vulnerabilities")
def vulnerabilities(
    severity: str | None = None,
    is_exploited: bool | None = None,
    days: int | None = None,
    limit: int | None = None,
) -> list[dict]:
    return build_vulnerability_records(
        severity=severity,
        is_exploited=is_exploited,
        days=days,
        limit=limit,
    )


@app.get("/api/vulnerabilities/{event_id}")
def vulnerability_detail(event_id: str) -> dict:
    payload = build_vulnerability_detail(event_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="vulnerability event not found")
    return payload


class RunSiteRequest(BaseModel):
    site_name: str
    force: bool = True


class RunAllRequest(BaseModel):
    force: bool = True


class SetSiteEnabledRequest(BaseModel):
    enabled: bool


class VulnerabilitySyncRunRequest(BaseModel):
    limit: int = 300


class VulnerabilitySyncStartRequest(BaseModel):
    interval_seconds: int = 3600
    limit: int = 300


@app.post("/api/jobs/run-site")
def run_site(payload: RunSiteRequest) -> dict:
    return dispatch_run_site(site_name=payload.site_name, force=payload.force)


@app.post("/api/jobs/run-all")
def run_all(payload: RunAllRequest) -> dict:
    return dispatch_run_all_enabled_sites_once(force=payload.force)


@app.post("/api/jobs/run-all-once")
def run_all_once(payload: RunAllRequest) -> dict:
    return dispatch_run_all_enabled_sites_once(force=payload.force)


@app.post("/api/jobs/run-all-continuous/start")
def run_all_continuous_start() -> dict:
    return start_continuous_dispatch()


@app.post("/api/jobs/run-all-continuous/stop")
def run_all_continuous_stop() -> dict:
    return stop_continuous_dispatch()


@app.get("/api/jobs/continuous-status")
def continuous_status() -> dict:
    return get_continuous_dispatch_status()


@app.get("/api/vulnerabilities/sync/status")
def vulnerability_sync_status() -> dict:
    return get_vulnerability_sync_status()


@app.post("/api/vulnerabilities/sync/run")
def vulnerability_sync_run(payload: VulnerabilitySyncRunRequest) -> dict:
    return dispatch_run_vulnerability_sync_once(limit=payload.limit)


@app.post("/api/vulnerabilities/sync/start")
def vulnerability_sync_start(payload: VulnerabilitySyncStartRequest) -> dict:
    return start_vulnerability_sync_dispatch(
        interval_seconds=payload.interval_seconds,
        limit=payload.limit,
    )


@app.post("/api/vulnerabilities/sync/stop")
def vulnerability_sync_stop() -> dict:
    return stop_vulnerability_sync_dispatch()


@app.post("/api/sites/{site_name}/enabled")
def set_site_enabled(site_name: str, payload: SetSiteEnabledRequest) -> dict:
    return update_site_enabled(site_name=site_name, enabled=payload.enabled)
