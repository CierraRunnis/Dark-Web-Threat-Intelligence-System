from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from darkweb_collector.api_app import _auth_sessions, app


class ApiAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        _auth_sessions.clear()
        self._auth_env = patch.dict(os.environ, {"DARKWEB_AUTH_PASSWORD": "test-password"}, clear=False)
        self._auth_env.start()
        self.addCleanup(self._auth_env.stop)

    def test_default_admin_login_session_and_logout(self) -> None:
        client = TestClient(app)

        self.assertEqual(200, client.get("/api/health").status_code)
        self.assertEqual(401, client.get("/api/jobs").status_code)

        wrong_login = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        self.assertEqual(401, wrong_login.status_code)

        login = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
        self.assertEqual(200, login.status_code)
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = client.get("/api/auth/me", headers=headers)
        self.assertEqual(200, me.status_code)
        self.assertEqual("admin", me.json()["username"])

        logout = client.post("/api/auth/logout", headers=headers)
        self.assertEqual(200, logout.status_code)
        self.assertEqual(401, client.get("/api/auth/me", headers=headers).status_code)

    def test_login_requires_configured_password(self) -> None:
        with patch.dict(os.environ, {"DARKWEB_AUTH_PASSWORD": ""}, clear=False):
            client = TestClient(app)
            response = client.post("/api/auth/login", json={"username": "admin", "password": "anything"})
            self.assertEqual(503, response.status_code)


if __name__ == "__main__":
    unittest.main()
