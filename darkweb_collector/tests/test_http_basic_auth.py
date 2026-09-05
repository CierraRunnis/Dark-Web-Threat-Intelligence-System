from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.basic_auth_app import HttpBasicGateMiddleware
from darkweb_collector.http_basic_auth import validate_http_basic_auth_config


def _test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/gate")
    def gate() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/protected")
    def protected(request: Request) -> dict[str, bool]:
        if request.headers.get("authorization") != "Bearer app-token":
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="application login required")
        return {"ok": True}

    @app.get("/api/ai/intelligence")
    def ai_intelligence() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(HttpBasicGateMiddleware)
    return app


class HttpBasicAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patch = patch.dict(
            os.environ,
            {
                "DARKWEB_BASIC_AUTH_ENABLED": "1",
                "DARKWEB_BASIC_AUTH_USERNAME": "outer-user",
                "DARKWEB_BASIC_AUTH_PASSWORD": "outer-secret",
                "DARKWEB_BASIC_AUTH_REALM": "Test Realm",
                "DARKWEB_BASIC_AUTH_TTL_SECONDS": "600",
                "DARKWEB_SKIP_API_WARMUP": "1",
            },
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()

    def test_enabled_config_requires_a_non_default_password(self) -> None:
        with patch.dict(os.environ, {"DARKWEB_BASIC_AUTH_PASSWORD": "", "DARKWEB_AUTH_PASSWORD": ""}):
            with self.assertRaises(RuntimeError):
                validate_http_basic_auth_config()

    def test_missing_credentials_receive_a_standard_basic_challenge(self) -> None:
        with TestClient(_test_app()) as client:
            response = client.get("/gate")

        self.assertEqual(401, response.status_code)
        self.assertEqual(
            'Basic realm="Test Realm", charset="UTF-8"',
            response.headers["www-authenticate"],
        )

    def test_basic_gate_cookie_and_application_bearer_can_coexist(self) -> None:
        with TestClient(_test_app()) as client:
            gate_response = client.get("/gate", auth=("outer-user", "outer-secret"))
            protected_response = client.get(
                "/api/protected",
                headers={"Authorization": "Bearer app-token"},
            )

        self.assertEqual(200, gate_response.status_code)
        self.assertIn("dwti_basic_gate=", gate_response.headers["set-cookie"])
        self.assertIn("HttpOnly", gate_response.headers["set-cookie"])
        self.assertEqual(200, protected_response.status_code)

    def test_bearer_without_gate_cookie_is_rejected_by_outer_layer(self) -> None:
        with TestClient(_test_app()) as client:
            response = client.get(
                "/api/protected",
                headers={"Authorization": "Bearer app-token"},
            )

        self.assertEqual(401, response.status_code)
        self.assertIn("Basic realm=", response.headers["www-authenticate"])

    def test_ai_intelligence_bypasses_outer_basic_gate(self) -> None:
        with TestClient(_test_app()) as client:
            response = client.get("/api/ai/intelligence")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True}, response.json())


if __name__ == "__main__":
    unittest.main()
