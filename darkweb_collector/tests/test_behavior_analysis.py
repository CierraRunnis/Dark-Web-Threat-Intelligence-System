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

    def test_intelligence_payload_uses_cached_normalized_events_during_requests(self) -> None:
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
                    self.assertEqual(1, mocked_refresh.call_count)

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
                self.assertEqual(
                    ["Newer Victim", "Older Victim"],
                    titles,
                )

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

    def test_country_inference_supports_hong_kong_thailand_vietnam_and_venezuela(self) -> None:
        self.assertEqual("香港", normalized_intelligence._infer_country_bundle(("title", 8, "Hong Kong ha.org.hk leak"))["country"])
        self.assertEqual("泰国", normalized_intelligence._infer_country_bundle(("title", 8, "Thailand Ministry of Finance"))["country"])
        self.assertEqual("越南", normalized_intelligence._infer_country_bundle(("title", 8, "Vietnam Fortress Tools JSC"))["country"])
        self.assertEqual("委内瑞拉", normalized_intelligence._infer_country_bundle(("title", 8, "VENEZUELA CORDIALITO leaks betting house"))["country"])
        self.assertEqual("伊拉克", normalized_intelligence._infer_country_bundle(("title", 8, "Basra Transports"))["country"])

    def test_domain_country_code_supports_ca_and_nz(self) -> None:
        self.assertEqual("CA", normalized_intelligence._domain_country_code("emond.ca"))
        self.assertEqual("NZ", normalized_intelligence._domain_country_code("elitefitness.co.nz"))

    def test_base_domain_reduces_subdomain_noise(self) -> None:
        self.assertEqual("gray-adams.com", normalized_intelligence._to_base_domain("adm.gray-adams.com"))
        self.assertEqual("example.co.nz", normalized_intelligence._to_base_domain("www.example.co.nz"))

    def test_industry_inference_supports_rehabilitation_and_casino(self) -> None:
        self.assertEqual("医疗", normalized_intelligence._infer_industry("Advanced Rehabilitation Technology"))
        self.assertEqual("文娱", normalized_intelligence._infer_industry("Brazil casino betting records"))
        self.assertEqual("文娱", normalized_intelligence._infer_industry("Emond Publishing"))
        self.assertEqual("文娱", normalized_intelligence._infer_industry("Elite Fitness"))
        self.assertEqual("制造业", normalized_intelligence._infer_industry("Matthew Allchurch Architects"))

    def test_industry_inference_covers_recent_darkforums_titles(self) -> None:
        self.assertEqual("文娱", normalized_intelligence._infer_industry("VIEW ONLYFANS CONTENT FOR FREE"))
        self.assertEqual("政府", normalized_intelligence._infer_industry("CHINA - 64 sets of ID cards - front back holding"))
        self.assertEqual("金融", normalized_intelligence._infer_industry("AUJ Forex Australia"))
        self.assertEqual("科技", normalized_intelligence._infer_industry("Fudan Microelectronics Breach Free Docs"))
        self.assertEqual("教育", normalized_intelligence._infer_industry("Mexico - Universidad Autonoma de Sinaloa"))

    def test_industry_inference_prefers_manufacturing_over_served_medical_markets(self) -> None:
        snippet = (
            "Anomatic is a full-service manufacturer of anodized aluminum and metalized packaging "
            "for the automotive, beauty, personal care, consumer electronics, pharmaceutical, "
            "medical devices, and spirits industries worldwide"
        )
        self.assertEqual("制造业", normalized_intelligence._infer_industry(snippet))

    def test_industry_inference_identifies_agriculture_over_retail_context(self) -> None:
        snippet = (
            "Northern Family Farms Welcome to Northern Family Farms Growing Since 1955 "
            "Nursery Plants Trees, Fruits, Topiaries, Roses, Perennials, Shrubs and more. "
            "Christmas Tree Grower serving our retail or landscape business customers."
        )
        self.assertEqual("农业", normalized_intelligence._infer_industry(snippet))

    def test_country_inference_supports_generic_country_names(self) -> None:
        bundle = normalized_intelligence._infer_country_bundle(("title", 8, "Peru RENIEC national citizen database"))
        self.assertEqual("PE", bundle["country_code"])

    def test_country_label_supports_near_full_chinese_fallback(self) -> None:
        self.assertEqual("孟加拉国", normalized_intelligence._label_country("BD"))
        self.assertEqual("尼日利亚", normalized_intelligence._label_country("NG"))
        self.assertEqual("荷兰", normalized_intelligence._label_country("NL"))

    def test_forum_country_inference_ignores_source_topic_domain(self) -> None:
        row = {
            "id": 1,
            "site_name": "darkforums",
            "section": "databases",
            "topic_url": "https://darkforums.su/thread-something",
            "content": "credential sample without country clues",
            "attachments": "",
            "victims": "",
            "attackers": "",
            "fetched_at": "2026-04-10T00:00:00+00:00",
            "raw_json": "{}",
            "title": "Generic leak post",
            "victim_names": "",
            "industries": "",
            "regions": "",
        }
        with patch("darkweb_collector.normalized_intelligence._enrich_domain") as mocked_enrich:
            event = normalized_intelligence._build_forum_base_event(row, domain_cache={})
        mocked_enrich.assert_not_called()
        self.assertEqual("未知", event["country"])

    def test_victim_country_inference_ignores_source_detail_domain(self) -> None:
        row = {
            "id": 1,
            "site_name": "dragonforceblog",
            "source_url": "https://dragonforce.example/listing",
            "detail_url": "https://dragonforce.example/post/1",
            "name": "Victim Org",
            "display_label": "Victim Org",
            "domain": "",
            "status": "published",
            "published_at_utc": "2026-04-10T00:00:00+00:00",
            "raw_json": "{}",
            "text_excerpt": "",
            "page_title": "",
            "fetched_at_utc": "",
            "detail_raw_json": "{}",
        }
        with patch("darkweb_collector.normalized_intelligence._enrich_domain") as mocked_enrich:
            event = normalized_intelligence._build_victim_base_event(row, domain_cache={})
        mocked_enrich.assert_not_called()
        self.assertEqual("未知", event["country"])

    def test_low_confidence_ip_geo_country_is_not_propagated(self) -> None:
        events = [
            {
                "victim_key": "acme",
                "country": "美国",
                "country_code": "US",
                "region": "北美",
                "industry": "科技",
                "confidence_score": 40,
                "completeness_score": 40,
                "metadata": {"country_source": "ip_geo", "country_score": 4, "industry_source": "title", "industry_score": 8},
            },
            {
                "victim_key": "acme",
                "country": "未知",
                "country_code": "",
                "region": "未知",
                "industry": "未知",
                "confidence_score": 20,
                "completeness_score": 20,
                "metadata": {},
            },
        ]
        normalized_intelligence._propagate_entity_context(events)
        self.assertEqual("未知", events[1]["country"])

    def test_display_title_for_data_leak_is_explicit(self) -> None:
        with patch(
            "darkweb_collector.normalized_intelligence.translate_event_title_live",
            return_value="美国船主数据库",
        ):
            title = normalized_intelligence.build_display_title(
                {
                    "event_type": "data_leak",
                    "title": "2M USA BOAT OWNERS",
                    "victim": "2M USA BOAT OWNERS",
                    "leak_type": "数据库泄露",
                    "category": "数据库泄露",
                }
            )
        self.assertEqual("美国船主数据库", title)

    def test_display_title_for_ransomware_is_explicit(self) -> None:
        title = normalized_intelligence.build_display_title(
            {
                "event_type": "ransomware",
                "title": "Northern Family Farms listed by DragonForce",
                "victim": "Northern Family Farms",
                "attacker": "DragonForce",
                "category": "已公开",
            }
        )
        self.assertEqual("Northern Family Farms listed by DragonForce", title)

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

    def test_executive_countries_excludes_vulnerability_only_country_counts(self) -> None:
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
                            "detail_url": "https://fr-victim.example/",
                            "name": "French Victim",
                            "display_label": "French Victim",
                            "domain": "fr-victim.example",
                            "status": "published",
                            "published_at_utc": "2026-03-18T02:00:00+00:00",
                            "claimed_size": "10G",
                            "claimed_size_gb": 10.0,
                            "content_hash": "fr-victim-hash",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps({"description": "Company in France"}),
                        },
                    )
                    connection.execute(
                        """
                        INSERT INTO vulnerability_records (
                            source_name, source_type, cve_id, title, vendor, product, vulnerability_type,
                            severity, cvss, is_exploited, has_poc, patch_available, wide_impact,
                            disclosure_time, affected_versions, summary, advisory_url, reference_urls_json,
                            raw_json, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "securityweek",
                            "media",
                            "CVE-2026-9999",
                            "United States infrastructure issue",
                            "Example Vendor",
                            "Example Product",
                            "Remote Code Execution",
                            "high",
                            8.8,
                            0,
                            0,
                            1,
                            0,
                            "2026-03-19T02:00:00+00:00",
                            "[]",
                            "Issue impacting systems in New York, United States.",
                            "https://example.com/advisory",
                            "[]",
                            "{}",
                            "2026-03-19T02:00:00+00:00",
                        ),
                    )
                    connection.commit()

                payload = build_intelligence_payload()
                self.assertTrue(payload["threatExecutiveCountries"])
                self.assertEqual("法国", payload["threatExecutiveCountries"][0]["name"])
