from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.db import SCHEMA, connect, get_db_connection
from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence
from darkweb_collector.runtime import default_db_path


SKIP_TABLES = {"normalized_intelligence_events", "normalized_intelligence_cache_state", "sqlite_sequence"}
BASE_TABLES = {
    "collection_runs",
    "victims",
    "victim_details",
    "forum_topics",
    "forum_details",
    "forum_victims",
    "crawl_jobs",
    "vulnerability_records",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair collector.db by copying readable tables into a fresh SQLite file.")
    parser.add_argument("--db-path", default=str(default_db_path()), help="Path to collector.db")
    parser.add_argument("--keep-temp", action="store_true", help="Keep intermediate repaired db next to the source db.")
    return parser


def _user_tables(source: sqlite3.Connection) -> list[str]:
    rows = source.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _table_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _create_extra_tables(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    extra_tables = [table for table in _user_tables(source) if table not in BASE_TABLES and table not in SKIP_TABLES]
    for table_name in extra_tables:
        row = source.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if row and row[0]:
            target.execute(str(row[0]))


def _copy_table(source: sqlite3.Connection, target: sqlite3.Connection, table_name: str) -> int:
    columns = _table_columns(source, table_name)
    column_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    rows = source.execute(f"SELECT {column_sql} FROM {table_name}").fetchall()
    if rows:
        target.executemany(
            f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
            [tuple(row) for row in rows],
        )
    return len(rows)


def _copy_sequences(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    try:
        rows = source.execute("SELECT name, seq FROM sqlite_sequence").fetchall()
    except sqlite3.DatabaseError:
        return
    if not rows:
        return
    target.executemany(
        "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES(?, ?)",
        [tuple(row) for row in rows if str(row[0]) not in SKIP_TABLES],
    )


def _create_extra_indexes(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    extra_tables = [table for table in _user_tables(source) if table not in BASE_TABLES and table not in SKIP_TABLES]
    for table_name in extra_tables:
        rows = source.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL
            ORDER BY name
            """,
            (table_name,),
        ).fetchall()
        for row in rows:
            if row[0]:
                target.execute(str(row[0]))


def _integrity_check(connection: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]


def main() -> int:
    args = build_parser().parse_args()
    source_path = Path(args.db_path).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"database not found: {source_path}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = source_path.with_name(f"{source_path.stem}.backup-{stamp}{source_path.suffix}")
    repaired_path = source_path.with_name(f"{source_path.stem}.repaired-{stamp}{source_path.suffix}")

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = connect(repaired_path)
    try:
        target.executescript(SCHEMA)
        _create_extra_tables(source, target)

        copied_counts: dict[str, int] = {}
        for table_name in _user_tables(source):
            if table_name in SKIP_TABLES:
                continue
            copied_counts[table_name] = _copy_table(source, target, table_name)
        _copy_sequences(source, target)
        _create_extra_indexes(source, target)

        rebuilt_events = ensure_normalized_intelligence(target, force=True)
        target.commit()
        integrity_rows = _integrity_check(target)
    finally:
        source.close()
        target.close()

    shutil.copy2(source_path, backup_path)
    shutil.move(str(repaired_path), str(source_path))

    print(
        {
            "database": str(source_path),
            "backup": str(backup_path),
            "copied_counts": copied_counts,
            "normalized_events": len(rebuilt_events),
            "integrity_check": integrity_rows[:10],
        }
    )

    if args.keep_temp and repaired_path.exists():
        print({"temp": str(repaired_path)})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
