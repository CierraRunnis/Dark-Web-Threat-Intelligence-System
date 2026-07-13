from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from darkweb_collector.bot_assistant import (
    BotAssistantError,
    build_text_payload,
    load_bot_config,
    post_bot_payload,
    set_bot_enabled,
)
from darkweb_collector.monitoring_notifications import notify_keyword_matches_for_events


class BotAssistantSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "bot-settings.json"
        self.previous_settings_path = os.environ.get("DARKWEB_BOT_SETTINGS_PATH")
        os.environ["DARKWEB_BOT_SETTINGS_PATH"] = str(self.settings_path)

    def tearDown(self) -> None:
        if self.previous_settings_path is None:
            os.environ.pop("DARKWEB_BOT_SETTINGS_PATH", None)
        else:
            os.environ["DARKWEB_BOT_SETTINGS_PATH"] = self.previous_settings_path
        self.temp_dir.cleanup()

    def _write_config(self, *, include_enabled: bool = True) -> None:
        payload = {
            "provider": "wechat_work_aibot",
            "bot_id": "test-bot",
            "secret": "test-secret",
            "chat_ids": ["test-chat"],
            "websocket_url": "wss://example.invalid",
        }
        if include_enabled:
            payload["enabled"] = True
        self.settings_path.write_text(json.dumps(payload), encoding="utf-8")

    def test_legacy_config_defaults_to_enabled(self) -> None:
        self._write_config(include_enabled=False)

        self.assertTrue(load_bot_config().enabled)

    def test_disabling_push_preserves_credentials_and_blocks_delivery(self) -> None:
        self._write_config()

        status = set_bot_enabled(False)
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        config = load_bot_config()

        self.assertFalse(status["enabled"])
        self.assertTrue(status["configured"])
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["bot_id"], "test-bot")
        self.assertEqual(saved["secret"], "test-secret")
        self.assertEqual(saved["chat_ids"], ["test-chat"])
        with self.assertRaisesRegex(BotAssistantError, "disabled"):
            post_bot_payload(build_text_payload("test"), config)

        notification_status = notify_keyword_matches_for_events(None, [], config=config)
        self.assertFalse(notification_status["enabled"])
        self.assertEqual(notification_status["sent"], 0)


if __name__ == "__main__":
    unittest.main()
