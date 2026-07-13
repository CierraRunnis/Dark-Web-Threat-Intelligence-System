from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from darkweb_collector.adapters.forum_connector import ForumConnectorAdapter
from darkweb_collector.adapters.registry import get_adapter
from darkweb_collector.db import get_db_connection, list_normalized_intelligence_events
from darkweb_collector.models import RunContext, SiteConfig
from darkweb_collector.normalized_intelligence import ensure_normalized_intelligence


class _Response:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class ForumConnectorAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.previous_db = os.environ.get("DARKWEB_COLLECTOR_DB_PATH")
        self.previous_url = os.environ.get("TEST_CONNECTOR_URL")
        self.previous_token = os.environ.get("TEST_CONNECTOR_TOKEN")
        os.environ["DARKWEB_COLLECTOR_DB_PATH"] = str(self.root / "collector.db")
        os.environ["TEST_CONNECTOR_URL"] = "https://connector.example/xss"
        os.environ["TEST_CONNECTOR_TOKEN"] = "secret"

    def tearDown(self) -> None:
        for name, value in (
            ("DARKWEB_COLLECTOR_DB_PATH", self.previous_db),
            ("TEST_CONNECTOR_URL", self.previous_url),
            ("TEST_CONNECTOR_TOKEN", self.previous_token),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp_dir.cleanup()

    def _config(self) -> SiteConfig:
        return SiteConfig(
            site_name="xss",
            enabled=True,
            seed_urls=("env:TEST_CONNECTOR_URL",),
            seed_fetch_mode="tor_http",
            detail_fetch_mode="tor_http",
            profile="warm",
            max_topics_per_run=20,
            max_detail_pages_per_run=0,
            cooldown_seconds=900,
            output_dir=self.root / "output" / "xss",
            dedupe_window_minutes=180,
            extras={
                "connector_url_env": "TEST_CONNECTOR_URL",
                "connector_token_env": "TEST_CONNECTOR_TOKEN",
            },
        )

    def test_registered_sources_use_the_connector_adapter(self) -> None:
        for site_name in ("changan_night_city", "xss", "breachforums"):
            self.assertIsInstance(get_adapter(site_name), ForumConnectorAdapter)

    def test_finding_flows_into_existing_data_leak_events(self) -> None:
        response = _Response(
            {
                "findings": [
                    {
                        "event_id": "xss-1001",
                        "title": "Example Manufacturing database offered for sale",
                        "threat_type": "database sale",
                        "target_name": "Example Manufacturing",
                        "target_industry": "制造业",
                        "region": "亚洲",
                        "discovered_at": "2026-07-13T08:30:00+00:00",
                        "content_excerpt": "A database sample is advertised in the thread.",
                        "attacker": "seller-account",
                    }
                ]
            }
        )
        adapter = ForumConnectorAdapter("xss")
        run_context = RunContext(
            job_id="test-xss",
            job_type="seed",
            queue_name="seed_tor_http",
            target="xss",
            started_at_utc="2026-07-13T08:31:00+00:00",
        )

        with patch("darkweb_collector.adapters.forum_connector.urlopen", return_value=response) as mocked_urlopen:
            seed_result = adapter.collect_seed(self._config(), run_context)
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        adapter.persist(self._config(), run_context, seed_result=seed_result)

        with get_db_connection() as connection:
            detail = connection.execute(
                "SELECT site_name, section, topic_url, victims FROM forum_details"
            ).fetchone()
            victim = connection.execute(
                "SELECT victim_name, industry, region FROM forum_victims"
            ).fetchone()
            ensure_normalized_intelligence(connection, force=True)
            events = list_normalized_intelligence_events(connection)

        self.assertEqual(dict(detail)["site_name"], "xss")
        self.assertEqual(dict(detail)["section"], "databases")
        self.assertTrue(dict(detail)["topic_url"].startswith("connector://xss/"))
        self.assertEqual(dict(victim), {
            "victim_name": "Example Manufacturing",
            "industry": "制造业",
            "region": "亚洲",
        })
        event = next(item for item in events if item["source_site_name"] == "xss")
        self.assertEqual(event["event_type"], "data_leak")
        self.assertEqual(event["victim"], "Example Manufacturing")


if __name__ == "__main__":
    unittest.main()
