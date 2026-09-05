from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.config import ConfigError, load_site_configs


class ConfigTests(unittest.TestCase):
    def test_duplicate_site_names_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "sites.yaml"
            config_path.write_text(
                json.dumps(
                    {
                        "sites": [
                            {
                                "site_name": "dup",
                                "enabled": True,
                                "seed_urls": ["http://example.onion/"],
                                "seed_fetch_mode": "tor_http",
                                "detail_fetch_mode": "tor_http",
                                "profile": "hot",
                                "max_topics_per_run": 1,
                                "max_detail_pages_per_run": 1,
                                "cooldown_seconds": 60,
                                "output_dir": str(Path(tmp_dir) / "out1"),
                                "dedupe_window_minutes": 5,
                            },
                            {
                                "site_name": "dup",
                                "enabled": True,
                                "seed_urls": ["http://example2.onion/"],
                                "seed_fetch_mode": "tor_http",
                                "detail_fetch_mode": "tor_http",
                                "profile": "warm",
                                "max_topics_per_run": 1,
                                "max_detail_pages_per_run": 1,
                                "cooldown_seconds": 60,
                                "output_dir": str(Path(tmp_dir) / "out2"),
                                "dedupe_window_minutes": 5,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_site_configs(config_path)

    def test_invalid_fetch_mode_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "sites.yaml"
            config_path.write_text(
                json.dumps(
                    {
                        "sites": [
                            {
                                "site_name": "alpha",
                                "enabled": True,
                                "seed_urls": ["http://example.onion/"],
                                "seed_fetch_mode": "invalid_mode",
                                "detail_fetch_mode": "tor_http",
                                "profile": "hot",
                                "max_topics_per_run": 1,
                                "max_detail_pages_per_run": 1,
                                "cooldown_seconds": 60,
                                "output_dir": str(Path(tmp_dir) / "out"),
                                "dedupe_window_minutes": 5,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError):
                load_site_configs(config_path)
