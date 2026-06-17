from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.api_actions import dispatch_run_site
from darkweb_collector.api_data import build_jobs_payload
from darkweb_collector.db import get_db_connection, upsert_crawl_job


class ApiJobsTests(unittest.TestCase):
    def _write_sites_config(self, path: Path) -> None:
        path.write_text(
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
                            "output_dir": str(path.parent / "alpha"),
                            "dedupe_window_minutes": 5,
                        },
                        {
                            "site_name": "beta",
                            "enabled": True,
                            "seed_urls": ["http://beta.onion/"],
                            "seed_fetch_mode": "tor_http",
                            "detail_fetch_mode": "tor_http",
                            "profile": "hot",
                            "max_topics_per_run": 1,
                            "max_detail_pages_per_run": 1,
                            "cooldown_seconds": 60,
                            "output_dir": str(path.parent / "beta"),
                            "dedupe_window_minutes": 5,
                        },
                        {
                            "site_name": "gamma",
                            "enabled": True,
                            "seed_urls": ["http://gamma.onion/"],
                            "seed_fetch_mode": "tor_http",
                            "detail_fetch_mode": "tor_http",
                            "profile": "hot",
                            "max_topics_per_run": 1,
                            "max_detail_pages_per_run": 1,
                            "cooldown_seconds": 60,
                            "output_dir": str(path.parent / "gamma"),
                            "dedupe_window_minutes": 5,
                        },
                        {
                            "site_name": "browser_alpha",
                            "enabled": True,
                            "seed_urls": ["http://browser-alpha.onion/"],
                            "seed_fetch_mode": "browser",
                            "detail_fetch_mode": "browser",
                            "profile": "hot",
                            "max_topics_per_run": 1,
                            "max_detail_pages_per_run": 1,
                            "cooldown_seconds": 60,
                            "output_dir": str(path.parent / "browser_alpha"),
                            "dedupe_window_minutes": 5,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    def test_latest_success_clears_old_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False):
                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="alpha-detail-failed",
                        site_name="alpha",
                        job_type="detail",
                        queue_name="detail_http",
                        target="alpha-detail",
                        status="failed",
                        started_at="2026-03-15T10:00:00+00:00",
                        finished_at="2026-03-15T10:10:00+00:00",
                        error_message="old error",
                    )
                    upsert_crawl_job(
                        connection,
                        job_id="alpha-seed-success",
                        site_name="alpha",
                        job_type="seed",
                        queue_name="seed_http",
                        target="alpha",
                        status="succeeded",
                        started_at="2026-03-15T10:20:00+00:00",
                        finished_at="2026-03-15T10:30:00+00:00",
                    )
                    connection.commit()
                payload = build_jobs_payload()

            alpha = next(item for item in payload["site_health"] if item["site_name"] == "alpha")
            self.assertEqual("正常", alpha["overall_status"])
            self.assertEqual("未更新", alpha["detail_status"])
            self.assertEqual(0, alpha["failed_jobs_24h"])

    def test_latest_detail_success_clears_failure_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False):
                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="beta-detail-failed",
                        site_name="beta",
                        job_type="detail",
                        queue_name="detail_http",
                        target="beta-detail",
                        status="failed",
                        started_at="2026-03-15T11:00:00+00:00",
                        finished_at="2026-03-15T11:10:00+00:00",
                        error_message="detail error",
                    )
                    upsert_crawl_job(
                        connection,
                        job_id="beta-detail-success",
                        site_name="beta",
                        job_type="detail",
                        queue_name="detail_http",
                        target="beta-detail",
                        status="succeeded",
                        started_at="2026-03-15T11:20:00+00:00",
                        finished_at="2026-03-15T11:30:00+00:00",
                    )
                    connection.commit()
                payload = build_jobs_payload()

            beta = next(item for item in payload["site_health"] if item["site_name"] == "beta")
            self.assertEqual("正常", beta["overall_status"])
            self.assertEqual("成功", beta["detail_status"])
            self.assertEqual([], [item for item in payload["recent_failures"] if item["site_name"] == "beta"])

    def test_stale_running_marks_exception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False):
                stale_started_at = (
                    datetime.now(timezone.utc) - timedelta(minutes=31)
                ).isoformat()
                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="gamma-running",
                        site_name="gamma",
                        job_type="seed",
                        queue_name="seed_http",
                        target="gamma",
                        status="running",
                        started_at=stale_started_at,
                    )
                    connection.commit()
                payload = build_jobs_payload()

            gamma = next(item for item in payload["site_health"] if item["site_name"] == "gamma")
            self.assertEqual("异常", gamma["overall_status"])
            self.assertEqual("异常挂起", gamma["seed_status"])

    def test_jobs_payload_includes_ransomware_sync_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False):
                payload = build_jobs_payload()

            self.assertIn("ransomware_sync", payload)
            self.assertEqual(0, payload["ransomware_sync"]["record_count"])

    def test_dispatch_run_site_falls_back_to_thread_when_no_worker_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            class _FakeThread:
                def __init__(self, target=None, args=(), daemon=None):
                    self.target = target
                    self.args = args
                    self.daemon = daemon
                    self.started = False

                def start(self):
                    self.started = True

            with patch.dict(os.environ, env, clear=False), patch(
                "darkweb_collector.api_actions._has_queue_worker",
                return_value=False,
            ), patch(
                "darkweb_collector.api_actions.Thread",
                _FakeThread,
            ):
                payload = dispatch_run_site("alpha", force=True)

            self.assertEqual("thread", payload["dispatch_mode"])
            self.assertEqual("", payload["job_id"])

    def test_dispatch_browser_site_falls_back_to_process_when_no_worker_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False), patch(
                "darkweb_collector.api_actions._has_queue_worker",
                return_value=False,
            ), patch(
                "darkweb_collector.api_actions.submit_browser_site",
            ) as submit_browser_site:
                payload = dispatch_run_site("browser_alpha", force=True)

            self.assertEqual("process", payload["dispatch_mode"])
            self.assertTrue(payload["job_id"])
            submit_browser_site.assert_called_once_with(site_name="browser_alpha", job_id=payload["job_id"])

    def test_jobs_payload_includes_browser_runtime_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
                "DARKWEB_BROWSER_CONCURRENCY": "4",
            }

            with patch.dict(os.environ, env, clear=False), patch(
                "darkweb_collector.api_actions._refresh_worker_queue_cache",
                return_value=(
                    {"browser_render"},
                    {"browser_render": 2},
                    {"browser_render": ["worker-browser-1", "worker-browser-2"]},
                ),
            ):
                payload = build_jobs_payload()

            self.assertEqual(4, payload["browser_runtime"]["browser_concurrency"])
            self.assertEqual(2, payload["browser_runtime"]["browser_worker_count"])
            self.assertEqual(["worker-browser-1", "worker-browser-2"], payload["browser_runtime"]["browser_worker_names"])

    def test_enqueued_seed_waiting_on_busy_queue_is_not_marked_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False):
                enqueued_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
                started_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="alpha-seed-enqueued",
                        site_name="alpha",
                        job_type="seed",
                        queue_name="browser_render",
                        target="alpha",
                        status="enqueued",
                        enqueued_at=enqueued_at,
                    )
                    upsert_crawl_job(
                        connection,
                        job_id="beta-detail-running",
                        site_name="beta",
                        job_type="detail",
                        queue_name="browser_render",
                        target="beta-detail",
                        status="running",
                        started_at=started_at,
                    )
                    connection.commit()
                payload = build_jobs_payload()

            alpha = next(item for item in payload["site_health"] if item["site_name"] == "alpha")
            self.assertEqual("enqueued", alpha["activeSeedJobStatus"])
            self.assertFalse(alpha["staleSeedDetected"])
            self.assertEqual("active_seed_job", alpha["blockingReason"])

    def test_dispatch_run_site_keeps_busy_enqueued_seed_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False):
                enqueued_at = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
                started_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
                with get_db_connection() as connection:
                    upsert_crawl_job(
                        connection,
                        job_id="alpha-seed-enqueued",
                        site_name="alpha",
                        job_type="seed",
                        queue_name="seed_http",
                        target="alpha",
                        status="enqueued",
                        enqueued_at=enqueued_at,
                    )
                    upsert_crawl_job(
                        connection,
                        job_id="beta-detail-running",
                        site_name="beta",
                        job_type="detail",
                        queue_name="seed_http",
                        target="beta-detail",
                        status="running",
                        started_at=started_at,
                    )
                    connection.commit()

                payload = dispatch_run_site("alpha", force=True)

                with get_db_connection() as connection:
                    row = connection.execute(
                        """
                        SELECT status
                        FROM crawl_jobs
                        WHERE job_id = 'alpha-seed-enqueued'
                        """
                    ).fetchone()

            self.assertEqual("skipped", payload["dispatch_mode"])
            self.assertEqual("alpha-seed-enqueued", payload["job_id"])
            self.assertIsNotNone(row)
            self.assertEqual("enqueued", row["status"])

    def test_jobs_payload_includes_failure_cooldown_and_error_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            config_path = tmp_path / "sites.yaml"
            self._write_sites_config(config_path)

            env = {
                "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
                "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
            }

            with patch.dict(os.environ, env, clear=False):
                now = datetime.now(timezone.utc)
                with get_db_connection() as connection:
                    for index in range(3):
                        finished_at = (now - timedelta(minutes=index)).isoformat()
                        upsert_crawl_job(
                            connection,
                            job_id=f"alpha-seed-failed-{index}",
                            site_name="alpha",
                            job_type="seed",
                            queue_name="seed_http",
                            target="alpha",
                            status="failed",
                            started_at=(now - timedelta(minutes=index, seconds=30)).isoformat(),
                            finished_at=finished_at,
                            error_message="greenlet cannot switch to a different thread",
                        )
                    connection.commit()
                payload = build_jobs_payload()

            alpha = next(item for item in payload["site_health"] if item["site_name"] == "alpha")
            self.assertEqual(3, alpha["consecutive_failures"])
            self.assertEqual(3, alpha["failure_threshold"])
            self.assertTrue(alpha["circuit_breaker_open"])
            self.assertEqual("failure_cooldown", alpha["blockingReason"])
            self.assertEqual("browser_runtime", alpha["error_category"])
            self.assertTrue(alpha["failure_cooldown_until"])
            alpha_failure = next(item for item in payload["recent_failures"] if item["site_name"] == "alpha")
            self.assertEqual("browser_runtime", alpha_failure["error_category"])
