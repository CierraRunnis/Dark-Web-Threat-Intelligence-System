from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from darkweb_collector.adapters.changan import ChanganAdapter, _artifact_stem
from darkweb_collector.api_data import _label_source as api_source_label
from darkweb_collector.config import get_site_config
from darkweb_collector.models import DetailTask, SeedResult, SiteConfig
from darkweb_collector.normalized_intelligence import _canonical_key, normalized_event_to_detail
from darkweb_collector.remote_browser_sessions import _validate_session_before_save
from darkweb_collector.site_auth import (
    SiteAuthenticationRequired,
    load_local_storage_value,
    site_auth_readiness,
)
from darkweb_collector.sites.changan import parse_changan_detail, parse_changan_list


FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "http://cabyceogpsji73sske5nvo45mdrkbz4m3qd3iommf3zaaa6izg3j2cqd.onion"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _config(output_dir: Path, *, max_details: int = 15) -> SiteConfig:
    return SiteConfig(
        site_name="changan",
        enabled=True,
        seed_urls=(f"{BASE_URL}/#/home",),
        seed_fetch_mode="tor_http",
        detail_fetch_mode="browser",
        profile="hot",
        max_topics_per_run=30,
        max_detail_pages_per_run=max_details,
        cooldown_seconds=1800,
        output_dir=output_dir,
        dedupe_window_minutes=120,
        extras={
            "display_name": "长安不夜城",
            "auth_platform": "changan",
            "auth_origin": BASE_URL,
            "auth_storage_key": "token",
        },
    )


class ChanganParserTests(unittest.TestCase):
    def test_list_mapping_limit_and_content_hash(self):
        payload = _fixture("changan_list.json")
        parsed = parse_changan_list(
            payload,
            base_url=BASE_URL,
            collected_at_utc="2026-07-13T00:00:00+00:00",
            max_topics=2,
        )

        self.assertEqual(parsed["topic_count"], 2)
        self.assertEqual(parsed["total"], 3)
        self.assertEqual(parsed["topics"][0]["author"], "seller-one")
        self.assertEqual(parsed["topics"][0]["category"], "数据库")
        self.assertEqual(parsed["topics"][0]["full_url"], f"{BASE_URL}/#/detail?gid=goods-101")

        changed = deepcopy(payload)
        changed["data"]["goods"][0]["intro"] = "变更后的脱敏说明"
        changed_parsed = parse_changan_list(
            changed,
            base_url=BASE_URL,
            collected_at_utc="2026-07-13T00:00:00+00:00",
            max_topics=2,
        )
        self.assertNotEqual(
            parsed["topics"][0]["content_hash"],
            changed_parsed["topics"][0]["content_hash"],
        )

    def test_detail_mapping_strips_active_html(self):
        detail = parse_changan_detail(
            _fixture("changan_detail.json"),
            detail_url=f"{BASE_URL}/#/detail?gid=goods-101",
            collected_at_utc="2026-07-13T00:00:00+00:00",
        )

        self.assertEqual(detail["title"], "示例数据库商品")
        self.assertEqual(detail["author"], "seller-one")
        self.assertEqual(detail["category"], "数据库")
        self.assertEqual(detail["origin"], "示例来源")
        self.assertIn("字段说明", detail["content"])
        self.assertNotIn("ignored()", detail["content"])
        self.assertEqual(len(detail["attachments"]), 2)

    def test_empty_list_is_not_an_error(self):
        parsed = parse_changan_list(
            {"code": 2000, "data": {"total": 0, "goods": []}},
            base_url=BASE_URL,
            collected_at_utc="2026-07-13T00:00:00+00:00",
            max_topics=30,
        )
        self.assertEqual(parsed["topics"], [])

    def test_unix_timestamps_and_source_label_are_normalized(self):
        list_payload = _fixture("changan_list.json")
        list_payload["data"]["goods"][0]["ctime"] = 1778130744
        parsed = parse_changan_list(
            list_payload,
            base_url=BASE_URL,
            collected_at_utc="2026-07-13T00:00:00+00:00",
            max_topics=1,
        )
        self.assertEqual(parsed["topics"][0]["published_at"], "2026-05-07T05:12:24+00:00")

        detail_payload = _fixture("changan_detail.json")
        detail_payload["data"]["ctime"] = 1782350792000
        detail = parse_changan_detail(
            detail_payload,
            detail_url=f"{BASE_URL}/#/detail?gid=goods-101",
            collected_at_utc="2026-07-13T00:00:00+00:00",
        )
        self.assertEqual(detail["timestamp"], "2026-06-25T01:26:32+00:00")
        self.assertEqual(api_source_label("changan"), "长安不夜城")

    def test_chinese_titles_do_not_collapse_to_the_same_dedupe_key(self):
        self.assertNotEqual(_canonical_key("日本购物数据15万"), _canonical_key("越南银行数据15万"))

    def test_normalized_detail_uses_source_display_name(self):
        detail = normalized_event_to_detail(
            {
                "event_id": "forum:changan:test",
                "source_kind": "forum",
                "event_type": "data_leak",
                "raw_source_type": "test_fixture",
                "title": "测试商品",
                "disclosure_time": "2026-07-13T00:00:00+00:00",
                "attacker": "长安不夜城",
                "source_url": f"{BASE_URL}/#/detail?gid=test",
                "detail_text": "测试详情",
                "category": "交易售卖",
                "source": "changan",
                "industry": "未知",
                "region": "未知",
                "mirror_resources": [],
                "screenshot_resources": [],
                "json_preview_url": "",
                "victim": "未知实体",
                "risk_score": 0,
                "risk_reasons": [],
                "leak_type": "数据售卖",
                "severity": "medium",
                "metadata": {},
            }
        )
        self.assertEqual(detail["source"], "长安不夜城")


class ChanganAuthTests(unittest.TestCase):
    def test_storage_state_token_and_no_login_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "storage_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "origins": [
                            {
                                "origin": BASE_URL,
                                "localStorage": [{"name": "token", "value": "noLogin_example"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_local_storage_value(state_path, BASE_URL, "token"), "noLogin_example")
            config = _config(Path(temp_dir) / "output")
            with (
                patch("darkweb_collector.site_auth.get_db_connection", return_value=nullcontext(object())),
                patch("darkweb_collector.site_auth.get_platform_session", return_value={"status": "configured"}),
                patch("darkweb_collector.site_auth.resolve_platform_storage_state_path", return_value=state_path),
            ):
                readiness = site_auth_readiness(config)
            self.assertFalse(readiness["ready"])
            self.assertEqual(readiness["auth_status"], "login_required")

    def test_remote_save_validation_requires_authenticated_api(self):
        valid_page = Mock()
        valid_page.evaluate.return_value = {"valid": True, "code": 2000, "message": "ok"}
        _validate_session_before_save(SimpleNamespace(platform="changan"), valid_page)
        self.assertIn("/api/category/goods", valid_page.evaluate.call_args.args[0])

        invalid_page = Mock()
        invalid_page.evaluate.return_value = {"valid": False, "code": 4009, "message": "InvalidAuthorization"}
        with self.assertRaisesRegex(ValueError, "4009"):
            _validate_session_before_save(SimpleNamespace(platform="changan"), invalid_page)

    def test_auth_api_codes_mark_session_invalid(self):
        adapter = ChanganAdapter()
        config = _config(Path("output/changan"))
        for code in (4009, 4087):
            result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"code": code, "msg": "InvalidAuthorization"}).encode(),
                stderr=b"",
            )
            with self.subTest(code=code):
                with (
                    patch("darkweb_collector.adapters.changan.require_site_auth_token", return_value=("token", "state.json")),
                    patch("darkweb_collector.adapters.changan.shutil.which", return_value="curl"),
                    patch("darkweb_collector.adapters.changan.get_tor_socks_settings", return_value=("127.0.0.1", 9050)),
                    patch("darkweb_collector.adapters.changan.subprocess.run", return_value=result),
                    patch("darkweb_collector.adapters.changan.mark_site_auth_invalid") as mark_invalid,
                ):
                    with self.assertRaises(SiteAuthenticationRequired):
                        adapter._api_get(config, "/api/category/goods")
                    mark_invalid.assert_called_once()


class ChanganSchedulingTests(unittest.TestCase):
    def test_detail_screenshot_keeps_product_image_and_information(self):
        adapter = ChanganAdapter()
        config = _config(Path("output/changan"))
        task = DetailTask(
            site_name="changan",
            target_url=f"{BASE_URL}/#/detail?gid=goods-101",
            metadata={"goods_id": "goods-101", "artifact_stem": "fixture"},
        )
        with (
            patch.object(adapter, "_api_get", return_value=_fixture("changan_detail.json")),
            patch(
                "darkweb_collector.adapters.changan.require_site_auth_token",
                return_value=("token", "storage-state.json"),
            ),
            patch(
                "darkweb_collector.adapters.changan.fetch_page_artifacts_with_browser",
                return_value=("<html></html>", b"png"),
            ) as fetch_artifacts,
        ):
            result = adapter.collect_detail(task, config, SimpleNamespace())

        self.assertIsNotNone(result)
        self.assertEqual(
            fetch_artifacts.call_args.kwargs["screenshot_selectors"],
            (".product-detail-info",),
        )
        self.assertNotIn("redact_selectors", fetch_artifacts.call_args.kwargs)

    def test_detail_plan_limits_and_skips_unchanged_artifacts(self):
        adapter = ChanganAdapter()
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(Path(temp_dir), max_details=15)
            topics = [
                {
                    "goods_id": str(index),
                    "title": f"item-{index}",
                    "full_url": f"{BASE_URL}/#/detail?gid={index}",
                    "content_hash": f"hash-{index}",
                }
                for index in range(20)
            ]
            seed = SeedResult(
                site_name="changan",
                collected_at_utc="2026-07-13T00:00:00+00:00",
                payload={"sections": [{"topics": topics}]},
                raw_html_by_url={},
            )
            with (
                patch("darkweb_collector.adapters.changan.get_db_connection", return_value=nullcontext(object())),
                patch("darkweb_collector.adapters.changan.get_forum_topic_snapshot", return_value=None),
                patch("darkweb_collector.adapters.changan.get_forum_detail_snapshot", return_value=None),
            ):
                self.assertEqual(len(adapter.plan_details(seed, config)), 15)

            first = topics[0]
            stem = _artifact_stem(first["full_url"])
            detail_dir = config.output_dir / "sellers_place" / "details"
            detail_dir.mkdir(parents=True)
            for suffix in ("html", "json", "png"):
                (detail_dir / f"{stem}.{suffix}").write_bytes(b"fixture")
            one_seed = SeedResult(
                site_name="changan",
                collected_at_utc=seed.collected_at_utc,
                payload={"sections": [{"topics": [first]}]},
                raw_html_by_url={},
            )
            with (
                patch("darkweb_collector.adapters.changan.get_db_connection", return_value=nullcontext(object())),
                patch("darkweb_collector.adapters.changan.get_forum_topic_snapshot", return_value={"content_hash": first["content_hash"]}),
                patch("darkweb_collector.adapters.changan.get_forum_detail_snapshot", return_value={"id": 1}),
            ):
                self.assertEqual(adapter.plan_details(one_seed, config), [])
                changed = deepcopy(one_seed)
                changed.payload["sections"][0]["topics"][0]["content_hash"] = "changed"
                self.assertEqual(len(adapter.plan_details(changed, config)), 1)

    def test_direct_run_marks_auth_requirement_as_skipped(self):
        config = _config(Path("output/changan"))
        auth_error = SiteAuthenticationRequired("changan", "尚未完成账号登录")
        with (
            patch("darkweb_collector.orchestrator.get_site_config", return_value=config),
            patch("darkweb_collector.orchestrator.mark_job_running"),
            patch("darkweb_collector.orchestrator.execute_seed_job", side_effect=auth_error),
            patch("darkweb_collector.orchestrator.mark_job_finished") as mark_finished,
        ):
            from darkweb_collector.orchestrator import run_site_once

            result = run_site_once("changan", state_store=Mock())
        self.assertEqual(result["reason"], "auth_required")
        self.assertEqual(mark_finished.call_args.kwargs["status"], "skipped")

    def test_repository_config_has_no_credentials_or_monitoring_terms(self):
        config = get_site_config("changan", Path(__file__).parents[1] / "sites.yaml")
        self.assertTrue(config.enabled)
        self.assertEqual(config.effective_interval_seconds, 1800)
        self.assertEqual(config.max_topics_per_run, 30)
        self.assertEqual(config.max_detail_pages_per_run, 15)
        forbidden = {"username", "password", "account", "credentials", "monitoring_keywords"}
        self.assertFalse(forbidden.intersection(config.extras))


if __name__ == "__main__":
    unittest.main()
