from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.tor_fetch import (
    browser_proxy_server_for_url,
    fetch_url,
    fetch_via_tor_curl,
    is_onion_url,
)


class FetchRoutingTests(unittest.TestCase):
    def test_is_onion_url_uses_hostname_not_scheme(self) -> None:
        self.assertTrue(is_onion_url("http://abc.onion/"))
        self.assertTrue(is_onion_url("https://abc.onion/path"))
        self.assertFalse(is_onion_url("https://darkforums.su/"))
        self.assertFalse(is_onion_url("http://example.com/"))

    def test_browser_proxy_server_matches_url_type(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TOR_SOCKS_HOST": "127.0.0.1",
                "TOR_SOCKS_PORT": "9150",
                "PROXY_HOST": "127.0.0.1",
                "PROXY_PORT": "7890",
            },
            clear=False,
        ):
            self.assertEqual("socks5://127.0.0.1:9150", browser_proxy_server_for_url("https://abc.onion/"))
            self.assertEqual("http://127.0.0.1:7890", browser_proxy_server_for_url("https://example.com/"))

    def test_fetch_url_routes_onion_to_tor(self) -> None:
        with patch("darkweb_collector.tor_fetch.fetch_via_tor_curl", return_value="ok") as tor_fetch, patch(
            "darkweb_collector.tor_fetch.fetch_via_http_proxy"
        ) as http_fetch:
            result = fetch_url(
                url="https://abc.onion/path",
                mode="tor_http",
                timeout_seconds=10,
            )
        self.assertEqual("ok", result)
        tor_fetch.assert_called_once()
        http_fetch.assert_not_called()

    def test_fetch_url_routes_http_mode_to_http_proxy(self) -> None:
        with patch("darkweb_collector.tor_fetch.fetch_via_http_proxy", return_value="ok") as http_fetch, patch(
            "darkweb_collector.tor_fetch.fetch_via_tor_curl"
        ) as tor_fetch:
            result = fetch_url(
                url="https://darkforums.su/thread",
                mode="http",
                timeout_seconds=10,
            )
        self.assertEqual("ok", result)
        http_fetch.assert_called_once()
        tor_fetch.assert_not_called()


    def test_fetch_via_tor_curl_uses_explicit_socks_proxy_without_noproxy(self) -> None:
        proxy_env = {
            "ALL_PROXY": "http://127.0.0.1:8888",
            "HTTPS_PROXY": "http://127.0.0.1:8888",
            "HTTP_PROXY": "http://127.0.0.1:8888",
            "NO_PROXY": "*",
            "all_proxy": "http://127.0.0.1:8888",
            "https_proxy": "http://127.0.0.1:8888",
            "http_proxy": "http://127.0.0.1:8888",
            "no_proxy": "*",
        }
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"ok", stderr=b"")
        with patch.dict("os.environ", proxy_env, clear=False), patch(
            "darkweb_collector.tor_fetch.shutil.which", return_value="/usr/bin/curl"
        ), patch("darkweb_collector.tor_fetch.subprocess.run", return_value=completed) as run:
            result = fetch_via_tor_curl(
                url="https://cracked.st/Forum-Other-Leaks",
                socks_host="127.0.0.1",
                socks_port=9150,
                timeout=10,
                retries=0,
            )

        self.assertEqual("ok", result)
        command = run.call_args.args[0]
        self.assertNotIn("--noproxy", command)
        self.assertIn("--proxy", command)
        self.assertEqual("socks5h://127.0.0.1:9150", command[command.index("--proxy") + 1])

        clean_env = run.call_args.kwargs["env"]
        for key in proxy_env:
            self.assertNotIn(key, clean_env)
    def test_fetch_url_routes_browser_by_url_type(self) -> None:
        with patch("darkweb_collector.browser_client.fetch_html_with_browser", return_value="ok") as browser_fetch, patch.dict(
            "os.environ",
            {
                "TOR_SOCKS_HOST": "127.0.0.1",
                "TOR_SOCKS_PORT": "9150",
                "PROXY_HOST": "127.0.0.1",
                "PROXY_PORT": "7890",
            },
            clear=False,
        ):
            fetch_url("https://abc.onion/path", mode="browser", timeout_seconds=10, render_wait_seconds=3)
            fetch_url("https://example.com/path", mode="browser", timeout_seconds=10, render_wait_seconds=3)

        proxy_servers = [call.kwargs["proxy_server"] for call in browser_fetch.call_args_list]
        self.assertEqual(["socks5://127.0.0.1:9150", "http://127.0.0.1:7890"], proxy_servers)
