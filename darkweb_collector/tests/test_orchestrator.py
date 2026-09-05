from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.orchestrator import run_site_once, show_runs
from darkweb_collector.state_store import InMemoryStateStore


SEED_HTML = """
<html>
  <head><title>DragonForce</title></head>
  <body>
    <div class="text"><a class="text-pointer-animations link-published" href="/victim-1">Acme Corp (acme.example)</a></div>
    <div class="timer timer-published">1 March 2026</div>
    <div class=number><b>12 GB</b></div>
  </body>
</html>
"""

DETAIL_HTML = """
<html>
  <head><title>Acme Detail</title></head>
  <body>
    <a href="https://example.com/">external</a>
    Detailed victim page
  </body>
</html>
"""


class OrchestratorTests(unittest.TestCase):
    def test_run_site_once_persists_outputs_and_job_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "sites.yaml"
            db_path = tmp_path / "collector.db"
            output_dir = tmp_path / "output"
            config_path.write_text(
                json.dumps(
                    {
                        "sites": [
                            {
                                "site_name": "dragonforce",
                                "enabled": True,
                                "seed_urls": ["http://dragon.onion/"],
                                "seed_fetch_mode": "tor_http",
                                "detail_fetch_mode": "tor_http",
                                "profile": "hot",
                                "max_topics_per_run": 5,
                                "max_detail_pages_per_run": 1,
                                "cooldown_seconds": 60,
                                "output_dir": str(output_dir),
                                "dedupe_window_minutes": 5,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                with patch("darkweb_collector.adapters.dragonforce.fetch_url", return_value=SEED_HTML), patch(
                    "darkweb_collector.adapters.dragonforce.fetch_page_artifacts",
                    return_value=(DETAIL_HTML, None),
                ):
                    result = run_site_once(
                        "dragonforce",
                        config_path=config_path,
                        state_store=InMemoryStateStore(),
                    )

                self.assertEqual("dragonforce", result["site_name"])
                self.assertTrue((output_dir / "latest.json").exists())
                detail_json_files = list((output_dir / "details").glob("*.json"))
                self.assertEqual(1, len(detail_json_files))

                runs = show_runs(limit=10)
                statuses = {(row["job_type"], row["status"]) for row in runs}
                self.assertIn(("seed", "succeeded"), statuses)
                self.assertIn(("detail", "succeeded"), statuses)

    def test_run_site_once_continues_when_one_detail_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "sites.yaml"
            db_path = tmp_path / "collector.db"
            output_dir = tmp_path / "output"
            config_path.write_text(
                json.dumps(
                    {
                        "sites": [
                            {
                                "site_name": "dragonforce",
                                "enabled": True,
                                "seed_urls": ["http://dragon.onion/"],
                                "seed_fetch_mode": "tor_http",
                                "detail_fetch_mode": "tor_http",
                                "profile": "hot",
                                "max_topics_per_run": 5,
                                "max_detail_pages_per_run": 1,
                                "cooldown_seconds": 60,
                                "output_dir": str(output_dir),
                                "dedupe_window_minutes": 5,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                with patch("darkweb_collector.adapters.dragonforce.fetch_url", return_value=SEED_HTML), patch(
                    "darkweb_collector.adapters.dragonforce.fetch_page_artifacts",
                    side_effect=RuntimeError("detail boom"),
                ):
                    result = run_site_once(
                        "dragonforce",
                        config_path=config_path,
                        state_store=InMemoryStateStore(),
                    )

                self.assertEqual(1, result["detail_failed_count"])
                runs = show_runs(limit=10)
                statuses = {(row["job_type"], row["status"]) for row in runs}
                self.assertIn(("seed", "succeeded"), statuses)
                self.assertIn(("detail", "failed"), statuses)
