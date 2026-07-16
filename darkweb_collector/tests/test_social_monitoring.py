from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from darkweb_collector.db import connect
from darkweb_collector import social_monitoring as social
from darkweb_collector.social_adapters import CollectResult, CoverageStatus, SocialPost
from darkweb_collector.social_scheduler import execute_claimed_social_scan


class SocialMonitoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db_path = self.root / "collector.db"
        self.connection_patch = patch.object(social, "get_db_connection", side_effect=lambda: connect(self.db_path))
        self.connection_patch.start()
        self.evidence_patch = patch.dict(os.environ, {"SOCIAL_EVIDENCE_ROOT": str(self.root / "evidence")})
        self.evidence_patch.start()
        self.admin = social.ensure_initial_admin("admin", "123456")

    def tearDown(self) -> None:
        self.evidence_patch.stop()
        self.connection_patch.stop()
        self.temporary.cleanup()

    def _campaign(self) -> dict:
        return social.save_campaign_payload(
            self.admin,
            {
                "name": "重要节点监测",
                "startAt": "2026-07-15T00:00:00+00:00",
                "anchorAt": "2026-07-15T00:00:00+00:00",
                "platforms": ["x", "telegram"],
                "terms": {
                    "region": ["西藏"],
                    "target": ["测试单位"],
                    "threat": ["数据售卖"],
                    "exclude": ["演练"],
                },
                "sources": [
                    {"platform": "x", "sourceType": "account", "sourceValue": "test-source"}
                ],
            },
        )

    def _event(self, *, severity: str = "major") -> int:
        campaign = self._campaign()
        result = social.upsert_social_post_event(
            campaign["id"],
            None,
            {
                "platform": "x",
                "platformPostId": "post-1",
                "sourceUrl": "https://x.example/post-1",
                "title": "发现数据售卖线索",
                "originalText": "声称售卖测试单位数据",
                "matchedTerms": ["测试单位", "数据售卖"],
                "severity": severity,
            },
        )
        return int(result["id"])

    def test_schema_contains_all_social_tables(self) -> None:
        required = {
            "users", "social_campaigns", "social_terms", "social_sources", "social_scan_runs",
            "social_events", "social_evidence", "social_actions", "social_publications",
            "social_publication_reads",
        }
        with connect(self.db_path) as connection:
            actual = {
                row["name"]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        self.assertTrue(required.issubset(actual))

    def test_user_password_and_disable_invalidate_sessions(self) -> None:
        analyst = social.create_user_payload(
            self.admin,
            {"username": "analyst", "password": "secret12", "role": "analyst"},
        )
        logged_in = social.authenticate_user("analyst", "secret12")
        self.assertIsNotNone(logged_in)
        assert logged_in is not None
        version = logged_in["sessionVersion"]
        social.change_user_password(self.admin, analyst["id"], "changed12")
        self.assertIsNone(social.validate_session_user(analyst["id"], version))
        refreshed = social.authenticate_user("analyst", "changed12")
        self.assertIsNotNone(refreshed)
        assert refreshed is not None
        social.update_user_payload(self.admin, analyst["id"], {"enabled": False})
        self.assertIsNone(social.validate_session_user(analyst["id"], refreshed["sessionVersion"]))

    def test_api_session_checks_database_session_version(self) -> None:
        from darkweb_collector import api_app

        logged_in = social.authenticate_user("admin", "123456")
        assert logged_in is not None
        token, _ = api_app._create_auth_session(logged_in)
        self.assertEqual(api_app._get_auth_user(token)["id"], self.admin["id"])
        social.change_user_password(self.admin, self.admin["id"], "changed12")
        self.assertIsNone(api_app._get_auth_user(token))

    def test_campaign_due_snapshot_and_scan_lifecycle(self) -> None:
        campaign = self._campaign()
        due = social.list_due_social_campaign_platforms("2026-07-15T00:29:59+00:00")
        x_task = next(item for item in due if item["platform"] == "x")
        self.assertEqual(x_task["scheduled_at"], "2026-07-15T00:00:00+00:00")
        self.assertIn("数据售卖", x_task["keywords"])
        self.assertEqual(x_task["sources"][0]["value"], "test-source")
        scan = social.claim_social_scan(campaign["id"], "x", x_task["scheduled_at"])
        delayed_due = social.list_due_social_campaign_platforms("2026-07-15T00:30:00+00:00")
        self.assertFalse(any(item["platform"] == "x" for item in delayed_due))
        self.assertIn("delayed", social.list_scans_payload(campaign["id"])[0]["errorMessage"])
        social.finish_social_scan(
            scan["id"],
            stats={"candidate_count": 2, "new_count": 1, "duplicate_count": 1},
            status="succeeded",
            error=None,
            cursor="cursor-1",
        )
        rows = social.list_scans_payload(campaign["id"])
        self.assertEqual(rows[0]["newEventCount"], 1)
        self.assertEqual(rows[0]["cursorAfter"], "cursor-1")

    def test_reenabling_campaign_resets_the_thirty_minute_anchor(self) -> None:
        campaign = self._campaign()
        social.save_campaign_payload(self.admin, {"enabled": False}, campaign["id"])
        with patch.object(social, "utc_now", return_value="2026-07-15T03:04:05+00:00"):
            enabled = social.save_campaign_payload(self.admin, {"enabled": True}, campaign["id"])
        self.assertEqual(enabled["anchorAt"], "2026-07-15T03:04:05+00:00")

    def test_keyword_only_platform_restores_last_successful_scan_cursor(self) -> None:
        campaign = social.save_campaign_payload(
            self.admin,
            {
                "name": "YouTube keyword monitoring",
                "startAt": "2026-07-15T00:00:00+00:00",
                "anchorAt": "2026-07-15T00:00:00+00:00",
                "platforms": ["youtube"],
                "terms": {"region": ["Tibet"], "threat": ["data leak"]},
                "sources": [],
            },
        )
        first = social.list_due_social_campaign_platforms("2026-07-15T00:00:00+00:00")[0]
        scan = social.claim_social_scan(campaign["id"], "youtube", first["scheduled_at"])
        cursor = json.dumps({"__global__": "2026-07-15T00:00:01+00:00"})
        social.finish_social_scan(
            scan["id"],
            stats={"candidate_count": 1, "new_count": 0, "duplicate_count": 0},
            status="succeeded",
            error=None,
            cursor=cursor,
        )

        second = social.list_due_social_campaign_platforms("2026-07-15T00:30:00+00:00")[0]
        self.assertEqual(second["cursor"], cursor)

    def test_admin_can_save_write_only_platform_credentials_outside_the_repository(self) -> None:
        secrets_path = self.root / "private" / "social-platform-secrets.json"
        environment = {
            "SOCIAL_PLATFORM_SECRETS_FILE": str(secrets_path),
            "SOCIAL_YOUTUBE_API_KEY": "",
            "SOCIAL_TELEGRAM_API_ID": "",
            "SOCIAL_TELEGRAM_API_HASH": "",
            "SOCIAL_TELEGRAM_SESSION": "",
        }
        youtube_key = "AIza" + "A" * 35
        telegram_session = "1" + "A" * 180
        with patch.dict(os.environ, environment):
            youtube = social.save_platform_config_payload(
                self.admin, "youtube", {"apiKey": youtube_key}
            )
            telegram = social.save_platform_config_payload(
                self.admin,
                "telegram",
                {"apiId": "123456", "apiHash": "a" * 32, "session": telegram_session},
            )
            config = social.platform_config_payload(self.admin)
            status = {item["platform"]: item for item in social.platform_status_payload()}

            self.assertTrue(youtube["configured"])
            self.assertTrue(telegram["configured"])
            self.assertTrue(config["youtube"]["credentials"]["apiKey"]["configured"])
            self.assertEqual(config["youtube"]["credentials"]["apiKey"]["source"], "local_file")
            self.assertTrue(status["youtube"]["configured"])
            self.assertTrue(status["telegram"]["configured"])
            response_text = json.dumps(config)
            self.assertNotIn(youtube_key, response_text)
            self.assertNotIn(telegram_session, response_text)
            self.assertIn(youtube_key, secrets_path.read_text(encoding="utf-8"))

            cleared = social.clear_platform_config_payload(self.admin, "youtube")
            self.assertFalse(cleared["configured"])

    def test_analyst_cannot_manage_platform_credentials(self) -> None:
        analyst = social.create_user_payload(
            self.admin, {"username": "analyst-config", "password": "secret12", "role": "analyst"}
        )
        with self.assertRaisesRegex(social.SocialMonitoringError, "admin"):
            social.platform_config_payload(analyst)
        with self.assertRaisesRegex(social.SocialMonitoringError, "admin"):
            social.save_platform_config_payload(analyst, "youtube", {"apiKey": "AIza" + "A" * 35})

    def test_edited_post_keeps_content_snapshots(self) -> None:
        event_id = self._event()
        campaign_id = social.get_event_payload(event_id)["campaignId"]
        result = social.upsert_social_post_event(
            campaign_id,
            None,
            {
                "platform": "x",
                "platformPostId": "post-1",
                "sourceUrl": "https://x.example/post-1",
                "title": "已编辑的数据售卖线索",
                "originalText": "编辑后的正文",
            },
        )
        self.assertEqual(result["status"], "duplicate")
        snapshots = social.get_event_payload(event_id)["snapshots"]
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1]["originalText"], "编辑后的正文")
        social.upsert_social_post_event(
            campaign_id,
            None,
            {
                "platform": "x",
                "platformPostId": "post-1",
                "sourceUrl": "https://x.example/post-1",
                "title": "已编辑的数据售卖线索",
                "originalText": "编辑后的正文",
                "isDeleted": True,
            },
        )
        self.assertIsNotNone(social.get_event_payload(event_id)["sourceDeletedAt"])

    def test_claim_verify_redact_publish_notify_and_report(self) -> None:
        event_id = self._event()
        claimed = social.claim_event_payload(self.admin, event_id)
        self.assertEqual(claimed["status"], "verifying")
        verified = social.verify_event_payload(
            self.admin,
            event_id,
            {
                "result": "credible",
                "threatTitle": "测试单位数据售卖",
                "threatType": "data_sale",
                "targetUnit": "测试单位",
                "targetIndustry": "政务",
                "evidenceNote": "公开帖文待进一步核实",
                "disposalDirection": "通知相关单位核查暴露范围",
                "severity": "major",
            },
        )
        self.assertEqual(verified["status"], "verified")

        image_buffer = io.BytesIO()
        Image.new("RGB", (40, 30), "white").save(image_buffer, format="PNG")
        original = social.save_evidence_payload(
            self.admin, event_id, "source.png", "image/png", image_buffer.getvalue()
        )
        redacted = social.redact_evidence_payload(
            self.admin,
            event_id,
            original["id"],
            [{"x": 5, "y": 5, "width": 10, "height": 8}],
            True,
        )
        self.assertTrue(redacted["approved"])
        self.assertEqual(len(social.list_event_evidence_payload(event_id)), 2)
        original_path, _ = social.read_evidence_payload(self.admin, original["id"])
        redacted_path, _ = social.read_evidence_payload(self.admin, redacted["id"])
        self.assertNotEqual(original_path.read_bytes(), redacted_path.read_bytes())

        publication = social.publish_event_payload(self.admin, event_id)
        self.assertEqual(publication["card"]["targetUnit"], "测试单位")
        notifications = social.notifications_payload(self.admin)
        self.assertFalse(notifications[0]["read"])
        social.mark_notification_read_payload(self.admin, publication["id"])
        self.assertTrue(social.notifications_payload(self.admin)[0]["read"])
        report = social.report_data_payload(self.admin, event_id)
        self.assertIn("重大威胁事件专项分析报告", report["reportTitle"])
        result = social.record_report_generated(
            self.admin, event_id, "report.docx", "a" * 64
        )
        self.assertTrue(result["ok"])

    def test_verification_records_actual_elapsed_time_without_an_sla(self) -> None:
        event_id = self._event()
        with patch.object(social, "utc_now", return_value="2026-07-15T00:00:00+00:00"):
            social.claim_event_payload(self.admin, event_id)
        with patch.object(social, "utc_now", return_value="2026-07-15T00:02:05+00:00"):
            verified = social.verify_event_payload(
                self.admin,
                event_id,
                {
                    "result": "credible",
                    "threatTitle": "测试事件",
                    "threatType": "dataSale",
                    "targetUnit": "测试单位",
                    "disposalDirection": "人工核查",
                },
            )
        self.assertEqual(verified["verificationDurationSeconds"], 125)

    def test_authorized_browser_capture_saves_private_html_and_screenshot(self) -> None:
        event_id = self._event()
        social.claim_event_payload(self.admin, event_id)
        image_buffer = io.BytesIO()
        Image.new("RGB", (16, 12), "white").save(image_buffer, format="PNG")
        with patch.object(
            social,
            "_capture_page_artifacts",
            return_value=(b"<html><body>fixture</body></html>", image_buffer.getvalue()),
        ):
            evidence = social.capture_event_evidence_payload(self.admin, event_id)
        self.assertEqual([item["mimeType"] for item in evidence], ["text/html", "image/png"])
        self.assertEqual(len([path for path in (self.root / "evidence").rglob("*") if path.is_file()]), 2)

    def test_event_claim_is_compare_and_swap_and_original_evidence_is_private(self) -> None:
        first = social.create_user_payload(
            self.admin, {"username": "first", "password": "secret12", "role": "analyst"}
        )
        second = social.create_user_payload(
            self.admin, {"username": "second", "password": "secret12", "role": "analyst"}
        )
        event_id = self._event()
        social.claim_event_payload(first, event_id)
        with self.assertRaisesRegex(social.SocialMonitoringError, "already been claimed"):
            social.claim_event_payload(second, event_id)
        image_buffer = io.BytesIO()
        Image.new("RGB", (12, 10), "white").save(image_buffer, format="PNG")
        original = social.save_evidence_payload(
            first, event_id, "source.png", "image/png", image_buffer.getvalue()
        )
        with self.assertRaisesRegex(social.SocialMonitoringError, "claim the event"):
            social.read_evidence_payload(second, original["id"])
        self.assertTrue(social.read_evidence_payload(self.admin, original["id"])[0].is_file())

    def test_offline_end_to_end_flow_starts_with_a_platform_scan(self) -> None:
        class Adapter:
            platform = "x"

            def collect(self, _request):
                return CollectResult(
                    (
                        SocialPost(
                            platform="x",
                            platform_post_id="e2e-1",
                            source_url="https://x.com/example/status/e2e-1",
                            title="西藏测试单位数据售卖",
                            original_text="声称售卖测试单位数据",
                            published_at="2026-07-15T00:00:00+00:00",
                        ),
                    ),
                    "cursor-e2e",
                    CoverageStatus("fixture", True),
                )

        campaign = self._campaign()
        due = next(
            item
            for item in social.list_due_social_campaign_platforms("2026-07-15T00:00:00+00:00")
            if item["platform"] == "x"
        )
        scan = social.claim_social_scan(campaign["id"], "x", due["scheduled_at"])
        result = execute_claimed_social_scan(
            {**due, "scan_run_id": scan["id"]}, service=social, adapter=Adapter()
        )
        self.assertEqual(result["new_count"], 1)
        event = next(item for item in social.list_events_payload() if item["platformPostId"] == "e2e-1")
        claimed = social.claim_event_payload(self.admin, event["id"])
        self.assertEqual(claimed["status"], "verifying")
        social.verify_event_payload(
            self.admin,
            event["id"],
            {
                "result": "credible",
                "threatTitle": "西藏测试单位数据售卖",
                "threatType": "dataSale",
                "targetUnit": "测试单位",
                "disposalDirection": "通知相关单位核查",
                "severity": "major",
            },
        )
        image_buffer = io.BytesIO()
        Image.new("RGB", (20, 16), "white").save(image_buffer, format="PNG")
        original = social.save_evidence_payload(
            self.admin, event["id"], "source.png", "image/png", image_buffer.getvalue()
        )
        social.redact_evidence_payload(
            self.admin, event["id"], original["id"], [{"x": 1, "y": 1, "width": 6, "height": 5}], True
        )
        publication = social.publish_event_payload(self.admin, event["id"])
        report = social.report_data_payload(self.admin, event["id"])
        self.assertEqual(publication["card"]["platform"], "x")
        self.assertIn("专项分析报告", report["reportTitle"])

    def test_publish_requires_approved_redacted_evidence(self) -> None:
        event_id = self._event(severity="normal")
        social.claim_event_payload(self.admin, event_id)
        social.verify_event_payload(
            self.admin,
            event_id,
            {
                "result": "credible",
                "threatTitle": "威胁线索",
                "threatType": "attack_threat",
                "targetUnit": "测试单位",
                "disposalDirection": "人工核查",
            },
        )
        with self.assertRaisesRegex(social.SocialMonitoringError, "approved redacted screenshot"):
            social.publish_event_payload(self.admin, event_id)

    def test_wsl_launcher_starts_social_api_worker(self) -> None:
        launcher = Path(__file__).parents[1] / "scripts" / "start_all_services_wsl.sh"
        content = launcher.read_text(encoding="utf-8")
        self.assertIn("python scripts/crawl.py worker --queue social_api", content)
        self.assertIn('tmux_new_window "worker-social"', content)

    def test_telegram_session_helper_reads_page_managed_secrets(self) -> None:
        helper = Path(__file__).parents[1] / "scripts" / "create_telegram_session.py"
        content = helper.read_text(encoding="utf-8")
        self.assertIn('get_social_secret("SOCIAL_TELEGRAM_API_ID")', content)
        self.assertIn('get_social_secret("SOCIAL_TELEGRAM_API_HASH")', content)


if __name__ == "__main__":
    unittest.main()
