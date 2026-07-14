from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from darkweb_collector.version_check import current_version_payload


class VersionBranchTests(unittest.TestCase):
    def test_version_file_branch_is_used_instead_of_checked_out_branch(self) -> None:
        with (
            patch.dict(os.environ, {"DARKWEB_UPDATE_BRANCH": ""}, clear=False),
            patch(
                "darkweb_collector.version_check._load_version_file",
                return_value={"version": "v0.12.0", "branch": "main"},
            ),
            patch("darkweb_collector.version_check._git_commit", return_value="abcdef123456"),
        ):
            payload = current_version_payload()

        self.assertEqual(payload["branch"], "main")

    def test_environment_can_override_update_branch(self) -> None:
        with (
            patch.dict(os.environ, {"DARKWEB_UPDATE_BRANCH": "release-test"}, clear=False),
            patch(
                "darkweb_collector.version_check._load_version_file",
                return_value={"version": "v0.12.0", "branch": "main"},
            ),
            patch("darkweb_collector.version_check._git_commit", return_value="abcdef123456"),
        ):
            payload = current_version_payload()

        self.assertEqual(payload["branch"], "release-test")


if __name__ == "__main__":
    unittest.main()
