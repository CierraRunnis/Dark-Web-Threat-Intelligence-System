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

from darkweb_collector.db import get_db_connection, upsert_crawl_job
from darkweb_collector.orchestrator import enqueue_due_sites
from darkweb_collector.queueing import BROWSER_RENDER_QUEUE, DETAIL_HTTP_QUEUE, SEED_HTTP_QUEUE, queue_for_detail, queue_for_seed
from darkweb_collector.state_store import InMemoryStateStore
from darkweb_collector.utils import utc_now_iso


class QueueingTests(unittest.TestCase):
    def test_queue_routing_matches_fetch_mode(self) -> None:
        self.assertEqual(SEED_HTTP_QUEUE, queue_for_seed("tor_http"))
        self.assertEqual(DETAIL_HTTP_QUEUE, queue_for_detail("tor_http"))
        self.assertEqual(BROWSER_RENDER_QUEUE, queue_for_seed("browser"))
        self.assertEqual(BROWSER_RENDER_QUEUE, queue_for_detail("browser"))

    def test_enqueue_due_sites_skips_disabled_and_recent_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "sites.yaml"
            db_path = Path(tmp_dir) / "collector.db"
            config_path.write_text(
                json.dumps(
                    {
                        "sites": [
                            {
                                "site_name": "alpha",
                                "enabled": True,
                                "seed_urls": ["http://alpha.onion/"],
                                "seed_fetch_mode": "tor_http",
                                "detail_fetch_mode": "tor_http",
                                "profile": "hot",
                                "max_topics_per_run": 1,
                                "max_detail_pages_per_run": 1,
                                "cooldown_seconds": 60,
                                "output_dir": str(Path(tmp_dir) / "alpha"),
                                "dedupe_window_minutes": 5,
                            },
                            {
                                "site_name": "beta",
                                "enabled": False,
                                "seed_urls": ["http://beta.onion/"],
                                "seed_fetch_mode": "tor_http",
                                "detail_fetch_mode": "tor_http",
                                "profile": "hot",
                                "max_topics_per_run": 1,
                                "max_detail_pages_per_run": 1,
                                "cooldown_seconds": 60,
                                "output_dir": str(Path(tmp_dir) / "beta"),
                                "dedupe_window_minutes": 5,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                state_store = InMemoryStateStore()
                dispatched = enqueue_due_sites(
                    seed_dispatcher=lambda config: f"job-{config.site_name}",
                    state_store=state_store,
                    config_path=config_path,
                )
                self.assertEqual(["alpha"], [item["site_name"] for item in dispatched])

                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="job-alpha",
                        site_name="alpha",
                        job_type="seed",
                        queue_name=SEED_HTTP_QUEUE,
                        target="alpha",
                        status="succeeded",
                        finished_at=utc_now_iso(),
                    )
                    connection.commit()

                second_pass = enqueue_due_sites(
                    seed_dispatcher=lambda config: f"job2-{config.site_name}",
                    state_store=InMemoryStateStore(),
                    config_path=config_path,
                )
                self.assertEqual([], second_pass)
