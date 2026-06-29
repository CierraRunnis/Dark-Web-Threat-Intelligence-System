from __future__ import annotations

import importlib
import logging
import os
import secrets
import time
from pathlib import Path
from threading import Lock, Thread

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from darkweb_collector.bot_assistant import (
    BotAssistantError,
    bot_config_status,
    build_markdown_payload,
    build_text_payload,
    ensure_wecom_aibot_listener,
    load_bot_config,
    post_bot_payload,
    send_intelligence_digest,
    set_bot_config,
)
from darkweb_collector.api_actions import (
    dispatch_run_all_enabled_sites_once,
    dispatch_run_code_monitoring_once,
    dispatch_run_netdisk_monitoring_once,
    dispatch_run_ransomware_sync_once,
    dispatch_run_site,
    dispatch_run_vulnerability_sync_once,
    get_code_monitoring_continuous_status,
    get_continuous_dispatch_status,
    get_netdisk_monitoring_continuous_status,
    get_ransomware_sync_status,
    get_vulnerability_sync_status,
    start_code_monitoring_dispatch,
    start_netdisk_monitoring_dispatch,
    start_ransomware_sync_dispatch,
    start_continuous_dispatch,
    start_vulnerability_sync_dispatch,
    stop_code_monitoring_dispatch,
    stop_netdisk_monitoring_dispatch,
    stop_ransomware_sync_dispatch,
    stop_continuous_dispatch,
    stop_vulnerability_sync_dispatch,
    update_site_enabled,
)
import darkweb_collector.api_data as api_data_module
from darkweb_collector.document_exposure import (
    add_document_exposure_review,
    build_document_exposure_detail,
    list_exposure_scan_runs_payload,
    build_document_exposure_summary,
    ensure_netdisk_source_health_defaults,
    list_document_exposures_payload,
    list_netdisk_source_health_payload,
    list_netdisk_source_states_payload,
    list_watchlists_payload,
    netdisk_source_policy,
    reset_netdisk_source_states_payload,
    save_watchlist_payload,
    scan_watchlist_once,
)
from darkweb_collector.code_monitoring import (
    add_code_monitoring_review,
    build_code_hit_detail,
    build_code_monitoring_summary,
    delete_code_watchlist_payload,
    list_code_hits_payload,
    list_code_scan_runs_payload,
    list_code_watchlists_payload,
    save_code_watchlist_payload,
    scan_code_watchlist_once,
)
from darkweb_collector.document_exposure_sessions import (
    auto_detect_platform_sessions,
    build_platform_session_payloads,
    launch_platform_login,
    remove_platform_session,
    save_platform_session,
    verify_platform_session,
)
from darkweb_collector.document_exposure_platforms import list_exposure_platforms
import darkweb_collector.monitoring_rules as monitoring_rules_module
import darkweb_collector.normalized_intelligence as normalized_intelligence_module
from darkweb_collector.db import get_db_connection, list_monitoring_keyword_notifications
from darkweb_collector.ransomware_live import get_ransomware_live_config_status, set_ransomware_live_api_key
from darkweb_collector.runtime import output_root


app = FastAPI(title="Darkweb Collector API", version="1.0.0")
logger = logging.getLogger("darkweb_collector.api")
_warmup_lock = Lock()
_warmup_started = False
_auth_lock = Lock()
_auth_sessions: dict[str, dict[str, object]] = {}
_api_auto_reload_enabled = os.environ.get("DARKWEB_API_AUTO_RELOAD") == "1"
collector_output_dir = output_root()
collector_output_dir.mkdir(parents=True, exist_ok=True)

AUTH_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/health",
}


def _auth_enabled() -> bool:
    return os.environ.get("DARKWEB_API_AUTH_DISABLED") != "1"


def _auth_username() -> str:
    return os.environ.get("DARKWEB_AUTH_USERNAME", "admin")


def _auth_password() -> str:
    return os.environ.get("DARKWEB_AUTH_PASSWORD", "").strip()


def _auth_session_ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get("DARKWEB_AUTH_TTL_SECONDS", "43200")))
    except ValueError:
        return 43200


def _auth_user_payload(username: str) -> dict[str, str]:
    return {
        "username": username,
        "display_name": "个人用户" if username == "admin" else username,
    }


def _extract_bearer_token(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _create_auth_session(username: str) -> tuple[str, float]:
    now = time.time()
    expires_at = now + _auth_session_ttl_seconds()
    token = secrets.token_urlsafe(32)
    with _auth_lock:
        _auth_sessions[token] = {
            "username": username,
            "created_at": now,
            "expires_at": expires_at,
        }
    return token, expires_at


def _get_auth_user(token: str) -> dict[str, str] | None:
    if not token:
        return None
    now = time.time()
    with _auth_lock:
        session = _auth_sessions.get(token)
        if not session:
            return None
        expires_at = float(session.get("expires_at") or 0)
        if expires_at < now:
            _auth_sessions.pop(token, None)
            return None
        return _auth_user_payload(str(session.get("username") or ""))


def _revoke_auth_session(token: str) -> None:
    if not token:
        return
    with _auth_lock:
        _auth_sessions.pop(token, None)


def _requires_auth(request: Request) -> bool:
    path = request.url.path
    if not _auth_enabled() or request.method == "OPTIONS":
        return False
    if not path.startswith("/api/") or path in AUTH_EXEMPT_PATHS:
        return False
    return True


def _reload_api_modules():
    if not _api_auto_reload_enabled:
        return api_data_module
    importlib.reload(normalized_intelligence_module)
    importlib.reload(monitoring_rules_module)
    return importlib.reload(api_data_module)


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


@app.middleware("http")
async def require_api_auth(request: Request, call_next):
    if not _requires_auth(request):
        return await call_next(request)
    token = _extract_bearer_token(request.headers.get("authorization", ""))
    user = _get_auth_user(token)
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期"})
    request.state.current_user = user
    return await call_next(request)


def _run_payload_warmup() -> None:
    started_at = time.perf_counter()
    try:
        _reload_api_modules().warm_api_payloads()
    except Exception:
        logger.exception("API warmup failed")
        return
    logger.info("API warmup completed in %.2fs", time.perf_counter() - started_at)


@app.on_event("startup")
def warm_payloads_on_startup() -> None:
    try:
        ensure_wecom_aibot_listener()
    except Exception:
        logger.exception("failed to start WeCom AI Bot listener")
    try:
        ensure_netdisk_source_health_defaults()
    except Exception:
        logger.exception("failed to initialize netdisk source health records")
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


class AuthLoginRequest(BaseModel):
    username: str = ""
    account: str = ""
    password: str = ""


@app.post("/api/auth/login")
def auth_login(payload: AuthLoginRequest) -> dict:
    username = (payload.username or payload.account).strip()
    password = payload.password
    expected_password = _auth_password()
    if not expected_password:
        raise HTTPException(status_code=503, detail="DARKWEB_AUTH_PASSWORD is not configured")
    username_matches = secrets.compare_digest(username, _auth_username())
    password_matches = secrets.compare_digest(password, expected_password)
    if not username_matches or not password_matches:
        raise HTTPException(status_code=401, detail="账号或密码错误")

    token, expires_at = _create_auth_session(username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": int(expires_at),
        "user": _auth_user_payload(username),
    }


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, str]:
    return getattr(request.state, "current_user", _auth_user_payload(_auth_username()))


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> dict[str, bool]:
    token = _extract_bearer_token(request.headers.get("authorization", ""))
    _revoke_auth_session(token)
    return {"ok": True}


@app.get("/api/intelligence")
def intelligence() -> dict:
    return _reload_api_modules().build_intelligence_payload()


@app.get("/api/jobs")
def jobs() -> dict:
    return _reload_api_modules().build_jobs_payload()


@app.get("/api/events")
def events() -> list[dict]:
    return _reload_api_modules().build_event_records()


@app.get("/api/events/{event_id}")
def event_detail(event_id: str, translate_detail: bool = False) -> dict:
    payload = _reload_api_modules().build_event_detail(event_id, translate_detail=translate_detail)
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
    return _reload_api_modules().build_vulnerability_records(
        severity=severity,
        is_exploited=is_exploited,
        days=days,
        limit=limit,
    )


@app.get("/api/vulnerabilities/{event_id}")
def vulnerability_detail(event_id: str) -> dict:
    payload = _reload_api_modules().build_vulnerability_detail(event_id)
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


class RansomwareSyncRunRequest(BaseModel):
    limit: int = 0


class RansomwareSyncStartRequest(BaseModel):
    interval_seconds: int = 3600
    limit: int = 0


class RansomwareConfigRequest(BaseModel):
    api_key: str


class MonitoringKeywordRow(BaseModel):
    keyword: str
    category: str
    weight: int
    enabled: bool = True
    match_mode: str = "contains"


class MonitoringKeywordsRequest(BaseModel):
    keywords: list[MonitoringKeywordRow]


class BotSendRequest(BaseModel):
    type: str = "digest"
    content: str = ""
    provider: str | None = None
    bot_id: str | None = None
    chat_id: str | None = None
    websocket_url: str | None = None
    webhook_url: str | None = None
    webhook_key: str | None = None
    secret: str | None = None
    dry_run: bool = False
    limit: int = 5


class BotConfigRequest(BaseModel):
    provider: str = "wechat_work_aibot"
    bot_id: str = ""
    chat_id: str = ""
    websocket_url: str = ""
    webhook_url: str = ""
    webhook_key: str = ""
    secret: str = ""


class ExposureWatchTermRequest(BaseModel):
    term: str
    term_type: str
    weight: int = 10
    enabled: bool = True


class ExposureWatchlistRequest(BaseModel):
    id: int | None = None
    name: str
    organization_name: str
    enabled: bool = True
    notes: str = ""
    source_families: list[str] = []
    file_types: list[str] = []
    page_limit: int = 4
    detail_fetch: bool = True
    terms: list[ExposureWatchTermRequest] = []


class PlatformSessionSaveRequest(BaseModel):
    account_label: str = ""


class ExposureScanRequest(BaseModel):
    max_candidates_per_term: int = 6
    source_families: list[str] = []
    file_types: list[str] = []
    page_limit: int | None = None
    detail_fetch: bool | None = None


class DocumentExposureReviewRequest(BaseModel):
    status: str
    reviewer: str = ""
    note: str = ""


class NetdiskMonitoringContinuousStartRequest(BaseModel):
    interval_seconds: int = 3600
    watchlist_id: int = Field(..., gt=0)


class NetdiskMonitoringContinuousStopRequest(BaseModel):
    watchlist_id: int = Field(..., gt=0)


class NetdiskSourceStateResetRequest(BaseModel):
    watchlist_id: int | None = None
    source_key: str = ""
    term: str = ""


class CodeWatchTermRequest(BaseModel):
    term: str
    term_type: str
    weight: int = 0
    enabled: bool = True


class CodeEnterpriseProfileRequest(BaseModel):
    official_names: list[str] = Field(default_factory=list)
    brand_aliases: list[str] = Field(default_factory=list)
    english_aliases: list[str] = Field(default_factory=list)
    root_domains: list[str] = Field(default_factory=list)
    trusted_subdomain_patterns: list[str] = Field(default_factory=list)
    internal_system_keywords: list[str] = Field(default_factory=list)
    negative_aliases: list[str] = Field(default_factory=list)
    short_alias_guard: list[str] = Field(default_factory=list)


class CodeWatchlistRequest(BaseModel):
    id: int | None = None
    name: str
    organization_name: str
    enabled: bool = True
    notes: str = ""
    platforms: list[str] = []
    file_extensions: list[str] = []
    search_page_limit: int = 0
    max_results_per_term: int = 0
    detail_fetch: bool = True
    enabled_rule_keys: list[str] = []
    terms: list[CodeWatchTermRequest] = []
    enterprise_profile: CodeEnterpriseProfileRequest = Field(default_factory=CodeEnterpriseProfileRequest)


class CodeScanRequest(BaseModel):
    platforms: list[str] = []
    file_extensions: list[str] = []
    search_page_limit: int | None = None
    max_results_per_term: int | None = None
    detail_fetch: bool | None = None
    enabled_rule_keys: list[str] = []


class CodeMonitoringReviewRequest(BaseModel):
    status: str
    reviewer: str = ""
    note: str = ""


class CodeMonitoringContinuousStartRequest(BaseModel):
    interval_seconds: int = 3600
    watchlist_id: int = Field(..., gt=0)


class CodeMonitoringContinuousStopRequest(BaseModel):
    watchlist_id: int = Field(..., gt=0)


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


@app.get("/api/ransomware/sync/status")
def ransomware_sync_status() -> dict:
    return get_ransomware_sync_status()


@app.post("/api/ransomware/sync/run")
def ransomware_sync_run(payload: RansomwareSyncRunRequest) -> dict:
    return dispatch_run_ransomware_sync_once(limit=payload.limit)


@app.post("/api/ransomware/sync/start")
def ransomware_sync_start(payload: RansomwareSyncStartRequest) -> dict:
    return start_ransomware_sync_dispatch(
        interval_seconds=payload.interval_seconds,
        limit=payload.limit,
    )


@app.post("/api/ransomware/sync/stop")
def ransomware_sync_stop() -> dict:
    return stop_ransomware_sync_dispatch()


@app.get("/api/ransomware/config")
def ransomware_config() -> dict:
    return get_ransomware_live_config_status()


@app.post("/api/ransomware/config")
def ransomware_config_save(payload: RansomwareConfigRequest) -> dict:
    return set_ransomware_live_api_key(payload.api_key)


@app.post("/api/sites/{site_name}/enabled")
def set_site_enabled(site_name: str, payload: SetSiteEnabledRequest) -> dict:
    return update_site_enabled(site_name=site_name, enabled=payload.enabled)


@app.get("/api/monitoring/keywords")
def monitoring_keywords() -> list[dict]:
    _reload_api_modules()
    return monitoring_rules_module.get_monitoring_keywords()


@app.post("/api/monitoring/keywords")
def update_monitoring_keywords(payload: MonitoringKeywordsRequest) -> list[dict]:
    _reload_api_modules()
    return monitoring_rules_module.save_monitoring_keywords([item.model_dump() for item in payload.keywords])


@app.get("/api/analysis/monitoring-status")
def monitoring_status() -> dict:
    _reload_api_modules()
    return monitoring_rules_module.build_monitoring_status()


@app.get("/api/monitoring/keyword-notifications")
def monitoring_keyword_notifications() -> list[dict]:
    with get_db_connection() as connection:
        return list_monitoring_keyword_notifications(connection)


@app.get("/api/bot/status")
def bot_status() -> dict:
    return bot_config_status()


@app.get("/api/platform-sessions")
def platform_sessions(module: str | None = None) -> list[dict]:
    return build_platform_session_payloads(module=module, manageable_only=True)


@app.get("/api/exposure-platforms")
def exposure_platforms(module: str | None = None) -> list[dict]:
    rows = []
    for platform in list_exposure_platforms(module=module):
        row = {
            "platform": platform.key,
            "label": platform.label,
            "module": platform.module,
            "platform_type": platform.platform_type,
            "homepage_url": platform.homepage_url,
            "login_url": platform.login_url,
            "domains": list(platform.domains),
            "requires_login": platform.requires_login,
            "discovery_only": platform.discovery_only,
        }
        if platform.platform_type == "netdisk_search":
            row.update(netdisk_source_policy(platform.key))
        rows.append(row)
    return rows


@app.post("/api/platform-sessions/auto-detect")
def platform_sessions_auto_detect(module: str | None = None) -> list[dict]:
    return auto_detect_platform_sessions(module=module)


@app.post("/api/platform-sessions/{platform}/launch-login")
def platform_session_launch(platform: str) -> dict:
    try:
        return launch_platform_login(platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/platform-sessions/{platform}/save")
def platform_session_save(platform: str, payload: PlatformSessionSaveRequest) -> dict:
    try:
        return save_platform_session(platform, account_label=payload.account_label)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/platform-sessions/{platform}/verify")
def platform_session_verify(platform: str) -> dict:
    try:
        return verify_platform_session(platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/platform-sessions/{platform}")
def platform_session_delete(platform: str) -> dict:
    try:
        return remove_platform_session(platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/exposure-watchlists")
def exposure_watchlists() -> list[dict]:
    return list_watchlists_payload()


@app.post("/api/exposure-watchlists")
def save_exposure_watchlist(payload: ExposureWatchlistRequest) -> dict:
    return save_watchlist_payload(payload.model_dump())


@app.post("/api/exposure-watchlists/{watchlist_id}/scan")
def exposure_watchlist_scan(watchlist_id: int, payload: ExposureScanRequest) -> dict:
    try:
        return scan_watchlist_once(
            watchlist_id,
            max_candidates_per_term=payload.max_candidates_per_term,
            source_families=payload.source_families,
            file_types=payload.file_types,
            page_limit=payload.page_limit,
            detail_fetch=payload.detail_fetch,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/exposure-scans")
def exposure_scans(watchlist_id: int | None = None, limit: int = 50) -> list[dict]:
    return list_exposure_scan_runs_payload(watchlist_id=watchlist_id, limit=limit)


@app.get("/api/document-exposures")
def document_exposures(
    watchlist_id: int | None = None,
    review_status: str | None = None,
    platform: str | None = None,
    access_state: str | None = None,
    source_family: str | None = None,
    limit: int = 200,
) -> list[dict]:
    return list_document_exposures_payload(
        watchlist_id=watchlist_id,
        review_status=review_status,
        platform=platform,
        access_state=access_state,
        source_family=source_family,
        limit=limit,
    )


@app.get("/api/document-exposures/summary")
def document_exposure_summary(source_family: str | None = None) -> dict:
    return build_document_exposure_summary(source_family=source_family)


@app.get("/api/document-exposures/netdisk/source-states")
def netdisk_source_states(watchlist_id: int | None = None) -> list[dict]:
    return list_netdisk_source_states_payload(watchlist_id=watchlist_id)


@app.get("/api/document-exposures/netdisk/source-health")
def netdisk_source_health() -> list[dict]:
    return list_netdisk_source_health_payload()


@app.post("/api/document-exposures/netdisk/source-states/reset")
def netdisk_source_states_reset(payload: NetdiskSourceStateResetRequest) -> dict:
    return reset_netdisk_source_states_payload(payload.model_dump())


@app.get("/api/document-exposures/netdisk/continuous-status")
def netdisk_monitoring_continuous_status(watchlist_id: int | None = None) -> dict:
    return get_netdisk_monitoring_continuous_status(watchlist_id=watchlist_id)


@app.post("/api/document-exposures/netdisk/continuous/run")
def netdisk_monitoring_continuous_run() -> dict:
    return dispatch_run_netdisk_monitoring_once()


@app.post("/api/document-exposures/netdisk/continuous/start")
def netdisk_monitoring_continuous_start(payload: NetdiskMonitoringContinuousStartRequest) -> dict:
    try:
        return start_netdisk_monitoring_dispatch(
            interval_seconds=payload.interval_seconds,
            watchlist_id=payload.watchlist_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/document-exposures/netdisk/continuous/stop")
def netdisk_monitoring_continuous_stop(payload: NetdiskMonitoringContinuousStopRequest) -> dict:
    try:
        return stop_netdisk_monitoring_dispatch(watchlist_id=payload.watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/document-exposures/{hit_id}")
def document_exposure_detail(hit_id: int) -> dict:
    payload = build_document_exposure_detail(hit_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="document exposure not found")
    return payload


@app.post("/api/document-exposures/{hit_id}/review")
def document_exposure_review(hit_id: int, payload: DocumentExposureReviewRequest) -> dict:
    try:
        return add_document_exposure_review(
            hit_id,
            status=payload.status,
            reviewer=payload.reviewer,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/code-monitoring/summary")
def code_monitoring_summary() -> dict:
    return build_code_monitoring_summary()


@app.get("/api/code-monitoring/watchlists")
def code_monitoring_watchlists() -> list[dict]:
    return list_code_watchlists_payload()


@app.post("/api/code-monitoring/watchlists")
def save_code_monitoring_watchlist(payload: CodeWatchlistRequest) -> dict:
    return save_code_watchlist_payload(payload.model_dump())


@app.delete("/api/code-monitoring/watchlists/{watchlist_id}")
def delete_code_monitoring_watchlist(watchlist_id: int) -> dict:
    try:
        return delete_code_watchlist_payload(watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/code-monitoring/watchlists/{watchlist_id}/scan")
def code_monitoring_watchlist_scan(watchlist_id: int, payload: CodeScanRequest) -> dict:
    try:
        return scan_code_watchlist_once(
            watchlist_id,
            platforms=payload.platforms,
            file_extensions=payload.file_extensions,
            search_page_limit=payload.search_page_limit,
            max_results_per_term=payload.max_results_per_term,
            detail_fetch=payload.detail_fetch,
            enabled_rule_keys=payload.enabled_rule_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/code-monitoring/scans")
def code_monitoring_scans(watchlist_id: int | None = None, limit: int = 50) -> list[dict]:
    return list_code_scan_runs_payload(watchlist_id=watchlist_id, limit=limit)


@app.get("/api/code-monitoring/continuous-status")
def code_monitoring_continuous_status(watchlist_id: int | None = None) -> dict:
    return get_code_monitoring_continuous_status(watchlist_id=watchlist_id)


@app.post("/api/code-monitoring/continuous/run")
def code_monitoring_continuous_run() -> dict:
    return dispatch_run_code_monitoring_once()


@app.post("/api/code-monitoring/continuous/start")
def code_monitoring_continuous_start(payload: CodeMonitoringContinuousStartRequest) -> dict:
    try:
        return start_code_monitoring_dispatch(
            interval_seconds=payload.interval_seconds,
            watchlist_id=payload.watchlist_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/code-monitoring/continuous/stop")
def code_monitoring_continuous_stop(payload: CodeMonitoringContinuousStopRequest) -> dict:
    try:
        return stop_code_monitoring_dispatch(watchlist_id=payload.watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/code-monitoring/hits")
def code_monitoring_hits(
    watchlist_id: int | None = None,
    review_status: str | None = None,
    platform: str | None = None,
    sensitive_type: str | None = None,
    include_suppressed: bool = False,
    limit: int = 200,
) -> list[dict]:
    return list_code_hits_payload(
        watchlist_id=watchlist_id,
        review_status=review_status,
        platform=platform,
        sensitive_type=sensitive_type,
        include_suppressed=include_suppressed,
        limit=limit,
    )


@app.get("/api/code-monitoring/hits/{hit_id}")
def code_monitoring_hit_detail(hit_id: int) -> dict:
    payload = build_code_hit_detail(hit_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="code monitoring hit not found")
    return payload


@app.post("/api/code-monitoring/hits/{hit_id}/review")
def code_monitoring_review(hit_id: int, payload: CodeMonitoringReviewRequest) -> dict:
    try:
        return add_code_monitoring_review(
            hit_id,
            status=payload.status,
            reviewer=payload.reviewer,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/bot/config")
def save_bot_config(payload: BotConfigRequest) -> dict:
    try:
        status = set_bot_config(
            provider=payload.provider,
            bot_id=payload.bot_id,
            chat_id=payload.chat_id,
            websocket_url=payload.websocket_url,
            webhook_url=payload.webhook_url,
            webhook_key=payload.webhook_key,
            secret=payload.secret,
        )
    except BotAssistantError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        from darkweb_collector.monitoring_notifications import notify_current_keyword_matches

        config = load_bot_config()
        if config.chat_ids or payload.provider != "wechat_work_aibot":
            status["keyword_notification_scan"] = notify_current_keyword_matches(config=config)
    except Exception:
        logger.exception("failed to scan monitoring keyword notifications after bot config update")
    return status


@app.post("/api/bot/send")
def send_bot(payload: BotSendRequest) -> dict:
    config = load_bot_config(
        provider=payload.provider,
        bot_id=payload.bot_id,
        chat_id=payload.chat_id,
        websocket_url=payload.websocket_url,
        webhook_url=payload.webhook_url,
        webhook_key=payload.webhook_key,
        secret=payload.secret,
        dry_run=payload.dry_run,
    )
    try:
        if payload.type == "digest":
            intelligence_payload = _reload_api_modules().build_intelligence_payload()
            return send_intelligence_digest(intelligence_payload, config=config, limit=payload.limit)
        if payload.type == "text":
            if not payload.content:
                raise HTTPException(status_code=400, detail="content is required for text messages")
            return post_bot_payload(build_text_payload(payload.content), config)
        if payload.type == "markdown":
            if not payload.content:
                raise HTTPException(status_code=400, detail="content is required for markdown messages")
            return post_bot_payload(build_markdown_payload(payload.content), config)
    except BotAssistantError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="type must be one of: digest, text, markdown")
