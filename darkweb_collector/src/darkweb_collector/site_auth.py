from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from darkweb_collector.db import get_db_connection, get_platform_session, upsert_platform_session
from darkweb_collector.document_exposure_platforms import get_exposure_platform
from darkweb_collector.document_exposure_sessions import resolve_platform_storage_state_path
from darkweb_collector.models import SiteConfig


READY_SESSION_STATUSES = {"configured", "valid"}


class SiteAuthenticationRequired(RuntimeError):
    def __init__(self, platform: str, message: str) -> None:
        super().__init__(message)
        self.platform = platform


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def site_display_name(config: SiteConfig) -> str:
    return str(config.extras.get("display_name") or config.site_name).strip()


def site_auth_platform(config: SiteConfig) -> str:
    return str(config.extras.get("auth_platform") or "").strip()


def _origin_for_url(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def load_local_storage_value(storage_state_path: Path, origin: str, name: str) -> str:
    try:
        payload = json.loads(storage_state_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    normalized_origin = _origin_for_url(origin).lower()
    for entry in payload.get("origins") or []:
        if not isinstance(entry, dict):
            continue
        entry_origin = _origin_for_url(str(entry.get("origin") or "")).lower()
        if normalized_origin and entry_origin != normalized_origin:
            continue
        for item in entry.get("localStorage") or []:
            if isinstance(item, dict) and str(item.get("name") or "") == name:
                return str(item.get("value") or "").strip()
    return ""


def site_auth_readiness(config: SiteConfig) -> dict[str, Any]:
    platform = site_auth_platform(config)
    if not platform:
        return {
            "ready": True,
            "auth_required": False,
            "auth_status": "not_required",
            "auth_platform": "",
            "auth_message": "",
            "storage_state_path": "",
            "token": "",
        }

    with get_db_connection() as connection:
        row = get_platform_session(connection, platform)
    storage_path = resolve_platform_storage_state_path(platform, row)
    status = str((row or {}).get("status") or "missing").strip() or "missing"
    storage_key = str(config.extras.get("auth_storage_key") or "token").strip()
    origin = str(config.extras.get("auth_origin") or _origin_for_url(config.seed_urls[0])).strip()
    token = load_local_storage_value(storage_path, origin, storage_key) if storage_path.exists() else ""

    if row is None or not storage_path.exists():
        auth_status = "missing"
        message = "尚未保存登录会话"
    elif status == "login_in_progress":
        auth_status = status
        message = "登录正在进行中"
    elif status not in READY_SESSION_STATUSES:
        auth_status = status
        message = str(row.get("last_error") or "登录会话不可用")
    elif not token or token.startswith("noLogin_"):
        auth_status = "login_required"
        message = "尚未完成账号登录"
    else:
        auth_status = "valid"
        message = "登录会话有效"

    ready = auth_status == "valid"
    return {
        "ready": ready,
        "auth_required": not ready,
        "auth_status": auth_status,
        "auth_platform": platform,
        "auth_message": message,
        "storage_state_path": str(storage_path),
        "token": token if ready else "",
    }


def require_site_auth_token(config: SiteConfig) -> tuple[str, str]:
    readiness = site_auth_readiness(config)
    if not readiness["ready"]:
        raise SiteAuthenticationRequired(
            str(readiness["auth_platform"]),
            str(readiness["auth_message"] or "需要先完成账号登录"),
        )
    return str(readiness["token"]), str(readiness["storage_state_path"])


def mark_site_auth_invalid(config: SiteConfig, message: str) -> None:
    platform_name = site_auth_platform(config)
    if not platform_name:
        return
    platform = get_exposure_platform(platform_name)
    with get_db_connection() as connection:
        existing = get_platform_session(connection, platform_name) or {}
        storage_path = resolve_platform_storage_state_path(platform_name, existing)
        upsert_platform_session(
            connection,
            {
                "platform": platform_name,
                "account_label": existing.get("account_label", ""),
                "login_url": existing.get("login_url") or platform.login_url,
                "homepage_url": existing.get("homepage_url") or platform.homepage_url,
                "requires_login": True,
                "status": "invalid",
                "storage_state_path": str(storage_path),
                "last_verified_at": _now_utc_iso(),
                "expires_hint": existing.get("expires_hint", ""),
                "last_error": message,
                "metadata_json": existing.get("metadata_json") or "{}",
                "updated_at": _now_utc_iso(),
            },
        )
        connection.commit()
