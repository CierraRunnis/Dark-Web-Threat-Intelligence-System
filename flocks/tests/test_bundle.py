from pathlib import Path
import sys
import tempfile
import unittest

BUNDLE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUNDLE / "scripts"))
from install_plugins import install
from verify_bundle import verify


class BundleTests(unittest.TestCase):
    def test_dependency_closure_and_checksums(self):
        result = verify(BUNDLE)
        self.assertEqual((4, 7, 3, 25), (result["workflows"], result["agents"], result["custom_tools"], result["verified_plugin_files"]))

    def test_dry_run_and_install_are_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "flocks-home"
            preview = install(BUNDLE, destination, dry_run=True)
            self.assertEqual(25, preview["copied_or_planned"])
            self.assertFalse(destination.exists())
            result = install(BUNDLE, destination)
            self.assertEqual(25, result["copied_or_planned"])
            self.assertFalse((destination / "config").exists())
            self.assertEqual(25, install(BUNDLE, destination)["unchanged"])

    def test_conflicts_do_not_write_any_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            conflict = destination / "plugins/agents/report-agent/prompt.md"
            conflict.parent.mkdir(parents=True)
            conflict.write_text("local customization", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                install(BUNDLE, destination)
            self.assertEqual("local customization", conflict.read_text(encoding="utf-8"))
            self.assertEqual([conflict], [path for path in destination.rglob("*") if path.is_file()])
            self.assertEqual(25, install(BUNDLE, destination, overwrite=True)["copied_or_planned"])


if __name__ == "__main__":
    unittest.main()
