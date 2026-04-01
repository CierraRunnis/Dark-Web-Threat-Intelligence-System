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
