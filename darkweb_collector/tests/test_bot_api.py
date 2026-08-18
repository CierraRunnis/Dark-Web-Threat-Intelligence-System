from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import darkweb_collector.api_app as api_app
import darkweb_collector.bot_assistant as bot
import darkweb_collector.monitoring_notifications as notifications
import darkweb_collector.normalized_intelligence as normalized


def _request(*, role: str = "user", modules: list[str] | None = None) -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/bot/status",
            "raw_path": b"/api/bot/status",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )
    request.state.current_user = {
        "username": "tester",
        "role": role,
        "is_admin": role == "admin",
        "modules": list(modules or []),
        "enabled": True,
    }
    return request


class BotApiTests(unittest.TestCase):
    def test_status_requires_file_monitoring_and_returns_masked_status(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            api_app.bot_status(_request())
        self.assertEqual(403, raised.exception.status_code)

        expected = {"configured": True, "bot_id": "bot-****"}
        with patch.object(api_app, "bot_config_status", return_value=expected):
            result = api_app.bot_status(_request(modules=["file_monitoring"]))
        self.assertEqual(expected, result)

    def test_config_and_send_are_admin_only(self) -> None:
        config = api_app.BotConfigRequest(bot_id="bot-id", secret="secret")
        with self.assertRaises(HTTPException) as raised:
            api_app.save_bot_config(config, _request(modules=["file_monitoring"]))
        self.assertEqual(403, raised.exception.status_code)

        message = api_app.BotSendRequest(type="markdown", content="test")
        with self.assertRaises(HTTPException) as raised:
            api_app.send_bot(message, _request(modules=["file_monitoring"]))
        self.assertEqual(403, raised.exception.status_code)

    def test_admin_can_save_config_without_exposing_secret(self) -> None:
        payload = api_app.BotConfigRequest(bot_id="bot-id", secret="secret-value")
        saved = {"configured": True, "bot_id": "bot****", "has_secret": True}
        config = SimpleNamespace(chat_ids=(), provider="wechat_work_aibot")
        with patch.object(api_app, "set_bot_config", return_value=saved) as setter, patch.object(
            api_app,
            "load_bot_config",
            return_value=config,
        ):
            result = api_app.save_bot_config(payload, _request(role="admin"))
        self.assertEqual(saved, result)
        setter.assert_called_once_with(
            provider="wechat_work_aibot",
            bot_id="bot-id",
            chat_id="",
            websocket_url="",
            webhook_url="",
            webhook_key="",
            secret="secret-value",
        )
        self.assertNotIn("secret-value", json.dumps(result))

    def test_admin_can_send_markdown(self) -> None:
        payload = api_app.BotSendRequest(type="markdown", content="hello")
        config = SimpleNamespace()
        with patch.object(api_app, "load_bot_config", return_value=config), patch.object(
            api_app,
            "post_bot_payload",
            return_value={"ok": True},
        ) as post:
            result = api_app.send_bot(payload, _request(role="admin"))
        self.assertEqual({"ok": True}, result)
        post.assert_called_once_with(
            {"msgtype": "markdown", "markdown": {"content": "hello"}},
            config,
        )

    def test_saved_bot_secret_is_masked_and_file_is_private(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "bot.json"
            with patch.dict(
                os.environ,
                {bot.BOT_SETTINGS_PATH_ENV: str(settings_path)},
                clear=False,
            ), patch.object(bot, "ensure_wecom_aibot_listener"):
                status = bot.set_bot_config(bot_id="bot-123456", secret="top-secret")
            stored = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual("top-secret", stored["secret"])
            self.assertNotIn("top-secret", json.dumps(status))
            if os.name != "nt":
                self.assertEqual(0, settings_path.stat().st_mode & 0o077)

    def test_current_notification_scan_never_refreshes_normalization(self) -> None:
        connection = object()
        with patch.object(notifications, "get_db_connection") as connection_factory, patch.object(
            normalized,
            "load_normalized_events",
            return_value=[],
        ) as load_events, patch.object(
            notifications,
            "notify_keyword_matches_for_events",
            return_value={"sent": 0},
        ) as notify:
            connection_factory.return_value.__enter__.return_value = connection
            result = notifications.notify_current_keyword_matches()
        self.assertEqual({"sent": 0}, result)
        load_events.assert_called_once_with(connection, allow_refresh=False)
        notify.assert_called_once_with(connection, [], config=None)

    def test_bot_routes_are_registered_once(self) -> None:
        pairs = []
        for route in api_app.app.routes:
            if route.path.startswith("/api/bot/"):
                for method in getattr(route, "methods", None) or {"WEBSOCKET"}:
                    if method not in {"HEAD", "OPTIONS"}:
                        pairs.append((route.path, method))
        self.assertCountEqual(
            [
                ("/api/bot/status", "GET"),
                ("/api/bot/config", "POST"),
                ("/api/bot/send", "POST"),
            ],
            pairs,
        )


if __name__ == "__main__":
    unittest.main()
