from __future__ import annotations

import base64
import binascii
import os
import secrets


BASIC_AUTH_ENABLED_ENV = "DARKWEB_BASIC_AUTH_ENABLED"
BASIC_AUTH_USERNAME_ENV = "DARKWEB_BASIC_AUTH_USERNAME"
BASIC_AUTH_PASSWORD_ENV = "DARKWEB_BASIC_AUTH_PASSWORD"
BASIC_AUTH_REALM_ENV = "DARKWEB_BASIC_AUTH_REALM"


def http_basic_auth_enabled() -> bool:
    return os.environ.get(BASIC_AUTH_ENABLED_ENV, "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def http_basic_auth_username() -> str:
    return (
        os.environ.get(BASIC_AUTH_USERNAME_ENV, "").strip()
        or os.environ.get("DARKWEB_AUTH_USERNAME", "").strip()
        or "admin"
    )


def http_basic_auth_password() -> str:
    return (
        os.environ.get(BASIC_AUTH_PASSWORD_ENV, "").strip()
        or os.environ.get("DARKWEB_AUTH_PASSWORD", "").strip()
    )


def http_basic_auth_realm() -> str:
    raw_realm = os.environ.get(
        BASIC_AUTH_REALM_ENV,
        "Dark Web Threat Intelligence",
    )
    return (
        raw_realm.replace("\\", "")
        .replace('"', "")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
        or "Restricted"
    )


def validate_http_basic_auth_config() -> None:
    if not http_basic_auth_enabled():
        return
    username = http_basic_auth_username()
    password = http_basic_auth_password()
    if not username or ":" in username or "\r" in username or "\n" in username:
        raise RuntimeError(
            f"{BASIC_AUTH_USERNAME_ENV} must be a non-empty HTTP Basic username without ':'"
        )
    if not password:
        raise RuntimeError(
            f"{BASIC_AUTH_ENABLED_ENV}=1 requires {BASIC_AUTH_PASSWORD_ENV}; "
            "no insecure default password is used"
        )


def decode_http_basic_authorization(authorization: str) -> tuple[str, str] | None:
    scheme, separator, encoded = str(authorization or "").partition(" ")
    if separator != " " or scheme.casefold() != "basic" or not encoded.strip():
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, separator, password = decoded.partition(":")
    if separator != ":":
        return None
    return username, password


def http_basic_authorization_valid(authorization: str) -> bool:
    provided = decode_http_basic_authorization(authorization)
    if provided is None:
        return False
    username, password = provided
    expected_username = http_basic_auth_username()
    expected_password = http_basic_auth_password()
    return bool(expected_password) and secrets.compare_digest(
        username,
        expected_username,
    ) and secrets.compare_digest(password, expected_password)


def http_basic_challenge_header() -> str:
    return f'Basic realm="{http_basic_auth_realm()}", charset="UTF-8"'
