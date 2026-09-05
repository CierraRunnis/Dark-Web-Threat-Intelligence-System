from __future__ import annotations

from pathlib import Path
import os
import socket
import sys
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector import ransomware_live
from darkweb_collector.ransomware_live import _IPv6FirstHTTPSConnection


class _FakeSocket:
    def __init__(self, address: tuple[str, int]) -> None:
        self.address = address
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeSSLContext:
    def __init__(self, *, fail_ipv4: bool = False) -> None:
        self.fail_ipv4 = fail_ipv4
        self.server_names: list[str] = []

    def wrap_socket(self, sock: _FakeSocket, *, server_hostname: str) -> _FakeSocket:
        self.server_names.append(server_hostname)
        if ":" in sock.address[0] or self.fail_ipv4:
            raise TimeoutError(f"{sock.address[0]} TLS handshake timed out")
        return sock


class RansomwareLiveConnectionTests(unittest.TestCase):
    def _connect_with_fake_addresses(self, context: _FakeSSLContext) -> list[tuple[str, int]]:
        attempts: list[tuple[str, int]] = []

        def fake_getaddrinfo(host, port, family, socktype):
            if family == socket.AF_INET6:
                return [(family, socktype, 0, "", ("2001:db8::1", port, 0, 0))]
            if family == socket.AF_INET:
                return [(family, socktype, 0, "", ("149.202.86.189", port))]
            return []

        def fake_create_connection(address, timeout, source_address):
            attempts.append(address)
            return _FakeSocket(address)

        connection = _IPv6FirstHTTPSConnection("api-pro.ransomware.live", timeout=10)
        connection._context = context

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo), patch(
            "socket.create_connection", side_effect=fake_create_connection
        ):
            connection.connect()
        self.assertEqual(("149.202.86.189", 443), connection.sock.address)
        return attempts

    def test_connect_falls_back_to_ipv4_when_ipv6_tls_handshake_fails(self) -> None:
        context = _FakeSSLContext()
        attempts = self._connect_with_fake_addresses(context)
        self.assertEqual([("2001:db8::1", 443), ("149.202.86.189", 443)], attempts)
        self.assertEqual(["api-pro.ransomware.live", "api-pro.ransomware.live"], context.server_names)

    def test_connect_raises_after_ipv6_and_ipv4_both_fail(self) -> None:
        context = _FakeSSLContext(fail_ipv4=True)
        with self.assertRaisesRegex(TimeoutError, "149.202.86.189 TLS handshake timed out"):
            self._connect_with_fake_addresses(context)
        self.assertEqual(["api-pro.ransomware.live", "api-pro.ransomware.live"], context.server_names)


class RansomwareLiveProxySettingsTests(unittest.TestCase):
    def test_fetch_uses_unified_proxy_host_and_port(self) -> None:
        attempts: list[tuple[str, int]] = []

        def fake_request(request, *, timeout, proxy_port):
            attempts.append((ransomware_live._proxy_host(), proxy_port))
            return {"count": 1, "victims": []}

        with patch.dict(
            os.environ,
            {"PROXY_HOST": "127.0.0.1", "PROXY_PORT": "7892"},
        ), patch.object(ransomware_live, "get_ransomware_live_api_key", return_value="test-key"), patch.object(
            ransomware_live, "_request_json_via_proxy", side_effect=fake_request
        ):
            payload = ransomware_live._fetch_json("https://example.test", timeout=30)

        self.assertEqual(1, payload["count"])
        self.assertEqual([("127.0.0.1", 7892)], attempts)

    def test_missing_proxy_port_fails_closed(self) -> None:
        with patch.dict(
            os.environ,
            {"PROXY_HOST": "127.0.0.1", "PROXY_PORT": ""},
        ), patch.object(ransomware_live, "get_ransomware_live_api_key", return_value="test-key"):
            with self.assertRaisesRegex(RuntimeError, "PROXY_PORT is not set"):
                ransomware_live._fetch_json("https://example.test", timeout=30)

    def test_invalid_proxy_port_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"PROXY_HOST": "127.0.0.1", "PROXY_PORT": "invalid"},
        ), patch.object(ransomware_live, "get_ransomware_live_api_key", return_value="test-key"):
            with self.assertRaisesRegex(RuntimeError, "PROXY_PORT must be an integer"):
                ransomware_live._fetch_json("https://example.test", timeout=30)


if __name__ == "__main__":
    unittest.main()
