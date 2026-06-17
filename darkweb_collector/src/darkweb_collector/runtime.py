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


def _looks_like_foreign_collector_output(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    current_output = (project_root() / "output").resolve()
    if resolved == current_output:
        return False
    if resolved.name.lower() != "output":
        return False
    parent = resolved.parent
    return parent.name.lower() == "darkweb_collector"


def output_root() -> Path:
    raw_path = os.environ.get("DARKWEB_COLLECTOR_OUTPUT_ROOT")
    if raw_path:
        resolved = Path(raw_path).expanduser().resolve()
        legacy = _legacy_output_root()
        if legacy is not None and resolved == legacy:
            return project_root() / "output"
        if _looks_like_foreign_collector_output(resolved):
            return project_root() / "output"
        return resolved
    return project_root() / "output"
