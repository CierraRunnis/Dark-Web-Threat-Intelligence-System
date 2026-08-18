from __future__ import annotations

from datetime import datetime, timedelta, timezone
import http.client
import json
import logging
import os
import socket
import ssl
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from darkweb_collector.db import (
    get_db_connection,
    get_ransomware_live_sync_state,
    mark_normalized_intelligence_dirty,
    upsert_ransomware_live_victim,
)
from darkweb_collector.runtime import default_db_path


RANSOMWARE_LIVE_API_URL = "https://api-pro.ransomware.live/victims/recent?order=discovered"
RANSOMWARE_LIVE_API_KEY_ENV = "RANSOMWARE_LIVE_API_KEY"
RANSOMWARE_LIVE_SETTINGS_PATH_ENV = "DARKWEB_RANSOMWARE_LIVE_SETTINGS_PATH"
RANSOMWARE_LIVE_SETTINGS_FILE = "ransomware_live_settings.json"
RANSOMWARE_LIVE_SYNC_TTL_SECONDS = 3600
RANSOMWARE_LIVE_DEFAULT_LIMIT = 0
RANSOMWARE_LIVE_PROXY_PORTS_ENV = "RANSOMWARE_LIVE_PROXY_PORTS"
RANSOMWARE_LIVE_PROXY_FAILURE_THRESHOLD_ENV = "RANSOMWARE_LIVE_PROXY_FAILURE_THRESHOLD"
RANSOMWARE_LIVE_DEFAULT_PROXY_PORTS = (7890, 10808)
RANSOMWARE_LIVE_DEFAULT_PROXY_FAILURE_THRESHOLD = 3
RANSOMWARE_LIVE_PROXY_PROBE_TIMEOUT_SECONDS = 15
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "bishe-threat-intel/1.0",
}

logger = logging.getLogger("darkweb_collector.ransomware_live")
_sync_lock = Lock()
_sync_thread: Thread | None = None
_proxy_state_lock = Lock()
_selected_proxy_port: int | None = None
_selected_proxy_failure_count = 0


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


def _apply_record_limit(victims: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return victims
    try:
        normalized = int(limit)
    except (TypeError, ValueError):
        return victims
    if normalized <= 0:
        return victims
    return victims[:normalized]


def _build_ssl_context() -> ssl.SSLContext:
    # Python's default multi-version ClientHello (TLS 1.2+1.3) is silently dropped
    # on the IPv4 path to api-pro.ransomware.live; pinning to TLS 1.3 shrinks the
    # ClientHello past whatever middlebox/fingerprint is filtering it.
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx


class _IPv6FirstHTTPSConnection(http.client.HTTPSConnection):
    # IPv6 first, fall back to IPv4; the IPv4 path can stall during TLS handshakes.
    def connect(self) -> None:
        last_err: Exception | None = None
        for family in (socket.AF_INET6, socket.AF_INET):
            try:
                infos = socket.getaddrinfo(self.host, self.port, family, socket.SOCK_STREAM)
            except OSError as exc:
                last_err = exc
                continue
            for _, _, _, _, sockaddr in infos:
                raw_sock = None
                try:
                    raw_sock = socket.create_connection(sockaddr[:2], self.timeout, self.source_address)
                    self.sock = raw_sock
                    if self._tunnel_host:
                        self._tunnel()
                    self.sock = self._context.wrap_socket(
                        self.sock, server_hostname=self._tunnel_host or self.host
                    )
                except (OSError, TimeoutError) as exc:
                    last_err = exc
                    if raw_sock is not None:
                        raw_sock.close()
                    self.sock = None
                    continue
                return
        raise last_err if last_err else OSError(f"cannot connect to {self.host}")


class _IPv6FirstHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv6FirstHTTPSConnection, req, context=self._context)


def _proxy_host() -> str:
    return str(os.environ.get("PROXY_HOST") or "127.0.0.1").strip()


def _proxy_ports() -> tuple[int, ...]:
    raw_ports = str(os.environ.get(RANSOMWARE_LIVE_PROXY_PORTS_ENV) or "").strip()
    values = raw_ports.split(",") if raw_ports else RANSOMWARE_LIVE_DEFAULT_PROXY_PORTS
    ports: list[int] = []
    for value in values:
        try:
            port = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if 0 < port <= 65535 and port not in ports:
            ports.append(port)
    return tuple(ports) or RANSOMWARE_LIVE_DEFAULT_PROXY_PORTS


def _proxy_failure_threshold() -> int:
    try:
        return max(
            1,
            int(
                os.environ.get(RANSOMWARE_LIVE_PROXY_FAILURE_THRESHOLD_ENV)
                or RANSOMWARE_LIVE_DEFAULT_PROXY_FAILURE_THRESHOLD
            ),
        )
    except ValueError:
        return RANSOMWARE_LIVE_DEFAULT_PROXY_FAILURE_THRESHOLD


def _proxy_state() -> tuple[int | None, int]:
    with _proxy_state_lock:
        return _selected_proxy_port, _selected_proxy_failure_count


def _mark_proxy_success(port: int) -> None:
    global _selected_proxy_port, _selected_proxy_failure_count
    with _proxy_state_lock:
        previous_port = _selected_proxy_port
        _selected_proxy_port = port
        _selected_proxy_failure_count = 0
    if previous_port != port:
        logger.info("ransomware.live selected HTTP proxy %s:%s", _proxy_host(), port)


def _mark_proxy_failure(port: int) -> int:
    global _selected_proxy_failure_count
    with _proxy_state_lock:
        if _selected_proxy_port != port:
            return 0
        _selected_proxy_failure_count += 1
        return _selected_proxy_failure_count


def _reset_proxy_failures(port: int) -> None:
    global _selected_proxy_failure_count
    with _proxy_state_lock:
        if _selected_proxy_port == port:
            _selected_proxy_failure_count = 0


def _request_json_via_proxy(request: Request, *, timeout: int, proxy_port: int) -> dict[str, Any]:
    proxy_url = f"http://{_proxy_host()}:{proxy_port}"
    opener = build_opener(
        ProxyHandler({"http": proxy_url, "https": proxy_url}),
        _IPv6FirstHTTPSHandler(context=_build_ssl_context()),
    )
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def _probe_proxy_ports(
    request: Request,
    *,
    timeout: int,
    failed_port: int | None = None,
) -> dict[str, Any]:
    ports = list(_proxy_ports())
    if failed_port in ports:
        ports = [port for port in ports if port != failed_port] + [failed_port]
    last_error: Exception | None = None
    probe_timeout = min(timeout, RANSOMWARE_LIVE_PROXY_PROBE_TIMEOUT_SECONDS)
    for port in ports:
        try:
            payload = _request_json_via_proxy(request, timeout=probe_timeout, proxy_port=port)
        except HTTPError:
            _mark_proxy_success(port)
            raise
        except (URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            last_error = exc
            logger.warning("ransomware.live proxy %s:%s unavailable: %s", _proxy_host(), port, exc)
            continue
        except Exception:
            _mark_proxy_success(port)
            raise
        _mark_proxy_success(port)
        return payload
    if last_error is not None:
        raise last_error
    raise RuntimeError("no ransomware.live proxy ports are configured")


def _fetch_json(url: str, *, timeout: int = 120) -> dict[str, Any]:
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
    selected_port, _ = _proxy_state()
    if selected_port is None:
        return _probe_proxy_ports(request, timeout=timeout)
    try:
        payload = _request_json_via_proxy(request, timeout=timeout, proxy_port=selected_port)
    except HTTPError:
        _mark_proxy_success(selected_port)
        raise
    except (URLError, TimeoutError, OSError, ssl.SSLError):
        failure_count = _mark_proxy_failure(selected_port)
        if failure_count < _proxy_failure_threshold():
            raise
        logger.warning(
            "ransomware.live proxy %s:%s failed %s consecutive times; checking alternatives",
            _proxy_host(),
            selected_port,
            failure_count,
        )
        try:
            return _probe_proxy_ports(request, timeout=timeout, failed_port=selected_port)
        except (URLError, TimeoutError, OSError, ssl.SSLError):
            _reset_proxy_failures(selected_port)
            raise
    except Exception:
        _mark_proxy_success(selected_port)
        raise
    _mark_proxy_success(selected_port)
    return payload


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
    limited = _apply_record_limit(victims, limit)
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
        if records:
            mark_normalized_intelligence_dirty(connection)
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
