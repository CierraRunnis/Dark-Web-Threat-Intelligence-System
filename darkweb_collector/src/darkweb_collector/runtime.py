from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def user_data_root() -> Path:
    override = os.environ.get("DARKWEB_USER_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (Path(local_app_data) / "DarkWebThreatIntel").resolve()
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return (Path(xdg_data_home).expanduser() / "darkweb-threat-intel").resolve()
    return (Path.home() / ".local" / "share" / "darkweb-threat-intel").resolve()


def active_release_path() -> Path:
    override = os.environ.get("DARKWEB_ACTIVE_RELEASE_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return user_data_root() / "active-release.json"


def active_release_config() -> dict[str, Any]:
    path = active_release_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) and payload.get("format") == 1 else {}


def configured_database_url() -> str:
    override = os.environ.get("DARKWEB_COLLECTOR_DATABASE_URL", "").strip()
    if override:
        return override
    release = active_release_config()
    return str(
        release.get("runtime_database_url") or release.get("database_url") or ""
    ).strip()


def configured_database_schema() -> str:
    override = os.environ.get("DARKWEB_COLLECTOR_DATABASE_SCHEMA", "").strip()
    if override:
        return override
    return str(active_release_config().get("database_schema") or "").strip()


def configured_schema_fingerprint() -> str:
    override = os.environ.get("DARKWEB_COLLECTOR_SCHEMA_FINGERPRINT", "").strip()
    if override:
        return override
    return str(active_release_config().get("schema_fingerprint") or "").strip()


def configured_schema_version() -> str:
    override = os.environ.get("DARKWEB_COLLECTOR_SCHEMA_VERSION", "").strip()
    if override:
        return override
    return str(
        active_release_config().get("schema_version") or "0006_postgres_read_paths"
    ).strip()


def default_config_path() -> Path:
    raw_path = os.environ.get("DARKWEB_COLLECTOR_SITES_FILE")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return project_root() / "sites.yaml"


def default_db_path() -> Path:
    raw_path = os.environ.get("DARKWEB_COLLECTOR_DB_PATH")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return project_root() / "data" / "collector.db"


def _legacy_output_root() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return (Path(local_app_data) / "DarkWebThreatIntel" / "output").expanduser().resolve()


def output_root() -> Path:
    raw_path = os.environ.get("DARKWEB_COLLECTOR_OUTPUT_ROOT")
    if raw_path:
        resolved = Path(raw_path).expanduser().resolve()
        legacy = _legacy_output_root()
        if legacy is not None and resolved == legacy:
            return project_root() / "output"
        return resolved
    active_output = str(active_release_config().get("output_root") or "").strip()
    if active_output:
        return Path(active_output).expanduser().resolve()
    return project_root() / "output"
