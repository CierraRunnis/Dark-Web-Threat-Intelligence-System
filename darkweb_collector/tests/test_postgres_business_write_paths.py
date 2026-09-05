from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

import pytest

from darkweb_collector import db
from darkweb_collector.db import (
    get_normalized_intelligence_cache_state,
    upsert_forum_detail,
    upsert_forum_topic,
    upsert_victim,
)


@pytest.fixture
def sqlite_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sqlite3.Connection]:
    monkeypatch.setenv("DARKWEB_COLLECTOR_DATABASE_URL", "")
    monkeypatch.setenv(
        "DARKWEB_ACTIVE_RELEASE_FILE",
        str(tmp_path / "missing-active-release.json"),
    )
    connection = db.connect(tmp_path / "collector.db")
    try:
        yield connection
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def _revision(connection: sqlite3.Connection) -> int:
    state = get_normalized_intelligence_cache_state(connection) or {}
    return int(state.get("source_revision") or 0)


def test_sqlite_victim_contract_preserves_null_key_stable_id_and_rollback(
    sqlite_connection: sqlite3.Connection,
) -> None:
    first_payload = {
        "site_name": "victim-site",
        "source_url": "https://source.invalid/list",
        "detail_url": "https://source.invalid/detail/1",
        "name": "Acme",
        "display_label": "Acme original",
        "domain": None,
        "status": "published",
        "published_at_utc": "2026-08-24T01:00:00+00:00",
        "claimed_size": "10 GB",
        "claimed_size_gb": 10.0,
        "content_hash": "hash-1",
        "last_detail_fetch_status": "ok",
    }
    victim_id = upsert_victim(sqlite_connection, 101, first_payload)
    sqlite_connection.commit()
    first_revision = _revision(sqlite_connection)

    updated_payload = {
        **first_payload,
        "detail_url": "https://source.invalid/detail/2",
        "display_label": "Acme updated",
        "domain": "",
        "claimed_size": "11 GB",
        "claimed_size_gb": 11.0,
        "content_hash": "hash-2",
        "last_detail_fetch_status": None,
    }
    repeated_id = upsert_victim(sqlite_connection, 202, updated_payload)
    sqlite_connection.commit()

    row = sqlite_connection.execute(
        "SELECT * FROM victims WHERE id = ?",
        (victim_id,),
    ).fetchone()
    assert row is not None
    assert repeated_id == victim_id
    assert sqlite_connection.execute("SELECT COUNT(*) FROM victims").fetchone()[0] == 1
    assert row["domain"] is None
    assert row["first_seen_run_id"] == 101
    assert row["last_seen_run_id"] == 202
    assert row["last_detail_fetch_status"] == "ok"
    assert row["display_label"] == "Acme updated"
    assert row["content_hash"] == "hash-2"
    assert row["raw_json"] == json.dumps(updated_payload, ensure_ascii=False)
    assert _revision(sqlite_connection) == first_revision + 1

    committed_row = dict(row)
    committed_revision = _revision(sqlite_connection)
    rollback_payload = {
        **updated_payload,
        "display_label": "must roll back",
        "content_hash": "hash-rollback",
        "last_detail_fetch_status": "failed",
    }
    assert upsert_victim(sqlite_connection, 303, rollback_payload) == victim_id
    sqlite_connection.rollback()

    rolled_back_row = sqlite_connection.execute(
        "SELECT * FROM victims WHERE id = ?",
        (victim_id,),
    ).fetchone()
    assert rolled_back_row is not None
    assert dict(rolled_back_row) == committed_row
    assert _revision(sqlite_connection) == committed_revision


def _topic_kwargs(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "site_name": "forum-site",
        "section": "databases",
        "title": "Original title",
        "url": "https://forum.invalid/topic/1",
        "author": "alice",
        "replies": "1",
        "views": "10",
        "published_at": "2026-08-24",
        "last_reply_at": "",
        "content_hash": "topic-hash-1",
        "collected_at_utc": "2026-08-24T02:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def test_sqlite_forum_topic_only_material_changes_advance_revision(
    sqlite_connection: sqlite3.Connection,
) -> None:
    topic_id = upsert_forum_topic(sqlite_connection, **_topic_kwargs())
    sqlite_connection.commit()
    first_revision = _revision(sqlite_connection)

    same_content = _topic_kwargs(
        author="bob",
        replies="2",
        views="99",
        collected_at_utc="2026-08-24T03:00:00+00:00",
    )
    assert upsert_forum_topic(sqlite_connection, **same_content) == topic_id
    sqlite_connection.commit()
    unchanged_revision = _revision(sqlite_connection)
    row = sqlite_connection.execute(
        "SELECT * FROM forum_topics WHERE id = ?",
        (topic_id,),
    ).fetchone()
    assert row is not None
    assert unchanged_revision == first_revision
    assert row["first_seen_at"] == "2026-08-24T02:00:00+00:00"
    assert row["last_seen_at"] == "2026-08-24T03:00:00+00:00"
    assert row["author"] == "bob"
    assert row["views"] == "99"

    title_changed = _topic_kwargs(
        title="Changed title",
        content_hash="topic-hash-1",
        collected_at_utc="2026-08-24T04:00:00+00:00",
    )
    assert upsert_forum_topic(sqlite_connection, **title_changed) == topic_id
    sqlite_connection.commit()
    assert _revision(sqlite_connection) == unchanged_revision + 1

    hash_changed = {
        **title_changed,
        "content_hash": "topic-hash-2",
        "collected_at_utc": "2026-08-24T05:00:00+00:00",
    }
    assert upsert_forum_topic(sqlite_connection, **hash_changed) == topic_id
    sqlite_connection.commit()
    committed_revision = _revision(sqlite_connection)
    committed_row = dict(
        sqlite_connection.execute(
            "SELECT * FROM forum_topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
    )

    assert upsert_forum_topic(
        sqlite_connection,
        **{
            **hash_changed,
            "title": "must roll back",
            "collected_at_utc": "2026-08-24T06:00:00+00:00",
        },
    ) == topic_id
    sqlite_connection.rollback()

    rolled_back = sqlite_connection.execute(
        "SELECT * FROM forum_topics WHERE id = ?",
        (topic_id,),
    ).fetchone()
    assert rolled_back is not None
    assert dict(rolled_back) == committed_row
    assert _revision(sqlite_connection) == committed_revision


def _forum_victims() -> list[dict[str, str | None]]:
    return [
        {"name": "Acme", "industry": None, "region": "CN"},
        {"name": "Acme", "industry": "", "region": None},
        {"name": "Beta", "industry": "finance", "region": "EU"},
        {"name": "Gamma", "region": ""},
        {"name": "Delta", "industry": None, "region": None},
    ]


def _detail_kwargs(
    victims: list[dict[str, str | None]],
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "site_name": "forum-site",
        "section": "databases",
        "topic_url": "https://forum.invalid/topic/1",
        "content": "detail body",
        "authors": "alice",
        "timestamps": "2026-08-24",
        "published_at_utc": "2026-08-24T01:30:00+00:00",
        "attachments": "https://files.invalid/a.zip",
        "victims": victims,
        "attackers": ["actor-a", "actor-b"],
        "content_hash": "detail-hash-1",
        "collected_at_utc": "2026-08-24T02:30:00+00:00",
    }
    payload.update(overrides)
    return payload


def _child_rows(
    connection: sqlite3.Connection,
    detail_id: int,
) -> list[tuple[str, str | None, str | None]]:
    return [
        (str(row["victim_name"]), row["industry"], row["region"])
        for row in connection.execute(
            """
            SELECT victim_name, industry, region
            FROM forum_victims
            WHERE forum_detail_id = ?
            ORDER BY id
            """,
            (detail_id,),
        ).fetchall()
    ]


def test_sqlite_forum_detail_replaces_ordered_duplicate_children_atomically(
    sqlite_connection: sqlite3.Connection,
) -> None:
    victims = _forum_victims()
    expected_children = [
        ("Acme", None, "CN"),
        ("Acme", "", None),
        ("Beta", "finance", "EU"),
        ("Gamma", None, ""),
        ("Delta", None, None),
    ]

    detail_id = upsert_forum_detail(
        sqlite_connection,
        **_detail_kwargs(victims),
    )
    sqlite_connection.commit()
    first_revision = _revision(sqlite_connection)
    assert _child_rows(sqlite_connection, detail_id) == expected_children

    empty_id = upsert_forum_detail(
        sqlite_connection,
        **_detail_kwargs(
            [],
            content="empty child set",
            content_hash="detail-hash-empty",
            collected_at_utc="2026-08-24T03:30:00+00:00",
        ),
    )
    sqlite_connection.commit()
    assert empty_id == detail_id
    assert _child_rows(sqlite_connection, detail_id) == []
    assert _revision(sqlite_connection) == first_revision + 1

    restored_id = upsert_forum_detail(
        sqlite_connection,
        **_detail_kwargs(
            victims,
            content="restored child set",
            content_hash="detail-hash-restored",
            collected_at_utc="2026-08-24T04:30:00+00:00",
        ),
    )
    sqlite_connection.commit()
    assert restored_id == detail_id
    assert _child_rows(sqlite_connection, detail_id) == expected_children
    assert _revision(sqlite_connection) == first_revision + 2

    parent = sqlite_connection.execute(
        "SELECT * FROM forum_details WHERE id = ?",
        (detail_id,),
    ).fetchone()
    assert parent is not None
    assert parent["victims"] == "Acme, Acme, Beta, Gamma, Delta"
    assert parent["attackers"] == "actor-a, actor-b"

    committed_parent = dict(parent)
    committed_children = _child_rows(sqlite_connection, detail_id)
    committed_revision = _revision(sqlite_connection)
    sqlite_connection.execute(
        """
        CREATE TRIGGER fail_forum_victim_insert
        BEFORE INSERT ON forum_victims
        WHEN NEW.victim_name = 'boom'
        BEGIN
            SELECT RAISE(ABORT, 'injected forum victim failure');
        END
        """
    )
    sqlite_connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected forum victim failure"):
        upsert_forum_detail(
            sqlite_connection,
            **_detail_kwargs(
                [
                    {"name": "replacement", "industry": "one", "region": "A"},
                    {"name": "boom", "industry": None, "region": None},
                ],
                content="must roll back",
                content_hash="detail-hash-rollback",
            ),
        )
    sqlite_connection.rollback()

    rolled_back_parent = sqlite_connection.execute(
        "SELECT * FROM forum_details WHERE id = ?",
        (detail_id,),
    ).fetchone()
    assert rolled_back_parent is not None
    assert dict(rolled_back_parent) == committed_parent
    assert _child_rows(sqlite_connection, detail_id) == committed_children
    assert _revision(sqlite_connection) == committed_revision


class _ReturningCursor:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def fetchone(self) -> dict[str, Any]:
        return self._row


class _PostgresBusinessConnection:
    backend_name = "postgresql"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...],
    ) -> _ReturningCursor:
        self.calls.append((sql, parameters))
        if "dwti_upsert_victim" in sql:
            return _ReturningCursor({"victim_id": "71"})
        if "dwti_upsert_forum_topic" in sql:
            return _ReturningCursor(
                {"topic_id": "72", "materially_changed": True}
            )
        if "dwti_upsert_forum_detail" in sql:
            return _ReturningCursor({"detail_id": "73"})
        raise AssertionError(f"unexpected SQL: {sql}")


def test_postgres_business_paths_use_one_schema_function_call_each(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _PostgresBusinessConnection()
    monkeypatch.setattr(
        db,
        "_normalization_state_timestamp",
        lambda value=None: "2026-08-24T08:00:00+00:00",
    )
    victim_payload = {
        "site_name": "victim-site",
        "source_url": "https://source.invalid/list",
        "detail_url": None,
        "name": "企业甲",
        "display_label": "企业甲",
        "domain": None,
        "status": "published",
        "published_at_utc": "",
        "claimed_size": None,
        "claimed_size_gb": None,
        "content_hash": "victim-hash",
        "last_detail_fetch_status": None,
    }
    victims = _forum_victims()

    assert upsert_victim(connection, 11, victim_payload) == 71  # type: ignore[arg-type]
    assert upsert_forum_topic(
        connection,  # type: ignore[arg-type]
        **_topic_kwargs(),
    ) == 72
    assert upsert_forum_detail(
        connection,  # type: ignore[arg-type]
        **_detail_kwargs(victims),
    ) == 73

    assert len(connection.calls) == 3
    victim_sql, victim_parameters = connection.calls[0]
    assert "dwti_upsert_victim" in victim_sql
    assert len(victim_parameters) == 15
    assert victim_parameters[:8] == (
        11,
        "victim-site",
        "https://source.invalid/list",
        None,
        "企业甲",
        "企业甲",
        None,
        "published",
    )
    assert victim_parameters[13] == json.dumps(
        victim_payload,
        ensure_ascii=False,
    )
    assert victim_parameters[14] == "2026-08-24T08:00:00+00:00"

    topic_sql, topic_parameters = connection.calls[1]
    assert "dwti_upsert_forum_topic" in topic_sql
    assert len(topic_parameters) == 13
    assert topic_parameters[0:4] == (
        "forum-site",
        "databases",
        "Original title",
        "https://forum.invalid/topic/1",
    )
    assert topic_parameters[-1] == "2026-08-24T08:00:00+00:00"

    detail_sql, detail_parameters = connection.calls[2]
    assert "dwti_upsert_forum_detail" in detail_sql
    assert len(detail_parameters) == 14
    assert detail_parameters[7] == "Acme, Acme, Beta, Gamma, Delta"
    assert detail_parameters[8] == "actor-a, actor-b"
    assert json.loads(detail_parameters[12]) == victims
    assert detail_parameters[13] == "2026-08-24T08:00:00+00:00"


@pytest.mark.parametrize("required_field", ["title", "content_hash"])
def test_sqlite_forum_topic_rejects_null_required_material_fields_atomically(
    sqlite_connection: sqlite3.Connection,
    required_field: str,
) -> None:
    topic_id = upsert_forum_topic(sqlite_connection, **_topic_kwargs())
    sqlite_connection.commit()
    committed_revision = _revision(sqlite_connection)
    committed_row = dict(
        sqlite_connection.execute(
            "SELECT * FROM forum_topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
    )
    invalid = {
        **_topic_kwargs(
            collected_at_utc="2026-08-24T09:00:00+00:00",
        ),
        required_field: None,
    }

    with pytest.raises(sqlite3.IntegrityError):
        upsert_forum_topic(sqlite_connection, **invalid)
    sqlite_connection.rollback()

    row = sqlite_connection.execute(
        "SELECT * FROM forum_topics WHERE id = ?",
        (topic_id,),
    ).fetchone()
    assert row is not None
