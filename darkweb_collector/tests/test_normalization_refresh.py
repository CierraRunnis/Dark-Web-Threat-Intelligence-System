from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import os
from pathlib import Path
import sys
import tempfile
from threading import Event, Lock
import time
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import api_data, normalizer_service, ransomware_live
from darkweb_collector.cli import build_parser
from darkweb_collector.db import (
    get_db_connection,
    get_normalized_intelligence_cache_state,
    get_readonly_db_connection,
    mark_normalized_intelligence_dirty,
    replace_normalized_intelligence_events,
    upsert_normalized_intelligence_cache_state,
)
from darkweb_collector.normalized_intelligence import refresh_normalized_intelligence


class NormalizationRefreshTests(unittest.TestCase):
    def _env(self, db_path: Path) -> dict[str, str]:
        return {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}

    def _state(self) -> dict:
        with get_readonly_db_connection() as connection:
            return get_normalized_intelligence_cache_state(connection) or {}

    def _normalized_row(self, *, event_id: str = "forum:test:databases:snapshot", title: str = "Snapshot A") -> dict:
        return {
            "event_id": event_id,
            "source_kind": "data_leak",
            "raw_source_type": "forum",
            "source_site_name": "test",
            "source_record_id": "1",
            "event_type": "data_leak",
            "category": "数据库泄露",
            "leak_type": "database",
            "title": title,
            "attacker": "actor",
            "victim": "Acme Energy",
            "victim_key": "acme-energy",
            "industry": "energy",
            "region": "asia",
            "disclosure_time": "2026-07-28T00:00:00+00:00",
            "severity": "high",
            "risk_score": 80,
            "source_url": "https://example.invalid/thread",
            "detail_text": "Snapshot detail",
            "mirror_resources_json": "[]",
            "screenshot_resources_json": "[]",
            "json_preview_url": "",
            "risk_reasons_json": "[]",
            "event_metadata_json": "{}",
            "updated_at": "2026-07-28T00:00:00+00:00",
        }

    def _install_snapshot(self, connection, *, title: str = "Snapshot A") -> None:
        replace_normalized_intelligence_events(
            connection,
            [self._normalized_row(title=title)],
        )
        upsert_normalized_intelligence_cache_state(
            connection,
            source_signature="snapshot-a",
            event_count=1,
            refreshed_at="2026-07-28T00:00:00+00:00",
        )
        connection.commit()

    def test_source_write_and_revision_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                with get_db_connection():
                    pass

                writer = get_db_connection()
                try:
                    writer.execute(
                        """
                        INSERT INTO forum_topics (
                            site_name, section, title, url, author, replies, views,
                            published_at, last_reply_at, content_hash, first_seen_at,
                            last_seen_at, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "test",
                            "databases",
                            "Atomic topic",
                            "https://example.invalid/atomic",
                            "poster",
                            "0",
                            "1",
                            "2026-07-28",
                            "",
                            "hash",
                            "2026-07-28T00:00:00+00:00",
                            "2026-07-28T00:00:00+00:00",
                            "{}",
                        ),
                    )
                    target_revision = mark_normalized_intelligence_dirty(writer)

                    with get_readonly_db_connection() as reader:
                        self.assertEqual(
                            0,
                            reader.execute(
                                "SELECT COUNT(*) FROM forum_topics WHERE url = ?",
                                ("https://example.invalid/atomic",),
                            ).fetchone()[0],
                        )
                        uncommitted_state = get_normalized_intelligence_cache_state(reader) or {}
                    self.assertLess(
                        int(uncommitted_state.get("source_revision") or 0),
                        target_revision,
                    )
                    writer.rollback()
                finally:
                    writer.close()

                with get_readonly_db_connection() as reader:
                    self.assertEqual(
                        0,
                        reader.execute(
                            "SELECT COUNT(*) FROM forum_topics WHERE url = ?",
                            ("https://example.invalid/atomic",),
                        ).fetchone()[0],
                    )
                    rolled_back_state = get_normalized_intelligence_cache_state(reader) or {}
                self.assertLess(
                    int(rolled_back_state.get("source_revision") or 0),
                    target_revision,
                )

                with get_db_connection() as connection:
                    connection.execute(
                        """
                        INSERT INTO forum_topics (
                            site_name, section, title, url, author, replies, views,
                            published_at, last_reply_at, content_hash, first_seen_at,
                            last_seen_at, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "test",
                            "databases",
                            "Atomic topic",
                            "https://example.invalid/atomic",
                            "poster",
                            "0",
                            "1",
                            "2026-07-28",
                            "",
                            "hash",
                            "2026-07-28T00:00:00+00:00",
                            "2026-07-28T00:00:00+00:00",
                            "{}",
                        ),
                    )
                    committed_revision = mark_normalized_intelligence_dirty(connection)
                    connection.commit()

                with get_readonly_db_connection() as reader:
                    self.assertEqual(
                        1,
                        reader.execute(
                            "SELECT COUNT(*) FROM forum_topics WHERE url = ?",
                            ("https://example.invalid/atomic",),
                        ).fetchone()[0],
                    )
                    committed_state = get_normalized_intelligence_cache_state(reader) or {}
                self.assertEqual(
                    committed_revision,
                    int(committed_state.get("source_revision") or 0),
                )

    def test_target_revision_preserves_newer_dirty_revision_for_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                with get_db_connection() as connection:
                    first_revision = mark_normalized_intelligence_dirty(connection)
                    second_revision = mark_normalized_intelligence_dirty(connection)
                    connection.commit()

                with get_db_connection() as connection:
                    refresh_normalized_intelligence(
                        connection,
                        target_revision=first_revision,
                    )

                state_after_first = self._state()
                self.assertEqual(
                    second_revision,
                    int(state_after_first.get("source_revision") or 0),
                )
                self.assertEqual(
                    first_revision,
                    int(state_after_first.get("applied_revision") or 0),
                )

                normalizer_service.refresh_pending_normalization(
                    debounce_seconds=0,
                    max_delay_seconds=0,
                    db_path=db_path,
                )
                state_after_follow_up = self._state()
                self.assertEqual(
                    second_revision,
                    int(state_after_follow_up.get("applied_revision") or 0),
                )

    def test_ransomware_sync_marks_dirty_even_when_legacy_refresh_flag_is_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            record = {
                "victim_id": "victim-1",
                "group_name": "test-group",
                "victim_name": "Acme Energy",
                "discovered_at": "2026-07-28T00:00:00+00:00",
                "last_seen_at": "2026-07-28T00:00:00+00:00",
            }
            with patch.dict(os.environ, self._env(db_path), clear=False):
                with patch.object(
                    ransomware_live,
                    "fetch_recent_ransomware_live_victims",
                    return_value=([record], {"count": 1}),
                ):
                    ransomware_live.sync_ransomware_live_victims(
                        refresh_normalized=False,
                    )

                state = self._state()
                self.assertGreater(
                    int(state.get("source_revision") or 0),
                    int(state.get("applied_revision") or 0),
                )

    def test_normalizer_cli_uses_frozen_service_defaults(self) -> None:
        args = build_parser().parse_args(["normalizer"])
        self.assertFalse(args.once)
        self.assertFalse(args.force)
        self.assertEqual(5, args.poll_seconds)
        self.assertEqual(60, args.debounce_seconds)
        self.assertEqual(300, args.max_delay_seconds)

    def test_ai_reads_previous_snapshot_without_refresh_or_default_keyword_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                with get_db_connection() as connection:
                    self._install_snapshot(connection)
                    mark_normalized_intelligence_dirty(connection)
                    connection.commit()

                with patch(
                    "darkweb_collector.normalized_intelligence.refresh_normalized_intelligence",
                    side_effect=AssertionError("API must not refresh normalized data"),
                ):
                    events = api_data._ai_load_events("data_leak")

                self.assertEqual(
                    ["forum:test:databases:snapshot"],
                    [item["id"] for item in events],
                )
                with get_readonly_db_connection() as connection:
                    keyword_count = connection.execute(
                        "SELECT COUNT(*) FROM monitoring_keywords"
                    ).fetchone()[0]
                self.assertEqual(0, keyword_count)

    def test_readonly_api_reads_old_snapshot_while_writer_holds_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                with get_db_connection() as connection:
                    self._install_snapshot(connection)

                writer = get_db_connection()
                executor = ThreadPoolExecutor(max_workers=1)
                try:
                    writer.execute("BEGIN IMMEDIATE")
                    writer.execute(
                        "UPDATE normalized_intelligence_events SET title = ? WHERE event_id = ?",
                        ("Uncommitted B", "forum:test:databases:snapshot"),
                    )
                    started_at = time.perf_counter()
                    future = executor.submit(api_data._ai_load_events, "data_leak")
                    try:
                        events = future.result(timeout=2)
                    except FutureTimeoutError:
                        writer.rollback()
                        self.fail("read-only API waited on an active SQLite writer")
                    elapsed = time.perf_counter() - started_at
                    self.assertLess(elapsed, 2)
                    self.assertEqual("Snapshot A", events[0]["originalTitle"])
                finally:
                    if writer.in_transaction:
                        writer.rollback()
                    writer.close()
                    executor.shutdown(wait=True)

    def test_single_instance_lock_prevents_overlapping_normalizers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                with get_db_connection() as connection:
                    mark_normalized_intelligence_dirty(connection)
                    connection.commit()

                entered = Event()
                release = Event()
                call_lock = Lock()
                call_count = 0

                def blocking_refresh(*args, **kwargs):
                    nonlocal call_count
                    with call_lock:
                        call_count += 1
                    entered.set()
                    release.wait(timeout=5)
                    return []

                executor = ThreadPoolExecutor(max_workers=2)
                try:
                    with patch.object(
                        normalizer_service,
                        "refresh_normalized_intelligence",
                        side_effect=blocking_refresh,
                    ):
                        first = executor.submit(
                            normalizer_service.refresh_pending_normalization,
                            True,
                            debounce_seconds=0,
                            max_delay_seconds=0,
                            db_path=db_path,
                        )
                        self.assertTrue(entered.wait(timeout=2))
                        second = executor.submit(
                            normalizer_service.refresh_pending_normalization,
                            True,
                            debounce_seconds=0,
                            max_delay_seconds=0,
                            db_path=db_path,
                        )
                        try:
                            second.result(timeout=2)
                            second_completed_without_waiting = True
                        except FutureTimeoutError:
                            second_completed_without_waiting = False
                        finally:
                            release.set()
                        first.result(timeout=5)
                        second.result(timeout=5)
                finally:
                    release.set()
                    executor.shutdown(wait=True)

                self.assertTrue(
                    second_completed_without_waiting,
                    "a second normalizer blocked instead of reporting the active instance",
                )
                self.assertEqual(1, call_count)


if __name__ == "__main__":
    unittest.main()
