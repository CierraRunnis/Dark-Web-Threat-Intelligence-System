from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import darkweb_collector.api_app as api_app
from darkweb_collector.auth_accounts import (
    ASSIGNABLE_MODULES,
    get_account,
    normalize_modules,
    verify_password,
)


def _request(user: dict[str, object]) -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/auth/accounts",
            "raw_path": b"/api/auth/accounts",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )
    request.state.current_user = user
    return request


def _authorized_request(path: str, token: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode("utf-8"))],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )


async def _ok_call_next(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


class AuthAccountsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {
                "DARKWEB_AUTH_ACCOUNTS_DB": str(Path(self.tmp_dir.name) / "auth-accounts.db"),
                "DARKWEB_AUTH_USERNAME": "rootadmin",
                "DARKWEB_AUTH_PASSWORD": "root-secret",
                "DARKWEB_SKIP_API_WARMUP": "1",
            },
            clear=False,
        )
        self.env_patch.start()
        with api_app._auth_lock:
            api_app._auth_sessions.clear()

    def tearDown(self) -> None:
        with api_app._auth_lock:
            api_app._auth_sessions.clear()
        self.env_patch.stop()
        self.tmp_dir.cleanup()

    def test_current_configured_account_is_fixed_admin_with_every_module(self) -> None:
        payload = api_app.auth_login(
            api_app.AuthLoginRequest(username="rootadmin", password="root-secret")
        )

        self.assertEqual("admin", payload["user"]["role"])
        self.assertTrue(payload["user"]["is_admin"])
        self.assertTrue(payload["user"]["fixed"])
        self.assertEqual(list(ASSIGNABLE_MODULES), payload["user"]["modules"])

    def test_admin_can_create_update_and_disable_an_account(self) -> None:
        admin_request = _request(api_app._admin_user_payload())
        created = api_app.auth_account_create(
            admin_request,
            api_app.AuthAccountCreateRequest(
                username="analyst01",
                display_name="分析员",
                password="analyst-secret",
                modules=["ransomware", "file_monitoring"],
            ),
        )

        self.assertEqual(["ransomware", "file_monitoring"], created["modules"])
        stored = get_account("analyst01", include_password=True)
        self.assertIsNotNone(stored)
        self.assertNotEqual("analyst-secret", stored["password_hash"])
        self.assertTrue(verify_password("analyst-secret", str(stored["password_hash"])))

        login_payload = api_app.auth_login(
            api_app.AuthLoginRequest(username="analyst01", password="analyst-secret")
        )
        token = str(login_payload["access_token"])
        self.assertEqual("user", login_payload["user"]["role"])
        self.assertEqual(["ransomware", "file_monitoring"], login_payload["user"]["modules"])

        updated = api_app.auth_account_update(
            "analyst01",
            admin_request,
            api_app.AuthAccountUpdateRequest(
                display_name="值班分析员",
                modules=["data_leak"],
                enabled=False,
            ),
        )

        self.assertEqual(["data_leak"], updated["modules"])
        self.assertFalse(updated["enabled"])
        disabled_payload = get_account("analyst01")
        self.assertIsNotNone(disabled_payload)
        self.assertFalse(disabled_payload["enabled"])
        self.assertIsNone(api_app._get_auth_user(token))
        with self.assertRaises(HTTPException) as raised:
            api_app.auth_login(
                api_app.AuthLoginRequest(username="analyst01", password="analyst-secret")
            )
        self.assertEqual(401, raised.exception.status_code)

    def test_overview_is_fixed_and_not_an_assignable_permission(self) -> None:
        self.assertNotIn("dashboard", ASSIGNABLE_MODULES)
        self.assertNotIn("overview", ASSIGNABLE_MODULES)
        with self.assertRaises(ValueError):
            normalize_modules(["dashboard"])

    def test_non_admin_cannot_manage_accounts(self) -> None:
        ordinary_request = _request(
            {
                "username": "analyst01",
                "role": "user",
                "is_admin": False,
                "modules": [],
                "enabled": True,
            }
        )

        with self.assertRaises(HTTPException) as raised:
            api_app.auth_accounts(ordinary_request)
        self.assertEqual(403, raised.exception.status_code)

        with self.assertRaises(HTTPException) as profile_error:
            api_app.auth_account_profile_update(
                "analyst01",
                ordinary_request,
                api_app.AuthAccountProfileUpdateRequest(
                    username="analyst02",
                    display_name="分析员",
                ),
            )
        self.assertEqual(403, profile_error.exception.status_code)

        with self.assertRaises(HTTPException) as delete_error:
            api_app.auth_account_delete("analyst01", ordinary_request)
        self.assertEqual(403, delete_error.exception.status_code)

    def test_business_api_middleware_does_not_check_module_permissions(self) -> None:
        admin_request = _request(api_app._admin_user_payload())
        api_app.auth_account_create(
            admin_request,
            api_app.AuthAccountCreateRequest(
                username="overview-only",
                display_name="仅总览",
                password="overview-secret",
                modules=[],
            ),
        )
        login_payload = api_app.auth_login(
            api_app.AuthLoginRequest(username="overview-only", password="overview-secret")
        )

        response = asyncio.run(
            api_app.require_api_auth(
                _authorized_request("/api/intelligence", str(login_payload["access_token"])),
                _ok_call_next,
            )
        )

        self.assertEqual(200, response.status_code)

    def test_admin_can_edit_account_information_and_reset_password(self) -> None:
        admin_request = _request(api_app._admin_user_payload())
        api_app.auth_account_create(
            admin_request,
            api_app.AuthAccountCreateRequest(
                username="analyst01",
                display_name="分析员",
                password="analyst-secret",
                modules=["ransomware"],
            ),
        )
        login_payload = api_app.auth_login(
            api_app.AuthLoginRequest(username="analyst01", password="analyst-secret")
        )
        old_token = str(login_payload["access_token"])

        updated = api_app.auth_account_profile_update(
            "analyst01",
            admin_request,
            api_app.AuthAccountProfileUpdateRequest(
                username="analyst02",
                display_name="高级分析员",
                new_password="renewed-secret",
            ),
        )

        self.assertEqual("analyst02", updated["username"])
        self.assertEqual("高级分析员", updated["display_name"])
        self.assertEqual(["ransomware"], updated["modules"])
        self.assertIsNone(get_account("analyst01"))
        self.assertIsNone(api_app._get_auth_user(old_token))
        with self.assertRaises(HTTPException):
            api_app.auth_login(
                api_app.AuthLoginRequest(username="analyst02", password="analyst-secret")
            )
        relogin = api_app.auth_login(
            api_app.AuthLoginRequest(username="analyst02", password="renewed-secret")
        )
        self.assertEqual("analyst02", relogin["user"]["username"])

    def test_admin_can_delete_account_and_revoke_its_sessions(self) -> None:
        admin_request = _request(api_app._admin_user_payload())
        api_app.auth_account_create(
            admin_request,
            api_app.AuthAccountCreateRequest(
                username="temporary-user",
                display_name="临时账号",
                password="temporary-secret",
                modules=[],
            ),
        )
        login_payload = api_app.auth_login(
            api_app.AuthLoginRequest(username="temporary-user", password="temporary-secret")
        )
        token = str(login_payload["access_token"])

        result = api_app.auth_account_delete("temporary-user", admin_request)

        self.assertEqual({"ok": True}, result)
        self.assertIsNone(get_account("temporary-user"))
        self.assertIsNone(api_app._get_auth_user(token))
        with self.assertRaises(HTTPException) as raised:
            api_app.auth_login(
                api_app.AuthLoginRequest(username="temporary-user", password="temporary-secret")
            )
        self.assertEqual(401, raised.exception.status_code)

    def test_account_rename_rejects_an_existing_username(self) -> None:
        admin_request = _request(api_app._admin_user_payload())
        for username in ("analyst01", "analyst02"):
            api_app.auth_account_create(
                admin_request,
                api_app.AuthAccountCreateRequest(
                    username=username,
                    display_name=username,
                    password="analyst-secret",
                    modules=[],
                ),
            )

        with self.assertRaises(HTTPException) as raised:
            api_app.auth_account_profile_update(
                "analyst01",
                admin_request,
                api_app.AuthAccountProfileUpdateRequest(
                    username="analyst02",
                    display_name="分析员",
                ),
            )
        self.assertEqual(409, raised.exception.status_code)

    def test_admin_account_cannot_be_recreated_or_modified(self) -> None:
        admin_request = _request(api_app._admin_user_payload())
        with self.assertRaises(HTTPException) as create_error:
            api_app.auth_account_create(
                admin_request,
                api_app.AuthAccountCreateRequest(
                    username="ROOTADMIN",
                    password="another-secret",
                    modules=[],
                ),
            )
        self.assertEqual(409, create_error.exception.status_code)

        with self.assertRaises(HTTPException) as update_error:
            api_app.auth_account_update(
                "rootadmin",
                admin_request,
                api_app.AuthAccountUpdateRequest(display_name="other", modules=[], enabled=False),
            )
        self.assertEqual(409, update_error.exception.status_code)

        with self.assertRaises(HTTPException) as profile_error:
            api_app.auth_account_profile_update(
                "rootadmin",
                admin_request,
                api_app.AuthAccountProfileUpdateRequest(
                    username="other-admin",
                    display_name="other",
                ),
            )
        self.assertEqual(409, profile_error.exception.status_code)

        with self.assertRaises(HTTPException) as delete_error:
            api_app.auth_account_delete("rootadmin", admin_request)
        self.assertEqual(409, delete_error.exception.status_code)


if __name__ == "__main__":
    unittest.main()
