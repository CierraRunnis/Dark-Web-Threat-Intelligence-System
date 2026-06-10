from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.api_data import build_event_detail, build_event_records
from darkweb_collector.db import (
    add_document_hit_review,
    get_db_connection,
    insert_document_hit_snapshot,
    update_document_hit_last_snapshot,
    upsert_document_hit,
)
from darkweb_collector.document_exposure import (
    build_document_exposure_event_detail,
    build_document_exposure_event_records,
    list_exposure_scan_runs_payload,
    build_document_exposure_summary,
    ensure_default_watchlist,
    list_document_exposures_payload,
    save_watchlist_payload,
    scan_watchlist_once,
)
from darkweb_collector.document_exposure_platforms import get_exposure_platform


class DocumentExposureTests(unittest.TestCase):
    def _env(self, db_path: Path, output_root: Path, config_path: Path) -> dict[str, str]:
        return {
            "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_root),
            "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
        }

    def _write_empty_sites(self, path: Path) -> None:
        path.write_text(json.dumps({"sites": []}, ensure_ascii=False), encoding="utf-8")

    def test_default_watchlist_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                payload = ensure_default_watchlist()
                self.assertTrue(payload["id"])
                self.assertTrue(payload["terms"])

    def test_legacy_watchlist_schema_is_auto_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE exposure_watchlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    organization_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
            connection.close()

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                payload = save_watchlist_payload(
                    {
                        "name": "Legacy Watch",
                        "organization_name": "Legacy Corp",
                        "enabled": True,
                        "notes": "legacy schema",
                        "source_families": ["document_library"],
                        "file_types": ["pdf"],
                        "terms": [
                            {"term": "Legacy", "term_type": "company_name", "weight": 10, "enabled": True},
                        ],
                    }
                )
                self.assertEqual("Legacy Watch", payload["name"])
                self.assertEqual(["document_library"], payload["source_families"])
                self.assertEqual(["pdf"], payload["file_types"])

    def test_document_hit_is_exposed_through_event_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            html_path = output_root / "document_exposure" / "default" / "test" / "acme.html"
            screenshot_path = output_root / "document_exposure" / "default" / "test" / "acme.png"
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text("<html><title>Acme 内部方案</title><body>Acme 内部方案 PDF</body></html>", encoding="utf-8")
            screenshot_path.write_bytes(b"fake-png")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Acme Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                            {"term": "内部", "term_type": "sensitive_keyword", "weight": 10, "enabled": True},
                        ],
                    }
                )
                with get_db_connection() as connection:
                    hit_id = upsert_document_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "baidu_wenku",
                            "platform_type": "document_library",
                            "discovery_source": "baidu_search",
                            "canonical_url": "https://wenku.baidu.com/view/acme-doc.html",
                            "normalized_title": "acme-internal-doc",
                            "title": "Acme 内部方案",
                            "access_state": "public",
                            "confidence_score": 82,
                            "risk_score": 88,
                            "severity": "high",
                            "matched_terms_json": json.dumps(
                                [
                                    {"term": "Acme", "term_type": "company_name", "weight": 15},
                                    {"term": "内部", "term_type": "sensitive_keyword", "weight": 10},
                                ],
                                ensure_ascii=False,
                            ),
                            "file_count": 2,
                            "share_owner": "",
                            "disclosure_time": "2026-06-04T00:00:00+00:00",
                            "first_seen_at": "2026-06-04T00:00:00+00:00",
                            "last_seen_at": "2026-06-04T01:00:00+00:00",
                            "raw_json": json.dumps({"preview_text": "Acme 内部方案 PDF"}, ensure_ascii=False),
                        },
                    )
                    snapshot_id = insert_document_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": "2026-06-04T01:00:00+00:00",
                            "source_query": "Acme",
                            "source_url": "https://www.baidu.com/s?wd=site:wenku.baidu.com+Acme",
                            "page_url": "https://wenku.baidu.com/view/acme-doc.html",
                            "page_title": "Acme 内部方案",
                            "html_path": str(html_path),
                            "screenshot_path": str(screenshot_path),
                            "ocr_text": "Acme 内部方案 PDF",
                            "preview_text": "Acme 内部方案 PDF",
                            "file_list_json": json.dumps([{"name": "Acme内部方案.pdf"}], ensure_ascii=False),
                            "access_state": "public",
                            "matched_terms_json": json.dumps([{"term": "Acme"}], ensure_ascii=False),
                            "raw_json": json.dumps({}, ensure_ascii=False),
                        },
                    )
                    update_document_hit_last_snapshot(connection, hit_id, snapshot_id)
                    add_document_hit_review(
                        connection,
                        {
                            "hit_id": hit_id,
                            "status": "confirmed",
                            "reviewer": "tester",
                            "note": "confirmed in unit test",
                            "created_at": "2026-06-04T01:02:00+00:00",
                        },
                    )
                    connection.commit()

                exposures = list_document_exposures_payload()
                self.assertEqual(1, len(exposures))
                self.assertEqual("baidu_wenku", exposures[0]["platform"])

                summary = build_document_exposure_summary()
                self.assertEqual(1, summary["totalHits"])
                self.assertEqual(1, summary["highRiskCount"])
                self.assertEqual(0, summary["pendingReviewCount"])
                self.assertEqual(0, summary["configuredSessionCount"])

                event_rows = build_document_exposure_event_records()
                self.assertEqual("document:1", event_rows[0]["id"])

                event_detail = build_document_exposure_event_detail("document:1")
                self.assertIsNotNone(event_detail)
                self.assertEqual("document_exposure", event_detail["normalized_event_type"])
                self.assertTrue(event_detail["screenshot_resources"])

                events = build_event_records()
                self.assertEqual("document:1", events[0]["id"])

                detail = build_event_detail("document:1")
                self.assertIsNotNone(detail)
                self.assertEqual("document_exposure", detail["normalized_event_type"])

    def test_scan_watchlist_once_with_mocked_fetchers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            fake_search_html = """
            <html><body>
              <a href="https://wenku.baidu.com/view/acme-scheme.html">Acme 内部方案</a>
            </body></html>
            """

            detail_platform = get_exposure_platform("baidu_wenku")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Scan Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch("darkweb_collector.document_exposure._fetch_html", return_value=fake_search_html), patch(
                    "darkweb_collector.document_exposure._detail_payload_from_page",
                    return_value={
                        "platform": detail_platform,
                        "page_url": "https://wenku.baidu.com/view/acme-scheme.html",
                        "page_title": "Acme 内部方案",
                        "html": "<html><title>Acme 内部方案</title><body>Acme 内部方案 PDF</body></html>",
                        "screenshot_png": b"png",
                        "preview_text": "Acme 内部方案 PDF",
                        "ocr_text": "Acme 内部方案 PDF",
                        "file_names": ["Acme内部方案.pdf"],
                        "access_state": "public",
                        "source_query": "Acme",
                        "source_url": "https://www.baidu.com/s?wd=site:wenku.baidu.com+Acme",
                    },
                ):
                    result = scan_watchlist_once(int(watchlist["id"]), max_candidates_per_term=1)

                self.assertEqual(1, result["hits"])
                exposures = list_document_exposures_payload()
                self.assertEqual(1, len(exposures))
                scan_runs = list_exposure_scan_runs_payload()
                self.assertEqual(1, len(scan_runs))
                self.assertEqual(1, scan_runs[0]["hitCount"])
                self.assertEqual("succeeded", scan_runs[0]["status"])


if __name__ == "__main__":
    unittest.main()
