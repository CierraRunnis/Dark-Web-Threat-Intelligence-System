from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.api_data import build_event_detail, build_event_records
from darkweb_collector import api_actions
from darkweb_collector.db import (
    add_document_hit_review,
    get_db_connection,
    insert_document_hit_snapshot,
    update_document_hit_last_snapshot,
    upsert_document_hit,
)
from darkweb_collector.document_exposure import (
    DISCOVERY_SOURCES,
    _build_search_urls,
    _fetch_html,
    _fetch_netdisk_api_candidates,
    _extract_netdisk_preview_file_names,
    _matched_terms,
    _netdisk_resource_fingerprint,
    _probe_netdisk_link_access_state,
    _parse_candidates_from_html,
    _parse_netdisk_api_candidates,
    build_document_exposure_detail,
    build_document_exposure_event_detail,
    build_document_exposure_event_records,
    list_exposure_scan_runs_payload,
    build_document_exposure_summary,
    ensure_default_watchlist,
    list_document_exposures_payload,
    list_netdisk_source_health_payload,
    list_netdisk_source_states_payload,
    netdisk_source_policy,
    save_watchlist_payload,
    scan_watchlist_once,
    _select_netdisk_primary_file,
)
from darkweb_collector.document_exposure_browser import NetdiskShareUnavailable
from darkweb_collector.document_exposure_platforms import get_exposure_platform, platform_from_url


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

    def test_phase_one_netdisk_sources_are_registered(self) -> None:
        keys = {source.key for source in DISCOVERY_SOURCES}
        self.assertTrue(
            {
                "pansou",
                "panhub",
                "lingfengyun",
                "pikasoo",
                "lzpanx",
                "esoua",
                "xiaobudian",
                "dalipan",
                "pandashi",
                "panyq",
            }.issubset(keys)
        )
        self.assertEqual("onedrive_share", platform_from_url("https://1drv.ms/f/s!abc").key)
        self.assertEqual("xunlei_share", platform_from_url("https://pan.xunlei.com/s/example").key)

    def test_netdisk_scan_uses_no_login_sources_by_default(self) -> None:
        with patch.dict(
            os.environ,
            {"DARKWEB_NETDISK_INCLUDE_UNSTABLE_SOURCES": "", "PANHUB_API_BASE": "", "PANHUB_BASE_URL": ""},
            clear=False,
        ):
            keys = [source.key for source, _ in _build_search_urls("python", ["netdisk_aggregator"])]
            pansou_enabled = netdisk_source_policy("pansou")["scan_enabled"]
            panyq_enabled = netdisk_source_policy("panyq")["scan_enabled"]

        self.assertEqual(["pikasoo", "lzpanx", "esoua", "pandashi", "pansou"], keys)
        self.assertTrue(pansou_enabled)
        self.assertFalse(panyq_enabled)

    def test_document_library_sources_are_registered(self) -> None:
        keys = {source.key for source in DISCOVERY_SOURCES}
        self.assertTrue(
            {
                "renrendoc",
                "jinchutou",
                "mbalib_doc",
                "wenku_360",
                "tencent_wenku",
                "quark_doc",
                "taodocs",
                "doczj",
                "souhong_wenku",
            }.issubset(keys)
        )
        self.assertEqual("renrendoc", platform_from_url("https://www.renrendoc.com/paper/123.html").key)
        self.assertEqual("jinchutou", platform_from_url("https://www.jinchutou.com/shtml/example.html").key)
        self.assertEqual("mbalib_doc", platform_from_url("https://doc.mbalib.com/view/example").key)

    def test_document_library_scan_uses_public_sources_by_default(self) -> None:
        with patch.dict(os.environ, {"DARKWEB_DOCUMENT_LIBRARY_INCLUDE_RESTRICTED_SOURCES": ""}, clear=False):
            keys = [source.key for source, _ in _build_search_urls("Acme", ["document_library"])]

        self.assertEqual(
            [
                "renrendoc",
                "jinchutou",
                "mbalib_doc",
                "wenku_360",
                "tencent_wenku",
                "quark_doc",
                "taodocs",
                "doczj",
                "souhong_wenku",
            ],
            keys,
        )
        self.assertNotIn("baidu_wenku", keys)
        self.assertNotIn("book118", keys)

    def test_document_library_defaults_to_larger_candidate_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Library Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "source_families": ["document_library"],
                        "terms": [{"term": "Acme", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                self.assertEqual(10, watchlist["page_limit"])

                with patch("darkweb_collector.document_exposure._build_search_urls", return_value=[]):
                    result = scan_watchlist_once(int(watchlist["id"]), source_families=["document_library"])

                self.assertEqual(10, result["page_limit"])

    def test_document_library_scan_does_not_inherit_netdisk_page_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Netdisk Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "page_limit": 4,
                        "terms": [{"term": "Acme", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with patch("darkweb_collector.document_exposure._build_search_urls", return_value=[]):
                    result = scan_watchlist_once(int(watchlist["id"]), source_families=["document_library"])

                self.assertEqual(10, result["page_limit"])

    def test_document_library_scan_records_public_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "renrendoc")
            platform = get_exposure_platform("renrendoc")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Library Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["document_library"],
                        "file_types": ["pdf"],
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.renrendoc.com/search.html?keyword=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    return_value=[
                        {
                            "url": "https://www.renrendoc.com/paper/acme-plan.html",
                            "title": "Acme 内部方案.pdf",
                            "source": "renrendoc",
                            "preview_text": "Acme 内部方案.pdf",
                        }
                    ],
                ), patch(
                    "darkweb_collector.document_exposure._detail_payload_from_page",
                    return_value={
                        "platform": platform,
                        "page_url": "https://www.renrendoc.com/paper/acme-plan.html",
                        "page_title": "Acme 内部方案.pdf",
                        "html": "<html>Acme 内部方案.pdf</html>",
                        "screenshot_png": b"png",
                        "preview_text": "Acme 内部方案.pdf 包含内部材料",
                        "ocr_text": "Acme 内部方案.pdf 包含内部材料",
                        "file_names": ["Acme 内部方案.pdf"],
                        "file_sizes": ["128 KB"],
                        "share_code": "",
                        "share_type": "public_share",
                        "access_state": "public",
                        "source_query": "Acme",
                        "source_url": "https://www.renrendoc.com/search.html?keyword=Acme",
                    },
                ):
                    result = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["document_library"],
                        file_types=["pdf"],
                    )

                self.assertEqual(1, result["hits"])
                exposures = list_document_exposures_payload(source_family="document_library")
                self.assertEqual(1, len(exposures))
                self.assertEqual("renrendoc", exposures[0]["platform"])
                self.assertEqual("document_library", exposures[0]["sourceFamily"])
                detail = build_document_exposure_detail(int(exposures[0]["id"]))
                self.assertTrue(detail["latestSnapshot"]["htmlPath"])
                self.assertTrue(detail["latestSnapshot"]["screenshotPath"])
                self.assertTrue(Path(detail["latestSnapshot"]["htmlPath"]).exists())
                self.assertTrue(Path(detail["latestSnapshot"]["screenshotPath"]).exists())
                self.assertTrue(detail["previewAssets"])
                health = [row for row in list_netdisk_source_health_payload(source_family="document_library") if row["sourceKey"] == "renrendoc"]
                self.assertEqual(1, len(health))
                self.assertEqual("healthy", health[0]["status"])
                self.assertEqual(1, health[0]["successCount"])

    def test_document_library_list_filter_applies_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Acme Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "terms": [{"term": "Acme", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with get_db_connection() as connection:
                    for index in range(3):
                        upsert_document_hit(
                            connection,
                            {
                                "watchlist_id": int(watchlist["id"]),
                                "platform": "aliyundrive_share",
                                "platform_type": "netdisk_share",
                                "discovery_source": "pansou",
                                "canonical_url": f"https://www.aliyundrive.com/s/acme-{index}",
                                "normalized_title": f"acme-netdisk-{index}",
                                "title": f"Acme netdisk {index}",
                                "access_state": "public",
                                "confidence_score": 90,
                                "risk_score": 90,
                                "severity": "high",
                                "matched_terms_json": json.dumps([{"term": "Acme"}], ensure_ascii=False),
                                "file_count": 1,
                                "share_owner": "",
                                "disclosure_time": "",
                                "first_seen_at": "2026-06-04T00:00:00+00:00",
                                "last_seen_at": "2026-06-04T02:00:00+00:00",
                                "raw_json": json.dumps({"file_names": ["Acme.pdf"]}, ensure_ascii=False),
                            },
                        )
                    upsert_document_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "tencent_wenku",
                            "platform_type": "document_library",
                            "discovery_source": "tencent_wenku",
                            "canonical_url": "https://wenku.docs.qq.com/detail?docId=acme",
                            "normalized_title": "acme-document-library",
                            "title": "Acme document library report",
                            "access_state": "unknown",
                            "confidence_score": 70,
                            "risk_score": 30,
                            "severity": "low",
                            "matched_terms_json": json.dumps([{"term": "Acme"}], ensure_ascii=False),
                            "file_count": 1,
                            "share_owner": "",
                            "disclosure_time": "",
                            "first_seen_at": "2026-06-04T00:00:00+00:00",
                            "last_seen_at": "2026-06-04T01:00:00+00:00",
                            "raw_json": json.dumps({"preview_text": "Acme report"}, ensure_ascii=False),
                        },
                    )
                    connection.commit()

                exposures = list_document_exposures_payload(
                    watchlist_id=int(watchlist["id"]),
                    source_family="document_library",
                    limit=1,
                )
                self.assertEqual(1, len(exposures))
                self.assertEqual("tencent_wenku", exposures[0]["platform"])
                self.assertEqual("document_library", exposures[0]["sourceFamily"])

    def test_document_library_scan_records_login_and_captcha_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            renrendoc = next(item for item in DISCOVERY_SOURCES if item.key == "renrendoc")
            jinchutou = next(item for item in DISCOVERY_SOURCES if item.key == "jinchutou")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Library Health Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["document_library"],
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(renrendoc, "https://www.renrendoc.com/search.html?keyword=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    side_effect=RuntimeError("renrendoc:login_required"),
                ):
                    scan_watchlist_once(int(watchlist["id"]), source_families=["document_library"])

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(jinchutou, "https://so.jinchutou.com/search.html?keyword=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    side_effect=RuntimeError("jinchutou:captcha_or_security_verification"),
                ):
                    scan_watchlist_once(int(watchlist["id"]), source_families=["document_library"])

                health = {row["sourceKey"]: row for row in list_netdisk_source_health_payload(source_family="document_library")}

        self.assertEqual("login_required", health["renrendoc"]["status"])
        self.assertEqual(1, health["renrendoc"]["loginRequiredCount"])
        self.assertEqual("captcha", health["jinchutou"]["status"])
        self.assertEqual(1, health["jinchutou"]["captchaCount"])

    def test_unstable_netdisk_sources_are_opt_in(self) -> None:
        with patch.dict(
            os.environ,
            {"DARKWEB_NETDISK_INCLUDE_UNSTABLE_SOURCES": "1", "PANHUB_API_BASE": "", "PANHUB_BASE_URL": ""},
            clear=False,
        ):
            keys = [source.key for source, _ in _build_search_urls("python", ["netdisk_aggregator"])]

        self.assertIn("xiaobudian", keys)
        self.assertIn("panyq", keys)

    def test_aliyundrive_resource_fingerprint_dedupes_different_share_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            url_a = "https://www.aliyundrive.com/s/Wj1jLbTRbef/folder/6351738ed56e3da0bfbb480c8fedab3613c01cd6"
            url_b = "https://www.aliyundrive.com/s/Jw5FmeRCCBu/folder/6351738ed56e3da0bfbb480c8fedab3613c01cd6"
            fingerprint_a = _netdisk_resource_fingerprint(
                "aliyundrive_share",
                url_a,
                "01_reports",
                ["sample.pdf"],
                ["10 MB"],
                [],
            )
            fingerprint_b = _netdisk_resource_fingerprint(
                "aliyundrive_share",
                url_b,
                "01_reports",
                ["sample.pdf"],
                ["10 MB"],
                [],
            )

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                with get_db_connection() as connection:
                    connection.execute(
                        """
                        INSERT INTO exposure_watchlists (
                            name, organization_name, enabled, notes, metadata_json, created_at, updated_at
                        ) VALUES (?, ?, 1, '', '{}', ?, ?)
                        """,
                        ("Aliyun fingerprint watch", "Aliyun fingerprint watch", "2026-06-24T00:00:00Z", "2026-06-24T00:00:00Z"),
                    )
                    watchlist_id = int(connection.execute("SELECT id FROM exposure_watchlists").fetchone()["id"])
                    payload = {
                        "watchlist_id": watchlist_id,
                        "platform": "aliyundrive_share",
                        "platform_type": "netdisk_share",
                        "discovery_source": "pansou",
                        "normalized_title": "01_reports",
                        "resource_fingerprint": fingerprint_a,
                        "title": "01_reports",
                        "access_state": "public",
                        "confidence_score": 80,
                        "risk_score": 70,
                        "severity": "high",
                        "matched_terms_json": "[]",
                        "file_count": 1,
                        "evidence_count": 1,
                        "first_seen_at": "2026-06-24T00:00:00Z",
                        "last_seen_at": "2026-06-24T00:00:00Z",
                        "raw_json": "{}",
                    }
                    first_id = upsert_document_hit(connection, {**payload, "canonical_url": url_a})
                    second_id = upsert_document_hit(
                        connection,
                        {
                            **payload,
                            "canonical_url": url_b,
                            "resource_fingerprint": fingerprint_b,
                            "last_seen_at": "2026-06-24T01:00:00Z",
                        },
                    )
                    rows = connection.execute(
                        "SELECT canonical_url, resource_fingerprint, last_seen_at FROM document_hits"
                    ).fetchall()

            self.assertEqual(fingerprint_a, fingerprint_b)
            self.assertEqual(first_id, second_id)
            self.assertEqual(1, len(rows))
            self.assertEqual("2026-06-24T01:00:00Z", rows[0]["last_seen_at"])

    def test_netdisk_monitoring_continuous_dispatch_start_and_stop(self) -> None:
        with patch(
            "darkweb_collector.api_actions.list_watchlists_payload",
            return_value=[{"id": 7, "name": "网盘对象", "enabled": True, "source_families": ["netdisk_aggregator"]}],
        ), patch(
            "darkweb_collector.api_actions._run_netdisk_monitoring_once_for_watchlist",
            return_value={"watchlist_count": 1, "candidate_count": 0, "hit_count": 0, "error_count": 0, "errors": [], "results": []},
        ):
            started = api_actions.start_netdisk_monitoring_dispatch(interval_seconds=1, watchlist_id=7)
            time.sleep(0.1)
            status = api_actions.get_netdisk_monitoring_continuous_status(watchlist_id=7)
            stopped = api_actions.stop_netdisk_monitoring_dispatch(watchlist_id=7)

        self.assertTrue(started["enabled"])
        self.assertTrue(status["enabled"] or started["enabled"])
        self.assertEqual(7, started["target_watchlist_id"])
        self.assertEqual("网盘对象", started["target_watchlist_name"])
        self.assertFalse(stopped["enabled"])

    def test_netdisk_monitoring_continuous_run_scopes_to_selected_watchlist(self) -> None:
        with patch(
            "darkweb_collector.api_actions.list_watchlists_payload",
            return_value=[
                {"id": 1, "name": "对象一", "enabled": True, "source_families": ["netdisk_aggregator"], "file_types": ["pdf"], "page_limit": 4},
                {"id": 2, "name": "对象二", "enabled": True, "source_families": ["netdisk_aggregator"], "file_types": ["xlsx"], "page_limit": 3},
                {"id": 3, "name": "对象三", "enabled": True, "source_families": ["search_engine"], "file_types": ["doc"], "page_limit": 2},
            ],
        ), patch(
            "darkweb_collector.api_actions.scan_watchlist_once",
            return_value={"candidates": 5, "hits": 2, "errors": ["source:error"]},
        ) as scan_mock:
            result = api_actions._run_netdisk_monitoring_once_for_watchlist(2)

        self.assertEqual(1, result["watchlist_count"])
        self.assertEqual(5, result["candidate_count"])
        self.assertEqual(2, result["hit_count"])
        self.assertEqual(1, result["error_count"])
        scan_mock.assert_called_once()
        self.assertEqual(2, scan_mock.call_args.args[0])
        self.assertEqual(["netdisk_aggregator"], scan_mock.call_args.kwargs["source_families"])
        self.assertEqual(["xlsx"], scan_mock.call_args.kwargs["file_types"])
        self.assertNotIn("page_limit", scan_mock.call_args.kwargs)
        self.assertNotIn("max_candidates_per_term", scan_mock.call_args.kwargs)
        self.assertFalse(scan_mock.call_args.kwargs["detail_fetch"])

    def test_netdisk_monitoring_continuous_dispatch_supports_multiple_watchlists(self) -> None:
        with patch(
            "darkweb_collector.api_actions.list_watchlists_payload",
            return_value=[
                {"id": 11, "name": "网盘对象一", "enabled": True, "source_families": ["netdisk_aggregator"]},
                {"id": 13, "name": "网盘对象三", "enabled": True, "source_families": ["netdisk_aggregator"]},
            ],
        ), patch(
            "darkweb_collector.api_actions._run_netdisk_monitoring_once_for_watchlist",
            return_value={"watchlist_count": 1, "candidate_count": 0, "hit_count": 0, "error_count": 0, "errors": [], "results": []},
        ):
            started_one = api_actions.start_netdisk_monitoring_dispatch(interval_seconds=1, watchlist_id=11)
            started_two = api_actions.start_netdisk_monitoring_dispatch(interval_seconds=1, watchlist_id=13)
            time.sleep(0.1)
            status_one = api_actions.get_netdisk_monitoring_continuous_status(watchlist_id=11)
            status_two = api_actions.get_netdisk_monitoring_continuous_status(watchlist_id=13)
            api_actions.stop_netdisk_monitoring_dispatch(watchlist_id=11)
            api_actions.stop_netdisk_monitoring_dispatch(watchlist_id=13)

        self.assertTrue(started_one["enabled"])
        self.assertTrue(started_two["enabled"])
        self.assertEqual(2, status_one["active_watchlist_count"])
        self.assertEqual(2, status_two["active_watchlist_count"])
        self.assertEqual(11, status_one["target_watchlist_id"])
        self.assertEqual(13, status_two["target_watchlist_id"])

    def test_netdisk_primary_file_prefers_hit_title_or_keyword_match(self) -> None:
        title_name, title_size = _select_netdisk_primary_file(
            ["2-见实【私域×游戏化】白皮书202204-60页.pdf", "宁德时代供应链深度分析-60页.pdf"],
            ["19.75 MB", "8.88 MB"],
            "宁德时代供应链深度分析-60页.pdf",
            [{"term": "宁德时代", "term_type": "company_name"}],
        )
        keyword_name, keyword_size = _select_netdisk_primary_file(
            ["菜鸟怎样在欧洲搭建物流枢纽.pdf", "动力电池巨头宁德时代怎样布局储能（下）.pdf"],
            ["", "3.48 MB"],
            "09 蔡钰 商业参考",
            [{"term": "宁德时代", "term_type": "company_name"}],
        )

        self.assertEqual("宁德时代供应链深度分析-60页.pdf", title_name)
        self.assertEqual("8.88 MB", title_size)
        self.assertEqual("动力电池巨头宁德时代怎样布局储能（下）.pdf", keyword_name)
        self.assertEqual("3.48 MB", keyword_size)

    def test_netdisk_api_candidates_parse_merged_results(self) -> None:
        source = next(item for item in DISCOVERY_SOURCES if item.key == "pansou")
        payload = {
            "merged_by_type": {
                "baidu": [
                    {
                        "url": "https://pan.baidu.com/s/1abcdef",
                        "password": "8m7d",
                        "note": "Acme 内部名单.xlsx",
                        "source": "plugin:panyq",
                        "datetime": "2026-06-16T00:00:00Z",
                    }
                ],
                "quark": {
                    "links": [
                        {
                            "url": "https://pan.quark.cn/s/abcdef",
                            "password": "",
                            "note": "Acme 合同资料",
                        }
                    ]
                },
            }
        }

        candidates = _parse_netdisk_api_candidates(source, payload, "Acme")

        self.assertEqual(2, len(candidates))
        self.assertEqual("https://pan.baidu.com/s/1abcdef", candidates[0]["url"])
        self.assertEqual("8m7d", candidates[0]["share_code"])
        self.assertEqual("plugin:panyq", candidates[0]["source_detail"])

    def test_pikasoo_parser_keeps_result_card_description(self) -> None:
        source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")
        html = """
        <div class="search-item">
          <a href="https://pan.quark.cn/s/799fa4f8af8c" target="_blank">
            <h2 class="search-title">远川投学苑·公司案例课</h2>
          </a>
          <div class="search-des">
            <p>01.【福莱特】</p><p>05【宁德时代】</p><p>......</p>
          </div>
          <div class="search-note"><span>文件大小: 1.90 MB</span></div>
        </div>
        """

        candidates = _parse_candidates_from_html(source, html, "https://www.pikasoo.top/search?q=x")

        self.assertEqual(1, len(candidates))
        self.assertEqual("https://pan.quark.cn/s/799fa4f8af8c", candidates[0]["url"])
        self.assertEqual("远川投学苑·公司案例课", candidates[0]["title"])
        self.assertIn("宁德时代", candidates[0]["preview_text"])
        self.assertEqual(["1.90 MB"], candidates[0]["file_sizes"])

    def test_doc_detail_search_parser_follows_detail_page_for_share_link(self) -> None:
        search_html = """
        <noscript>
          <div class="search-item">
            <div class="search-item-head">
              <a class="search-item-title" href="/doc/example">CATL media kit</a>
            </div>
            <span class="search-item-info">
              <p class="search-item-info">file:CATL-media-kit.pdf size: 20 MB</p>
            </span>
          </div>
        </noscript>
        """
        detail_html = '<noscript><a href="https://pan.baidu.com/s/13g0-gPP4kA2m3S0NKB5FnQ?pwd=d8fd">open</a></noscript>'

        for key in ("lzpanx", "esoua"):
            source = next(item for item in DISCOVERY_SOURCES if item.key == key)
            with patch("darkweb_collector.document_exposure._fetch_html", return_value=detail_html):
                candidates = _parse_candidates_from_html(source, search_html, f"https://www.{key}.com/search?q=x")

            self.assertEqual(1, len(candidates))
            self.assertEqual("https://pan.baidu.com/s/13g0-gPP4kA2m3S0NKB5FnQ?pwd=d8fd", candidates[0]["url"])
            self.assertEqual("CATL media kit", candidates[0]["title"])
            self.assertEqual("d8fd", candidates[0]["share_code"])

    def test_matched_terms_ignore_highlight_spacing(self) -> None:
        matches = _matched_terms(
            "",
            "battery report: Ningde equivalent 宁德 时代 layout",
            [],
            [{"term": "宁德时代", "term_type": "company_name", "weight": 10}],
        )

        self.assertEqual(1, len(matches))
        self.assertEqual("宁德时代", matches[0]["term"])

    def test_netdisk_preview_file_names_ignore_recommendation_sections(self) -> None:
        preview_text = (
            "宁德时代超级科技日媒体素材包 "
            "file:宁德企宣2026完整版.mov "
            "file:NP3.0_风阻_02.jpg "
            "file:【核心信息】2026宁德时代Techday超级科技日.docx "
            "file:宁德时代企业简介 CN V20260316.pdf "
            "问题反馈 链接失效、内容异常、密码错误等问题都可以快速提交。 "
            "相似推荐 超级科技强国-捕鱼者.txt 超级科技大亨-驾雾.epub "
            "最新资源 谋圣从误认曹操为岳父开始1-718.txt"
        )

        self.assertEqual(
            [
                "宁德企宣2026完整版.mov",
                "NP3.0_风阻_02.jpg",
                "【核心信息】2026宁德时代Techday超级科技日.docx",
                "宁德时代企业简介 CN V20260316.pdf",
            ],
            _extract_netdisk_preview_file_names(preview_text),
        )

    def test_netdisk_preview_extracts_chinese_pdf_title(self) -> None:
        preview_text = (
            "21讲 宁德时代+晶科能源：新能源企业的下一条扩张之路在哪里？【图欧学习资源库】.pdf "
            "文件来源于阿里云盘分享：得到精品课【最新】 打开此分享 文件大小: 3.48 MB"
        )

        self.assertEqual(
            ["21讲 宁德时代+晶科能源：新能源企业的下一条扩张之路在哪里？【图欧学习资源库】.pdf"],
            _extract_netdisk_preview_file_names(preview_text),
        )

    def test_scan_prefers_baidupan_directory_listing_over_aggregator_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "esoua")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "CATL BaiduPan",
                        "organization_name": "CATL",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "file_types": [],
                        "page_limit": 1,
                        "detail_fetch": False,
                        "terms": [{"term": "宁德时代", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.esoua.com/search?q=x")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    return_value=[
                        {
                            "url": "https://pan.baidu.com/s/13g0-gPP4kA2m3S0NKB5FnQ?pwd=d8fd",
                            "title": "宁德时代超级科技日媒体素材包",
                            "source": "esoua",
                            "source_detail": "百度网盘",
                            "share_code": "d8fd",
                            "preview_text": (
                                "宁德时代超级科技日媒体素材包 file:宁德企宣2026完整版.mov "
                                "相似推荐 超级科技强国-捕鱼者.txt 最新资源 谋圣从误认曹操为岳父开始1-718.txt"
                            ),
                        }
                    ],
                ), patch(
                    "darkweb_collector.document_exposure._probe_netdisk_link_access_state",
                    return_value="public",
                ), patch(
                    "darkweb_collector.document_exposure.fetch_baidupan_share_file_entries",
                    return_value=[
                        {
                            "name": "图文素材",
                            "path": "/sharelink/root/宁德时代超级科技日媒体素材包/图文素材",
                            "size": 0,
                            "is_dir": True,
                            "depth": 1,
                        },
                        {
                            "name": "【核心信息】2026宁德时代Techday超级科技日.docx",
                            "path": "/sharelink/root/宁德时代超级科技日媒体素材包/图文素材/【核心信息】2026宁德时代Techday超级科技日.docx",
                            "size": 42108,
                            "is_dir": False,
                            "depth": 2,
                        },
                    ],
                ):
                    result = scan_watchlist_once(int(watchlist["id"]), source_families=["netdisk_aggregator"], detail_fetch=False)
                exposures = list_document_exposures_payload(source_family="netdisk_aggregator")
                with patch("darkweb_collector.document_exposure.fetch_quark_share_file_entries", return_value=[]):
                    detail = build_document_exposure_detail(int(exposures[0]["id"]))

        self.assertEqual(1, result["hits"])
        self.assertEqual([], result["errors"])
        self.assertEqual("图文素材", detail["fileList"][0]["name"])
        self.assertEqual("folder", detail["fileList"][0]["type"])
        self.assertIn("【核心信息】2026宁德时代Techday超级科技日.docx", [item["name"] for item in detail["fileList"]])
        self.assertNotIn("超级科技强国-捕鱼者.txt", [item["name"] for item in detail["fileList"]])

    def test_scan_prefers_aliyundrive_share_listing_over_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "CATL Aliyun",
                        "organization_name": "CATL",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "file_types": [],
                        "page_limit": 1,
                        "detail_fetch": False,
                        "terms": [{"term": "CATL", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search?q=x")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    return_value=[
                        {
                            "url": "https://www.aliyundrive.com/s/example/folder/folderid",
                            "title": "CATL energy files",
                            "source": "pikasoo",
                            "source_detail": "aliyundrive",
                            "share_code": "",
                            "preview_text": "CATL energy files unrelated-preview.pdf",
                        }
                    ],
                ), patch(
                    "darkweb_collector.document_exposure.fetch_aliyundrive_share_file_entries",
                    return_value=[
                        {"name": "CATL-report.pdf", "path": "CATL/CATL-report.pdf", "size": 2048, "is_dir": False, "depth": 1},
                    ],
                ), patch(
                    "darkweb_collector.document_exposure._probe_netdisk_link_access_state",
                    return_value="public",
                ):
                    result = scan_watchlist_once(int(watchlist["id"]), source_families=["netdisk_aggregator"], detail_fetch=False)
                exposures = list_document_exposures_payload(source_family="netdisk_aggregator")
                with patch("darkweb_collector.document_exposure.fetch_quark_share_file_entries", return_value=[]):
                    detail = build_document_exposure_detail(int(exposures[0]["id"]))

        self.assertEqual(1, result["hits"])
        self.assertEqual([], result["errors"])
        self.assertEqual("share_listing", detail["fileListMeta"]["quality"])
        self.assertEqual("CATL-report.pdf", detail["fileList"][0]["name"])
        self.assertEqual("share_listing", detail["fileList"][0]["source"])
        self.assertNotIn("unrelated-preview.pdf", [item["name"] for item in detail["fileList"]])

    def test_scan_prefers_quark_share_listing_over_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "CATL Quark",
                        "organization_name": "CATL",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "file_types": [],
                        "page_limit": 1,
                        "detail_fetch": False,
                        "terms": [{"term": "CATL", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search?q=x")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    return_value=[
                        {
                            "url": "https://pan.quark.cn/s/example",
                            "title": "CATL quark files",
                            "source": "pikasoo",
                            "source_detail": "quark",
                            "share_code": "",
                            "preview_text": "CATL quark files stale-preview.pdf",
                        }
                    ],
                ), patch(
                    "darkweb_collector.document_exposure.fetch_quark_share_file_entries",
                    return_value=[
                        {"name": "CATL", "path": "CATL", "size": 0, "is_dir": True, "depth": 0},
                        {"name": "CATL-report.pdf", "path": "CATL/CATL-report.pdf", "size": 4096, "is_dir": False, "depth": 1},
                    ],
                ), patch(
                    "darkweb_collector.document_exposure._probe_netdisk_link_access_state",
                    return_value="public",
                ):
                    result = scan_watchlist_once(int(watchlist["id"]), source_families=["netdisk_aggregator"], detail_fetch=False)
                exposures = list_document_exposures_payload(source_family="netdisk_aggregator")
                detail = build_document_exposure_detail(int(exposures[0]["id"]))

        self.assertEqual(1, result["hits"])
        self.assertEqual([], result["errors"])
        self.assertEqual("share_listing", detail["fileListMeta"]["quality"])
        self.assertEqual("folder", detail["fileList"][0]["type"])
        self.assertIn("CATL-report.pdf", [item["name"] for item in detail["fileList"]])
        self.assertNotIn("stale-preview.pdf", [item["name"] for item in detail["fileList"]])

    def test_scan_does_not_build_preview_tree_for_removed_quark_share(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "CATL Removed Quark",
                        "organization_name": "CATL",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "file_types": [],
                        "page_limit": 1,
                        "detail_fetch": False,
                        "terms": [{"term": "CATL", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search?q=x")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    return_value=[
                        {
                            "url": "https://pan.quark.cn/s/removed",
                            "title": "CATL removed share",
                            "source": "pikasoo",
                            "source_detail": "quark",
                            "share_code": "",
                            "preview_text": "CATL removed share 01.fake.pdf 02.fake.mp4",
                        }
                    ],
                ), patch(
                    "darkweb_collector.document_exposure.fetch_quark_share_file_entries",
                    side_effect=NetdiskShareUnavailable("removed", "cancelled"),
                ), patch(
                    "darkweb_collector.document_exposure._probe_netdisk_link_access_state",
                    return_value="public",
                ):
                    result = scan_watchlist_once(int(watchlist["id"]), source_families=["netdisk_aggregator"], detail_fetch=False)
                exposures = list_document_exposures_payload(source_family="netdisk_aggregator")
                detail = build_document_exposure_detail(int(exposures[0]["id"]))

        self.assertEqual(1, result["hits"])
        self.assertEqual([], result["errors"])
        self.assertEqual("removed", exposures[0]["accessState"])
        self.assertEqual(0, exposures[0]["fileCount"])
        self.assertEqual([], detail["fileList"])
        self.assertEqual("none", detail["fileListMeta"]["quality"])

    def test_netdisk_list_refreshes_legacy_unknown_access_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Legacy Netdisk",
                        "organization_name": "CATL",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "file_types": [],
                        "terms": [{"term": "CATL", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with get_db_connection() as connection:
                    hit_id = upsert_document_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "quark_share",
                            "platform_type": "netdisk_share",
                            "discovery_source": "pikasoo",
                            "canonical_url": "https://pan.quark.cn/s/removed",
                            "normalized_title": "catl-removed",
                            "title": "CATL removed.pdf",
                            "access_state": "unknown",
                            "confidence_score": 60,
                            "risk_score": 60,
                            "severity": "medium",
                            "matched_terms_json": json.dumps([{"term": "CATL"}], ensure_ascii=False),
                            "file_count": 1,
                            "share_owner": "",
                            "disclosure_time": "",
                            "first_seen_at": "2026-06-16T07:17:18+00:00",
                            "last_seen_at": "2026-06-16T07:17:18+00:00",
                            "raw_json": json.dumps(
                                {
                                    "page_url": "https://pan.quark.cn/s/removed",
                                    "preview_text": "CATL removed.pdf",
                                    "file_names": ["CATL removed.pdf"],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    snapshot_id = insert_document_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": "2026-06-16T07:17:18+00:00",
                            "source_query": "CATL",
                            "source_url": "https://www.pikasoo.top/search?q=CATL",
                            "page_url": "https://pan.quark.cn/s/removed",
                            "page_title": "CATL removed.pdf",
                            "html_path": "",
                            "screenshot_path": "",
                            "ocr_text": "CATL removed.pdf",
                            "preview_text": "CATL removed.pdf",
                            "file_list_json": json.dumps([{"name": "CATL removed.pdf"}], ensure_ascii=False),
                            "access_state": "unknown",
                            "matched_terms_json": json.dumps([{"term": "CATL"}], ensure_ascii=False),
                            "raw_json": "{}",
                        },
                    )
                    update_document_hit_last_snapshot(connection, hit_id, snapshot_id)
                    connection.commit()

                with patch("darkweb_collector.document_exposure._probe_netdisk_link_access_state", return_value="removed"):
                    exposures = list_document_exposures_payload(source_family="netdisk_aggregator")

                with get_db_connection() as connection:
                    hit_row = connection.execute("SELECT access_state, raw_json FROM document_hits WHERE id = ?", (hit_id,)).fetchone()
                    snapshot_row = connection.execute(
                        "SELECT access_state, raw_json FROM document_hit_snapshots WHERE id = ?",
                        (snapshot_id,),
                    ).fetchone()

        self.assertEqual("removed", exposures[0]["accessState"])
        self.assertEqual("removed", hit_row["access_state"])
        self.assertEqual("removed", snapshot_row["access_state"])
        self.assertEqual("removed", json.loads(hit_row["raw_json"])["access_state"])
        self.assertTrue(json.loads(hit_row["raw_json"])["validated_at"])

    def test_netdisk_detail_promotes_matched_preview_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Deep Listing",
                        "organization_name": "宁德时代",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "file_types": [],
                        "terms": [{"term": "宁德时代", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with get_db_connection() as connection:
                    hit_id = upsert_document_hit(
                        connection,
                        {
                            "watchlist_id": int(watchlist["id"]),
                            "platform": "aliyundrive_share",
                            "platform_type": "netdisk_share",
                            "discovery_source": "esoua",
                            "canonical_url": "https://www.aliyundrive.com/s/deep",
                            "normalized_title": "business-reference",
                            "title": "09 蔡钰 商业参考",
                            "access_state": "public",
                            "confidence_score": 78,
                            "risk_score": 78,
                            "severity": "high",
                            "matched_terms_json": json.dumps([{"term": "宁德时代", "term_type": "company_name", "weight": 10}], ensure_ascii=False),
                            "file_count": 1,
                            "share_owner": "",
                            "disclosure_time": "",
                            "first_seen_at": "2026-06-16T10:01:47+00:00",
                            "last_seen_at": "2026-06-16T10:01:47+00:00",
                            "raw_json": json.dumps(
                                {
                                    "page_url": "https://www.aliyundrive.com/s/deep",
                                    "preview_text": (
                                        "file:cy256 ｜ 动力电池巨头 宁德 时代 怎样布局储能 "
                                        "file:cy256 ｜ 动力电池巨头宁德时代怎样布局储能（下）.pdf"
                                    ),
                                    "file_names": [],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    snapshot_id = insert_document_hit_snapshot(
                        connection,
                        {
                            "hit_id": hit_id,
                            "fetched_at": "2026-06-16T10:01:47+00:00",
                            "source_query": "宁德时代",
                            "source_url": "https://www.esoua.com/search?q=x",
                            "page_url": "https://www.aliyundrive.com/s/deep",
                            "page_title": "09 蔡钰 商业参考",
                            "html_path": "",
                            "screenshot_path": "",
                            "ocr_text": "",
                            "preview_text": (
                                "file:cy256 ｜ 动力电池巨头 宁德 时代 怎样布局储能 "
                                "file:cy256 ｜ 动力电池巨头宁德时代怎样布局储能（下）.pdf"
                            ),
                            "file_list_json": json.dumps([{"name": "09 蔡钰 商业参考", "path": "09 蔡钰 商业参考"}], ensure_ascii=False),
                            "access_state": "public",
                            "matched_terms_json": json.dumps([{"term": "宁德时代"}], ensure_ascii=False),
                            "raw_json": "{}",
                        },
                    )
                    update_document_hit_last_snapshot(connection, hit_id, snapshot_id)
                    connection.commit()

                exposures = list_document_exposures_payload(source_family="netdisk_aggregator")
                self.assertEqual("动力电池巨头宁德时代怎样布局储能（下）.pdf", exposures[0]["primaryFileName"])

                calls = []

                def fake_listing(url, share_code):
                    calls.append((url, share_code))
                    return [
                        {
                            "name": "09 蔡钰 商业参考",
                            "path": "09 蔡钰 商业参考",
                            "size": "",
                            "is_dir": True,
                            "source": "share_listing",
                        },
                        {
                            "name": "unrelated.pdf",
                            "path": "09 蔡钰 商业参考/unrelated.pdf",
                            "size": "",
                            "is_dir": False,
                            "source": "share_listing",
                        },
                    ]

                with patch("darkweb_collector.document_exposure._netdisk_file_entries_from_aliyundrive", side_effect=fake_listing):
                    detail = build_document_exposure_detail(hit_id)

        file_names = [item["name"] for item in detail["fileList"]]
        self.assertEqual([("https://www.aliyundrive.com/s/deep", "")], calls)
        self.assertTrue(detail["previewAssets"])
        self.assertEqual("镜像文件", detail["previewAssets"][0]["label"])
        self.assertTrue(detail["latestSnapshot"]["htmlPath"])
        self.assertEqual("share_listing", detail["fileListMeta"]["quality"])
        self.assertEqual("动力电池巨头宁德时代怎样布局储能（下）.pdf", detail["fileList"][0]["name"])
        self.assertEqual("matched_preview", detail["fileList"][0]["source"])
        self.assertIn("unrelated.pdf", file_names)

    def test_scan_matches_netdisk_candidate_preview_without_detail_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "CATL Preview",
                        "organization_name": "CATL",
                        "enabled": True,
                        "source_families": ["netdisk_aggregator"],
                        "file_types": [],
                        "page_limit": 1,
                        "detail_fetch": False,
                        "terms": [{"term": "宁德时代", "term_type": "company_name", "weight": 10, "enabled": True}],
                    }
                )
                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search?q=x")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    return_value=[
                        {
                            "url": "https://pan.quark.cn/s/799fa4f8af8c",
                            "title": "远川投学苑·公司案例课",
                            "source": "pikasoo",
                            "source_detail": "夸克网盘分享页",
                            "share_code": "",
                            "preview_text": (
                                "远川投学苑·公司案例课 远川投学苑·公司案例课 "
                                "01.【福莱特】 05【宁德时代】 文件大小: 3.55 GB 数量: 30 神秘网友 反馈"
                            ),
                            "file_sizes": ["3.55 GB"],
                        }
                    ],
                ), patch(
                    "darkweb_collector.document_exposure.fetch_quark_share_file_entries",
                    return_value=[],
                ), patch(
                    "darkweb_collector.document_exposure._probe_netdisk_link_access_state",
                    return_value="public",
                ):
                    result = scan_watchlist_once(int(watchlist["id"]), source_families=["netdisk_aggregator"], detail_fetch=False)
                    exposures = list_document_exposures_payload(source_family="netdisk_aggregator")
                    detail = build_document_exposure_detail(int(exposures[0]["id"]))

        self.assertEqual(1, result["hits"])
        self.assertEqual([], result["errors"])
        self.assertEqual("public", exposures[0]["accessState"])
        self.assertGreaterEqual(exposures[0]["fileCount"], 2)
        self.assertEqual("远川投学苑·公司案例课", detail["fileList"][0]["name"])
        self.assertEqual("folder", detail["fileList"][0]["type"])
        self.assertEqual("aggregator_preview", detail["fileListMeta"]["quality"])
        self.assertIn("05【宁德时代】", [item["name"] for item in detail["fileList"]])

    def test_netdisk_link_probe_marks_reachable_link_public(self) -> None:
        with patch(
            "darkweb_collector.document_exposure._fetch_html",
            return_value="<html><body>请输入提取码 查看文件列表</body></html>",
        ):
            state = _probe_netdisk_link_access_state("https://pan.quark.cn/s/799fa4f8af8c")

        self.assertEqual("public", state)

    def test_netdisk_link_probe_ignores_status_codes_inside_scripts(self) -> None:
        with patch(
            "darkweb_collector.document_exposure._fetch_html",
            return_value=(
                "<html><head><title>阿里云盘分享</title></head>"
                "<body><div id=\"root\"></div><script>window.chunkId='410'</script></body></html>"
            ),
        ):
            state = _probe_netdisk_link_access_state("https://www.aliyundrive.com/s/example/folder/627f4e")

        self.assertEqual("public", state)

    def test_netdisk_link_probe_marks_404_removed(self) -> None:
        error = HTTPError("https://pan.quark.cn/s/missing", 404, "Not Found", {}, None)
        with patch("darkweb_collector.document_exposure._fetch_html", side_effect=error):
            state = _probe_netdisk_link_access_state("https://pan.quark.cn/s/missing")

        self.assertEqual("removed", state)

    def test_fetch_html_retries_once_on_transport_error(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b"<html>ok</html>"

        with patch(
            "darkweb_collector.document_exposure.urlopen",
            side_effect=[URLError("temporary eof"), FakeResponse()],
        ) as urlopen_mock, patch("darkweb_collector.document_exposure.time.sleep") as sleep_mock:
            html = _fetch_html("https://www.pikasoo.top/search/?q=test", timeout=1)

        self.assertEqual("<html>ok</html>", html)
        self.assertEqual(2, urlopen_mock.call_count)
        sleep_mock.assert_called_once_with(0.5)

    def test_pansou_api_request_does_not_force_cloud_type_filter(self) -> None:
        source = next(item for item in DISCOVERY_SOURCES if item.key == "pansou")
        requests = []

        def fake_post_json_api(url, payload, token=None):
            requests.append(payload)
            return {
                "merged_by_type": {
                    "quark": [
                        {
                            "url": "https://pan.quark.cn/s/abcdef",
                            "note": "python tutorial",
                        }
                    ]
                }
            }

        with patch.dict(os.environ, {"PANSOU_API_BASE": "http://127.0.0.1:8888"}, clear=False), patch(
            "darkweb_collector.document_exposure._post_json_api",
            side_effect=fake_post_json_api,
        ):
            candidates = _fetch_netdisk_api_candidates(source, "python")

        self.assertEqual(1, len(candidates))
        self.assertNotIn("cloud_types", requests[0])

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
                        "source_families": ["document_library"],
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
                    result = scan_watchlist_once(
                        int(watchlist["id"]),
                        max_candidates_per_term=1,
                        source_families=["document_library"],
                    )

                self.assertEqual(1, result["hits"])
                exposures = list_document_exposures_payload()
                self.assertEqual(1, len(exposures))
                scan_runs = list_exposure_scan_runs_payload()
                self.assertEqual(1, len(scan_runs))
                self.assertEqual(1, scan_runs[0]["hitCount"])
                self.assertEqual("succeeded", scan_runs[0]["status"])

    def test_scan_watchlist_once_keeps_structured_netdisk_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            detail_platform = get_exposure_platform("baidupan_share")

            def fake_api_candidates(source, term):
                if source.key != "pansou":
                    return []
                return [
                    {
                        "url": "https://pan.baidu.com/s/1abcdef",
                        "title": "Acme 内部名单.xlsx",
                        "source": "pansou",
                        "source_detail": "plugin:panyq",
                        "share_code": "8m7d",
                        "cloud_type": "baidu",
                        "source_datetime": "2026-06-16T00:00:00Z",
                        "preview_text": "Acme 内部名单.xlsx 提取码 8m7d",
                    }
                ]

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Netdisk Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["netdisk_aggregator"],
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch("darkweb_collector.document_exposure._fetch_netdisk_api_candidates", side_effect=fake_api_candidates), patch(
                    "darkweb_collector.document_exposure._fetch_html",
                    return_value="<html><body></body></html>",
                ), patch(
                    "darkweb_collector.document_exposure._detail_payload_from_page",
                    side_effect=AssertionError("netdisk scan should not fetch page artifacts"),
                ), patch(
                    "darkweb_collector.document_exposure._netdisk_file_entries_from_baidupan",
                    return_value=[
                        {
                            "name": "Acme内部名单.xlsx",
                            "path": "Acme内部名单.xlsx",
                            "size": "85.6 KB",
                            "is_dir": False,
                            "source": "share_listing",
                        }
                    ],
                ), patch("darkweb_collector.document_exposure._probe_netdisk_link_access_state", return_value="public"):
                    result = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["netdisk_aggregator"],
                        detail_fetch=True,
                    )

                self.assertEqual(1, result["hits"])
                exposures = list_document_exposures_payload(source_family="netdisk_aggregator")
                self.assertEqual(1, len(exposures))
                self.assertEqual("baidupan_share", exposures[0]["platform"])
                self.assertEqual("8m7d", exposures[0]["shareCode"])
                self.assertEqual("password_share", exposures[0]["shareType"])
                detail = build_document_exposure_detail(int(exposures[0]["id"]))
                self.assertTrue(detail["previewAssets"])
                self.assertTrue(detail["latestSnapshot"]["htmlPath"])
                self.assertTrue(Path(detail["latestSnapshot"]["htmlPath"]).exists())
                self.assertEqual("", detail["latestSnapshot"]["screenshotPath"])
                self.assertIn("Acme", Path(detail["latestSnapshot"]["htmlPath"]).read_text(encoding="utf-8"))

    def test_netdisk_scan_does_not_limit_candidates_per_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pansou")
            candidates = [
                {
                    "url": f"https://pan.baidu.com/s/1acme{index}",
                    "title": f"Acme 泄露资料 {index}.pdf",
                    "source": "pansou",
                    "preview_text": f"Acme 泄露资料 {index}.pdf",
                }
                for index in range(3)
            ]

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Netdisk Unlimited Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["netdisk_aggregator"],
                        "file_types": ["pdf"],
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "pansou://search?kw=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    return_value=candidates,
                ), patch(
                    "darkweb_collector.document_exposure._netdisk_file_entries_from_baidupan",
                    return_value=[
                        {
                            "name": "Acme 泄露资料.pdf",
                            "path": "Acme 泄露资料.pdf",
                            "size": "1 MB",
                            "is_dir": False,
                            "source": "share_listing",
                        }
                    ],
                ), patch("darkweb_collector.document_exposure._probe_netdisk_link_access_state", return_value="public"):
                    result = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["netdisk_aggregator"],
                        file_types=["pdf"],
                        page_limit=1,
                    )

                self.assertEqual(3, result["candidates"])
                self.assertEqual(3, result["hits"])

    def test_netdisk_scan_paginates_primary_source_and_records_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")

            def fake_search_candidates(_source, page_url, _term):
                if "page=3" in page_url:
                    return []
                suffix = "2" if "page=2" in page_url else "1"
                return [
                    {
                        "url": f"https://pan.baidu.com/s/1acme-page-{suffix}",
                        "title": f"Acme 第{suffix}页资料.pdf",
                        "source": "pikasoo",
                        "preview_text": f"Acme 第{suffix}页资料.pdf",
                    }
                ]

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Netdisk Paging Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["netdisk_aggregator"],
                        "file_types": ["pdf"],
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search/?pan=all&type=doc&q=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    side_effect=fake_search_candidates,
                ), patch(
                    "darkweb_collector.document_exposure._netdisk_file_entries_from_baidupan",
                    return_value=[
                        {
                            "name": "Acme 分页资料.pdf",
                            "path": "Acme 分页资料.pdf",
                            "size": "1 MB",
                            "is_dir": False,
                            "source": "share_listing",
                        }
                    ],
                ), patch("darkweb_collector.document_exposure._probe_netdisk_link_access_state", return_value="public"):
                    result = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["netdisk_aggregator"],
                        file_types=["pdf"],
                    )

                self.assertEqual(2, result["candidates"])
                self.assertEqual(2, result["hits"])
                self.assertEqual(1, len(result["source_stats"]))
                self.assertEqual(3, result["source_stats"][0]["pagesScanned"])
                self.assertEqual(2, result["source_stats"][0]["candidateCount"])
                self.assertEqual(2, result["source_stats"][0]["hitCount"])
                scan_runs = list_exposure_scan_runs_payload()
                self.assertEqual(3, scan_runs[0]["sourceStats"][0]["pagesScanned"])
                self.assertEqual(2, scan_runs[0]["sourceStats"][0]["candidateCount"])

    def test_netdisk_scan_page_limit_caps_paginated_search_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")

            def fake_search_candidates(_source, page_url, _term):
                page = 1
                if "page=" in page_url:
                    page = int(page_url.rsplit("page=", 1)[1])
                return [
                    {
                        "url": f"https://pan.baidu.com/s/1acme-page-limit-{page}",
                        "title": f"Acme page {page}.pdf",
                        "source": "pikasoo",
                        "preview_text": f"Acme page {page}.pdf",
                    }
                ]

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Netdisk Page Limit Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["netdisk_aggregator"],
                        "file_types": ["pdf"],
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search/?pan=all&type=doc&q=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    side_effect=fake_search_candidates,
                ), patch(
                    "darkweb_collector.document_exposure._netdisk_file_entries_from_baidupan",
                    return_value=[
                        {
                            "name": "Acme page.pdf",
                            "path": "Acme page.pdf",
                            "size": "1 MB",
                            "is_dir": False,
                            "source": "share_listing",
                        }
                    ],
                ), patch("darkweb_collector.document_exposure._probe_netdisk_link_access_state", return_value="public"):
                    result = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["netdisk_aggregator"],
                        file_types=["pdf"],
                        page_limit=2,
                    )

                self.assertEqual(2, result["candidates"])
                self.assertEqual(2, result["hits"])
                self.assertEqual(2, result["source_stats"][0]["pagesScanned"])

    def test_legacy_netdisk_scan_records_cursor_without_changing_page_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")
            scanned_pages = []

            def fake_search_candidates(_source, page_url, _term):
                page = 1
                if "page=" in page_url:
                    page = int(page_url.rsplit("page=", 1)[1])
                scanned_pages.append(page)
                return [
                    {
                        "url": f"https://pan.baidu.com/s/1legacy-page-{page}",
                        "title": f"Acme legacy page {page}.pdf",
                        "source": "pikasoo",
                        "preview_text": f"Acme legacy page {page}.pdf",
                    }
                ]

            env = {**self._env(db_path, output_root, config_path), "NETDISK_SCAN_MODE": "legacy"}
            with patch.dict(os.environ, env, clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Netdisk Legacy Cursor Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["netdisk_aggregator"],
                        "file_types": ["pdf"],
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search/?pan=all&type=doc&q=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    side_effect=fake_search_candidates,
                ), patch(
                    "darkweb_collector.document_exposure._netdisk_file_entries_from_baidupan",
                    return_value=[
                        {
                            "name": "Acme legacy page.pdf",
                            "path": "Acme legacy page.pdf",
                            "size": "1 MB",
                            "is_dir": False,
                            "source": "share_listing",
                        }
                    ],
                ), patch("darkweb_collector.document_exposure._probe_netdisk_link_access_state", return_value="public"):
                    result = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["netdisk_aggregator"],
                        file_types=["pdf"],
                        page_limit=2,
                    )

                self.assertEqual([1, 2], scanned_pages)
                self.assertEqual("legacy", result["netdisk_scan_mode"])
                states = list_netdisk_source_states_payload(watchlist_id=int(watchlist["id"]))
                self.assertEqual(1, len(states))
                self.assertEqual(3, states[0]["nextPage"])
                self.assertEqual(2, states[0]["pageWindowSize"])
                self.assertEqual([1, 3, 4], states[0]["suggestedPages"])

    def test_incremental_netdisk_scan_advances_deep_page_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)
            source = next(item for item in DISCOVERY_SOURCES if item.key == "pikasoo")
            scanned_pages = []

            def fake_search_candidates(_source, page_url, _term):
                page = 1
                if "page=" in page_url:
                    page = int(page_url.rsplit("page=", 1)[1])
                scanned_pages.append(page)
                return [
                    {
                        "url": f"https://pan.baidu.com/s/1incremental-page-{page}",
                        "title": f"Acme incremental page {page}.pdf",
                        "source": "pikasoo",
                        "preview_text": f"Acme incremental page {page}.pdf",
                    }
                ]

            env = {**self._env(db_path, output_root, config_path), "NETDISK_SCAN_MODE": "incremental"}
            with patch.dict(os.environ, env, clear=False):
                watchlist = save_watchlist_payload(
                    {
                        "name": "Netdisk Incremental Cursor Watch",
                        "organization_name": "Acme Corp",
                        "enabled": True,
                        "notes": "",
                        "source_families": ["netdisk_aggregator"],
                        "file_types": ["pdf"],
                        "page_limit": 4,
                        "terms": [
                            {"term": "Acme", "term_type": "company_name", "weight": 15, "enabled": True},
                        ],
                    }
                )

                with patch(
                    "darkweb_collector.document_exposure._build_search_urls",
                    return_value=[(source, "https://www.pikasoo.top/search/?pan=all&type=doc&q=Acme")],
                ), patch(
                    "darkweb_collector.document_exposure._search_candidates_for_source",
                    side_effect=fake_search_candidates,
                ), patch(
                    "darkweb_collector.document_exposure._netdisk_file_entries_from_baidupan",
                    return_value=[
                        {
                            "name": "Acme incremental page.pdf",
                            "path": "Acme incremental page.pdf",
                            "size": "1 MB",
                            "is_dir": False,
                            "source": "share_listing",
                        }
                    ],
                ), patch("darkweb_collector.document_exposure._probe_netdisk_link_access_state", return_value="public"):
                    first = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["netdisk_aggregator"],
                        file_types=["pdf"],
                    )
                    first_pages = list(scanned_pages)
                    scanned_pages.clear()
                    second = scan_watchlist_once(
                        int(watchlist["id"]),
                        source_families=["netdisk_aggregator"],
                        file_types=["pdf"],
                    )
                    second_pages = list(scanned_pages)

                self.assertEqual("incremental", first["netdisk_scan_mode"])
                self.assertEqual("incremental", second["netdisk_scan_mode"])
                self.assertEqual([1, 2, 3, 4], first_pages)
                self.assertEqual([1, 5, 6, 7, 8], second_pages)
                states = list_netdisk_source_states_payload(watchlist_id=int(watchlist["id"]))
                self.assertEqual(1, len(states))
                self.assertEqual(9, states[0]["nextPage"])
                self.assertEqual(8, states[0]["lastScannedPage"])
                self.assertEqual([1, 9, 10, 11, 12], states[0]["suggestedPages"])
                health = [row for row in list_netdisk_source_health_payload() if row["sourceKey"] == "pikasoo"]
                self.assertEqual(1, len(health))
                self.assertEqual(2, health[0]["successCount"])


if __name__ == "__main__":
    unittest.main()
