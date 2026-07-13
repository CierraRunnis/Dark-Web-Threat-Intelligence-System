from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from darkweb_collector.version_check import build_version_status


class VersionCheckTests(unittest.TestCase):
    def _current(self, branch: str, commit: str = "a" * 40) -> dict:
        return {
            "version": "test",
            "commit": commit,
            "short_commit": commit[:7],
            "branch": branch,
            "repository": "owner/repository",
            "updated_at": "",
            "source": "git",
        }

    def test_feature_checkout_still_targets_main_but_cannot_update(self) -> None:
        with patch(
            "darkweb_collector.version_check.current_version_payload",
            return_value=self._current("feature"),
        ), patch(
            "darkweb_collector.version_check.latest_github_version",
            return_value={"commit": "b" * 40, "short_commit": "bbbbbbb"},
        ) as latest:
            status = build_version_status()

        latest.assert_called_once_with("owner/repository", "main")
        self.assertEqual(status["target"]["ref"], "origin/main")
        self.assertEqual(status["relation"], "wrong_branch")
        self.assertFalse(status["update_available"])
        self.assertFalse(status["can_update"])

    def test_main_is_synced_only_when_commits_match(self) -> None:
        commit = "c" * 40
        with patch(
            "darkweb_collector.version_check.current_version_payload",
            return_value=self._current("main", commit),
        ), patch(
            "darkweb_collector.version_check.latest_github_version",
            return_value={"commit": commit, "short_commit": commit[:7]},
        ):
            status = build_version_status()

        self.assertEqual(status["relation"], "identical")
        self.assertFalse(status["update_available"])
        self.assertTrue(status["can_update"])

    def test_github_error_never_reports_synced(self) -> None:
        with patch(
            "darkweb_collector.version_check.current_version_payload",
            return_value=self._current("main"),
        ), patch(
            "darkweb_collector.version_check.latest_github_version",
            side_effect=urllib.error.URLError("offline"),
        ):
            status = build_version_status()

        self.assertEqual(status["status"], "error")
        self.assertEqual(status["relation"], "unknown")
        self.assertFalse(status["update_available"])
        self.assertFalse(status["can_update"])


if __name__ == "__main__":
    unittest.main()
