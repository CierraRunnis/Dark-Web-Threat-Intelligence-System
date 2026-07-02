from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
from unittest.mock import patch
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.tor_bridge_control import (
    DEFAULT_MEEK_LITE_BRIDGE,
    DEFAULT_OBFS4_BRIDGE,
    DEFAULT_SNOWFLAKE_BRIDGE,
    active_socks_settings,
    build_torrc,
    load_tor_bridge_settings,
    save_tor_bridge_settings,
    write_torrc,
)
from darkweb_collector.tor_fetch import get_tor_socks_settings


class TorBridgeControlTests(unittest.TestCase):
    def test_snowflake_profile_uses_builtin_bridge_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {"DARKWEB_TOR_BRIDGE_SETTINGS_PATH": str(Path(tmp_dir) / "settings.json")},
            clear=True,
        ):
            save_tor_bridge_settings(
                {
                    "enabled": True,
                    "bridge_mode": "snowflake",
                    "socks_port": 19050,
                    "data_directory": str(Path(tmp_dir) / "runtime"),
                }
            )
            settings = load_tor_bridge_settings()
            torrc = build_torrc(settings)

        self.assertIn("UseBridges 1", torrc)
        self.assertIn("SocksPort 127.0.0.1:19050", torrc)
        self.assertIn(DEFAULT_SNOWFLAKE_BRIDGE, torrc)

    def test_obfs4_profile_uses_builtin_bridge_when_empty(self) -> None:
        settings = {
            "enabled": True,
            "bridge_mode": "obfs4",
            "tor_executable": "/usr/bin/tor",
            "transport_executable": "/usr/bin/lyrebird",
            "socks_host": "127.0.0.1",
            "socks_port": 9050,
            "bridge_lines": [],
            "extra_torrc_lines": [],
            "data_directory": "/tmp/darkweb-tor-test",
        }
        torrc = build_torrc(settings)

        self.assertIn("ClientTransportPlugin obfs4 exec /usr/bin/lyrebird", torrc)
        self.assertIn(DEFAULT_OBFS4_BRIDGE, torrc)

    def test_meek_profile_uses_builtin_bridge_when_empty(self) -> None:
        settings = {
            "enabled": True,
            "bridge_mode": "meek_lite",
            "tor_executable": "/usr/bin/tor",
            "transport_executable": "/usr/bin/lyrebird",
            "socks_host": "127.0.0.1",
            "socks_port": 9050,
            "bridge_lines": [],
            "extra_torrc_lines": [],
            "data_directory": "/tmp/darkweb-tor-test",
        }
        torrc = build_torrc(settings)

        self.assertIn("ClientTransportPlugin meek_lite exec /usr/bin/lyrebird", torrc)
        self.assertIn(DEFAULT_MEEK_LITE_BRIDGE, torrc)

    def test_obfs4_lines_are_normalized_and_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {"DARKWEB_TOR_BRIDGE_SETTINGS_PATH": str(Path(tmp_dir) / "settings.json")},
            clear=True,
        ):
            save_tor_bridge_settings(
                {
                    "enabled": True,
                    "bridge_mode": "obfs4",
                    "transport_executable": str(Path(tmp_dir) / "lyrebird.exe"),
                    "bridge_lines": ["obfs4 1.2.3.4:443 ABCDEF cert=fake iat-mode=0"],
                    "data_directory": str(Path(tmp_dir) / "runtime"),
                }
            )
            torrc_path = write_torrc()
            torrc = torrc_path.read_text(encoding="utf-8")

        self.assertIn("ClientTransportPlugin obfs4 exec", torrc)
        self.assertIn("Bridge obfs4 1.2.3.4:443 ABCDEF cert=fake iat-mode=0", torrc)

    def test_snowflake_uses_relative_lyrebird_path_for_tor_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tor_dir = Path(tmp_dir) / "Tor Browser" / "Browser" / "TorBrowser" / "Tor"
            settings = {
                "enabled": True,
                "bridge_mode": "snowflake",
                "tor_executable": str(tor_dir / "tor.exe"),
                "transport_executable": str(tor_dir / "PluggableTransports" / "lyrebird.exe"),
                "socks_host": "127.0.0.1",
                "socks_port": 9050,
                "bridge_lines": [],
                "extra_torrc_lines": [],
                "data_directory": str(Path(tmp_dir) / "runtime"),
            }
            torrc = build_torrc(settings)

        self.assertIn(r"ClientTransportPlugin snowflake exec PluggableTransports\lyrebird.exe", torrc)
        self.assertNotIn("-url https://snowflake-broker.torproject.net/", torrc)

    def test_linux_lyrebird_snowflake_does_not_get_snowflake_client_args(self) -> None:
        settings = {
            "enabled": True,
            "bridge_mode": "snowflake",
            "tor_executable": "/usr/bin/tor",
            "transport_executable": "/usr/bin/lyrebird",
            "socks_host": "127.0.0.1",
            "socks_port": 9050,
            "bridge_lines": [],
            "extra_torrc_lines": [],
            "data_directory": "/tmp/darkweb-tor-test",
        }
        torrc = build_torrc(settings)

        self.assertIn("ClientTransportPlugin snowflake exec /usr/bin/lyrebird", torrc)
        self.assertNotIn("-url https://snowflake-broker.torproject.net/", torrc)

    def test_invalid_socks_port_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {"DARKWEB_TOR_BRIDGE_SETTINGS_PATH": str(Path(tmp_dir) / "settings.json")},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                save_tor_bridge_settings({"enabled": True, "socks_port": 70000})

    def test_enabled_profile_becomes_collector_socks_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {"DARKWEB_TOR_BRIDGE_SETTINGS_PATH": str(Path(tmp_dir) / "settings.json")},
            clear=True,
        ):
            save_tor_bridge_settings({"enabled": True, "socks_port": 19051})
            self.assertEqual(("127.0.0.1", 19051), active_socks_settings())
            self.assertEqual(("127.0.0.1", 19051), get_tor_socks_settings())


if __name__ == "__main__":
    unittest.main()
