from __future__ import annotations

from pathlib import Path
import json
import os
import sqlite3
from threading import Lock
import time

from darkweb_collector.runtime import default_db_path


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


_SCHEMA_INIT_LOCK = Lock()
_SCHEMA_INIT_FINGERPRINTS: set[tuple[str, int, int]] = set()


def _has_core_schema(connection: sqlite3.Connection) -> bool:
    required_tables = ("collection_runs", "victims", "victim_details", "normalized_intelligence_events")
    for table_name in required_tables:
        row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if row is None:
            return False
    return True


def _should_skip_wal(db_path: Path) -> bool:
    resolved = db_path.resolve()
    path_text = resolved.as_posix().lower()
    return os.name != "nt" and path_text.startswith("/mnt/")


def _is_transient_open_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "unable to open database file" in message or "disk i/o error" in message


SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    collected_at_utc TEXT NOT NULL,
    victim_count INTEGER NOT NULL,
    run_metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS victims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    detail_url TEXT,
    name TEXT NOT NULL,
    display_label TEXT NOT NULL,
    domain TEXT,
    status TEXT NOT NULL,
    published_at_utc TEXT,
    claimed_size TEXT,
    claimed_size_gb REAL,
    content_hash TEXT NOT NULL,
    first_seen_run_id INTEGER NOT NULL,
    last_seen_run_id INTEGER NOT NULL,
    last_detail_fetch_status TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(site_name, source_url, name, domain, status)
);

CREATE TABLE IF NOT EXISTS victim_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    victim_id INTEGER NOT NULL,
    fetched_at_utc TEXT NOT NULL,
    fetch_status TEXT NOT NULL,
    page_title TEXT,
    text_excerpt TEXT,
    outbound_link_count INTEGER,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forum_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    section TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    author TEXT,
    replies TEXT,
    views TEXT,
    published_at TEXT,
    last_reply_at TEXT,
    content_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE(site_name, section, url)
);

CREATE TABLE IF NOT EXISTS forum_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name TEXT NOT NULL,
    section TEXT NOT NULL,
    topic_url TEXT NOT NULL,
    content TEXT,
    authors TEXT,
    timestamps TEXT,
    attachments TEXT,
    victims TEXT,
    attackers TEXT,
    content_hash TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    UNIQUE(site_name, section, topic_url)
);

CREATE TABLE IF NOT EXISTS forum_victims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forum_detail_id INTEGER NOT NULL,
    victim_name TEXT NOT NULL,
    industry TEXT,
    region TEXT,
    FOREIGN KEY (forum_detail_id) REFERENCES forum_details(id)
);

CREATE TABLE IF NOT EXISTS crawl_jobs (
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
);

CREATE INDEX IF NOT EXISTS idx_crawl_jobs_site_type_status
ON crawl_jobs(site_name, job_type, status);

CREATE INDEX IF NOT EXISTS idx_crawl_jobs_finished_at
ON crawl_jobs(finished_at);

CREATE TABLE IF NOT EXISTS vulnerability_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    cve_id TEXT NOT NULL,
    title TEXT NOT NULL,
    vendor TEXT NOT NULL,
    product TEXT NOT NULL,
    vulnerability_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    cvss REAL,
    is_exploited INTEGER NOT NULL DEFAULT 0,
    has_poc INTEGER NOT NULL DEFAULT 0,
    patch_available INTEGER NOT NULL DEFAULT 0,
    wide_impact INTEGER NOT NULL DEFAULT 0,
    disclosure_time TEXT NOT NULL,
    affected_versions TEXT NOT NULL,
    summary TEXT NOT NULL,
    advisory_url TEXT NOT NULL,
    reference_urls_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(source_name, cve_id)
);

CREATE INDEX IF NOT EXISTS idx_vulnerability_records_cve
ON vulnerability_records(cve_id);

CREATE INDEX IF NOT EXISTS idx_vulnerability_records_time
ON vulnerability_records(disclosure_time);

CREATE TABLE IF NOT EXISTS ransomware_live_victims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    victim_id TEXT NOT NULL UNIQUE,
    group_name TEXT NOT NULL,
    victim_name TEXT NOT NULL,
    website TEXT NOT NULL,
    country_code TEXT NOT NULL,
    activity TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    attacked_at TEXT NOT NULL,
    post_url TEXT NOT NULL,
    permalink TEXT NOT NULL,
    screenshot_url TEXT NOT NULL,
    description TEXT NOT NULL,
    press_url TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ransomware_live_victims_attacked_at
ON ransomware_live_victims(attacked_at);

CREATE INDEX IF NOT EXISTS idx_ransomware_live_victims_discovered_at
ON ransomware_live_victims(discovered_at);

CREATE INDEX IF NOT EXISTS idx_ransomware_live_victims_last_seen_at
ON ransomware_live_victims(last_seen_at);

CREATE TABLE IF NOT EXISTS normalized_intelligence_events (
    event_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    raw_source_type TEXT NOT NULL,
    source_site_name TEXT NOT NULL,
    source_record_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    category TEXT NOT NULL,
    leak_type TEXT NOT NULL,
    title TEXT NOT NULL,
    attacker TEXT NOT NULL,
    victim TEXT NOT NULL,
    victim_key TEXT NOT NULL,
    industry TEXT NOT NULL,
    region TEXT NOT NULL,
    disclosure_time TEXT,
    severity TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    detail_text TEXT NOT NULL,
    mirror_resources_json TEXT NOT NULL,
    screenshot_resources_json TEXT NOT NULL,
    json_preview_url TEXT NOT NULL,
    risk_reasons_json TEXT NOT NULL,
    event_metadata_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_normalized_intelligence_type_time
ON normalized_intelligence_events(event_type, disclosure_time);

CREATE INDEX IF NOT EXISTS idx_normalized_intelligence_attacker
ON normalized_intelligence_events(attacker);

CREATE INDEX IF NOT EXISTS idx_normalized_intelligence_victim_key
ON normalized_intelligence_events(victim_key);

CREATE TABLE IF NOT EXISTS normalized_intelligence_cache_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    source_signature TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitoring_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    category TEXT NOT NULL,
    weight INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    match_mode TEXT NOT NULL DEFAULT 'contains',
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_monitoring_keywords_unique
ON monitoring_keywords(keyword, category);
"""


def _ensure_schema(connection: sqlite3.Connection) -> None:
    for statement in [item.strip() for item in SCHEMA.split(";") if item.strip()]:
        try:
            connection.execute(statement)
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            # Older databases in the workspace may have pre-existing tables with
            # narrower schemas. Ignore index-creation failures that only stem from
            # missing legacy columns so we can still create newly added tables.
            if "no such column" in message:
                continue
            raise


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = db_path.resolve()
    last_error: Exception | None = None
    for attempt in range(1, 6):
        connection = sqlite3.connect(db_path, factory=ManagedConnection, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            skip_wsl_checks = _should_skip_wal(resolved)
            if not skip_wsl_checks:
                try:
                    connection.execute("PRAGMA journal_mode=WAL")
                except sqlite3.OperationalError:
                    # On WSL drvfs mounts, switching journal mode can fail even though the
                    # database itself is readable and writable. Keep SQLite's existing
                    # journal mode in that case so the shared workspace DB remains usable.
                    pass
            stat = resolved.stat()
            fingerprint = (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
            if skip_wsl_checks and stat.st_size > 0:
                _SCHEMA_INIT_FINGERPRINTS.clear()
                _SCHEMA_INIT_FINGERPRINTS.add(fingerprint)
                return connection
            if fingerprint not in _SCHEMA_INIT_FINGERPRINTS:
                with _SCHEMA_INIT_LOCK:
                    if fingerprint not in _SCHEMA_INIT_FINGERPRINTS:
                        _ensure_schema(connection)
                        _SCHEMA_INIT_FINGERPRINTS.clear()
                        _SCHEMA_INIT_FINGERPRINTS.add(fingerprint)
            return connection
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            last_error = exc
            connection.close()
            if not _is_transient_open_error(exc) or attempt == 5:
                raise
            time.sleep(0.2 * attempt)
    assert last_error is not None
    raise last_error


def get_db_connection() -> sqlite3.Connection:
    """Get database connection"""
    return connect(default_db_path())


def insert_collection_run(connection: sqlite3.Connection, payload: dict) -> int:
    cursor = connection.execute(
        """
        INSERT INTO collection_runs (
            site_name, source_url, collected_at_utc, victim_count, run_metadata_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            payload["site_name"],
            payload["source_url"],
            payload["collected_at_utc"],
            payload["victim_count"],
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    return int(cursor.lastrowid)


def upsert_victim(connection: sqlite3.Connection, run_id: int, payload: dict) -> int:
    cursor = connection.execute(
        """
        SELECT id
        FROM victims
        WHERE site_name = ? AND source_url = ? AND name = ? AND ifnull(domain, '') = ifnull(?, '') AND status = ?
        """,
        (
            payload["site_name"],
            payload["source_url"],
            payload["name"],
            payload.get("domain"),
            payload["status"],
        ),
    )
    row = cursor.fetchone()
    raw_json = json.dumps(payload, ensure_ascii=False)
    if row:
        victim_id = int(row[0])
        connection.execute(
            """
            UPDATE victims
            SET detail_url = ?, display_label = ?, published_at_utc = ?, claimed_size = ?,
                claimed_size_gb = ?, content_hash = ?, last_seen_run_id = ?,
                last_detail_fetch_status = COALESCE(?, last_detail_fetch_status), raw_json = ?
            WHERE id = ?
            """,
            (
                payload.get("detail_url"),
                payload["display_label"],
                payload.get("published_at_utc"),
                payload.get("claimed_size"),
                payload.get("claimed_size_gb"),
                payload["content_hash"],
                run_id,
                payload.get("last_detail_fetch_status"),
                raw_json,
                victim_id,
            ),
        )
        return victim_id

    cursor = connection.execute(
        """
        INSERT INTO victims (
            site_name, source_url, detail_url, name, display_label, domain, status, published_at_utc,
            claimed_size, claimed_size_gb, content_hash, first_seen_run_id, last_seen_run_id,
            last_detail_fetch_status, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["site_name"],
            payload["source_url"],
            payload.get("detail_url"),
            payload["name"],
            payload["display_label"],
            payload.get("domain"),
            payload["status"],
            payload.get("published_at_utc"),
            payload.get("claimed_size"),
            payload.get("claimed_size_gb"),
            payload["content_hash"],
            run_id,
            run_id,
            payload.get("last_detail_fetch_status"),
            raw_json,
        ),
    )
    return int(cursor.lastrowid)


def insert_victim_detail(connection: sqlite3.Connection, victim_id: int, payload: dict) -> None:
    connection.execute(
        """
        INSERT INTO victim_details (
            victim_id, fetched_at_utc, fetch_status, page_title, text_excerpt, outbound_link_count, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            victim_id,
            payload["fetched_at_utc"],
            payload["fetch_status"],
            payload.get("page_title"),
            payload.get("text_excerpt"),
            payload.get("outbound_link_count"),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def get_victim_snapshot(
    connection: sqlite3.Connection,
    site_name: str,
    source_url: str,
    name: str,
    domain: str | None,
    status: str,
) -> dict | None:
    cursor = connection.execute(
        """
        SELECT id, content_hash, last_detail_fetch_status
        FROM victims
        WHERE site_name = ? AND source_url = ? AND name = ? AND ifnull(domain, '') = ifnull(?, '') AND status = ?
        """,
        (site_name, source_url, name, domain, status),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def record_victim_detail(
    connection: sqlite3.Connection,
    site_name: str,
    source_url: str,
    name: str,
    domain: str | None,
    status: str,
    detail_payload: dict,
) -> None:
    snapshot = get_victim_snapshot(
        connection,
        site_name=site_name,
        source_url=source_url,
        name=name,
        domain=domain,
        status=status,
    )
    if snapshot is None:
        raise ValueError(f"victim not found for detail persistence: {site_name} {source_url} {name}")

    connection.execute(
        "UPDATE victims SET last_detail_fetch_status = ? WHERE id = ?",
        (detail_payload["fetch_status"], snapshot["id"]),
    )
    insert_victim_detail(connection, int(snapshot["id"]), detail_payload)

def upsert_forum_topic(connection: sqlite3.Connection, **kwargs) -> int:
    """Upsert forum topic"""
    cursor = connection.execute(
        """
        SELECT id
        FROM forum_topics
        WHERE site_name = ? AND section = ? AND url = ?
        """,
        (
            kwargs["site_name"],
            kwargs["section"],
            kwargs["url"],
        ),
    )
    row = cursor.fetchone()
    now = kwargs.get("collected_at_utc", "") or ""
    
    payload = {
        "site_name": kwargs["site_name"],
        "section": kwargs["section"],
        "title": kwargs["title"],
        "url": kwargs["url"],
        "author": kwargs.get("author", ""),
        "replies": kwargs.get("replies", ""),
        "views": kwargs.get("views", ""),
        "published_at": kwargs.get("published_at", ""),
        "last_reply_at": kwargs.get("last_reply_at", ""),
        "content_hash": kwargs["content_hash"]
    }
    
    raw_json = json.dumps(payload, ensure_ascii=False)
    
    if row:
        topic_id = int(row[0])
        connection.execute(
            """
            UPDATE forum_topics
            SET title = ?, author = ?, replies = ?, views = ?, published_at = ?, last_reply_at = ?,
                content_hash = ?, last_seen_at = ?, raw_json = ?
            WHERE id = ?
            """,
            (
                kwargs["title"],
                kwargs.get("author", ""),
                kwargs.get("replies", ""),
                kwargs.get("views", ""),
                kwargs.get("published_at", ""),
                kwargs.get("last_reply_at", ""),
                kwargs["content_hash"],
                now,
                raw_json,
                topic_id,
            ),
        )
        return topic_id

    cursor = connection.execute(
        """
        INSERT INTO forum_topics (
            site_name, section, title, url, author, replies, views, published_at, last_reply_at, content_hash,
            first_seen_at, last_seen_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kwargs["site_name"],
            kwargs["section"],
            kwargs["title"],
            kwargs["url"],
            kwargs.get("author", ""),
            kwargs.get("replies", ""),
            kwargs.get("views", ""),
            kwargs.get("published_at", ""),
            kwargs.get("last_reply_at", ""),
            kwargs["content_hash"],
            now,
            now,
            raw_json,
        ),
    )
    return int(cursor.lastrowid)


def get_forum_topic_snapshot(connection: sqlite3.Connection, site_name: str, section: str, url: str) -> dict | None:
    cursor = connection.execute(
        """
        SELECT id, content_hash, last_seen_at
        FROM forum_topics
        WHERE site_name = ? AND section = ? AND url = ?
        """,
        (site_name, section, url),
    )
    row = cursor.fetchone()
    return dict(row) if row else None

def upsert_forum_detail(connection: sqlite3.Connection, **kwargs) -> int:
    """Upsert forum detail"""
    cursor = connection.execute(
        """
        SELECT id
        FROM forum_details
        WHERE site_name = ? AND section = ? AND topic_url = ?
        """,
        (
            kwargs["site_name"],
            kwargs["section"],
            kwargs["topic_url"],
        ),
    )
    row = cursor.fetchone()
    now = kwargs.get("collected_at_utc", "") or ""
    
    # Get victims and attackers
    victims = kwargs.get("victims", [])
    attackers = kwargs.get("attackers", [])
    
    # Convert to string for storage
    victims_str = ", ".join([v['name'] for v in victims]) if victims else ""
    attackers_str = ", ".join(attackers) if attackers else ""
    
    payload = {
        "site_name": kwargs["site_name"],
        "section": kwargs["section"],
        "topic_url": kwargs["topic_url"],
        "content": kwargs.get("content", ""),
        "authors": kwargs.get("authors", ""),
        "timestamps": kwargs.get("timestamps", ""),
        "published_at_utc": kwargs.get("published_at_utc", ""),
        "attachments": kwargs.get("attachments", ""),
        "victims": victims_str,
        "attackers": attackers_str,
        "content_hash": kwargs["content_hash"]
    }
    
    raw_json = json.dumps(payload, ensure_ascii=False)
    
    if row:
        detail_id = int(row[0])
        connection.execute(
            """
            UPDATE forum_details
            SET content = ?, authors = ?, timestamps = ?, attachments = ?, victims = ?, attackers = ?, content_hash = ?, fetched_at = ?, raw_json = ?
            WHERE id = ?
            """,
            (
                kwargs.get("content", ""),
                kwargs.get("authors", ""),
                kwargs.get("timestamps", ""),
                kwargs.get("attachments", ""),
                victims_str,
                attackers_str,
                kwargs["content_hash"],
                now,
                raw_json,
                detail_id,
            ),
        )
        
        # Update victim details
        connection.execute("DELETE FROM forum_victims WHERE forum_detail_id = ?", (detail_id,))
        for victim in victims:
            connection.execute(
                """
                INSERT INTO forum_victims (forum_detail_id, victim_name, industry, region)
                VALUES (?, ?, ?, ?)
                """,
                (detail_id, victim['name'], victim.get('industry'), victim.get('region'))
            )
        
        return detail_id

    cursor = connection.execute(
        """
        INSERT INTO forum_details (
            site_name, section, topic_url, content, authors, timestamps, attachments, victims, attackers, content_hash, fetched_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kwargs["site_name"],
            kwargs["section"],
            kwargs["topic_url"],
            kwargs.get("content", ""),
            kwargs.get("authors", ""),
            kwargs.get("timestamps", ""),
            kwargs.get("attachments", ""),
            victims_str,
            attackers_str,
            kwargs["content_hash"],
            now,
            raw_json,
        ),
    )
    
    detail_id = int(cursor.lastrowid)
    
    # Insert victim details
    for victim in victims:
        connection.execute(
            """
            INSERT INTO forum_victims (forum_detail_id, victim_name, industry, region)
            VALUES (?, ?, ?, ?)
            """,
            (detail_id, victim['name'], victim.get('industry'), victim.get('region'))
        )
    
    return detail_id


def get_forum_detail_snapshot(connection: sqlite3.Connection, site_name: str, section: str, topic_url: str) -> dict | None:
    cursor = connection.execute(
        """
        SELECT id, content_hash, fetched_at
        FROM forum_details
        WHERE site_name = ? AND section = ? AND topic_url = ?
        """,
        (site_name, section, topic_url),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def upsert_crawl_job(connection: sqlite3.Connection, **kwargs) -> None:
    connection.execute(
        """
        INSERT INTO crawl_jobs (
            job_id, site_name, job_type, queue_name, target, status,
            enqueued_at, started_at, finished_at, duration_ms, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            site_name = excluded.site_name,
            job_type = excluded.job_type,
            queue_name = excluded.queue_name,
            target = excluded.target,
            status = excluded.status,
            enqueued_at = COALESCE(excluded.enqueued_at, crawl_jobs.enqueued_at),
            started_at = COALESCE(excluded.started_at, crawl_jobs.started_at),
            finished_at = COALESCE(excluded.finished_at, crawl_jobs.finished_at),
            duration_ms = COALESCE(excluded.duration_ms, crawl_jobs.duration_ms),
            error_message = excluded.error_message
        """,
        (
            kwargs["job_id"],
            kwargs["site_name"],
            kwargs["job_type"],
            kwargs["queue_name"],
            kwargs["target"],
            kwargs["status"],
            kwargs.get("enqueued_at"),
            kwargs.get("started_at"),
            kwargs.get("finished_at"),
            kwargs.get("duration_ms"),
            kwargs.get("error_message"),
        ),
    )


def upsert_vulnerability_record(connection: sqlite3.Connection, payload: dict) -> int:
    raw_json = json.dumps(payload, ensure_ascii=False)
    reference_urls_json = json.dumps(payload.get("reference_urls") or [], ensure_ascii=False)
    affected_versions = payload.get("affected_versions") or []
    if isinstance(affected_versions, list):
        affected_versions_text = json.dumps(affected_versions, ensure_ascii=False)
    else:
        affected_versions_text = str(affected_versions)

    cursor = connection.execute(
        """
        SELECT id
        FROM vulnerability_records
        WHERE source_name = ? AND cve_id = ?
        """,
        (
            payload["source_name"],
            payload["cve_id"],
        ),
    )
    row = cursor.fetchone()
    if row:
        record_id = int(row[0])
        connection.execute(
            """
            UPDATE vulnerability_records
            SET source_type = ?, title = ?, vendor = ?, product = ?, vulnerability_type = ?, severity = ?,
                cvss = ?, is_exploited = ?, has_poc = ?, patch_available = ?, wide_impact = ?,
                disclosure_time = ?, affected_versions = ?, summary = ?, advisory_url = ?,
                reference_urls_json = ?, raw_json = ?, last_seen_at = ?
            WHERE id = ?
            """,
            (
                payload.get("source_type", "public"),
                payload.get("title", ""),
                payload.get("vendor", ""),
                payload.get("product", ""),
                payload.get("vulnerability_type", ""),
                payload.get("severity", ""),
                payload.get("cvss"),
                int(bool(payload.get("is_exploited"))),
                int(bool(payload.get("has_poc"))),
                int(bool(payload.get("patch_available"))),
                int(bool(payload.get("wide_impact"))),
                payload.get("disclosure_time", ""),
                affected_versions_text,
                payload.get("summary", ""),
                payload.get("advisory_url", ""),
                reference_urls_json,
                raw_json,
                payload.get("last_seen_at") or payload.get("disclosure_time") or "",
                record_id,
            ),
        )
        return record_id

    cursor = connection.execute(
        """
        INSERT INTO vulnerability_records (
            source_name, source_type, cve_id, title, vendor, product, vulnerability_type, severity,
            cvss, is_exploited, has_poc, patch_available, wide_impact, disclosure_time,
            affected_versions, summary, advisory_url, reference_urls_json, raw_json, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["source_name"],
            payload.get("source_type", "public"),
            payload["cve_id"],
            payload.get("title", ""),
            payload.get("vendor", ""),
            payload.get("product", ""),
            payload.get("vulnerability_type", ""),
            payload.get("severity", ""),
            payload.get("cvss"),
            int(bool(payload.get("is_exploited"))),
            int(bool(payload.get("has_poc"))),
            int(bool(payload.get("patch_available"))),
            int(bool(payload.get("wide_impact"))),
            payload.get("disclosure_time", ""),
            affected_versions_text,
            payload.get("summary", ""),
            payload.get("advisory_url", ""),
            reference_urls_json,
            raw_json,
            payload.get("last_seen_at") or payload.get("disclosure_time") or "",
        ),
    )
    return int(cursor.lastrowid)


def list_vulnerability_records(connection: sqlite3.Connection) -> list[dict]:
    cursor = connection.execute(
        """
        SELECT id, source_name, source_type, cve_id, title, vendor, product, vulnerability_type,
               severity, cvss, is_exploited, has_poc, patch_available, wide_impact,
               disclosure_time, affected_versions, summary, advisory_url, reference_urls_json,
               raw_json, last_seen_at
        FROM vulnerability_records
        ORDER BY datetime(disclosure_time) DESC, id DESC
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def replace_vulnerability_records(connection: sqlite3.Connection, rows: list[dict]) -> None:
    connection.execute("DELETE FROM vulnerability_records")
    for row in rows:
        upsert_vulnerability_record(connection, row)


def upsert_ransomware_live_victim(connection: sqlite3.Connection, payload: dict) -> int:
    raw_json = payload.get("raw_json")
    if isinstance(raw_json, str):
        raw_json_text = raw_json
    else:
        raw_json_text = json.dumps(raw_json if raw_json is not None else payload, ensure_ascii=False)

    cursor = connection.execute(
        """
        SELECT id
        FROM ransomware_live_victims
        WHERE victim_id = ?
        """,
        (payload["victim_id"],),
    )
    row = cursor.fetchone()
    if row:
        record_id = int(row[0])
        connection.execute(
            """
            UPDATE ransomware_live_victims
            SET group_name = ?, victim_name = ?, website = ?, country_code = ?, activity = ?,
                discovered_at = ?, attacked_at = ?, post_url = ?, permalink = ?, screenshot_url = ?,
                description = ?, press_url = ?, raw_json = ?, last_seen_at = ?
            WHERE id = ?
            """,
            (
                payload.get("group_name", ""),
                payload.get("victim_name", ""),
                payload.get("website", ""),
                payload.get("country_code", ""),
                payload.get("activity", ""),
                payload.get("discovered_at", ""),
                payload.get("attacked_at", ""),
                payload.get("post_url", ""),
                payload.get("permalink", ""),
                payload.get("screenshot_url", ""),
                payload.get("description", ""),
                payload.get("press_url", ""),
                raw_json_text,
                payload.get("last_seen_at", ""),
                record_id,
            ),
        )
        return record_id

    cursor = connection.execute(
        """
        INSERT INTO ransomware_live_victims (
            victim_id, group_name, victim_name, website, country_code, activity,
            discovered_at, attacked_at, post_url, permalink, screenshot_url,
            description, press_url, raw_json, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["victim_id"],
            payload.get("group_name", ""),
            payload.get("victim_name", ""),
            payload.get("website", ""),
            payload.get("country_code", ""),
            payload.get("activity", ""),
            payload.get("discovered_at", ""),
            payload.get("attacked_at", ""),
            payload.get("post_url", ""),
            payload.get("permalink", ""),
            payload.get("screenshot_url", ""),
            payload.get("description", ""),
            payload.get("press_url", ""),
            raw_json_text,
            payload.get("last_seen_at", ""),
        ),
    )
    return int(cursor.lastrowid)


def list_ransomware_live_victims(connection: sqlite3.Connection) -> list[dict]:
    cursor = connection.execute(
        """
        SELECT id, victim_id, group_name, victim_name, website, country_code, activity,
               discovered_at, attacked_at, post_url, permalink, screenshot_url,
               description, press_url, raw_json, last_seen_at
        FROM ransomware_live_victims
        ORDER BY datetime(COALESCE(attacked_at, discovered_at)) DESC, id DESC
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def get_ransomware_live_sync_state(connection: sqlite3.Connection) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count,
               MAX(last_seen_at) AS latest_seen_at,
               MAX(COALESCE(attacked_at, discovered_at)) AS latest_disclosure_time
        FROM ransomware_live_victims
        """
    ).fetchone()
    if row is None:
        return {
            "count": 0,
            "latest_seen_at": "",
            "latest_disclosure_time": "",
        }
    return dict(row)


def get_last_successful_crawl_job(connection: sqlite3.Connection, site_name: str, job_type: str) -> dict | None:
    cursor = connection.execute(
        """
        SELECT job_id, status, finished_at
        FROM crawl_jobs
        WHERE site_name = ? AND job_type = ? AND status = 'succeeded'
        ORDER BY datetime(finished_at) DESC
        LIMIT 1
        """,
        (site_name, job_type),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_active_crawl_job(connection: sqlite3.Connection, site_name: str, job_type: str) -> dict | None:
    cursor = connection.execute(
        """
        SELECT job_id, status, queue_name, target, started_at, enqueued_at, finished_at, error_message
        FROM crawl_jobs
        WHERE site_name = ? AND job_type = ? AND status IN ('enqueued', 'running')
        ORDER BY COALESCE(started_at, enqueued_at) DESC
        LIMIT 1
        """,
        (site_name, job_type),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def list_crawl_jobs(connection: sqlite3.Connection, limit: int = 20) -> list[dict]:
    cursor = connection.execute(
        """
        SELECT job_id, site_name, job_type, queue_name, target, status,
               enqueued_at, started_at, finished_at, duration_ms, error_message
        FROM crawl_jobs
        ORDER BY COALESCE(finished_at, started_at, enqueued_at) DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def replace_normalized_intelligence_events(
    connection: sqlite3.Connection,
    rows: list[dict],
) -> None:
    connection.execute("DELETE FROM normalized_intelligence_events")
    connection.executemany(
        """
        INSERT INTO normalized_intelligence_events (
            event_id, source_kind, raw_source_type, source_site_name, source_record_id,
            event_type, category, leak_type, title, attacker, victim, victim_key,
            industry, region, disclosure_time, severity, risk_score, source_url,
            detail_text, mirror_resources_json, screenshot_resources_json,
            json_preview_url, risk_reasons_json, event_metadata_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["event_id"],
                row["source_kind"],
                row["raw_source_type"],
                row["source_site_name"],
                row["source_record_id"],
                row["event_type"],
                row["category"],
                row["leak_type"],
                row["title"],
                row["attacker"],
                row["victim"],
                row["victim_key"],
                row["industry"],
                row["region"],
                row.get("disclosure_time"),
                row["severity"],
                row["risk_score"],
                row["source_url"],
                row["detail_text"],
                row["mirror_resources_json"],
                row["screenshot_resources_json"],
                row["json_preview_url"],
                row["risk_reasons_json"],
                row["event_metadata_json"],
                row["updated_at"],
            )
            for row in rows
        ],
    )


def list_normalized_intelligence_events(connection: sqlite3.Connection) -> list[dict]:
    cursor = connection.execute(
        """
        SELECT event_id, source_kind, raw_source_type, source_site_name, source_record_id,
               event_type, category, leak_type, title, attacker, victim, victim_key,
               industry, region, disclosure_time, severity, risk_score, source_url,
               detail_text, mirror_resources_json, screenshot_resources_json,
               json_preview_url, risk_reasons_json, event_metadata_json, updated_at
        FROM normalized_intelligence_events
        ORDER BY COALESCE(disclosure_time, updated_at) DESC, event_id DESC
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def get_normalized_intelligence_event(
    connection: sqlite3.Connection,
    event_id: str,
) -> dict | None:
    cursor = connection.execute(
        """
        SELECT event_id, source_kind, raw_source_type, source_site_name, source_record_id,
               event_type, category, leak_type, title, attacker, victim, victim_key,
               industry, region, disclosure_time, severity, risk_score, source_url,
               detail_text, mirror_resources_json, screenshot_resources_json,
               json_preview_url, risk_reasons_json, event_metadata_json, updated_at
        FROM normalized_intelligence_events
        WHERE event_id = ?
        """,
        (event_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_normalized_intelligence_cache_state(connection: sqlite3.Connection) -> dict | None:
    cursor = connection.execute(
        """
        SELECT id, source_signature, event_count, refreshed_at
        FROM normalized_intelligence_cache_state
        WHERE id = 1
        """
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def upsert_normalized_intelligence_cache_state(
    connection: sqlite3.Connection,
    *,
    source_signature: str,
    event_count: int,
    refreshed_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO normalized_intelligence_cache_state (id, source_signature, event_count, refreshed_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            source_signature = excluded.source_signature,
            event_count = excluded.event_count,
            refreshed_at = excluded.refreshed_at
        """,
        (source_signature, event_count, refreshed_at),
    )


def list_monitoring_keywords(connection: sqlite3.Connection) -> list[dict]:
    cursor = connection.execute(
        """
        SELECT id, keyword, category, weight, enabled, match_mode, updated_at
        FROM monitoring_keywords
        ORDER BY category, keyword
        """
    )
    rows = []
    for row in cursor.fetchall():
        payload = dict(row)
        payload["enabled"] = bool(payload.get("enabled"))
        rows.append(payload)
    return rows


def replace_monitoring_keywords(connection: sqlite3.Connection, rows: list[dict]) -> None:
    connection.execute("DELETE FROM monitoring_keywords")
    if not rows:
        return
    connection.executemany(
        """
        INSERT INTO monitoring_keywords (
            keyword, category, weight, enabled, match_mode, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                str(row.get("keyword") or "").strip(),
                str(row.get("category") or "").strip(),
                int(row.get("weight") or 0),
                int(bool(row.get("enabled", True))),
                str(row.get("match_mode") or "contains").strip() or "contains",
                str(row.get("updated_at") or ""),
            )
            for row in rows
            if str(row.get("keyword") or "").strip()
        ],
    )
