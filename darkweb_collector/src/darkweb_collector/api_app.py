from __future__ import annotations

import importlib
import json
import logging
import os
import secrets
import time
from hashlib import sha1
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from darkweb_collector.ai_aggregation.router import router as ai_aggregation_router
from darkweb_collector.db import database_health_payload
from darkweb_collector.migration_api import router as migration_router
from darkweb_collector.postgres_backend import close_postgres_pools
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


class AsciiSafeJSONResponse(JSONResponse):
    """对所有非 ASCII 字符做 \\uXXXX 转义的 JSON 响应。

    用于 AI 调用接口：避免某些客户端（PowerShell 5.x 的 Invoke-WebRequest、
    部分浏览器直连、运行在 GBK 终端的 curl、某些 LLM 网关）忽略
    `Content-Type: application/json; charset=utf-8`，按系统代码页（如中文 Windows
    的 CP936/GBK）解码 UTF-8 字节导致中文乱码的问题。
    body 全部为 ASCII 字符，任何代码页解码都不会乱；JSON 解析器会自动还原
    \\uXXXX 转义为正常的 Unicode 字符串，对接收方完全透明。
    """

    media_type = "application/json; charset=utf-8"

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=True,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("ascii")

from darkweb_collector.api_actions import (
    dispatch_run_all_enabled_sites_once,
    dispatch_run_code_monitoring_once,
    dispatch_run_ransomware_sync_once,
    dispatch_run_site,
    dispatch_run_vulnerability_sync_once,
    dispatch_run_netdisk_monitoring_once,
    get_code_monitoring_continuous_status,
    get_continuous_dispatch_status,
    get_netdisk_monitoring_continuous_status,
    get_ransomware_sync_status,
    get_vulnerability_sync_status,
    start_code_monitoring_dispatch,
    start_ransomware_sync_dispatch,
    start_netdisk_monitoring_dispatch,
    start_continuous_dispatch,
    start_vulnerability_sync_dispatch,
    stop_code_monitoring_dispatch,
    stop_ransomware_sync_dispatch,
    stop_netdisk_monitoring_dispatch,
    stop_continuous_dispatch,
    stop_vulnerability_sync_dispatch,
    update_site_enabled,
)
from darkweb_collector.auth_accounts import (
    ASSIGNABLE_MODULES,
    create_account as create_stored_auth_account,
    delete_account as delete_stored_auth_account,
    get_account as get_stored_auth_account,
    list_accounts as list_stored_auth_accounts,
    normalize_modules,
    update_account as update_stored_auth_account,
    update_account_profile as update_stored_auth_account_profile,
    update_account_password,
    verify_password as verify_stored_password,
)
from darkweb_collector.document_exposure import (
    add_document_exposure_review,
    build_document_exposure_detail,
    build_document_exposure_summary,
    delete_watchlist_payload,
    ensure_netdisk_source_health_defaults,
    list_document_exposures_payload,
    list_exposure_scan_runs_payload,
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
    build_agent_code_hit_detail,
    build_code_hit_detail,
    build_code_monitoring_summary,
    delete_code_watchlist_payload,
    list_code_hits_payload,
    list_code_scan_runs_payload,
    list_code_watchlists_payload,
    save_code_watchlist_payload,
    scan_code_watchlist_once,
)
from darkweb_collector.document_exposure_platforms import list_exposure_platforms
from darkweb_collector.document_exposure_sessions import (
    auto_detect_platform_sessions,
    build_platform_session_payloads,
    launch_platform_login,
    remove_platform_session,
    visible_platform_login_available,
    save_platform_session,
    verify_platform_session,
)
from darkweb_collector.github_app_auth import (
    GitHubAppConfigError,
    GitHubAppConnectionError,
    delete_github_app_config,
    github_app_config_status,
    save_github_app_config,
)
from darkweb_collector.remote_browser_sessions import (
    close_all_remote_browser_sessions,
    close_remote_browser_login,
    control_remote_browser,
    finish_remote_browser_login,
    get_remote_browser_state,
    proxy_remote_browser_rfb,
    proxy_remote_browser_stream,
    start_remote_browser_login,
    validate_remote_browser_ticket,
)
import darkweb_collector.api_data as api_data_module
import darkweb_collector.monitoring_rules as monitoring_rules_module
import darkweb_collector.normalized_intelligence as normalized_intelligence_module
from darkweb_collector.ransomware_live import get_ransomware_live_config_status, set_ransomware_live_api_key
from darkweb_collector.runtime import output_root, project_root
from darkweb_collector.session_cookies import (
    clear_session_cookie,
    get_session_cookie_status,
    list_cookie_capable_sites,
    set_session_cookie,
)
from darkweb_collector.version_check import build_version_status


app = FastAPI(title="Darkweb Collector API", version="1.0.0")
app.include_router(ai_aggregation_router)
app.include_router(migration_router)
logger = logging.getLogger("darkweb_collector.api")
_warmup_lock = Lock()
_warmup_started = False
_auth_lock = Lock()
_auth_sessions: dict[str, dict[str, object]] = {}
_api_auto_reload_enabled = os.environ.get("DARKWEB_API_AUTO_RELOAD") == "1"
collector_output_dir = output_root().resolve()
collector_output_dir.mkdir(parents=True, exist_ok=True)

AUTH_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/ai/intelligence",
    "/api/health",
    "/api/jobs/continuous-status",
    "/api/jobs/run-all-continuous/start",
    "/api/jobs/run-all-continuous/stop",
    "/api/system/version",
}
AGENT_API_PREFIX = "/api/agent/"
AGENT_API_KEY_ENV = "DARKWEB_AGENT_API_KEY"


DEFAULT_AUTH_PASSWORD = "123456"


def _auth_enabled() -> bool:
    return os.environ.get("DARKWEB_API_AUTH_DISABLED") != "1"


def _auth_username() -> str:
    return os.environ.get("DARKWEB_AUTH_USERNAME", "admin")


def _default_auth_password_file() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "DarkWebThreatIntel" / "auth-password.txt"

    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        return Path(user_profile) / "AppData" / "Local" / "DarkWebThreatIntel" / "auth-password.txt"

    return Path.home() / "AppData" / "Local" / "DarkWebThreatIntel" / "auth-password.txt"


def _auth_password_file_path() -> Path:
    password_file = os.environ.get("DARKWEB_AUTH_PASSWORD_FILE", "").strip()
    return Path(password_file) if password_file else _default_auth_password_file()


def _auth_password() -> str:
    password = os.environ.get("DARKWEB_AUTH_PASSWORD", "").strip()
    if password:
        return password

    try:
        password = _auth_password_file_path().read_text(encoding="utf-8").strip()
    except OSError:
        password = ""
    return password or DEFAULT_AUTH_PASSWORD


def _write_auth_password(password: str) -> None:
    if os.environ.get("DARKWEB_AUTH_PASSWORD", "").strip():
        raise HTTPException(status_code=409, detail="DARKWEB_AUTH_PASSWORD is controlled by environment")

    password_path = _auth_password_file_path()
    password_path.parent.mkdir(parents=True, exist_ok=True)
    password_path.write_text(password, encoding="utf-8")


def _auth_session_ttl_seconds() -> int:
    try:
        return max(60, int(os.environ.get("DARKWEB_AUTH_TTL_SECONDS", "43200")))
    except ValueError:
        return 43200


def _is_bootstrap_admin(username: str) -> bool:
    return secrets.compare_digest(username, _auth_username())


def _admin_user_payload() -> dict[str, object]:
    username = _auth_username()
    return {
        "username": username,
        "display_name": "管理员",
        "role": "admin",
        "is_admin": True,
        "modules": list(ASSIGNABLE_MODULES),
        "enabled": True,
        "fixed": True,
    }


def _auth_user_payload(username: str) -> dict[str, object] | None:
    if _is_bootstrap_admin(username):
        return _admin_user_payload()
    account = get_stored_auth_account(username)
    if not account or not bool(account.get("enabled")):
        return None
    return account


def _extract_bearer_token(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _extract_agent_api_key(request: Request) -> str:
    return request.headers.get("x-api-key", "").strip() or _extract_bearer_token(
        request.headers.get("authorization", "")
    )


def _agent_api_auth_error(request: Request) -> JSONResponse | None:
    expected_key = os.environ.get(AGENT_API_KEY_ENV, "").strip()
    if not expected_key:
        return JSONResponse(status_code=503, content={"detail": f"{AGENT_API_KEY_ENV} is not configured"})
    provided_key = _extract_agent_api_key(request)
    if not provided_key or not secrets.compare_digest(provided_key, expected_key):
        return JSONResponse(status_code=401, content={"detail": "invalid agent API key"})
    return None


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


def _get_auth_user(token: str) -> dict[str, object] | None:
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


def _revoke_user_sessions(username: str) -> None:
    with _auth_lock:
        stale_tokens = [
            token
            for token, session in _auth_sessions.items()
            if str(session.get("username") or "").casefold() == username.casefold()
        ]
        for token in stale_tokens:
            _auth_sessions.pop(token, None)


def _require_admin(request: Request) -> dict[str, object]:
    user = getattr(request.state, "current_user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以管理账号")
    return user


def _require_module(request: Request, module_key: str) -> dict[str, object]:
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    if user.get("role") == "admin" or module_key in (user.get("modules") or []):
        return user
    raise HTTPException(status_code=403, detail="当前账号没有该模块的访问权限")


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
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

app.mount(
    "/collector-output",
    StaticFiles(directory=str(collector_output_dir), html=False),
    name="collector-output",
)


@app.middleware("http")
async def require_api_auth(request: Request, call_next):
    if request.url.path.startswith(AGENT_API_PREFIX):
        auth_error = _agent_api_auth_error(request)
        if auth_error is not None:
            return auth_error
        return await call_next(request)
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


@app.on_event("shutdown")
def close_runtime_resources_on_shutdown() -> None:
    try:
        close_all_remote_browser_sessions()
    finally:
        close_postgres_pools()


def _database_health_response(payload: dict[str, Any]) -> dict[str, Any]:
    backend = str(payload.get("backend") or "")
    schema = str(payload.get("schema") or "")
    versions = [str(value) for value in (payload.get("schemaVersions") or [])]
    schema_version = versions[-1] if versions else ""
    healthy = payload.get("status") == "ok"
    database_name = str(payload.get("database") or "")
    if backend == "sqlite" and database_name:
        database_name = Path(database_name).name
    database = {
        **payload,
        "database": database_name,
        "database_name": database_name,
        "engine": backend,
        "database_engine": backend,
        "schema": schema,
        "database_schema": schema,
        "schema_version": schema_version,
        "healthy": healthy,
        "database_ready": healthy,
    }
    return {
        "status": "ok" if healthy else "error",
        "engine": backend,
        "database_engine": backend,
        "schema": schema,
        "database_schema": schema,
        "schema_version": schema_version,
        "healthy": healthy,
        "database_ready": healthy,
        "database": database,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        response = _database_health_response(database_health_payload())
    except Exception as exc:
        logger.exception("database health check failed")
        raise HTTPException(
            status_code=503,
            detail={
                "message": "数据库健康检查执行失败",
                "error_type": type(exc).__name__,
            },
        ) from exc
    if response["status"] != "ok":
        raise HTTPException(
            status_code=503,
            detail={
                "message": "数据库结构或迁移版本未就绪",
                "database": response["database"],
            },
        )
    return response


@app.get("/api/system/version")
def system_version(force: bool = False) -> dict:
    return build_version_status(force=force)


class AuthLoginRequest(BaseModel):
    username: str = ""
    account: str = ""
    password: str = ""


class AuthPasswordChangeRequest(BaseModel):
    current_password: str = ""
    new_password: str = ""


class AuthAccountCreateRequest(BaseModel):
    username: str = ""
    display_name: str = ""
    password: str = ""
    modules: list[str] = Field(default_factory=list)


class AuthAccountUpdateRequest(BaseModel):
    display_name: str = ""
    modules: list[str] = Field(default_factory=list)
    enabled: bool = True


class AuthAccountProfileUpdateRequest(BaseModel):
    username: str = ""
    display_name: str = ""
    new_password: str = ""


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


@app.post("/api/auth/login")
def auth_login(payload: AuthLoginRequest) -> dict:
    username = (payload.username or payload.account).strip()
    password = payload.password
    if _is_bootstrap_admin(username):
        authenticated = secrets.compare_digest(password, _auth_password())
        canonical_username = _auth_username()
    else:
        account = get_stored_auth_account(username, include_password=True)
        authenticated = bool(
            account
            and account.get("enabled")
            and verify_stored_password(password, str(account.get("password_hash") or ""))
        )
        canonical_username = str(account.get("username") or username) if account else username

    if not authenticated:
        raise HTTPException(status_code=401, detail="账号或密码错误")

    token, expires_at = _create_auth_session(canonical_username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": int(expires_at),
        "user": _auth_user_payload(canonical_username),
    }


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, object]:
    return getattr(request.state, "current_user", None) or _admin_user_payload()


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> dict[str, bool]:
    token = _extract_bearer_token(request.headers.get("authorization", ""))
    _revoke_auth_session(token)
    return {"ok": True}


@app.post("/api/auth/change-password")
def auth_change_password(request: Request, payload: AuthPasswordChangeRequest) -> dict[str, bool]:
    current_password = payload.current_password
    new_password = payload.new_password.strip()
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="new password must be at least 6 characters")

    user = getattr(request.state, "current_user", None) or _admin_user_payload()
    username = str(user.get("username") or "")
    if user.get("role") == "admin":
        if not secrets.compare_digest(current_password, _auth_password()):
            raise HTTPException(status_code=400, detail="current password is incorrect")
        _write_auth_password(new_password)
        return {"ok": True}

    account = get_stored_auth_account(username, include_password=True)
    if not account or not verify_stored_password(
        current_password,
        str(account.get("password_hash") or ""),
    ):
        raise HTTPException(status_code=400, detail="current password is incorrect")
    if not update_account_password(username, new_password):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"ok": True}


def _validated_account_modules(modules: list[str]) -> list[str]:
    try:
        return normalize_modules(modules)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _validate_new_username(username: str) -> str:
    normalized = username.strip()
    if len(normalized) < 3 or len(normalized) > 64 or any(char.isspace() for char in normalized):
        raise HTTPException(status_code=400, detail="账号需为 3-64 个不含空格的字符")
    if normalized.casefold() == _auth_username().casefold():
        raise HTTPException(status_code=409, detail="该账号已存在")
    return normalized


@app.get("/api/auth/accounts")
def auth_accounts(request: Request) -> dict[str, list[dict[str, object]]]:
    _require_admin(request)
    return {"items": [_admin_user_payload(), *list_stored_auth_accounts()]}


@app.post("/api/auth/accounts", status_code=201)
def auth_account_create(request: Request, payload: AuthAccountCreateRequest) -> dict[str, object]:
    _require_admin(request)
    username = _validate_new_username(payload.username)
    password = payload.password.strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码至少需要 6 位")
    account = create_stored_auth_account(
        username=username,
        display_name=payload.display_name.strip() or username,
        password=password,
        modules=_validated_account_modules(payload.modules),
    )
    if account is None:
        raise HTTPException(status_code=409, detail="该账号已存在")
    return account


@app.put("/api/auth/accounts/{username}")
def auth_account_update(
    username: str,
    request: Request,
    payload: AuthAccountUpdateRequest,
) -> dict[str, object]:
    _require_admin(request)
    if username.casefold() == _auth_username().casefold():
        raise HTTPException(status_code=409, detail="固定管理员账号不能修改")
    account = update_stored_auth_account(
        username,
        display_name=payload.display_name.strip() or username,
        modules=_validated_account_modules(payload.modules),
        enabled=payload.enabled,
    )
    if account is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if not payload.enabled:
        _revoke_user_sessions(username)
    return account


@app.put("/api/auth/accounts/{username}/profile")
def auth_account_profile_update(
    username: str,
    request: Request,
    payload: AuthAccountProfileUpdateRequest,
) -> dict[str, object]:
    _require_admin(request)
    if username.casefold() == _auth_username().casefold():
        raise HTTPException(status_code=409, detail="固定管理员账号不能修改")

    current = get_stored_auth_account(username)
    if current is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    new_username = _validate_new_username(payload.username or username)
    existing = get_stored_auth_account(new_username)
    if existing and str(existing.get("username") or "").casefold() != username.casefold():
        raise HTTPException(status_code=409, detail="该账号已存在")

    new_password = payload.new_password.strip()
    if new_password and len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少需要 6 位")

    account = update_stored_auth_account_profile(
        username,
        new_username=new_username,
        display_name=payload.display_name.strip() or str(current.get("display_name") or new_username),
        new_password=new_password,
    )
    if account is None:
        raise HTTPException(status_code=409, detail="账号信息更新失败，登录账号可能已存在")
    if new_username.casefold() != username.casefold() or new_password:
        _revoke_user_sessions(username)
    return account


@app.delete("/api/auth/accounts/{username}")
def auth_account_delete(username: str, request: Request) -> dict[str, bool]:
    _require_admin(request)
    if username.casefold() == _auth_username().casefold():
        raise HTTPException(status_code=409, detail="固定管理员账号不能删除")
    if not delete_stored_auth_account(username):
        raise HTTPException(status_code=404, detail="账号不存在")
    _revoke_user_sessions(username)
    return {"ok": True}


@app.get("/api/intelligence")
def intelligence() -> dict:
    return _reload_api_modules().build_intelligence_payload()


def _conditional_aggregate_response(request: Request, payload: dict[str, Any]) -> Response:
    identity = f"{payload.get('snapshotRevision', '')}:{request.url.query}"
    etag = f'"{sha1(identity.encode("utf-8")).hexdigest()}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=0, must-revalidate",
        "Vary": "Authorization, Accept-Encoding",
    }
    if request.headers.get("if-none-match", "").strip() == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=payload, headers=headers)


@app.get("/api/dashboard/overview")
def dashboard_overview(
    request: Request,
    days: int = 7,
    event_type: str = "all",
    severity: str = "",
    keyword: str = "",
) -> Response:
    payload = _reload_api_modules().build_dashboard_overview(
        days=days,
        event_type=event_type,
        severity=severity,
        keyword=keyword,
    )
    return _conditional_aggregate_response(request, payload)


@app.get("/api/threat-situation")
def threat_situation(request: Request, days: int = 30) -> Response:
    _require_module(request, "threat_situation")
    payload = _reload_api_modules().build_threat_situation(days=days)
    return _conditional_aggregate_response(request, payload)


@app.get("/api/intelligence/search")
def intelligence_search(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    types: str | None = None,
    keyword: str | None = None,
    days: int | None = None,
    severity: str | None = None,
    industry: str | None = None,
    region: str | None = None,
    country: str | None = None,
    attacker: str | None = None,
    min_risk_score: int | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    _require_module(request, "intelligence_search")
    return _reload_api_modules().build_intelligence_search_page(
        page=page,
        page_size=page_size,
        types=types,
        keyword=keyword,
        days=days,
        severity=severity,
        industry=industry,
        region=region,
        country=country,
        attacker=attacker,
        min_risk_score=min_risk_score,
        sort=sort,
    )


@app.get("/api/intelligence/ransomware")
def intelligence_ransomware(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    stage: str | None = None,
    industry: str | None = None,
    days: int | None = None,
    severity: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    _require_module(request, "ransomware")
    return _reload_api_modules().build_ransomware_page(
        page=page,
        page_size=page_size,
        keyword=keyword,
        stage=stage,
        industry=industry,
        days=days,
        severity=severity,
        sort=sort,
    )


@app.get("/api/intelligence/data-leak")
def intelligence_data_leak(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    keyword: str = "",
    category: str = "",
    days: int | None = None,
    attacker: str | None = None,
    industry: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    _require_module(request, "data_leak")
    return _reload_api_modules().build_data_leak_page(
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        days=days,
        attacker=attacker,
        industry=industry,
        severity=severity,
        source=source,
        sort=sort,
    )


@app.get("/api/intelligence/export")
def intelligence_export(
    request: Request,
    dataset: str = "search",
    types: str | None = None,
    keyword: str | None = None,
    days: int | None = None,
    severity: str | None = None,
    industry: str | None = None,
    region: str | None = None,
    country: str | None = None,
    attacker: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    source: str | None = None,
    min_risk_score: int | None = None,
    sort: str | None = None,
) -> StreamingResponse:
    normalized_dataset = dataset.replace("-", "_").strip().lower()
    module_key = {
        "search": "intelligence_search",
        "ransomware": "ransomware",
        "data_leak": "data_leak",
    }.get(normalized_dataset)
    if module_key is None:
        raise HTTPException(status_code=400, detail="unsupported export dataset")
    _require_module(request, module_key)
    parameters = {
        "keyword": keyword,
        "days": days,
        "severity": severity,
        "industry": industry,
        "sort": sort,
    }
    if normalized_dataset == "search":
        parameters.update(
            {
                "types": types,
                "region": region,
                "country": country,
                "attacker": attacker,
                "min_risk_score": min_risk_score,
            }
        )
    elif normalized_dataset == "ransomware":
        parameters["stage"] = stage
    elif normalized_dataset == "data_leak":
        parameters.update({"category": category, "attacker": attacker, "source": source})
    return StreamingResponse(
        _reload_api_modules().iter_intelligence_csv(normalized_dataset, parameters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{normalized_dataset}.csv"'},
    )


@app.get("/api/data-leaks")
def data_leaks(
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
    category: str = "",
    days: int | None = None,
    attacker: str | None = None,
    industry: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    sort: str | None = None,
) -> dict:
    return _reload_api_modules().build_data_leak_page(
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        days=days,
        attacker=attacker,
        industry=industry,
        severity=severity,
        source=source,
        sort=sort,
    )


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
    keyword: str | None = None,
    industry: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    sort: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> list[dict] | dict[str, Any]:
    if page is not None or page_size is not None or keyword is not None:
        return _reload_api_modules().build_vulnerability_page(
            severity=severity,
            is_exploited=is_exploited,
            days=days,
            keyword=keyword,
            industry=industry,
            vendor=vendor,
            product=product,
            sort=sort,
            page=page or 1,
            page_size=page_size or 20,
        )

    return _reload_api_modules().build_vulnerability_records(
        severity=severity,
        is_exploited=is_exploited,
        days=days,
        limit=limit,
    )


@app.get("/api/vulnerabilities/export")
def vulnerability_export(
    request: Request,
    severity: str | None = None,
    is_exploited: bool | None = None,
    days: int | None = None,
    keyword: str | None = None,
    industry: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    sort: str | None = None,
) -> StreamingResponse:
    _require_module(request, "vulnerability_alerts")
    return StreamingResponse(
        _reload_api_modules().iter_intelligence_csv(
            "vulnerability",
            {
                "severity": severity,
                "is_exploited": is_exploited,
                "days": days,
                "keyword": keyword,
                "industry": industry,
                "vendor": vendor,
                "product": product,
                "sort": sort,
            },
        ),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vulnerabilities.csv"'},
    )


@app.get("/api/vulnerabilities/{event_id}")
def vulnerability_detail(event_id: str) -> dict:
    payload = _reload_api_modules().build_vulnerability_detail(event_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="vulnerability event not found")
    return payload


@app.get("/api/ai/intelligence")
def ai_intelligence(
    request: Request,
    event_type: str | None = None,
    days: int | None = None,
    industry: str | None = None,
    region: str | None = None,
    country: str | None = None,
    severity: str | None = None,
    attacker: str | None = None,
    keyword: str | None = None,
    min_risk_score: int | None = None,
    limit: int | None = None,
) -> JSONResponse:
    """供 AI 调用的统一情报接口：返回与前端同源的、已分类筛选好的事件 + 聚合统计。

    参数（全部可选，未提供则不参与筛选）：
    - event_type: data_leak / ransomware / vulnerability / all（也支持逗号分隔多选）
    - days: 仅返回最近 N 天的事件
    - industry / region / country: 行业、宏观区域、国家（中英文均可，做包含匹配）
    - severity: low / medium / high / critical
    - attacker: 攻击组织/泄露源名称（包含匹配）
    - keyword: 在标题、受害者、摘要、CVE 等字段上做包含匹配
    - min_risk_score: 风险分阈值（0-100）
    - limit: 返回事件上限，默认 100，最大 500

    响应显式声明 charset=utf-8，避免 PowerShell / .NET 客户端用本地代码页解码导致中文乱码。
    """
    client_host = request.client.host if request.client else ""
    if client_host != "127.0.0.1":
        raise HTTPException(status_code=403, detail="仅允许 127.0.0.1 本地访问")
    payload = _reload_api_modules().build_ai_intelligence_payload(
        event_type=event_type,
        days=days,
        industry=industry,
        region=region,
        country=country,
        severity=severity,
        attacker=attacker,
        keyword=keyword,
        min_risk_score=min_risk_score,
        limit=limit,
    )
    return AsciiSafeJSONResponse(content=payload)


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


class SessionCookieRequest(BaseModel):
    cookie: str


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


class RemoteBrowserActionRequest(BaseModel):
    action: str
    x: float | None = None
    y: float | None = None
    text: str = ""
    key: str = ""
    url: str = ""
    ms: int | None = None
    username: str = ""
    password: str = ""
    otp: str = ""


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



class GitHubAppConfigRequest(BaseModel):
    app_id: int = Field(..., gt=0)
    installation_id: int = Field(..., gt=0)
    private_key: SecretStr = Field(default_factory=lambda: SecretStr(""), max_length=65536)


class MonitoringKeywordRow(BaseModel):
    keyword: str
    category: str
    weight: int
    enabled: bool = True
    match_mode: str = "contains"


class MonitoringKeywordsRequest(BaseModel):
    keywords: list[MonitoringKeywordRow]


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


@app.get("/api/sites/cookies")
def list_site_cookies() -> dict:
    """Return cookie status for every site that requires a session cookie.

    Frontend uses this to render a per-site cookie panel without hardcoding
    which sites need a cookie — drop a `session_cookie_*` block into
    sites.yaml and the dashboard picks the site up automatically.
    """
    return {"sites": list_cookie_capable_sites()}


@app.get("/api/sites/{site_name}/cookie")
def get_site_cookie(site_name: str) -> dict:
    try:
        return get_session_cookie_status(site_name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/sites/{site_name}/cookie")
def save_site_cookie(site_name: str, payload: SessionCookieRequest) -> dict:
    try:
        return set_session_cookie(site_name=site_name, cookie_value=payload.cookie)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/sites/{site_name}/cookie")
def delete_site_cookie(site_name: str) -> dict:
    try:
        return clear_session_cookie(site_name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/monitoring/keywords")
def monitoring_keywords() -> list[dict]:
    _reload_api_modules()
    return monitoring_rules_module.get_monitoring_keywords(persist_defaults=False)


@app.post("/api/monitoring/keywords")
def update_monitoring_keywords(payload: MonitoringKeywordsRequest) -> list[dict]:
    _reload_api_modules()
    return monitoring_rules_module.save_monitoring_keywords([item.model_dump() for item in payload.keywords])


@app.get("/api/analysis/monitoring-status")
def monitoring_status() -> dict:
    _reload_api_modules()
    return monitoring_rules_module.build_monitoring_status(persist_default_keywords=False)


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


@app.post("/api/platform-sessions/{platform}/remote-login/start")
def platform_session_remote_login_start(platform: str, request: Request) -> dict:
    _require_module(request, "file_monitoring")
    try:
        return start_remote_browser_login(platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/platform-sessions/remote-login/{session_id}")
def platform_session_remote_login_state(session_id: str, request: Request) -> dict:
    _require_module(request, "file_monitoring")
    try:
        return get_remote_browser_state(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.websocket("/api/platform-sessions/remote-login/{session_id}/rfb")
async def platform_session_remote_login_rfb(websocket: WebSocket, session_id: str) -> None:
    ticket = str(websocket.query_params.get("ticket") or "")
    if not validate_remote_browser_ticket(session_id, ticket):
        await websocket.close(code=1008)
        return
    await proxy_remote_browser_rfb(session_id, websocket)


@app.websocket("/api/platform-sessions/remote-login/{session_id}/stream")
async def platform_session_remote_login_stream(websocket: WebSocket, session_id: str) -> None:
    ticket = str(websocket.query_params.get("ticket") or "")
    if not validate_remote_browser_ticket(session_id, ticket):
        await websocket.close(code=1008)
        return
    await proxy_remote_browser_stream(session_id, websocket)


@app.post("/api/platform-sessions/remote-login/{session_id}/control")
def platform_session_remote_login_control(
    session_id: str,
    payload: RemoteBrowserActionRequest,
    request: Request,
) -> dict:
    _require_module(request, "file_monitoring")
    try:
        return control_remote_browser(
            session_id,
            payload.action,
            {
                "x": payload.x,
                "y": payload.y,
                "text": payload.text,
                "key": payload.key,
                "url": payload.url,
                "ms": payload.ms,
                "username": payload.username,
                "password": payload.password,
                "otp": payload.otp,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/platform-sessions/remote-login/{session_id}/finish")
def platform_session_remote_login_finish(
    session_id: str,
    payload: PlatformSessionSaveRequest,
    request: Request,
) -> dict:
    _require_module(request, "file_monitoring")
    try:
        return finish_remote_browser_login(session_id, account_label=payload.account_label)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/platform-sessions/remote-login/{session_id}")
def platform_session_remote_login_close(session_id: str, request: Request) -> dict:
    _require_module(request, "file_monitoring")
    try:
        return close_remote_browser_login(session_id)
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


@app.delete("/api/exposure-watchlists/{watchlist_id}")
def delete_exposure_watchlist_route(watchlist_id: int, request: Request) -> dict:
    _require_module(request, "file_monitoring")
    try:
        return delete_watchlist_payload(watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/platform-sessions/{platform}/adaptive-login/start")
def platform_session_adaptive_login_start(platform: str, request: Request) -> dict:
    _require_module(request, "file_monitoring")
    fallback_reason = "interactive desktop browser is unavailable"
    if visible_platform_login_available():
        try:
            return launch_platform_login(platform)
        except Exception as exc:
            fallback_reason = str(exc) or "visible browser startup failed"
    try:
        payload = start_remote_browser_login(platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        **payload,
        "mode": "embedded_browser",
        "fallback_reason": fallback_reason,
    }


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
def netdisk_source_health(source_family: str | None = None) -> list[dict]:
    return list_netdisk_source_health_payload(source_family=source_family)


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


@app.get("/api/bot/status")
def bot_status(request: Request) -> dict:
    _require_module(request, "file_monitoring")
    return bot_config_status()


@app.post("/api/bot/config")
def save_bot_config(payload: BotConfigRequest, request: Request) -> dict:
    _require_admin(request)
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
def send_bot(payload: BotSendRequest, request: Request) -> dict:
    _require_admin(request)
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


@app.get("/api/code-monitoring/summary")
def code_monitoring_summary() -> dict:
    return build_code_monitoring_summary()


@app.get("/api/code-monitoring/github-app")
def get_code_monitoring_github_app(request: Request) -> dict:
    _require_module(request, "file_monitoring")
    return github_app_config_status()


@app.put("/api/code-monitoring/github-app")
def configure_code_monitoring_github_app(
    payload: GitHubAppConfigRequest,
    request: Request,
) -> dict:
    _require_admin(request)
    try:
        return save_github_app_config(
            app_id=payload.app_id,
            installation_id=payload.installation_id,
            private_key=payload.private_key.get_secret_value(),
        )
    except GitHubAppConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GitHubAppConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/code-monitoring/github-app")
def remove_code_monitoring_github_app(request: Request) -> dict:
    _require_admin(request)
    try:
        return delete_github_app_config()
    except GitHubAppConfigError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@app.get("/api/agent/code-leaks")
def agent_code_leaks(
    watchlist_id: int | None = None,
    review_status: str | None = None,
    platform: str | None = None,
    sensitive_type: str | None = None,
    include_suppressed: bool = True,
    limit: int = 50,
) -> dict:
    effective_limit = max(1, min(int(limit), 200))
    hits = list_code_hits_payload(
        watchlist_id=watchlist_id,
        review_status=review_status,
        platform=platform,
        sensitive_type=sensitive_type,
        include_suppressed=include_suppressed,
        limit=effective_limit,
    )
    hits = hits[:effective_limit]
    items = []
    for hit in hits:
        detail = build_agent_code_hit_detail(int(hit["id"]))
        if detail is not None:
            items.append(detail)
    return {"count": len(items), "items": items}


@app.get("/api/agent/code-leaks/{hit_id}")
def agent_code_leak_detail(hit_id: int) -> dict:
    payload = build_agent_code_hit_detail(hit_id)
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




class TranslateTitlesRequest(BaseModel):
    titles: list[str]


@app.post("/api/translate/titles")
def translate_titles(payload: TranslateTitlesRequest) -> dict:
    """独立的标题翻译API，异步翻译标题列表，不阻塞主数据加载。"""
    from darkweb_collector.detail_i18n import translate_event_title_live

    results: dict[str, str] = {}
    for title in payload.titles[:50]:  # 限制每次最多翻译50个
        try:
            translated = translate_event_title_live(title, fallback=title)
            results[title] = translated
        except Exception:
            results[title] = title
    return {"translations": results}
