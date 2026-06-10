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

from darkweb_collector.bot_assistant import BOT_PROVIDER_WECHAT_WORK_WEBHOOK, BotConfig
from darkweb_collector.api_app import BotConfigRequest, save_bot_config as save_bot_config_endpoint
from darkweb_collector.db import (
    get_db_connection,
    list_monitoring_keyword_notifications,
    replace_monitoring_keywords,
    replace_normalized_intelligence_events,
)
from darkweb_collector.monitoring_notifications import notify_keyword_matches_for_events
from darkweb_collector.monitoring_rules import save_monitoring_keywords


def _event(**overrides):
    payload = {
        "event_id": "event-1",
        "source_kind": "forum",
        "raw_source_type": "forum_details",
        "source_site_name": "darkforums",
        "source_record_id": 1,
        "event_type": "data_leak",
        "category": "database",
        "leak_type": "database",
        "title": "Acme customer database leak",
        "attacker": "darkforums",
        "victim": "Acme",
        "victim_key": "acme",
        "industry": "technology",
        "region": "asia",
        "country": "China",
        "disclosure_time": "2026-06-01T08:00:00+00:00",
        "severity": "high",
        "risk_score": 70,
        "source_url": "https://example.test/thread/acme",
        "detail_text": "Threat actor is selling Acme data.",
        "mirror_resources": [],
        "screenshot_resources": [],
        "json_preview_url": "",
        "risk_reasons": [],
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _persisted_row(event):
    return {
        "event_id": event["event_id"],
        "source_kind": event["source_kind"],
        "raw_source_type": event["raw_source_type"],
        "source_site_name": event["source_site_name"],
        "source_record_id": event["source_record_id"],
        "event_type": event["event_type"],
        "category": event["category"],
        "leak_type": event["leak_type"],
        "title": event["title"],
        "attacker": event["attacker"],
        "victim": event["victim"],
        "victim_key": event["victim_key"],
        "industry": event["industry"],
        "region": event["region"],
        "disclosure_time": event["disclosure_time"],
        "severity": event["severity"],
        "risk_score": event["risk_score"],
        "source_url": event["source_url"],
        "detail_text": event["detail_text"],
        "mirror_resources_json": "[]",
        "screenshot_resources_json": "[]",
        "json_preview_url": "",
        "risk_reasons_json": "[]",
        "event_metadata_json": json.dumps(event.get("metadata") or {}, ensure_ascii=False),
        "updated_at": "2026-06-01T08:00:00+00:00",
    }


class MonitoringNotificationTests(unittest.TestCase):
    def _env(self, db_path: Path) -> dict[str, str]:
        return {
            "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
            "DARKWEB_BOT_SETTINGS_PATH": str(db_path.with_name("bot_settings.json")),
            "BOT_PROVIDER": BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
            "BOT_WEBHOOK_URL": "https://example.invalid/webhook",
        }

    def test_keyword_match_sends_wecom_notification_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                with get_db_connection() as connection:
                    replace_monitoring_keywords(
                        connection,
                        [
                            {
                                "keyword": "Acme",
                                "category": "custom_keywords",
                                "weight": 15,
                                "enabled": True,
                                "match_mode": "contains",
                                "updated_at": "2026-06-01T08:00:00+00:00",
                            }
                        ],
                    )
                    connection.commit()

                    config = BotConfig(
                        provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
                        webhook_url="https://example.invalid/webhook",
                    )
                    with patch(
                        "darkweb_collector.monitoring_notifications.post_bot_payload",
                        return_value={"ok": True, "dry_run": False},
                    ) as post_bot_payload:
                        first_result = notify_keyword_matches_for_events(connection, [_event()], config=config)
                        second_result = notify_keyword_matches_for_events(connection, [_event()], config=config)

                    rows = list_monitoring_keyword_notifications(connection)

                self.assertEqual(1, first_result["matched"])
                self.assertEqual(1, first_result["sent"])
                self.assertEqual(1, second_result["matched"])
                self.assertEqual(1, second_result["skipped"])
                self.assertEqual(1, post_bot_payload.call_count)
                self.assertEqual(1, len(rows))
                self.assertEqual("sent", rows[0]["status"])

    def test_saving_keywords_scans_existing_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                event = _event()
                with get_db_connection() as connection:
                    replace_normalized_intelligence_events(connection, [_persisted_row(event)])
                    connection.commit()

                with patch(
                    "darkweb_collector.monitoring_notifications.post_bot_payload",
                    return_value={"ok": True, "dry_run": False},
                ) as post_bot_payload:
                    rows = save_monitoring_keywords(
                        [
                            {
                                "keyword": "Acme",
                                "category": "custom_keywords",
                                "weight": 15,
                                "enabled": True,
                                "match_mode": "contains",
                            }
                        ]
                    )

                with get_db_connection() as connection:
                    notifications = list_monitoring_keyword_notifications(connection)

                self.assertEqual(1, len(rows))
                self.assertEqual(1, post_bot_payload.call_count)
                self.assertEqual(1, len(notifications))
                self.assertEqual("sent", notifications[0]["status"])

    def test_saving_bot_config_scans_existing_keyword_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            with patch.dict(os.environ, self._env(db_path), clear=False):
                event = _event()
                with get_db_connection() as connection:
                    replace_normalized_intelligence_events(connection, [_persisted_row(event)])
                    replace_monitoring_keywords(
                        connection,
                        [
                            {
                                "keyword": "Acme",
                                "category": "custom_keywords",
                                "weight": 15,
                                "enabled": True,
                                "match_mode": "contains",
                                "updated_at": "2026-06-01T08:00:00+00:00",
                            }
                        ],
                    )
                    connection.commit()

                with patch(
                    "darkweb_collector.monitoring_notifications.post_bot_payload",
                    return_value={"ok": True, "dry_run": False},
                ) as post_bot_payload:
                    status = save_bot_config_endpoint(
                        BotConfigRequest(
                            provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
                            webhook_url="https://example.invalid/webhook",
                        )
                    )

                with get_db_connection() as connection:
                    notifications = list_monitoring_keyword_notifications(connection)

                self.assertTrue(status["configured"])
                self.assertEqual(1, status["keyword_notification_scan"]["sent"])
                self.assertEqual(1, post_bot_payload.call_count)
                self.assertEqual(1, len(notifications))


if __name__ == "__main__":
    unittest.main()
