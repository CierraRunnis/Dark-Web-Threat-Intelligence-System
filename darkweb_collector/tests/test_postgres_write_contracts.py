from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from darkweb_collector.ai_aggregation.repository import Repository, utc_now
from darkweb_collector.db import (
    begin_write_transaction,
    mark_normalized_intelligence_dirty,
)
from darkweb_collector.postgres_backend import PostgreSQLIntegrityError


@pytest.fixture
def sqlite_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repository:
    monkeypatch.setenv("DARKWEB_COLLECTOR_DATABASE_URL", "")
    monkeypatch.setenv(
        "DARKWEB_ACTIVE_RELEASE_FILE",
        str(tmp_path / "missing-active-release.json"),
    )
    repository = Repository(tmp_path / "collector.db")
    repository.initialize()
    return repository


def _claim_created_at(
    repository: Repository,
    profile_id: str,
    scheduled_for: str,
) -> str:
    with repository.connection() as connection:
        row = connection.execute(
            """
            SELECT created_at
            FROM ai_aggregation_schedule_claims
            WHERE profile_id = ? AND scheduled_for = ?
            """,
            (profile_id, scheduled_for),
        ).fetchone()
    assert row is not None
    return str(row["created_at"])


def test_sqlite_schedule_claim_preserves_existing_contract(
    sqlite_repository: Repository,
) -> None:
    scheduled_for = "2026-08-24T09:00:00+00:00"

    assert sqlite_repository.claim_schedule("profile-a", scheduled_for) is True
    created_at = _claim_created_at(
        sqlite_repository,
        "profile-a",
        scheduled_for,
    )

    assert sqlite_repository.claim_schedule("profile-a", scheduled_for) is False
    assert (
        _claim_created_at(sqlite_repository, "profile-a", scheduled_for)
        == created_at
    )

    sqlite_repository.release_schedule("profile-a", scheduled_for)
    assert sqlite_repository.claim_schedule("profile-a", scheduled_for) is True

    rolled_back_slot = "2026-08-24T09:05:00+00:00"
    with sqlite_repository.connection() as connection:
        begin_write_transaction(connection)
        connection.execute(
            """
            INSERT INTO ai_aggregation_schedule_claims(
                profile_id, scheduled_for, created_at
            ) VALUES (?, ?, ?)
            """,
            ("profile-a", rolled_back_slot, utc_now()),
        )
        connection.rollback()

    assert sqlite_repository.claim_schedule("profile-a", rolled_back_slot) is True


def test_sqlite_schedule_claim_allows_only_one_concurrent_winner(
    sqlite_repository: Repository,
) -> None:
    barrier = Barrier(8)

    def claim() -> bool:
        barrier.wait(timeout=5)
        return sqlite_repository.claim_schedule(
            "profile-concurrent",
            "2026-08-24T10:00:00+00:00",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: claim(), range(8)))

    assert results.count(True) == 1
    assert results.count(False) == 7


class _ReturningCursor:
    def __init__(self, row: dict[str, str] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, str] | None:
        return self._row


class _PostgresClaimConnection:
    backend_name = "postgresql"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...],
    ) -> _ReturningCursor:
        self.calls.append((sql, parameters))
        if len(self.calls) == 2:
            raise PostgreSQLIntegrityError("duplicate schedule claim")
        return _ReturningCursor(None)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_postgres_schedule_claim_uses_shared_integrity_rollback_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository(tmp_path / "unused.db")
    connection = _PostgresClaimConnection()
    monkeypatch.setattr(
        repository,
        "connection",
        lambda: nullcontext(connection),
    )

    assert repository.claim_schedule("profile-pg", "slot") is True
    assert repository.claim_schedule("profile-pg", "slot") is False

    assert connection.commits == 1
    assert connection.rollbacks == 1
    assert len(connection.calls) == 2
    for sql, parameters in connection.calls:
        assert "ON CONFLICT" not in sql
        assert "RETURNING" not in sql
        assert parameters[:2] == ("profile-pg", "slot")


class _PostgresDirtyConnection:
    backend_name = "postgresql"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def execute(
        self,
        sql: str,
        parameters: tuple[str, ...],
    ) -> _ReturningCursor:
        self.calls.append((sql, parameters))
        return _ReturningCursor({"source_revision": "17"})


def test_postgres_dirty_mark_uses_single_function_call() -> None:
    connection = _PostgresDirtyConnection()

    revision = mark_normalized_intelligence_dirty(
        connection,  # type: ignore[arg-type]
        changed_at="2026-08-24T08:00:00+00:00",
    )

    assert revision == 17
    assert len(connection.calls) == 1
    sql, parameters = connection.calls[0]
    assert "SELECT dwti_mark_normalized_dirty(?)" in sql
    assert parameters == ("2026-08-24T08:00:00+00:00",)
