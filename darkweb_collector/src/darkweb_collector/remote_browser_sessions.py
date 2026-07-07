from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import json
import os
from queue import Queue
import shutil
import socket
import subprocess
from threading import Lock, Thread
import time
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

USERNAME_SELECTORS = [
    "input#login_field",
    "input#user_login",
    "input[name='login']",
    "input[name='username']",
    "input[name='user[login]']",
    "input[name='account']",
    "input[name='email']",
    "input[type='email']",
    "input[autocomplete='username']",
    "input[autocomplete='email']",
    "input[placeholder*='账号']",
    "input[placeholder*='用户名']",
    "input[placeholder*='邮箱']",
    "input[placeholder*='Email']",
    "input[placeholder*='Username']",
    "input[type='text']",
]
PASSWORD_SELECTORS = [
    "input#password",
    "input[name='password']",
    "input[type='password']",
    "input[autocomplete='current-password']",
]
OTP_SELECTORS = [
    "input[name*='otp']",
    "input[name*='code']",
    "input[id*='otp']",
    "input[id*='code']",
    "input[autocomplete='one-time-code']",
    "input[placeholder*='验证码']",
    "input[placeholder*='验证']",
    "input[placeholder*='code']",
]
SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Sign in')",
    "button:has-text('Log in')",
    "button:has-text('登录')",
    "button:has-text('登入')",
    "button:has-text('下一步')",
    "button:has-text('Continue')",
    "button:has-text('Next')",
]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _find_free_display() -> str:
    for display_number in range(90, 140):
        socket_path = f"/tmp/.X11-unix/X{display_number}"
        if not os.path.exists(socket_path):
            return f":{display_number}"
    raise RuntimeError("no free X display was found for embedded browser")


def _require_linux_embedded_runtime() -> None:
    missing = [name for name in ("Xvfb", "x11vnc") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(
            "embedded browser runtime is missing: "
            + ", ".join(missing)
            + ". Install xvfb and x11vnc on Linux."
        )


def _wait_for_x_display(display: str, process: subprocess.Popen) -> None:
    display_number = display.lstrip(":").split(".", 1)[0]
    socket_path = f"/tmp/.X11-unix/X{display_number}"
    deadline = time.time() + 8
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Xvfb exited before the embedded browser display became ready")
        if os.path.exists(socket_path):
            return
        time.sleep(0.1)
    raise RuntimeError("embedded browser display did not become ready")


def _wait_for_tcp_port(port: int, process: subprocess.Popen) -> None:
    deadline = time.time() + 8
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("x11vnc exited before the VNC port became ready")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("embedded browser VNC port did not become ready")


def _terminate_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=4)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _start_embedded_display(session: "RemoteBrowserSession") -> None:
    _require_linux_embedded_runtime()
    session.display = _find_free_display()
    session.vnc_port = _find_free_tcp_port()
    env = os.environ.copy()
    env["DISPLAY"] = session.display

    session.xvfb_process = subprocess.Popen(
        [
            "Xvfb",
            session.display,
            "-screen",
            "0",
            f"{REMOTE_LOGIN_VIEWPORT['width']}x{REMOTE_LOGIN_VIEWPORT['height']}x24",
            "-nolisten",
            "tcp",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    _wait_for_x_display(session.display, session.xvfb_process)

    if shutil.which("openbox") is not None:
        session.window_manager_process = subprocess.Popen(
            ["openbox"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    session.vnc_process = subprocess.Popen(
        [
            "x11vnc",
            "-display",
            session.display,
            "-localhost",
            "-nopw",
            "-forever",
            "-shared",
            "-rfbport",
            str(session.vnc_port),
            "-quiet",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    _wait_for_tcp_port(session.vnc_port, session.vnc_process)


def _stop_embedded_display(session: "RemoteBrowserSession") -> None:
    _terminate_process(session.vnc_process)
    _terminate_process(session.window_manager_process)
    _terminate_process(session.xvfb_process)
    session.vnc_process = None
    session.window_manager_process = None
    session.xvfb_process = None


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
    display: str = ""
    vnc_port: int = 0
    xvfb_process: subprocess.Popen | None = None
    window_manager_process: subprocess.Popen | None = None
    vnc_process: subprocess.Popen | None = None


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
        "mode": "embedded_browser" if session.vnc_port else "headless_control",
        "title": title,
        "url": url,
        "screenshot": screenshot,
        "rfb_ws_path": f"/api/platform-sessions/remote-login/{session.session_id}/rfb" if session.vnc_port else "",
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
        "remote_browser_mode": "embedded_browser" if session.vnc_port else "headless_control",
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
        browser_env = os.environ.copy()
        if session.display:
            browser_env["DISPLAY"] = session.display
        context = playwright.chromium.launch_persistent_context(
            session.user_data_dir,
            headless=not bool(session.display),
            viewport=dict(REMOTE_LOGIN_VIEWPORT),
            screen=dict(REMOTE_LOGIN_VIEWPORT),
            env=browser_env,
            ignore_https_errors=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--window-position=0,0",
                f"--window-size={REMOTE_LOGIN_VIEWPORT['width']},{REMOTE_LOGIN_VIEWPORT['height']}",
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
        _stop_embedded_display(session)


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
    elif action == "fill_login_form":
        result = _fill_login_form(page, payload)
        page.wait_for_timeout(500)
        state = _state_payload(session, page)
        state["action_result"] = result
        return state
    elif action == "submit_login_form":
        result = _submit_login_form(page)
        page.wait_for_timeout(1200)
        state = _state_payload(session, page)
        state["action_result"] = result
        return state
    else:
        raise ValueError(f"unsupported remote browser action: {action}")
    page.wait_for_timeout(500)
    return _state_payload(session, page)


def _first_editable_locator(page: Any, selectors: list[str]) -> Any | None:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 6)
        except Exception:
            continue
        for index in range(count):
            item = locator.nth(index)
            try:
                if item.is_visible() and item.is_enabled():
                    return item
            except Exception:
                continue
    return None


def _fill_first_available(page: Any, selectors: list[str], value: str) -> bool:
    text = str(value or "")
    if not text:
        return False
    locator = _first_editable_locator(page, selectors)
    if locator is None:
        return False
    locator.fill(text)
    return True


def _fill_login_form(page: Any, payload: dict[str, Any]) -> dict[str, Any]:
    username_filled = _fill_first_available(page, USERNAME_SELECTORS, str(payload.get("username") or ""))
    password_filled = _fill_first_available(page, PASSWORD_SELECTORS, str(payload.get("password") or ""))
    otp = str(payload.get("otp") or "")
    otp_filled = _fill_first_available(page, OTP_SELECTORS, otp) if otp else False
    if not username_filled and not password_filled and not otp_filled:
        raise ValueError("no supported login input was found on the current page")
    return {
        "username_filled": username_filled,
        "password_filled": password_filled,
        "otp_filled": otp_filled,
    }


def _submit_login_form(page: Any) -> dict[str, Any]:
    locator = _first_editable_locator(page, SUBMIT_SELECTORS)
    if locator is not None:
        locator.click()
        return {"submitted": True, "method": "button"}
    page.keyboard.press("Enter")
    return {"submitted": True, "method": "enter"}


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
    if os.name != "nt":
        try:
            _start_embedded_display(session)
        except Exception:
            _stop_embedded_display(session)
            raise

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


async def proxy_remote_browser_rfb(session_id: str, websocket: Any) -> None:
    try:
        session = _get_remote_session(session_id)
    except ValueError:
        await websocket.close(code=1008)
        return
    if not session.vnc_port:
        await websocket.close(code=1008)
        return

    protocol_header = str(websocket.headers.get("sec-websocket-protocol") or "")
    subprotocol = "binary" if "binary" in protocol_header else None
    await websocket.accept(subprotocol=subprotocol)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", session.vnc_port)
    except OSError:
        await websocket.close(code=1011)
        return

    async def websocket_to_vnc() -> None:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is None and message.get("text") is not None:
                data = str(message["text"]).encode("latin-1")
            if data:
                writer.write(data)
                await writer.drain()

    async def vnc_to_websocket() -> None:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            await websocket.send_bytes(data)

    tasks = [
        asyncio.create_task(websocket_to_vnc()),
        asyncio.create_task(vnc_to_websocket()),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
