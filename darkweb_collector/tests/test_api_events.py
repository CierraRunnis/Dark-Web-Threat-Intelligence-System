from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import api_data
from darkweb_collector.api_data import build_event_detail, build_event_records
from darkweb_collector.db import get_db_connection, upsert_forum_detail, upsert_forum_topic, upsert_victim


class ApiEventsTests(unittest.TestCase):
    def _env(self, db_path: Path, config_path: Path) -> dict[str, str]:
        return {
            "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
            "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
        }

    def _write_sites_config(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "sites": [
                        {
                            "site_name": "darkforums",
                            "enabled": True,
                            "seed_urls": ["https://darkforums.su/Forum-Databases"],
                            "seed_fetch_mode": "tor_http",
                            "detail_fetch_mode": "tor_http",
                            "profile": "warm",
                            "max_topics_per_run": 1,
                            "max_detail_pages_per_run": 1,
                            "cooldown_seconds": 60,
                            "output_dir": str(path.parent / "darkforums"),
                            "dedupe_window_minutes": 5,
                        },
                        {
                            "site_name": "dragonforce",
                            "enabled": True,
                            "seed_urls": ["http://dragon.onion/"],
                            "seed_fetch_mode": "tor_http",
                            "detail_fetch_mode": "tor_http",
                            "profile": "hot",
                            "max_topics_per_run": 1,
                            "max_detail_pages_per_run": 1,
                            "cooldown_seconds": 60,
                            "output_dir": str(path.parent / "dragonforce"),
                            "dedupe_window_minutes": 5,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_build_event_records_returns_forum_and_victim_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_forum_topic(
                        connection,
                        site_name="darkforums",
                        section="databases",
                        title="Acme Database Leak",
                        url="https://darkforums.su/thread-acme",
                        author="poster",
                        replies="1",
                        views="10",
                        published_at="2026-03-17",
                        last_reply_at="",
                        content_hash="forum-hash",
                        collected_at_utc="2026-03-17T00:00:00+00:00",
                    )
                    upsert_forum_detail(
                        connection,
                        site_name="darkforums",
                        section="databases",
                        topic_url="https://darkforums.su/thread-acme",
                        content="forum detail body",
                        authors="poster",
                        timestamps="2026-03-17",
                        attachments="https://mirror.example/file.zip",
                        victims=[{"name": "Acme", "industry": "technology", "region": "asia"}],
                        attackers=["darkforums"],
                        content_hash="forum-detail-hash",
                        collected_at_utc="2026-03-17T01:00:00+00:00",
                    )
                    upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://victim.example/",
                            "name": "Victim One",
                            "display_label": "Victim One (victim.example)",
                            "domain": "victim.example",
                            "status": "published",
                            "published_at_utc": "2026-03-17T02:00:00+00:00",
                            "claimed_size": "10G",
                            "claimed_size_gb": 10.0,
                            "content_hash": "victim-hash",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"thumbnails": ["https://img.example/1.png"]}),
                        },
                    )
                    connection.commit()

                events = build_event_records()
                event_types = {item["event_type"] for item in events}
                self.assertIn("forum", event_types)
                self.assertIn("victim", event_types)

    def test_build_event_detail_returns_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_forum_topic(
                        connection,
                        site_name="darkforums",
                        section="other_leaks",
                        title="Breach Record",
                        url="https://darkforums.su/thread-breach",
                        author="poster",
                        replies="1",
                        views="20",
                        published_at="2026-03-17",
                        last_reply_at="",
                        content_hash="topic-hash",
                        collected_at_utc="2026-03-17T00:00:00+00:00",
                    )
                    upsert_forum_detail(
                        connection,
                        site_name="darkforums",
                        section="other_leaks",
                        topic_url="https://darkforums.su/thread-breach",
                        content="full detail content",
                        authors="poster",
                        timestamps="2026-03-17",
                        attachments="",
                        victims=[{"name": "Breach Org", "industry": "finance", "region": "europe"}],
                        attackers=["darkforums"],
                        content_hash="detail-hash",
                        collected_at_utc="2026-03-17T01:00:00+00:00",
                    )
                    connection.commit()

                events = build_event_records()
                forum_event = next(item for item in events if item["event_type"] == "forum")
                detail = build_event_detail(forum_event["id"])
                self.assertIsNotNone(detail)
                self.assertEqual("Breach Record", detail["original_title"])
                self.assertIn("疑似", detail["title"])
                self.assertEqual("darkforums", detail["source"])
                self.assertIn("disclosure_url", detail)
                self.assertIn("detail_text", detail)
                self.assertIn("mirror_resources", detail)
                self.assertIn("screenshot_resources", detail)

    def test_build_event_detail_does_not_call_build_event_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_forum_topic(
                        connection,
                        site_name="darkforums",
                        section="databases",
                        title="Direct Lookup Event",
                        url="https://darkforums.su/thread-direct",
                        author="poster",
                        replies="1",
                        views="20",
                        published_at="2026-03-17",
                        last_reply_at="",
                        content_hash="direct-topic-hash",
                        collected_at_utc="2026-03-17T00:00:00+00:00",
                    )
                    upsert_forum_detail(
                        connection,
                        site_name="darkforums",
                        section="databases",
                        topic_url="https://darkforums.su/thread-direct",
                        content="direct detail content",
                        authors="poster",
                        timestamps="2026-03-17",
                        attachments="",
                        victims=[{"name": "Direct Org", "industry": "technology", "region": "asia"}],
                        attackers=["darkforums"],
                        content_hash="direct-detail-hash",
                        collected_at_utc="2026-03-17T01:00:00+00:00",
                    )
                    connection.commit()

                event_id = "forum:darkforums:databases:" + api_data._event_hash("https://darkforums.su/thread-direct")

                with patch("darkweb_collector.api_data.build_event_records", side_effect=AssertionError("should not scan all events")):
                    detail = build_event_detail(event_id)

                self.assertIsNotNone(detail)
                self.assertEqual("Direct Lookup Event", detail["original_title"])
                self.assertIn("疑似", detail["title"])
