#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Iterable

from darkweb_collector.migration_bundle import MigrationBundleError, export_bundle


SERVICE_MARKERS = (
    "darkweb_collector.api_app",
    "darkweb_collector.normalizer_service",
    "darkweb_collector.tasks",
    "darkweb_collector.celery_app:app",
    "serve_api.py",
    "run_worker.py",
    "run_scheduler.py",
    "run_normalizer.py",
    "scripts/crawl.py worker",
    "scripts/crawl.py enqueue-due",
    "scripts/crawl.py sync-public-vulns",
    "scripts/crawl.py normalizer",
    "celery worker",
    "celery beat",
    "uvicorn",
)


def _linux_processes() -> Iterable[tuple[int, str]]:
    proc = Path("/proc")
    if not proc.is_dir():
        return
    excluded = {os.getpid(), os.getppid()}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in excluded:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if command:
            yield pid, command


def _windows_processes() -> Iterable[tuple[int, str]]:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_Process | "
            "ForEach-Object { '{0}|{1}' -f $_.ProcessId,$_.CommandLine }"
        ),
    ]
    try:
        output = subprocess.check_output(command, text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return
    excluded = {os.getpid(), os.getppid()}
    for line in output.splitlines():
        raw_pid, separator, cmdline = line.partition("|")
        if not separator:
            continue
        try:
            pid = int(raw_pid)
        except ValueError:
            continue
        if pid not in excluded and cmdline:
            yield pid, cmdline


def running_writer_services() -> list[dict[str, object]]:
    processes = _windows_processes() if os.name == "nt" else _linux_processes()
    found = []
    for pid, command in processes:
        lowered = command.lower()
        markers = sorted(marker for marker in SERVICE_MARKERS if marker in lowered)
        if markers:
            found.append({"pid": pid, "markers": markers, "command": command[:500]})
    return found


def assert_sqlite_exclusive(database_path: Path) -> None:
    connection = sqlite3.connect(database_path, timeout=0, isolation_level=None)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("ROLLBACK")
    except sqlite3.OperationalError as exc:
        raise MigrationBundleError("SQLite 当前仍被写入或锁定，请停止全部服务后重试") from exc
    finally:
        connection.close()


def assert_services_stopped(database_path: Path) -> None:
    running = running_writer_services()
    if running:
        rendered = ", ".join(
            f"pid={item['pid']} ({'/'.join(item['markers'])})" for item in running[:10]
        )
        raise MigrationBundleError(
            "检测到仍在运行的 API、worker、scheduler 或 normalizer：" + rendered
        )
    assert_sqlite_exclusive(database_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="停止服务后，把活动 SQLite 数据库和完整 output 目录导出为 .dwti"
    )
    parser.add_argument("--database", required=True, type=Path, help="活动 collector.db")
    parser.add_argument("--artifacts", required=True, type=Path, help="完整 output 证据目录")
    parser.add_argument("--output", required=True, type=Path, help="新建的 .dwti 文件")
    args = parser.parse_args()

    database = args.database.expanduser().resolve(strict=True)
    artifacts = args.artifacts.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".dwti":
        parser.error("--output 必须以 .dwti 结尾")
    try:
        assert_services_stopped(database)

        def progress(phase: str, percent: int, message: str) -> None:
            print(f"[{percent:3d}%] {phase}: {message}", file=sys.stderr, flush=True)

        report = export_bundle(
            database,
            artifacts,
            output,
            progress=progress,
            upgrade_schema=True,
        )
    except (MigrationBundleError, OSError, sqlite3.Error) as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
