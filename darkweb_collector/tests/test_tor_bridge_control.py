from __future__ import annotations

import os
import socket
import tempfile
import unittest
from pathlib import Path

from darkweb_collector.tor_bridge_control import (
    build_torrc,
    load_tor_bridge_settings,
    save_tor_bridge_settings,
    start_tor_bridge,
    stop_tor_bridge,
    _client_transport_plugin,
    _validate_start_inputs,
)


def _settings(**overrides):
    settings = {
        "enabled": True,
        "bridge_mode": "snowflake",
        "tor_executable": "",
        "transport_executable": "",
        "socks_host": "127.0.0.1",
        "socks_port": 9050,
        "bridge_lines": [],
        "extra_torrc_lines": [],
        "data_directory": "",
    }
    settings.update(overrides)
    return settings


class TorBridgeControlTests(unittest.TestCase):
    def test_missing_tor_executable_is_rejected_before_process_start(self):
        with self.assertRaisesRegex(RuntimeError, "Tor executable was not found"):
            _validate_start_inputs(_settings())

    def test_missing_transport_plugin_is_reported_for_builtin_snowflake(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tor_path = Path(temp_dir) / "tor"
            tor_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            os.chmod(tor_path, 0o755)

            with self.assertRaisesRegex(RuntimeError, "transport plugin"):
                _validate_start_inputs(_settings(tor_executable=str(tor_path)))

    def test_snowflake_transport_uses_bridge_line_parameters(self):
        plugin = _client_transport_plugin(
            _settings(transport_executable="/usr/bin/snowflake-client"),
            {"snowflake_log_path": "/tmp/snowflake.log"},
        )

        self.assertIn("ClientTransportPlugin snowflake exec", plugin)
        self.assertIn("-log /tmp/snowflake.log", plugin)
        self.assertNotIn("-url", plugin)
        self.assertNotIn("-front", plugin)

    def test_torrc_includes_status_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            torrc = build_torrc(_settings(data_directory=temp_dir))

        self.assertIn("Log notice file ", torrc)
        self.assertIn("tor.log", torrc)

    def test_load_settings_uses_runtime_path_environment(self):
        old_settings_path = os.environ.get("DARKWEB_TOR_BRIDGE_SETTINGS_PATH")
        old_tor = os.environ.get("DARKWEB_TOR_EXECUTABLE")
        old_transport = os.environ.get("DARKWEB_TOR_TRANSPORT_EXECUTABLE")
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.environ["DARKWEB_TOR_BRIDGE_SETTINGS_PATH"] = str(Path(temp_dir) / "settings.json")
                os.environ["DARKWEB_TOR_EXECUTABLE"] = str(Path(temp_dir) / "tor.exe")
                os.environ["DARKWEB_TOR_TRANSPORT_EXECUTABLE"] = str(Path(temp_dir) / "snowflake-client.exe")

                settings = load_tor_bridge_settings()
            finally:
                for name, value in {
                    "DARKWEB_TOR_BRIDGE_SETTINGS_PATH": old_settings_path,
                    "DARKWEB_TOR_EXECUTABLE": old_tor,
                    "DARKWEB_TOR_TRANSPORT_EXECUTABLE": old_transport,
                }.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value

        self.assertTrue(settings["tor_executable"].endswith("tor.exe"))
        self.assertTrue(settings["transport_executable"].endswith("snowflake-client.exe"))

    def test_start_rejects_busy_socks_port_before_process_start(self):
        old_settings_path = os.environ.get("DARKWEB_TOR_BRIDGE_SETTINGS_PATH")
        with tempfile.TemporaryDirectory() as temp_dir, socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                os.environ["DARKWEB_TOR_BRIDGE_SETTINGS_PATH"] = str(Path(temp_dir) / "settings.json")
                tor_path = Path(temp_dir) / "tor"
                transport_path = Path(temp_dir) / "snowflake-client"
                tor_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                transport_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                os.chmod(tor_path, 0o755)
                os.chmod(transport_path, 0o755)
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                busy_port = listener.getsockname()[1]

                save_tor_bridge_settings(
                    _settings(
                        tor_executable=str(tor_path),
                        transport_executable=str(transport_path),
                        socks_port=busy_port,
                        data_directory=str(Path(temp_dir) / "runtime"),
                    )
                )

                with self.assertRaisesRegex(RuntimeError, "already in use"):
                    start_tor_bridge()
            finally:
                stop_tor_bridge()
                if old_settings_path is None:
                    os.environ.pop("DARKWEB_TOR_BRIDGE_SETTINGS_PATH", None)
                else:
                    os.environ["DARKWEB_TOR_BRIDGE_SETTINGS_PATH"] = old_settings_path


if __name__ == "__main__":
    unittest.main()
