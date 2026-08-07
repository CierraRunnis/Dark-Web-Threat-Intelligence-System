from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from darkweb_collector import api_app
from darkweb_collector.document_exposure_sessions import visible_platform_login_available


class AdaptivePlatformLoginTests(unittest.TestCase):
    def test_force_embedded_browser_disables_visible_login(self):
        with patch.dict(os.environ, {"DARKWEB_FORCE_EMBEDDED_BROWSER": "1"}):
            self.assertFalse(visible_platform_login_available())

    def test_headless_linux_disables_visible_login(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"DISPLAY", "WAYLAND_DISPLAY", "DARKWEB_FORCE_EMBEDDED_BROWSER"}
        }
        with (
            patch.object(os, "name", "posix"),
            patch.dict(os.environ, environment, clear=True),
        ):
            self.assertFalse(visible_platform_login_available())

    def test_adaptive_login_prefers_visible_browser(self):
        external = {"platform": "github", "mode": "external_browser", "pid": 42}
        with (
            patch.object(api_app, "chaojiying_configured", return_value=False),
            patch.object(api_app, "visible_platform_login_available", return_value=True),
            patch.object(api_app, "launch_platform_login", return_value=external) as launch,
            patch.object(api_app, "start_remote_browser_login") as embedded,
        ):
            payload = api_app.platform_session_adaptive_login_start("github")

        self.assertEqual(payload, external)
        launch.assert_called_once_with("github")
        embedded.assert_not_called()

    def test_adaptive_login_uses_embedded_browser_without_desktop(self):
        embedded = {"platform": "github", "session_id": "session-1", "mode": "embedded_browser"}
        with (
            patch.object(api_app, "chaojiying_configured", return_value=False),
            patch.object(api_app, "visible_platform_login_available", return_value=False),
            patch.object(api_app, "launch_platform_login") as launch,
            patch.object(api_app, "start_remote_browser_login", return_value=embedded) as start_embedded,
        ):
            payload = api_app.platform_session_adaptive_login_start("github")

        self.assertEqual(payload["mode"], "embedded_browser")
        self.assertEqual(payload["session_id"], "session-1")
        self.assertIn("desktop", payload["fallback_reason"])
        launch.assert_not_called()
        start_embedded.assert_called_once_with("github")

    def test_adaptive_login_falls_back_when_visible_browser_exits(self):
        embedded = {"platform": "github", "session_id": "session-2", "mode": "embedded_browser"}
        with (
            patch.object(api_app, "chaojiying_configured", return_value=False),
            patch.object(api_app, "visible_platform_login_available", return_value=True),
            patch.object(api_app, "launch_platform_login", side_effect=ValueError("browser exited")),
            patch.object(api_app, "start_remote_browser_login", return_value=embedded),
        ):
            payload = api_app.platform_session_adaptive_login_start("github")

        self.assertEqual(payload["mode"], "embedded_browser")
        self.assertEqual(payload["fallback_reason"], "browser exited")

    def test_adaptive_login_uses_embedded_browser_when_captcha_api_is_configured(self):
        embedded = {"platform": "changan", "session_id": "session-3", "mode": "embedded_browser"}
        with (
            patch.object(api_app, "chaojiying_configured", return_value=True),
            patch.object(api_app, "visible_platform_login_available", return_value=True),
            patch.object(api_app, "launch_platform_login") as launch,
            patch.object(api_app, "start_remote_browser_login", return_value=embedded) as start_embedded,
        ):
            payload = api_app.platform_session_adaptive_login_start("changan")

        self.assertEqual(payload["mode"], "embedded_browser")
        self.assertIn("Chaojiying", payload["fallback_reason"])
        launch.assert_not_called()
        start_embedded.assert_called_once_with("changan")


if __name__ == "__main__":
    unittest.main()
