from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any


DATA_ROOT_ENV = "DARKWEB_DATA_ROOT"
APP_ROOT_ENV = "DARKWEB_APP_ROOT"
DATA_ROOT_CONFIG_NAME = "data-root.json"


def control_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (Path(local_app_data) / "DarkWebThreatIntel").resolve()
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config_home:
        return (Path(xdg_config_home).expanduser() / "darkweb-threat-intel").resolve()
    return (Path.home() / ".config" / "darkweb-threat-intel").resolve()


def update_state_root() -> Path:
    configured = os.environ.get("DARKWEB_UPDATE_STATE_DIR", "").strip()
    if not configured:
        return control_root()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        raise ValueError("update state root must be an absolute local directory")
    resolved = path.resolve()
    if os.name == "nt" and str(resolved).startswith("\\"):
        raise ValueError("update state root must be on a local Windows volume")
    return resolved


def default_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (Path(local_app_data) / "DarkWebThreatIntel").resolve()
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "darkweb-threat-intel").resolve()
    return (Path.home() / ".local" / "share" / "darkweb-threat-intel").resolve()


def data_root_config_path() -> Path:
    override = os.environ.get("DARKWEB_DATA_ROOT_CONFIG", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return control_root() / DATA_ROOT_CONFIG_NAME


def _validate_data_root(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError("data root must be an absolute directory below the drive root")
    resolved = expanded.resolve()
    anchor = Path(resolved.anchor)
    if resolved == anchor:
        raise ValueError("data root must be an absolute directory below the drive root")
    if os.name == "nt":
        if str(resolved).startswith("\\"):
            raise ValueError("data root must be on a local Windows volume")
        for value in (os.environ.get("SystemRoot"), os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not value:
                continue
            protected = Path(value).resolve()
            try:
                resolved.relative_to(protected)
            except ValueError:
                continue
            raise ValueError(f"data root cannot be under a protected system directory: {protected}")
    return resolved


def configured_data_root() -> tuple[Path, str]:
    for name in (DATA_ROOT_ENV, "DARKWEB_USER_DATA_ROOT"):
        value = os.environ.get(name, "").strip()
        if value:
            return _validate_data_root(Path(value)), f"environment:{name}"

    config_path = data_root_config_path()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_data_root(), "default"
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"invalid data root configuration: {config_path}") from exc
    if not isinstance(payload, dict) or payload.get("format") != 1:
        raise RuntimeError(f"unsupported data root configuration: {config_path}")
    value = str(payload.get("data_root") or "").strip()
    if not value:
        raise RuntimeError(f"data root configuration is empty: {config_path}")
    return _validate_data_root(Path(value)), "config"


def data_root() -> Path:
    return configured_data_root()[0]


def app_root() -> Path:
    configured = os.environ.get(APP_ROOT_ENV, "").strip()
    if configured:
        return _validate_data_root(Path(configured))
    return (data_root() / "app").resolve()


def _disk_usage(path: Path) -> tuple[int, int]:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    usage = shutil.disk_usage(candidate)
    return int(usage.total), int(usage.free)


def _postgresql_data_directory() -> str:
    environment_value = os.environ.get("DARKWEB_POSTGRESQL_DATA_DIRECTORY", "").strip()
    if environment_value:
        return environment_value
    target_config = control_root() / "postgresql-target.json"
    try:
        payload = json.loads(target_config.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(payload.get("data_directory") or "").strip() if isinstance(payload, dict) else ""


def _active_application_root() -> str:
    path = update_state_root() / "installation.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(payload, dict) or payload.get("format") != 1:
        return ""
    return str(payload.get("current_root") or "").strip()


def _path_is_within(value: str | Path, root: Path) -> bool:
    if not value:
        return False
    try:
        Path(value).expanduser().resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def storage_summary(active_release: dict[str, Any] | None = None) -> dict[str, Any]:
    root, source = configured_data_root()
    control = control_root()
    update_state = update_state_root()
    migration_override = os.environ.get("DARKWEB_MIGRATION_ROOT", "").strip()
    migration_path = (
        Path(migration_override).expanduser().resolve()
        if migration_override
        else (root / "migrations").resolve()
    )
    total_bytes, free_bytes = _disk_usage(root)
    active_output = str((active_release or {}).get("output_root") or "").strip()
    collector_output = active_output or os.environ.get("DARKWEB_COLLECTOR_OUTPUT_ROOT", "").strip() or str(root / "output")
    collector_database = os.environ.get("DARKWEB_COLLECTOR_DB_PATH", "").strip() or str(root / "collector.db")
    garnet_data = os.environ.get("DARKWEB_GARNET_DATA_ROOT", "").strip() or str(root / "garnet-data")
    postgresql_data_directory = _postgresql_data_directory()
    application_root = app_root()
    active_application_root = _active_application_root()
    playwright_root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip() or root / "playwright").expanduser().resolve()
    return {
        "data_root": str(root),
        "control_root": str(control),
        "update_state_root": str(update_state),
        "source": source,
        "custom": root != default_data_root(),
        "migration_root": str(migration_path),
        "migration_on_data_root": _path_is_within(migration_path, root),
        "postgresql_data_directory": postgresql_data_directory,
        "postgresql_on_data_root": _path_is_within(postgresql_data_directory, root),
        "application_root": str(application_root),
        "application_on_data_root": _path_is_within(application_root, root),
        "active_application_root": active_application_root,
        "active_application_on_data_root": _path_is_within(active_application_root, root),
        "playwright_root": str(playwright_root),
        "playwright_on_data_root": _path_is_within(playwright_root, root),
        "collector_database_path": collector_database,
        "collector_database_on_data_root": _path_is_within(collector_database, root),
        "collector_output_root": collector_output,
        "collector_output_on_data_root": _path_is_within(collector_output, root),
        "garnet_data_root": garnet_data,
        "garnet_on_data_root": _path_is_within(garnet_data, root),
        "active_output_root": active_output,
        "active_output_on_data_root": _path_is_within(active_output, root),
        "disk_total_bytes": total_bytes,
        "disk_free_bytes": free_bytes,
        "config_path": str(data_root_config_path()),
    }
