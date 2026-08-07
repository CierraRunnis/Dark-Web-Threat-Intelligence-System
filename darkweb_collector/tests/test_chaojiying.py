from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from urllib.parse import parse_qs
import unittest
from unittest.mock import patch

from darkweb_collector.chaojiying import (
    ChaojiyingError,
    chaojiying_config_status,
    delete_chaojiying_config,
    load_chaojiying_credentials,
    recognize_captcha,
    report_recognition_error,
    save_chaojiying_config,
)
from darkweb_collector import remote_browser_sessions


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class ChaojiyingClientTests(unittest.TestCase):
    def test_shared_config_hashes_password_and_is_used_without_site_credentials(self):
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            return _Response({"err_no": 0, "pic_id": "pic-shared", "pic_str": "ab12"})

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "chaojiying.json"
            environment = {
                "DARKWEB_CHAOJIYING_CONFIG_FILE": str(config_path),
                "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(Path(temp_dir) / "output"),
            }
            with patch.dict(os.environ, environment, clear=True):
                status = save_chaojiying_config(
                    user="shared-user",
                    password="shared-password",
                    soft_id="1234",
                )
                stored_text = config_path.read_text(encoding="utf-8")
                stored = json.loads(stored_text)
                credentials = load_chaojiying_credentials()
                with patch("darkweb_collector.chaojiying.urlopen", side_effect=fake_urlopen):
                    recognize_captcha(b"png-bytes")

        expected_hash = hashlib.md5(b"shared-password").hexdigest()  # noqa: S324
        form = parse_qs(captured["request"].data.decode("ascii"))
        self.assertEqual(stored["DARKWEB_CHAOJIYING_PASS2"], expected_hash)
        self.assertNotIn("shared-password", stored_text)
        self.assertEqual(credentials.pass2, expected_hash)
        self.assertEqual(form["user"], ["shared-user"])
        self.assertEqual(form["pass2"], [expected_hash])
        self.assertTrue(status["configured"])
        self.assertNotIn("shared-user", repr(status))
        self.assertNotIn(expected_hash, repr(status))

    def test_shared_config_blank_fields_preserve_values_and_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "chaojiying.json"
            environment = {
                "DARKWEB_CHAOJIYING_CONFIG_FILE": str(config_path),
                "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(Path(temp_dir) / "output"),
            }
            with patch.dict(os.environ, environment, clear=True):
                save_chaojiying_config(user="shared-user", password="shared-password")
                preserved = save_chaojiying_config()
                credentials = load_chaojiying_credentials()
                deleted = delete_chaojiying_config()
                file_deleted = not config_path.exists()

        self.assertTrue(preserved["managedConfigured"])
        self.assertEqual(credentials.user, "shared-user")
        self.assertFalse(deleted["configured"])
        self.assertTrue(file_deleted)

    def test_environment_credentials_can_be_promoted_to_shared_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "chaojiying.json"
            environment = {
                "DARKWEB_CHAOJIYING_CONFIG_FILE": str(config_path),
                "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(Path(temp_dir) / "output"),
                "DARKWEB_CHAOJIYING_USER": "environment-user",
                "DARKWEB_CHAOJIYING_PASSWORD": "environment-password",
            }
            with patch.dict(os.environ, environment, clear=True):
                status = save_chaojiying_config()
                stored = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertTrue(status["managedConfigured"])
        self.assertEqual(stored["DARKWEB_CHAOJIYING_USER"], "environment-user")
        self.assertEqual(
            stored["DARKWEB_CHAOJIYING_PASS2"],
            hashlib.md5(b"environment-password").hexdigest(),  # noqa: S324
        )

    def test_saving_shared_config_migrates_legacy_changan_provider_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "output"
            legacy_path = output_path / "platform_sessions" / "changan" / "auto_login_credentials.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "DARKWEB_CHAOJIYING_USER": "legacy-user",
                        "DARKWEB_CHAOJIYING_PASS2": "0" * 32,
                        "DARKWEB_CHANGAN_USERNAME": "changan-user",
                        "DARKWEB_CHANGAN_PASSWORD": "changan-password",
                    }
                ),
                encoding="utf-8",
            )
            config_path = Path(temp_dir) / "chaojiying.json"
            environment = {
                "DARKWEB_CHAOJIYING_CONFIG_FILE": str(config_path),
                "DARKWEB_COLLECTOR_OUTPUT_ROOT": str(output_path),
            }
            with patch.dict(os.environ, environment, clear=True):
                status = save_chaojiying_config()
                migrated = json.loads(config_path.read_text(encoding="utf-8"))
                remaining = json.loads(legacy_path.read_text(encoding="utf-8"))

        self.assertTrue(status["configured"])
        self.assertEqual(migrated["DARKWEB_CHAOJIYING_USER"], "legacy-user")
        self.assertNotIn("DARKWEB_CHAOJIYING_USER", remaining)
        self.assertEqual(remaining["DARKWEB_CHANGAN_USERNAME"], "changan-user")

    def test_recognize_captcha_accepts_explicit_credentials_for_background_login(self):
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            return _Response({"err_no": 0, "pic_id": "pic-explicit", "pic_str": "18"})

        with patch.dict(os.environ, {}, clear=True), patch(
            "darkweb_collector.chaojiying.urlopen",
            side_effect=fake_urlopen,
        ):
            result = recognize_captcha(
                b"png-bytes",
                user="file-user",
                password="file-password",
                soft_id="1234",
                code_type="5000",
            )

        form = parse_qs(captured["request"].data.decode("ascii"))
        self.assertEqual(form["user"], ["file-user"])
        self.assertEqual(form["pass2"], [hashlib.md5(b"file-password").hexdigest()])  # noqa: S324
        self.assertEqual(form["softid"], ["1234"])
        self.assertEqual(form["codetype"], ["5000"])
        self.assertEqual(result["pic_str"], "18")

    def test_report_recognition_error_posts_picture_id_for_refund(self):
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response({"err_no": 0, "err_str": "OK"})

        environment = {
            "DARKWEB_CHAOJIYING_USER": "test-user",
            "DARKWEB_CHAOJIYING_PASS2": "0" * 32,
            "DARKWEB_CHAOJIYING_SOFT_ID": "1234",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "darkweb_collector.chaojiying.urlopen",
            side_effect=fake_urlopen,
        ):
            result = report_recognition_error("pic-refund-1")

        form = parse_qs(captured["request"].data.decode("ascii"))
        self.assertEqual(captured["request"].full_url, "https://upload.chaojiying.net/Upload/ReportError.php")
        self.assertEqual(captured["timeout"], 60)
        self.assertEqual(form["user"], ["test-user"])
        self.assertEqual(form["pass2"], ["0" * 32])
        self.assertEqual(form["softid"], ["1234"])
        self.assertEqual(form["id"], ["pic-refund-1"])
        self.assertEqual(result, {"reported": True})

    def test_recognize_captcha_defaults_to_changan_mixed_character_code_type(self):
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            return _Response({"err_no": 0, "pic_id": "pic-0", "pic_str": "a1b2c3"})

        environment = {
            "DARKWEB_CHAOJIYING_USER": "test-user",
            "DARKWEB_CHAOJIYING_PASS2": "0" * 32,
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "darkweb_collector.chaojiying.urlopen",
            side_effect=fake_urlopen,
        ):
            recognize_captcha(b"png-bytes")

        form = parse_qs(captured["request"].data.decode("ascii"))
        self.assertEqual(form["codetype"], ["5000"])

    def test_recognize_captcha_posts_base64_and_hashes_plaintext_password(self):
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return _Response(
                {
                    "err_no": 0,
                    "err_str": "OK",
                    "pic_id": "pic-1",
                    "pic_str": "8vka",
                    "md5": "response-md5",
                }
            )

        environment = {
            "DARKWEB_CHAOJIYING_USER": "test-user",
            "DARKWEB_CHAOJIYING_PASSWORD": "test-password",
            "DARKWEB_CHAOJIYING_SOFT_ID": "1234",
            "DARKWEB_CHAOJIYING_CODE_TYPE": "1004",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "darkweb_collector.chaojiying.urlopen",
            side_effect=fake_urlopen,
        ):
            result = recognize_captcha(b"png-bytes")

        form = parse_qs(captured["request"].data.decode("ascii"))
        self.assertEqual(captured["request"].full_url, "https://upload.chaojiying.net/Upload/Processing.php")
        self.assertEqual(captured["timeout"], 60)
        self.assertEqual(form["user"], ["test-user"])
        self.assertEqual(form["pass2"], [hashlib.md5(b"test-password").hexdigest()])  # noqa: S324
        self.assertNotIn("pass", form)
        self.assertEqual(form["softid"], ["1234"])
        self.assertEqual(form["codetype"], ["1004"])
        self.assertEqual(form["file_base64"], ["cG5nLWJ5dGVz"])
        self.assertEqual(result["pic_id"], "pic-1")
        self.assertEqual(result["pic_str"], "8vka")

    def test_recognize_captcha_surfaces_provider_error_without_credentials(self):
        environment = {
            "DARKWEB_CHAOJIYING_USER": "private-user",
            "DARKWEB_CHAOJIYING_PASS2": "0" * 32,
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "darkweb_collector.chaojiying.urlopen",
            return_value=_Response({"err_no": -1005, "err_str": "无可用题分"}),
        ):
            with self.assertRaisesRegex(ChaojiyingError, "无可用题分") as raised:
                recognize_captcha(b"png-bytes")

        self.assertNotIn("private-user", str(raised.exception))
        self.assertNotIn("0" * 32, str(raised.exception))


class _Locator:
    def __init__(self, *, screenshot: bytes | None = None) -> None:
        self._screenshot = screenshot
        self.filled = ""

    def is_visible(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def screenshot(self, *, type: str) -> bytes:
        self.screenshot_type = type
        return self._screenshot or b""

    def fill(self, value: str) -> None:
        self.filled = value


class _LocatorList:
    def __init__(self, items: list[_Locator]) -> None:
        self.items = items

    def count(self) -> int:
        return len(self.items)

    def nth(self, index: int) -> _Locator:
        return self.items[index]


class _Page:
    def __init__(self, image: _Locator, captcha_input: _Locator) -> None:
        self.image = image
        self.captcha_input = captcha_input

    def locator(self, selector: str) -> _LocatorList:
        if selector == remote_browser_sessions.CAPTCHA_IMAGE_SELECTORS[0]:
            return _LocatorList([self.image])
        if selector == remote_browser_sessions.CAPTCHA_INPUT_SELECTORS[0]:
            return _LocatorList([self.captcha_input])
        return _LocatorList([])


class RemoteCaptchaFillTests(unittest.TestCase):
    def test_solve_captcha_screenshots_image_and_fills_result(self):
        image = _Locator(screenshot=b"captcha-png")
        captcha_input = _Locator()
        page = _Page(image, captcha_input)

        with patch.object(
            remote_browser_sessions,
            "recognize_captcha",
            return_value={"pic_id": "pic-2", "pic_str": "ab12"},
        ) as recognize:
            result = remote_browser_sessions._solve_captcha(page)

        recognize.assert_called_once_with(b"captcha-png")
        self.assertEqual(captcha_input.filled, "ab12")
        self.assertEqual(result, {"captcha_filled": True, "pic_id": "pic-2"})

    def test_report_captcha_error_marks_picture_as_reported(self):
        session = SimpleNamespace(last_captcha_pic_id="pic-2", last_captcha_reported=False)

        with patch.object(
            remote_browser_sessions,
            "report_recognition_error",
            return_value={"reported": True},
        ) as report, patch.object(
            remote_browser_sessions,
            "_state_payload",
            return_value={"captcha_error_report_available": False},
        ):
            result = remote_browser_sessions._apply_remote_action(
                session,
                object(),
                {"action": "report_captcha_error"},
            )

        report.assert_called_once_with("pic-2")
        self.assertTrue(session.last_captcha_reported)
        self.assertEqual(result["action_result"], {"reported": True})

        with self.assertRaisesRegex(ValueError, "no unreported captcha"):
            remote_browser_sessions._apply_remote_action(
                session,
                object(),
                {"action": "report_captcha_error"},
            )


if __name__ == "__main__":
    unittest.main()
