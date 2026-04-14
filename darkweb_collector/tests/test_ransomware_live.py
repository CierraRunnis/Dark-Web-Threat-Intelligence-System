from __future__ import annotations

import importlib
import inspect
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.api_data import build_event_detail, build_intelligence_payload
from darkweb_collector.db import get_db_connection, insert_victim_detail, upsert_victim


class RansomwareLiveTests(unittest.TestCase):
    def _env(self, db_path: Path, config_path: Path) -> dict[str, str]:
        return {
            "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
            "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            "RANSOMWARE_LIVE_API_KEY": "test-token",
        }

    def _write_sites_config(self, path: Path) -> None:
        path.write_text(json.dumps({"sites": []}), encoding="utf-8")

    def _write_sample_feed(self, path: Path, records: list[dict], *, name: str = "ransomware_live_sample.json") -> Path:
        sample_path = path / name
        sample_path.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return sample_path

    def _import_ransomware_live(self):
        return importlib.import_module("darkweb_collector.ransomware_live")

    def _call_first(self, module, candidate_names: list[str], **kwargs):
        for name in candidate_names:
            fn = getattr(module, name, None)
            if not callable(fn):
                continue
            signature = inspect.signature(fn)
            accepts_sample_file = "sample_file" in signature.parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
            )
            if "sample_file" in kwargs and not accepts_sample_file:
                continue
            filtered_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
            if kwargs and not filtered_kwargs and not any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
            ):
                continue
            return fn(**filtered_kwargs)
        available = ", ".join(sorted(name for name in dir(module) if "ransom" in name.lower() or "victim" in name.lower()))
        raise AssertionError(f"none of the expected ransomware.live functions exist: {candidate_names}. available: {available}")

    def _sync_sample(self, sample_file: Path):
        module = self._import_ransomware_live()
        return self._call_first(
            module,
            [
                "sync_ransomware_live",
                "sync_ransomware_live_feed",
                "sync_ransomware_live_victims",
                "sync_ransomware",
                "sync_live_ransomware_feed",
                "sync_live_ransomware_victims",
                "sync_live_ransomware",
            ],
            sample_file=sample_file,
            prefer_live=False,
            limit=20,
        )

    def _create_old_schema_db(self, db_path: Path) -> None:
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("CREATE TABLE collection_runs (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            connection.execute("CREATE TABLE victims (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            connection.execute("CREATE TABLE victim_details (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            connection.execute("CREATE TABLE normalized_intelligence_events (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            connection.commit()
        finally:
            connection.close()

    def test_sync_cumulatively_upserts_and_updates_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.json"
            self._write_sites_config(config_path)

            first_records = [
                {
                    "id": "YmxhY2tzdWl0QGJhY2tkb29y",
                    "victim": "BlackSuit Demo",
                    "group": "blacksuit",
                    "country": "US",
                    "activity": "Manufacturing",
                    "discovered": "2026-04-10 10:00:00",
                    "attackdate": "2026-04-10 08:30:00",
                    "description": "Initial ransomware.live disclosure.",
                    "website": "blacksuit.example",
                    "post_url": "https://black.example/post/1",
                    "permalink": "https://www.ransomware.live/id/YmxhY2tzdWl0QGJhY2tkb29y",
                    "screenshot": "https://images.ransomware.live/victims/first.png",
                }
            ]
            second_records = [
                {
                    "id": "UmFuc29tSGl0QGJhc2U0",
                    "victim": "RansomHit Demo",
                    "group": "ransomhit",
                    "country": "GB",
                    "activity": "Financial Services",
                    "discovered": "2026-04-11 11:00:00",
                    "attackdate": "2026-04-11 09:45:00",
                    "description": "Second ransomware.live disclosure.",
                    "website": "ransomhit.example",
                    "post_url": "https://black.example/post/2",
                    "permalink": "https://www.ransomware.live/id/UmFuc29tSGl0QGJhc2U0",
                    "screenshot": "https://images.ransomware.live/victims/second.png",
                }
            ]
            first_updated_records = [
                {
                    **first_records[0],
                    "description": "Initial ransomware.live disclosure, updated note.",
                    "screenshot": "https://images.ransomware.live/victims/first-updated.png",
                }
            ]

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                first_sample = self._write_sample_feed(tmp_path, first_records, name="ransomware_live_first.json")
                second_sample = self._write_sample_feed(tmp_path, second_records, name="ransomware_live_second.json")
                updated_sample = self._write_sample_feed(tmp_path, first_updated_records, name="ransomware_live_first_updated.json")

                self._sync_sample(first_sample)
                with get_db_connection() as connection:
                    rows = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT victim_id, raw_json, last_seen_at FROM ransomware_live_victims ORDER BY victim_id"
                        ).fetchall()
                    ]
                self.assertEqual(1, len(rows))
                self.assertEqual("YmxhY2tzdWl0QGJhY2tkb29y", str(rows[0]["victim_id"]))
                self.assertIn("BlackSuit Demo", json.loads(rows[0]["raw_json"])["victim"])

                self._sync_sample(second_sample)
                with get_db_connection() as connection:
                    rows = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT victim_id, raw_json, last_seen_at FROM ransomware_live_victims ORDER BY victim_id"
                        ).fetchall()
                    ]
                self.assertEqual(2, len(rows))

                self._sync_sample(updated_sample)
                with get_db_connection() as connection:
                    rows = [
                        dict(row)
                        for row in connection.execute(
                            "SELECT victim_id, raw_json, last_seen_at FROM ransomware_live_victims ORDER BY victim_id"
                        ).fetchall()
                    ]
                self.assertEqual(2, len(rows))
                first_row = next(row for row in rows if row["victim_id"] == "YmxhY2tzdWl0QGJhY2tkb29y")
                self.assertIn("updated note", json.loads(first_row["raw_json"])["description"])
                self.assertTrue(first_row["last_seen_at"])

    def test_ransomware_live_activity_labels_are_translated_to_chinese(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.json"
            self._write_sites_config(config_path)

            sample_records = [
                {
                    "id": "VHJhbnNwb3J0QGRlbW8=",
                    "victim": "Transit Demo",
                    "group": "demoactor",
                    "country": "US",
                    "activity": "Transportation/Logistics",
                    "discovered": "2026-04-12 09:00:00",
                    "attackdate": "2026-04-12 08:15:00",
                    "description": "Transportation victim details from ransomware.live.",
                    "website": "transit.example",
                    "post_url": "https://transit.example/post/1",
                    "permalink": "https://www.ransomware.live/id/VHJhbnNwb3J0QGRlbW8=",
                    "screenshot": "https://images.ransomware.live/victims/transit.png",
                },
                {
                    "id": "QnVzaW5lc3NAZGVtbw==",
                    "victim": "Business Demo",
                    "group": "demoactor",
                    "country": "US",
                    "activity": "Business Services",
                    "discovered": "2026-04-12 09:10:00",
                    "attackdate": "2026-04-12 08:20:00",
                    "description": "Business victim details from ransomware.live.",
                    "website": "business.example",
                    "post_url": "https://business.example/post/1",
                    "permalink": "https://www.ransomware.live/id/QnVzaW5lc3NAZGVtbw==",
                    "screenshot": "https://images.ransomware.live/victims/business.png",
                },
            ]

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                sample_file = self._write_sample_feed(tmp_path, sample_records, name="ransomware_live_industry_labels.json")
                self._sync_sample(sample_file)
                payload = build_intelligence_payload()
                by_title = {item["title"]: item for item in payload["ransomwareEvents"]}

                self.assertEqual("交通运输", by_title["Transit Demo"]["industry"])
                self.assertEqual("企业服务", by_title["Business Demo"]["industry"])

    def test_api_key_can_be_saved_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.json"
            self._write_sites_config(config_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                module = self._import_ransomware_live()
                status_before = module.get_ransomware_live_config_status()
                self.assertTrue(status_before["has_api_key"])

                with patch.dict(os.environ, {"RANSOMWARE_LIVE_API_KEY": ""}, clear=False):
                    status_empty = module.get_ransomware_live_config_status()
                    self.assertFalse(status_empty["has_api_key"])
                    saved = module.set_ransomware_live_api_key("demo-key-123456")
                    self.assertTrue(saved["has_api_key"])
                    self.assertTrue(saved["masked_api_key"])
                    self.assertIn("settings_path", saved)
                    self.assertEqual("environment", saved["source"])

    def test_old_schema_auto_creates_ransomware_live_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.json"
            self._write_sites_config(config_path)
            self._create_old_schema_db(db_path)

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                with get_db_connection() as connection:
                    table_row = connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                        ("ransomware_live_victims",),
                    ).fetchone()
                    index_rows = connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ?",
                        ("ransomware_live_victims",),
                    ).fetchall()

                self.assertIsNotNone(table_row)
                self.assertGreaterEqual(len(index_rows), 1)

    def test_intelligence_payload_and_event_detail_include_ransomware_live_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.json"
            self._write_sites_config(config_path)

            sample_records = [
                {
                    "id": "QmFkQml0QGFrcmE=",
                    "victim": "BadBit Demo",
                    "group": "badbit",
                    "country": "US",
                    "activity": "Healthcare",
                    "discovered": "2026-04-12 09:00:00",
                    "attackdate": "2026-04-12 08:15:00",
                    "description": "Healthcare victim details from ransomware.live.",
                    "website": "badbit.example",
                    "post_url": "https://badbit.example/post/1",
                    "permalink": "https://www.ransomware.live/id/QmFkQml0QGFrcmE=",
                    "screenshot": "https://images.ransomware.live/victims/badbit.png",
                }
            ]

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                sample_file = self._write_sample_feed(tmp_path, sample_records)
                self._sync_sample(sample_file)

                payload = build_intelligence_payload()
                self.assertIn("ransomwareSummary", payload)
                self.assertTrue(payload["ransomwareEvents"])

                event = next(
                    item
                    for item in payload["ransomwareEvents"]
                    if item["title"].startswith("BadBit Demo") or item["attacker"] == "badbit"
                )
                self.assertEqual("badbit", event["attacker"])
                self.assertEqual("US", event["countryCode"])
                self.assertEqual("医疗", event["industry"])
                self.assertTrue(event["disclosureTime"])
                self.assertTrue(event["title"])

                detail = build_event_detail(event["id"])
                self.assertIsNotNone(detail)
                self.assertEqual(event["id"], detail["id"])
                self.assertTrue(detail["disclosure_url"])
                self.assertTrue(detail["detail_text"])
                self.assertTrue(detail["raw_source_type_label"])
                self.assertTrue(detail["reference_urls"])
                self.assertTrue(detail["screenshot_resources"])
                self.assertTrue(any("ransomware.live" in item["url"] for item in detail["reference_urls"]))
                self.assertTrue(any(item["url"].endswith(".png") for item in detail["screenshot_resources"]))

    def test_cross_source_dedup_merges_local_victim_and_ransomware_live_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.json"
            self._write_sites_config(config_path)

            sample_records = [
                {
                    "id": "QWNtZVNvdXJjZUBkcmFnb24=",
                    "victim": "Acme Source",
                    "group": "dragonforce",
                    "country": "US",
                    "activity": "Business Services",
                    "discovered": "2026-04-13 10:00:00",
                    "attackdate": "2026-04-13 09:30:00",
                    "description": "Ransomware.live disclosure for Acme Source.",
                    "website": "acme-source.example",
                    "post_url": "https://acme-source.example/post",
                    "permalink": "https://www.ransomware.live/id/QWNtZVNvdXJjZUBkcmFnb24=",
                    "screenshot": "https://images.ransomware.live/victims/acme-source.png",
                }
            ]

            with patch.dict(os.environ, self._env(db_path, config_path), clear=False):
                sample_file = self._write_sample_feed(tmp_path, sample_records)
                self._sync_sample(sample_file)

                with get_db_connection() as connection:
                    victim_id = upsert_victim(
                        connection,
                        run_id=1,
                        payload={
                            "site_name": "dragonforce",
                            "source_url": "https://dragonforce.example/",
                            "detail_url": "https://acme-source.example/local-detail",
                            "name": "Acme Source",
                            "display_label": "Acme Source (acme-source.example)",
                            "domain": "acme-source.example",
                            "status": "published",
                            "published_at_utc": "2026-04-13T09:30:00+00:00",
                            "claimed_size": "1.2 TB",
                            "claimed_size_gb": 1.2,
                            "content_hash": "acme-source-local-hash",
                            "last_detail_fetch_status": "ok",
                            "raw_json": json.dumps(
                                {
                                    "description": "Local victim source for the same ransomware event.",
                                    "thumbnails": ["https://local.example/screens/acme-source.png"],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    insert_victim_detail(
                        connection,
                        victim_id=victim_id,
                        payload={
                            "fetched_at_utc": "2026-04-13T10:10:00+00:00",
                            "fetch_status": "ok",
                            "page_title": "Acme Source local detail",
                            "text_excerpt": "Local detail mirror for the same event.",
                            "outbound_link_count": 2,
                            "raw_json": json.dumps({"detail_url": "https://acme-source.example/local-detail"}, ensure_ascii=False),
                        },
                    )
                    connection.commit()

                payload = build_intelligence_payload()
                matching_events = [
                    item
                    for item in payload["ransomwareEvents"]
                    if item["attacker"] == "dragonforce" and "Acme Source" in item["title"]
                ]
                self.assertEqual(1, len(matching_events))

                detail = build_event_detail(matching_events[0]["id"])
                self.assertIsNotNone(detail)
                self.assertTrue(any("acme-source.example" in item["url"] for item in detail["mirror_resources"]))
                self.assertTrue(any("ransomware.live" in item["url"] for item in detail["mirror_resources"]))
