from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import time
from typing import Any
from urllib.request import urlopen

from darkweb_collector.migration_api import (
    _read_state,
    _target_database_urls,
    _target_fingerprint,
    update_job,
)
from darkweb_collector.migration_bundle import (
    SCHEMA_VERSION,
    activate_import,
    migration_operation_lock,
    restore_previous_active,
    validate_active_schema,
    validate_postgres_schema,
)
from darkweb_collector.runtime import project_root


ACTIVE_RELEASE_OVERRIDE_KEYS = (
    "DARKWEB_COLLECTOR_DATABASE_URL",
    "DARKWEB_COLLECTOR_DATABASE_SCHEMA",
    "DARKWEB_COLLECTOR_OUTPUT_ROOT",
    "DARKWEB_COLLECTOR_SCHEMA_FINGERPRINT",
    "DARKWEB_COLLECTOR_SCHEMA_VERSION",
)


def _run(command: list[str], timeout: int = 600) -> None:
    subprocess.run(command, check=True, timeout=timeout)


def _launcher_commands() -> tuple[list[str], list[str]]:
    collector_root = project_root()
    if os.name == "nt":
        launcher = collector_root / "scripts" / "start_all_services_windows.ps1"
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("找不到 PowerShell")
        base = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher)]
        return [*base, "stop"], [*base, "start"]
    launcher = collector_root / "scripts" / "start_all_services_wsl.sh"
    return ["bash", str(launcher), "stop"], ["bash", str(launcher), "start"]


def _runtime_api_port() -> int:
    collector_root = project_root()
    if os.name == "nt":
        try:
            payload = json.loads(
                (collector_root / ".runtime" / "windows" / "ports.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            return int(payload["api_port"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
    else:
        try:
            for line in (
                collector_root / ".runtime" / "wsl" / "ports.env"
            ).read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key == "API_PORT":
                    return int(value.strip().strip("'\""))
        except (OSError, ValueError):
            pass
    return int(os.environ.get("DARKWEB_API_PORT", "8000"))


def _health_database(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("database")
    return nested if isinstance(nested, dict) else payload


def _api_ready(expected_schema: str, timeout_seconds: int = 90) -> dict[str, Any] | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        port = _runtime_api_port()
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                raise RuntimeError("API health 状态不是 ok")
            database = _health_database(payload)
            engine = str(
                database.get("database_engine")
                or database.get("engine")
                or payload.get("database_engine")
                or ""
            ).lower()
            schema = str(
                database.get("database_schema")
                or database.get("schema")
                or payload.get("database_schema")
                or ""
            )
            version = str(
                database.get("schema_version")
                or payload.get("schema_version")
                or ""
            )
            ready = database.get("database_ready", database.get("healthy"))
            if engine != "postgresql" or schema != expected_schema or version != SCHEMA_VERSION:
                raise RuntimeError("API health 未指向预期 PostgreSQL Schema")
            if ready is not True:
                raise RuntimeError("API health 未确认数据库可用")
            return payload
        except Exception:
            pass
        time.sleep(2)
    return None


def _database_ready(runtime_database_url: str, report: dict[str, Any], *, canary: bool) -> dict[str, Any]:
    return validate_postgres_schema(
        runtime_database_url,
        str(report["database_schema"]),
        expected_fingerprint=str(report["schema_fingerprint"]),
        run_canary=canary,
    )


def run(job_id: str) -> int:
    stop_command, start_command = _launcher_commands()
    state = _read_state(job_id)
    report = state.get("report")
    if not isinstance(report, dict):
        update_job(
            job_id,
            status="failed",
            phase="failed",
            message="激活任务缺少导入报告，活动版本未改变",
        )
        return 1
    migration_url, runtime_url = _target_database_urls()
    if not migration_url or not runtime_url:
        update_job(
            job_id,
            status="failed",
            phase="failed",
            message="PostgreSQL 迁移账号或运行账号配置缺失，活动版本未改变",
        )
        return 1
    expected_target = str(state.get("target_database_fingerprint") or "")
    current_target = _target_fingerprint(migration_url, runtime_url)
    if not expected_target or not secrets.compare_digest(expected_target, current_target):
        update_job(
            job_id,
            status="failed",
            phase="failed",
            message="PostgreSQL 目标配置在控制器启动前发生变化，活动版本未改变",
        )
        return 1

    for key in ACTIVE_RELEASE_OVERRIDE_KEYS:
        os.environ.pop(key, None)

    stopped = False
    active_written = False
    try:
        with migration_operation_lock(migration_url):
            update_job(
                job_id,
                status="activating",
                phase="stopping",
                progress=10,
                message="正在停止 API、worker、scheduler 和 normalizer",
            )
            _run(stop_command)
            stopped = True

            update_job(
                job_id,
                status="activating",
                phase="canary",
                progress=35,
                message="服务已停止，正在执行目标 Schema 和事务回滚 canary",
            )
            pre_activation_health = _database_ready(runtime_url, report, canary=True)

            update_job(
                job_id,
                status="activating",
                phase="switching",
                progress=55,
                message="目标数据库已通过 canary，正在写入活动版本",
            )
            active = activate_import(report, runtime_url)
            active_written = True
            update_job(
                job_id,
                status="activating",
                phase="starting",
                progress=70,
                message="活动版本已写入，正在启动完整服务",
                active_release=active,
                pre_activation_health=pre_activation_health,
            )
            _run(start_command)
            stopped = False

            post_activation_health = validate_active_schema(run_canary=True)
            api_health = _api_ready(str(report["database_schema"]))
            if api_health is None:
                raise RuntimeError("切换后的 API 未通过强健康检查")
            update_job(
                job_id,
                status="active",
                phase="active",
                progress=100,
                message="迁移版本已激活，系统已使用 PostgreSQL 和新镜像目录",
                database_health=post_activation_health,
                api_health=api_health,
            )
            return 0
    except Exception as exc:
        try:
            if active_written:
                restore_previous_active(job_id)
            if not stopped:
                _run(stop_command)
                stopped = True
            _run(start_command)
            stopped = False
        except Exception as rollback_exc:
            update_job(
                job_id,
                status="rollback_failed",
                phase="rollback_failed",
                message=f"激活失败且自动回退失败：{exc}; {rollback_exc}",
            )
            return 2
        update_job(
            job_id,
            status="rolled_back",
            phase="rolled_back",
            progress=100,
            message=(
                f"激活失败，已恢复原活动版本：{exc}"
                if active_written
                else f"激活前检查失败，活动版本未改变且旧服务已恢复：{exc}"
            ),
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    return run(args.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
