from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.db import get_db_connection
from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence
from darkweb_collector.runtime import project_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delete all persisted data for a collector site and rebuild normalized events.")
    parser.add_argument("--site", required=True, help="Site name to delete, for example: dragonforce")
    parser.add_argument("--keep-output", action="store_true", help="Keep output/<site> artifacts on disk.")
    return parser


def _output_dir_for_site(site_name: str) -> Path:
    return (project_root() / "output" / site_name).resolve()


def _assert_output_dir(path: Path) -> None:
    output_root = (project_root() / "output").resolve()
    path.relative_to(output_root)


def _count(connection, sql: str, params: tuple[object, ...]) -> int:
    row = connection.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def _rebuild_crawl_jobs_without_site(connection, site_name: str) -> None:
    rows = connection.execute(
        """
        SELECT id, job_id, site_name, job_type, queue_name, target, status,
               enqueued_at, started_at, finished_at, duration_ms, error_message
        FROM crawl_jobs
        WHERE site_name <> ?
        ORDER BY id ASC
        """,
        (site_name,),
    ).fetchall()

    connection.execute("DROP INDEX IF EXISTS idx_crawl_jobs_site_type_status")
    connection.execute("DROP INDEX IF EXISTS idx_crawl_jobs_finished_at")
    connection.execute("DROP TABLE IF EXISTS crawl_jobs")
    connection.execute(
        """
        CREATE TABLE crawl_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL UNIQUE,
            site_name TEXT NOT NULL,
            job_type TEXT NOT NULL,
            queue_name TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            enqueued_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            duration_ms INTEGER,
            error_message TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_crawl_jobs_site_type_status
        ON crawl_jobs(site_name, job_type, status)
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_crawl_jobs_finished_at
        ON crawl_jobs(finished_at)
        """
    )

    if rows:
        connection.executemany(
            """
            INSERT INTO crawl_jobs (
                id, job_id, site_name, job_type, queue_name, target, status,
                enqueued_at, started_at, finished_at, duration_ms, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [tuple(row) for row in rows],
        )


def delete_site_rows(connection, site_name: str) -> dict[str, int]:
    victim_ids = [
        row[0]
        for row in connection.execute(
            "SELECT id FROM victims WHERE site_name = ?",
            (site_name,),
        ).fetchall()
    ]
    forum_detail_ids = [
        row[0]
        for row in connection.execute(
            "SELECT id FROM forum_details WHERE site_name = ?",
            (site_name,),
        ).fetchall()
    ]

    summary = {
        "collection_runs": _count(connection, "SELECT COUNT(*) FROM collection_runs WHERE site_name = ?", (site_name,)),
        "crawl_jobs": _count(connection, "SELECT COUNT(*) FROM crawl_jobs WHERE site_name = ?", (site_name,)),
        "victims": len(victim_ids),
        "victim_details": _count(
            connection,
            f"SELECT COUNT(*) FROM victim_details WHERE victim_id IN ({','.join('?' for _ in victim_ids)})" if victim_ids else "SELECT 0",
            tuple(victim_ids),
        ),
        "forum_topics": _count(connection, "SELECT COUNT(*) FROM forum_topics WHERE site_name = ?", (site_name,)),
        "forum_details": len(forum_detail_ids),
        "forum_victims": _count(
            connection,
            f"SELECT COUNT(*) FROM forum_victims WHERE forum_detail_id IN ({','.join('?' for _ in forum_detail_ids)})" if forum_detail_ids else "SELECT 0",
            tuple(forum_detail_ids),
        ),
        "normalized_events_before_rebuild": _count(
            connection,
            "SELECT COUNT(*) FROM normalized_intelligence_events WHERE source_site_name = ?",
            (site_name,),
        ),
    }

    if forum_detail_ids:
        connection.execute(
            f"DELETE FROM forum_victims WHERE forum_detail_id IN ({','.join('?' for _ in forum_detail_ids)})",
            tuple(forum_detail_ids),
        )
    connection.execute("DELETE FROM forum_details WHERE site_name = ?", (site_name,))
    connection.execute("DELETE FROM forum_topics WHERE site_name = ?", (site_name,))

    if victim_ids:
        connection.execute(
            f"DELETE FROM victim_details WHERE victim_id IN ({','.join('?' for _ in victim_ids)})",
            tuple(victim_ids),
        )
    connection.execute("DELETE FROM victims WHERE site_name = ?", (site_name,))

    connection.execute("DELETE FROM collection_runs WHERE site_name = ?", (site_name,))
    try:
        connection.execute("DELETE FROM crawl_jobs WHERE site_name = ?", (site_name,))
    except sqlite3.DatabaseError as exc:
        if "malformed" not in str(exc).lower():
            raise
        _rebuild_crawl_jobs_without_site(connection, site_name)
    connection.execute("DELETE FROM normalized_intelligence_events WHERE source_site_name = ?", (site_name,))
    connection.execute("DELETE FROM normalized_intelligence_cache_state")

    return summary


def main() -> int:
    args = build_parser().parse_args()
    site_name = args.site.strip()

    output_dir = _output_dir_for_site(site_name)
    _assert_output_dir(output_dir)

    with get_db_connection() as connection:
        summary = delete_site_rows(connection, site_name)
        connection.commit()
        rebuilt_events = ensure_normalized_intelligence(connection, force=True)
        summary["normalized_events_after_rebuild"] = sum(
            1 for item in rebuilt_events if str(item.get("source_site_name") or "") == site_name
        )
        connection.commit()

    if not args.keep_output and output_dir.exists():
        shutil.rmtree(output_dir)
        summary["output_dir_removed"] = 1
    else:
        summary["output_dir_removed"] = 0

    print(json.dumps({"site_name": site_name, **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
