from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from darkweb_collector.runtime import output_root


CHAOJIYING_RECOGNIZE_URL = "https://upload.chaojiying.net/Upload/Processing.php"
CHAOJIYING_REPORT_ERROR_URL = "https://upload.chaojiying.net/Upload/ReportError.php"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 60
_CONFIG_LOCK = Lock()


class ChaojiyingError(ValueError):
    pass


class ChaojiyingConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ChaojiyingCredentials:
    user: str
    password: str = ""
    pass2: str = ""
    soft_id: str = ""


def chaojiying_config_path() -> Path:
    configured = str(os.environ.get("DARKWEB_CHAOJIYING_CONFIG_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return output_root() / "captcha_providers" / "chaojiying_credentials.json"


def _legacy_changan_config_path() -> Path:
    return output_root() / "platform_sessions" / "changan" / "auto_login_credentials.json"


def _read_json_config(path: Path, *, required: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            raise ChaojiyingConfigError("尚未配置超级鹰验证码服务")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ChaojiyingConfigError("超级鹰配置文件无法读取") from exc
    if not isinstance(payload, dict):
        raise ChaojiyingConfigError("超级鹰配置文件格式无效")
    return payload


def _parse_legacy_credentials_file(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ChaojiyingConfigError("兼容凭据文件无法读取") from exc
    values: dict[str, str] = {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        values.update({str(key).strip().upper(): str(value or "").strip() for key, value in payload.items()})
    for raw_line in text.splitlines():
        line = raw_line.strip()
        assignment = re.match(r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if assignment:
            values[assignment.group(1).upper()] = assignment.group(2).strip().strip("\"'")
            continue
        if "超级鹰" in line:
            parts = re.split(r"[:：]", line, maxsplit=1)
            credentials = parts[1].split() if len(parts) == 2 else []
            if len(credentials) == 2:
                values["DARKWEB_CHAOJIYING_USER"] = credentials[0]
                values["DARKWEB_CHAOJIYING_PASSWORD"] = credentials[1]
    return values


def _managed_values() -> dict[str, str]:
    payload = _read_json_config(chaojiying_config_path())
    return {str(key).strip().upper(): str(value or "").strip() for key, value in payload.items()}


def _legacy_values() -> dict[str, str]:
    values: dict[str, str] = {}
    legacy_path = _legacy_changan_config_path()
    if legacy_path.is_file() and legacy_path != chaojiying_config_path():
        values.update(_parse_legacy_credentials_file(legacy_path))
    configured_path = str(os.environ.get("DARKWEB_CHANGAN_AUTO_LOGIN_CREDENTIALS_FILE") or "").strip()
    if configured_path:
        path = Path(configured_path).expanduser().resolve()
        if not path.is_file():
            raise ChaojiyingConfigError("长安自动登录兼容凭据文件不存在")
        if path not in {legacy_path, chaojiying_config_path()}:
            values.update(_parse_legacy_credentials_file(path))
    return values


def _value(values: dict[str, str], *names: str) -> str:
    for name in names:
        configured = str(os.environ.get(name) or values.get(name.upper()) or "").strip()
        if configured:
            return configured
    return ""


def load_chaojiying_credentials(*, required: bool = True) -> ChaojiyingCredentials | None:
    values = _legacy_values()
    values.update(_managed_values())
    environment_password = str(
        os.environ.get("DARKWEB_CHAOJIYING_PASSWORD")
        or os.environ.get("CHAOJIYING_PASSWORD")
        or ""
    ).strip()
    environment_pass2 = str(
        os.environ.get("DARKWEB_CHAOJIYING_PASS2")
        or os.environ.get("CHAOJIYING_PASS2")
        or ""
    ).strip()
    file_password = str(values.get("DARKWEB_CHAOJIYING_PASSWORD") or values.get("CHAOJIYING_PASSWORD") or "").strip()
    file_pass2 = str(values.get("DARKWEB_CHAOJIYING_PASS2") or values.get("CHAOJIYING_PASS2") or "").strip()
    credentials = ChaojiyingCredentials(
        user=_value(values, "DARKWEB_CHAOJIYING_USER", "CHAOJIYING_USER"),
        password=environment_password or ("" if environment_pass2 else file_password),
        pass2=environment_pass2 or ("" if environment_password else file_pass2),
        soft_id=_value(values, "DARKWEB_CHAOJIYING_SOFT_ID", "CHAOJIYING_SOFT_ID"),
    )
    if credentials.user and (credentials.password or credentials.pass2):
        return credentials
    if required:
        raise ChaojiyingConfigError("超级鹰配置不完整：必须提供账号和密码")
    return None


def _write_json_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            json.dump(payload, stream, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _strip_legacy_chaojiying_fields() -> None:
    path = _legacy_changan_config_path()
    if not path.is_file() or path == chaojiying_config_path():
        return
    payload = _read_json_config(path)
    changed = False
    for key in (
        "DARKWEB_CHAOJIYING_USER",
        "DARKWEB_CHAOJIYING_PASSWORD",
        "DARKWEB_CHAOJIYING_PASS2",
        "DARKWEB_CHAOJIYING_SOFT_ID",
    ):
        changed = payload.pop(key, None) is not None or changed
    if changed:
        _write_json_config(path, payload)


def chaojiying_config_status() -> dict[str, Any]:
    try:
        managed = _managed_values()
        legacy = _legacy_values()
        credentials = load_chaojiying_credentials(required=False)
        error = ""
    except (OSError, ValueError) as exc:
        managed = {}
        legacy = {}
        credentials = None
        error = str(exc)
    managed_complete = bool(
        managed.get("DARKWEB_CHAOJIYING_USER")
        and (managed.get("DARKWEB_CHAOJIYING_PASSWORD") or managed.get("DARKWEB_CHAOJIYING_PASS2"))
    )
    environment_names = (
        "DARKWEB_CHAOJIYING_USER",
        "DARKWEB_CHAOJIYING_PASSWORD",
        "DARKWEB_CHAOJIYING_PASS2",
        "DARKWEB_CHAOJIYING_SOFT_ID",
        "CHAOJIYING_USER",
        "CHAOJIYING_PASSWORD",
        "CHAOJIYING_PASS2",
        "CHAOJIYING_SOFT_ID",
    )
    legacy_complete = bool(
        legacy.get("DARKWEB_CHAOJIYING_USER")
        and (legacy.get("DARKWEB_CHAOJIYING_PASSWORD") or legacy.get("DARKWEB_CHAOJIYING_PASS2"))
    )
    legacy_file_from_environment = bool(
        str(os.environ.get("DARKWEB_CHANGAN_AUTO_LOGIN_CREDENTIALS_FILE") or "").strip()
        and legacy_complete
    )
    return {
        "configured": credentials is not None,
        "managedConfigured": managed_complete,
        "managedByEnvironment": legacy_file_from_environment
        or any(str(os.environ.get(name) or "").strip() for name in environment_names),
        "legacyConfigured": legacy_complete,
        "hasUser": bool(credentials and credentials.user),
        "hasCredential": bool(credentials and (credentials.password or credentials.pass2)),
        "hasSoftId": bool(credentials and credentials.soft_id),
        "defaultCodeType": str(os.environ.get("DARKWEB_CHAOJIYING_CODE_TYPE") or "5000").strip(),
        "lastError": error,
    }


def save_chaojiying_config(
    *,
    user: str = "",
    password: str = "",
    pass2: str = "",
    soft_id: str = "",
) -> dict[str, Any]:
    with _CONFIG_LOCK:
        existing = load_chaojiying_credentials(required=False)
        normalized_pass2 = str(pass2 or "").strip().lower()
        plaintext_password = str(password or "")
        if not normalized_pass2 and not plaintext_password and existing:
            normalized_pass2 = existing.pass2
            plaintext_password = existing.password
        if plaintext_password:
            normalized_pass2 = hashlib.md5(
                plaintext_password.encode("utf-8"),
                usedforsecurity=False,
            ).hexdigest()
        if normalized_pass2 and not re.fullmatch(r"[0-9a-f]{32}", normalized_pass2):
            raise ChaojiyingConfigError("超级鹰密码摘要必须是 32 位小写 MD5")
        payload = {
            "DARKWEB_CHAOJIYING_USER": str(user or "").strip()
            or str(existing.user if existing else "").strip(),
            "DARKWEB_CHAOJIYING_PASS2": normalized_pass2,
            "DARKWEB_CHAOJIYING_SOFT_ID": str(soft_id or "").strip()
            or str(existing.soft_id if existing else "").strip(),
        }
        if not payload["DARKWEB_CHAOJIYING_USER"] or not payload["DARKWEB_CHAOJIYING_PASS2"]:
            raise ChaojiyingConfigError("首次配置必须填写超级鹰账号和密码")
        _write_json_config(chaojiying_config_path(), payload)
        _strip_legacy_chaojiying_fields()
    return chaojiying_config_status()


def delete_chaojiying_config() -> dict[str, Any]:
    with _CONFIG_LOCK:
        try:
            chaojiying_config_path().unlink(missing_ok=True)
            _strip_legacy_chaojiying_fields()
        except OSError as exc:
            raise ChaojiyingConfigError("超级鹰配置文件无法删除") from exc
    return chaojiying_config_status()


def chaojiying_configured(*, user: str = "", password: str = "", pass2: str = "") -> bool:
    if user or password or pass2:
        return bool(str(user or "").strip() and str(pass2 or password or "").strip())
    try:
        return load_chaojiying_credentials(required=False) is not None
    except (OSError, ValueError):
        return False


def _password_md5(*, password: str = "", pass2: str = "") -> str:
    configured = str(pass2 or os.environ.get("DARKWEB_CHAOJIYING_PASS2") or "").strip().lower()
    if configured:
        if not re.fullmatch(r"[0-9a-f]{32}", configured):
            raise ChaojiyingError("DARKWEB_CHAOJIYING_PASS2 must be a 32-character lowercase MD5 value")
        return configured
    plaintext = str(password or os.environ.get("DARKWEB_CHAOJIYING_PASSWORD") or "")
    if not plaintext:
        raise ChaojiyingError("Chaojiying credentials are not configured")
    return hashlib.md5(plaintext.encode("utf-8"), usedforsecurity=False).hexdigest()


def _auth_settings(
    *,
    user: str = "",
    password: str = "",
    pass2: str = "",
    soft_id: str = "",
) -> dict[str, str]:
    managed = None
    if not any((user, password, pass2)):
        managed = load_chaojiying_credentials(required=False)
    configured_user = str(
        user
        or os.environ.get("DARKWEB_CHAOJIYING_USER")
        or (managed.user if managed else "")
        or ""
    ).strip()
    if not configured_user:
        raise ChaojiyingError("Chaojiying credentials are not configured")
    return {
        "user": configured_user,
        "pass2": _password_md5(
            password=password or (managed.password if managed else ""),
            pass2=pass2 or (managed.pass2 if managed else ""),
        ),
        "softid": str(
            soft_id
            or os.environ.get("DARKWEB_CHAOJIYING_SOFT_ID")
            or (managed.soft_id if managed else "")
            or ""
        ).strip(),
    }


def _recognition_settings(
    *,
    user: str = "",
    password: str = "",
    pass2: str = "",
    soft_id: str = "",
    code_type: str = "",
) -> dict[str, str]:
    codetype = str(code_type or os.environ.get("DARKWEB_CHAOJIYING_CODE_TYPE") or "5000").strip()
    if not codetype.isdigit():
        raise ChaojiyingError("DARKWEB_CHAOJIYING_CODE_TYPE must be numeric")
    return {
        **_auth_settings(user=user, password=password, pass2=pass2, soft_id=soft_id),
        "codetype": codetype,
    }


def _post_form(url: str, form: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=urlencode(form).encode("ascii"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "DarkWebThreatIntelligenceSystem/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChaojiyingError(f"Chaojiying request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise ChaojiyingError("Chaojiying returned an invalid response")
    return payload


def recognize_captcha(
    image: bytes,
    *,
    user: str = "",
    password: str = "",
    pass2: str = "",
    soft_id: str = "",
    code_type: str = "",
) -> dict[str, Any]:
    image_bytes = bytes(image or b"")
    if not image_bytes:
        raise ChaojiyingError("captcha image is empty")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ChaojiyingError("captcha image exceeds the 2 MB provider limit")

    form = {
        **_recognition_settings(
            user=user,
            password=password,
            pass2=pass2,
            soft_id=soft_id,
            code_type=code_type,
        ),
        "file_base64": base64.b64encode(image_bytes).decode("ascii"),
    }
    payload = _post_form(CHAOJIYING_RECOGNIZE_URL, form)
    try:
        error_number = int(payload.get("err_no") or 0)
    except (TypeError, ValueError) as exc:
        raise ChaojiyingError("Chaojiying returned an invalid response") from exc
    if error_number != 0:
        message = str(payload.get("err_str") or "recognition failed").strip()
        raise ChaojiyingError(f"Chaojiying error {error_number}: {message}")

    result = str(payload.get("pic_str") or "").strip()
    if not result:
        raise ChaojiyingError("Chaojiying returned an empty recognition result")
    return {
        "pic_id": str(payload.get("pic_id") or "").strip(),
        "pic_str": result,
        "md5": str(payload.get("md5") or "").strip(),
    }


def report_recognition_error(
    pic_id: str,
    *,
    user: str = "",
    password: str = "",
    pass2: str = "",
    soft_id: str = "",
) -> dict[str, Any]:
    identifier = str(pic_id or "").strip()
    if not identifier:
        raise ChaojiyingError("Chaojiying picture id is empty")
    settings = _auth_settings(user=user, password=password, pass2=pass2, soft_id=soft_id)
    payload = _post_form(
        CHAOJIYING_REPORT_ERROR_URL,
        {
            **settings,
            "id": identifier,
        },
    )
    try:
        error_number = int(payload.get("err_no") or 0)
    except (TypeError, ValueError) as exc:
        raise ChaojiyingError("Chaojiying returned an invalid response") from exc
    if error_number != 0:
        message = str(payload.get("err_str") or "error report failed").strip()
        raise ChaojiyingError(f"Chaojiying error {error_number}: {message}")
    return {"reported": True}
