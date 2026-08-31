from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from darkweb_collector.bot_assistant import (
    BotConfig,
    bot_config_status,
    build_markdown_payload,
    delete_bot_config,
    ensure_wecom_aibot_listener,
    load_bot_config,
    post_bot_payload,
    set_bot_config,
)
from darkweb_collector.db import get_code_watchlist, get_db_connection, list_code_watchlists
from darkweb_collector.dingtalk_bot import (
    DingTalkConfig,
    delete_dingtalk_config,
    dingtalk_config_status,
    load_dingtalk_config,
    post_dingtalk_markdown,
    set_dingtalk_config,
)
from darkweb_collector.runtime import default_db_path


PROFILE_FILE = "profile.json"
WECOM_FILE = "wecom.json"
DINGTALK_FILE = "dingtalk.json"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return default_db_path().with_name("watchlist-notifications").resolve()


def _watchlist_dir(watchlist_id: int) -> Path:
    return _root() / str(int(watchlist_id))


def _paths(watchlist_id: int) -> tuple[Path, Path, Path]:
    root = _watchlist_dir(watchlist_id)
    return root / PROFILE_FILE, root / WECOM_FILE, root / DINGTALK_FILE


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _require_watchlist(watchlist_id: int) -> dict[str, Any]:
    with get_db_connection() as connection:
        watchlist = get_code_watchlist(connection, int(watchlist_id))
    if watchlist is None:
        raise ValueError(f"watchlist not found: {watchlist_id}")
    return watchlist


def _normalize_keywords(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows or []:
        keyword = " ".join(str(row.get("keyword") or "").split()).strip()
        category = " ".join(str(row.get("category") or "custom_keywords").split()).strip() or "custom_keywords"
        key = (keyword.casefold(), category.casefold())
        if not keyword or key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "keyword": keyword,
                "category": category,
                "weight": int(row.get("weight") or 0),
                "enabled": bool(row.get("enabled", True)),
                "match_mode": str(row.get("match_mode") or "contains").strip() or "contains",
            }
        )
    return normalized


def _load_profile(watchlist_id: int) -> dict[str, Any]:
    profile_path, _, _ = _paths(watchlist_id)
    payload = _read_json(profile_path)
    return {
        "keywords": _normalize_keywords(payload.get("keywords") if isinstance(payload.get("keywords"), list) else []),
        "wechat_enabled": bool(payload.get("wechat_enabled", False)),
        "dingtalk_enabled": bool(payload.get("dingtalk_enabled", False)),
        "updated_at": str(payload.get("updated_at") or ""),
    }


def save_watchlist_notification_profile(
    watchlist_id: int,
    *,
    keywords: list[dict[str, Any]] | None = None,
    wechat_enabled: bool | None = None,
    dingtalk_enabled: bool | None = None,
) -> dict[str, Any]:
    _require_watchlist(watchlist_id)
    profile = _load_profile(watchlist_id)
    if keywords is not None:
        profile["keywords"] = _normalize_keywords(keywords)
    if wechat_enabled is not None:
        if wechat_enabled:
            _, wecom_path, _ = _paths(watchlist_id)
            if not bot_config_status(load_bot_config(settings_path=wecom_path)).get("configured"):
                raise ValueError("当前监测对象尚未配置企业微信")
        profile["wechat_enabled"] = bool(wechat_enabled)
    if dingtalk_enabled is not None:
        if dingtalk_enabled:
            _, _, dingtalk_path = _paths(watchlist_id)
            if not dingtalk_config_status(load_dingtalk_config(settings_path=dingtalk_path)).get("configured"):
                raise ValueError("当前监测对象尚未配置钉钉")
        profile["dingtalk_enabled"] = bool(dingtalk_enabled)
    profile["updated_at"] = _now_utc_iso()
    profile_path, _, _ = _paths(watchlist_id)
    _write_json(profile_path, profile)
    return get_watchlist_notification_profile(watchlist_id)


def get_watchlist_notification_profile(watchlist_id: int) -> dict[str, Any]:
    watchlist = _require_watchlist(watchlist_id)
    profile = _load_profile(watchlist_id)
    _, wecom_path, dingtalk_path = _paths(watchlist_id)
    wechat = bot_config_status(load_bot_config(settings_path=wecom_path))
    dingtalk = dingtalk_config_status(load_dingtalk_config(settings_path=dingtalk_path))
    return {
        "watchlist_id": int(watchlist_id),
        "watchlist_name": str(watchlist.get("name") or ""),
        "organization_name": str(watchlist.get("organization_name") or ""),
        **profile,
        "wechat": {**wechat, "enabled": profile["wechat_enabled"]},
        "dingtalk": {**dingtalk, "enabled": profile["dingtalk_enabled"]},
    }


def set_watchlist_wechat_config(
    watchlist_id: int,
    *,
    bot_id: str,
    secret: str,
    websocket_url: str = "",
) -> dict[str, Any]:
    _require_watchlist(watchlist_id)
    _, wecom_path, _ = _paths(watchlist_id)
    set_bot_config(
        bot_id=bot_id,
        secret=secret,
        websocket_url=websocket_url,
        settings_path=wecom_path,
    )
    return save_watchlist_notification_profile(watchlist_id, wechat_enabled=True)


def delete_watchlist_wechat_config(watchlist_id: int) -> dict[str, Any]:
    _require_watchlist(watchlist_id)
    _, wecom_path, _ = _paths(watchlist_id)
    delete_bot_config(settings_path=wecom_path)
    return save_watchlist_notification_profile(watchlist_id, wechat_enabled=False)


def set_watchlist_dingtalk_config(
    watchlist_id: int,
    *,
    webhook_url: str,
    secret: str = "",
) -> dict[str, Any]:
    _require_watchlist(watchlist_id)
    _, _, dingtalk_path = _paths(watchlist_id)
    set_dingtalk_config(webhook_url=webhook_url, secret=secret, settings_path=dingtalk_path)
    return save_watchlist_notification_profile(watchlist_id, dingtalk_enabled=True)


def delete_watchlist_dingtalk_config(watchlist_id: int) -> dict[str, Any]:
    _require_watchlist(watchlist_id)
    _, _, dingtalk_path = _paths(watchlist_id)
    delete_dingtalk_config(settings_path=dingtalk_path)
    return save_watchlist_notification_profile(watchlist_id, dingtalk_enabled=False)


def load_watchlist_channel_configs(
    watchlist_id: int,
) -> tuple[BotConfig | None, DingTalkConfig | None, dict[str, Any]]:
    profile = _load_profile(watchlist_id)
    _, wecom_path, dingtalk_path = _paths(watchlist_id)
    wechat = load_bot_config(settings_path=wecom_path) if profile["wechat_enabled"] else None
    dingtalk = load_dingtalk_config(settings_path=dingtalk_path) if profile["dingtalk_enabled"] else None
    return wechat, dingtalk, profile


def list_watchlist_notification_profiles() -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        watchlists = [item for item in list_code_watchlists(connection) if bool(item.get("enabled"))]
    profiles = []
    for watchlist in watchlists:
        watchlist_id = int(watchlist["id"])
        profile = _load_profile(watchlist_id)
        if not profile["keywords"] and not profile["wechat_enabled"] and not profile["dingtalk_enabled"]:
            continue
        profiles.append(
            {
                "watchlist_id": watchlist_id,
                "watchlist_name": str(watchlist.get("name") or ""),
                "organization_name": str(watchlist.get("organization_name") or ""),
                **profile,
            }
        )
    return profiles


def ensure_watchlist_wecom_listeners() -> None:
    for profile in list_watchlist_notification_profiles():
        if not profile["wechat_enabled"]:
            continue
        wechat, _, _ = load_watchlist_channel_configs(profile["watchlist_id"])
        if wechat is not None:
            ensure_wecom_aibot_listener(wechat)


def send_watchlist_test(
    watchlist_id: int,
    channel: str,
    content: str,
) -> dict[str, Any]:
    wechat, dingtalk, _ = load_watchlist_channel_configs(watchlist_id)
    if channel == "wechat_work":
        if wechat is None:
            raise ValueError("当前监测对象未启用企业微信")
        return post_bot_payload(build_markdown_payload(content), wechat)
    if channel == "dingtalk":
        if dingtalk is None:
            raise ValueError("当前监测对象未启用钉钉")
        return post_dingtalk_markdown(content, dingtalk, title="监测对象通知测试")
    raise ValueError(f"unsupported channel: {channel}")


def delete_watchlist_notification_files(watchlist_id: int) -> None:
    root = _watchlist_dir(watchlist_id)
    if not root.exists():
        return
    profile_path, wecom_path, dingtalk_path = _paths(watchlist_id)
    if wecom_path.exists():
        delete_bot_config(settings_path=wecom_path)
    if dingtalk_path.exists():
        delete_dingtalk_config(settings_path=dingtalk_path)
    profile_path.unlink(missing_ok=True)
    try:
        root.rmdir()
    except OSError:
        pass
