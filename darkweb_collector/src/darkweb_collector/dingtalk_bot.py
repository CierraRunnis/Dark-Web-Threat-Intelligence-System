from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from threading import RLock
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from darkweb_collector.runtime import default_db_path


DINGTALK_SETTINGS_PATH_ENV = "DARKWEB_DINGTALK_SETTINGS_PATH"
DINGTALK_WEBHOOK_ENV = "DINGTALK_BOT_WEBHOOK"
DINGTALK_SECRET_ENV = "DINGTALK_BOT_SECRET"
DINGTALK_SETTINGS_FILE = "dingtalk_bot_settings.json"
DINGTALK_WEBHOOK_BASE_URL = "https://oapi.dingtalk.com/robot/send"
DINGTALK_WEBHOOK_HOST = "oapi.dingtalk.com"


_SETTINGS_LOCK = RLock()


class DingTalkBotError(RuntimeError):
    """Raised when a DingTalk robot message cannot be built or delivered."""


@dataclass(frozen=True)
class DingTalkConfig:
    webhook_url: str = ""
    secret: str = ""
    timeout_seconds: float = 10.0
    dry_run: bool = False
    source: str = "none"
    settings_path: str = ""
    updated_at: str = ""


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _settings_path(settings_path: str | Path | None = None) -> Path:
    if settings_path:
        return Path(settings_path).expanduser().resolve()
    configured = _normalize_text(os.environ.get(DINGTALK_SETTINGS_PATH_ENV))
    if configured:
        return Path(configured).expanduser().resolve()
    return default_db_path().with_name(DINGTALK_SETTINGS_FILE).resolve()


def _load_settings(settings_path: str | Path | None = None) -> dict[str, Any]:
    path = _settings_path(settings_path)
    if not path.exists():
        return {}
    try:
        with _SETTINGS_LOCK:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_settings(payload: dict[str, Any], settings_path: str | Path | None = None) -> None:
    path = _settings_path(settings_path)
    with _SETTINGS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_webhook(value: str) -> str:
    raw = _normalize_text(value)
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"{DINGTALK_WEBHOOK_BASE_URL}?access_token={quote_plus(raw)}"
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https" or parsed.hostname != DINGTALK_WEBHOOK_HOST:
        raise DingTalkBotError("DingTalk webhook must use https://oapi.dingtalk.com")
    if parsed.path.rstrip("/") != "/robot/send":
        raise DingTalkBotError("DingTalk webhook path must be /robot/send")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if not _normalize_text(query.get("access_token")):
        raise DingTalkBotError("DingTalk webhook access_token is required")
    return raw


def _mask_secret(value: str) -> str:
    raw = _normalize_text(value)
    if not raw:
        return ""
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}{'*' * max(4, len(raw) - 8)}{raw[-4:]}"


def _mask_webhook_url(webhook_url: str) -> str:
    parsed = urlparse(_normalize_text(webhook_url))
    if not parsed.netloc:
        return ""
    query = parse_qsl(parsed.query, keep_blank_values=True)
    masked_query = [
        (key, _mask_secret(value) if key == "access_token" else value)
        for key, value in query
    ]
    return urlunparse(parsed._replace(query=urlencode(masked_query)))


def load_dingtalk_config(
    *,
    webhook_url: str | None = None,
    secret: str | None = None,
    timeout_seconds: float | None = None,
    dry_run: bool | None = None,
    settings_path: str | Path | None = None,
) -> DingTalkConfig:
    settings = _load_settings(settings_path)
    allow_environment = settings_path is None
    saved_webhook = _normalize_text(settings.get("webhook_url"))
    saved_secret = _normalize_text(settings.get("secret"))
    env_webhook = _normalize_text(os.environ.get(DINGTALK_WEBHOOK_ENV)) if allow_environment else ""
    env_secret = _normalize_text(os.environ.get(DINGTALK_SECRET_ENV)) if allow_environment else ""
    explicit_webhook = _normalize_text(webhook_url)

    resolved_webhook = explicit_webhook or saved_webhook or env_webhook
    if resolved_webhook:
        resolved_webhook = _normalize_webhook(resolved_webhook)
    resolved_secret = _normalize_text(secret) if secret is not None else (saved_secret or env_secret)
    if explicit_webhook or secret is not None:
        source = "request"
        updated_at = ""
    elif saved_webhook:
        source = "saved_file"
        updated_at = _normalize_text(settings.get("updated_at"))
    elif env_webhook:
        source = "environment"
        updated_at = ""
    else:
        source = "none"
        updated_at = ""

    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = float(os.environ.get("BOT_TIMEOUT_SECONDS", "10"))
    resolved_dry_run = dry_run
    if resolved_dry_run is None:
        resolved_dry_run = os.environ.get("BOT_DRY_RUN", "0") == "1"
    return DingTalkConfig(
        webhook_url=resolved_webhook,
        secret=resolved_secret,
        timeout_seconds=float(resolved_timeout),
        dry_run=bool(resolved_dry_run),
        source=source,
        settings_path=str(_settings_path(settings_path)),
        updated_at=updated_at,
    )


def set_dingtalk_config(
    *,
    webhook_url: str,
    secret: str = "",
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_webhook = _normalize_webhook(webhook_url)
    if not normalized_webhook:
        raise DingTalkBotError("DingTalk webhook is required")
    _save_settings(
        {
            "webhook_url": normalized_webhook,
            "secret": _normalize_text(secret),
            "updated_at": _now_utc_iso(),
        },
        settings_path,
    )
    return dingtalk_config_status(load_dingtalk_config(settings_path=settings_path))


def delete_dingtalk_config(settings_path: str | Path | None = None) -> dict[str, Any]:
    path = _settings_path(settings_path)
    with _SETTINGS_LOCK:
        deleted = path.is_file()
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise DingTalkBotError(f"Unable to delete DingTalk settings: {exc}") from exc
    return {
        **dingtalk_config_status(load_dingtalk_config(settings_path=settings_path)),
        "saved_config_deleted": deleted,
    }


def dingtalk_config_status(config: DingTalkConfig | None = None) -> dict[str, Any]:
    resolved = config or load_dingtalk_config()
    parsed = urlparse(resolved.webhook_url)
    return {
        "provider": "dingtalk_webhook",
        "configured": bool(resolved.webhook_url),
        "source": resolved.source,
        "has_secret": bool(resolved.secret),
        "dry_run": resolved.dry_run,
        "masked_webhook_url": _mask_webhook_url(resolved.webhook_url),
        "webhook_host": parsed.netloc if resolved.webhook_url else "",
        "settings_path": resolved.settings_path,
        "updated_at": resolved.updated_at,
    }


def build_dingtalk_markdown_payload(content: str, *, title: str = "暗网威胁情报通知") -> dict[str, Any]:
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": _normalize_text(title) or "暗网威胁情报通知",
            "text": str(content or ""),
        },
    }


def _signed_webhook_url(config: DingTalkConfig, *, timestamp_ms: int | None = None) -> str:
    if not config.secret:
        return config.webhook_url
    timestamp = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
    message = f"{timestamp}\n{config.secret}".encode("utf-8")
    signature = base64.b64encode(
        hmac.new(config.secret.encode("utf-8"), message, digestmod=hashlib.sha256).digest()
    ).decode("ascii")
    parsed = urlparse(config.webhook_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"timestamp": str(timestamp), "sign": signature})
    return urlunparse(parsed._replace(query=urlencode(query)))


def post_dingtalk_markdown(
    content: str,
    config: DingTalkConfig | None = None,
    *,
    title: str = "暗网威胁情报通知",
) -> dict[str, Any]:
    resolved = config or load_dingtalk_config()
    payload = build_dingtalk_markdown_payload(content, title=title)
    if resolved.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "payload": payload,
            **dingtalk_config_status(resolved),
        }
    if not resolved.webhook_url:
        raise DingTalkBotError("DingTalk webhook is not configured")
    request = Request(
        _signed_webhook_url(resolved),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=resolved.timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(response.status)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DingTalkBotError(f"DingTalk webhook returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise DingTalkBotError(f"DingTalk webhook request failed: {exc}") from exc
    try:
        response_payload: Any = json.loads(body) if body else {}
    except json.JSONDecodeError:
        response_payload = body
    ok = 200 <= status_code < 300
    if isinstance(response_payload, dict) and "errcode" in response_payload:
        ok = ok and int(response_payload.get("errcode") or 0) == 0
    result = {
        "ok": ok,
        "dry_run": False,
        "status_code": status_code,
        "response": response_payload,
        **dingtalk_config_status(resolved),
    }
    if not ok:
        raise DingTalkBotError(f"DingTalk webhook rejected message: {result}")
    return result
