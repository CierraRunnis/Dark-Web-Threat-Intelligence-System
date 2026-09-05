from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from datetime import datetime, timedelta, timezone
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
from darkweb_collector.queueing import (
    BROWSER_RENDER_QUEUE,
    DETAIL_HTTP_QUEUE,
    SEED_HTTP_QUEUE,
    WORKER_SOFT_TIME_LIMIT_SECONDS,
    WORKER_TIME_LIMIT_SECONDS,
    build_worker_command,
    queue_for_detail,
    queue_for_seed,
)
from darkweb_collector.state_store import InMemoryStateStore
from darkweb_collector.utils import utc_now_iso


class QueueingTests(unittest.TestCase):
    def _write_single_site_config(self, tmp_dir: str) -> tuple[Path, Path]:
        tmp_path = Path(tmp_dir)
        config_path = tmp_path / "sites.yaml"
        db_path = tmp_path / "collector.db"
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
                            "output_dir": str(tmp_path / "alpha"),
                            "dedupe_window_minutes": 5,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return config_path, db_path

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

    def test_worker_command_names_each_queue_and_sets_time_limits(self) -> None:
        for queue_name in (SEED_HTTP_QUEUE, DETAIL_HTTP_QUEUE, BROWSER_RENDER_QUEUE):
            command = build_worker_command(queue_name)
            self.assertEqual(f"{queue_name}@%h", command[command.index("-n") + 1])
            self.assertEqual(
                str(WORKER_SOFT_TIME_LIMIT_SECONDS),
                command[command.index("--soft-time-limit") + 1],
            )
            self.assertEqual(
                str(WORKER_TIME_LIMIT_SECONDS),
                command[command.index("--time-limit") + 1],
            )

        browser_command = build_worker_command(BROWSER_RENDER_QUEUE)
        self.assertEqual("10", browser_command[browser_command.index("--max-tasks-per-child") + 1])

    def test_enqueue_due_sites_clears_stale_running_seed_and_dispatches_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path, db_path = self._write_single_site_config(tmp_dir)
            stale_started_at = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()

            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="alpha-stale-running",
                        site_name="alpha",
                        job_type="seed",
                        queue_name=SEED_HTTP_QUEUE,
                        target="alpha",
                        status="running",
                        started_at=stale_started_at,
                    )
                    connection.commit()

                dispatched = enqueue_due_sites(
                    seed_dispatcher=lambda config: f"new-{config.site_name}-job",
                    state_store=InMemoryStateStore(),
                    config_path=config_path,
                )

                with get_db_connection() as connection:
                    stale_row = connection.execute(
                        "SELECT status, finished_at, error_message FROM crawl_jobs WHERE job_id = 'alpha-stale-running'"
                    ).fetchone()
                    new_row = connection.execute(
                        "SELECT status, queue_name FROM crawl_jobs WHERE job_id = 'new-alpha-job'"
                    ).fetchone()

            self.assertEqual(
                [{"site_name": "alpha", "job_id": "new-alpha-job", "queue_name": SEED_HTTP_QUEUE}],
                dispatched,
            )
            self.assertIsNotNone(stale_row)
            self.assertEqual("stale", stale_row["status"])
            self.assertTrue(stale_row["finished_at"])
            self.assertEqual("stale seed task auto-cleared", stale_row["error_message"])
            self.assertIsNotNone(new_row)
            self.assertEqual("enqueued", new_row["status"])
            self.assertEqual(SEED_HTTP_QUEUE, new_row["queue_name"])

    def test_enqueue_due_sites_keeps_busy_enqueued_seed_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path, db_path = self._write_single_site_config(tmp_dir)
            enqueued_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
            recent_started_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

            def fail_dispatcher(config):
                raise AssertionError("stale busy queue seed should not dispatch")

            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(db_path)}, clear=False):
                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="alpha-enqueued",
                        site_name="alpha",
                        job_type="seed",
                        queue_name=SEED_HTTP_QUEUE,
                        target="alpha",
                        status="enqueued",
                        enqueued_at=enqueued_at,
                    )
                    upsert_crawl_job(
                        connection,
                        job_id="beta-running",
                        site_name="beta",
                        job_type="detail",
                        queue_name=SEED_HTTP_QUEUE,
                        target="beta-detail",
                        status="running",
                        started_at=recent_started_at,
                    )
                    connection.commit()

                dispatched = enqueue_due_sites(
                    seed_dispatcher=fail_dispatcher,
                    state_store=InMemoryStateStore(),
                    config_path=config_path,
                )

                with get_db_connection() as connection:
                    row = connection.execute(
                        "SELECT status, finished_at FROM crawl_jobs WHERE job_id = 'alpha-enqueued'"
                    ).fetchone()

            self.assertEqual([], dispatched)
            self.assertIsNotNone(row)
            self.assertEqual("enqueued", row["status"])
            self.assertIsNone(row["finished_at"])
