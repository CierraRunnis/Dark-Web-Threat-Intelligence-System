from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from darkweb_collector.document_exposure import (
    DiscoverySource,
    _detect_search_block_reason,
    _parse_search_engine_candidates,
    build_document_exposure_summary,
    list_document_exposures_payload,
    save_watchlist_payload,
    scan_watchlist_once,
)
from darkweb_collector.document_exposure_platforms import list_exposure_platforms


class SearchEngineDocumentExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self._old_env = {
            "DARKWEB_COLLECTOR_DB_PATH": os.environ.get("DARKWEB_COLLECTOR_DB_PATH"),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": os.environ.get("DARKWEB_COLLECTOR_OUTPUT_ROOT"),
        }
        root = Path(self.temp_dir.name)
        os.environ["DARKWEB_COLLECTOR_DB_PATH"] = str(root / "collector.db")
        os.environ["DARKWEB_COLLECTOR_OUTPUT_ROOT"] = str(root / "output")

    def tearDown(self) -> None:
        for name, value in self._old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp_dir.cleanup()

    def test_search_engines_are_exposed_as_document_sources(self):
        rows = list_exposure_platforms(module="document_exposure")
        search_engines = {row.key for row in rows if row.platform_type == "search_engine"}

        self.assertGreaterEqual({"baidu_search", "bing_search", "so360_search"}, search_engines)

    def test_bing_result_page_is_not_misclassified_as_captcha(self):
        source = DiscoverySource("bing_search", "Bing", "https://www.bing.com/search?q={query}", "search_engine")
        html = """
        <html><body>
          <ol id="b_results">
            <li class="b_algo">
              <a href="https://www.bing.com/ck/a?!&&u=a1aHR0cHM6Ly93d3cuY2F0bC5jb20v">
                catl.com https://www.catl.com › index.html
              </a>
              <a href="https://www.bing.com/ck/a?!&&u=a1aHR0cHM6Ly93d3cuY2F0bC5jb20v">
                宁德时代 · CATL
              </a>
            </li>
          </ol>
          <script>var captchaTelemetry = true;</script>
        </body></html>
        """

        self.assertEqual(_detect_search_block_reason(source, html, "https://www.bing.com/search?q=catl"), "")
        candidates = _parse_search_engine_candidates(source, html, "https://www.bing.com/search?q=catl")
        self.assertEqual(candidates[0]["url"], "https://www.catl.com/")
        self.assertEqual(candidates[0]["title"], "宁德时代 · CATL")
        self.assertEqual(candidates[0]["source_detail"], "www.catl.com")

    def test_search_engine_scan_persists_generic_web_result(self):
        watchlist = save_watchlist_payload(
            {
                "name": "Search Engine Test",
                "organization_name": "Acme Power",
                "enabled": True,
                "source_families": ["search_engine"],
                "file_types": ["pdf"],
                "page_limit": 2,
                "detail_fetch": False,
                "terms": [
                    {
                        "term": "Acme Power",
                        "term_type": "company_name",
                        "weight": 15,
                        "enabled": True,
                    }
                ],
            }
        )
        html = """
        <html><body>
          <a href="https://example.com/reports/acme-power-internal-audit.pdf">
            Acme Power internal audit.pdf
          </a>
          <a href="/search?q=Acme+Power">navigation</a>
        </body></html>
        """

        with patch("darkweb_collector.document_exposure._fetch_html", return_value=html):
            result = scan_watchlist_once(
                int(watchlist["id"]),
                source_families=["search_engine"],
                file_types=["pdf"],
                page_limit=2,
                detail_fetch=False,
            )

        self.assertGreaterEqual(result["candidates"], 1)
        self.assertEqual(result["hits"], 1)
        rows = list_document_exposures_payload(source_family="search_engine", limit=20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sourceFamily"], "search_engine")
        self.assertEqual(rows[0]["platform"], "baidu_search")
        self.assertEqual(rows[0]["platformType"], "search_engine")
        self.assertEqual(rows[0]["primaryFileType"], "pdf")
        self.assertIn("example.com", rows[0]["canonicalUrl"])

        summary = build_document_exposure_summary(source_family="search_engine")
        self.assertEqual(summary["totalHits"], 1)
        self.assertEqual(summary["lastHitCount"], 1)


if __name__ == "__main__":
    unittest.main()
