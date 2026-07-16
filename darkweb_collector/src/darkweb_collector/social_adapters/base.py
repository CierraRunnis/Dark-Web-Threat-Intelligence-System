from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from darkweb_collector.social_secrets import get_social_secret


class SocialAdapterError(RuntimeError):
    """A platform API request failed; callers must retain the last good cursor."""


@dataclass(frozen=True)
class SocialPost:
    platform: str
    platform_post_id: str
    source_url: str
    original_text: str
    published_at: str
    author: str = ""
    title: str = ""
    collected_at: str = ""
    media_urls: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = "\n".join((self.title.strip(), self.original_text.strip()))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "platform_post_id": self.platform_post_id,
            "source_url": self.source_url,
            "original_text": self.original_text,
            "title": self.title,
            "published_at": self.published_at,
            "author": self.author,
            "collected_at": self.collected_at,
            "media_urls": list(self.media_urls),
            "metadata": dict(self.metadata),
            "is_deleted": bool(self.metadata.get("deleted")),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class CoverageStatus:
    mode: str
    configured: bool
    limited: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "configured": self.configured,
            "limited": self.limited,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CollectRequest:
    keywords: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    cursor: str | None = None
    since: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class CollectResult:
    posts: tuple[SocialPost, ...]
    next_cursor: str | None
    coverage: CoverageStatus


class JSONTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        ...


class UrllibJSONTransport:
    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        clean_params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
        target = f"{url}?{urlencode(clean_params)}" if clean_params else url
        request = Request(target, headers=dict(headers or {}), method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise SocialAdapterError(f"GET {url} failed: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise SocialAdapterError(f"GET {url} returned a non-object response")
        return payload


class SocialAdapter(Protocol):
    platform: str

    def coverage_status(self) -> CoverageStatus:
        ...

    def collect(self, request: CollectRequest) -> CollectResult:
        ...


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_timestamp(value: Any, *, default: str = "") -> str:
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return default
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def dedupe_posts(posts: list[SocialPost]) -> tuple[SocialPost, ...]:
    by_key: dict[tuple[str, str], SocialPost] = {}
    for post in posts:
        stable_id = post.platform_post_id.strip() or hashlib.sha256(post.source_url.encode("utf-8")).hexdigest()
        key = (post.platform, stable_id)
        existing = by_key.get(key)
        if existing is None or post.published_at > existing.published_at:
            by_key[key] = post
    return tuple(by_key.values())


def decode_cursor_map(cursor: str | None) -> dict[str, str]:
    if not cursor:
        return {}
    try:
        payload = json.loads(cursor)
    except (TypeError, ValueError):
        return {"__global__": str(cursor)}
    if not isinstance(payload, Mapping):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value not in (None, "")}


def encode_cursor_map(cursor_map: Mapping[str, Any]) -> str | None:
    clean = {str(key): str(value) for key, value in cursor_map.items() if value not in (None, "")}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True) if clean else None


def env_value(name: str) -> str:
    return get_social_secret(name)


def ensure_api_success(payload: Mapping[str, Any], platform: str) -> None:
    error = payload.get("error")
    errors = payload.get("errors")
    if error or errors:
        detail = error or errors
        raise SocialAdapterError(f"{platform} API returned an error: {detail}")


def quote_search_term(value: str) -> str:
    clean = " ".join(value.split())
    if not clean:
        return ""
    return f'"{clean}"' if " " in clean else clean
