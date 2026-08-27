"""Per-site session cookie management for forum-type adapters.

Some forums (e.g. breached.st) gate every page behind a XenForo login. The
collector cannot use anonymous fetches, so each adapter resolves a session
cookie header out of the site's `extras` block and passes it through to the
HTTP fetch layer (`tor_fetch.fetch_url(..., cookie_header=...)`).

This module centralizes the resolve / read / write logic so:
- adapters share one resolver instead of duplicating env+file+inline lookup,
- the API layer can read the same status (configured / source / preview)
  without reaching into adapter internals.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from darkweb_collector.config import get_site_config, load_site_configs
from darkweb_collector.models import SiteConfig
from darkweb_collector.runtime import user_data_root


COOKIE_SOURCE_ENV = "env"
COOKIE_SOURCE_FILE = "file"
COOKIE_SOURCE_INLINE = "inline"
COOKIE_SOURCE_NONE = "none"


def _site_needs_cookie(config: SiteConfig) -> bool:
    extras = config.extras or {}
    return bool(
        extras.get("session_cookie_env")
        or extras.get("session_cookie_file")
        or extras.get("session_cookie")
    )


def _resolve_cookie_file_path(config: SiteConfig) -> Path | None:
    raw = (config.extras or {}).get("session_cookie_file")
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = (user_data_root() / path).resolve()
    return path


def _normalize_cookie_value(value: str) -> str:
    """Collapse whitespace inside a cookie header line.

    Browsers paste cookie strings with arbitrary surrounding whitespace; curl
    accepts any well-formed `name=value; name2=value2` line, so we just strip
    edges and squash internal newlines.
    """
    return " ".join(str(value or "").split())


def _mask_cookie(cookie: str) -> str:
    """Return a redacted preview safe to show in the UI.

    For each `name=value` pair we keep the name and the trailing 4 chars of
    the value; everything else becomes `*`. Empty input returns "".
    """
    cookie = _normalize_cookie_value(cookie)
    if not cookie:
        return ""
    parts: list[str] = []
    for token in cookie.split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            parts.append(token)
            continue
        name, value = token.split("=", 1)
        value = value.strip()
        if len(value) <= 6:
            masked = "*" * len(value)
        else:
            masked = "*" * (len(value) - 4) + value[-4:]
        parts.append(f"{name.strip()}={masked}")
    return "; ".join(parts)


def resolve_session_cookie(config: SiteConfig) -> str | None:
    """Return the live session cookie header for a site, or None.

    Lookup order: env var (`extras.session_cookie_env`) -> file
    (`extras.session_cookie_file`) -> inline (`extras.session_cookie`).
    """
    extras = config.extras or {}

    env_name = extras.get("session_cookie_env")
    if env_name:
        value = _normalize_cookie_value(os.environ.get(str(env_name), ""))
        if value:
            return value

    cookie_file = _resolve_cookie_file_path(config)
    if cookie_file and cookie_file.exists():
        value = _normalize_cookie_value(cookie_file.read_text(encoding="utf-8"))
        if value:
            return value

    inline = extras.get("session_cookie")
    if inline:
        value = _normalize_cookie_value(str(inline))
        if value:
            return value

    return None


def get_session_cookie_status(site_name: str) -> dict[str, Any]:
    """Return a UI-safe status dict for the given site.

    Never leaks the raw cookie value — only the masked preview.
    """
    config = get_site_config(site_name)
    extras = config.extras or {}
    cookie_file = _resolve_cookie_file_path(config)
    env_name = str(extras.get("session_cookie_env") or "")

    cookie = resolve_session_cookie(config)
    if cookie:
        if env_name and _normalize_cookie_value(os.environ.get(env_name, "")):
            source = COOKIE_SOURCE_ENV
        elif cookie_file and cookie_file.exists():
            source = COOKIE_SOURCE_FILE
        else:
            source = COOKIE_SOURCE_INLINE
    else:
        source = COOKIE_SOURCE_NONE

    updated_at = ""
    if source == COOKIE_SOURCE_FILE and cookie_file is not None:
        try:
            mtime = cookie_file.stat().st_mtime
            updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            updated_at = ""

    return {
        "site_name": config.site_name,
        "display_name": str(extras.get("display_name") or config.site_name),
        "configured": bool(cookie),
        "source": source,
        "masked_preview": _mask_cookie(cookie or ""),
        "cookie_file": str(cookie_file) if cookie_file else "",
        "cookie_file_exists": bool(cookie_file and cookie_file.exists()),
        "cookie_env": env_name,
        "env_set": bool(env_name and os.environ.get(env_name)),
        "updated_at": updated_at,
        # Engine + example are surfaced to the dashboard so the UI can render
        # site-appropriate hints/placeholders without hardcoding per-site logic.
        "cookie_engine": str(extras.get("session_cookie_engine") or ""),
        "cookie_example": str(extras.get("session_cookie_example") or ""),
    }


def list_cookie_capable_sites() -> list[dict[str, Any]]:
    """Return cookie status for every site that declares session_cookie_* extras.

    Used by the dashboard to render the multi-site cookie panel without
    hardcoding a per-site list on the frontend.
    """
    statuses: list[dict[str, Any]] = []
    for cfg in load_site_configs():
        if not _site_needs_cookie(cfg):
            continue
        try:
            statuses.append(get_session_cookie_status(cfg.site_name))
        except Exception as exc:  # pragma: no cover - defensive: one bad site shouldn't hide others
            statuses.append({
                "site_name": cfg.site_name,
                "display_name": str((cfg.extras or {}).get("display_name") or cfg.site_name),
                "configured": False,
                "source": COOKIE_SOURCE_NONE,
                "masked_preview": "",
                "cookie_file": "",
                "cookie_file_exists": False,
                "cookie_env": "",
                "env_set": False,
                "updated_at": "",
                "cookie_engine": "",
                "cookie_example": "",
                "error": str(exc),
            })
    return statuses


def set_session_cookie(site_name: str, cookie_value: str) -> dict[str, Any]:
    """Persist a session cookie for the site by writing to the configured file.

    Requires the site config to declare `extras.session_cookie_file`. The file
    is created with mode 600. Returns the updated status dict.
    """
    normalized = _normalize_cookie_value(cookie_value)
    if not normalized:
        raise RuntimeError("cookie value must not be empty")

    config = get_site_config(site_name)
    cookie_file = _resolve_cookie_file_path(config)
    if cookie_file is None:
        raise RuntimeError(
            f"site '{site_name}' has no session_cookie_file configured in sites.yaml extras"
        )

    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    cookie_file.write_text(normalized + "\n", encoding="utf-8")
    try:
        os.chmod(cookie_file, 0o600)
    except OSError:
        # Windows / non-POSIX filesystems silently ignore chmod; that's fine.
        pass

    return get_session_cookie_status(site_name)


def clear_session_cookie(site_name: str) -> dict[str, Any]:
    """Remove the persisted cookie file. Env-var cookies are not touched."""
    config = get_site_config(site_name)
    cookie_file = _resolve_cookie_file_path(config)
    if cookie_file is not None and cookie_file.exists():
        cookie_file.unlink()
    return get_session_cookie_status(site_name)
