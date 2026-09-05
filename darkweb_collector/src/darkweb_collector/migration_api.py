from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlsplit
import uuid

from fastapi import APIRouter, HTTPException, Request

from darkweb_collector.migration_bundle import (
    DEFAULT_MAX_BUNDLE_BYTES,
    PERFORMANCE_READ_SCENARIOS,
    MigrationBundleError,
    benchmark_required,
    exclusive_file_lock,
    import_bundle,
    migration_root,
    performance_acceptance_passed,
    public_active_release,
    record_performance_acceptance,
)
from darkweb_collector.runtime import user_data_root


router = APIRouter(prefix="/api/migrations", tags=["database-migrations"])
_state_lock = Lock()
_activation_lock = Lock()


def _target_config_path() -> Path:
    override = os.environ.get("DARKWEB_POSTGRESQL_TARGET_CONFIG", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return user_data_root() / "postgresql-target.json"


def _load_target_config() -> dict[str, Any]:
    try:
        payload = json.loads(_target_config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as exc:
        raise MigrationBundleError("PostgreSQL 目标配置损坏") from exc
    if not isinstance(payload, dict) or payload.get("format") not in {1, 2}:
        raise MigrationBundleError("PostgreSQL 目标配置格式无效")
    return payload


def _target_database_urls() -> tuple[str, str]:
    config = _load_target_config()
    migration_url = (
        os.environ.get("DARKWEB_MIGRATION_TARGET_DATABASE_URL", "").strip()
        or str(config.get("migration_database_url") or "").strip()
    )
    runtime_url = (
        os.environ.get("DARKWEB_MIGRATION_RUNTIME_DATABASE_URL", "").strip()
        or str(config.get("runtime_database_url") or "").strip()
    )
    return migration_url, runtime_url


def _url_summary(database_url: str) -> dict[str, Any]:
    if not database_url:
        return {"configured": False}
    try:
        parsed = urlsplit(database_url)
        port = parsed.port or 5432
    except ValueError:
        return {"configured": False, "error": "PostgreSQL URL 无效"}
    configured = parsed.scheme.lower() in {"postgres", "postgresql"} and bool(
        parsed.hostname and parsed.path.lstrip("/") and parsed.username
    )
    return {
        "configured": configured,
        "host": parsed.hostname or "",
        "port": port,
        "database": parsed.path.lstrip("/"),
        "role": unquote(parsed.username or ""),
    }


def _target_summary() -> dict[str, Any]:
    migration_url, runtime_url = _target_database_urls()
    migration = _url_summary(migration_url)
    runtime = _url_summary(runtime_url)
    error = ""
    if migration.get("configured") and runtime.get("configured"):
        if migration.get("role") == runtime.get("role"):
            error = "迁移账号与运行账号必须分离"
    configured = bool(migration.get("configured") and runtime.get("configured") and not error)
    return {
        "configured": configured,
        "migration": migration,
        "runtime": runtime,
        **({"error": error} if error else {}),
    }


def _target_fingerprint(migration_url: str, runtime_url: str) -> str:
    return hashlib.sha256((migration_url + "\0" + runtime_url).encode("utf-8")).hexdigest()


def _require_admin(request: Request) -> None:
    if os.environ.get("DARKWEB_API_AUTH_DISABLED") == "1":
        return
    current = getattr(request.state, "current_user", {}) or {}
    role = str(current.get("role") or "").strip().lower()
    if role != "admin":
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


def _atomic_state(job_id: str, payload: dict[str, Any]) -> None:
    root = _job_root(job_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "state.json"
    temporary = path.with_name(f"state.json.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def _write_state(job_id: str, payload: dict[str, Any]) -> None:
    with _state_lock:
        with exclusive_file_lock(migration_root() / ".state.lock", blocking=True):
            _atomic_state(job_id, payload)


def update_job(job_id: str, **changes: Any) -> dict[str, Any]:
    with _state_lock:
        with exclusive_file_lock(migration_root() / ".state.lock", blocking=True):
            state = _read_state(job_id)
            state.update(changes)
            _atomic_state(job_id, state)
    return state


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    public = dict(state)
    for key in (
        "bundle_path",
        "target_database_url",
        "runtime_database_url",
        "target_database_fingerprint",
    ):
        public.pop(key, None)
    return public


def _phase_status(phase: str) -> str:
    return {
        "preflight": "preflight",
        "artifacts": "importing",
        "database": "importing",
        "verify": "verifying",
        "analyzing": "analyzing",
        "ready": "ready",
    }.get(phase, "importing")


def _run_import(job_id: str) -> int:
    try:
        state = _read_state(job_id)
        migration_url, runtime_url = _target_database_urls()
        if not migration_url or not runtime_url:
            raise MigrationBundleError("未配置独立的 PostgreSQL 迁移账号和运行账号 URL")

        def report_progress(phase: str, progress: int, message: str) -> None:
            update_job(
                job_id,
                status=_phase_status(phase),
                phase=phase,
                progress=progress,
                message=message,
            )

        report = import_bundle(
            Path(state["bundle_path"]),
            migration_url,
            job_id,
            runtime_database_url=runtime_url,
            progress=report_progress,
        )
        waiting = report.get("status") == "analyzing"
        update_job(
            job_id,
            status="analyzing" if waiting else "ready",
            phase="analyzing" if waiting else "ready",
            progress=99 if waiting else 100,
            message=(
                "数据、镜像、Schema 和 canary 已通过；等待性能与语义一致性报告"
                if waiting
                else "数据库和镜像文件已导入并通过校验，等待确认切换"
            ),
            report=report,
            target_database_fingerprint=_target_fingerprint(migration_url, runtime_url),
            worker_completed_at=report.get("verified_at"),
        )
        return 0
    except Exception as exc:
        try:
            update_job(
                job_id,
                status="failed",
                phase="failed",
                message=str(exc),
                error_type=type(exc).__name__,
            )
        except Exception:
            pass
        return 1


def _spawn_module(job_id: str, argument: str, log_name: str) -> int:
    job_root = _job_root(job_id)
    log_path = job_root / log_name
    command = [
        sys.executable,
        "-m",
        "darkweb_collector.migration_api"
        if argument == "--run-import"
        else "darkweb_collector.migration_controller",
        argument,
        job_id,
    ]
    kwargs: dict[str, Any] = {"cwd": str(Path(__file__).resolve().parents[2])}
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            **kwargs,
        )
    return int(process.pid)


def _spawn_import_worker(job_id: str) -> int:
    return _spawn_module(job_id, "--run-import", "import.log")


def _spawn_restart_controller(job_id: str) -> int:
    if os.environ.get("DARKWEB_MIGRATION_AUTO_RESTART", "1") == "0":
        raise MigrationBundleError("已禁用自动重启，不能执行受控激活")
    return _spawn_module(job_id, "--job-id", "restart.log")


@router.get("/config")
def migration_config(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return {
        "target": _target_summary(),
        "active_release": public_active_release(),
        "max_bundle_bytes": int(
            os.environ.get("DARKWEB_MIGRATION_MAX_BUNDLE_BYTES", DEFAULT_MAX_BUNDLE_BYTES)
        ),
        "auto_restart": os.environ.get("DARKWEB_MIGRATION_AUTO_RESTART", "1") != "0",
        "benchmark_required": benchmark_required(),
        "performance_contract": {
            "read_scenarios": sorted(PERFORMANCE_READ_SCENARIOS),
            "concurrency": [1, 8],
            "concurrency_8_read_p95_ratio_max": 0.80,
            "concurrency_1_read_p95_ratio_max": 1.10,
            "write_model": "business_supercycle_v2",
            "write_report_version": 2,
            "write_rounds_per_backend": 3,
            "write_throughput_ratio_min": 2.0,
            "write_measured_cycles_min": 800,
            "write_transactions_min": 800,
            "errors": 0,
            "semantic_equivalence": True,
        },
    }


@router.get("")
def migration_jobs(request: Request) -> dict[str, Any]:
    _require_admin(request)
    jobs_root = migration_root() / "jobs"
    states = []
    if jobs_root.exists():
        paths = list(jobs_root.glob("*/state.json"))
        paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        for path in paths[:20]:
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
    target = _target_summary()
    if not target.get("configured"):
        raise HTTPException(status_code=409, detail=target.get("error") or "尚未配置目标 PostgreSQL")
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
        with bundle_path.open("xb") as target_file:
            async for chunk in request.stream():
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="迁移包超过允许大小")
                target_file.write(chunk)
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
    try:
        worker_pid = _spawn_import_worker(job_id)
        state = update_job(job_id, worker_pid=worker_pid)
    except Exception as exc:
        state = update_job(
            job_id,
            status="failed",
            phase="failed",
            message=f"启动迁移子进程失败：{exc}",
            error_type=type(exc).__name__,
        )
    return _public_state(state)


@router.get("/{job_id}")
def migration_job(job_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        return _public_state(_read_state(job_id))
    except MigrationBundleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{job_id}/performance")
async def submit_performance_report(job_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        state = _read_state(job_id)
        if state.get("status") != "analyzing" or not isinstance(state.get("report"), dict):
            raise MigrationBundleError("只有等待性能验收的迁移任务可以提交报告")
        try:
            payload = await request.json()
        except (ValueError, TypeError) as exc:
            raise MigrationBundleError("性能报告不是有效 JSON") from exc
        report = record_performance_acceptance(state["report"], payload)
        updated = update_job(
            job_id,
            status="ready",
            phase="ready",
            progress=100,
            message="性能、语义、数据库和镜像校验全部通过，等待确认切换",
            report=report,
        )
        return _public_state(updated)
    except MigrationBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/activate", status_code=202)
def activate_migration(job_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        with _activation_lock:
            state = _read_state(job_id)
            if state.get("status") != "ready" or not isinstance(state.get("report"), dict):
                raise MigrationBundleError("只有已通过全部验收的迁移任务可以激活")
            acceptance = state["report"].get("performance_acceptance")
            if not performance_acceptance_passed(acceptance):
                raise MigrationBundleError("迁移任务尚未通过性能与语义一致性验收")
            migration_url, runtime_url = _target_database_urls()
            if not migration_url or not runtime_url:
                raise MigrationBundleError("目标 PostgreSQL 配置已丢失")
            expected_target = str(state.get("target_database_fingerprint") or "")
            current_target = _target_fingerprint(migration_url, runtime_url)
            if not expected_target or not secrets.compare_digest(expected_target, current_target):
                raise MigrationBundleError("目标 PostgreSQL 配置已改变，请重新导入迁移包")
            update_job(
                job_id,
                status="activating",
                phase="activating",
                progress=0,
                message="正在启动受控切换进程；尚未修改活动版本",
            )
            try:
                controller_pid = _spawn_restart_controller(job_id)
            except Exception:
                update_job(
                    job_id,
                    status="ready",
                    phase="ready",
                    progress=100,
                    message="切换控制器未启动，活动版本未改变",
                )
                raise
            updated = update_job(
                job_id,
                controller_pid=controller_pid,
                message="切换控制器已启动，正在停止服务并执行激活",
            )
        return _public_state(updated)
    except MigrationBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-import", metavar="JOB_ID")
    args = parser.parse_args()
    if args.run_import:
        return _run_import(args.run_import)
    parser.error("--run-import is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
