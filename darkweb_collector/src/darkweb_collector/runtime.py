from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from darkweb_collector.storage_paths import data_root


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def user_data_root() -> Path:
    return data_root()


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
    return str(active_release_config().get("database_url") or "").strip()


def configured_database_schema() -> str:
    override = os.environ.get("DARKWEB_COLLECTOR_DATABASE_SCHEMA", "").strip()
    if override:
        return override
    return str(active_release_config().get("database_schema") or "").strip()


def default_config_path() -> Path:
    raw_path = os.environ.get("DARKWEB_COLLECTOR_SITES_FILE")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return project_root() / "sites.yaml"


def default_db_path() -> Path:
    raw_path = os.environ.get("DARKWEB_COLLECTOR_DB_PATH")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    return user_data_root() / "collector.db"


def output_root() -> Path:
    raw_path = os.environ.get("DARKWEB_COLLECTOR_OUTPUT_ROOT")
    if raw_path:
        return Path(raw_path).expanduser().resolve()
    active_output = str(active_release_config().get("output_root") or "").strip()
    if active_output:
        return Path(active_output).expanduser().resolve()
    return user_data_root() / "output"
