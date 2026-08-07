from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from darkweb_collector.changan_auto_login import (
    ChanganAutoLoginCredentials,
    changan_auto_login_available,
    changan_auto_login_config_status,
    delete_changan_auto_login_config,
    load_auto_login_credentials,
    recover_changan_session,
    save_changan_auto_login_config,
    test_changan_auto_login_config,
)
from darkweb_collector.models import SiteConfig


BASE_URL = "http://cabyceogpsji73sske5nvo45mdrkbz4m3qd3iommf3zaaa6izg3j2cqd.onion"


def _config() -> SiteConfig:
    return SiteConfig(
        site_name="changan",
        enabled=True,
        seed_urls=(f"{BASE_URL}/#/home",),
        seed_fetch_mode="tor_http",
        detail_fetch_mode="browser",
        profile="hot",
        max_topics_per_run=30,
        max_detail_pages_per_run=15,
        cooldown_seconds=1800,
        output_dir=Path("output/changan"),
        dedupe_window_minutes=120,
        extras={
            "auth_platform": "changan",
            "auth_origin": BASE_URL,
            "auth_storage_key": "token",
        },
    )


class ChanganAutoLoginTests(unittest.TestCase):
    def test_frontend_config_stores_only_changan_credentials_and_never_echoes_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "auto-login.json"
            environment = {
                "DARKWEB_CHANGAN_AUTO_LOGIN_CONFIG_FILE": str(path),
                "DARKWEB_CHAOJIYING_USER": "test-chao",
                "DARKWEB_CHAOJIYING_PASSWORD": "plain-chao-password",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("darkweb_collector.changan_auto_login._session_auto_login_state", return_value={}),
            ):
                status = save_changan_auto_login_config(
                    enabled=True,
                    changan_username="test-changan",
                    changan_password="plain-changan-password",
                )
                stored_text = path.read_text(encoding="utf-8")
                stored = json.loads(stored_text)
                credentials = load_auto_login_credentials()

        self.assertEqual(set(stored), {"enabled", "DARKWEB_CHANGAN_USERNAME", "DARKWEB_CHANGAN_PASSWORD"})
        self.assertNotIn("plain-chao-password", stored_text)
        self.assertEqual(credentials.chaojiying_password, "plain-chao-password")
        self.assertEqual(credentials.changan_password, "plain-changan-password")
        self.assertTrue(status["configured"])
        self.assertTrue(status["providerConfigured"])
        self.assertTrue(status["ready"])
        self.assertNotIn("test-chao", repr(status))
        self.assertNotIn("test-changan", repr(status))
        self.assertNotIn("plain-changan-password", repr(status))

    def test_frontend_config_blank_secrets_preserve_existing_values_and_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "auto-login.json"
            environment = {
                "DARKWEB_CHANGAN_AUTO_LOGIN_CONFIG_FILE": str(path),
                "DARKWEB_CHAOJIYING_USER": "test-chao",
                "DARKWEB_CHAOJIYING_PASSWORD": "chao-password",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("darkweb_collector.changan_auto_login._session_auto_login_state", return_value={}),
            ):
                save_changan_auto_login_config(
                    enabled=True,
                    changan_username="test-changan",
                    changan_password="changan-password",
                )
                save_changan_auto_login_config(enabled=False)
                credentials = load_auto_login_credentials()
                status = changan_auto_login_config_status()
                deleted = delete_changan_auto_login_config()
                file_deleted = not path.exists()

        self.assertEqual(credentials.changan_password, "changan-password")
        self.assertFalse(status["enabled"])
        self.assertFalse(deleted["configured"])
        self.assertTrue(file_deleted)

    def test_frontend_test_returns_only_sanitized_attempt_counts(self):
        credentials = ChanganAutoLoginCredentials(
            chaojiying_user="test-chao",
            chaojiying_pass2="0123456789abcdef0123456789abcdef",
            changan_username="test-changan",
            changan_password="changan-password",
        )
        login_result = {
            "success": True,
            "authenticated_probe_ok": True,
            "gate_recognition_attempts": 1,
            "login_recognition_attempts": 2,
            "login_error_reports": 1,
        }
        with (
            patch("darkweb_collector.changan_auto_login.load_auto_login_credentials", return_value=credentials),
            patch("darkweb_collector.changan_auto_login.perform_changan_login", return_value=login_result),
            patch("darkweb_collector.changan_auto_login.changan_auto_login_config_status", return_value={"configured": True}),
        ):
            result = test_changan_auto_login_config(_config())

        self.assertEqual(
            result["testResult"],
            {"success": True, "gateAttempts": 1, "loginAttempts": 2, "errorReports": 1},
        )
        self.assertNotIn("test-chao", repr(result))
        self.assertNotIn("changan-password", repr(result))

    def test_combined_credentials_file_is_loaded_without_environment_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "credentials.txt"
            path.write_text(
                "超级鹰:test-chao chao-password\n长安不夜城，test-changan:changan-password\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_CHANGAN_AUTO_LOGIN_CREDENTIALS_FILE": str(path),
                    "DARKWEB_CHAOJIYING_CONFIG_FILE": str(Path(temp_dir) / "provider.json"),
                },
                clear=True,
            ):
                credentials = load_auto_login_credentials()
                available = changan_auto_login_available(_config())

        self.assertTrue(available)
        self.assertEqual(credentials.chaojiying_user, "test-chao")
        self.assertEqual(credentials.chaojiying_password, "chao-password")
        self.assertEqual(credentials.changan_username, "test-changan")
        self.assertEqual(credentials.changan_password, "changan-password")

    def test_explicit_disable_prevents_automatic_login(self):
        environment = {
            "DARKWEB_CHANGAN_AUTO_LOGIN": "0",
            "DARKWEB_CHAOJIYING_USER": "test-chao",
            "DARKWEB_CHAOJIYING_PASSWORD": "chao-password",
            "DARKWEB_CHANGAN_USERNAME": "test-changan",
            "DARKWEB_CHANGAN_PASSWORD": "changan-password",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertFalse(changan_auto_login_available(_config()))

    def test_recovery_saves_new_session_and_marks_it_valid(self):
        credentials = ChanganAutoLoginCredentials(
            chaojiying_user="test-chao",
            chaojiying_password="chao-password",
            changan_username="test-changan",
            changan_password="changan-password",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir)
            state_path = profile / "storage_state.json"
            result = {
                "success": True,
                "session_saved": True,
                "expires_hint": "2026-08-07T00:00:00+00:00",
                "gate_recognition_attempts": 1,
                "login_recognition_attempts": 1,
            }
            with (
                patch("darkweb_collector.changan_auto_login.changan_auto_login_available", return_value=True),
                patch("darkweb_collector.changan_auto_login.platform_profile_dir", return_value=profile),
                patch("darkweb_collector.changan_auto_login.site_auth_readiness", return_value={"ready": False}),
                patch("darkweb_collector.changan_auto_login.get_db_connection", return_value=nullcontext(object())),
                patch("darkweb_collector.changan_auto_login.get_platform_session", return_value={}),
                patch(
                    "darkweb_collector.changan_auto_login.resolve_platform_storage_state_path",
                    return_value=state_path,
                ),
                patch("darkweb_collector.changan_auto_login.load_auto_login_credentials", return_value=credentials),
                patch("darkweb_collector.changan_auto_login.perform_changan_login", return_value=result) as login,
                patch("darkweb_collector.changan_auto_login._update_session") as update,
            ):
                recovered = recover_changan_session(_config(), "expired")

        self.assertTrue(recovered)
        login.assert_called_once()
        self.assertEqual(update.call_args_list[0].kwargs["status"], "login_in_progress")
        self.assertEqual(update.call_args_list[1].kwargs["status"], "valid")
        self.assertEqual(update.call_args_list[1].kwargs["expires_hint"], result["expires_hint"])

    def test_recent_failed_recovery_is_not_retried_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = Path(temp_dir)
            existing = {
                "status": "invalid",
                "metadata_json": json.dumps(
                    {
                        "automatic_login": {
                            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                            "success": False,
                        }
                    }
                ),
            }
            with (
                patch("darkweb_collector.changan_auto_login.changan_auto_login_available", return_value=True),
                patch("darkweb_collector.changan_auto_login.platform_profile_dir", return_value=profile),
                patch("darkweb_collector.changan_auto_login.site_auth_readiness", return_value={"ready": False}),
                patch("darkweb_collector.changan_auto_login.get_db_connection", return_value=nullcontext(object())),
                patch("darkweb_collector.changan_auto_login.get_platform_session", return_value=existing),
                patch("darkweb_collector.changan_auto_login.perform_changan_login") as login,
                patch("darkweb_collector.changan_auto_login._update_session") as update,
            ):
                recovered = recover_changan_session(_config(), "expired")

        self.assertFalse(recovered)
        login.assert_not_called()
        update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
