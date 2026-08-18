from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from darkweb_collector.runtime import default_db_path


GITHUB_API_VERSION = "2022-11-28"
TOKEN_REFRESH_SKEW_SECONDS = 300
TOKEN_RETRY_SECONDS = 60
_STATE_LOCK = Lock()
_TOKEN_REFRESH_LOCK = Lock()
_TOKEN_CACHE: dict[str, Any] = {
    "fingerprint": "",
    "token": "",
    "expires_epoch": 0.0,
    "retry_after_epoch": 0.0,
}
_STATE: dict[str, str] = {
    "last_error": "",
    "last_validated_at": "",
    "token_expires_at": "",
}


class GitHubAppConfigError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_config") -> None:
        super().__init__(message)
        self.code = code


class GitHubAppConnectionError(RuntimeError):
    def __init__(self, message: str, *, code: str = "connection_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GitHubAppCredentials:
    app_id: int
    installation_id: int
    private_key: str


def github_app_config_path() -> Path:
    configured = os.environ.get("DARKWEB_GITHUB_APP_CONFIG_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return default_db_path().with_name("github_app_credentials.json")


def _positive_id(value: Any, label: str) -> int:
    try:
        normalized = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise GitHubAppConfigError(f"{label} 必须是正整数") from exc
    if normalized <= 0:
        raise GitHubAppConfigError(f"{label} 必须是正整数")
    return normalized


def _normalize_private_key(value: Any) -> str:
    private_key = str(value or "").strip().replace("\r\n", "\n")
    if "\\n" in private_key and "\n" not in private_key:
        private_key = private_key.replace("\\n", "\n")
    if not private_key:
        raise GitHubAppConfigError("首次配置必须提供 GitHub App 私钥", code="private_key_required")
    return f"{private_key}\n"


def _credentials_from_payload(payload: dict[str, Any]) -> GitHubAppCredentials:
    return GitHubAppCredentials(
        app_id=_positive_id(payload.get("app_id"), "App ID"),
        installation_id=_positive_id(payload.get("installation_id"), "Installation ID"),
        private_key=_normalize_private_key(payload.get("private_key")),
    )


def _load_credentials(*, required: bool = False) -> GitHubAppCredentials | None:
    path = github_app_config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise GitHubAppConfigError("尚未配置 GitHub App", code="not_configured")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise GitHubAppConfigError("GitHub App 配置文件无法读取", code="config_invalid") from exc
    if not isinstance(payload, dict):
        raise GitHubAppConfigError("GitHub App 配置文件格式无效", code="config_invalid")
    return _credentials_from_payload(payload)


def _credentials_fingerprint(credentials: GitHubAppCredentials) -> str:
    material = f"{credentials.app_id}:{credentials.installation_id}:".encode("utf-8")
    material += credentials.private_key.encode("utf-8")
    return sha256(material).hexdigest()


def _parse_expiry(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise GitHubAppConnectionError("GitHub 返回的安装令牌有效期无效", code="invalid_response") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _encode_app_jwt(credentials: GitHubAppCredentials, now_epoch: float) -> str:
    try:
        import jwt
    except ImportError as exc:
        raise GitHubAppConfigError("服务缺少 PyJWT[crypto] 依赖", code="missing_dependency") from exc

    claims = {
        "iat": int(now_epoch) - 60,
        "exp": int(now_epoch) + 540,
        "iss": str(credentials.app_id),
    }
    try:
        encoded = jwt.encode(claims, credentials.private_key, algorithm="RS256")
    except Exception as exc:
        raise GitHubAppConfigError("GitHub App 私钥格式或内容无效", code="invalid_private_key") from exc
    return str(encoded)


def _exchange_installation_token(credentials: GitHubAppCredentials) -> tuple[str, str, float]:
    now_epoch = time.time()
    app_jwt = _encode_app_jwt(credentials, now_epoch)
    request = Request(
        f"https://api.github.com/app/installations/{credentials.installation_id}/access_tokens",
        data=b"{}",
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {app_jwt}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "darkweb-threat-intelligence-system",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        if exc.code in {401, 403, 404, 422}:
            raise GitHubAppConnectionError(
                "GitHub App 验证失败，请检查 App ID、Installation ID、私钥和安装状态",
                code="credentials_rejected",
            ) from exc
        raise GitHubAppConnectionError("GitHub 暂时无法签发安装令牌", code="github_unavailable") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GitHubAppConnectionError("无法连接 GitHub 安装令牌接口", code="network_error") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubAppConnectionError("GitHub 返回了无法识别的响应", code="invalid_response") from exc

    token = str(payload.get("token") or "").strip() if isinstance(payload, dict) else ""
    expires_at = str(payload.get("expires_at") or "").strip() if isinstance(payload, dict) else ""
    if not token or not expires_at:
        raise GitHubAppConnectionError("GitHub 返回的安装令牌响应不完整", code="invalid_response")
    return token, expires_at, _parse_expiry(expires_at)


def _write_credentials(credentials: GitHubAppCredentials) -> None:
    path = github_app_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)

    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            json.dump(
                {
                    "app_id": credentials.app_id,
                    "installation_id": credentials.installation_id,
                    "private_key": credentials.private_key,
                },
                stream,
                ensure_ascii=False,
            )
            stream.write("\n")
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _record_success(fingerprint: str, token: str, expires_at: str, expires_epoch: float) -> None:
    with _STATE_LOCK:
        _TOKEN_CACHE.update(
            {
                "fingerprint": fingerprint,
                "token": token,
                "expires_epoch": expires_epoch,
                "retry_after_epoch": 0.0,
            }
        )
        _STATE.update(
            {
                "last_error": "",
                "last_validated_at": datetime.now(timezone.utc).isoformat(),
                "token_expires_at": expires_at,
            }
        )


def _record_failure(fingerprint: str, error_code: str) -> None:
    with _STATE_LOCK:
        _TOKEN_CACHE.update(
            {
                "fingerprint": fingerprint,
                "token": "",
                "expires_epoch": 0.0,
                "retry_after_epoch": time.time() + TOKEN_RETRY_SECONDS,
            }
        )
        _STATE.update({"last_error": error_code, "token_expires_at": ""})


def github_app_installation_token() -> str:
    try:
        credentials = _load_credentials()
    except GitHubAppConfigError as exc:
        _record_failure("", exc.code)
        return ""
    if credentials is None:
        return ""

    fingerprint = _credentials_fingerprint(credentials)
    with _TOKEN_REFRESH_LOCK:
        now_epoch = time.time()
        with _STATE_LOCK:
            if (
                _TOKEN_CACHE.get("fingerprint") == fingerprint
                and str(_TOKEN_CACHE.get("token") or "")
                and float(_TOKEN_CACHE.get("expires_epoch") or 0) > now_epoch + TOKEN_REFRESH_SKEW_SECONDS
            ):
                return str(_TOKEN_CACHE["token"])
            if (
                _TOKEN_CACHE.get("fingerprint") == fingerprint
                and float(_TOKEN_CACHE.get("retry_after_epoch") or 0) > now_epoch
            ):
                return ""

        try:
            token, expires_at, expires_epoch = _exchange_installation_token(credentials)
        except (GitHubAppConfigError, GitHubAppConnectionError) as exc:
            _record_failure(fingerprint, exc.code)
            return ""
        _record_success(fingerprint, token, expires_at, expires_epoch)
        return token


def github_app_config_status() -> dict[str, Any]:
    try:
        credentials = _load_credentials()
        config_error = ""
    except GitHubAppConfigError as exc:
        credentials = None
        config_error = exc.code

    with _STATE_LOCK:
        state = dict(_STATE)
    return {
        "configured": credentials is not None,
        "appId": credentials.app_id if credentials else None,
        "installationId": credentials.installation_id if credentials else None,
        "hasPrivateKey": credentials is not None,
        "lastValidatedAt": state.get("last_validated_at", ""),
        "tokenExpiresAt": state.get("token_expires_at", ""),
        "lastError": config_error or state.get("last_error", ""),
    }


def save_github_app_config(*, app_id: Any, installation_id: Any, private_key: str = "") -> dict[str, Any]:
    supplied_key = str(private_key or "").strip()
    if not supplied_key:
        existing = _load_credentials(required=True)
        supplied_key = existing.private_key if existing else ""

    credentials = _credentials_from_payload(
        {
            "app_id": app_id,
            "installation_id": installation_id,
            "private_key": supplied_key,
        }
    )
    fingerprint = _credentials_fingerprint(credentials)
    with _TOKEN_REFRESH_LOCK:
        try:
            token, expires_at, expires_epoch = _exchange_installation_token(credentials)
        except (GitHubAppConfigError, GitHubAppConnectionError) as exc:
            _record_failure(fingerprint, exc.code)
            raise
        _write_credentials(credentials)
        _record_success(fingerprint, token, expires_at, expires_epoch)
    return github_app_config_status()


def delete_github_app_config() -> dict[str, Any]:
    path = github_app_config_path()
    with _TOKEN_REFRESH_LOCK:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise GitHubAppConfigError("GitHub App 配置文件无法删除", code="delete_failed") from exc
        with _STATE_LOCK:
            _TOKEN_CACHE.update(
                {
                    "fingerprint": "",
                    "token": "",
                    "expires_epoch": 0.0,
                    "retry_after_epoch": 0.0,
                }
            )
            _STATE.update({"last_error": "", "last_validated_at": "", "token_expires_at": ""})
    return github_app_config_status()
