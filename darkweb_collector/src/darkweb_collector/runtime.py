from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


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
    return project_root() / "output"
