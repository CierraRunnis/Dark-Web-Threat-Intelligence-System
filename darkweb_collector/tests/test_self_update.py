from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from darkweb_collector.self_update import SelfUpdateError, apply_git_update
from darkweb_collector.version_check import current_version_payload


def _git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class SelfUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.source = root / "source"
        self.remote = root / "remote.git"
        self.checkout = root / "checkout"

        self.source.mkdir()
        _git(self.source, "init")
        _git(self.source, "config", "user.name", "Update Test")
        _git(self.source, "config", "user.email", "update-test@example.invalid")
        (self.source / "version.txt").write_text("one\n", encoding="utf-8")
        _git(self.source, "add", "version.txt")
        _git(self.source, "commit", "-m", "initial")
        _git(self.source, "branch", "-M", "main")
        subprocess.run(["git", "clone", "--bare", str(self.source), str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(self.remote), str(self.checkout)], check=True, capture_output=True)
        _git(self.source, "remote", "add", "origin", str(self.remote))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def push_remote_change(self) -> str:
        (self.source / "version.txt").write_text("two\n", encoding="utf-8")
        _git(self.source, "add", "version.txt")
        _git(self.source, "commit", "-m", "remote update")
        _git(self.source, "push", "origin", "main")
        return _git(self.source, "rev-parse", "HEAD")

    def test_apply_git_update_fast_forwards_current_branch(self):
        expected_commit = self.push_remote_change()

        result = apply_git_update(self.checkout, "main")

        self.assertTrue(result["updated"])
        self.assertEqual(result["after_commit"], expected_commit)
        self.assertEqual((self.checkout / "version.txt").read_text(encoding="utf-8"), "two\n")

    def test_apply_git_update_rejects_tracked_local_changes(self):
        (self.checkout / "version.txt").write_text("local\n", encoding="utf-8")

        with self.assertRaisesRegex(SelfUpdateError, "未提交修改"):
            apply_git_update(self.checkout, "main")

    def test_current_version_prefers_live_git_branch_and_commit(self):
        expected_commit = _git(self.checkout, "rev-parse", "HEAD")
        old_branch = os.environ.pop("DARKWEB_UPDATE_BRANCH", None)
        old_commit = os.environ.pop("DARKWEB_APP_COMMIT", None)
        try:
            with patch("darkweb_collector.version_check._project_root", return_value=self.checkout), patch(
                "darkweb_collector.version_check._load_version_file",
                return_value={"branch": "stale-branch", "commit": "stale-commit", "version": "test"},
            ):
                payload = current_version_payload()
        finally:
            if old_branch is not None:
                os.environ["DARKWEB_UPDATE_BRANCH"] = old_branch
            if old_commit is not None:
                os.environ["DARKWEB_APP_COMMIT"] = old_commit

        self.assertEqual(payload["branch"], "main")
        self.assertEqual(payload["commit"], expected_commit)
        self.assertEqual(payload["source"], "git")


if __name__ == "__main__":
    unittest.main()
