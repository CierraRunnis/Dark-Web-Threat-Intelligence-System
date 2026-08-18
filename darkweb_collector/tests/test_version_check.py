from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import version_check


class VersionCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        version_check.clear_version_status_cache()

    def tearDown(self) -> None:
        version_check.clear_version_status_cache()

    def test_current_version_uses_independent_release_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            version_file = Path(temporary_dir) / "version.json"
            version_file.write_text(
                json.dumps(
                    {
                        "version": "v0.21.0",
                        "commit": "a" * 40,
                        "branch": "v.0.21.0",
                        "repository": version_check.DEFAULT_REPOSITORY,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"DARKWEB_VERSION_FILE": str(version_file)}, clear=False):
                with patch.object(version_check, "_git_commit", return_value="b" * 40):
                    payload = version_check.current_version_payload()

        self.assertEqual("v0.21.0", payload["version"])
        self.assertEqual("a" * 40, payload["commit"])
        self.assertEqual("b" * 40, payload["local_commit"])
        self.assertEqual("version_file", payload["source"])

    def test_release_lookup_selects_highest_three_part_release_branch(self) -> None:
        output = "\n".join(
            [
                f"{'1' * 40}\trefs/heads/v.0.20.0",
                f"{'2' * 40}\trefs/heads/v.0.21.0",
                f"{'3' * 40}\trefs/heads/v.10.0",
                f"{'4' * 40}\trefs/heads/agent/release-v0.22.0",
            ]
        )
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=output, stderr="")
        with patch.object(version_check.subprocess, "run", return_value=completed):
            payload = version_check.latest_github_release(version_check.DEFAULT_REPOSITORY)

        self.assertEqual("v0.21.0", payload["version"])
        self.assertEqual("v.0.21.0", payload["branch"])
        self.assertEqual("2" * 40, payload["commit"])

    def test_status_reports_release_without_enabling_update(self) -> None:
        current = {
            "version": "v0.21.0",
            "commit": "a" * 40,
            "short_commit": "aaaaaaa",
            "branch": "v.0.21.0",
            "repository": version_check.DEFAULT_REPOSITORY,
        }
        latest = {
            "version": "v0.22.0",
            "commit": "b" * 40,
            "short_commit": "bbbbbbb",
            "branch": "v.0.22.0",
            "html_url": "https://github.com/example/release",
        }
        with patch.object(version_check, "current_version_payload", return_value=current):
            with patch.object(version_check, "latest_github_release", return_value=latest):
                payload = version_check.build_version_status(force=True)

        self.assertEqual("release", payload["channel"])
        self.assertTrue(payload["update_available"])
        self.assertFalse(payload["update_enabled"])
        self.assertEqual("发现新版本", payload["message"])
        self.assertIn("compare", payload["compare_url"])

    def test_cached_status_is_reused_until_forced(self) -> None:
        current = {
            "version": "v0.21.0",
            "commit": "a" * 40,
            "short_commit": "aaaaaaa",
            "branch": "v.0.21.0",
            "repository": version_check.DEFAULT_REPOSITORY,
        }
        latest = {
            "version": "v0.21.0",
            "commit": "a" * 40,
            "short_commit": "aaaaaaa",
            "branch": "v.0.21.0",
            "html_url": "https://github.com/example/release",
        }
        with patch.object(version_check, "current_version_payload", return_value=current):
            with patch.object(version_check, "latest_github_release", return_value=latest) as lookup:
                first = version_check.build_version_status(force=True)
                cached = version_check.build_version_status()
                refreshed = version_check.build_version_status(force=True)

        self.assertEqual(2, lookup.call_count)
        self.assertEqual(first, cached)
        self.assertFalse(refreshed["update_available"])


if __name__ == "__main__":
    unittest.main()
