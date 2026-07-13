from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

ACTIVE_STATUSES = {"queued", "running"}
UPDATE_BRANCH = "main"
UPDATE_REMOTE = "origin"
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
REMOTE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SelfUpdateError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _state_dir() -> Path:
    configured = os.environ.get("DARKWEB_UPDATE_STATE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", "").strip() or Path.home() / "AppData" / "Local")
        return base / "DarkWebThreatIntel"
    base = Path(os.environ.get("XDG_STATE_HOME", "").strip() or Path.home() / ".local" / "state")
    return base / "darkweb-threat-intel"


def _state_path() -> Path:
    return _state_dir() / "update-status.json"


def _log_path() -> Path:
    return _state_dir() / "update.log"


def _idle_status() -> dict[str, Any]:
    return {
        "status": "idle",
        "stage": "idle",
        "message": "尚未执行更新",
        "updated": False,
        "restart_required": False,
    }


def read_update_status() -> dict[str, Any]:
    path = _state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _idle_status()
    return payload if isinstance(payload, dict) else _idle_status()


def read_public_update_status() -> dict[str, Any]:
    payload = read_update_status().copy()
    payload.pop("log_path", None)
    return payload


def _write_update_status(payload: dict[str, Any]) -> dict[str, Any]:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "updated_at": _now_iso()}
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary_path, path)
    return payload


def _process_running(pid: object) -> bool:
    try:
        process_id = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if process_id <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _validate_branch(branch: str) -> str:
    value = str(branch or "").strip()
    if (
        not BRANCH_PATTERN.fullmatch(value)
        or ".." in value
        or "@{" in value
        or value.endswith("/")
        or value.endswith(".")
        or "//" in value
    ):
        raise SelfUpdateError("更新分支名称无效")
    return value


def _validate_remote(remote: str) -> str:
    value = str(remote or "").strip()
    if not REMOTE_PATTERN.fullmatch(value):
        raise SelfUpdateError("Git 远端名称无效")
    return value


def _run_git(
    project_root: Path,
    *arguments: str,
    check: bool = True,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SelfUpdateError(f"Git 命令执行失败：{exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SelfUpdateError(detail or f"Git 命令失败：{' '.join(arguments)}")
    return result


def _ensure_update_ready(project_root: Path, branch: str, remote: str) -> None:
    if os.environ.get("DARKWEB_SELF_UPDATE_ENABLED", "1") == "0":
        raise SelfUpdateError("在线更新已被 DARKWEB_SELF_UPDATE_ENABLED 禁用")
    if shutil.which("git") is None:
        raise SelfUpdateError("系统未安装 Git，无法执行在线更新")
    if not (project_root / ".git").exists():
        raise SelfUpdateError("当前安装不是 Git 工作副本，无法执行在线更新")
    _validate_branch(branch)
    _validate_remote(remote)
    if branch != UPDATE_BRANCH or remote != UPDATE_REMOTE:
        raise SelfUpdateError("在线更新目标固定为 origin/main")
    checkout_branch = _run_git(project_root, "branch", "--show-current").stdout.strip()
    if checkout_branch != UPDATE_BRANCH:
        raise SelfUpdateError("在线更新仅允许在 main 分支执行")
    dirty = _run_git(project_root, "status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        raise SelfUpdateError("项目存在未提交修改，请先提交或还原后再更新")


def apply_git_update(project_root: Path, branch: str, remote: str = "origin") -> dict[str, Any]:
    branch = _validate_branch(branch)
    remote = _validate_remote(remote)
    _ensure_update_ready(project_root, branch, remote)

    before = _run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    remote_ref = f"refs/remotes/{remote}/{branch}"
    refspec = f"refs/heads/{branch}:{remote_ref}"
    _run_git(project_root, "fetch", "--prune", remote, refspec, timeout=300)
    target = _run_git(project_root, "rev-parse", remote_ref).stdout.strip()
    if before == target:
        return {"updated": False, "before_commit": before, "after_commit": before}

    ancestor = _run_git(project_root, "merge-base", "--is-ancestor", before, target, check=False)
    if ancestor.returncode != 0:
        raise SelfUpdateError("远端历史与本地不一致，无法安全快进更新")

    _run_git(project_root, "merge", "--ff-only", target, timeout=300)
    after = _run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    return {"updated": True, "before_commit": before, "after_commit": after}


def _launcher_command(project_root: Path, action: str) -> list[str]:
    if os.name == "nt":
        script = project_root / "darkweb_collector" / "scripts" / "start_all_services_windows.ps1"
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell or not script.exists():
            raise SelfUpdateError("找不到 Windows 服务启动脚本或 PowerShell")
        return [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), action]

    script = project_root / "darkweb_collector" / "scripts" / "start_all_services_wsl.sh"
    bash = shutil.which("bash")
    if not bash or not script.exists():
        raise SelfUpdateError("找不到 Linux 服务启动脚本或 Bash")
    return [bash, str(script), action]


def _run_logged(command: list[str], project_root: Path, log: TextIO, timeout: int = 1800) -> None:
    log.write(f"\n[{_now_iso()}] $ {' '.join(command)}\n")
    log.flush()
    try:
        result = subprocess.run(
            command,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SelfUpdateError(f"更新命令执行失败：{exc}") from exc
    if result.returncode != 0:
        raise SelfUpdateError(f"更新命令退出码为 {result.returncode}，请查看自动更新日志")


def run_self_update(job_id: str, branch: str, remote: str = "origin", wait_seconds: float = 1.0) -> None:
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    project_root = _project_root()
    state = {
        "job_id": job_id,
        "pid": os.getpid(),
        "status": "running",
        "stage": "fetching",
        "message": f"正在获取 {remote}/{branch} 的最新代码",
        "branch": branch,
        "remote": remote,
        "updated": False,
        "restart_required": False,
        "started_at": _now_iso(),
        "log_path": str(_log_path()),
    }
    _write_update_status(state)

    try:
        result = apply_git_update(project_root, branch, remote)
        state.update(result)
        if not result["updated"]:
            state.update(
                status="completed",
                stage="completed",
                message="当前已经是最新版本",
                finished_at=_now_iso(),
            )
            _write_update_status(state)
            return

        _log_path().parent.mkdir(parents=True, exist_ok=True)
        with _log_path().open("a", encoding="utf-8") as log:
            state.update(stage="installing", message="代码已更新，正在同步运行环境")
            _write_update_status(state)
            _run_logged(_launcher_command(project_root, "install"), project_root, log)

            state.update(stage="restarting", message="环境已同步，正在重启服务", restart_required=True)
            _write_update_status(state)
            _run_logged(_launcher_command(project_root, "stop"), project_root, log)
            _run_logged(_launcher_command(project_root, "start"), project_root, log)

        state.update(
            status="completed",
            stage="completed",
            message="更新完成，服务已重新启动",
            finished_at=_now_iso(),
        )
        _write_update_status(state)
    except Exception as exc:
        state.update(
            status="failed",
            stage="failed",
            message="自动更新失败",
            error=str(exc),
            finished_at=_now_iso(),
        )
        _write_update_status(state)


def start_self_update() -> dict[str, Any]:
    branch = UPDATE_BRANCH
    remote = UPDATE_REMOTE

    existing = read_update_status()
    if existing.get("status") in ACTIVE_STATUSES and _process_running(existing.get("pid")):
        raise SelfUpdateError("已有更新任务正在执行")
    if existing.get("status") in ACTIVE_STATUSES:
        existing.update(status="failed", stage="failed", message="上一次更新进程已中止", error="更新进程意外退出")
        _write_update_status(existing)

    _ensure_update_ready(_project_root(), branch, remote)

    job_id = uuid.uuid4().hex
    state = _write_update_status(
        {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "message": "更新任务已启动",
            "branch": branch,
            "remote": remote,
            "updated": False,
            "restart_required": False,
            "started_at": _now_iso(),
            "log_path": str(_log_path()),
        }
    )

    helper = _project_root() / "darkweb_collector" / "scripts" / "run_self_update.py"
    command = [sys.executable, str(helper), "--job-id", job_id, "--branch", branch, "--remote", remote]
    kwargs: dict[str, Any] = {
        "cwd": str(_project_root()),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as exc:
        state.update(status="failed", stage="failed", message="无法启动更新进程", error=str(exc))
        _write_update_status(state)
        raise SelfUpdateError(str(exc)) from exc

    state["pid"] = process.pid
    return _write_update_status(state)
