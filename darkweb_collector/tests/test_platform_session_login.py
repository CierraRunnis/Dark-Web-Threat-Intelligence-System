from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.document_exposure_platforms import ExposurePlatform
from darkweb_collector.document_exposure_sessions import _verify_gitee_code_search_capability, launch_platform_login
from darkweb_collector.platform_session_login import build_parser


class PlatformSessionLoginTests(unittest.TestCase):
    def test_login_worker_accepts_proxy_server_arg(self) -> None:
        args = build_parser().parse_args(
            [
                "--platform",
                "github",
                "--login-url",
                "https://github.com/login",
                "--homepage-url",
                "https://github.com/",
                "--user-data-dir",
                "/tmp/profile",
                "--storage-state",
                "/tmp/profile/storage_state.json",
                "--proxy-server",
                "http://127.0.0.1:7890",
            ]
        )

        self.assertEqual("http://127.0.0.1:7890", args.proxy_server)

    def test_launch_platform_login_passes_configured_proxy_to_worker(self) -> None:
        platform = ExposurePlatform(
            key="github",
            label="GitHub",
            module="code_monitoring",
            platform_type="code_repository",
            homepage_url="https://github.com/",
            login_url="https://github.com/login",
            domains=("github.com",),
            requires_login=True,
        )

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def commit(self) -> None:
                pass

        class FakeProcess:
            pid = 12345

        fake_playwright_module = types.ModuleType("playwright")
        fake_sync_api_module = types.ModuleType("playwright.sync_api")
        fake_sync_api_module.sync_playwright = object()

        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "DARKWEB_COLLECTOR_OUTPUT_ROOT": tmp_dir,
                "PROXY_HOST": "127.0.0.1",
                "PROXY_PORT": "7890",
            },
            clear=False,
        ), patch.dict(
            sys.modules,
            {
                "playwright": fake_playwright_module,
                "playwright.sync_api": fake_sync_api_module,
            },
            clear=False,
        ), patch(
            "darkweb_collector.document_exposure_sessions.get_exposure_platform",
            return_value=platform,
        ), patch(
            "darkweb_collector.document_exposure_sessions._is_process_alive",
            return_value=False,
        ), patch(
            "darkweb_collector.document_exposure_sessions.get_db_connection",
            return_value=FakeConnection(),
        ), patch(
            "darkweb_collector.document_exposure_sessions.upsert_platform_session",
        ), patch(
            "darkweb_collector.document_exposure_sessions.subprocess.Popen",
            return_value=FakeProcess(),
        ) as popen:
            payload = launch_platform_login("github")

            command = popen.call_args.args[0]
            self.assertIn("--proxy-server", command)
            self.assertEqual("http://127.0.0.1:7890", command[command.index("--proxy-server") + 1])
            self.assertEqual("http://127.0.0.1:7890", payload["proxy_server"])

            metadata_path = Path(tmp_dir) / "platform_sessions" / "github" / "launch_meta.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual("http://127.0.0.1:7890", metadata["proxy_server"])


    def test_gitee_verification_uses_configured_http_proxy(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"hits":{"total":{"value":1,"relation":"eq"}}}'

            def geturl(self) -> str:
                return "https://so.gitee.com/v1/search/widget/test"

        class FakeOpener:
            def open(self, request, timeout=0):
                self.request = request
                self.timeout = timeout
                return FakeResponse()

        fake_opener = FakeOpener()
        with patch.dict(
            os.environ,
            {"PROXY_HOST": "127.0.0.1", "PROXY_PORT": "10808"},
            clear=False,
        ), patch(
            "darkweb_collector.document_exposure_sessions.build_opener",
            return_value=fake_opener,
        ) as build_opener, patch(
            "darkweb_collector.document_exposure_sessions.urlopen",
        ) as urlopen:
            result = _verify_gitee_code_search_capability()

        self.assertTrue(result["valid"])
        build_opener.assert_called_once()
        urlopen.assert_not_called()
        self.assertEqual(30, fake_opener.timeout)



if __name__ == "__main__":
    unittest.main()
