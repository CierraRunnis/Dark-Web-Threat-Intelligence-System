from __future__ import annotations

import json
from typing import Any
from collections.abc import Sequence

from darkweb_collector import db

from _writebench_core import WriteBenchmarkError, _utc_now


class ProductionPaths:
    """Current production business paths (SQLite or PostgreSQL 0005)."""

    def mark_dirty(self, connection, changed_at: str | None = None) -> int:
        return db.mark_normalized_intelligence_dirty(connection, changed_at=changed_at)

    def claim(self, connection, profile_id: str, scheduled_for: str, created_at: str) -> bool:
        try:
            connection.execute(
                "INSERT INTO ai_aggregation_schedule_claims(profile_id, scheduled_for, created_at) "
                "VALUES (?, ?, ?)",
                (profile_id, scheduled_for, created_at),
            )
            return True
        except db.DATABASE_INTEGRITY_ERRORS:
            connection.rollback()
            return False

    def release(self, connection, profile_id: str, scheduled_for: str) -> None:
        connection.execute(
            "DELETE FROM ai_aggregation_schedule_claims WHERE profile_id=? AND scheduled_for=?",
            (profile_id, scheduled_for),
        )

    def upsert_vulnerability(self, connection, payload: dict[str, Any]) -> int:
        return db.upsert_vulnerability_record(connection, payload)

    def upsert_ransomware(self, connection, payload: dict[str, Any]) -> int:
        return db.upsert_ransomware_live_victim(connection, payload)

    def upsert_victim(self, connection, run_id: int, payload: dict[str, Any]) -> int:
        return db.upsert_victim(connection, run_id, payload)

    def insert_victim_detail(self, connection, victim_id: int, payload: dict[str, Any]) -> None:
        db.insert_victim_detail(connection, victim_id, payload)

    def upsert_topic(self, connection, payload: dict[str, Any]) -> int:
        return db.upsert_forum_topic(connection, **payload)

    def upsert_detail(self, connection, payload: dict[str, Any]) -> int:
        return db.upsert_forum_detail(connection, **payload)


class LegacyPostgresPaths(ProductionPaths):
    """The 0004 paths reconstructed from the historical benchmark scripts."""

    def _insert_id(self, connection, sql_text: str, parameters: Sequence[Any]) -> int:
        cursor = connection.execute(sql_text, parameters, return_identity=True)
        if cursor.lastrowid is None:
            raise WriteBenchmarkError("legacy identity insert did not return an id")
        return int(cursor.lastrowid)

    def mark_dirty(self, connection, changed_at: str | None = None) -> int:
        timestamp = changed_at or _utc_now()
        connection.execute(
            """
            INSERT INTO normalized_intelligence_cache_state(
                id, source_signature, event_count, refreshed_at,
                source_revision, applied_revision, dirty_since, dirty_at
            ) VALUES(1, '', 0, '', 1, 0, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                dirty_since=CASE
                    WHEN normalized_intelligence_cache_state.source_revision
                         <= normalized_intelligence_cache_state.applied_revision
                      OR normalized_intelligence_cache_state.dirty_since=''
                    THEN excluded.dirty_since
                    ELSE normalized_intelligence_cache_state.dirty_since
                END,
                source_revision=normalized_intelligence_cache_state.source_revision+1,
                dirty_at=excluded.dirty_at
            """,
            (timestamp, timestamp),
        )
        row = connection.execute(
            "SELECT source_revision FROM normalized_intelligence_cache_state WHERE id=1"
        ).fetchone()
        if row is None:
            raise WriteBenchmarkError("legacy dirty state is unavailable")
        return int(row[0])

    def claim(self, connection, profile_id: str, scheduled_for: str, created_at: str) -> bool:
        try:
            connection.execute(
                "INSERT INTO ai_aggregation_schedule_claims(profile_id, scheduled_for, created_at) "
                "VALUES (?, ?, ?)",
                (profile_id, scheduled_for, created_at),
            )
            return True
        except db.DATABASE_INTEGRITY_ERRORS:
            connection.rollback()
            return False

    def upsert_victim(self, connection, run_id: int, payload: dict[str, Any]) -> int:
        row = connection.execute(
            """
            SELECT id FROM victims
            WHERE site_name=? AND source_url=? AND name=?
              AND COALESCE(domain, '')=COALESCE(?, '') AND status=?
            """,
            (payload["site_name"], payload["source_url"], payload["name"],
             payload.get("domain"), payload["status"]),
        ).fetchone()
        raw_json = json.dumps(payload, ensure_ascii=False)
        if row is not None:
            victim_id = int(row[0])
            connection.execute(
                """
                UPDATE victims
                SET detail_url=?, display_label=?, published_at_utc=?, claimed_size=?,
                    claimed_size_gb=?, content_hash=?, last_seen_run_id=?,
                    last_detail_fetch_status=COALESCE(?, last_detail_fetch_status), raw_json=?
                WHERE id=?
                """,
                (payload.get("detail_url"), payload["display_label"], payload.get("published_at_utc"),
                 payload.get("claimed_size"), payload.get("claimed_size_gb"), payload["content_hash"],
                 run_id, payload.get("last_detail_fetch_status"), raw_json, victim_id),
            )
        else:
            victim_id = self._insert_id(
                connection,
                """
                INSERT INTO victims(
                    site_name, source_url, detail_url, name, display_label, domain, status,
                    published_at_utc, claimed_size, claimed_size_gb, content_hash,
                    first_seen_run_id, last_seen_run_id, last_detail_fetch_status, raw_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (payload["site_name"], payload["source_url"], payload.get("detail_url"), payload["name"],
                 payload["display_label"], payload.get("domain"), payload["status"],
                 payload.get("published_at_utc"), payload.get("claimed_size"),
                 payload.get("claimed_size_gb"), payload["content_hash"], run_id, run_id,
                 payload.get("last_detail_fetch_status"), raw_json),
            )
        self.mark_dirty(connection)
        return victim_id

    def insert_victim_detail(self, connection, victim_id: int, payload: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO victim_details(
                victim_id, fetched_at_utc, fetch_status, page_title,
                text_excerpt, outbound_link_count, raw_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (victim_id, payload["fetched_at_utc"], payload["fetch_status"],
             payload.get("page_title"), payload.get("text_excerpt"),
             payload.get("outbound_link_count"), json.dumps(payload, ensure_ascii=False)),
        )
        self.mark_dirty(connection)

    def upsert_topic(self, connection, payload: dict[str, Any]) -> int:
        row = connection.execute(
            "SELECT id, title, content_hash FROM forum_topics WHERE site_name=? AND section=? AND url=?",
            (payload["site_name"], payload["section"], payload["url"]),
        ).fetchone()
        now = payload.get("collected_at_utc", "") or ""
        raw = json.dumps({key: payload.get(key, "") for key in (
            "site_name", "section", "title", "url", "author", "replies", "views",
            "published_at", "last_reply_at", "content_hash",
        )}, ensure_ascii=False)
        if row is not None:
            topic_id = int(row[0])
            changed = (
                str(row[1] or "") != str(payload["title"])
                or str(row[2] or "") != str(payload["content_hash"])
            )
            connection.execute(
                """
                UPDATE forum_topics SET title=?, author=?, replies=?, views=?, published_at=?,
                    last_reply_at=?, content_hash=?, last_seen_at=?, raw_json=? WHERE id=?
                """,
                (payload["title"], payload.get("author", ""), payload.get("replies", ""),
                 payload.get("views", ""), payload.get("published_at", ""),
                 payload.get("last_reply_at", ""), payload["content_hash"], now, raw, topic_id),
            )
            if changed:
                self.mark_dirty(connection)
            return topic_id
        topic_id = self._insert_id(
            connection,
            """
            INSERT INTO forum_topics(
                site_name, section, title, url, author, replies, views, published_at,
                last_reply_at, content_hash, first_seen_at, last_seen_at, raw_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (payload["site_name"], payload["section"], payload["title"], payload["url"],
             payload.get("author", ""), payload.get("replies", ""), payload.get("views", ""),
             payload.get("published_at", ""), payload.get("last_reply_at", ""),
             payload["content_hash"], now, now, raw),
        )
        self.mark_dirty(connection)
        return topic_id

    def upsert_detail(self, connection, payload: dict[str, Any]) -> int:
        row = connection.execute(
            "SELECT id FROM forum_details WHERE site_name=? AND section=? AND topic_url=?",
            (payload["site_name"], payload["section"], payload["topic_url"]),
        ).fetchone()
        now = payload.get("collected_at_utc", "") or ""
        victims = payload.get("victims", [])
        victims_text = ", ".join(victim["name"] for victim in victims) if victims else ""
        attackers_text = ", ".join(payload.get("attackers", []))
        raw = json.dumps({
            "site_name": payload["site_name"], "section": payload["section"],
            "topic_url": payload["topic_url"], "content": payload.get("content", ""),
            "authors": payload.get("authors", ""), "timestamps": payload.get("timestamps", ""),
            "published_at_utc": payload.get("published_at_utc", ""),
            "attachments": payload.get("attachments", ""), "victims": victims_text,
            "attackers": attackers_text, "content_hash": payload["content_hash"],
        }, ensure_ascii=False)
        if row is not None:
            detail_id = int(row[0])
            connection.execute(
                """
                UPDATE forum_details SET content=?, authors=?, timestamps=?, attachments=?,
                    victims=?, attackers=?, content_hash=?, fetched_at=?, raw_json=? WHERE id=?
                """,
                (payload.get("content", ""), payload.get("authors", ""),
                 payload.get("timestamps", ""), payload.get("attachments", ""), victims_text,
                 attackers_text, payload["content_hash"], now, raw, detail_id),
            )
            connection.execute("DELETE FROM forum_victims WHERE forum_detail_id=?", (detail_id,))
        else:
            detail_id = self._insert_id(
                connection,
                """
                INSERT INTO forum_details(
                    site_name, section, topic_url, content, authors, timestamps, attachments,
                    victims, attackers, content_hash, fetched_at, raw_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (payload["site_name"], payload["section"], payload["topic_url"],
                 payload.get("content", ""), payload.get("authors", ""),
                 payload.get("timestamps", ""), payload.get("attachments", ""), victims_text,
                 attackers_text, payload["content_hash"], now, raw),
            )
        for victim in victims:
            connection.execute(
                "INSERT INTO forum_victims(forum_detail_id, victim_name, industry, region) "
                "VALUES(?, ?, ?, ?)",
                (detail_id, victim["name"], victim.get("industry"), victim.get("region")),
            )
        self.mark_dirty(connection)
        return detail_id

