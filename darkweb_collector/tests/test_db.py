from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from darkweb_collector import db


class DatabaseConnectionTests(unittest.TestCase):
    def test_connect_does_not_rerun_schema_after_regular_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            db._SCHEMA_INIT_FINGERPRINTS.clear()
            try:
                with db.connect(db_path) as connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS runtime_touch (id INTEGER PRIMARY KEY)")
                    connection.execute("INSERT INTO runtime_touch DEFAULT VALUES")
                    connection.commit()

                with patch("darkweb_collector.db._ensure_schema", side_effect=AssertionError("schema reran")):
                    with db.connect(db_path) as connection:
                        value = connection.execute("SELECT COUNT(*) FROM runtime_touch").fetchone()[0]

                self.assertEqual(1, value)
            finally:
                db._SCHEMA_INIT_FINGERPRINTS.clear()

    def test_connect_creates_netdisk_state_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collector.db"
            db._SCHEMA_INIT_FINGERPRINTS.clear()
            try:
                with db.connect(db_path) as connection:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        ).fetchall()
                    }

                self.assertIn("netdisk_source_states", tables)
                self.assertIn("netdisk_source_health", tables)
            finally:
                db._SCHEMA_INIT_FINGERPRINTS.clear()


if __name__ == "__main__":
    unittest.main()
