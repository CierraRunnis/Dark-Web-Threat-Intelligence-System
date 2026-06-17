from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.document_exposure_sessions import (
    platform_storage_state_path,
    verify_platform_session,
)


class DocumentExposureSessionTests(unittest.TestCase):
    def _env(self, db_path: Path, output_root: Path, config_path: Path) -> dict[str, str]:
        return {
            "DARKWEB_COLLECTOR_DB_PATH": str(db_path),
            "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_root),
            "DARKWEB_COLLECTOR_SITES_FILE": str(config_path),
        }

    def _write_empty_sites(self, path: Path) -> None:
        path.write_text(json.dumps({"sites": []}, ensure_ascii=False), encoding="utf-8")

    def test_verify_platform_session_marks_gitee_invalid_on_security_challenge(self) -> None:
        class FakeResponse:
            def __init__(self, body: str, url: str) -> None:
                self._body = body
                self._url = url

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return self._body.encode("utf-8")

            def geturl(self) -> str:
                return self._url

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            db_path = tmp_path / "collector.db"
            output_root = tmp_path / "output"
            config_path = tmp_path / "sites.json"
            self._write_empty_sites(config_path)

            with patch.dict(os.environ, self._env(db_path, output_root, config_path), clear=False):
                storage_state = platform_storage_state_path("gitee")
                storage_state.parent.mkdir(parents=True, exist_ok=True)
                storage_state.write_text("{}", encoding="utf-8")

                with patch(
                    "darkweb_collector.document_exposure_sessions.urlopen",
                    return_value=FakeResponse(
                        "<html><title>安全验证码-独立验证</title><body>verify you are human</body></html>",
                        "https://so.gitee.com/v1/search/widget/wong1slagnlmzwvsu5ya?q=readme&from=0&size=20",
                    ),
                ):
                    result = verify_platform_session("gitee")

                self.assertFalse(result["valid"])
                self.assertEqual("invalid", result["status"])
                self.assertIn("security verification", result["last_error"])
                self.assertEqual("gitee_widget_api", result["metadata"].get("verification_mode"))

