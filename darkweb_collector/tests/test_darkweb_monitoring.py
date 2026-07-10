from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from darkweb_collector.darkweb_monitoring import (
    SLA_MINUTES,
    build_case_markdown,
    build_monthly_report,
    build_overview,
    ingest_finding,
    poll_configured_connectors,
    push_case,
    review_case,
    scan_sla_breaches,
)
from darkweb_collector.db import get_db_connection
from darkweb_collector.monitoring_rules import get_monitoring_keywords


class DarkwebMonitoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.previous_env = {
            "DARKWEB_COLLECTOR_DB_PATH": os.environ.get("DARKWEB_COLLECTOR_DB_PATH"),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": os.environ.get("DARKWEB_COLLECTOR_OUTPUT_ROOT"),
            "DARKWEB_XSS_CONNECTOR_URL": os.environ.get("DARKWEB_XSS_CONNECTOR_URL"),
            "DARKWEB_XSS_CONNECTOR_TOKEN": os.environ.get("DARKWEB_XSS_CONNECTOR_TOKEN"),
        }
        os.environ["DARKWEB_COLLECTOR_DB_PATH"] = str(root / "collector.db")
        os.environ["DARKWEB_COLLECTOR_OUTPUT_ROOT"] = str(root / "output")

    def tearDown(self) -> None:
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def test_platform_scope_and_tibet_keywords_are_initialized(self) -> None:
        overview = build_overview()
        self.assertEqual(overview["service"]["slaMinutes"], SLA_MINUTES)
        self.assertEqual(overview["service"]["monitoredPlatformCount"], 4)
        self.assertEqual(
            {item["name"] for item in overview["platforms"]},
            {"长安不夜城", "XSS", "BreachForums", "Telegram"},
        )
        keywords = get_monitoring_keywords()
        keyword_values = {item["keyword"].lower() for item in keywords}
        self.assertTrue({"西藏", "tibet", "xizang", "拉萨"}.issubset(keyword_values))

    def test_finding_review_sla_catalog_and_monthly_report(self) -> None:
        finding = ingest_finding(
            {
                "source_platform": "XSS",
                "source_url": "https://example.invalid/thread/100",
                "title": "售卖某西藏能源单位数据库",
                "threat_type": "数据售卖",
                "target_name": "某西藏能源单位",
                "target_industry": "能源",
                "content_excerpt": "声称包含客户和运维数据。",
                "screenshot_url": "/collector-output/xss/thread-100.png",
                "confidence_level": "medium",
            }
        )
        detected = datetime.fromisoformat(finding["firstDetectedAt"])
        due = datetime.fromisoformat(finding["slaDueAt"])
        self.assertEqual(int((due - detected).total_seconds() // 60), SLA_MINUTES)
        self.assertEqual(finding["verificationStatus"], "pending")

        reviewed = review_case(
            finding["id"],
            {
                "verification_status": "verified",
                "confidence_level": "high",
                "target_name": "某西藏能源单位",
                "target_industry": "能源",
                "threat_type": "数据售卖",
                "suggested_action": "通知关联单位排查并固定证据。",
                "screenshot_compliant": True,
                "reviewer": "analyst",
                "disposition": "待单位核查",
                "note": "已完成来源与样本初验。",
            },
        )
        self.assertEqual(reviewed["slaStatus"], "completed")
        self.assertTrue(reviewed["verifiedAt"])
        self.assertTrue(reviewed["catalogedAt"])
        self.assertEqual(reviewed["catalogStatus"], "cataloged")
        self.assertTrue(reviewed["catalogNumber"].startswith("XZ-DW-"))
        self.assertTrue(reviewed["screenshotCompliant"])

        markdown = build_case_markdown(reviewed)
        for label in ("威胁标题", "来源平台/网址", "威胁类型", "关联目标", "发现时间", "原始内容截图", "初步置信度", "建议处置方向"):
            self.assertIn(label, markdown)

        report = build_monthly_report(detected.strftime("%Y-%m"))
        self.assertEqual(report["metrics"]["findingCount"], 1)
        self.assertEqual(report["metrics"]["verifiedCount"], 1)
        self.assertEqual(report["platformDistribution"][0]["name"], "XSS")
        self.assertIn("暗网监测月报", report["markdown"])
        with get_db_connection() as connection:
            archived = connection.execute(
                "SELECT report_type, period FROM darkweb_monitoring_reports WHERE report_type = 'monthly'"
            ).fetchone()
        self.assertEqual(archived["period"], detected.strftime("%Y-%m"))

        with patch("darkweb_collector.darkweb_monitoring.post_bot_payload", return_value={"dry_run": True}):
            dry_run = push_case(finding["id"])
        self.assertTrue(dry_run["response"]["dry_run"])
        self.assertEqual(dry_run["case"]["pushedAt"], "")

    def test_configured_connector_ingests_findings_and_updates_health(self) -> None:
        os.environ["DARKWEB_XSS_CONNECTOR_URL"] = "https://connector.example/xss"
        os.environ["DARKWEB_XSS_CONNECTOR_TOKEN"] = "test-token"
        response = MagicMock()
        response.read.return_value = json_bytes(
            {
                "findings": [
                    {
                        "title": "西藏某单位数据售卖线索",
                        "source_url": "https://xss.example/thread/1",
                        "threat_type": "数据售卖",
                        "target_name": "西藏某单位",
                    }
                ]
            }
        )
        response.__enter__.return_value = response
        with patch("darkweb_collector.darkweb_monitoring.urlopen", return_value=response) as mocked_urlopen:
            result = poll_configured_connectors()
        xss = next(item for item in result["results"] if item["key"] == "xss")
        self.assertEqual(xss["status"], "connected")
        self.assertEqual(xss["ingested"], 1)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer test-token")
        overview = build_overview()
        xss_platform = next(item for item in overview["platforms"] if item["key"] == "xss")
        self.assertEqual(xss_platform["status"], "connected")
        self.assertEqual(xss_platform["findingCount"], 1)

    def test_overdue_pending_case_triggers_sla_alert_once(self) -> None:
        finding = ingest_finding(
            {
                "source_platform": "Telegram",
                "title": "涉西藏数据售卖频道线索",
                "threat_type": "数据售卖",
                "target_industry": "政务",
            }
        )
        with get_db_connection() as connection:
            connection.execute(
                "UPDATE darkweb_monitoring_cases SET sla_due_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
                (finding["id"],),
            )
            connection.commit()
        with patch("darkweb_collector.darkweb_monitoring.post_bot_payload", return_value={"ok": True}):
            result = scan_sla_breaches()
        self.assertEqual(result["breached"], 1)
        self.assertEqual(result["alerted"], 1)
        with patch("darkweb_collector.darkweb_monitoring.post_bot_payload", return_value={"ok": True}):
            second = scan_sla_breaches()
        self.assertEqual(second["breached"], 0)


def json_bytes(payload: dict) -> bytes:
    import json

    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
