from __future__ import annotations

import os
from pathlib import Path
import sys
from unittest.mock import patch
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.code_monitoring import _http_get_json


class CodeMonitoringProxyTests(unittest.TestCase):
    def test_http_json_uses_configured_proxy(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"ok": true}'

            def geturl(self) -> str:
                return "https://api.github.com/test"

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
            "darkweb_collector.code_monitoring.build_opener",
            return_value=fake_opener,
        ) as build_opener, patch(
            "darkweb_collector.code_monitoring.urlopen",
        ) as urlopen:
            payload = _http_get_json(
                "https://api.github.com/test",
                headers={"User-Agent": "test"},
                timeout=12,
            )

        self.assertEqual({"ok": True}, payload)
        build_opener.assert_called_once()
        urlopen.assert_not_called()
        self.assertEqual(12, fake_opener.timeout)


if __name__ == "__main__":
    unittest.main()
