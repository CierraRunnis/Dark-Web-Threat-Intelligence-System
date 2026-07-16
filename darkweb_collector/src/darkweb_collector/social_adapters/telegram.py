from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from .base import (
    CollectRequest,
    CollectResult,
    CoverageStatus,
    SocialAdapterError,
    SocialPost,
    decode_cursor_map,
    dedupe_posts,
    encode_cursor_map,
    env_value,
    normalize_timestamp,
    utc_now_iso,
)


TelegramFetcher = Callable[[CollectRequest], tuple[list[Mapping[str, Any]], Mapping[str, Any]]]
TelegramClientFactory = Callable[[str, int, str], Any]


def telegram_source_identifier(source: str) -> str:
    clean = source.strip().rstrip("/")
    if not clean:
        return ""
    if clean.startswith("@"):
        clean = clean[1:]
    elif "://" in clean or clean.lower().startswith(("t.me/", "www.t.me/")):
        parsed = urlparse(clean if "://" in clean else f"https://{clean}")
        if parsed.netloc.lower() not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
            return ""
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0] == "s":
            parts = parts[1:]
        if not parts or parts[0].startswith("+") or parts[0].lower() == "joinchat":
            return ""
        clean = parts[0]
    return clean if re.fullmatch(r"[A-Za-z0-9_]{5,}", clean) else ""


def _global_cursor_key(term: str) -> str:
    digest = hashlib.sha256(term.casefold().encode("utf-8")).hexdigest()[:12]
    return f"__global__:{digest}"


class TelegramAdapter:
    platform = "telegram"

    def __init__(
        self,
        fetcher: TelegramFetcher | None = None,
        api_id: str | None = None,
        api_hash: str | None = None,
        session: str | None = None,
        client_factory: TelegramClientFactory | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.api_id = api_id if api_id is not None else (
            env_value("SOCIAL_TELEGRAM_API_ID") or env_value("TELEGRAM_API_ID")
        )
        self.api_hash = api_hash if api_hash is not None else (
            env_value("SOCIAL_TELEGRAM_API_HASH") or env_value("TELEGRAM_API_HASH")
        )
        self.session = session if session is not None else (
            env_value("SOCIAL_TELEGRAM_SESSION") or env_value("TELEGRAM_SESSION")
        )
        self.client_factory = client_factory

    def coverage_status(self) -> CoverageStatus:
        if self.fetcher or (self.api_id and self.api_hash and self.session):
            return CoverageStatus(
                mode="api",
                configured=True,
                limited=True,
                reason="Telegram collection is restricted to public broadcast channels and accessible global search",
            )
        return CoverageStatus(
            mode="browser_fallback",
            configured=False,
            limited=True,
            reason="Telegram API credentials/session are not configured; only authorized browser review is available",
        )

    def collect(self, request: CollectRequest) -> CollectResult:
        coverage = self.coverage_status()
        if not coverage.configured:
            return CollectResult((), request.cursor, coverage)
        fetcher = self.fetcher or self._telethon_fetch
        rows, cursor_map = fetcher(request)
        return CollectResult(
            dedupe_posts(parse_telegram_messages(rows)),
            encode_cursor_map(cursor_map) or request.cursor,
            coverage,
        )

    def _telethon_fetch(self, request: CollectRequest) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
        if self.client_factory is None:
            try:
                from telethon.sync import TelegramClient
                from telethon.sessions import StringSession
            except ImportError as exc:
                raise SocialAdapterError("telethon is required for Telegram API collection") from exc

            client_factory: TelegramClientFactory = (
                lambda session, api_id, api_hash: TelegramClient(StringSession(session), api_id, api_hash)
            )
        else:
            client_factory = self.client_factory

        cursors = decode_cursor_map(request.cursor)
        next_cursors = dict(cursors)
        rows: list[Mapping[str, Any]] = []
        terms = tuple(dict.fromkeys(item.strip() for item in request.keywords if item.strip()))
        client = None
        try:
            client = client_factory(self.session, int(self.api_id), self.api_hash)
            client.connect()
            if not client.is_user_authorized():
                raise SocialAdapterError("Telegram session is not authorized; generate a new StringSession")

            for term in terms:
                cursor_key = _global_cursor_key(term)
                after = normalize_timestamp(cursors.get(cursor_key) or request.since)
                latest = after
                for message in client.iter_messages(None, search=term, limit=max(request.limit, 1)):
                    row = _telegram_message_row(message)
                    if row is None or (after and row["date"] <= after):
                        continue
                    rows.append(row)
                    latest = max(latest, str(row["date"]))
                if latest:
                    next_cursors[cursor_key] = latest

            for target in request.sources:
                identifier = telegram_source_identifier(target)
                if not identifier:
                    continue
                entity = client.get_entity(identifier)
                if (
                    not bool(getattr(entity, "broadcast", False))
                    or bool(getattr(entity, "megagroup", False))
                    or not str(getattr(entity, "username", "") or "")
                ):
                    continue
                max_id = int(cursors.get(target, "0") or 0)
                for message in client.iter_messages(
                    entity,
                    search=None,
                    min_id=max_id,
                    limit=max(request.limit, 1),
                ):
                    row = _telegram_message_row(message)
                    if row is None:
                        continue
                    published = str(row["date"])
                    if request.since and published <= normalize_timestamp(request.since):
                        continue
                    rows.append(row)
                    max_id = max(max_id, int(row["id"]))
                if max_id:
                    next_cursors[target] = str(max_id)
        except SocialAdapterError:
            raise
        except Exception as exc:
            raise SocialAdapterError(f"Telegram API collection failed: {exc}") from exc
        finally:
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
        return rows, next_cursors


def _telegram_message_row(message: Any) -> Mapping[str, Any] | None:
    chat = getattr(message, "chat", None)
    username = str(getattr(chat, "username", "") or "")
    message_id = int(getattr(message, "id", 0) or 0)
    if (
        not message_id
        or not username
        or not bool(getattr(chat, "broadcast", False))
        or bool(getattr(chat, "megagroup", False))
    ):
        return None
    return {
        "id": message_id,
        "text": str(getattr(message, "message", "") or ""),
        "date": normalize_timestamp(getattr(message, "date", None)),
        "channel_id": str(getattr(chat, "id", "") or ""),
        "channel_title": str(getattr(chat, "title", "") or username),
        "username": username,
        "is_broadcast": True,
        "is_private": False,
    }


def parse_telegram_messages(rows: list[Mapping[str, Any]], *, collected_at: str | None = None) -> list[SocialPost]:
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in rows:
        if item.get("is_private") or not item.get("is_broadcast", True) or not item.get("id"):
            continue
        username = str(item.get("username") or "")
        if not username:
            continue
        channel_id = str(item.get("channel_id") or username)
        post_id = str(item["id"])
        if username:
            source_url = f"https://t.me/{username}/{post_id}"
        else:
            source_url = str(item.get("source_url") or "")
        posts.append(
            SocialPost(
                platform="telegram",
                platform_post_id=f"{channel_id}:{post_id}",
                source_url=source_url,
                original_text=str(item.get("text") or ""),
                published_at=normalize_timestamp(item.get("date")),
                author=str(item.get("channel_title") or username or channel_id),
                collected_at=collected,
                media_urls=tuple(str(url) for url in item.get("media_urls", []) or [] if url),
                metadata={"channel_id": channel_id, "message_id": post_id},
            )
        )
    return posts
