from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.db import get_db_connection
from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence
from darkweb_collector.runtime import default_db_path


def _connect_fallback() -> sqlite3.Connection:
    connection = sqlite3.connect(default_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def main() -> int:
    try:
        with get_db_connection() as connection:
            events = ensure_normalized_intelligence(connection, force=True)
    except Exception:
        with _connect_fallback() as connection:
            events = ensure_normalized_intelligence(connection, force=True)

    site_stats: dict[str, dict[str, int]] = {}
    for event in events:
        site_name = str(event.get("source_site_name") or "unknown")
        site_stats.setdefault(site_name, {"events": 0, "screenshots": 0, "mirrors": 0})
        site_stats[site_name]["events"] += 1
        site_stats[site_name]["screenshots"] += len(event.get("screenshot_resources") or [])
        site_stats[site_name]["mirrors"] += len(event.get("mirror_resources") or [])

    print(json.dumps(site_stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
