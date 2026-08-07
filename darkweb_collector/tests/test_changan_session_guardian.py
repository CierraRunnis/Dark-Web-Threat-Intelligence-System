from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from darkweb_collector.adapters.changan import ChanganAdapter
from darkweb_collector.models import SiteConfig
from darkweb_collector.orchestrator import enqueue_due_sites
from darkweb_collector.site_auth import site_auth_readiness


BASE_URL = "http://example.onion"


def _config(output_dir: Path) -> SiteConfig:
    return SiteConfig(
        site_name="changan",
        enabled=True,
        seed_urls=(f"{BASE_URL}/#/home",),
        seed_fetch_mode="tor_http",
        detail_fetch_mode="browser",
        profile="hot",
        max_topics_per_run=30,
        max_detail_pages_per_run=15,
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


class _StateStore:
    def claim_seed_slot(self, site_name: str, ttl_seconds: int) -> bool:
        return True


class ChanganSessionGuardianTests(unittest.TestCase):
    def test_expired_session_hint_marks_saved_token_unavailable(self):
        with TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "storage_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "origins": [
                            {
                                "origin": BASE_URL,
                                "localStorage": [{"name": "token", "value": "saved-token"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = _config(Path(temp_dir) / "output")
            with (
                patch("darkweb_collector.site_auth.get_db_connection", return_value=nullcontext(object())),
                patch(
                    "darkweb_collector.site_auth.get_platform_session",
                    return_value={"status": "valid", "expires_hint": "2000-01-01T00:00:00+00:00"},
                ),
                patch("darkweb_collector.site_auth.resolve_platform_storage_state_path", return_value=state_path),
            ):
                readiness = site_auth_readiness(config)

        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["auth_status"], "expired")
        self.assertEqual(readiness["token"], "")

    def test_scheduler_recovers_invalid_session_before_due_job_checks(self):
        config = _config(Path("output"))
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        with (
            patch("darkweb_collector.orchestrator.get_db_connection", return_value=nullcontext(connection)),
            patch("darkweb_collector.orchestrator.load_site_configs", return_value=[config]),
            patch(
                "darkweb_collector.orchestrator.site_auth_readiness",
                side_effect=[
                    {"ready": False, "auth_message": "session expired"},
                    {"ready": True},
                ],
            ),
            patch("darkweb_collector.orchestrator.changan_auto_login_available", return_value=True),
            patch("darkweb_collector.orchestrator.recover_changan_session", return_value=True) as recover,
            patch("darkweb_collector.orchestrator.get_active_crawl_job", return_value=None),
            patch(
                "darkweb_collector.orchestrator.get_last_successful_crawl_job",
                return_value={"finished_at": datetime.now(timezone.utc).isoformat()},
            ),
        ):
            dispatched = enqueue_due_sites(
                seed_dispatcher=lambda _config: "should-not-run",
                state_store=_StateStore(),
            )

        self.assertEqual(dispatched, [])
        recover.assert_called_once_with(config, "session expired")

    def test_scheduler_does_not_login_when_session_is_ready(self):
        config = _config(Path("output"))
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = []
        with (
            patch("darkweb_collector.orchestrator.get_db_connection", return_value=nullcontext(connection)),
            patch("darkweb_collector.orchestrator.load_site_configs", return_value=[config]),
            patch("darkweb_collector.orchestrator.site_auth_readiness", return_value={"ready": True}),
            patch("darkweb_collector.orchestrator.recover_changan_session") as recover,
            patch("darkweb_collector.orchestrator.get_active_crawl_job", return_value=None),
            patch(
                "darkweb_collector.orchestrator.get_last_successful_crawl_job",
                return_value={"finished_at": datetime.now(timezone.utc).isoformat()},
            ),
        ):
            dispatched = enqueue_due_sites(
                seed_dispatcher=lambda _config: "should-not-run",
                state_store=_StateStore(),
            )

        self.assertEqual(dispatched, [])
        recover.assert_not_called()

    def test_auth_api_retries_once_after_automatic_login(self):
        adapter = ChanganAdapter()
        config = _config(Path("output"))
        expired = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"code": 4009, "msg": "InvalidAuthorization"}).encode(),
            stderr=b"",
        )
        recovered = SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"code": 2000, "data": {"goods": []}}).encode(),
            stderr=b"",
        )
        with (
            patch(
                "darkweb_collector.adapters.changan.require_site_auth_token",
                side_effect=[("expired-token", "state.json"), ("fresh-token", "state.json")],
            ),
            patch("darkweb_collector.adapters.changan.shutil.which", return_value="curl"),
            patch("darkweb_collector.adapters.changan.get_tor_socks_settings", return_value=("127.0.0.1", 9050)),
            patch("darkweb_collector.adapters.changan.subprocess.run", side_effect=[expired, recovered]),
            patch("darkweb_collector.adapters.changan.mark_site_auth_invalid"),
            patch("darkweb_collector.adapters.changan.recover_changan_session", return_value=True) as recover,
        ):
            payload = adapter._api_get(config, "/api/category/goods")

        self.assertEqual(payload["code"], 2000)
        recover.assert_called_once_with(config, "InvalidAuthorization")


if __name__ == "__main__":
    unittest.main()
