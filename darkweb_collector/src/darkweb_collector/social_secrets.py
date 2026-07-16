from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Iterable, Mapping


SOCIAL_SECRET_NAMES = {
    "SOCIAL_YOUTUBE_API_KEY",
    "SOCIAL_TELEGRAM_API_ID",
    "SOCIAL_TELEGRAM_API_HASH",
    "SOCIAL_TELEGRAM_SESSION",
}
_LOCK = threading.Lock()


def social_secrets_path() -> Path:
    configured = os.environ.get("SOCIAL_PLATFORM_SECRETS_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".config" / "darkweb-threat-intel" / "social-platform-secrets.json").resolve()


def _read_file() -> dict[str, str]:
    path = social_secrets_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(name): str(value).strip()
        for name, value in payload.items()
        if name in SOCIAL_SECRET_NAMES and str(value).strip()
    }


def get_social_secret(name: str) -> str:
    if name not in SOCIAL_SECRET_NAMES:
        return os.environ.get(name, "").strip()
    environment_value = os.environ.get(name, "").strip()
    if environment_value:
        return environment_value
    return _read_file().get(name, "")


def social_secret_state(name: str) -> dict[str, object]:
    if os.environ.get(name, "").strip():
        return {"configured": True, "source": "environment"}
    configured = bool(_read_file().get(name))
    return {"configured": configured, "source": "local_file" if configured else "missing"}


def _write_file(values: Mapping[str, str]) -> None:
    path = social_secrets_path()
    if not values:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".social-secrets-", delete=False
        ) as handle:
            json.dump(dict(sorted(values.items())), handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)


def update_social_secrets(updates: Mapping[str, str]) -> None:
    clean = {
        name: str(value).strip()
        for name, value in updates.items()
        if name in SOCIAL_SECRET_NAMES and str(value).strip()
    }
    if not clean:
        return
    with _LOCK:
        values = _read_file()
        values.update(clean)
        _write_file(values)


def remove_social_secrets(names: Iterable[str]) -> None:
    selected = {name for name in names if name in SOCIAL_SECRET_NAMES}
    if not selected:
        return
    with _LOCK:
        values = _read_file()
        for name in selected:
            values.pop(name, None)
        _write_file(values)
