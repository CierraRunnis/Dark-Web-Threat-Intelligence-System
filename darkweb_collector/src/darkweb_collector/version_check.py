from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REPOSITORY = "CierraRunnis/Dark-Web-Threat-Intelligence-System"
DEFAULT_BRANCH = "main"
DEFAULT_TIMEOUT_SECONDS = 6


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
    commit = (
        os.environ.get("DARKWEB_APP_COMMIT", "").strip()
        or str(version_file.get("commit") or "").strip()
        or _git_commit()
    )
    version = os.environ.get("DARKWEB_APP_VERSION", "").strip() or str(version_file.get("version") or "").strip()
    return {
        "version": version or "local",
        "commit": commit,
        "short_commit": _short_commit(commit),
        "branch": os.environ.get("DARKWEB_UPDATE_BRANCH", "").strip() or str(version_file.get("branch") or "").strip() or DEFAULT_BRANCH,
        "repository": os.environ.get("DARKWEB_UPDATE_REPO", "").strip() or str(version_file.get("repository") or "").strip() or DEFAULT_REPOSITORY,
        "updated_at": str(version_file.get("updated_at") or "").strip(),
        "source": "version_file" if version_file else "git" if commit else "unknown",
    }


def _github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "darkweb-threat-intel-version-check",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def latest_github_version(repository: str, branch: str) -> dict[str, Any]:
    repo_path = urllib.parse.quote(repository.strip(), safe="/")
    branch_path = urllib.parse.quote(branch.strip(), safe="")
    url = f"https://api.github.com/repos/{repo_path}/commits/{branch_path}"
    request = urllib.request.Request(url, headers=_github_api_headers())
    timeout = int(os.environ.get("DARKWEB_UPDATE_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
        payload = json.loads(response.read().decode("utf-8"))

    commit = str(payload.get("sha") or "").strip()
    commit_payload = payload.get("commit") if isinstance(payload.get("commit"), dict) else {}
    committer = commit_payload.get("committer") if isinstance(commit_payload.get("committer"), dict) else {}
    return {
        "commit": commit,
        "short_commit": _short_commit(commit),
        "message": str(commit_payload.get("message") or "").splitlines()[0],
        "committed_at": str(committer.get("date") or "").strip(),
        "html_url": str(payload.get("html_url") or "").strip(),
    }


def _same_commit(left: str, right: str) -> bool:
    left_value = str(left or "").strip()
    right_value = str(right or "").strip()
    if not left_value or not right_value:
        return False
    return left_value == right_value or left_value.startswith(right_value) or right_value.startswith(left_value)


def build_version_status() -> dict[str, Any]:
    current = current_version_payload()
    repository = current["repository"]
    branch = current["branch"]
    latest: dict[str, Any] = {}
    status = "ok"
    error = ""

    try:
        latest = latest_github_version(repository, branch)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        status = "error"
        error = str(exc)

    current_commit = str(current.get("commit") or "")
    latest_commit = str(latest.get("commit") or "")
    update_available = bool(latest_commit and current_commit and not _same_commit(current_commit, latest_commit))
    if update_available and current_commit:
        compare_url = f"https://github.com/{repository}/compare/{urllib.parse.quote(current_commit, safe='')}...{urllib.parse.quote(branch, safe='')}"
    else:
        compare_url = f"https://github.com/{repository}/tree/{urllib.parse.quote(branch, safe='')}"

    if status == "error":
        message = "无法检查 GitHub 更新"
    elif update_available:
        message = "发现新版本"
    elif latest_commit:
        message = "当前已是最新版本"
    else:
        message = "本地版本信息不完整"

    return {
        "status": status,
        "message": message,
        "repository": repository,
        "branch": branch,
        "current": current,
        "latest": latest,
        "update_available": update_available,
        "compare_url": compare_url,
        "checked_at": _now_iso(),
        "error": error,
    }
