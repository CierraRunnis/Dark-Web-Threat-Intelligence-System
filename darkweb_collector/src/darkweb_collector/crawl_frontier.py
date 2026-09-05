from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
import time

from darkweb_collector.models import DetailTask


FRONTIER_SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_frontier (
    site_name TEXT NOT NULL,
    target_url TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT '',
    discovery_lane TEXT NOT NULL DEFAULT 'recent',
    metadata_json TEXT NOT NULL,
    observed_version TEXT NOT NULL,
    fetched_version TEXT NOT NULL DEFAULT '',
    claimed_version TEXT NOT NULL DEFAULT '',
    artifacts_complete INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    lease_token TEXT NOT NULL DEFAULT '',
    lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
    next_retry DOUBLE PRECISION NOT NULL DEFAULT 0,
    first_seen_at DOUBLE PRECISION NOT NULL,
    observed_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    last_claimed_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (site_name, target_url)
);
CREATE INDEX IF NOT EXISTS idx_crawl_frontier_pending
ON crawl_frontier(site_name, status, next_retry, lease_until);
CREATE INDEX IF NOT EXISTS idx_crawl_frontier_section
ON crawl_frontier(site_name, discovery_lane, section, last_claimed_at);
CREATE TABLE IF NOT EXISTS crawl_page_cursors (
    site_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    next_page INTEGER NOT NULL DEFAULT 2,
    last_signature TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (site_name, source_url)
);
"""


def ensure_frontier_schema(connection) -> None:
    """Called once during database initialization, never by frontier operations."""
    for statement in FRONTIER_SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def _timestamp(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _task(row, *, claimed: bool = False) -> DetailTask:
    metadata = json.loads(row["metadata_json"])
    metadata["source_version"] = row["observed_version"]
    metadata["section"] = row["section"]
    metadata["discovery_lane"] = row["discovery_lane"]
    if claimed:
        metadata["frontier_token"] = row["lease_token"]
        metadata["frontier_version"] = row["claimed_version"]
        metadata["frontier_artifact_only"] = row["fetched_version"] == row["claimed_version"]
    return DetailTask(row["site_name"], row["target_url"], metadata)


def observe_frontier(connection, site_name: str, detail_tasks: Iterable[DetailTask], now=None) -> int:
    """Remember every discovered version without disturbing an in-flight owner."""
    timestamp = _timestamp(now)
    count = 0
    for task in detail_tasks:
        if task.site_name != site_name:
            raise ValueError("Frontier task site does not match observation site")
        metadata = {key: value for key, value in task.metadata.items() if not key.startswith("frontier_")}
        source_version = str(metadata.get("source_version") or metadata.get("content_hash") or "")
        if not source_version:
            version_metadata = {key: value for key, value in metadata.items() if key != "discovery_lane"}
            source_version = hashlib.sha256(json.dumps(version_metadata, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        metadata["source_version"] = source_version
        section = str(metadata.get("section") or "")
        lane = "backfill" if metadata.get("discovery_lane") == "backfill" else "recent"
        fetched_version = str(task.metadata.get("frontier_fetched_version") or "")
        artifacts_complete = int(bool(fetched_version and task.metadata.get("frontier_artifacts_complete", True)))
        status = "done" if fetched_version == source_version and artifacts_complete else "pending"
        connection.execute(
            """
            INSERT INTO crawl_frontier (
                site_name, target_url, section, discovery_lane, metadata_json,
                observed_version, fetched_version, artifacts_complete, status,
                first_seen_at, observed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site_name, target_url) DO UPDATE SET
                section = excluded.section,
                discovery_lane = CASE WHEN excluded.discovery_lane = 'recent'
                    THEN 'recent' ELSE crawl_frontier.discovery_lane END,
                metadata_json = excluded.metadata_json,
                observed_version = excluded.observed_version,
                observed_at = excluded.observed_at,
                updated_at = excluded.updated_at,
                next_retry = CASE WHEN excluded.observed_version <> crawl_frontier.observed_version
                    THEN 0 ELSE crawl_frontier.next_retry END,
                status = CASE
                    WHEN crawl_frontier.lease_until > excluded.updated_at THEN crawl_frontier.status
                    WHEN excluded.observed_version = crawl_frontier.fetched_version
                        AND crawl_frontier.artifacts_complete = 1 THEN 'done'
                    ELSE 'pending' END
            """,
            (site_name, task.target_url, section, lane, json.dumps(metadata, ensure_ascii=False),
             source_version, fetched_version, artifacts_complete, status, timestamp, timestamp, timestamp),
        )
        count += 1
    return count


def list_frontier_candidates(connection, site_name: str, now=None, limit: int = 1000) -> list[DetailTask]:
    """Round-robin lanes and sections, taking old body work before screenshot retries."""
    timestamp = _timestamp(now)
    rows = connection.execute(
        """
        WITH activity AS (
            SELECT section, discovery_lane, MAX(last_claimed_at) AS served_at
            FROM crawl_frontier WHERE site_name = ? GROUP BY section, discovery_lane
        ), lanes AS (
            SELECT discovery_lane, MAX(served_at) AS lane_served_at
            FROM activity GROUP BY discovery_lane
        ), candidates AS (
            SELECT f.*, a.served_at, l.lane_served_at,
                CASE WHEN f.observed_version = f.fetched_version THEN 1 ELSE 0 END AS artifact_only,
                ROW_NUMBER() OVER (
                    PARTITION BY f.discovery_lane, f.section
                    ORDER BY CASE WHEN f.observed_version = f.fetched_version THEN 1 ELSE 0 END,
                        f.last_claimed_at, f.first_seen_at, f.target_url
                ) AS section_rank
            FROM crawl_frontier f
            JOIN activity a ON a.section = f.section AND a.discovery_lane = f.discovery_lane
            JOIN lanes l ON l.discovery_lane = f.discovery_lane
            WHERE f.site_name = ? AND f.status <> 'done'
                AND f.next_retry <= ? AND f.lease_until <= ?
        ), ranked AS (
            SELECT candidates.*, ROW_NUMBER() OVER (
                PARTITION BY discovery_lane ORDER BY section_rank, served_at, section
            ) AS lane_rank FROM candidates
        )
        SELECT * FROM ranked
        ORDER BY lane_rank, lane_served_at, discovery_lane DESC
        LIMIT ?
        """,
        (site_name, site_name, timestamp, timestamp, max(1, int(limit))),
    ).fetchall()
    return [_task(row) for row in rows]


def claim_frontier(connection, site_name: str, target_url: str, lease_token: str, lease_seconds: float, now=None) -> DetailTask | None:
    if not lease_token:
        raise ValueError("A non-empty frontier lease token is required")
    timestamp = _timestamp(now)
    row = connection.execute(
        """
        UPDATE crawl_frontier SET status = 'queued', lease_token = ?, lease_until = ?,
            claimed_version = observed_version, last_claimed_at = ?, updated_at = ?
        WHERE site_name = ? AND target_url = ? AND status <> 'done'
            AND next_retry <= ? AND lease_until <= ?
        RETURNING *
        """,
        (lease_token, timestamp + max(1, lease_seconds), timestamp, timestamp,
         site_name, target_url, timestamp, timestamp),
    ).fetchone()
    return _task(row, claimed=True) if row is not None else None


def _lease_transition(connection, site_name, target_url, lease_token, lease_seconds, now, *, old_status=None, new_status=None) -> bool:
    timestamp = _timestamp(now)
    status_sql = "status = ?" if old_status else "status IN ('queued', 'running')"
    expires_at = timestamp + max(1, lease_seconds)
    parameters = [expires_at, expires_at, timestamp]
    update_sql = "lease_until = CASE WHEN lease_until > ? THEN lease_until ELSE ? END, updated_at = ?"
    if new_status:
        update_sql += ", status = ?"
        parameters.append(new_status)
    parameters.extend((site_name, target_url, lease_token, timestamp))
    if old_status:
        parameters.append(old_status)
    cursor = connection.execute(
        f"UPDATE crawl_frontier SET {update_sql} WHERE site_name = ? AND target_url = ? "
        f"AND lease_token = ? AND lease_until > ? AND {status_sql}",
        parameters,
    )
    return cursor.rowcount == 1


def start_frontier(connection, site_name, target_url, lease_token, lease_seconds=300, now=None) -> bool:
    return _lease_transition(connection, site_name, target_url, lease_token, lease_seconds, now, old_status="queued", new_status="running")


def renew_frontier(connection, site_name, target_url, lease_token, lease_seconds=300, now=None) -> bool:
    return _lease_transition(connection, site_name, target_url, lease_token, lease_seconds, now)


def retry_frontier(connection, site_name, target_url, lease_token, lease_seconds=3600, now=None) -> bool:
    return _lease_transition(connection, site_name, target_url, lease_token, lease_seconds, now, old_status="running", new_status="queued")


def begin_persist_frontier(connection, site_name, target_url, lease_token, lease_seconds=300, now=None) -> bool:
    """Hold the owner row lock until the caller commits detail persistence + completion."""
    return _lease_transition(connection, site_name, target_url, lease_token, lease_seconds, now, old_status="running")


def complete_frontier(connection, site_name, target_url, lease_token, *, artifacts_complete=True, retry_seconds=300, now=None) -> bool:
    timestamp = _timestamp(now)
    cursor = connection.execute(
        """
        UPDATE crawl_frontier SET fetched_version = claimed_version, artifacts_complete = ?,
            status = CASE WHEN observed_version = claimed_version AND ? = 1 THEN 'done' ELSE 'pending' END,
            next_retry = CASE WHEN observed_version <> claimed_version OR ? = 1 THEN 0 ELSE ? END,
            lease_token = '', lease_until = 0, claimed_version = '', last_error = '', updated_at = ?
        WHERE site_name = ? AND target_url = ? AND lease_token = ?
            AND lease_until > ? AND status = 'running'
        """,
        (int(bool(artifacts_complete)), int(bool(artifacts_complete)), int(bool(artifacts_complete)),
         timestamp + max(0, retry_seconds), timestamp, site_name, target_url, lease_token, timestamp),
    )
    return cursor.rowcount == 1


def fail_frontier(connection, site_name, target_url, lease_token, *, retry_seconds=60, error_message='', now=None) -> bool:
    timestamp = _timestamp(now)
    cursor = connection.execute(
        """
        UPDATE crawl_frontier SET status = 'pending', lease_token = '', lease_until = 0,
            claimed_version = '', next_retry = ?, last_error = ?, updated_at = ?
        WHERE site_name = ? AND target_url = ? AND lease_token = ?
            AND status IN ('queued', 'running')
        """,
        (timestamp + max(0, retry_seconds), str(error_message)[:1000], timestamp, site_name, target_url, lease_token),
    )
    return cursor.rowcount == 1


def count_frontier_pending(connection, site_name: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM crawl_frontier WHERE site_name = ? AND status <> 'done'", (site_name,),
    ).fetchone()
    return int(row[0])


def _sites_filter(site_names, column="site_name"):
    names = list(dict.fromkeys(site_names)) if site_names is not None else None
    if names is None:
        return names, "", []
    if not names:
        return names, " WHERE 1 = 0", []
    return names, f" WHERE {column} IN ({', '.join('?' for _ in names)})", names


def frontier_counts(connection, site_names=None, now=None) -> dict[str, dict[str, int]]:
    names, where, parameters = _sites_filter(site_names)
    timestamp = _timestamp(now)
    rows = connection.execute(
        """
        SELECT site_name, COUNT(*) AS total,
            SUM(CASE WHEN status <> 'done' AND lease_until <= ? THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN status <> 'done' AND lease_until > ? THEN 1 ELSE 0 END) AS inflight,
            SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status <> 'done' AND fetched_version = observed_version
                AND artifacts_complete = 0 THEN 1 ELSE 0 END) AS artifacts_pending
        FROM crawl_frontier
        """ + where + " GROUP BY site_name",
        [timestamp, timestamp, *parameters],
    ).fetchall()
    empty = {key: 0 for key in ("total", "pending", "inflight", "completed", "artifacts_pending")}
    result = {name: dict(empty) for name in names or []}
    for row in rows:
        result[row["site_name"]] = {key: int(row[key]) for key in empty}
    return result


def load_page_cursor(connection, site_name: str, source_url: str) -> dict:
    row = connection.execute(
        "SELECT next_page, last_signature, completed_at, updated_at FROM crawl_page_cursors WHERE site_name = ? AND source_url = ?",
        (site_name, source_url),
    ).fetchone()
    return dict(row) if row is not None else {"next_page": 2, "last_signature": "", "completed_at": "", "updated_at": 0.0}


def save_page_cursor(connection, site_name: str, source_url: str, *, next_page: int, last_signature='', completed_at='', now=None) -> None:
    connection.execute(
        """
        INSERT INTO crawl_page_cursors (site_name, source_url, next_page, last_signature, completed_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(site_name, source_url) DO UPDATE SET next_page = excluded.next_page,
            last_signature = excluded.last_signature, completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
        """,
        (site_name, source_url, max(2, int(next_page)), str(last_signature or ''), str(completed_at or ''), _timestamp(now)),
    )


def list_page_cursors(connection, site_names=None) -> dict[str, list[dict]]:
    names, where, parameters = _sites_filter(site_names)
    rows = connection.execute(
        "SELECT site_name, source_url, next_page, last_signature, completed_at, updated_at FROM crawl_page_cursors"
        + where + " ORDER BY site_name, source_url", parameters,
    ).fetchall()
    result = {name: [] for name in names or []}
    for row in rows:
        result.setdefault(row["site_name"], []).append({key: row[key] for key in row.keys() if key != "site_name"})
    return result
