from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import api_app, api_data
from darkweb_collector.db import (
    get_db_connection,
    replace_normalized_intelligence_events,
    upsert_vulnerability_record,
)
from darkweb_collector.intelligence_queries import (
    build_data_leak_page,
    build_intelligence_search_page,
    build_ransomware_page,
    build_vulnerability_page,
    iter_csv_rows,
)


class IntelligenceQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "collector.db"
        self.env = patch.dict(
            os.environ,
            {
                "DARKWEB_COLLECTOR_DB_PATH": str(self.db_path),
                "DARKWEB_SKIP_API_WARMUP": "1",
            },
            clear=False,
        )
        self.env.start()
        with get_db_connection() as connection:
            replace_normalized_intelligence_events(
                connection,
                [
                    self._normalized("leak:new", "data_leak", "Database published", "数据库泄露", "2026-08-04T04:00:00+00:00", "seller-a"),
                    self._normalized("leak:old", "data_leak", "Credential archive", "凭证泄露", "2026-08-03T04:00:00+00:00", "seller-b"),
                    self._normalized("ran:published", "ransomware", "Victim files released", "已公开", "2026-08-04T05:00:00+00:00", "group-a"),
                    self._normalized("ran:countdown", "ransomware", "Negotiation countdown", "协商中", "2026-08-02T05:00:00+00:00", "group-b"),
                ],
            )
            self._vulnerability(connection, source_name="cisa_kev")
            self._vulnerability(connection, source_name="media", title="Duplicate source")
            connection.commit()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp_dir.cleanup()

    def _normalized(
        self,
        event_id: str,
        event_type: str,
        title: str,
        category: str,
        disclosure_time: str,
        attacker: str,
    ) -> dict:
        return {
            "event_id": event_id,
            "source_kind": event_type,
            "raw_source_type": "fixture",
            "source_site_name": "test",
            "source_record_id": 1,
            "event_type": event_type,
            "category": category,
            "leak_type": "database",
            "title": title,
            "attacker": attacker,
            "victim": "Acme",
            "victim_key": "acme",
            "industry": "technology",
            "region": "asia",
            "disclosure_time": disclosure_time,
            "severity": "high",
            "risk_score": 80,
            "source_url": f"https://example.invalid/{event_id}",
            "detail_text": title,
            "mirror_resources_json": "[]",
            "screenshot_resources_json": "[]",
            "json_preview_url": "",
            "risk_reasons_json": "[]",
            "event_metadata_json": json.dumps(
                {"country": "中国", "country_code": "CN", "macro_region": "亚洲"},
                ensure_ascii=False,
            ),
            "updated_at": disclosure_time,
        }

    def _vulnerability(self, connection, **overrides) -> None:
        payload = {
            "source_name": "cisa_kev",
            "source_type": "official",
            "cve_id": "CVE-2026-24001",
            "title": "Gateway command execution",
            "vendor": "Vendor",
            "product": "Gateway",
            "vulnerability_type": "远程代码执行",
            "severity": "critical",
            "cvss": 9.8,
            "is_exploited": True,
            "has_poc": True,
            "patch_available": True,
            "wide_impact": True,
            "disclosure_time": "2026-08-04T06:00:00+00:00",
            "affected_versions": ["1.x"],
            "summary": "Active exploitation.",
            "advisory_url": "https://example.invalid/cve",
            "reference_urls": ["https://example.invalid/cve"],
            "last_seen_at": "2026-08-04T06:00:00+00:00",
        }
        payload.update(overrides)
        upsert_vulnerability_record(connection, payload)

    def test_all_list_queries_are_server_paged_and_keep_full_counts(self) -> None:
        leaks = build_data_leak_page(page=2, page_size=1)
        ransomware = build_ransomware_page(page=1, page_size=1, stage="published")
        vulnerabilities = build_vulnerability_page(page=1, page_size=1)

        self.assertEqual(2, leaks["total"])
        self.assertEqual("leak:old", leaks["items"][0]["id"])
        self.assertEqual(1, ransomware["total"])
        self.assertEqual("ran:published", ransomware["items"][0]["id"])
        self.assertEqual(1, vulnerabilities["total"])
        self.assertEqual(1, vulnerabilities["summary"]["exploited"])

    def test_data_leak_source_filter_uses_full_filtered_set(self) -> None:
        public_page = build_data_leak_page(page=1, page_size=1, source="public")
        forum_page = build_data_leak_page(page=1, page_size=1, source="forum")

        self.assertEqual(2, public_page["total"])
        self.assertEqual({"public": 2}, public_page["sourceCounts"])
        self.assertEqual(0, forum_page["total"])
        self.assertEqual({"public": 2}, forum_page["sourceCounts"])

    def test_ai_endpoint_rejects_non_loopback_clients(self) -> None:
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/ai/intelligence",
                "raw_path": b"/api/ai/intelligence",
                "query_string": b"",
                "headers": [],
                "client": ("10.10.0.8", 4321),
                "server": ("127.0.0.1", 8000),
            }
        )
        with self.assertRaises(HTTPException) as denied:
            api_app.ai_intelligence(request)
        self.assertEqual(403, denied.exception.status_code)

    def test_search_uses_global_sort_and_type_counts(self) -> None:
        first = build_intelligence_search_page(page=1, page_size=2)
        second = build_intelligence_search_page(page=2, page_size=2)

        self.assertEqual(5, first["total"])
        self.assertEqual(
            {"data_leak": 2, "ransomware": 2, "vulnerability": 1},
            first["typeCounts"],
        )
        self.assertEqual("vuln:cve-2026-24001", first["items"][0]["id"])
        self.assertEqual(2, len(second["items"]))

    def test_ai_route_does_not_use_full_table_loaders(self) -> None:
        with patch.object(api_data, "load_normalized_events", side_effect=AssertionError("full normalized load")), patch.object(
            api_data,
            "list_vulnerability_records",
            side_effect=AssertionError("full vulnerability load"),
        ):
            payload = api_data.build_ai_intelligence_payload(event_type="all", limit=3)

        self.assertEqual(5, payload["matched_count"])
        self.assertEqual(3, payload["returned_count"])
        self.assertTrue(payload["truncated"])
        self.assertEqual(
            {
                "generated_at", "filters", "matched_count", "returned_count", "truncated",
                "summary_text", "aggregations", "events",
            },
            set(payload),
        )

    def test_streaming_export_yields_multiple_bounded_chunks(self) -> None:
        chunks = list(iter_csv_rows("search", {}))
        self.assertGreaterEqual(len(chunks), 6)
        self.assertTrue(chunks[0].startswith("\ufeff".encode("utf-8")))

    def test_search_endpoint_requires_its_independent_permission(self) -> None:
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/intelligence/search",
                "raw_path": b"/api/intelligence/search",
                "query_string": b"",
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 8000),
            }
        )
        request.state.current_user = {"role": "user", "modules": ["ransomware"]}
        with self.assertRaises(HTTPException) as denied:
            api_app.intelligence_search(request)
        self.assertEqual(403, denied.exception.status_code)

        request.state.current_user = {"role": "user", "modules": ["intelligence_search"]}
        payload = api_app.intelligence_search(request, page_size=1)
        self.assertEqual(5, payload["total"])


if __name__ == "__main__":
    unittest.main()
