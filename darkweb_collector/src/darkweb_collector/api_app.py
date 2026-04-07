from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from darkweb_collector.api_actions import (
    dispatch_run_all_enabled_sites_once,
    dispatch_run_site,
    get_continuous_dispatch_status,
    start_continuous_dispatch,
    stop_continuous_dispatch,
    update_site_enabled,
)
from darkweb_collector.api_data import build_behavior_payload, build_intelligence_payload, build_jobs_payload
from darkweb_collector.api_data import build_event_detail, build_event_records, build_vulnerability_detail, build_vulnerability_records
from darkweb_collector.runtime import project_root


app = FastAPI(title="Darkweb Collector API", version="1.0.0")
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
def event_detail(event_id: str) -> dict:
    payload = build_event_detail(event_id)
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


@app.post("/api/sites/{site_name}/enabled")
def set_site_enabled(site_name: str, payload: SetSiteEnabledRequest) -> dict:
    return update_site_enabled(site_name=site_name, enabled=payload.enabled)
