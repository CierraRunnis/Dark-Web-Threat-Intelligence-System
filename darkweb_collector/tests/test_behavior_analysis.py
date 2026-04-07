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

from darkweb_collector import normalized_intelligence
from darkweb_collector.api_data import build_behavior_payload, build_event_detail, build_event_records, build_intelligence_payload
from darkweb_collector.db import get_db_connection, upsert_forum_detail, upsert_forum_topic, upsert_victim


class BehaviorAnalysisTests(unittest.TestCase):
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

    def test_behavior_payload_aggregates_repeated_entities(self) -> None:
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
                        title="Acme Corp database leak",
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
                        content="Database leak for Acme Corp with credential sample.",
                        authors="poster",
                        timestamps="2026-03-17",
                        attachments="",
                        victims=[{"name": "Acme Corp", "industry": "technology", "region": "asia"}],
                        attackers=["NightCrew"],
                        content_hash="forum-detail-hash",
                        collected_at_utc="2026-03-17T01:00:00+00:00",
                    )
                    upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://acme.example/",
                            "name": "Acme Corp",
                            "display_label": "Acme Corp (acme.example)",
                            "domain": "acme.example",
                            "status": "published",
                            "published_at_utc": "2026-03-17T02:00:00+00:00",
                            "claimed_size": "10G",
                            "claimed_size_gb": 10.0,
                            "content_hash": "victim-hash-acme",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Technology company in Asia"}),
                        },
                    )
                    upsert_victim(
                        connection,
                        run_id=2,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://beta.example/",
                            "name": "Beta Logistics",
                            "display_label": "Beta Logistics (beta.example)",
                            "domain": "beta.example",
                            "status": "going",
                            "published_at_utc": "2026-03-18T02:00:00+00:00",
                            "claimed_size": "20G",
                            "claimed_size_gb": 20.0,
                            "content_hash": "victim-hash-beta",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Transport company in Europe"}),
                        },
                    )
                    connection.commit()

                payload = build_behavior_payload()
                self.assertTrue(payload["summaryCards"])
                self.assertTrue(payload["actorRiskRanking"])
                self.assertTrue(payload["victimRiskRanking"])
                self.assertTrue(payload["anomalyEvents"])

                top_actor = payload["actorRiskRanking"][0]
                self.assertIn(top_actor["actor"], {"DragonForce", "NightCrew"})

                acme = next(item for item in payload["victimRiskRanking"] if item["victim"] == "Acme Corp")
                self.assertGreaterEqual(acme["eventCount"], 2)

    def test_event_records_include_risk_score_from_normalized_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://gamma.example/",
                            "name": "Gamma Finance",
                            "display_label": "Gamma Finance (gamma.example)",
                            "domain": "gamma.example",
                            "status": "published",
                            "published_at_utc": "2026-03-18T02:00:00+00:00",
                            "claimed_size": "30G",
                            "claimed_size_gb": 30.0,
                            "content_hash": "victim-hash-gamma",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Finance company in North America"}),
                        },
                    )
                    connection.commit()

                event = build_event_records(limit=1)[0]
                self.assertIn("risk_score", event)
                self.assertIn("risk_reasons", event)
                self.assertGreater(event["risk_score"], 0)

    def test_event_detail_and_list_do_not_refresh_normalized_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://delta.example/",
                            "name": "Delta Motors",
                            "display_label": "Delta Motors (delta.example)",
                            "domain": "delta.example",
                            "status": "published",
                            "published_at_utc": "2026-03-18T02:00:00+00:00",
                            "claimed_size": "30G",
                            "claimed_size_gb": 30.0,
                            "content_hash": "victim-hash-delta",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Manufacturing company"}),
                        },
                    )
                    connection.commit()

                build_intelligence_payload()
                event_id = build_event_records(limit=1)[0]["id"]

                with patch(
                    "darkweb_collector.normalized_intelligence.refresh_normalized_intelligence",
                    side_effect=AssertionError("detail/list should not refresh normalized cache"),
                ):
                    detail = build_event_detail(event_id)
                    events = build_event_records(limit=1)

                self.assertIsNotNone(detail)
                self.assertEqual(event_id, events[0]["id"])

    def test_intelligence_payload_refreshes_only_when_source_data_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://epsilon.example/",
                            "name": "Epsilon Bank",
                            "display_label": "Epsilon Bank (epsilon.example)",
                            "domain": "epsilon.example",
                            "status": "published",
                            "published_at_utc": "2026-03-18T02:00:00+00:00",
                            "claimed_size": "30G",
                            "claimed_size_gb": 30.0,
                            "content_hash": "victim-hash-epsilon",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Finance company"}),
                        },
                    )
                    connection.commit()

                with patch(
                    "darkweb_collector.normalized_intelligence.refresh_normalized_intelligence",
                    wraps=normalized_intelligence.refresh_normalized_intelligence,
                ) as mocked_refresh:
                    build_intelligence_payload()
                    build_intelligence_payload()
                    self.assertEqual(1, mocked_refresh.call_count)

                    with get_db_connection() as connection:
                        upsert_victim(
                            connection,
                            run_id=2,
                            payload={
                                "site_name": "dragonforce",
                                "source_url": "http://dragon.onion/",
                                "detail_url": "https://zeta.example/",
                                "name": "Zeta Health",
                                "display_label": "Zeta Health (zeta.example)",
                                "domain": "zeta.example",
                                "status": "going",
                                "published_at_utc": "2026-03-19T02:00:00+00:00",
                                "claimed_size": "18G",
                                "claimed_size_gb": 18.0,
                                "content_hash": "victim-hash-zeta",
                                "last_detail_fetch_status": "ok",
                                "raw_json": json.dumps({"description": "Healthcare company"}),
                            },
                        )
                        connection.commit()

                    build_intelligence_payload()
                    self.assertEqual(2, mocked_refresh.call_count)

    def test_data_leak_events_are_not_capped_at_50_when_more_records_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    for index in range(60):
                        topic_url = f"https://darkforums.su/thread-{index}"
                        upsert_forum_topic(
                            connection,
                            site_name="darkforums",
                            section="databases",
                            title=f"[FR] Record {index}",
                            url=topic_url,
                            author="poster",
                            replies="1",
                            views="10",
                            published_at="2026-03-17",
                            last_reply_at="",
                            content_hash=f"forum-topic-{index}",
                            collected_at_utc=f"2026-03-17T00:{index % 60:02d}:00+00:00",
                        )
                        upsert_forum_detail(
                            connection,
                            site_name="darkforums",
                            section="databases",
                            topic_url=topic_url,
                            content=f"Database leak {index} for france.fr customer dataset",
                            authors="poster",
                            timestamps=f"2026-03-17T00:{index % 60:02d}:00+00:00",
                            attachments="",
                            victims=[{"name": f"Victim {index}", "industry": "technology", "region": "europe"}],
                            attackers=["NightCrew"],
                            content_hash=f"forum-detail-{index}",
                            collected_at_utc=f"2026-03-17T01:{index % 60:02d}:00+00:00",
                        )
                    connection.commit()

                payload = build_intelligence_payload()
                self.assertEqual(60, len(payload["dataLeakEvents"]))

    def test_ransomware_events_are_sorted_latest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://older.example/",
                            "name": "Older Victim",
                            "display_label": "Older Victim",
                            "domain": "older.example",
                            "status": "published",
                            "published_at_utc": "2026-03-01T08:00:00+00:00",
                            "claimed_size": "10G",
                            "claimed_size_gb": 10.0,
                            "content_hash": "older-hash",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Older event"}),
                        },
                    )
                    upsert_victim(
                        connection,
                        run_id=2,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://newer.example/",
                            "name": "Newer Victim",
                            "display_label": "Newer Victim",
                            "domain": "newer.example",
                            "status": "published",
                            "published_at_utc": "2026-03-07T08:00:00+00:00",
                            "claimed_size": "11G",
                            "claimed_size_gb": 11.0,
                            "content_hash": "newer-hash",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Newer event"}),
                        },
                    )
                    connection.commit()

                payload = build_intelligence_payload()
                titles = [item["title"] for item in payload["ransomwareEvents"][:2]]
                self.assertEqual(["Newer Victim", "Older Victim"], titles)

    def test_region_inference_uses_domain_and_country_signals(self) -> None:
        self.assertEqual("欧洲", normalized_intelligence._infer_region("[FR] ministry breach", "https://example.fr"))
        self.assertEqual("中东", normalized_intelligence._infer_region("Iraq National Security Database", "Baghdad"))
        self.assertEqual("非洲", normalized_intelligence._infer_region("Morocco education leak", "casablanca"))

    def test_country_inference_prefers_explicit_title_signal(self) -> None:
        bundle = normalized_intelligence._infer_country_bundle(
            ("title", 9, "China's National Super-computing Center (NSCC) Research Facility"),
            ("content", 4, "Research facility database leak"),
        )
        self.assertEqual("中国", bundle["country"])
        self.assertEqual("CN", bundle["country_code"])

    def test_country_inference_detects_russia(self) -> None:
        bundle = normalized_intelligence._infer_country_bundle(
            ("title", 9, "Russia Business Leaders — Corporate Database"),
            ("content", 5, "Corporate database with Moscow executive records"),
        )
        self.assertEqual("俄罗斯", bundle["country"])
        self.assertEqual("RU", bundle["country_code"])

    def test_industry_inference_supports_military(self) -> None:
        self.assertEqual("军事", normalized_intelligence._infer_industry("military research facility", "defense systems"))

    def test_intelligence_payload_includes_executive_threat_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "http://dragon.onion/",
                            "detail_url": "https://hms.com.au/",
                            "name": "Health Management Systems",
                            "display_label": "Health Management Systems (hms.com.au)",
                            "domain": "hms.com.au",
                            "status": "published",
                            "published_at_utc": "2026-03-18T08:00:00+00:00",
                            "claimed_size": "12G",
                            "claimed_size_gb": 12.0,
                            "content_hash": "hms-hash",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Healthcare provider in Australia", "website_url": "https://hms.com.au/"}),
                        },
                    )
                    connection.commit()

                payload = build_intelligence_payload()
                self.assertIn("threatExecutiveCards", payload)
                self.assertIn("threatExecutiveTrend", payload)
                self.assertIn("threatExecutiveCountries", payload)
                self.assertIn("threatExecutivePriorityEvents", payload)
                self.assertIn("threatExecutiveCoverage", payload)
                self.assertTrue(payload["threatExecutiveCountries"])
