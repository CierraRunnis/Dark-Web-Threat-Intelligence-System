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

from darkweb_collector.adapters.darkforums import DarkforumsAdapter
from darkweb_collector.models import DetailResult, RunContext, SeedResult, SiteConfig


class DarkforumsAdapterTests(unittest.TestCase):
    def test_invalid_detail_html_detects_nul_corruption(self) -> None:
        adapter = DarkforumsAdapter()
        self.assertFalse(adapter._is_valid_detail_html("abc\x00" * 100))
        self.assertTrue(adapter._is_valid_detail_html('<div id="posts"><div class="post_content">ok</div></div>'))

    def test_plan_details_rotates_across_sections(self) -> None:
        adapter = DarkforumsAdapter()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(Path(tmp_dir) / "collector.db")}, clear=False):
                config = SiteConfig(
                    site_name="darkforums",
                    enabled=True,
                    seed_urls=(
                        "https://darkforums.su/Forum-Databases",
                        "https://darkforums.su/Forum-Other-Leaks",
                        "https://darkforums.su/Forum-Sellers-Place",
                    ),
                    seed_fetch_mode="tor_http",
                    detail_fetch_mode="tor_http",
                    profile="warm",
                    max_topics_per_run=10,
                    max_detail_pages_per_run=4,
                    cooldown_seconds=60,
                    output_dir=Path(tmp_dir) / "output",
                    dedupe_window_minutes=10,
                )
                seed_result = SeedResult(
                    site_name="darkforums",
                    collected_at_utc="2026-03-11T00:00:00+00:00",
                    payload={
                        "sections": [
                            {
                                "section": "databases",
                                "topics": [
                                    {"full_url": "https://darkforums.su/db-1", "title": "db1", "content_hash": "a"},
                                    {"full_url": "https://darkforums.su/db-2", "title": "db2", "content_hash": "b"},
                                ],
                            },
                            {
                                "section": "other_leaks",
                                "topics": [
                                    {"full_url": "https://darkforums.su/ol-1", "title": "ol1", "content_hash": "c"},
                                    {"full_url": "https://darkforums.su/ol-2", "title": "ol2", "content_hash": "d"},
                                ],
                            },
                            {
                                "section": "sellers_place",
                                "topics": [
                                    {"full_url": "https://darkforums.su/sp-1", "title": "sp1", "content_hash": "e"},
                                    {"full_url": "https://darkforums.su/sp-2", "title": "sp2", "content_hash": "f"},
                                ],
                            },
                        ]
                    },
                    raw_html_by_url={},
                )

                tasks = adapter.plan_details(seed_result, config)

        sections = [task.metadata["section"] for task in tasks]
        self.assertEqual(
            ["databases", "other_leaks", "sellers_place", "databases"],
            sections,
        )

    def test_persist_refreshes_normalized_events_after_detail_results(self) -> None:
        adapter = DarkforumsAdapter()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"DARKWEB_COLLECTOR_DB_PATH": str(Path(tmp_dir) / "collector.db")}, clear=False):
                config = SiteConfig(
                    site_name="darkforums",
                    enabled=True,
                    seed_urls=("https://darkforums.su/Forum-Databases",),
                    seed_fetch_mode="tor_http",
                    detail_fetch_mode="tor_http",
                    profile="warm",
                    max_topics_per_run=10,
                    max_detail_pages_per_run=4,
                    cooldown_seconds=60,
                    output_dir=Path(tmp_dir) / "output",
                    dedupe_window_minutes=10,
                )
                run_ctx = RunContext(
                    job_id="job-1",
                    job_type="detail",
                    queue_name="detail_http",
                    target="https://darkforums.su/thread-1",
                    started_at_utc="2026-03-11T00:00:00+00:00",
                )
                detail_result = DetailResult(
                    site_name="darkforums",
                    target_url="https://darkforums.su/thread-1",
                    payload={
                        "content": "Forum detail body",
                        "author": "poster",
                        "timestamp": "2026-03-11",
                        "attachments": [],
                        "victims": [{"name": "Acme", "industry": "finance", "region": "asia"}],
                        "attackers": ["darkforums"],
                        "content_hash": "detail-hash",
                        "collected_at_utc": "2026-03-11T00:00:00+00:00",
                    },
                    raw_html="<html></html>",
                    screenshot_png=b"\x89PNG\r\n\x1a\n",
                    metadata={"section": "databases", "artifact_stem": "abc123"},
                )

                with patch("darkweb_collector.normalized_intelligence.ensure_normalized_intelligence") as mocked_refresh:
                    adapter.persist(config=config, run_ctx=run_ctx, detail_results=[detail_result])

                mocked_refresh.assert_called_once()
