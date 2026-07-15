from __future__ import annotations

import re
from typing import Any, Mapping

from .base import (
    CollectRequest,
    CollectResult,
    CoverageStatus,
    JSONTransport,
    SocialPost,
    UrllibJSONTransport,
    decode_cursor_map,
    dedupe_posts,
    encode_cursor_map,
    env_value,
    ensure_api_success,
    normalize_timestamp,
    utc_now_iso,
)


def _channel_identifier(source: str) -> str:
    clean = source.strip().rstrip("/")
    if "/channel/" in clean:
        clean = clean.split("/channel/", 1)[1].split("/", 1)[0]
    return clean if re.fullmatch(r"UC[A-Za-z0-9_-]{10,}", clean or "") else ""


class YouTubeAdapter:
    platform = "youtube"
    endpoint = "https://www.googleapis.com/youtube/v3/search"

    def __init__(self, transport: JSONTransport | None = None, api_key: str | None = None) -> None:
        self.transport = transport or UrllibJSONTransport()
        self.api_key = api_key if api_key is not None else (
            env_value("SOCIAL_YOUTUBE_API_KEY") or env_value("YOUTUBE_API_KEY")
        )

    def coverage_status(self) -> CoverageStatus:
        if self.api_key:
            return CoverageStatus(mode="api", configured=True)
        return CoverageStatus(
            mode="browser_fallback",
            configured=False,
            limited=True,
            reason="YOUTUBE_API_KEY is not configured; only authorized browser review is available",
        )

    def collect(self, request: CollectRequest) -> CollectResult:
        coverage = self.coverage_status()
        if not self.api_key:
            return CollectResult((), request.cursor, coverage)

        query = "|".join(item.strip() for item in request.keywords if item.strip())
        searches: list[tuple[str, str]] = []
        if query:
            searches.append(("__global__", ""))
        searches.extend(
            (source, channel)
            for source in request.sources
            for channel in (_channel_identifier(source),)
            if channel
        )
        if not searches:
            return CollectResult(
                (),
                request.cursor,
                CoverageStatus("api", True, True, "no YouTube keywords or channel sources are configured"),
            )

        cursors = decode_cursor_map(request.cursor)
        next_cursors = dict(cursors)
        posts: list[SocialPost] = []
        for cursor_key, channel_id in searches:
            payload = self.transport.get_json(
                self.endpoint,
                params={
                    "key": self.api_key,
                    "part": "snippet",
                    "type": "video",
                    "order": "date",
                    "maxResults": min(max(request.limit, 1), 50),
                    "q": query,
                    "channelId": channel_id,
                    "publishedAfter": cursors.get(cursor_key) or request.since,
                },
            )
            ensure_api_success(payload, "YouTube")
            search_posts = parse_youtube_payload(payload)
            posts.extend(search_posts)
            published = [post.published_at for post in search_posts if post.published_at]
            if published:
                next_cursors[cursor_key] = max(published)
        return CollectResult(dedupe_posts(posts), encode_cursor_map(next_cursors), coverage)


def parse_youtube_payload(payload: Mapping[str, Any], *, collected_at: str | None = None) -> list[SocialPost]:
    collected = collected_at or utc_now_iso()
    posts: list[SocialPost] = []
    for item in payload.get("items", []) or []:
        if not isinstance(item, Mapping):
            continue
        identifier = item.get("id") if isinstance(item.get("id"), Mapping) else {}
        video_id = str(identifier.get("videoId") or "")
        if not video_id:
            continue
        snippet = item.get("snippet") if isinstance(item.get("snippet"), Mapping) else {}
        thumbnails = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), Mapping) else {}
        thumbnail_urls = []
        for key in ("maxres", "standard", "high", "medium", "default"):
            thumbnail = thumbnails.get(key) if isinstance(thumbnails.get(key), Mapping) else {}
            if thumbnail.get("url"):
                thumbnail_urls.append(str(thumbnail["url"]))
                break
        posts.append(
            SocialPost(
                platform="youtube",
                platform_post_id=video_id,
                source_url=f"https://www.youtube.com/watch?v={video_id}",
                title=str(snippet.get("title") or ""),
                original_text=str(snippet.get("description") or ""),
                published_at=normalize_timestamp(snippet.get("publishedAt")),
                author=str(snippet.get("channelTitle") or snippet.get("channelId") or ""),
                collected_at=collected,
                media_urls=tuple(thumbnail_urls),
                metadata={"channel_id": str(snippet.get("channelId") or "")},
            )
        )
    return posts
