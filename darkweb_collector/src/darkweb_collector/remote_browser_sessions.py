from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
from queue import Queue
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from darkweb_collector.db import get_db_connection, upsert_platform_session
from darkweb_collector.document_exposure_platforms import get_exposure_platform
from darkweb_collector.document_exposure_sessions import (
    platform_profile_dir,
    platform_storage_state_path,
    platform_user_data_dir,
)


REMOTE_LOGIN_VIEWPORT = {"width": 1366, "height": 900}
_REMOTE_SESSIONS: dict[str, "RemoteBrowserSession"] = {}
_REMOTE_SESSIONS_LOCK = Lock()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RemoteBrowserSession:
    session_id: str
    platform: str
    label: str
    login_url: str
    homepage_url: str
    requires_login: bool
    storage_state_path: str
    user_data_dir: str
    created_at: str
    commands: Queue
    thread: Thread | None = None


def _state_payload(
    session: RemoteBrowserSession,
    page: Any,
    *,
    include_screenshot: bool = True,
) -> dict[str, Any]:
    title = ""
    url = ""
    screenshot = ""
    try:
        title = str(page.title() or "")
    except Exception:
        title = ""
    try:
        url = str(page.url or "")
    except Exception:
        url = ""
    if include_screenshot:
        png = page.screenshot(type="png", full_page=False)
        screenshot = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return {
        "session_id": session.session_id,
        "platform": session.platform,
        "label": session.label,
        "title": title,
        "url": url,
        "screenshot": screenshot,
        "viewport": dict(REMOTE_LOGIN_VIEWPORT),
        "storage_state_path": session.storage_state_path,
        "user_data_dir": session.user_data_dir,
        "created_at": session.created_at,
    }


def _save_platform_session(session: RemoteBrowserSession, account_label: str) -> dict[str, Any]:
    updated_at = _now_utc_iso()
    metadata = {
        "remote_browser_session": True,
        "remote_session_id": session.session_id,
        "user_data_dir": session.user_data_dir,
        "saved_at": updated_at,
    }
    with get_db_connection() as connection:
        upsert_platform_session(
            connection,
            {
                "platform": session.platform,
                "account_label": str(account_label or "").strip(),
                "login_url": session.login_url,
                "homepage_url": session.homepage_url,
                "requires_login": session.requires_login,
                "status": "configured",
                "storage_state_path": session.storage_state_path,
                "last_verified_at": updated_at,
                "last_error": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
                "updated_at": updated_at,
            },
        )
        connection.commit()
    return {
        "platform": session.platform,
        "status": "configured",
        "valid": True,
        "storage_state_path": session.storage_state_path,
        "last_verified_at": updated_at,
        "metadata": metadata,
    }


def _remote_browser_worker(session: RemoteBrowserSession, startup_queue: Queue) -> None:
    playwright = None
    context = None
    try:
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        context = playwright.chromium.launch_persistent_context(
            session.user_data_dir,
            headless=True,
            viewport=dict(REMOTE_LOGIN_VIEWPORT),
            ignore_https_errors=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(session.login_url or session.homepage_url, wait_until="domcontentloaded", timeout=45000)
        startup_queue.put(("ok", _state_payload(session, page)))

        while True:
            command = session.commands.get()
            op = str(command.get("op") or "")
            payload = command.get("payload") or {}
            response_queue = command["response_queue"]
            should_stop = False
            try:
                if op == "state":
                    result = _state_payload(session, page)
                elif op == "control":
                    result = _apply_remote_action(session, page, payload)
                elif op == "finish":
                    context.storage_state(path=session.storage_state_path)
                    result = _save_platform_session(session, str(payload.get("account_label") or ""))
                    should_stop = True
                elif op == "close":
                    result = {"session_id": session.session_id, "platform": session.platform, "status": "closed"}
                    should_stop = True
                else:
                    raise ValueError(f"unsupported remote browser op: {op}")
                response_queue.put(("ok", result))
            except Exception as exc:
                response_queue.put(("error", str(exc)))
            if should_stop:
                break
    except Exception as exc:
        startup_queue.put(("error", str(exc)))
    finally:
        if context is not None:
            try:
                context.storage_state(path=session.storage_state_path)
            except Exception:
                pass
            try:
                context.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def _apply_remote_action(session: RemoteBrowserSession, page: Any, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    if action == "click":
        page.mouse.click(float(payload.get("x") or 0), float(payload.get("y") or 0))
    elif action == "type":
        text = str(payload.get("text") or "")
        if text:
            page.keyboard.type(text, delay=20)
    elif action == "key":
        key = str(payload.get("key") or "").strip()
        if key:
            page.keyboard.press(key)
    elif action == "navigate":
        url = str(payload.get("url") or "").strip()
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
    elif action == "wait":
        page.wait_for_timeout(int(payload.get("ms") or 1000))
    else:
        raise ValueError(f"unsupported remote browser action: {action}")
    page.wait_for_timeout(500)
    return _state_payload(session, page)


def _get_remote_session(session_id: str) -> RemoteBrowserSession:
    with _REMOTE_SESSIONS_LOCK:
        session = _REMOTE_SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("remote browser session not found")
    return session


def _call_session(session: RemoteBrowserSession, op: str, payload: dict[str, Any] | None = None) -> Any:
    response_queue: Queue = Queue(maxsize=1)
    session.commands.put({"op": op, "payload": payload or {}, "response_queue": response_queue})
    status, result = response_queue.get(timeout=70)
    if status == "error":
        raise ValueError(str(result))
    return result


def _remove_session_keys(session: RemoteBrowserSession) -> None:
    with _REMOTE_SESSIONS_LOCK:
        _REMOTE_SESSIONS.pop(session.session_id, None)
        current = _REMOTE_SESSIONS.get(session.platform)
        if current is session:
            _REMOTE_SESSIONS.pop(session.platform, None)


def start_remote_browser_login(platform_name: str) -> dict[str, Any]:
    platform = get_exposure_platform(platform_name)
    profile_dir = platform_profile_dir(platform.key)
    profile_dir.mkdir(parents=True, exist_ok=True)
    user_data_dir = platform_user_data_dir(platform.key)
    user_data_dir.mkdir(parents=True, exist_ok=True)
    storage_state_path = platform_storage_state_path(platform.key)
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    with _REMOTE_SESSIONS_LOCK:
        previous = _REMOTE_SESSIONS.pop(platform.key, None)
        if previous is not None:
            _REMOTE_SESSIONS.pop(previous.session_id, None)
    if previous is not None:
        try:
            _call_session(previous, "close")
        except Exception:
            pass

    startup_queue: Queue = Queue(maxsize=1)
    session = RemoteBrowserSession(
        session_id=uuid4().hex,
        platform=platform.key,
        label=platform.label,
        login_url=platform.login_url or platform.homepage_url,
        homepage_url=platform.homepage_url,
        requires_login=platform.requires_login,
        storage_state_path=str(storage_state_path),
        user_data_dir=str(user_data_dir),
        created_at=_now_utc_iso(),
        commands=Queue(),
    )
    thread = Thread(target=_remote_browser_worker, args=(session, startup_queue), daemon=True)
    session.thread = thread
    thread.start()
    status, result = startup_queue.get(timeout=70)
    if status == "error":
        raise ValueError(str(result))
    with _REMOTE_SESSIONS_LOCK:
        _REMOTE_SESSIONS[session.session_id] = session
        _REMOTE_SESSIONS[session.platform] = session
    return result


def get_remote_browser_state(session_id: str) -> dict[str, Any]:
    return _call_session(_get_remote_session(session_id), "state")


def control_remote_browser(session_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = dict(payload or {})
    body["action"] = action
    return _call_session(_get_remote_session(session_id), "control", body)


def finish_remote_browser_login(session_id: str, account_label: str = "") -> dict[str, Any]:
    session = _get_remote_session(session_id)
    try:
        return _call_session(session, "finish", {"account_label": account_label})
    finally:
        _remove_session_keys(session)


def close_remote_browser_login(session_id: str) -> dict[str, Any]:
    session = _get_remote_session(session_id)
    try:
        return _call_session(session, "close")
    finally:
        _remove_session_keys(session)
