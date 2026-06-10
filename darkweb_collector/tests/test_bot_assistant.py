from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import darkweb_collector.bot_assistant as bot_assistant_module
from darkweb_collector.bot_assistant import (
    BOT_PROVIDER_WECHAT_WORK_AIBOT,
    BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
    BotAssistantError,
    BotConfig,
    build_intelligence_digest,
    build_markdown_payload,
    build_text_payload,
    build_wecom_aibot_markdown_payload,
    bot_config_status,
    load_bot_config,
    post_bot_payload,
    register_wecom_aibot_target_from_frame,
    set_bot_config,
)


class BotAssistantTests(unittest.TestCase):
    def test_build_text_payload(self) -> None:
        payload = build_text_payload("hello", mentioned_mobile_list=["13800000000"])
        self.assertEqual("text", payload["msgtype"])
        self.assertEqual("hello", payload["text"]["content"])
        self.assertEqual(["13800000000"], payload["text"]["mentioned_mobile_list"])

    def test_build_markdown_payload(self) -> None:
        payload = build_markdown_payload("### title")
        self.assertEqual("markdown", payload["msgtype"])
        self.assertEqual("### title", payload["markdown"]["content"])

    def test_digest_contains_main_sections(self) -> None:
        digest = build_intelligence_digest(
            {
                "dashboardSummaryCards": [{"label": "总事件", "value": "12"}],
                "vulnerabilityEvents": [{"title": "CVE-2026-0001", "severity": "HIGH"}],
                "ransomwareEvents": [{"victim": "Example Corp", "disclosure_time": "2026-06-01T12:00:00+00:00"}],
                "dataLeakEvents": [{"title": "数据库泄露"}],
                "situationAlerts": [{"title": "采集任务异常"}],
            },
            limit=2,
        )
        self.assertIn("暗网威胁情报推送", digest)
        self.assertIn("总事件: 12", digest)
        self.assertIn("CVE-2026-0001", digest)
        self.assertIn("Example Corp", digest)
        self.assertIn("数据库泄露", digest)
        self.assertIn("采集任务异常", digest)

    def test_webhook_dry_run_does_not_require_network(self) -> None:
        config = BotConfig(
            provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
            webhook_url="https://example.invalid/webhook",
            dry_run=True,
        )
        result = post_bot_payload(build_text_payload("hello"), config)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual("example.invalid", result["webhook_host"])

    def test_config_status_masks_url_to_host(self) -> None:
        status = bot_config_status(
            BotConfig(
                provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
                webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret",
                webhook_key="secret",
            )
        )
        self.assertTrue(status["configured"])
        self.assertEqual("qyapi.weixin.qq.com", status["webhook_host"])
        self.assertNotIn("secret", status["masked_webhook_url"])

    def test_missing_webhook_raises(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(BotAssistantError):
                post_bot_payload(
                    build_text_payload("hello"),
                    BotConfig(provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK, webhook_url=""),
                )

    def test_dry_run_can_render_without_webhook(self) -> None:
        result = post_bot_payload(build_text_payload("hello"), BotConfig(dry_run=True))
        self.assertTrue(result["ok"])
        self.assertFalse(result["configured"])
        self.assertEqual({"msgtype": "markdown", "markdown": {"content": "hello"}}, result["payload"])

    def test_save_wecom_aibot_config_returns_masked_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "bot_settings.json"
            env = {"DARKWEB_BOT_SETTINGS_PATH": str(settings_path)}
            with patch.dict("os.environ", env, clear=True):
                status = set_bot_config(
                    bot_id="aibp-example-bot-id-123456",
                    secret="top-secret",
                    chat_id="zhangsan",
                )
                self.assertTrue(status["configured"])
                self.assertEqual(BOT_PROVIDER_WECHAT_WORK_AIBOT, status["provider"])
                self.assertEqual("saved_file", status["source"])
                self.assertTrue(status["has_secret"])
                self.assertNotIn("aibp-example-bot-id-123456", str(status))
                self.assertNotIn("top-secret", str(status))

                config = load_bot_config()
                self.assertEqual("aibp-example-bot-id-123456", config.bot_id)
                self.assertEqual("top-secret", config.secret)
                self.assertEqual("zhangsan", config.chat_id)
                self.assertEqual(("zhangsan",), config.chat_ids)

    def test_save_wecom_aibot_config_without_target_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "bot_settings.json"
            env = {"DARKWEB_BOT_SETTINGS_PATH": str(settings_path)}
            with patch.dict("os.environ", env, clear=True), patch(
                "darkweb_collector.bot_assistant.ensure_wecom_aibot_listener"
            ):
                status = set_bot_config(
                    bot_id="aibp-example-bot-id-123456",
                    secret="top-secret",
                )
                self.assertTrue(status["configured"])
                self.assertEqual(0, status["chat_target_count"])
                config = load_bot_config()
                self.assertEqual("", config.chat_id)
                self.assertEqual((), config.chat_ids)

    def test_register_wecom_aibot_target_from_message_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "bot_settings.json"
            env = {"DARKWEB_BOT_SETTINGS_PATH": str(settings_path)}
            with patch.dict("os.environ", env, clear=True), patch(
                "darkweb_collector.bot_assistant.ensure_wecom_aibot_listener"
            ):
                set_bot_config(bot_id="aibp-example-bot-id-123456", secret="top-secret")
                result = register_wecom_aibot_target_from_frame(
                    {
                        "body": {
                            "msgtype": "text",
                            "chatid": "group-chat-id",
                            "text": {"content": "hello"},
                        }
                    }
                )
                self.assertTrue(result["registered"])
                self.assertTrue(result["added"])
                config = load_bot_config()
                self.assertEqual("group-chat-id", config.chat_id)
                self.assertEqual(("group-chat-id",), config.chat_ids)

    def test_changing_wecom_aibot_clears_registered_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "bot_settings.json"
            env = {"DARKWEB_BOT_SETTINGS_PATH": str(settings_path)}
            with patch.dict("os.environ", env, clear=True), patch(
                "darkweb_collector.bot_assistant.ensure_wecom_aibot_listener"
            ):
                set_bot_config(bot_id="aibp-old", secret="old-secret", chat_id="old-chat")
                set_bot_config(bot_id="aibp-new", secret="new-secret")
                config = load_bot_config()
                self.assertEqual("aibp-new", config.bot_id)
                self.assertEqual((), config.chat_ids)

    def test_save_webhook_key_still_builds_wechat_work_url_for_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "bot_settings.json"
            env = {"DARKWEB_BOT_SETTINGS_PATH": str(settings_path)}
            with patch.dict("os.environ", env, clear=True):
                set_bot_config(provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK, webhook_key="key-only")
                config = load_bot_config()
                self.assertEqual("key-only", config.webhook_key)
                self.assertEqual("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=key-only", config.webhook_url)
                self.assertEqual(BOT_PROVIDER_WECHAT_WORK_WEBHOOK, config.provider)

    def test_signed_webhook_appends_timestamp_and_sign(self) -> None:
        captured = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"errcode":0,"errmsg":"ok"}'

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return FakeResponse()

        config = BotConfig(
            provider=BOT_PROVIDER_WECHAT_WORK_WEBHOOK,
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef123456",
            webhook_key="abcdef123456",
            secret="top-secret",
        )
        with patch("darkweb_collector.bot_assistant.urlopen", fake_urlopen):
            result = post_bot_payload(build_text_payload("hello"), config)

        self.assertTrue(result["ok"])
        self.assertIn("timestamp=", captured["url"])
        self.assertIn("sign=", captured["url"])

    def test_wecom_aibot_markdown_payload_uses_sdk_body_shape(self) -> None:
        payload = build_wecom_aibot_markdown_payload("### title")
        self.assertEqual({"msgtype": "markdown", "markdown": {"content": "### title"}}, payload)
        result = post_bot_payload(build_markdown_payload("### title"), BotConfig(dry_run=True))
        self.assertEqual(payload, result["payload"])

    def test_wecom_aibot_requires_bot_id_and_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings_path = Path(tmp_dir) / "bot_settings.json"
            with patch.dict("os.environ", {"DARKWEB_BOT_SETTINGS_PATH": str(settings_path)}, clear=True):
                with self.assertRaises(BotAssistantError):
                    set_bot_config(bot_id="", secret="")

    def test_wecom_aibot_send_requires_registered_target(self) -> None:
        config = BotConfig(bot_id="aibp-example-bot-id-123456", secret="example-secret")
        with self.assertRaises(BotAssistantError):
            post_bot_payload(build_markdown_payload("### title"), config)

    def test_wecom_aibot_listener_does_not_restart_same_config_while_authenticating(self) -> None:
        class FakeThread:
            instances = []

            def __init__(self, *args, **kwargs):
                self.started = False
                FakeThread.instances.append(self)

            def start(self) -> None:
                self.started = True

            def is_alive(self) -> bool:
                return True

        listener = bot_assistant_module._WeComAibotListener()
        config = BotConfig(bot_id="aibp-example-bot-id-123456", secret="example-secret")

        with patch("darkweb_collector.bot_assistant.Thread", FakeThread):
            listener.ensure_started(config)
            first_stop_event = listener._stop_event
            listener.ensure_started(config)

        self.assertEqual(1, len(FakeThread.instances))
        self.assertIsNotNone(first_stop_event)
        self.assertFalse(first_stop_event.is_set())

    def test_wecom_aibot_listener_restarts_same_config_after_stale_connection_error(self) -> None:
        class FakeThread:
            instances = []

            def __init__(self, *args, **kwargs):
                FakeThread.instances.append(self)

            def start(self) -> None:
                pass

            def is_alive(self) -> bool:
                return True

        listener = bot_assistant_module._WeComAibotListener()
        config = BotConfig(bot_id="aibp-example-bot-id-123456", secret="example-secret")

        with patch("darkweb_collector.bot_assistant.Thread", FakeThread), patch(
            "darkweb_collector.bot_assistant.time.monotonic",
            side_effect=[100.0, 116.0],
        ):
            listener.ensure_started(config)
            first_stop_event = listener._stop_event
            listener._last_error = "sent 1000 (OK); no close frame received"
            listener.ensure_started(config)

        self.assertEqual(2, len(FakeThread.instances))
        self.assertIsNotNone(first_stop_event)
        self.assertTrue(first_stop_event.is_set())

    def test_wecom_aibot_listener_keeps_same_config_with_recent_connection_error(self) -> None:
        class FakeThread:
            instances = []

            def __init__(self, *args, **kwargs):
                FakeThread.instances.append(self)

            def start(self) -> None:
                pass

            def is_alive(self) -> bool:
                return True

        listener = bot_assistant_module._WeComAibotListener()
        config = BotConfig(bot_id="aibp-example-bot-id-123456", secret="example-secret")

        with patch("darkweb_collector.bot_assistant.Thread", FakeThread), patch(
            "darkweb_collector.bot_assistant.time.monotonic",
            side_effect=[100.0, 101.0],
        ):
            listener.ensure_started(config)
            first_stop_event = listener._stop_event
            listener._last_error = "temporary connection error"
            listener.ensure_started(config)

        self.assertEqual(1, len(FakeThread.instances))
        self.assertIsNotNone(first_stop_event)
        self.assertFalse(first_stop_event.is_set())

    def test_wecom_aibot_listener_restarts_when_config_changes(self) -> None:
        class FakeThread:
            instances = []

            def __init__(self, *args, **kwargs):
                FakeThread.instances.append(self)

            def start(self) -> None:
                pass

            def is_alive(self) -> bool:
                return True

        listener = bot_assistant_module._WeComAibotListener()

        with patch("darkweb_collector.bot_assistant.Thread", FakeThread):
            listener.ensure_started(BotConfig(bot_id="aibp-example-bot-id-123456", secret="old-secret"))
            first_stop_event = listener._stop_event
            listener.ensure_started(BotConfig(bot_id="aibp-example-bot-id-123456", secret="new-secret"))

        self.assertEqual(2, len(FakeThread.instances))
        self.assertIsNotNone(first_stop_event)
        self.assertTrue(first_stop_event.is_set())

    def test_wecom_aibot_post_can_run_inside_existing_event_loop(self) -> None:
        async def fake_post_async(payload, config):
            return {"ok": True, "payload": payload, "bot_id": config.bot_id}

        async def runner():
            return bot_assistant_module._post_wecom_aibot_payload(
                build_markdown_payload("### title"),
                BotConfig(bot_id="aibp-example-bot-id-123456", secret="example-secret", chat_ids=("chat-id",)),
            )

        with patch("darkweb_collector.bot_assistant._post_wecom_aibot_payload_async", fake_post_async):
            result = asyncio.run(runner())

        self.assertTrue(result["ok"])
        self.assertEqual("aibp-example-bot-id-123456", result["bot_id"])


if __name__ == "__main__":
    unittest.main()
