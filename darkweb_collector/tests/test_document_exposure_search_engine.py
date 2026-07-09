from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from darkweb_collector.document_exposure import (
    DiscoverySource,
    _detect_search_block_reason,
    _matched_terms,
    _parse_search_engine_candidates,
    _search_candidates_for_source,
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

    def test_search_engine_parser_prefers_descriptive_duplicate_title(self):
        source = DiscoverySource("bing_search", "Bing", "https://www.bing.com/search?q={query}", "search_engine")
        html = """
        <html><body>
          <a href="https://example.com/breach/23andme">example.comhttps://example.com</a>
          <a href="https://example.com/breach/23andme">23andMe Data Breach: affected records</a>
        </body></html>
        """

        candidates = _parse_search_engine_candidates(source, html, "https://www.bing.com/search?q=23andMe")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "23andMe Data Breach: affected records")

    def test_search_engine_scan_uses_browser_fallback_after_http_challenge(self):
        source = DiscoverySource("bing_search", "Bing", "https://www.bing.com/search?q={query}", "search_engine")
        blocked_html = "<html><title>Security verification</title><body>captcha</body></html>"
        browser_html = """
        <html><body>
          <ol id="b_results">
            <li class="b_algo">
              <a href="https://www.bing.com/ck/a?!&&u=a1aHR0cHM6Ly93d3cuY2F0bC5jb20vZW4v">
                CATL
              </a>
            </li>
          </ol>
        </body></html>
        """

        with patch("darkweb_collector.document_exposure._fetch_html", return_value=blocked_html), patch(
            "darkweb_collector.document_exposure.fetch_page_artifacts_with_session",
            return_value={
                "url": "https://www.bing.com/search?q=CATL&rdr=1",
                "title": "CATL - Search",
                "html": browser_html,
                "screenshot_png": b"",
            },
        ):
            candidates = _search_candidates_for_source(source, "https://www.bing.com/search?q=CATL", "CATL")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["url"], "https://www.catl.com/en/")

    def test_so360_result_page_login_links_are_filtered(self):
        source = DiscoverySource("so360_search", "360 Search", "https://www.so.com/s?q={query}", "search_engine")
        html = """
        <html><head><title>CATL_360搜索</title></head><body id="main">
          <a href="http://i.360.cn/login?src=pcw_newso">登录</a>
          <a href="http://i.360.cn/reg?src=pcw_newso">注册</a>
          <a href="http://www.baidu.com/s?wd=CATL">百度搜索</a>
          <a href="https://example.com/reports/CATL-risk-report.pdf">CATL risk report.pdf</a>
        </body></html>
        """

        self.assertEqual(_detect_search_block_reason(source, html, "https://www.so.com/s?q=CATL"), "")
        candidates = _parse_search_engine_candidates(source, html, "https://www.so.com/s?q=CATL")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["url"], "https://example.com/reports/CATL-risk-report.pdf")

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

    def test_search_engine_scan_persists_contextual_sensitive_result(self):
        watchlist = save_watchlist_payload(
            {
                "name": "Sensitive Search Engine Test",
                "organization_name": "Tesla",
                "enabled": True,
                "source_families": ["search_engine"],
                "file_types": ["pdf"],
                "page_limit": 1,
                "detail_fetch": False,
                "terms": [
                    {
                        "term": "Tesla data breach",
                        "term_type": "leak_keyword",
                        "weight": 18,
                        "enabled": True,
                    }
                ],
            }
        )
        html = """
        <html><body>
          <a href="https://example.com/leaks/tesla-employee-files.pdf">
            Tesla confirms breach involving leaked employee files.pdf
          </a>
        </body></html>
        """

        with patch("darkweb_collector.document_exposure._fetch_html", return_value=html):
            result = scan_watchlist_once(
                int(watchlist["id"]),
                source_families=["search_engine"],
                file_types=["pdf"],
                page_limit=1,
                detail_fetch=False,
            )

        self.assertEqual(result["hits"], 1)
        rows = list_document_exposures_payload(source_family="search_engine", limit=20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["matchedTerms"][0]["term"], "Tesla data breach")
        self.assertEqual(rows[0]["matchedTerms"][0]["match_type"], "contextual_sensitive")
        self.assertIn("breach", rows[0]["matchedTerms"][0]["matched_signals"])

    def test_sensitive_keyword_only_requires_watchlist_entity(self):
        matches = _matched_terms(
            "Unrelated internal employee files.pdf",
            "",
            [],
            [{"term": "internal", "term_type": "sensitive_keyword", "weight": 6}],
            organization_name="CATL",
        )

        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
