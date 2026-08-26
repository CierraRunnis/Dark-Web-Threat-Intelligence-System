from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from threading import Lock, Thread
from typing import Any
from urllib.parse import unquote, urlsplit
import uuid

from fastapi import APIRouter, HTTPException, Request

from darkweb_collector.migration_bundle import (
    DEFAULT_MAX_BUNDLE_BYTES,
    MigrationBundleError,
    activate_import,
    import_bundle,
    migration_root,
    public_active_release,
    restore_previous_active,
)
from darkweb_collector.storage_paths import storage_summary


router = APIRouter(prefix="/api/migrations", tags=["database-migrations"])
_state_lock = Lock()
_activation_lock = Lock()


def _target_database_url() -> str:
    return os.environ.get("DARKWEB_MIGRATION_TARGET_DATABASE_URL", "").strip()


def _target_summary() -> dict[str, Any]:
    database_url = _target_database_url()
    if not database_url:
        return {"configured": False}
    try:
        parsed = urlsplit(database_url)
    except ValueError:
        return {"configured": False, "error": "目标 PostgreSQL URL 无效"}
    return {
        "configured": parsed.scheme.lower() in {"postgres", "postgresql"},
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/"),
    }


def _require_admin(request: Request) -> None:
    if os.environ.get("DARKWEB_API_AUTH_DISABLED") == "1":
        return
    current = getattr(request.state, "current_user", {}) or {}
    username = str(current.get("username") or "")
    expected = os.environ.get("DARKWEB_AUTH_USERNAME", "admin")
    if username != expected:
        raise HTTPException(status_code=403, detail="仅管理员可以执行数据迁移")


def _job_root(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise MigrationBundleError("迁移任务编号无效")
    return migration_root() / "jobs" / job_id


def _state_path(job_id: str) -> Path:
    return _job_root(job_id) / "state.json"


def _read_state(job_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(_state_path(job_id).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationBundleError("迁移任务不存在") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise MigrationBundleError("迁移任务状态损坏") from exc
    if not isinstance(payload, dict):
        raise MigrationBundleError("迁移任务状态损坏")
    return payload


def _write_state(job_id: str, payload: dict[str, Any]) -> None:
    root = _job_root(job_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "state.json"
    temporary = path.with_name("state.json.tmp")
    with _state_lock:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def update_job(job_id: str, **changes: Any) -> dict[str, Any]:
    with _state_lock:
        state = _read_state(job_id)
        state.update(changes)
        path = _state_path(job_id)
        temporary = path.with_name("state.json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    return state


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    public = dict(state)
    public.pop("bundle_path", None)
    public.pop("target_database_url", None)
    public.pop("target_database_fingerprint", None)
    return public


def _run_import(job_id: str) -> None:
    try:
        state = _read_state(job_id)
        database_url = _target_database_url()
        if not database_url:
            raise MigrationBundleError("未配置 DARKWEB_MIGRATION_TARGET_DATABASE_URL")

        def report_progress(phase: str, progress: int, message: str) -> None:
            update_job(job_id, status="preparing", phase=phase, progress=progress, message=message)

        report = import_bundle(
            Path(state["bundle_path"]),
            database_url,
            job_id,
            progress=report_progress,
        )
        update_job(
            job_id,
            status="ready",
            phase="ready",
            progress=100,
            message="数据库和镜像文件已导入并通过校验，等待确认切换",
            report=report,
            target_database_fingerprint=hashlib.sha256(database_url.encode("utf-8")).hexdigest(),
        )
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            phase="failed",
            message=str(exc),
            error_type=type(exc).__name__,
        )


def _spawn_restart_controller(job_id: str) -> int | None:
    if os.environ.get("DARKWEB_MIGRATION_AUTO_RESTART", "1") == "0":
        return None
    job_root = _job_root(job_id)
    log_path = job_root / "restart.log"
    command = [
        sys.executable,
        "-m",
        "darkweb_collector.migration_controller",
        "--job-id",
        job_id,
    ]
    flags = 0
    kwargs: dict[str, Any] = {"cwd": str(Path(__file__).resolve().parents[2])}
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    with log_path.open("ab") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **kwargs)
    return int(process.pid)


@router.get("/config")
def migration_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    active_release = public_active_release()
    return {
        "target": _target_summary(),
        "active_release": active_release,
        "storage": storage_summary(active_release),
        "max_bundle_bytes": int(
            os.environ.get("DARKWEB_MIGRATION_MAX_BUNDLE_BYTES", DEFAULT_MAX_BUNDLE_BYTES)
        ),
        "auto_restart": os.environ.get("DARKWEB_MIGRATION_AUTO_RESTART", "1") != "0",
    }


@router.get("")
def migration_jobs(request: Request) -> dict[str, Any]:
    _require_admin(request)
    jobs_root = migration_root() / "jobs"
    states = []
    if jobs_root.exists():
        for path in sorted(jobs_root.glob("*/state.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:20]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict):
                states.append(_public_state(payload))
    return {"items": states}


@router.post("/upload", status_code=202)
async def upload_migration_bundle(request: Request) -> dict[str, Any]:
    _require_admin(request)
    if not _target_summary().get("configured"):
        raise HTTPException(status_code=409, detail="尚未配置目标 PostgreSQL")
    filename = Path(unquote(request.headers.get("x-dwti-filename", "migration.dwti"))).name
    if not filename.lower().endswith(".dwti"):
        raise HTTPException(status_code=400, detail="请选择 .dwti 迁移包")
    job_id = uuid.uuid4().hex
    root = _job_root(job_id)
    root.mkdir(parents=True)
    bundle_path = root / "upload.dwti"
    max_bytes = int(os.environ.get("DARKWEB_MIGRATION_MAX_BUNDLE_BYTES", DEFAULT_MAX_BUNDLE_BYTES))
    written = 0
    try:
        with bundle_path.open("xb") as target:
            async for chunk in request.stream():
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="迁移包超过允许大小")
                target.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="迁移包为空")
    except Exception:
        bundle_path.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
        raise
    state = {
        "job_id": job_id,
        "filename": filename,
        "bundle_bytes": written,
        "bundle_path": str(bundle_path),
        "status": "queued",
        "phase": "queued",
        "progress": 0,
        "message": "迁移包已上传，等待预检",
    }
    _write_state(job_id, state)
    Thread(target=_run_import, args=(job_id,), name=f"migration-{job_id[:8]}", daemon=True).start()
    return _public_state(state)


@router.get("/{job_id}")
def migration_job(job_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        return _public_state(_read_state(job_id))
    except MigrationBundleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{job_id}/activate", status_code=202)
def activate_migration(job_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        with _activation_lock:
            state = _read_state(job_id)
            if state.get("status") != "ready" or not isinstance(state.get("report"), dict):
                raise MigrationBundleError("只有已通过校验的迁移任务可以激活")
            database_url = _target_database_url()
            if not database_url:
                raise MigrationBundleError("目标 PostgreSQL 配置已丢失")
            expected_target = str(state.get("target_database_fingerprint") or "")
            current_target = hashlib.sha256(database_url.encode("utf-8")).hexdigest()
            if not expected_target or not secrets.compare_digest(expected_target, current_target):
                raise MigrationBundleError("目标 PostgreSQL 配置已改变，请重新导入迁移包")
            active = activate_import(state["report"], database_url)
            try:
                controller_pid = _spawn_restart_controller(job_id)
            except Exception as exc:
                restore_previous_active(job_id)
                update_job(
                    job_id,
                    status="failed",
                    phase="failed",
                    message=f"启动切换控制器失败，已恢复原活动版本：{exc}",
                )
                raise MigrationBundleError("启动切换控制器失败，已恢复原活动版本") from exc
            status = "activating" if controller_pid else "restart_required"
            updated = update_job(
                job_id,
                status=status,
                phase="activate",
                message="活动版本已切换，正在重启系统" if controller_pid else "活动版本已切换，请重启系统",
                active_release=active,
                controller_pid=controller_pid,
            )
        return _public_state(updated)
    except MigrationBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
