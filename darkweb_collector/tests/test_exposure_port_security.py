from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import darkweb_collector.api_app as api_app
import darkweb_collector.remote_browser_sessions as remote_sessions


def _request(*, role: str = "user", modules: list[str] | None = None) -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/settings",
            "raw_path": b"/api/settings",
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


class FakeWebSocket:
    def __init__(self, ticket: str = "") -> None:
        self.query_params = {"ticket": ticket}
        self.closed_code: int | None = None

    async def close(self, code: int) -> None:
        self.closed_code = code


class ExposurePortSecurityTests(unittest.TestCase):
    def test_github_app_status_requires_file_monitoring(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            api_app.get_code_monitoring_github_app(_request())
        self.assertEqual(403, raised.exception.status_code)

        with patch.object(api_app, "github_app_config_status", return_value={"configured": False}):
            payload = api_app.get_code_monitoring_github_app(
                _request(modules=["file_monitoring"])
            )
        self.assertEqual({"configured": False}, payload)

    def test_github_app_mutation_is_admin_only(self) -> None:
        payload = api_app.GitHubAppConfigRequest(
            app_id=12,
            installation_id=34,
            private_key="secret-pem",
        )
        with self.assertRaises(HTTPException) as raised:
            api_app.configure_code_monitoring_github_app(
                payload,
                _request(modules=["file_monitoring"]),
            )
        self.assertEqual(403, raised.exception.status_code)

        with patch.object(
            api_app,
            "save_github_app_config",
            return_value={"configured": True},
        ) as save:
            result = api_app.configure_code_monitoring_github_app(
                payload,
                _request(role="admin"),
            )
        self.assertTrue(result["configured"])
        save.assert_called_once_with(
            app_id=12,
            installation_id=34,
            private_key="secret-pem",
        )

    def test_remote_login_http_routes_require_file_monitoring(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            api_app.platform_session_remote_login_start("github", _request())
        self.assertEqual(403, raised.exception.status_code)

        with patch.object(
            api_app,
            "start_remote_browser_login",
            return_value={"session_id": "session-1"},
        ):
            payload = api_app.platform_session_remote_login_start(
                "github",
                _request(modules=["file_monitoring"]),
            )
        self.assertEqual("session-1", payload["session_id"])

    def test_invalid_websocket_ticket_is_rejected_before_proxy(self) -> None:
        socket = FakeWebSocket("invalid")
        with patch.object(api_app, "validate_remote_browser_ticket", return_value=False), patch.object(
            api_app,
            "proxy_remote_browser_stream",
            new=AsyncMock(),
        ) as proxy:
            asyncio.run(
                api_app.platform_session_remote_login_stream(socket, "missing-session")
            )
        self.assertEqual(1008, socket.closed_code)
        proxy.assert_not_awaited()

    def test_valid_websocket_ticket_reaches_proxy(self) -> None:
        socket = FakeWebSocket("valid")
        with patch.object(api_app, "validate_remote_browser_ticket", return_value=True), patch.object(
            api_app,
            "proxy_remote_browser_stream",
            new=AsyncMock(),
        ) as proxy:
            asyncio.run(
                api_app.platform_session_remote_login_stream(socket, "session-1")
            )
        self.assertIsNone(socket.closed_code)
        proxy.assert_awaited_once_with("session-1", socket)

    def test_ticket_comparison_uses_current_live_session(self) -> None:
        session = SimpleNamespace(ws_ticket="current-ticket")
        with patch.object(remote_sessions, "_get_remote_session", return_value=session):
            self.assertTrue(
                remote_sessions.validate_remote_browser_ticket(
                    "session-1",
                    "current-ticket",
                )
            )
            self.assertFalse(
                remote_sessions.validate_remote_browser_ticket(
                    "session-1",
                    "old-ticket",
                )
            )

    def test_shutdown_closes_each_unique_remote_session(self) -> None:
        first = SimpleNamespace(session_id="first", platform="github")
        second = SimpleNamespace(session_id="second", platform="gitee")
        sessions = {
            first.session_id: first,
            first.platform: first,
            second.session_id: second,
            second.platform: second,
        }
        with patch.object(remote_sessions, "_REMOTE_SESSIONS", sessions), patch.object(
            remote_sessions,
            "close_remote_browser_login",
        ) as close:
            remote_sessions.close_all_remote_browser_sessions()
        self.assertEqual(
            {"first", "second"},
            {call.args[0] for call in close.call_args_list},
        )


if __name__ == "__main__":
    unittest.main()
