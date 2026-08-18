from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request

from darkweb_collector import api_app, api_data
from darkweb_collector.db import (
    get_analysis_snapshot,
    get_db_connection,
    replace_normalized_intelligence_events,
    upsert_vulnerability_record,
)
from darkweb_collector.intelligence_aggregates import build_dashboard_overview, build_threat_situation
from darkweb_collector.monitoring_rules import MONITORING_SNAPSHOT_NAMESPACE, persist_monitoring_snapshot
from darkweb_collector.normalized_intelligence import load_normalized_events


def _request(path: str, user: dict[str, object], *, query: str = "", etag: str = "") -> Request:
    headers = [(b"if-none-match", etag.encode())] if etag else []
    request = Request({
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": query.encode(),
        "headers": headers, "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000),
    })
    request.state.current_user = user
    return request


class IntelligenceAggregateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "collector.db"
        self.env = patch.dict(os.environ, {
            "DARKWEB_COLLECTOR_DB_PATH": str(self.db_path),
            "DARKWEB_SKIP_API_WARMUP": "1",
        }, clear=False)
        self.env.start()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        recent = now.isoformat()
        old = (now - timedelta(days=45)).isoformat()
        with get_db_connection() as connection:
            replace_normalized_intelligence_events(connection, [
                self._event("leak:recent", "data_leak", "数据库泄露", "seller-a", recent, "critical", 92),
                self._event("ran:recent", "ransomware", "已公开", "group-a", recent, "high", 80),
                self._event("vuln:cve-2026-9999", "vulnerability", "远程代码执行", "Vendor", recent, "critical", 95),
                self._event("leak:old", "data_leak", "历史事件", "seller-b", old, "low", 20),
            ])
            upsert_vulnerability_record(connection, {
                "source_name": "cisa_kev", "source_type": "official", "cve_id": "CVE-2026-9999",
                "title": "Gateway command execution", "vendor": "Vendor", "product": "Gateway",
                "vulnerability_type": "远程代码执行", "severity": "critical", "cvss": 9.8,
                "is_exploited": True, "has_poc": True, "patch_available": True, "wide_impact": True,
                "disclosure_time": recent, "affected_versions": ["1.x"], "summary": "Active exploitation",
                "advisory_url": "https://example.invalid/cve", "reference_urls": [], "raw": {},
                "last_seen_at": recent,
            })
            connection.execute(
                """INSERT INTO exposure_watchlists
                   (name,organization_name,enabled,notes,metadata_json,created_at,updated_at)
                   VALUES ('Acme','Acme',1,'','{}',?,?)""", (recent, recent))
            watchlist_id = int(connection.execute("SELECT id FROM exposure_watchlists").fetchone()[0])
            connection.execute(
                """INSERT INTO document_hits
                   (watchlist_id,platform,platform_type,discovery_source,canonical_url,normalized_title,
                    resource_fingerprint,title,access_state,confidence_score,risk_score,severity,review_status,
                    matched_terms_json,file_count,evidence_count,share_owner,disclosure_time,first_seen_at,
                    last_seen_at,last_snapshot_id,raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (watchlist_id, "baidu", "netdisk", "baidu", "https://example.invalid/file", "acme",
                 "fixture-fingerprint", "Acme internal document", "public", 90, 88, "high", "new",
                 "[]", 1, 1, "", recent, recent, recent, None, json.dumps({"country": "United States", "country_code": "US"})),
            )
            connection.commit()
            events = load_normalized_events(connection, allow_refresh=False)
            persist_monitoring_snapshot(connection, events)
            connection.commit()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    @staticmethod
    def _event(event_id: str, event_type: str, category: str, attacker: str, timestamp: str, severity: str, risk: int) -> dict:
        return {
            "event_id": event_id, "source_kind": event_type, "raw_source_type": "fixture",
            "source_site_name": "test", "source_record_id": 1, "event_type": event_type,
            "category": category, "leak_type": category, "title": f"{attacker} title",
            "attacker": attacker, "victim": "Acme", "victim_key": "acme",
            "industry": "technology", "region": "asia", "disclosure_time": timestamp,
            "severity": severity, "risk_score": risk, "source_url": "https://example.invalid",
            "detail_text": f"{attacker} Acme 中国", "mirror_resources_json": "[]",
            "screenshot_resources_json": "[]", "json_preview_url": "", "risk_reasons_json": "[]",
            "event_metadata_json": json.dumps({"country": "中国", "country_code": "CN", "macro_region": "亚洲"}, ensure_ascii=False),
            "updated_at": timestamp,
        }

    def test_dashboard_uses_sql_aggregates_and_filters_full_result(self) -> None:
        with patch("darkweb_collector.intelligence_aggregates.load_normalized_events", side_effect=AssertionError("full load forbidden")):
            payload = build_dashboard_overview(days=7, event_type="data_leak", severity="critical", keyword="seller-a")
        self.assertEqual(1, payload["kpis"]["dataLeak"])
        self.assertEqual(1, payload["kpis"]["ransomware"])
        self.assertEqual(1, payload["kpis"]["vulnerability"])
        self.assertEqual(1, payload["kpis"]["documentExposure"])
        self.assertEqual(["leak:recent"], [item["id"] for item in payload["events"]])
        self.assertEqual(7, len(payload["dailyTrend"]["labels"]))
        self.assertEqual(4, payload["kpis"]["highRisk"])
        self.assertEqual(4, sum(payload["dailyTrend"]["total"]))
        self.assertTrue(any(item["code"] == "US" for item in payload["countries"]))
        self.assertLess(len(json.dumps(payload, ensure_ascii=False).encode()), 300_000)

    def test_threat_reads_materialized_monitoring_snapshot_without_full_load(self) -> None:
        with get_db_connection() as connection:
            snapshot = get_analysis_snapshot(connection, MONITORING_SNAPSHOT_NAMESPACE)
        self.assertIsNotNone(snapshot)
        with patch("darkweb_collector.intelligence_aggregates.load_normalized_events", side_effect=AssertionError("full load forbidden")):
            payload = build_threat_situation(days=30)
        self.assertEqual(2, payload["threatExecutiveCards"]["totalEvents30d"])
        self.assertEqual(3, payload["threatExecutiveCountries"][0]["eventCount"])
        self.assertTrue(payload["threatExecutiveIndustryDistribution"])
        self.assertTrue(payload["threatExecutiveActiveActors"])
        self.assertIn("monitoringConfigurationSummary", payload)
        self.assertNotIn("dataLeakEvents", payload)
        self.assertLess(len(json.dumps(payload, ensure_ascii=False).encode()), 300_000)

    def test_legacy_payload_cache_hits_before_full_event_loading(self) -> None:
        first = api_data.build_intelligence_payload()
        with patch.object(api_data, "load_normalized_events", side_effect=AssertionError("cache hit must not load events")):
            second = api_data.build_intelligence_payload()
        self.assertEqual(first, second)

    def test_endpoint_permissions_and_etag(self) -> None:
        admin = {"role": "admin", "modules": []}
        response = api_app.dashboard_overview(_request("/api/dashboard/overview", admin, query="days=7"), days=7)
        self.assertEqual(200, response.status_code)
        etag = response.headers["etag"]
        not_modified = api_app.dashboard_overview(
            _request("/api/dashboard/overview", admin, query="days=7", etag=etag), days=7
        )
        self.assertEqual(304, not_modified.status_code)
        with self.assertRaises(HTTPException) as denied:
            api_app.threat_situation(_request("/api/threat-situation", {"role": "user", "modules": []}))
        self.assertEqual(403, denied.exception.status_code)
        allowed = api_app.threat_situation(
            _request("/api/threat-situation", {"role": "user", "modules": ["threat_situation"]})
        )
        self.assertEqual(200, allowed.status_code)


if __name__ == "__main__":
    unittest.main()
