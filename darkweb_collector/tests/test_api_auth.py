from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
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

    def test_login_uses_default_password_when_no_config_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_AUTH_PASSWORD": "",
                    "DARKWEB_AUTH_PASSWORD_FILE": "",
                    "LOCALAPPDATA": temp_dir,
                    "USERPROFILE": temp_dir,
                },
                clear=False,
            ):
                client = TestClient(app)
                wrong = client.post("/api/auth/login", json={"username": "admin", "password": "anything"})
                self.assertEqual(401, wrong.status_code)

                response = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
                self.assertEqual(200, response.status_code)

    def test_login_uses_password_file_when_env_password_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            password_file = Path(temp_dir) / "auth-password.txt"
            password_file.write_text("file-password\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_AUTH_PASSWORD": "",
                    "DARKWEB_AUTH_PASSWORD_FILE": str(password_file),
                },
                clear=False,
            ):
                client = TestClient(app)
                response = client.post("/api/auth/login", json={"username": "admin", "password": "file-password"})
                self.assertEqual(200, response.status_code)

    def test_login_uses_default_local_password_file_when_env_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            password_file = Path(temp_dir) / "DarkWebThreatIntel" / "auth-password.txt"
            password_file.parent.mkdir(parents=True)
            password_file.write_text("local-password\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_AUTH_PASSWORD": "",
                    "DARKWEB_AUTH_PASSWORD_FILE": "",
                    "LOCALAPPDATA": temp_dir,
                },
                clear=False,
            ):
                client = TestClient(app)
                response = client.post("/api/auth/login", json={"username": "admin", "password": "local-password"})
                self.assertEqual(200, response.status_code)

    def test_change_password_updates_password_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            password_file = Path(temp_dir) / "auth-password.txt"
            password_file.write_text("old-password", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_AUTH_PASSWORD": "",
                    "DARKWEB_AUTH_PASSWORD_FILE": str(password_file),
                },
                clear=False,
            ):
                client = TestClient(app)
                login = client.post("/api/auth/login", json={"username": "admin", "password": "old-password"})
                self.assertEqual(200, login.status_code)
                headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

                response = client.post(
                    "/api/auth/change-password",
                    headers=headers,
                    json={"current_password": "old-password", "new_password": "new-password"},
                )
                self.assertEqual(200, response.status_code)
                self.assertEqual("new-password", password_file.read_text(encoding="utf-8").strip())

                old_login = client.post("/api/auth/login", json={"username": "admin", "password": "old-password"})
                self.assertEqual(401, old_login.status_code)
                new_login = client.post("/api/auth/login", json={"username": "admin", "password": "new-password"})
                self.assertEqual(200, new_login.status_code)

    def test_change_password_rejects_wrong_current_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            password_file = Path(temp_dir) / "auth-password.txt"
            password_file.write_text("old-password", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DARKWEB_AUTH_PASSWORD": "",
                    "DARKWEB_AUTH_PASSWORD_FILE": str(password_file),
                },
                clear=False,
            ):
                client = TestClient(app)
                login = client.post("/api/auth/login", json={"username": "admin", "password": "old-password"})
                self.assertEqual(200, login.status_code)
                headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

                response = client.post(
                    "/api/auth/change-password",
                    headers=headers,
                    json={"current_password": "wrong-password", "new_password": "new-password"},
                )
                self.assertEqual(400, response.status_code)
                self.assertEqual("old-password", password_file.read_text(encoding="utf-8").strip())

    def test_change_password_rejects_environment_password(self) -> None:
        client = TestClient(app)
        login = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
        self.assertEqual(200, login.status_code)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            "/api/auth/change-password",
            headers=headers,
            json={"current_password": "test-password", "new_password": "new-password"},
        )
        self.assertEqual(409, response.status_code)


if __name__ == "__main__":
    unittest.main()
