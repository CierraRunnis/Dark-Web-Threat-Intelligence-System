from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.db import SCHEMA, connect
from darkweb_collector.db import upsert_normalized_intelligence_cache_state
from darkweb_collector.normalized_intelligence import _build_source_signature, ensure_normalized_intelligence


SKIP_TABLES = {"normalized_intelligence_events", "normalized_intelligence_cache_state", "sqlite_sequence"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a stable runtime SQLite database for WSL services.")
    parser.add_argument("--source", required=True, help="Source collector.db path")
    parser.add_argument("--target", required=True, help="Target runtime collector.db path")
    parser.add_argument("--force", action="store_true", help="Rebuild target even if it already exists.")
    return parser


def _meta_path(target_path: Path) -> Path:
    return target_path.with_suffix(f"{target_path.suffix}.meta.json")


def _user_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
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


def _single_primary_key_column(connection: sqlite3.Connection, table_name: str) -> str | None:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    pk_columns = [str(row[1]) for row in rows if int(row[5]) > 0]
    if len(pk_columns) == 1:
        return pk_columns[0]
    return None


def _copy_table_row_by_row(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table_name: str,
    *,
    columns: list[str],
) -> int:
    pk_column = _single_primary_key_column(source, table_name)
    if not pk_column:
        raise sqlite3.DatabaseError(f"{table_name}: no single primary key available for salvage")

    column_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    copied = 0

    key_rows = source.execute(f"SELECT {pk_column} FROM {table_name}").fetchall()
    keys = [row[0] for row in key_rows if row[0] is not None]
    if not keys:
        return 0

    for key in keys:
        try:
            row = source.execute(
                f"SELECT {column_sql} FROM {table_name} WHERE {pk_column} = ?",
                (key,),
            ).fetchone()
        except sqlite3.DatabaseError:
            continue
        if row is None:
            continue
        target.execute(
            f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
            tuple(row),
        )
        copied += 1
    return copied


def _copy_table(source: sqlite3.Connection, target: sqlite3.Connection, table_name: str) -> int:
    columns = _table_columns(source, table_name)
    column_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    try:
        rows = source.execute(f"SELECT {column_sql} FROM {table_name}").fetchall()
    except sqlite3.DatabaseError:
        return _copy_table_row_by_row(source, target, table_name, columns=columns)
    if rows:
        target.executemany(
            f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
            [tuple(row) for row in rows],
        )
    return len(rows)


def main() -> int:
    args = build_parser().parse_args()
    source_path = Path(args.source).expanduser().resolve()
    target_path = Path(args.target).expanduser().resolve()

    if not source_path.exists():
        raise SystemExit(f"source database not found: {source_path}")

    if target_path.exists() and not args.force:
        print(json.dumps({"runtime_db": str(target_path), "prepared": False, "reason": "already exists"}, ensure_ascii=False))
        return 0

    if target_path.exists():
        target_path.unlink()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = connect(target_path)
    copied_counts: dict[str, int] = {}
    skipped_tables: dict[str, str] = {}
    try:
        target.executescript(SCHEMA)
        copied_normalized = False
        for table_name in _user_tables(source):
            if table_name in SKIP_TABLES:
                continue
            try:
                copied_counts[table_name] = _copy_table(source, target, table_name)
            except sqlite3.DatabaseError as exc:
                skipped_tables[table_name] = str(exc)
        try:
            copied_counts["normalized_intelligence_events"] = _copy_table(source, target, "normalized_intelligence_events")
            copied_normalized = copied_counts["normalized_intelligence_events"] > 0
        except sqlite3.DatabaseError as exc:
            skipped_tables["normalized_intelligence_events"] = str(exc)

        if copied_normalized:
            upsert_normalized_intelligence_cache_state(
                target,
                source_signature=_build_source_signature(target),
                event_count=int(copied_counts["normalized_intelligence_events"]),
                refreshed_at=datetime.now().isoformat(),
            )
        else:
            ensure_normalized_intelligence(target, force=True)
        target.commit()
    finally:
        source.close()
        target.close()

    payload = {
        "runtime_db": str(target_path),
        "prepared": True,
        "prepared_at": datetime.now().isoformat(),
        "source_db": str(source_path),
        "copied_counts": copied_counts,
        "skipped_tables": skipped_tables,
    }
    _meta_path(target_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
