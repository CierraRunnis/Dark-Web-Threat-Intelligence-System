from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

from darkweb_collector.migration_api import update_job
from darkweb_collector.migration_bundle import restore_previous_active
from darkweb_collector.db import get_db_connection
from darkweb_collector.runtime import project_root


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
            payload = json.loads((collector_root / ".runtime" / "windows" / "ports.json").read_text(encoding="utf-8-sig"))
            return int(payload["api_port"])
        except (OSError, ValueError, TypeError, KeyError):
            pass
    else:
        try:
            for line in (collector_root / ".runtime" / "wsl" / "ports.env").read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if separator and key == "API_PORT":
                    return int(value.strip().strip("'\""))
        except (OSError, ValueError):
            pass
    return int(os.environ.get("DARKWEB_API_PORT", "8000"))


def _api_ready(timeout_seconds: int = 90) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        port = _runtime_api_port()
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
                payload = json.load(response)
            if payload.get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def _database_ready() -> None:
    with get_db_connection() as connection:
        connection.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()


def run(job_id: str) -> int:
    stop_command, start_command = _launcher_commands()
    time.sleep(2)
    try:
        _run(stop_command)
        _run(start_command)
        _database_ready()
        if not _api_ready():
            raise RuntimeError("切换后的 API 未通过健康检查")
        update_job(
            job_id,
            status="active",
            phase="complete",
            progress=100,
            message="迁移版本已激活，系统已使用 PostgreSQL 和新镜像目录",
        )
        return 0
    except Exception as exc:
        try:
            restore_previous_active(job_id)
            _run(stop_command)
            _run(start_command)
        except Exception as rollback_exc:
            update_job(
                job_id,
                status="rollback_failed",
                phase="failed",
                message=f"激活失败且自动回退失败：{exc}; {rollback_exc}",
            )
            return 2
        update_job(
            job_id,
            status="rolled_back",
            phase="failed",
            message=f"激活失败，已恢复原活动版本：{exc}",
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    return run(args.job_id)


if __name__ == "__main__":
    raise SystemExit(main())
