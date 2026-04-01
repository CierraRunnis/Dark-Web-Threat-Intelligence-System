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


if __name__ == "__main__":
    os.chdir(ROOT)
    os.environ.setdefault("DARKWEB_COLLECTOR_DB_PATH", str((ROOT / "data" / "collector.db").resolve()))
    os.environ.setdefault("DARKWEB_COLLECTOR_SITES_FILE", str((ROOT / "sites.yaml").resolve()))
    uvicorn.run("darkweb_collector.api_app:app", host="0.0.0.0", port=8000, reload=False)
