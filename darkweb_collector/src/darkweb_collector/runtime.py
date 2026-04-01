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
