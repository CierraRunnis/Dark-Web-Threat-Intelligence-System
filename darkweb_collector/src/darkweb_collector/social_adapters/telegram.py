from __future__ import annotations

from typing import Any, Callable, Mapping

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


class TelegramAdapter:
    platform = "telegram"

    def __init__(
        self,
        fetcher: TelegramFetcher | None = None,
        api_id: str | None = None,
        api_hash: str | None = None,
        session: str | None = None,
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
        try:
            from telethon.sync import TelegramClient
            from telethon.sessions import StringSession
        except ImportError as exc:
            raise SocialAdapterError("telethon is required for Telegram API collection") from exc

        cursors = decode_cursor_map(request.cursor)
        next_cursors = dict(cursors)
        rows: list[Mapping[str, Any]] = []
        terms = " ".join(item.strip() for item in request.keywords if item.strip())
        targets = list(request.sources) or ["__global__"]
        try:
            with TelegramClient(StringSession(self.session), int(self.api_id), self.api_hash) as client:
                for target in targets:
                    entity = None if target == "__global__" else client.get_entity(target)
                    if entity is not None and (not bool(getattr(entity, "broadcast", False)) or bool(getattr(entity, "megagroup", False))):
                        continue
                    messages = client.iter_messages(
                        entity,
                        search=terms or None,
                        min_id=int(cursors.get(target, "0") or 0) if entity is not None else 0,
                        limit=max(request.limit, 1),
                    )
                    max_id = int(cursors.get(target, "0") or 0)
                    for message in messages:
                        chat = getattr(message, "chat", None)
                        if not bool(getattr(chat, "broadcast", False)) or bool(getattr(chat, "megagroup", False)):
                            continue
                        published = normalize_timestamp(getattr(message, "date", None))
                        if request.since and published and published <= normalize_timestamp(request.since):
                            continue
                        message_id = int(getattr(message, "id", 0) or 0)
                        max_id = max(max_id, message_id)
                        username = str(getattr(chat, "username", "") or "")
                        rows.append(
                            {
                                "id": message_id,
                                "text": str(getattr(message, "message", "") or ""),
                                "date": published,
                                "channel_id": str(getattr(chat, "id", "") or ""),
                                "channel_title": str(getattr(chat, "title", "") or username),
                                "username": username,
                                "is_broadcast": True,
                                "is_private": False,
                            }
                        )
                    if entity is not None and max_id:
                        next_cursors[target] = str(max_id)
        except Exception as exc:
            raise SocialAdapterError(f"Telegram API collection failed: {exc}") from exc
        return rows, next_cursors


def parse_telegram_messages(rows: list[Mapping[str, Any]], *, collected_at: str | None = None) -> list[SocialPost]:
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in rows:
        if item.get("is_private") or not item.get("is_broadcast", True) or not item.get("id"):
            continue
        username = str(item.get("username") or "")
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
