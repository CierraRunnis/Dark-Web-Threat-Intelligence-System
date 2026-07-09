from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from darkweb_collector.document_exposure import (
    build_document_exposure_summary,
    list_document_exposures_payload,
    save_watchlist_payload,
    scan_watchlist_once,
)
from darkweb_collector.document_exposure_platforms import list_exposure_platforms


class DocumentExposureSourceFamilyTests(unittest.TestCase):
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

    def test_search_engines_are_not_exposed_as_document_sources(self):
        rows = list_exposure_platforms(module="document_exposure")
        search_engines = {row.key for row in rows if row.platform_type == "search_engine"}

        self.assertEqual(search_engines, set())

    def test_search_engine_source_family_cannot_be_scanned(self):
        watchlist = save_watchlist_payload(
            {
                "name": "Source Family Test",
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

        self.assertEqual(watchlist["source_families"], ["netdisk_aggregator", "document_library"])

        result = scan_watchlist_once(
            int(watchlist["id"]),
            source_families=["search_engine"],
            file_types=["pdf"],
            page_limit=2,
            detail_fetch=False,
        )

        self.assertEqual(result["source_families"], [])
        self.assertEqual(result["scanned_terms"], 0)
        self.assertEqual(result["candidates"], 0)
        self.assertEqual(result["hits"], 0)
        self.assertIn("unsupported source family", result["errors"])
        self.assertEqual(list_document_exposures_payload(source_family="search_engine", limit=20), [])
        self.assertEqual(build_document_exposure_summary(source_family="search_engine")["totalHits"], 0)


if __name__ == "__main__":
    unittest.main()
