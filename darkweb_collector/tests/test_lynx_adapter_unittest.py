from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.adapters.lynx import LynxAdapter
from darkweb_collector.db import get_db_connection
from darkweb_collector.models import RunContext, SiteConfig


SEED_HTML = """
<html>
  <head><title>Lynx Leaks</title></head>
  <body>
    <h4 class="chat__block-title">Stera Chemicals</h4>
    publication: <span>2026-03-14</span>
    Category: <span>Manufacturing</span>
    Views: <span>12</span>
    <a href="http://lynxblogtwatfsrwj3oatpejwxk5bngqcd5f7s26iskagfu7ouaomjad.onion/leaks/69a3e76b9c439c5f45279cb9">Go to the publication</a>
  </body>
</html>
"""

DETAIL_HTML = """
<html>
  <head><title>Stera Chemicals</title></head>
  <body>
    publication: <span>2026-03-14</span>
    Category: <span>Manufacturing</span>
    Views: <span>20</span>
    <div class="chat__block-descr">Stera Chemicals internal leak with technical documents and production records.</div>
    <a href="/download/archive.zip" download>download</a>
  </body>
</html>
"""


class LynxAdapterTests(unittest.TestCase):
    def test_detail_persistence_matches_seed_record(self) -> None:
        adapter = LynxAdapter()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_dir = tmp_path / "output"
            config = SiteConfig(
                site_name="lynx",
                enabled=True,
                seed_urls=("http://lynxblogtwatfsrwj3oatpejwxk5bngqcd5f7s26iskagfu7ouaomjad.onion/leaks",),
                seed_fetch_mode="tor_http",
                detail_fetch_mode="tor_http",
                profile="warm",
                max_topics_per_run=10,
                max_detail_pages_per_run=5,
                cooldown_seconds=60,
                output_dir=output_dir,
                dedupe_window_minutes=10,
            )
            run_ctx = RunContext(
                job_id="lynx-seed-test",
                job_type="seed",
                queue_name="seed_http",
                target="lynx",
                started_at_utc="2026-03-14T00:00:00+00:00",
            )

            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                with patch("darkweb_collector.adapters.lynx.fetch_url", return_value=SEED_HTML):
                    seed_result = adapter.collect_seed(config, run_ctx)
                adapter.persist(config=config, run_ctx=run_ctx, seed_result=seed_result)

                detail_tasks = adapter.plan_details(seed_result, config)
                self.assertEqual(1, len(detail_tasks))
                self.assertEqual(
                    seed_result.payload["victims"][0]["source_url"],
                    detail_tasks[0].metadata["source_url"],
                )

                with patch("darkweb_collector.adapters.lynx.fetch_url", return_value=DETAIL_HTML):
                    detail_result = adapter.collect_detail(detail_tasks[0], config, run_ctx)
                adapter.persist(config=config, run_ctx=run_ctx, detail_results=[detail_result])

                with get_db_connection() as connection:
                    detail_count = connection.execute(
                        "SELECT COUNT(*) FROM victim_details"
                    ).fetchone()[0]
                    status = connection.execute(
                        "SELECT last_detail_fetch_status FROM victims WHERE site_name = 'lynx'"
                    ).fetchone()[0]

                self.assertEqual(1, detail_count)
                self.assertEqual("ok", status)
