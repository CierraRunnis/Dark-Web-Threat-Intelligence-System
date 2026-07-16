from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import time
import unittest
from unittest.mock import Mock, patch

from darkweb_collector import github_app_auth as github_app


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class GitHubAppAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        with github_app._STATE_LOCK:
            github_app._TOKEN_CACHE.update(
                {
                    "fingerprint": "",
                    "token": "",
                    "expires_epoch": 0.0,
                    "retry_after_epoch": 0.0,
                }
            )
            github_app._STATE.update(
                {
                    "last_error": "",
                    "last_validated_at": "",
                    "token_expires_at": "",
                }
            )

    def test_save_validates_and_status_never_exposes_secret_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / "github-app.json"
            env = {"DARKWEB_GITHUB_APP_CONFIG_FILE": str(config_path)}
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(
                    github_app,
                    "_exchange_installation_token",
                    return_value=("installation-token", "2099-01-01T00:00:00Z", 4_070_908_800.0),
                ) as exchange,
            ):
                status = github_app.save_github_app_config(
                    app_id=123,
                    installation_id=456,
                    private_key="private-key-test-value",
                )
                token = github_app.github_app_installation_token()
                stored = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(token, "installation-token")
            self.assertEqual(status["appId"], 123)
            self.assertEqual(status["installationId"], 456)
            self.assertTrue(status["configured"])
            self.assertEqual(stored["private_key"], "private-key-test-value\n")
            self.assertNotIn("private-key-test-value", json.dumps(status))
            self.assertNotIn("installation-token", json.dumps(status))
            exchange.assert_called_once()

    def test_failed_validation_does_not_write_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / "github-app.json"
            env = {"DARKWEB_GITHUB_APP_CONFIG_FILE": str(config_path)}
            error = github_app.GitHubAppConnectionError("rejected", code="credentials_rejected")
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(github_app, "_exchange_installation_token", side_effect=error),
            ):
                with self.assertRaises(github_app.GitHubAppConnectionError):
                    github_app.save_github_app_config(
                        app_id=123,
                        installation_id=456,
                        private_key="invalid-test-key",
                    )
                status = github_app.github_app_config_status()

            self.assertFalse(config_path.exists())
            self.assertFalse(status["configured"])
            self.assertEqual(status["lastError"], "credentials_rejected")

    def test_existing_private_key_can_be_retained_on_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / "github-app.json"
            config_path.write_text(
                json.dumps({"app_id": 1, "installation_id": 2, "private_key": "saved-key"}),
                encoding="utf-8",
            )
            env = {"DARKWEB_GITHUB_APP_CONFIG_FILE": str(config_path)}
            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(
                    github_app,
                    "_exchange_installation_token",
                    return_value=("new-token", "2099-01-01T00:00:00Z", 4_070_908_800.0),
                ) as exchange,
            ):
                status = github_app.save_github_app_config(app_id=3, installation_id=4)
                saved = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(saved["private_key"], "saved-key\n")
            self.assertEqual(status["appId"], 3)
            credentials = exchange.call_args.args[0]
            self.assertEqual(credentials.private_key, "saved-key\n")

    def test_delete_removes_file_and_cached_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / "github-app.json"
            config_path.write_text(
                json.dumps({"app_id": 1, "installation_id": 2, "private_key": "saved-key"}),
                encoding="utf-8",
            )
            env = {"DARKWEB_GITHUB_APP_CONFIG_FILE": str(config_path)}
            with patch.dict(os.environ, env, clear=True):
                status = github_app.delete_github_app_config()

            self.assertFalse(config_path.exists())
            self.assertFalse(status["configured"])
            self.assertEqual(github_app._TOKEN_CACHE["token"], "")

    def test_installation_token_request_uses_app_jwt_and_does_not_assume_token_length(self) -> None:
        credentials = github_app.GitHubAppCredentials(123, 456, "test-key\n")
        token_value = "variable-format-installation-token-value"
        urlopen_mock = Mock(
            return_value=_Response({"token": token_value, "expires_at": "2099-01-01T00:00:00Z"})
        )
        with (
            patch.object(github_app, "_encode_app_jwt", return_value="signed-app-jwt"),
            patch.object(github_app, "urlopen", urlopen_mock),
        ):
            token, expires_at, expires_epoch = github_app._exchange_installation_token(credentials)

        request = urlopen_mock.call_args.args[0]
        self.assertEqual(token, token_value)
        self.assertEqual(expires_at, "2099-01-01T00:00:00Z")
        self.assertGreater(expires_epoch, time.time())
        self.assertTrue(request.full_url.endswith("/app/installations/456/access_tokens"))
        self.assertEqual(request.get_header("Authorization"), "Bearer signed-app-jwt")
        self.assertEqual(request.get_header("X-github-api-version"), github_app.GITHUB_API_VERSION)

    def test_concurrent_token_reads_share_one_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            config_path = Path(temporary_dir) / "github-app.json"
            config_path.write_text(
                json.dumps({"app_id": 1, "installation_id": 2, "private_key": "saved-key"}),
                encoding="utf-8",
            )
            env = {"DARKWEB_GITHUB_APP_CONFIG_FILE": str(config_path)}

            def exchange(_credentials):
                time.sleep(0.02)
                return "shared-token", "2099-01-01T00:00:00Z", 4_070_908_800.0

            with (
                patch.dict(os.environ, env, clear=True),
                patch.object(github_app, "_exchange_installation_token", side_effect=exchange) as exchange_mock,
                ThreadPoolExecutor(max_workers=4) as executor,
            ):
                tokens = list(executor.map(lambda _: github_app.github_app_installation_token(), range(4)))

            self.assertEqual(tokens, ["shared-token"] * 4)
            self.assertEqual(exchange_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
