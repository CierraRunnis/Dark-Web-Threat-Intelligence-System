from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from darkweb_collector.tor_bridge_control import (
    _find_external_tor_pid,
    _parse_bootstrap_log,
    _parse_exit_ip_payload,
    _runtime_errors,
    load_tor_bridge_settings,
)


def _executable(path: Path) -> str:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(path, 0o755)
    return str(path)


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
    def test_bootstrap_parser_uses_latest_progress_line(self):
        details = _parse_bootstrap_log(
            "\n".join(
                [
                    "Bootstrapped 100% (done): Done",
                    "Bootstrapped 10% (conn_done): Connected to a relay",
                    "Bootstrapped 30% (loading_status): Loading networkstatus consensus",
                ]
            )
        )

        self.assertEqual(details["bootstrap_percent"], 30)
        self.assertEqual(details["bootstrap_stage"], "loading_status")
        self.assertEqual(details["bootstrap_summary"], "Loading networkstatus consensus")
        self.assertNotEqual(details["bootstrap_status"], "done")

    def test_bootstrap_parser_marks_100_percent_as_done(self):
        details = _parse_bootstrap_log("Bootstrapped 100% (done): Done")

        self.assertEqual(details["bootstrap_percent"], 100)
        self.assertEqual(details["bootstrap_status"], "done")

    def test_meek_requires_lyrebird_instead_of_obfs4proxy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            errors = _runtime_errors(
                _settings(
                    bridge_mode="meek_lite",
                    tor_executable=_executable(root / "tor"),
                    transport_executable=_executable(root / "obfs4proxy"),
                )
            )

        self.assertTrue(any("lyrebird" in error.lower() for error in errors))

    def test_explicit_runtime_environment_overrides_saved_obsolete_runtime(self):
        names = (
            "DARKWEB_TOR_BRIDGE_SETTINGS_PATH",
            "DARKWEB_TOR_EXECUTABLE",
            "DARKWEB_TOR_TRANSPORT_EXECUTABLE",
        )
        previous = {name: os.environ.get(name) for name in names}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            old_tor = _executable(root / "old-tor")
            old_transport = _executable(root / "obfs4proxy")
            new_tor = _executable(root / "darkweb-tor")
            new_transport = _executable(root / "lyrebird")
            settings_path.write_text(
                json.dumps(
                    _settings(
                        bridge_mode="meek_lite",
                        tor_executable=old_tor,
                        transport_executable=old_transport,
                    )
                ),
                encoding="utf-8",
            )
            try:
                os.environ["DARKWEB_TOR_BRIDGE_SETTINGS_PATH"] = str(settings_path)
                os.environ["DARKWEB_TOR_EXECUTABLE"] = new_tor
                os.environ["DARKWEB_TOR_TRANSPORT_EXECUTABLE"] = new_transport

                settings = load_tor_bridge_settings()
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value

        self.assertEqual(settings["tor_executable"], new_tor)
        self.assertEqual(settings["transport_executable"], new_transport)

    def test_exit_ip_payload_requires_tor_and_valid_ip(self):
        self.assertEqual(_parse_exit_ip_payload({"IsTor": True, "IP": "185.220.101.1"}), "185.220.101.1")
        with self.assertRaisesRegex(RuntimeError, "not using Tor"):
            _parse_exit_ip_payload({"IsTor": False, "IP": "203.0.113.1"})
        with self.assertRaisesRegex(RuntimeError, "invalid IP"):
            _parse_exit_ip_payload({"IsTor": True, "IP": "not-an-ip"})

    def test_external_process_is_recovered_after_api_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings(data_directory=temp_dir)
            with patch(
                "darkweb_collector.tor_bridge_control._pid_matches_runtime",
                side_effect=lambda pid, _: pid == 4242,
            ):
                Path(temp_dir, "tor.pid").write_text("4242", encoding="ascii")
                self.assertEqual(_find_external_tor_pid(settings), 4242)


if __name__ == "__main__":
    unittest.main()
