from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib.request import Request, urlopen

from darkweb_collector.db import (
    get_db_connection,
    get_ransomware_live_sync_state,
    upsert_ransomware_live_victim,
)
from darkweb_collector.runtime import default_db_path


RANSOMWARE_LIVE_API_URL = "https://api-pro.ransomware.live/victims/recent?order=discovered"
RANSOMWARE_LIVE_API_KEY_ENV = "RANSOMWARE_LIVE_API_KEY"
RANSOMWARE_LIVE_SETTINGS_PATH_ENV = "DARKWEB_RANSOMWARE_LIVE_SETTINGS_PATH"
RANSOMWARE_LIVE_SETTINGS_FILE = "ransomware_live_settings.json"
RANSOMWARE_LIVE_SYNC_TTL_SECONDS = 3600
RANSOMWARE_LIVE_DEFAULT_LIMIT = 100
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "bishe-threat-intel/1.0",
}

logger = logging.getLogger("darkweb_collector.ransomware_live")
_sync_lock = Lock()
_sync_thread: Thread | None = None


def _settings_path() -> Path:
    raw_path = str(os.environ.get(RANSOMWARE_LIVE_SETTINGS_PATH_ENV) or "").strip()
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return default_db_path().with_name(RANSOMWARE_LIVE_SETTINGS_FILE).resolve()


def _load_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_settings(payload: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _mask_api_key(value: str) -> str:
    key = _normalize_text(value)
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * max(4, len(key) - 8)}{key[-4:]}"


def get_ransomware_live_api_key() -> str:
    env_value = str(os.environ.get(RANSOMWARE_LIVE_API_KEY_ENV) or "").strip()
    if env_value:
        return env_value
    return _normalize_text(_load_settings().get("api_key"))


def has_ransomware_live_api_key() -> bool:
    return bool(get_ransomware_live_api_key())


def set_ransomware_live_api_key(api_key: str) -> dict[str, Any]:
    normalized = _normalize_text(api_key)
    if not normalized:
        raise RuntimeError("api_key must not be empty")
    _save_settings(
        {
            "api_key": normalized,
            "updated_at": _now_utc_iso(),
        }
    )
    os.environ[RANSOMWARE_LIVE_API_KEY_ENV] = normalized
    return get_ransomware_live_config_status()


def get_ransomware_live_config_status() -> dict[str, Any]:
    env_value = str(os.environ.get(RANSOMWARE_LIVE_API_KEY_ENV) or "").strip()
    settings = _load_settings()
    saved_value = _normalize_text(settings.get("api_key"))
    effective = env_value or saved_value
    source = "environment" if env_value else "saved_file" if saved_value else "none"
    return {
        "has_api_key": bool(effective),
        "masked_api_key": _mask_api_key(effective),
        "source": source,
        "env_var": RANSOMWARE_LIVE_API_KEY_ENV,
        "settings_path": str(_settings_path()),
        "updated_at": _normalize_text(settings.get("updated_at")),
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_utc_iso() -> str:
    return _now_utc().isoformat()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_datetime(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _fetch_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    api_key = get_ransomware_live_api_key()
    if not api_key:
        raise RuntimeError(f"{RANSOMWARE_LIVE_API_KEY_ENV} is not set")
    request = Request(
        url,
        headers={
            **HTTP_HEADERS,
            "X-API-KEY": api_key,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _load_sample_payload(sample_file: str | Path) -> dict[str, Any]:
    path = Path(sample_file).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return {"victims": payload.get("records") or [], "count": len(payload.get("records") or [])}
    if isinstance(payload, list):
        return {"victims": payload, "count": len(payload)}
    return payload if isinstance(payload, dict) else {"victims": [], "count": 0}


def normalize_ransomware_live_victim(record: dict[str, Any], *, last_seen_at: str | None = None) -> dict[str, Any]:
    raw_json = dict(record)
    discovered_at = _normalize_datetime(record.get("discovered"))
    attacked_at = _normalize_datetime(record.get("attackdate"))
    effective_last_seen_at = _normalize_datetime(last_seen_at) or _now_utc_iso()
    return {
        "victim_id": _normalize_text(record.get("id")),
        "group_name": _normalize_text(record.get("group")),
        "victim_name": _normalize_text(record.get("victim")),
        "website": _normalize_text(record.get("website")),
        "country_code": _normalize_text(record.get("country")).upper(),
        "activity": _normalize_text(record.get("activity")),
        "discovered_at": discovered_at,
        "attacked_at": attacked_at or discovered_at,
        "post_url": _normalize_text(record.get("post_url")),
        "permalink": _normalize_text(record.get("permalink")),
        "screenshot_url": _normalize_text(record.get("screenshot")),
        "description": _normalize_text(record.get("description")),
        "press_url": _normalize_text(record.get("press")),
        "raw_json": raw_json,
        "last_seen_at": effective_last_seen_at,
    }


def fetch_recent_ransomware_live_victims(
    *,
    limit: int = RANSOMWARE_LIVE_DEFAULT_LIMIT,
    sample_file: str | Path | None = None,
    prefer_live: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if sample_file is not None:
        payload = _load_sample_payload(sample_file)
    elif prefer_live:
        payload = _fetch_json(RANSOMWARE_LIVE_API_URL)
    else:
        payload = {"victims": [], "count": 0}
    victims = payload.get("victims") or []
    if not isinstance(victims, list):
        victims = []
    limited = victims[: max(1, int(limit))]
    observed_at = _now_utc_iso()
    records = [
        normalize_ransomware_live_victim(item, last_seen_at=observed_at)
        for item in limited
        if isinstance(item, dict) and _normalize_text(item.get("id"))
    ]
    return records, payload


def should_refresh_ransomware_live(connection, *, ttl_seconds: int = RANSOMWARE_LIVE_SYNC_TTL_SECONDS) -> bool:
    state = get_ransomware_live_sync_state(connection)
    if int(state.get("count") or 0) <= 0:
        return True
    latest_seen_at = _normalize_text(state.get("latest_seen_at"))
    if not latest_seen_at:
        return True
    try:
        latest_seen_dt = datetime.fromisoformat(latest_seen_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if latest_seen_dt.tzinfo is None:
        latest_seen_dt = latest_seen_dt.replace(tzinfo=timezone.utc)
    return latest_seen_dt < (_now_utc() - timedelta(seconds=max(1, int(ttl_seconds))))


def sync_ransomware_live_victims(
    *,
    limit: int = RANSOMWARE_LIVE_DEFAULT_LIMIT,
    sample_file: str | Path | None = None,
    prefer_live: bool = True,
    refresh_normalized: bool = True,
) -> dict[str, Any]:
    records, payload = fetch_recent_ransomware_live_victims(
        limit=limit,
        sample_file=sample_file,
        prefer_live=prefer_live,
    )
    with get_db_connection() as connection:
        for record in records:
            upsert_ransomware_live_victim(connection, record)
        if refresh_normalized:
            from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence

            ensure_normalized_intelligence(connection, force=True)
        connection.commit()
        sync_state = get_ransomware_live_sync_state(connection)
    return {
        "ingested": len(records),
        "count": int(sync_state.get("count") or 0),
        "latest_seen_at": _normalize_text(sync_state.get("latest_seen_at")),
        "latest_disclosure_time": _normalize_text(sync_state.get("latest_disclosure_time")),
        "source": RANSOMWARE_LIVE_API_URL,
        "payload_count": int(payload.get("count") or 0),
    }


def _background_sync_worker(limit: int) -> None:
    try:
        sync_ransomware_live_victims(limit=limit, refresh_normalized=True)
    except Exception:
        logger.exception("ransomware.live background sync failed")


def maybe_schedule_ransomware_live_sync(
    *,
    ttl_seconds: int = RANSOMWARE_LIVE_SYNC_TTL_SECONDS,
    limit: int = RANSOMWARE_LIVE_DEFAULT_LIMIT,
) -> bool:
    global _sync_thread
    if not has_ransomware_live_api_key():
        return False
    with get_db_connection() as connection:
        if not should_refresh_ransomware_live(connection, ttl_seconds=ttl_seconds):
            return False
    with _sync_lock:
        if _sync_thread is not None and _sync_thread.is_alive():
            return False
        _sync_thread = Thread(
            target=_background_sync_worker,
            args=(limit,),
            name="ransomware-live-sync",
            daemon=True,
        )
        _sync_thread.start()
    return True
