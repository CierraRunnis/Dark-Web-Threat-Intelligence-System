from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPOSITORY = "CierraRunnis/Dark-Web-Threat-Intelligence-System"
DEFAULT_BRANCH = "main"
DEFAULT_TIMEOUT_SECONDS = 6
DEFAULT_CACHE_SECONDS = 60
RELEASE_BRANCH_PATTERN = re.compile(r"^v\.(\d+)\.(\d+)\.(\d+)$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_status_cache_lock = threading.Lock()
_status_cache_payload: dict[str, Any] | None = None
_status_cache_time = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _version_file_path() -> Path:
    configured = os.environ.get("DARKWEB_VERSION_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return _project_root() / "version.json"


def _short_commit(commit: str) -> str:
    value = str(commit or "").strip()
    return value[:7] if len(value) >= 7 else value


def _load_version_file() -> dict[str, Any]:
    path = _version_file_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(_project_root()), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def current_version_payload() -> dict[str, Any]:
    version_file = _load_version_file()
    local_commit = _git_commit()
    configured_commit = os.environ.get("DARKWEB_APP_COMMIT", "").strip()
    commit = configured_commit or str(version_file.get("commit") or "").strip() or local_commit
    version = os.environ.get("DARKWEB_APP_VERSION", "").strip() or str(version_file.get("version") or "").strip()
    if configured_commit:
        source = "environment"
    elif version_file:
        source = "version_file"
    elif local_commit:
        source = "git"
    else:
        source = "unknown"
    return {
        "version": version or "local",
        "commit": commit,
        "short_commit": _short_commit(commit),
        "local_commit": local_commit,
        "local_short_commit": _short_commit(local_commit),
        "branch": os.environ.get("DARKWEB_UPDATE_BRANCH", "").strip()
        or str(version_file.get("branch") or "").strip()
        or DEFAULT_BRANCH,
        "repository": os.environ.get("DARKWEB_UPDATE_REPO", "").strip()
        or str(version_file.get("repository") or "").strip()
        or DEFAULT_REPOSITORY,
        "updated_at": str(version_file.get("updated_at") or "").strip(),
        "source": source,
    }


def _validate_repository(repository: str) -> str:
    value = str(repository or "").strip()
    if not REPOSITORY_PATTERN.fullmatch(value):
        raise ValueError("GitHub 仓库名称无效")
    return value


def _validate_release_branch(branch: str) -> tuple[str, tuple[int, int, int]]:
    value = str(branch or "").strip()
    match = RELEASE_BRANCH_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("GitHub 正式发布分支格式无效")
    return value, tuple(int(part) for part in match.groups())


def _release_version_from_branch(branch: str) -> str:
    value, _ = _validate_release_branch(branch)
    return f"v{value[2:]}"


def latest_github_release(repository: str) -> dict[str, Any]:
    repository = _validate_repository(repository)
    timeout = max(5, int(os.environ.get("DARKWEB_UPDATE_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS) * 2)
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", f"https://github.com/{repository}.git"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"无法通过 Git 查询正式版本：{exc}") from exc
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout).strip() or "Git 正式版本查询失败")

    releases: list[tuple[tuple[int, int, int], str, str]] = []
    for line in result.stdout.splitlines():
        commit, separator, ref_name = line.strip().partition("\t")
        if not separator or not ref_name.startswith("refs/heads/"):
            continue
        branch = ref_name.removeprefix("refs/heads/")
        try:
            branch, release_number = _validate_release_branch(branch)
        except ValueError:
            continue
        releases.append((release_number, branch, commit.strip()))
    if not releases:
        raise ValueError("GitHub 仓库中没有可用的正式发布分支")

    _, branch, commit = max(releases, key=lambda item: item[0])
    return {
        "version": _release_version_from_branch(branch),
        "branch": branch,
        "repository": repository,
        "commit": commit,
        "short_commit": _short_commit(commit),
        "message": "",
        "committed_at": "",
        "updated_at": "",
        "html_url": f"https://github.com/{repository}/tree/{urllib.parse.quote(branch, safe='')}",
        "release_source": "git",
    }


def _same_commit(left: str, right: str) -> bool:
    left_value = str(left or "").strip()
    right_value = str(right or "").strip()
    if not left_value or not right_value:
        return False
    return left_value == right_value or left_value.startswith(right_value) or right_value.startswith(left_value)


def _build_version_status_uncached() -> dict[str, Any]:
    current = current_version_payload()
    repository = current["repository"]
    latest: dict[str, Any] = {}
    status = "ok"
    error = ""
    try:
        latest = latest_github_release(repository)
    except (OSError, ValueError, TimeoutError) as exc:
        status = "error"
        error = str(exc)

    current_commit = str(current.get("commit") or "")
    latest_commit = str(latest.get("commit") or "")
    current_version = str(current.get("version") or "")
    latest_version = str(latest.get("version") or "")
    if current_commit and latest_commit:
        update_available = not _same_commit(current_commit, latest_commit)
    else:
        update_available = bool(
            current_version
            and current_version != "local"
            and latest_version
            and current_version != latest_version
        )

    latest_branch = str(latest.get("branch") or current.get("branch") or DEFAULT_BRANCH)
    if update_available and current_commit and latest_commit:
        compare_url = (
            f"https://github.com/{repository}/compare/"
            f"{urllib.parse.quote(current_commit, safe='')}...{urllib.parse.quote(latest_commit, safe='')}"
        )
    else:
        compare_url = str(latest.get("html_url") or "") or (
            f"https://github.com/{repository}/tree/{urllib.parse.quote(latest_branch, safe='')}"
        )

    if status == "error":
        message = "无法检查 GitHub 正式版本"
    elif update_available:
        message = "发现新版本"
    elif latest_commit:
        message = "当前已是最新正式版本"
    else:
        message = "本地版本信息不完整"

    return {
        "status": status,
        "message": message,
        "channel": "release",
        "repository": repository,
        "branch": latest_branch,
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "compare_url": compare_url,
        "checked_at": _now_iso(),
        "error": error,
        "update_enabled": False,
    }


def _cache_seconds() -> int:
    try:
        return max(0, int(os.environ.get("DARKWEB_VERSION_CACHE_SECONDS") or DEFAULT_CACHE_SECONDS))
    except ValueError:
        return DEFAULT_CACHE_SECONDS


def clear_version_status_cache() -> None:
    global _status_cache_payload, _status_cache_time
    with _status_cache_lock:
        _status_cache_payload = None
        _status_cache_time = 0.0


def build_version_status(*, force: bool = False) -> dict[str, Any]:
    global _status_cache_payload, _status_cache_time
    with _status_cache_lock:
        cache_age = time.monotonic() - _status_cache_time
        if not force and _status_cache_payload is not None and cache_age < _cache_seconds():
            return copy.deepcopy(_status_cache_payload)
        payload = _build_version_status_uncached()
        _status_cache_payload = copy.deepcopy(payload)
        _status_cache_time = time.monotonic()
        return payload
