#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import uvicorn


def _default_runtime_db_path() -> Path:
    shared_db_path = Path.home() / ".local" / "share" / "bishe" / "collector.db"
    if shared_db_path.exists():
        return shared_db_path.resolve()
    return (ROOT / "data" / "collector.db").resolve()


if __name__ == "__main__":
    os.chdir(ROOT)
    runtime_db_path = _default_runtime_db_path()
    os.environ.setdefault("DARKWEB_COLLECTOR_DB_PATH", str(runtime_db_path))
    os.environ.setdefault("DARKWEB_COLLECTOR_SOURCE_DB_PATH", str(runtime_db_path))
    os.environ.setdefault("DARKWEB_RUNTIME_DB_META_PATH", f"{runtime_db_path}.meta.json")
    os.environ.setdefault("DARKWEB_COLLECTOR_SITES_FILE", str((ROOT / "sites.yaml").resolve()))
    uvicorn.run("darkweb_collector.api_app:app", host="0.0.0.0", port=8000, reload=False)
