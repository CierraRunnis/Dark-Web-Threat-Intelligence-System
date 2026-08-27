from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any


DEFAULT_REPOSITORY = "Threat-Intelligence-monitor/Dark-Web-Threat-Intelligence-System"
DEFAULT_BRANCH = "main"
DEFAULT_CHANNEL = "stable"
DEFAULT_TIMEOUT_SECONDS = 10
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
VERSION_PATTERN = re.compile(r"^v?(\d+(?:\.\d+)*)(?:[-+]([0-9A-Za-z.-]+))?$")
DEFAULT_GITHUB_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, trust_url: str) -> None:
        super().__init__()
        self.trust_url = trust_url

    def redirect_request(self, request, response, code, message, headers, new_url):
        absolute_url = urllib.parse.urljoin(request.full_url, new_url)
        _validate_update_url(absolute_url, "更新下载重定向地址", self.trust_url)
        return super().redirect_request(request, response, code, message, headers, absolute_url)


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
    """Return a development checkout commit when Git happens to be present."""
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


def _default_manifest_url(repository: str) -> str:
    repo_path = urllib.parse.quote(repository.strip(), safe="/")
    return f"https://github.com/{repo_path}/releases/latest/download/latest-stable.json"


def current_version_payload() -> dict[str, Any]:
    version_file = _load_version_file()
    git_commit = _git_commit()
    commit = (
        os.environ.get("DARKWEB_APP_COMMIT", "").strip()
        or git_commit
        or str(version_file.get("commit") or "").strip()
    )
    version = os.environ.get("DARKWEB_APP_VERSION", "").strip() or str(version_file.get("version") or "").strip()
    repository = (
        os.environ.get("DARKWEB_UPDATE_REPO", "").strip()
        or str(version_file.get("repository") or "").strip()
        or DEFAULT_REPOSITORY
    )
    manifest_url = (
        os.environ.get("DARKWEB_UPDATE_MANIFEST_URL", "").strip()
        or str(version_file.get("update_manifest_url") or "").strip()
        or _default_manifest_url(repository)
    )
    return {
        "version": version or "local",
        "commit": commit,
        "short_commit": _short_commit(commit),
        "branch": os.environ.get("DARKWEB_UPDATE_BRANCH", "").strip() or str(version_file.get("branch") or "").strip() or DEFAULT_BRANCH,
        "channel": os.environ.get("DARKWEB_UPDATE_CHANNEL", "").strip() or str(version_file.get("channel") or "").strip() or DEFAULT_CHANNEL,
        "repository": repository,
        "manifest_url": manifest_url,
        "data_schema": int(version_file.get("data_schema") or 1),
        "updated_at": str(version_file.get("updated_at") or "").strip(),
        "source": "git" if git_commit else "version_file" if version_file else "unknown",
    }


def _request_headers(accept: str = "application/json") -> dict[str, str]:
    return {
        "Accept": accept,
        "User-Agent": "darkweb-threat-intel-release-updater",
    }


def _allowed_hosts(manifest_url: str) -> set[str]:
    configured = os.environ.get("DARKWEB_UPDATE_ALLOWED_HOSTS", "").strip()
    if configured:
        return {item.strip().lower() for item in configured.split(",") if item.strip()}
    manifest_host = (urllib.parse.urlparse(manifest_url).hostname or "").lower()
    hosts = {manifest_host} if manifest_host else set()
    if manifest_host in DEFAULT_GITHUB_HOSTS:
        hosts.update(DEFAULT_GITHUB_HOSTS)
    return hosts


def _validate_update_url(url: str, label: str, manifest_url: str | None = None) -> str:
    value = str(url or "").strip()
    parsed = urllib.parse.urlparse(value)
    allow_insecure = os.environ.get("DARKWEB_UPDATE_ALLOW_INSECURE", "") == "1"
    allowed_schemes = {"https", "http", "file"} if allow_insecure else {"https"}
    if parsed.scheme not in allowed_schemes:
        if not allow_insecure:
            raise ValueError(f"{label}必须使用 HTTPS")
        raise ValueError(f"{label}协议无效")
    if parsed.scheme != "file" and not parsed.hostname:
        raise ValueError(f"{label}地址无效")
    if manifest_url and parsed.scheme != "file":
        allowed = _allowed_hosts(manifest_url)
        if allowed and (parsed.hostname or "").lower() not in allowed:
            raise ValueError(f"{label}域名不在允许列表中")
    return value


def _read_json_url(url: str) -> dict[str, Any]:
    validated_url = _validate_update_url(url, "更新清单地址")
    timeout = int(os.environ.get("DARKWEB_UPDATE_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
    request = urllib.request.Request(validated_url, headers=_request_headers())
    with _open_update_request(request, validated_url, max(1, timeout)) as response:
        final_url = response.geturl()
        _validate_update_url(final_url, "更新清单重定向地址", validated_url)
        body = response.read(MAX_MANIFEST_BYTES + 1)
    if len(body) > MAX_MANIFEST_BYTES:
        raise ValueError("更新清单超过大小限制")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("更新清单格式无效")
    return payload


def _open_update_request(request: urllib.request.Request, trust_url: str, timeout: int):
    opener = urllib.request.build_opener(_ValidatingRedirectHandler(trust_url))
    return opener.open(request, timeout=timeout)


def _validate_manifest_payload(payload: dict[str, Any], manifest_url: str) -> dict[str, Any]:
    format_version = payload.get("format", payload.get("schema_version"))
    if format_version != 1:
        raise ValueError("更新清单版本不受支持")

    version = str(payload.get("version") or "").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("更新版本号无效")

    package_value = payload.get("package", payload.get("artifact"))
    if not isinstance(package_value, dict):
        raise ValueError("更新清单缺少安装包信息")
    package_url = _validate_update_url(str(package_value.get("url") or ""), "更新包地址", manifest_url)
    sha256 = str(package_value.get("sha256") or "").strip().lower()
    if not SHA256_PATTERN.fullmatch(sha256):
        raise ValueError("更新包 SHA-256 无效")
    try:
        package_size = int(package_value.get("size") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("更新包大小无效") from exc
    maximum = int(os.environ.get("DARKWEB_UPDATE_MAX_PACKAGE_BYTES") or MAX_PACKAGE_BYTES)
    if package_size <= 0 or package_size > maximum:
        raise ValueError("更新包大小超出允许范围")

    commit = str(payload.get("commit") or "").strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("更新提交标识无效")
    signature = payload.get("signature") if isinstance(payload.get("signature"), dict) else {}
    return {
        "format": 1,
        "channel": str(payload.get("channel") or DEFAULT_CHANNEL).strip() or DEFAULT_CHANNEL,
        "version": version,
        "commit": commit,
        "short_commit": _short_commit(commit),
        "message": str(payload.get("message") or "").strip(),
        "published_at": str(payload.get("published_at") or "").strip(),
        "release_url": str(payload.get("release_url") or "").strip(),
        "minimum_updater_version": int(payload.get("minimum_updater_version") or payload.get("min_updater_version") or 1),
        "data_schema": int(payload.get("data_schema") or 1),
        "rollback_compatible": payload.get("rollback_compatible") is True,
        "package": {
            "name": str(package_value.get("name") or "update.zip").strip() or "update.zip",
            "url": package_url,
            "sha256": sha256,
            "size": package_size,
        },
        "signature": signature,
        "manifest_url": manifest_url,
    }


def load_update_manifest(url: str | None = None) -> dict[str, Any]:
    current = current_version_payload()
    manifest_url = str(url or current.get("manifest_url") or "").strip()
    payload = _read_json_url(manifest_url)
    return _validate_manifest_payload(payload, manifest_url)


def _parsed_version(value: str) -> tuple[tuple[int, ...], str | None] | None:
    match = VERSION_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        return None
    numbers = tuple(int(item) for item in match.group(1).split("."))
    return numbers, match.group(2)


def _is_newer_version(latest: str, current: str) -> bool:
    if str(latest or "").strip() == str(current or "").strip():
        return False
    latest_parsed = _parsed_version(latest)
    current_parsed = _parsed_version(current)
    if not latest_parsed or not current_parsed:
        return bool(latest_parsed and not current_parsed)

    latest_numbers, latest_suffix = latest_parsed
    current_numbers, current_suffix = current_parsed
    for latest_part, current_part in zip_longest(latest_numbers, current_numbers, fillvalue=0):
        if latest_part != current_part:
            return latest_part > current_part
    if latest_suffix is None and current_suffix is not None:
        return True
    if latest_suffix is not None and current_suffix is None:
        return False
    return str(latest_suffix or "") > str(current_suffix or "")


def build_version_status() -> dict[str, Any]:
    current = current_version_payload()
    public_current = current.copy()
    public_current.pop("manifest_url", None)
    latest: dict[str, Any] = {}
    status = "ok"
    error = ""

    try:
        manifest = load_update_manifest(str(current.get("manifest_url") or ""))
        package = manifest["package"]
        latest = {
            "version": manifest["version"],
            "commit": manifest["commit"],
            "short_commit": manifest["short_commit"],
            "message": manifest["message"],
            "published_at": manifest["published_at"],
            "committed_at": manifest["published_at"],
            "html_url": manifest["release_url"],
            "package_size": package["size"],
        }
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError, TimeoutError, ValueError) as exc:
        status = "error"
        error = str(exc)

    current_version = str(current.get("version") or "")
    latest_version = str(latest.get("version") or "")
    update_available = bool(latest_version and _is_newer_version(latest_version, current_version))
    compare_url = str(latest.get("html_url") or "") or f"https://github.com/{current['repository']}/releases"

    if status == "error":
        message = "无法检查更新服务"
    elif update_available:
        message = "发现新版本"
    elif latest_version:
        message = "当前已是最新版本"
    else:
        message = "版本信息不完整"

    return {
        "status": status,
        "message": message,
        "repository": current["repository"],
        "branch": current["branch"],
        "channel": current["channel"],
        "current": public_current,
        "latest": latest,
        "update_available": update_available,
        "compare_url": compare_url,
        "checked_at": _now_iso(),
        "error": error,
    }
