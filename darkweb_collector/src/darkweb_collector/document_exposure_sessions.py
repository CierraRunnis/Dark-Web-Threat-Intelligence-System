from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any

from darkweb_collector.db import (
    delete_platform_session,
    get_db_connection,
    upsert_platform_session,
)
from darkweb_collector.document_exposure_platforms import (
    get_exposure_platform,
    list_exposure_platforms,
    list_session_manageable_platforms,
)
from darkweb_collector.runtime import output_root


LOGIN_WORKER_MODULE = "darkweb_collector.platform_session_login"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def platform_session_root() -> Path:
    path = output_root() / "platform_sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def platform_profile_dir(platform: str) -> Path:
    root = platform_session_root() / str(platform).strip()
    root.mkdir(parents=True, exist_ok=True)
    return root


def platform_storage_state_path(platform: str) -> Path:
    return platform_profile_dir(platform) / "storage_state.json"


def platform_user_data_dir(platform: str) -> Path:
    return platform_profile_dir(platform) / "user_data"


def platform_login_log_path(platform: str) -> Path:
    return platform_profile_dir(platform) / "login.log"


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dump_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _platform_metadata_payload(platform: str, row: dict[str, Any] | None) -> dict[str, Any]:
    meta = _load_json_file(platform_profile_dir(platform) / "launch_meta.json")
    if row and row.get("metadata_json"):
        try:
            saved = json.loads(str(row.get("metadata_json") or "{}"))
        except Exception:
            saved = {}
        if isinstance(saved, dict):
            meta = {**saved, **meta}
    return meta


def _pid_from_metadata(metadata: dict[str, Any]) -> int | None:
    try:
        pid = int(metadata.get("login_pid") or 0)
    except Exception:
        return None
    return pid if pid > 0 else None


def _is_process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in str(result.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _terminate_login_process(pid: int | None) -> None:
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _pid_from_metadata(metadata: dict[str, Any]) -> int | None:
    try:
        pid = int(metadata.get("login_pid") or 0)
    except Exception:
        return None
    return pid if pid > 0 else None


def _is_process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in str(completed.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _terminate_login_process(pid: int | None) -> None:
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def build_platform_session_payloads(
    *,
    manageable_only: bool = False,
    module: str | None = None,
) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = {str(row["platform"]): row for row in connection.execute(
            """
            SELECT id, platform, account_label, login_url, homepage_url, requires_login, status,
                   storage_state_path, last_verified_at, expires_hint, last_error, metadata_json, updated_at
            FROM platform_sessions
            """
        ).fetchall()}
    payloads: list[dict[str, Any]] = []
    platforms = (
        list_session_manageable_platforms(module=module)
        if manageable_only
        else list_exposure_platforms(module=module)
    )
    for platform in platforms:
        row = rows.get(platform.key)
        row_payload = dict(row) if row is not None else {}
        storage_path = platform_storage_state_path(platform.key)
        metadata = _platform_metadata_payload(platform.key, row_payload if row is not None else None)
        status = str(row_payload.get("status") or "")
        if status == "login_in_progress" and not _is_process_alive(_pid_from_metadata(metadata)):
            status = "configured" if storage_path.exists() else "not_configured"
        configured = storage_path.exists() or str(row_payload.get("status") or "") in {
            "configured",
            "valid",
            "invalid",
            "login_in_progress",
        }
        payloads.append(
            {
                "platform": platform.key,
                "label": platform.label,
                "module": platform.module,
                "platform_type": platform.platform_type,
                "homepage_url": platform.homepage_url,
                "login_url": platform.login_url,
                "requires_login": platform.requires_login,
                "configured": configured,
                "status": status or ("configured" if storage_path.exists() else "not_configured"),
                "account_label": str(row_payload.get("account_label") or ""),
                "storage_state_path": str(storage_path),
                "last_verified_at": str(row_payload.get("last_verified_at") or ""),
                "expires_hint": str(row_payload.get("expires_hint") or ""),
                "last_error": str(row_payload.get("last_error") or ""),
                "updated_at": str(row_payload.get("updated_at") or ""),
                "metadata": metadata,
            }
        )
    return payloads


def launch_platform_login(platform_name: str) -> dict[str, Any]:
    platform = get_exposure_platform(platform_name)
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:
        raise ValueError(f"playwright unavailable: {exc}") from exc
    profile_dir = platform_profile_dir(platform.key)
    user_data_dir = platform_user_data_dir(platform.key)
    storage_state_path = platform_storage_state_path(platform.key)
    log_path = platform_login_log_path(platform.key)
    launch_meta_path = profile_dir / "launch_meta.json"
    existing_meta = _load_json_file(launch_meta_path)
    existing_pid = _pid_from_metadata(existing_meta)
    if _is_process_alive(existing_pid):
        return {
            "platform": platform.key,
            "label": platform.label,
            "status": "login_in_progress",
            "pid": int(existing_pid),
            "log_path": str(log_path),
            "storage_state_path": str(storage_state_path),
            "user_data_dir": str(user_data_dir),
            "message": "已有登录窗口在运行，请直接在现有窗口中完成登录。",
        }
    command = [
        sys.executable,
        "-m",
        LOGIN_WORKER_MODULE,
        "--platform",
        platform.key,
        "--login-url",
        platform.login_url or platform.homepage_url,
        "--homepage-url",
        platform.homepage_url,
        "--user-data-dir",
        str(user_data_dir),
        "--storage-state",
        str(storage_state_path),
    ]
    log_handle = log_path.open("a", encoding="utf-8")
    src_dir = Path(__file__).resolve().parents[1]
    popen_kwargs: dict[str, Any] = {
        "cwd": str(src_dir),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
        "env": {
            **os.environ,
            "PYTHONPATH": str(src_dir),
        },
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, **popen_kwargs)
    metadata = {
        "login_pid": int(process.pid),
        "launch_command": command,
        "log_path": str(log_path),
        "user_data_dir": str(user_data_dir),
        "launched_at": _now_utc_iso(),
    }
    _dump_json_file(launch_meta_path, metadata)
    with get_db_connection() as connection:
        upsert_platform_session(
            connection,
            {
                "platform": platform.key,
                "account_label": "",
                "login_url": platform.login_url,
                "homepage_url": platform.homepage_url,
                "requires_login": platform.requires_login,
                "status": "login_in_progress",
                "storage_state_path": str(storage_state_path),
                "last_error": "",
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
                "updated_at": _now_utc_iso(),
            },
        )
        connection.commit()
    return {
        "platform": platform.key,
        "label": platform.label,
        "status": "login_in_progress",
        "pid": int(process.pid),
        "log_path": str(log_path),
        "storage_state_path": str(storage_state_path),
        "user_data_dir": str(user_data_dir),
        "message": "已启动可见浏览器登录会话，请在浏览器中完成登录后关闭窗口，再点击保存会话。",
    }


def verify_platform_session(platform_name: str) -> dict[str, Any]:
    platform = get_exposure_platform(platform_name)
    storage_state_path = platform_storage_state_path(platform.key)
    user_data_dir = platform_user_data_dir(platform.key)
    if not storage_state_path.exists() and not user_data_dir.exists():
        result = {
            "platform": platform.key,
            "status": "missing",
            "valid": False,
            "last_error": "session state file does not exist",
            "storage_state_path": str(storage_state_path),
        }
        with get_db_connection() as connection:
            upsert_platform_session(
                connection,
                {
                    "platform": platform.key,
                    "account_label": "",
                    "login_url": platform.login_url,
                    "homepage_url": platform.homepage_url,
                    "requires_login": platform.requires_login,
                    "status": "missing",
                    "storage_state_path": str(storage_state_path),
                    "last_error": result["last_error"],
                    "metadata_json": json.dumps({}, ensure_ascii=False),
                    "updated_at": _now_utc_iso(),
                },
            )
            connection.commit()
        return result

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - dependency/runtime specific
        metadata = _platform_metadata_payload(platform.key, None)
        metadata.update(
            {
                "validation_skipped": True,
                "validation_skip_reason": f"playwright unavailable: {exc}",
                "user_data_dir": str(user_data_dir),
            }
        )
        status = "configured" if storage_state_path.exists() or user_data_dir.exists() else "unavailable"
        result = {
            "platform": platform.key,
            "status": status,
            "valid": status == "configured",
            "last_error": "" if status == "configured" else f"playwright unavailable: {exc}",
            "storage_state_path": str(storage_state_path),
            "metadata": metadata,
        }
        with get_db_connection() as connection:
            existing_rows = [item for item in build_platform_session_payloads() if item["platform"] == platform.key]
            account_label = existing_rows[0]["account_label"] if existing_rows else ""
            upsert_platform_session(
                connection,
                {
                    "platform": platform.key,
                    "account_label": account_label,
                    "login_url": platform.login_url,
                    "homepage_url": platform.homepage_url,
                    "requires_login": platform.requires_login,
                    "status": status,
                    "storage_state_path": str(storage_state_path),
                    "last_error": result["last_error"],
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                    "updated_at": _now_utc_iso(),
                },
            )
            connection.commit()
        return result

    html = ""
    current_url = platform.homepage_url
    last_error = ""
    valid = False
    with sync_playwright() as playwright:  # pragma: no cover - browser runtime
        browser = playwright.chromium.launch(headless=True)
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1440, "height": 960},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
        }
        if storage_state_path.exists():
            context_kwargs["storage_state"] = str(storage_state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        try:
            page.goto(platform.homepage_url or platform.login_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            html = page.content()
            current_url = page.url
            lowered = html.lower()
            login_hits = sum(1 for token in platform.login_indicators if token.lower() in lowered or token.lower() in current_url.lower())
            success_hits = sum(1 for token in platform.success_indicators if token.lower() in lowered or token.lower() in current_url.lower())
            valid = success_hits > 0
            if not valid and platform.requires_login:
                last_error = "session appears to require login again"
        finally:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass
            context.close()
            browser.close()

    status = "valid" if valid else "invalid"
    updated_at = _now_utc_iso()
    metadata = _platform_metadata_payload(platform.key, None)
    metadata.update(
        {
            "last_verified_url": current_url,
            "verification_excerpt": html[:500],
            "user_data_dir": str(user_data_dir),
        }
    )
    with get_db_connection() as connection:
        existing_rows = [item for item in build_platform_session_payloads() if item["platform"] == platform.key]
        account_label = existing_rows[0]["account_label"] if existing_rows else ""
        upsert_platform_session(
            connection,
            {
                "platform": platform.key,
                "account_label": account_label,
                "login_url": platform.login_url,
                "homepage_url": platform.homepage_url,
                "requires_login": platform.requires_login,
                "status": status,
                "storage_state_path": str(storage_state_path),
                "last_verified_at": updated_at,
                "last_error": last_error,
                "metadata_json": json.dumps(metadata, ensure_ascii=False),
                "updated_at": updated_at,
            },
        )
        connection.commit()
    return {
        "platform": platform.key,
        "status": status,
        "valid": valid,
        "last_error": last_error,
        "storage_state_path": str(storage_state_path),
        "last_verified_at": updated_at,
        "metadata": metadata,
    }


def save_platform_session(platform_name: str, account_label: str = "") -> dict[str, Any]:
    verification = verify_platform_session(platform_name)
    platform = get_exposure_platform(platform_name)
    normalized_account_label = _normalize_text(account_label)
    with get_db_connection() as connection:
        upsert_platform_session(
            connection,
            {
                "platform": platform.key,
                "account_label": normalized_account_label,
                "login_url": platform.login_url,
                "homepage_url": platform.homepage_url,
                "requires_login": platform.requires_login,
                "status": verification["status"],
                "storage_state_path": verification["storage_state_path"],
                "last_verified_at": verification.get("last_verified_at"),
                "last_error": verification.get("last_error") or "",
                "metadata_json": json.dumps(verification.get("metadata") or {}, ensure_ascii=False),
                "updated_at": _now_utc_iso(),
            },
        )
        connection.commit()
    metadata = _load_json_file(platform_profile_dir(platform.key) / "launch_meta.json")
    _terminate_login_process(_pid_from_metadata(metadata))
    return {
        **verification,
        "account_label": normalized_account_label,
    }


def remove_platform_session(platform_name: str) -> dict[str, Any]:
    platform = get_exposure_platform(platform_name)
    storage_state_path = platform_storage_state_path(platform.key)
    user_data_dir = platform_user_data_dir(platform.key)
    metadata = _load_json_file(platform_profile_dir(platform.key) / "launch_meta.json")
    _terminate_login_process(_pid_from_metadata(metadata))
    for path in (storage_state_path, platform_login_log_path(platform.key), platform_profile_dir(platform.key) / "launch_meta.json"):
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    if user_data_dir.exists():
        for child in sorted(user_data_dir.rglob("*"), reverse=True):
            try:
                if child.is_file():
                    child.unlink()
                else:
                    child.rmdir()
            except Exception:
                pass
        try:
            user_data_dir.rmdir()
        except Exception:
            pass
    with get_db_connection() as connection:
        delete_platform_session(connection, platform.key)
        connection.commit()
    return {
        "platform": platform.key,
        "removed": True,
        "storage_state_path": str(storage_state_path),
    }
