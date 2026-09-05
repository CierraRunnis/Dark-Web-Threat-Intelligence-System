from __future__ import annotations

import hashlib
import hmac
import os
import time

from darkweb_collector.http_basic_auth import (
    http_basic_auth_password,
    http_basic_auth_realm,
    http_basic_auth_username,
)


BASIC_AUTH_COOKIE_NAME = "dwti_basic_gate"
BASIC_AUTH_TTL_ENV = "DARKWEB_BASIC_AUTH_TTL_SECONDS"


def http_basic_cookie_ttl_seconds() -> int:
    try:
        return min(7 * 24 * 60 * 60, max(60, int(os.environ.get(BASIC_AUTH_TTL_ENV, "43200"))))
    except ValueError:
        return 43200


def _cookie_signature(expires_at: int) -> str:
    message = (
        f"v1:{http_basic_auth_username()}:{expires_at}:{http_basic_auth_realm()}"
    ).encode("utf-8")
    return hmac.new(
        http_basic_auth_password().encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def issue_http_basic_gate_cookie(now: int | None = None) -> tuple[str, int]:
    ttl_seconds = http_basic_cookie_ttl_seconds()
    expires_at = int(now if now is not None else time.time()) + ttl_seconds
    return f"{expires_at}.{_cookie_signature(expires_at)}", ttl_seconds


def http_basic_gate_cookie_valid(value: str, now: int | None = None) -> bool:
    expires_text, separator, provided_signature = str(value or "").partition(".")
    if separator != "." or not expires_text.isdigit() or not provided_signature:
        return False
    expires_at = int(expires_text)
    current_time = int(now if now is not None else time.time())
    if expires_at < current_time:
        return False
    return hmac.compare_digest(provided_signature, _cookie_signature(expires_at))
