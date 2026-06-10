from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from threading import Event, Lock, RLock, Thread, current_thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen

from darkweb_collector.runtime import default_db_path


BOT_PROVIDER_WECHAT_WORK_AIBOT = "wechat_work_aibot"
BOT_PROVIDER_WECHAT_WORK_WEBHOOK = "wechat_work_webhook"
BOT_SETTINGS_PATH_ENV = "DARKWEB_BOT_SETTINGS_PATH"
BOT_SETTINGS_FILE = "bot_assistant_settings.json"
BOT_ID_ENV = "WECOM_BOT_ID"
BOT_SECRET_ENV = "WECOM_SECRET"
BOT_CHAT_ID_ENV = "WECOM_HOME_CHANNEL"
BOT_WEBSOCKET_URL_ENV = "WECOM_WEBSOCKET_URL"
BOT_WEBHOOK_URL_ENV = "BOT_WEBHOOK_URL"
BOT_WEBHOOK_SECRET_ENV = "BOT_WEBHOOK_SECRET"
WECHAT_WORK_BOT_WEBHOOK_ENV = "WECHAT_WORK_BOT_WEBHOOK"
WECHAT_WORK_BOT_SECRET_ENV = "WECHAT_WORK_BOT_SECRET"
WECHAT_BOT_WEBHOOK_ENV = "WECHAT_BOT_WEBHOOK"
WECHAT_WORK_WEBHOOK_BASE_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
WECHAT_WORK_AIBOT_WEBSOCKET_URL = "wss://openws.work.weixin.qq.com"
MAX_REGISTERED_TARGETS = 50
LISTENER_RESTART_BACKOFF_SECONDS = 15.0


logger = logging.getLogger("darkweb_collector.bot_assistant")
_SETTINGS_LOCK = RLock()


class BotAssistantError(RuntimeError):
    """Raised when a bot message cannot be built or delivered."""


@dataclass(frozen=True)
class BotConfig:
    provider: str = BOT_PROVIDER_WECHAT_WORK_AIBOT
    bot_id: str = ""
    chat_id: str = ""
    chat_ids: tuple[str, ...] = ()
    websocket_url: str = WECHAT_WORK_AIBOT_WEBSOCKET_URL
    webhook_url: str = ""
    webhook_key: str = ""
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


def _normalize_chat_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested_get(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current


def _find_first_value_for_keys(value: Any, keys: set[str]) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in keys:
                normalized = _normalize_text(item)
                if normalized:
                    return normalized
        for item in value.values():
            found = _find_first_value_for_keys(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_first_value_for_keys(item, keys)
            if found:
                return found
    return ""


def _settings_path() -> Path:
    raw_path = _normalize_text(os.environ.get(BOT_SETTINGS_PATH_ENV))
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return default_db_path().with_name(BOT_SETTINGS_FILE).resolve()


def _load_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        with _SETTINGS_LOCK:
            payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_settings(payload: dict[str, Any]) -> None:
    path = _settings_path()
    with _SETTINGS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_webhook_key(webhook_url: str) -> str:
    parsed = urlparse(webhook_url)
    query = parse_qs(parsed.query)
    values = query.get("key") or []
    return _normalize_text(values[0] if values else "")


def _normalize_wechat_work_webhook(value: str) -> tuple[str, str]:
    raw = _normalize_text(value)
    if not raw:
        return "", ""
    lowered = raw.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return raw, _extract_webhook_key(raw)
    return f"{WECHAT_WORK_WEBHOOK_BASE_URL}?key={quote_plus(raw)}", raw


def _mask_secret(value: str) -> str:
    raw = _normalize_text(value)
    if not raw:
        return ""
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:4]}{'*' * max(4, len(raw) - 8)}{raw[-4:]}"


def _mask_webhook_url(webhook_url: str, webhook_key: str) -> str:
    raw_url = _normalize_text(webhook_url)
    raw_key = _normalize_text(webhook_key)
    if not raw_url:
        return ""
    if raw_key:
        return raw_url.replace(raw_key, _mask_secret(raw_key))
    parsed = urlparse(raw_url)
    if parsed.query:
        return raw_url.replace(parsed.query, "***")
    return raw_url


def load_bot_config(
    *,
    provider: str | None = None,
    bot_id: str | None = None,
    chat_id: str | None = None,
    websocket_url: str | None = None,
    webhook_url: str | None = None,
    webhook_key: str | None = None,
    secret: str | None = None,
    timeout_seconds: float | None = None,
    dry_run: bool | None = None,
) -> BotConfig:
    raw_timeout = timeout_seconds
    if raw_timeout is None:
        raw_timeout = float(os.environ.get("BOT_TIMEOUT_SECONDS", "10"))
    raw_dry_run = dry_run
    if raw_dry_run is None:
        raw_dry_run = os.environ.get("BOT_DRY_RUN", "0") == "1"

    settings = _load_settings()
    settings_path = str(_settings_path())
    explicit_bot = _normalize_text(bot_id) or _normalize_text(secret) or _normalize_text(chat_id)
    explicit_webhook = _normalize_text(webhook_url) or _normalize_text(webhook_key)

    saved_bot_id = _normalize_text(settings.get("bot_id"))
    saved_secret = _normalize_text(settings.get("secret"))
    saved_chat_ids = _normalize_chat_ids(settings.get("chat_ids"))
    saved_url = _normalize_text(settings.get("webhook_url"))
    saved_key = _normalize_text(settings.get("webhook_key"))
    env_bot_id = _normalize_text(os.environ.get(BOT_ID_ENV))
    env_bot_secret = _normalize_text(os.environ.get(BOT_SECRET_ENV))
    env_url = _normalize_text(
        os.environ.get(BOT_WEBHOOK_URL_ENV)
        or os.environ.get(WECHAT_WORK_BOT_WEBHOOK_ENV)
        or os.environ.get(WECHAT_BOT_WEBHOOK_ENV)
    )
    raw_provider = _normalize_text(provider or settings.get("provider") or os.environ.get("BOT_PROVIDER"))
    if raw_provider:
        resolved_provider = raw_provider
    elif explicit_webhook:
        resolved_provider = BOT_PROVIDER_WECHAT_WORK_WEBHOOK
    elif explicit_bot or saved_bot_id or saved_secret or env_bot_id or env_bot_secret:
        resolved_provider = BOT_PROVIDER_WECHAT_WORK_AIBOT
    elif saved_url or saved_key or env_url:
        resolved_provider = BOT_PROVIDER_WECHAT_WORK_WEBHOOK
    else:
        resolved_provider = BOT_PROVIDER_WECHAT_WORK_AIBOT

    if explicit_bot or resolved_provider == BOT_PROVIDER_WECHAT_WORK_AIBOT:
        resolved_bot_id = _normalize_text(bot_id) or saved_bot_id or env_bot_id
        resolved_secret = _normalize_text(secret) or saved_secret or env_bot_secret
        resolved_chat_ids = _normalize_chat_ids(
            [
                _normalize_text(chat_id),
                *saved_chat_ids,
                _normalize_text(settings.get("chat_id")),
                _normalize_text(os.environ.get(BOT_CHAT_ID_ENV)),
            ]
        )
        resolved_chat_id = resolved_chat_ids[0] if resolved_chat_ids else ""
        resolved_websocket_url = (
            _normalize_text(websocket_url)
            or _normalize_text(settings.get("websocket_url"))
            or _normalize_text(os.environ.get(BOT_WEBSOCKET_URL_ENV))
            or WECHAT_WORK_AIBOT_WEBSOCKET_URL
        )
        if _normalize_text(bot_id) or _normalize_text(secret) or _normalize_text(chat_id):
            source = "request"
            updated_at = ""
        elif saved_bot_id or saved_secret:
            source = "saved_file"
            updated_at = _normalize_text(settings.get("updated_at"))
        elif env_bot_id or env_bot_secret:
            source = "environment"
            updated_at = ""
        else:
            source = "none"
            updated_at = ""
        resolved_url, resolved_key = "", ""
    elif explicit_webhook:
        resolved_url, resolved_key = _normalize_wechat_work_webhook(explicit_webhook)
        resolved_secret = _normalize_text(secret)
        resolved_bot_id = ""
        resolved_chat_id = ""
        resolved_chat_ids = ()
        resolved_websocket_url = WECHAT_WORK_AIBOT_WEBSOCKET_URL
        resolved_provider = BOT_PROVIDER_WECHAT_WORK_WEBHOOK
        source = "request"
        updated_at = ""
    else:
        if saved_url or saved_key:
            resolved_url, resolved_key = _normalize_wechat_work_webhook(saved_url or saved_key)
            resolved_secret = _normalize_text(settings.get("secret"))
            resolved_bot_id = ""
            resolved_chat_id = ""
            resolved_chat_ids = ()
            resolved_websocket_url = WECHAT_WORK_AIBOT_WEBSOCKET_URL
            resolved_provider = BOT_PROVIDER_WECHAT_WORK_WEBHOOK
            source = "saved_file"
            updated_at = _normalize_text(settings.get("updated_at"))
        elif env_url:
            resolved_url, resolved_key = _normalize_wechat_work_webhook(env_url)
            resolved_secret = _normalize_text(
                secret
                or os.environ.get(BOT_WEBHOOK_SECRET_ENV)
                or os.environ.get(WECHAT_WORK_BOT_SECRET_ENV)
            )
            resolved_bot_id = ""
            resolved_chat_id = ""
            resolved_chat_ids = ()
            resolved_websocket_url = WECHAT_WORK_AIBOT_WEBSOCKET_URL
            resolved_provider = BOT_PROVIDER_WECHAT_WORK_WEBHOOK
            source = "environment"
            updated_at = ""
        else:
            resolved_url, resolved_key = "", ""
            resolved_secret = _normalize_text(secret)
            resolved_bot_id = ""
            resolved_chat_id = ""
            resolved_chat_ids = ()
            resolved_websocket_url = WECHAT_WORK_AIBOT_WEBSOCKET_URL
            source = "none"
            updated_at = ""

    if secret is not None and not explicit_webhook:
        resolved_secret = _normalize_text(secret)

    return BotConfig(
        provider=resolved_provider,
        bot_id=resolved_bot_id,
        chat_id=resolved_chat_id,
        chat_ids=resolved_chat_ids,
        websocket_url=resolved_websocket_url,
        webhook_url=resolved_url,
        webhook_key=resolved_key,
        secret=resolved_secret,
        timeout_seconds=float(raw_timeout),
        dry_run=bool(raw_dry_run),
        source=source,
        settings_path=settings_path,
        updated_at=updated_at,
    )


def set_bot_config(
    *,
    bot_id: str = "",
    secret: str = "",
    chat_id: str = "",
    websocket_url: str = "",
    webhook_url: str = "",
    webhook_key: str = "",
    provider: str = BOT_PROVIDER_WECHAT_WORK_AIBOT,
) -> dict[str, Any]:
    normalized_provider = _normalize_text(provider) or BOT_PROVIDER_WECHAT_WORK_AIBOT
    if normalized_provider == BOT_PROVIDER_WECHAT_WORK_AIBOT:
        normalized_bot_id = _normalize_text(bot_id)
        normalized_secret = _normalize_text(secret)
        if not normalized_bot_id or not normalized_secret:
            raise BotAssistantError("bot_id and secret are required for WeCom AI Bot")
        existing = _load_settings()
        same_bot = _normalize_text(existing.get("bot_id")) == normalized_bot_id
        existing_chat_ids = _normalize_chat_ids(existing.get("chat_ids")) if same_bot else ()
        chat_ids = _normalize_chat_ids([_normalize_text(chat_id), *existing_chat_ids, _normalize_text(existing.get("chat_id")) if same_bot else ""])
        payload = {
            "provider": BOT_PROVIDER_WECHAT_WORK_AIBOT,
            "bot_id": normalized_bot_id,
            "secret": normalized_secret,
            "chat_ids": list(chat_ids),
            "websocket_url": _normalize_text(websocket_url) or WECHAT_WORK_AIBOT_WEBSOCKET_URL,
            "updated_at": _now_utc_iso(),
        }
        if same_bot and isinstance(existing.get("target_metadata"), dict):
            payload["target_metadata"] = existing["target_metadata"]
        _save_settings(payload)
        status = bot_config_status(load_bot_config())
        ensure_wecom_aibot_listener()
        return status

    raw_webhook = _normalize_text(webhook_url) or _normalize_text(webhook_key)
    resolved_url, resolved_key = _normalize_wechat_work_webhook(raw_webhook)
    if not resolved_url:
        raise BotAssistantError("webhook_url or webhook_key is required")
    payload = {
        "provider": BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
        "webhook_url": resolved_url,
        "webhook_key": resolved_key,
        "secret": _normalize_text(secret),
        "updated_at": _now_utc_iso(),
    }
    _save_settings(payload)
    return bot_config_status(load_bot_config())


def bot_config_status(config: BotConfig | None = None) -> dict[str, Any]:
    resolved = config or load_bot_config()
    parsed = urlparse(resolved.webhook_url)
    configured = bool(resolved.bot_id and resolved.secret) if resolved.provider == BOT_PROVIDER_WECHAT_WORK_AIBOT else bool(resolved.webhook_url)
    status = {
        "provider": resolved.provider,
        "configured": configured,
        "source": resolved.source,
        "has_secret": bool(resolved.secret),
        "dry_run": resolved.dry_run,
        "bot_id": _mask_secret(resolved.bot_id),
        "chat_id": _mask_secret(resolved.chat_id),
        "chat_ids": [_mask_secret(value) for value in resolved.chat_ids],
        "chat_target_count": len(resolved.chat_ids),
        "websocket_url": resolved.websocket_url,
        "webhook_key": _mask_secret(resolved.webhook_key),
        "masked_webhook_url": _mask_webhook_url(resolved.webhook_url, resolved.webhook_key),
        "webhook_host": parsed.netloc if resolved.webhook_url else "",
        "settings_path": resolved.settings_path,
        "updated_at": resolved.updated_at,
    }
    if resolved.provider == BOT_PROVIDER_WECHAT_WORK_AIBOT:
        status["listener"] = wecom_aibot_listener_status(resolved)
    return status


def _target_metadata() -> dict[str, dict[str, Any]]:
    settings = _load_settings()
    raw_metadata = settings.get("target_metadata")
    if not isinstance(raw_metadata, dict):
        return {}
    return {
        _normalize_text(key): value
        for key, value in raw_metadata.items()
        if _normalize_text(key) and isinstance(value, dict)
    }


def _extract_wecom_aibot_target(frame: dict[str, Any]) -> tuple[str, str]:
    body = _coerce_mapping(frame.get("body"))
    event = _coerce_mapping(body.get("event"))
    paths: list[tuple[str, tuple[str, ...], str]] = [
        ("chat", ("chatid",), "chat"),
        ("chat", ("chat_id",), "chat"),
        ("chat", ("conversation_id",), "chat"),
        ("chat", ("roomid",), "chat"),
        ("chat", ("room_id",), "chat"),
        ("chat", ("chat", "chatid"), "chat"),
        ("chat", ("conversation", "chatid"), "chat"),
        ("chat", ("message", "chatid"), "chat"),
        ("user", ("from", "userid"), "user"),
        ("user", ("sender", "userid"), "user"),
        ("user", ("user", "userid"), "user"),
        ("user", ("from_userid",), "user"),
        ("user", ("userid",), "user"),
    ]
    for _, path, target_type in paths:
        value = _normalize_text(_nested_get(body, path))
        if value:
            return value, target_type
    for path in (
        ("chatid",),
        ("chat_id",),
        ("conversation_id",),
        ("from", "userid"),
        ("userid",),
    ):
        value = _normalize_text(_nested_get(event, path))
        if value:
            target_type = "user" if "userid" in path else "chat"
            return value, target_type
    chat_target = _find_first_value_for_keys(frame, {"chatid", "chat_id", "conversation_id", "roomid", "room_id"})
    if chat_target:
        return chat_target, "chat"
    user_target = _find_first_value_for_keys(frame, {"userid", "user_id", "from_userid"})
    if user_target:
        return user_target, "user"
    return "", ""


def register_wecom_aibot_target_from_frame(frame: dict[str, Any]) -> dict[str, Any]:
    target, target_type = _extract_wecom_aibot_target(frame)
    if not target:
        return {"registered": False, "reason": "target_not_found"}

    now = _now_utc_iso()
    with _SETTINGS_LOCK:
        settings = _load_settings()
        chat_ids = list(_normalize_chat_ids([*(_normalize_chat_ids(settings.get("chat_ids"))), _normalize_text(settings.get("chat_id"))]))
        added = target not in chat_ids
        if added:
            chat_ids.append(target)
        chat_ids = chat_ids[-MAX_REGISTERED_TARGETS:]

        metadata = _target_metadata()
        current = dict(metadata.get(target) or {})
        current.setdefault("first_seen_at", now)
        current["last_seen_at"] = now
        current["target_type"] = target_type or current.get("target_type") or "chat"
        current["message_count"] = int(current.get("message_count") or 0) + 1
        metadata[target] = current

        settings["chat_ids"] = chat_ids
        settings["target_metadata"] = metadata
        settings.pop("chat_id", None)
        _save_settings(settings)

    return {
        "registered": True,
        "added": added,
        "target": _mask_secret(target),
        "target_type": target_type,
        "chat_target_count": len(chat_ids),
    }


class _WeComAibotListener:
    def __init__(self) -> None:
        self._lock = Lock()
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: Any = None
        self._started = False
        self._authenticated = False
        self._last_error = ""
        self._last_registered_at = ""
        self._stop_event: Event | None = None
        self._signature = ""
        self._last_started_monotonic = 0.0

    def ensure_started(self, config: BotConfig | None = None) -> None:
        resolved = config or load_bot_config()
        if resolved.provider != BOT_PROVIDER_WECHAT_WORK_AIBOT or not resolved.bot_id or not resolved.secret or resolved.dry_run:
            return
        signature = hashlib.sha256(
            f"{resolved.bot_id}\0{resolved.secret}\0{resolved.websocket_url}".encode("utf-8")
        ).hexdigest()
        now = time.monotonic()
        with self._lock:
            if self._thread and self._thread.is_alive():
                if self._signature == signature:
                    if not self._should_restart_unhealthy_locked(now):
                        return
                if self._stop_event:
                    self._stop_event.set()
            self._stop_event = Event()
            self._signature = signature
            self._authenticated = False
            self._last_error = ""
            self._client = None
            self._last_started_monotonic = now
            thread = Thread(
                target=self._run_thread,
                args=(resolved, self._stop_event),
                name="wecom-aibot-listener",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            self._started = True

    def _client_connected_locked(self) -> bool:
        client = self._client
        if not client:
            return False
        try:
            return bool(getattr(client, "is_connected", False))
        except Exception:
            return False

    def _should_restart_unhealthy_locked(self, now: float) -> bool:
        if not self._last_error:
            return False
        if self._authenticated or self._client_connected_locked():
            return False
        if now - self._last_started_monotonic < LISTENER_RESTART_BACKOFF_SECONDS:
            return False
        manager = getattr(self._client, "_ws_manager", None)
        reconnect_task = getattr(manager, "_reconnect_task", None)
        if reconnect_task is not None:
            try:
                if not reconnect_task.done():
                    return False
            except Exception:
                pass
        return True

    def status(self, config: BotConfig | None = None) -> dict[str, Any]:
        self.ensure_started(config)
        resolved = config or load_bot_config()
        configured = resolved.provider == BOT_PROVIDER_WECHAT_WORK_AIBOT and bool(resolved.bot_id and resolved.secret)
        with self._lock:
            running = bool(self._thread and self._thread.is_alive())
            connected = self._client_connected_locked()
            return {
                "enabled": configured and not resolved.dry_run,
                "running": running,
                "connected": connected,
                "authenticated": self._authenticated,
                "last_error": self._last_error,
                "last_registered_at": self._last_registered_at,
            }

    def _set_error(self, error: str, *, thread: Thread | None = None) -> None:
        with self._lock:
            if thread is not None and self._thread is not thread:
                return
            self._last_error = error
            self._authenticated = False

    def _mark_authenticated(self, *, thread: Thread | None = None) -> None:
        with self._lock:
            if thread is not None and self._thread is not thread:
                return
            self._authenticated = True
            self._last_error = ""

    def _mark_registered(self, *, thread: Thread | None = None) -> None:
        with self._lock:
            if thread is not None and self._thread is not thread:
                return
            self._last_registered_at = _now_utc_iso()

    def _run_thread(self, config: BotConfig, stop_event: Event) -> None:
        active_thread = current_thread()
        loop = asyncio.new_event_loop()
        with self._lock:
            self._loop = loop
        try:
            loop.run_until_complete(self._run_async(config, stop_event))
        except Exception as exc:
            logger.exception("WeCom AI Bot listener stopped")
            self._set_error(str(exc), thread=active_thread)
        finally:
            with self._lock:
                if self._thread is active_thread:
                    self._loop = None
                    self._client = None
                    self._authenticated = False
            loop.close()

    async def _run_async(self, config: BotConfig, stop_event: Event) -> None:
        try:
            from wecom_aibot_sdk import WSClient
        except ImportError as exc:
            self._set_error("wecom-aibot-sdk is not installed", thread=current_thread())
            raise BotAssistantError(
                "wecom-aibot-sdk is not installed; run `pip install -r requirements.txt`"
            ) from exc

        active_thread = current_thread()
        client = WSClient(
            bot_id=config.bot_id,
            secret=config.secret,
            ws_url=config.websocket_url or WECHAT_WORK_AIBOT_WEBSOCKET_URL,
            request_timeout=int(max(1.0, config.timeout_seconds) * 1000),
            max_reconnect_attempts=-1,
        )
        with self._lock:
            self._client = client

        def handle_frame(frame: dict[str, Any]) -> None:
            result = register_wecom_aibot_target_from_frame(frame)
            if result.get("registered"):
                self._mark_registered(thread=active_thread)

        client.on("authenticated", lambda: self._mark_authenticated(thread=active_thread))
        client.on("error", lambda error: self._set_error(str(error), thread=active_thread))
        client.on("disconnected", lambda reason: self._set_error(str(reason), thread=active_thread))
        ws_manager = getattr(client, "_ws_manager", None)
        message_handler = getattr(client, "_message_handler", None)
        if ws_manager is not None and message_handler is not None:
            ws_manager.on_message = lambda frame: (handle_frame(frame), message_handler.handle_frame(frame, client))
        else:
            client.on("message", handle_frame)
            client.on("event.enter_chat", handle_frame)

        await client.connect()
        while not stop_event.is_set():
            await asyncio.sleep(1)
        await client.disconnect()

    async def send_to_target(self, target: str, payload: dict[str, Any], timeout_seconds: float) -> Any:
        deadline = asyncio.get_running_loop().time() + max(3.0, timeout_seconds)
        while True:
            with self._lock:
                authenticated = self._authenticated
                loop = self._loop
                client = self._client
            if authenticated:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise BotAssistantError("WeCom AI Bot listener is not authenticated")
            await asyncio.sleep(0.1)
        with self._lock:
            loop = self._loop
            client = self._client
        if loop and client and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(client.send_message(target, payload), loop)
            return await asyncio.wrap_future(future)
        raise BotAssistantError("WeCom AI Bot listener is not connected")


_WECOM_AIBOT_LISTENER = _WeComAibotListener()


def ensure_wecom_aibot_listener(config: BotConfig | None = None) -> None:
    _WECOM_AIBOT_LISTENER.ensure_started(config)


def wecom_aibot_listener_status(config: BotConfig | None = None) -> dict[str, Any]:
    return _WECOM_AIBOT_LISTENER.status(config)


def _signed_webhook_url(config: BotConfig) -> str:
    if not config.secret:
        return config.webhook_url
    timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    sign_payload = f"{timestamp}\n{config.secret}".encode("utf-8")
    digest = hmac.new(config.secret.encode("utf-8"), sign_payload, hashlib.sha256).digest()
    signature = quote_plus(base64.b64encode(digest).decode("utf-8"))
    separator = "&" if "?" in config.webhook_url else "?"
    return f"{config.webhook_url}{separator}timestamp={timestamp}&sign={signature}"


def build_text_payload(content: str, *, mentioned_mobile_list: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "msgtype": "text",
        "text": {"content": content},
    }
    if mentioned_mobile_list:
        payload["text"]["mentioned_mobile_list"] = mentioned_mobile_list
    return payload


def build_markdown_payload(content: str) -> dict[str, Any]:
    return {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }


def build_wecom_aibot_markdown_payload(content: str) -> dict[str, Any]:
    return {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }


def _payload_for_provider(payload: dict[str, Any], config: BotConfig) -> dict[str, Any]:
    if config.provider != BOT_PROVIDER_WECHAT_WORK_AIBOT:
        return payload
    if payload.get("msgtype") == "markdown" and isinstance(payload.get("markdown"), dict):
        return payload
    if payload.get("msgtype") == "text" and isinstance(payload.get("text"), dict):
        content = _normalize_text(payload["text"].get("content"))
        return build_wecom_aibot_markdown_payload(content)
    if "markdown" in payload and isinstance(payload.get("markdown"), dict):
        return {"msgtype": "markdown", "markdown": payload["markdown"]}
    if "template_card" in payload and isinstance(payload.get("template_card"), dict):
        return {"msgtype": "template_card", "template_card": payload["template_card"]}
    return build_wecom_aibot_markdown_payload(json.dumps(payload, ensure_ascii=False))


def _coerce_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _item_title(item: dict[str, Any]) -> str:
    for key in ("title", "victim", "victimName", "name", "cveId", "id"):
        value = item.get(key)
        if value:
            return str(value)
    return "未命名事件"


def _item_time(item: dict[str, Any]) -> str:
    for key in ("disclosure_time", "publishedDate", "updatedDate", "time", "created_at"):
        value = item.get(key)
        if value:
            return str(value).replace("T", " ")[:16]
    return ""


def build_intelligence_digest(payload: dict[str, Any], *, limit: int = 5, title: str = "暗网威胁情报推送") -> str:
    summary_cards = _coerce_items(payload.get("dashboardSummaryCards"))
    vulnerability_events = _coerce_items(payload.get("vulnerabilityEvents"))
    ransomware_events = _coerce_items(payload.get("ransomwareEvents"))
    data_leak_events = _coerce_items(payload.get("dataLeakEvents"))
    situation_alerts = _coerce_items(payload.get("situationAlerts"))

    lines = [f"### {title}", f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]

    if summary_cards:
        lines.append("")
        lines.append("**概览**")
        for item in summary_cards[:4]:
            name = item.get("label") or item.get("title") or "指标"
            value = item.get("value") or item.get("count") or item.get("highlight") or "-"
            lines.append(f"- {name}: {value}")

    event_blocks = [
        ("漏洞预警", vulnerability_events),
        ("勒索情报", ransomware_events),
        ("数据泄露", data_leak_events),
    ]
    for block_title, items in event_blocks:
        if not items:
            continue
        lines.append("")
        lines.append(f"**{block_title}**")
        for item in items[:limit]:
            suffix_parts = []
            severity = item.get("severity") or item.get("riskLevel") or item.get("level")
            if severity:
                suffix_parts.append(str(severity))
            event_time = _item_time(item)
            if event_time:
                suffix_parts.append(event_time)
            suffix = f" ({' / '.join(suffix_parts)})" if suffix_parts else ""
            lines.append(f"- {_item_title(item)}{suffix}")

    if situation_alerts:
        lines.append("")
        lines.append("**态势告警**")
        for item in situation_alerts[:limit]:
            text = item.get("title") or item.get("message") or item.get("summary")
            if text:
                lines.append(f"- {text}")

    if len(lines) <= 2:
        lines.append("")
        lines.append("暂无可推送的情报数据。")
    return "\n".join(lines)


def post_bot_payload(payload: dict[str, Any], config: BotConfig | None = None) -> dict[str, Any]:
    resolved = config or load_bot_config()
    resolved_payload = _payload_for_provider(payload, resolved)
    if resolved.dry_run:
        return {"ok": True, "dry_run": True, "payload": resolved_payload, **bot_config_status(resolved)}
    if resolved.provider == BOT_PROVIDER_WECHAT_WORK_AIBOT:
        return _post_wecom_aibot_payload(resolved_payload, resolved)
    if resolved.provider != BOT_PROVIDER_WECHAT_WORK_WEBHOOK:
        raise BotAssistantError(f"unsupported bot provider: {resolved.provider}")
    if not resolved.webhook_url:
        raise BotAssistantError("Bot webhook is not configured")

    request = Request(
        _signed_webhook_url(resolved),
        data=json.dumps(resolved_payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=resolved.timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            status_code = int(response.status)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise BotAssistantError(f"Bot webhook returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise BotAssistantError(f"Bot webhook request failed: {exc}") from exc

    parsed_body: Any
    try:
        parsed_body = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        parsed_body = raw_body

    ok = 200 <= status_code < 300
    if isinstance(parsed_body, dict) and "errcode" in parsed_body:
        ok = ok and int(parsed_body.get("errcode") or 0) == 0
    result = {
        "ok": ok,
        "dry_run": False,
        "status_code": status_code,
        "response": parsed_body,
        **bot_config_status(resolved),
    }
    if not ok:
        raise BotAssistantError(f"Bot webhook rejected message: {result}")
    return result


def _post_wecom_aibot_payload(payload: dict[str, Any], config: BotConfig) -> dict[str, Any]:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop and running_loop.is_running():
        result: dict[str, Any] = {}
        error: list[BaseException] = []

        def run_in_thread() -> None:
            try:
                result.update(asyncio.run(_post_wecom_aibot_payload_async(payload, config)))
            except BaseException as exc:
                error.append(exc)

        thread = Thread(target=run_in_thread, name="wecom-aibot-send", daemon=True)
        thread.start()
        thread.join()
        if error:
            raise error[0]
        return result
    return asyncio.run(_post_wecom_aibot_payload_async(payload, config))


def _serialize_sdk_response(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return dict(value.__dict__)
        except Exception:
            pass
    return str(value)


async def _post_wecom_aibot_payload_async(payload: dict[str, Any], config: BotConfig) -> dict[str, Any]:
    if not config.bot_id or not config.secret:
        raise BotAssistantError("WeCom AI Bot ID and Secret are not configured")
    chat_ids = _normalize_chat_ids(config.chat_ids or [_normalize_text(config.chat_id)])
    if not chat_ids:
        raise BotAssistantError("WeCom AI Bot has no registered push target; add the bot to a group chat or send it a private message first")
    ensure_wecom_aibot_listener(config)
    try:
        responses = []
        errors = []
        for chat_id in chat_ids:
            try:
                response = await asyncio.wait_for(
                    _WECOM_AIBOT_LISTENER.send_to_target(chat_id, payload, config.timeout_seconds),
                    timeout=max(8.0, config.timeout_seconds + 5.0),
                )
                responses.append({"chat_id": _mask_secret(chat_id), "response": _serialize_sdk_response(response)})
            except Exception as exc:
                errors.append({"chat_id": _mask_secret(chat_id), "error": str(exc) or exc.__class__.__name__})
        if not responses:
            raise BotAssistantError(f"WeCom AI Bot request failed for all registered targets: {errors}")
        return {
            "ok": True,
            "dry_run": False,
            "sent": True,
            "sent_count": len(responses),
            "failed_count": len(errors),
            "responses": responses,
            "errors": errors,
            **bot_config_status(load_bot_config()),
        }
    except BotAssistantError:
        raise


def send_text_message(content: str, config: BotConfig | None = None) -> dict[str, Any]:
    return post_bot_payload(build_text_payload(content), config)


def send_markdown_message(content: str, config: BotConfig | None = None) -> dict[str, Any]:
    return post_bot_payload(build_markdown_payload(content), config)


def send_intelligence_digest(payload: dict[str, Any], config: BotConfig | None = None, *, limit: int = 5) -> dict[str, Any]:
    content = build_intelligence_digest(payload, limit=limit)
    return post_bot_payload(build_markdown_payload(content), config)
