from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import version_check
from darkweb_collector.api_app import app


class VersionCheckTests(unittest.TestCase):
    def _version_env(self, temp_dir: str, commit: str = "abc1234567890") -> dict[str, str]:
        version_file = Path(temp_dir) / "version.json"
        version_file.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "commit": commit,
                    "branch": "main",
                    "repository": "demo/repo",
                }
            ),
            encoding="utf-8",
        )
        return {
            "DARKWEB_VERSION_FILE": str(version_file),
            "DARKWEB_APP_COMMIT": "",
            "DARKWEB_UPDATE_BRANCH": "",
            "DARKWEB_UPDATE_REPO": "",
        }

    def test_build_version_status_reports_update_from_main(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, self._version_env(temp_dir), clear=False):
                with patch.object(
                    version_check,
                    "latest_github_version",
                    return_value={
                        "commit": "def9876543210",
                        "short_commit": "def9876",
                        "message": "new version",
                    },
                ):
                    payload = version_check.build_version_status()

        self.assertEqual("main", payload["branch"])
        self.assertTrue(payload["update_available"])
        self.assertEqual("abc1234", payload["current"]["short_commit"])
        self.assertEqual("def9876", payload["latest"]["short_commit"])

    def test_build_version_status_reports_current_version_when_commit_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, self._version_env(temp_dir), clear=False):
                with patch.object(
                    version_check,
                    "latest_github_version",
                    return_value={
                        "commit": "abc1234567890",
                        "short_commit": "abc1234",
                        "message": "same version",
                    },
                ):
                    payload = version_check.build_version_status()

        self.assertFalse(payload["update_available"])
        self.assertEqual("当前已是最新版本", payload["message"])

    def test_system_version_endpoint(self) -> None:
        with patch.dict(os.environ, {"DARKWEB_API_AUTH_DISABLED": "1"}, clear=False):
            with patch("darkweb_collector.api_app.build_version_status", return_value={"status": "ok", "branch": "main"}):
                response = TestClient(app).get("/api/system/version")

        self.assertEqual(200, response.status_code)
        self.assertEqual("main", response.json()["branch"])


if __name__ == "__main__":
    unittest.main()
